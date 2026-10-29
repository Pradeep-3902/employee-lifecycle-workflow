
from __future__ import annotations

import json
from datetime import date

import pytest

from app import create_app
from database.db import connect
from generator.generate_data import generate_rows
from services.access_control import decide_access
from services.anomaly_detection import detect_exceptions
from services.workflow import (
    complete_exit_task,
    set_task_status,
    start_offboarding,
)
from validators.validate_data import validate_tables


def seed_database(path, employee_count=24):
    """Generate and insert deterministic synthetic data into the test database."""
    tables, truth = generate_rows(
        employee_count,
        seed=20261022,
        inject=True,
    )

    with connect(path) as connection:
        for table, rows in tables.items():
            if not rows:
                continue

            columns = list(rows[0])
            column_names = ", ".join(columns)
            placeholders = ", ".join("?" for _ in columns)

            sql = (
                f"INSERT INTO {table} "
                f"({column_names}) "
                f"VALUES ({placeholders})"
            )

            values = [
                tuple(row.get(column) for column in columns)
                for row in rows
            ]

            connection.executemany(sql, values)

    return tables, truth


@pytest.fixture
def workflow(tmp_path):
    """Create an authenticated test client with a seeded SQLite database."""
    database_path = tmp_path / "workflow.sqlite"

    app = create_app(
        {
            "TESTING": True,
            "DATABASE": str(database_path),
            "AUTO_SEED": False,
            "LOGIN_EMAIL": "ops@test.local",
            "DEMO_LOGIN_PASSWORD": "TestPass!2026",
        }
    )

    tables, truth = seed_database(database_path)
    client = app.test_client()

    client.post(
        "/login",
        data={
            "email": "ops@test.local",
            "password": "TestPass!2026",
        },
    )

    return client, database_path, tables, truth


def test_login_protects_dashboard_and_apis_and_logout_clears_session(
    tmp_path,
):
    app = create_app(
        {
            "TESTING": True,
            "DATABASE": str(tmp_path / "auth.sqlite"),
            "AUTO_SEED": False,
            "LOGIN_EMAIL": "ops@test.local",
            "DEMO_LOGIN_PASSWORD": "TestPass!2026",
        }
    )

    client = app.test_client()

    assert client.get("/").status_code == 302
    assert client.get("/api/summary").status_code == 401
    assert client.get("/api/health").status_code == 200

    bad_login = client.post(
        "/login",
        data={
            "email": "ops@test.local",
            "password": "wrong",
        },
    )
    assert b"not recognized" in bad_login.data

    good_login = client.post(
        "/login",
        data={
            "email": "ops@test.local",
            "password": "TestPass!2026",
        },
    )
    assert good_login.status_code == 302
    assert client.get("/").status_code == 200

    logout_response = client.post("/logout")
    assert logout_response.status_code == 302
    assert client.get("/").status_code == 302


def test_full_generator_volume_and_known_exceptions():
    tables, truth = generate_rows(
        500,
        seed=20261022,
    )

    report = validate_tables(tables, truth)

    assert report["status"] == "passed", report["errors"]
    assert len(tables["employees"]) == 500
    assert len(tables["departments"]) == 8
    assert len(tables["roles"]) == 12
    assert len(tables["managers"]) == 50

    assert len(
        [
            row
            for row in tables["task_instances"]
            if row["case_id"]
        ]
    ) == 4000

    assert len(tables["assets"]) == 600
    assert len(tables["access_requests"]) == 300
    assert len(truth) == 7

    assert {
        row["owner_team"]
        for row in tables["task_instances"]
    } == {"HR", "IT", "Facilities", "Manager"}


def test_seeded_generation_is_reproducible():
    first, first_truth = generate_rows(20, seed=77)
    second, second_truth = generate_rows(20, seed=77)

    assert json.dumps(
        (first, first_truth),
        sort_keys=True,
    ) == json.dumps(
        (second, second_truth),
        sort_keys=True,
    )


def test_clean_baseline_validates_without_ground_truth():
    tables, truth = generate_rows(
        500,
        seed=20261022,
        inject=False,
    )

    report = validate_tables(
        tables,
        truth,
        expect_anomalies=False,
    )

    assert report["status"] == "passed", report["errors"]
    assert truth == []


def test_anomaly_injection_rejects_too_small_dataset():
    with pytest.raises(ValueError, match="at least 9 employees"):
        generate_rows(
            8,
            seed=20261022,
            inject=True,
        )


def test_validator_reports_broken_dependency_fk_without_crashing():
    tables, truth = generate_rows(
        12,
        seed=20261022,
        inject=False,
    )

    tables["task_dependencies"].append(
        {
            "task_id": "MISSING-TASK",
            "depends_on_task_id": "ALSO-MISSING",
        }
    )

    report = validate_tables(
        tables,
        truth,
        expect_anomalies=False,
    )

    assert report["status"] == "failed"
    assert any(
        "invalid foreign key" in error
        for error in report["errors"]
    )


def test_clean_dataset_validates_without_expected_anomalies():
    tables, truth = generate_rows(
        500,
        seed=20261022,
        inject=False,
    )

    report = validate_tables(
        tables,
        truth,
        expect_anomalies=False,
    )

    assert report["status"] == "passed", report["errors"]
    assert truth == []


def test_completed_task_requires_its_prerequisite(workflow):
    _, database_path, tables, _ = workflow

    child = next(
        row
        for row in tables["task_instances"]
        if row["task_kind"] == "account_creation"
        and row["status"] != "completed"
        and row["owner_employee_id"] != "EMP-000001"
    )

    dependency = next(
        row
        for row in tables["task_dependencies"]
        if row["task_id"] == child["task_id"]
    )

    with connect(database_path) as connection:
        connection.execute(
            """
            UPDATE task_instances
            SET status = 'not_started', completed_date = NULL
            WHERE task_id = ?
            """,
            (dependency["depends_on_task_id"],),
        )

        connection.execute(
            """
            UPDATE task_instances
            SET status = 'not_started', completed_date = NULL
            WHERE task_id = ?
            """,
            (child["task_id"],),
        )

        with pytest.raises(ValueError, match="Prerequisites"):
            set_task_status(
                connection,
                child["task_id"],
                "completed",
            )


def test_task_completion_rejects_prerequisite_completed_later(workflow):
    _, database_path, tables, _ = workflow

    child = next(
        row
        for row in tables["task_instances"]
        if row["task_kind"] == "account_creation"
        and row["owner_employee_id"] != "EMP-000001"
        and row["status"] != "completed"
    )

    dependency = next(
        row
        for row in tables["task_dependencies"]
        if row["task_id"] == child["task_id"]
    )

    with connect(database_path) as connection:
        connection.execute(
            """
            UPDATE task_instances
            SET status = 'completed', completed_date = '2099-10-22'
            WHERE task_id = ?
            """,
            (dependency["depends_on_task_id"],),
        )

        connection.execute(
            """
            UPDATE task_instances
            SET status = 'in_progress', completed_date = NULL
            WHERE task_id = ?
            """,
            (child["task_id"],),
        )

        with pytest.raises(ValueError, match="Prerequisites"):
            set_task_status(
                connection,
                child["task_id"],
                "completed",
            )


def test_access_approval_requires_active_employee_and_manager(workflow):
    _, database_path, tables, _ = workflow

    pending_ids = {
        row["access_request_id"]
        for row in tables["approvals"]
        if row["decision"] == "pending"
    }

    request = next(
        row
        for row in tables["access_requests"]
        if row["access_request_id"] in pending_ids
    )

    employee = next(
        row
        for row in tables["employees"]
        if row["employee_id"] == request["employee_id"]
    )

    with connect(database_path) as connection:
        connection.execute(
            """
            UPDATE employees
            SET lifecycle_state = 'terminated'
            WHERE employee_id = ?
            """,
            (employee["employee_id"],),
        )

        manager_id = (
            employee["manager_id"]
            or tables["managers"][0]["manager_id"]
        )

        with pytest.raises(ValueError, match="terminated"):
            decide_access(
                connection,
                request["access_request_id"],
                "approved",
                manager_id,
            )

        connection.execute(
            """
            UPDATE employees
            SET lifecycle_state = 'active'
            WHERE employee_id = ?
            """,
            (employee["employee_id"],),
        )

        other_manager = next(
            row["manager_id"]
            for row in tables["managers"]
            if row["manager_id"] != employee["manager_id"]
        )

        with pytest.raises(ValueError, match="assigned manager"):
            decide_access(
                connection,
                request["access_request_id"],
                "approved",
                other_manager,
            )


def test_approved_request_provisions_access_and_audits_decision(workflow):
    _, database_path, tables, _ = workflow

    incomplete_case_ids = {
        row["case_id"]
        for row in tables["task_instances"]
        if row["task_kind"] == "access_provisioning"
        and row["status"] != "completed"
    }

    request = next(
        row
        for row in tables["access_requests"]
        if row["case_id"] in incomplete_case_ids
    )

    employee = next(
        row
        for row in tables["employees"]
        if row["employee_id"] == request["employee_id"]
    )

    manager_id = (
        employee["manager_id"]
        or tables["managers"][0]["manager_id"]
    )

    with connect(database_path) as connection:
        connection.execute(
            """
            UPDATE employees
            SET lifecycle_state = 'active', manager_id = ?
            WHERE employee_id = ?
            """,
            (manager_id, employee["employee_id"]),
        )

        connection.execute(
            """
            UPDATE access_requests
            SET status = 'pending', effective_from = NULL
            WHERE access_request_id = ?
            """,
            (request["access_request_id"],),
        )

        connection.execute(
            """
            UPDATE approvals
            SET decision = 'pending', decision_date = NULL
            WHERE access_request_id = ?
            """,
            (request["access_request_id"],),
        )

        case_tasks = {
            row["task_kind"]: row["task_id"]
            for row in connection.execute(
                """
                SELECT task_kind, task_id
                FROM task_instances
                WHERE case_id = ?
                """,
                (request["case_id"],),
            ).fetchall()
        }

        for task_kind in (
            "identity_verification",
            "manager_approval",
            "account_creation",
        ):
            task_id = case_tasks[task_kind]

            task = connection.execute(
                "SELECT status FROM task_instances WHERE task_id = ?",
                (task_id,),
            ).fetchone()

            if task["status"] == "completed":
                continue

            if task["status"] == "blocked":
                connection.execute(
                    """
                    UPDATE task_instances
                    SET status = 'not_started', completed_date = NULL
                    WHERE task_id = ?
                    """,
                    (task_id,),
                )

            current_status = connection.execute(
                "SELECT status FROM task_instances WHERE task_id = ?",
                (task_id,),
            ).fetchone()["status"]

            if current_status == "not_started":
                set_task_status(
                    connection,
                    task_id,
                    "in_progress",
                )

            set_task_status(
                connection,
                task_id,
                "completed",
            )

        decide_access(
            connection,
            request["access_request_id"],
            "approved",
            manager_id,
        )

        state = connection.execute(
            """
            SELECT status
            FROM access_requests
            WHERE access_request_id = ?
            """,
            (request["access_request_id"],),
        ).fetchone()[0]

        assert state == "pending"

        provisioning = connection.execute(
            """
            SELECT task_id
            FROM task_instances
            WHERE case_id = ? AND task_kind = 'access_provisioning'
            """,
            (request["case_id"],),
        ).fetchone()

        provisioning_state = connection.execute(
            "SELECT status FROM task_instances WHERE task_id = ?",
            (provisioning["task_id"],),
        ).fetchone()[0]

        if provisioning_state == "blocked":
            connection.execute(
                """
                UPDATE task_instances
                SET status = 'not_started', completed_date = NULL
                WHERE task_id = ?
                """,
                (provisioning["task_id"],),
            )

        set_task_status(
            connection,
            provisioning["task_id"],
            "completed",
        )

        state = connection.execute(
            """
            SELECT status
            FROM access_requests
            WHERE access_request_id = ?
            """,
            (request["access_request_id"],),
        ).fetchone()[0]

        events = {
            row[0]
            for row in connection.execute(
                """
                SELECT event_type
                FROM audit_events
                WHERE entity_id = ?
                """,
                (request["access_request_id"],),
            ).fetchall()
        }

        assert state == "active"
        assert {"access_approved", "access_provisioned"}.issubset(events)


def test_offboarding_revokes_access_and_closes_after_exit_tasks(workflow):
    _, database_path, tables, _ = workflow

    assigned_employees = {
        row["employee_id"]
        for row in tables["asset_assignments"]
        if row["recovered_date"] is None
    }

    request_employee_ids = {
        row["employee_id"]
        for row in tables["access_requests"]
    }

    employee = next(
        row
        for row in tables["employees"]
        if row["lifecycle_state"] == "active"
        and row["employee_id"] not in assigned_employees
        and row["employee_id"] in request_employee_ids
        and row["start_date"] <= date.today().isoformat()
    )

    with connect(database_path) as connection:
        request = next(
            row
            for row in tables["access_requests"]
            if row["employee_id"] == employee["employee_id"]
        )

        connection.execute(
            """
            UPDATE access_requests
            SET status = 'active', effective_from = DATE('now')
            WHERE access_request_id = ?
            """,
            (request["access_request_id"],),
        )

        connection.execute(
            """
            UPDATE approvals
            SET decision = 'approved', decision_date = DATE('now')
            WHERE access_request_id = ?
            """,
            (request["access_request_id"],),
        )

        case_id = start_offboarding(
            connection,
            employee["employee_id"],
        )

        active_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM access_requests
            WHERE employee_id = ? AND status = 'active'
            """,
            (employee["employee_id"],),
        ).fetchone()[0]

        assert active_count == 0

        tasks = connection.execute(
            """
            SELECT task_id
            FROM task_instances
            WHERE offboarding_case_id = ?
            ORDER BY task_kind
            """,
            (case_id,),
        ).fetchall()

        assert len(tasks) == 2

        for task in tasks:
            complete_exit_task(connection, task["task_id"])

        status = connection.execute(
            """
            SELECT status
            FROM offboarding_cases
            WHERE offboarding_case_id = ?
            """,
            (case_id,),
        ).fetchone()[0]

        assert status == "completed"

        audit_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM audit_events
            WHERE employee_id = ?
            """,
            (employee["employee_id"],),
        ).fetchone()[0]

        assert audit_count > 0


def test_offboarding_is_idempotent_and_cancels_pending_access(workflow):
    _, database_path, tables, _ = workflow

    employees_by_id = {
        row["employee_id"]: row
        for row in tables["employees"]
    }
    request_employee_ids = {
        row["employee_id"]
        for row in tables["access_requests"]
    }
    employee = next(
        row
        for row in tables["employees"]
        if row["lifecycle_state"] == "active"
        and row["start_date"] <= date.today().isoformat()
        and row["employee_id"] in request_employee_ids
    )
    request = next(
        row
        for row in tables["access_requests"]
        if row["employee_id"] == employee["employee_id"]
    )

    with connect(database_path) as connection:
        # Arrange a pending access request for a valid, already-started
        # employee. The generator's random sample may otherwise assign every
        # pending request to preboarding employees in a small test dataset.
        connection.execute(
            """
            UPDATE access_requests
            SET status = 'pending', effective_from = NULL, effective_to = NULL
            WHERE access_request_id = ?
            """,
            (request["access_request_id"],),
        )
        connection.execute(
            """
            UPDATE approvals
            SET decision = 'pending', decision_date = NULL,
                effective_from = NULL, effective_to = NULL
            WHERE access_request_id = ?
            """,
            (request["access_request_id"],),
        )

        first_case = start_offboarding(
            connection,
            request["employee_id"],
        )

        second_case = start_offboarding(
            connection,
            request["employee_id"],
        )

        assert first_case == second_case

        access_state = connection.execute(
            """
            SELECT status
            FROM access_requests
            WHERE access_request_id = ?
            """,
            (request["access_request_id"],),
        ).fetchone()[0]

        approval_state = connection.execute(
            """
            SELECT decision
            FROM approvals
            WHERE access_request_id = ?
            """,
            (request["access_request_id"],),
        ).fetchone()[0]

        assert access_state == "rejected"
        assert approval_state == "rejected"


def test_repeated_exit_task_completion_is_idempotent(workflow):
    _, database_path, tables, _ = workflow

    assigned_employees = {
        row["employee_id"]
        for row in tables["asset_assignments"]
        if row["recovered_date"] is None
    }

    employee = next(
        row
        for row in tables["employees"]
        if row["lifecycle_state"] == "active"
        and row["employee_id"] not in assigned_employees
    )

    with connect(database_path) as connection:
        case_id = start_offboarding(
            connection,
            employee["employee_id"],
        )

        task_id = connection.execute(
            """
            SELECT task_id
            FROM task_instances
            WHERE offboarding_case_id = ?
              AND task_kind = 'recover_assets'
            """,
            (case_id,),
        ).fetchone()[0]

        complete_exit_task(connection, task_id)

        event_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM audit_events
            WHERE entity_type = 'AssetAssignment'
              AND event_type = 'asset_recovered'
              AND employee_id = ?
            """,
            (employee["employee_id"],),
        ).fetchone()[0]

        complete_exit_task(connection, task_id)

        repeated_event_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM audit_events
            WHERE entity_type = 'AssetAssignment'
              AND event_type = 'asset_recovered'
              AND employee_id = ?
            """,
            (employee["employee_id"],),
        ).fetchone()[0]

        assert repeated_event_count == event_count


def test_duplicate_asset_recovery_is_blocked_without_hiding_conflict(workflow):
    _, database_path, tables, _ = workflow

    duplicate = next(
        row
        for row in tables["asset_assignments"]
        if any(
            other["asset_id"] == row["asset_id"]
            and other["employee_id"] != row["employee_id"]
            and other["recovered_date"] is None
            for other in tables["asset_assignments"]
        )
    )

    other_owner = next(
        row
        for row in tables["asset_assignments"]
        if row["asset_id"] == duplicate["asset_id"]
        and row["employee_id"] != duplicate["employee_id"]
        and row["recovered_date"] is None
    )

    with connect(database_path) as connection:
        case_id = start_offboarding(
            connection,
            other_owner["employee_id"],
        )

        recovery_task = connection.execute(
            """
            SELECT task_id
            FROM task_instances
            WHERE offboarding_case_id = ?
              AND task_kind = 'recover_assets'
            """,
            (case_id,),
        ).fetchone()[0]

        with pytest.raises(
            ValueError,
            match="conflicting active assignment",
        ):
            complete_exit_task(connection, recovery_task)

        active_owner_count = connection.execute(
            """
            SELECT COUNT(DISTINCT employee_id)
            FROM asset_assignments
            WHERE asset_id = ? AND recovered_date IS NULL
            """,
            (duplicate["asset_id"],),
        ).fetchone()[0]

        assert active_owner_count == 2


def test_rejecting_approval_from_unassigned_manager(workflow):
    _, database_path, tables, _ = workflow

    request = next(
        row
        for row in tables["access_requests"]
        if next(
            approval
            for approval in tables["approvals"]
            if approval["access_request_id"] == row["access_request_id"]
        )["decision"] == "pending"
    )

    employee = next(
        row
        for row in tables["employees"]
        if row["employee_id"] == request["employee_id"]
    )

    other_manager = next(
        row["manager_id"]
        for row in tables["managers"]
        if row["manager_id"] != employee["manager_id"]
    )

    with connect(database_path) as connection:
        with pytest.raises(ValueError, match="assigned manager"):
            decide_access(
                connection,
                request["access_request_id"],
                "approved",
                other_manager,
            )


def test_dashboard_and_api_routes(workflow):
    client, database_path, _, _ = workflow

    assert client.get("/").status_code == 200

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json["status"] == "ok"

    summary = client.get("/api/summary")
    assert summary.status_code == 200
    assert summary.json["employees"] == 24

    overview = client.get("/api/dashboard-overview")
    assert overview.status_code == 200
    assert overview.json["run_breakdown"]["completed"] >= 0

    employees = client.get("/api/employees")
    assert employees.status_code == 200
    assert len(employees.json) == 24

    assert client.get("/api/runs").status_code == 200
    assert client.get("/api/assets").status_code == 200
    assert client.get("/api/audit").status_code == 200
    assert client.get("/api/tasks").status_code == 200
    assert client.get("/api/access").status_code == 200

    assert client.get("/api/export/invalid.csv").status_code == 404

    with connect(database_path) as connection:
        detected = detect_exceptions(connection)

    expected_issues = {
        "task_before_prerequisite",
        "manager_missing",
        "asset_assigned_twice",
        "start_before_background_check",
        "offboarding_active_access",
        "overdue_task",
        "department_changed_mid_process",
    }

    detected_issue_types = {
        row["issue_type"]
        for row in detected
    }

    assert expected_issues.issubset(detected_issue_types)
    assert all("ground_truth" not in row for row in detected)


def test_access_api_requires_approval_and_provisioning_before_active(workflow):
    client, database_path, tables, _ = workflow

    request = next(
        row
        for row in tables["access_requests"]
        if next(
            task
            for task in tables["task_instances"]
            if task["case_id"] == row["case_id"]
            and task["task_kind"] == "access_provisioning"
        )["status"] != "completed"
    )

    employee = next(
        row
        for row in tables["employees"]
        if row["employee_id"] == request["employee_id"]
    )

    manager_id = (
        employee["manager_id"]
        or tables["managers"][0]["manager_id"]
    )

    with connect(database_path) as connection:
        connection.execute(
            """
            UPDATE employees
            SET lifecycle_state = 'active', manager_id = ?
            WHERE employee_id = ?
            """,
            (manager_id, employee["employee_id"]),
        )

        connection.execute(
            """
            UPDATE access_requests
            SET status = 'pending', effective_from = NULL
            WHERE access_request_id = ?
            """,
            (request["access_request_id"],),
        )

        connection.execute(
            """
            UPDATE approvals
            SET decision = 'pending', decision_date = NULL
            WHERE access_request_id = ?
            """,
            (request["access_request_id"],),
        )

        connection.execute(
            """
            UPDATE task_instances
            SET status = 'not_started', completed_date = NULL
            WHERE case_id = ? AND task_kind = 'access_provisioning'
            """,
            (request["case_id"],),
        )

    approval_response = client.post(
        f"/api/access/{request['access_request_id']}/decision",
        json={
            "decision": "approved",
            "approver_manager_id": manager_id,
        },
    )

    assert approval_response.status_code == 200

    with connect(database_path) as connection:
        state = connection.execute(
            """
            SELECT status
            FROM access_requests
            WHERE access_request_id = ?
            """,
            (request["access_request_id"],),
        ).fetchone()[0]

        assert state == "pending"

        task_id = connection.execute(
            """
            SELECT task_id
            FROM task_instances
            WHERE case_id = ? AND task_kind = 'access_provisioning'
            """,
            (request["case_id"],),
        ).fetchone()[0]

        prerequisite_ids = [
            row[0]
            for row in connection.execute(
                """
                SELECT depends_on_task_id
                FROM task_dependencies
                WHERE task_id = ?
                """,
                (task_id,),
            ).fetchall()
        ]

        connection.executemany(
            """
            UPDATE task_instances
            SET status = 'completed', completed_date = DATE('now')
            WHERE task_id = ?
            """,
            [(prerequisite_id,) for prerequisite_id in prerequisite_ids],
        )

    complete_response = client.post(
        f"/api/tasks/{task_id}/status",
        json={"status": "completed"},
    )

    assert complete_response.status_code == 200

    with connect(database_path) as connection:
        state = connection.execute(
            """
            SELECT status
            FROM access_requests
            WHERE access_request_id = ?
            """,
            (request["access_request_id"],),
        ).fetchone()[0]

        assert state == "active"
