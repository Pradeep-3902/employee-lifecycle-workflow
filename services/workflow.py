
"""Transactional task, approval, and offboarding operations."""

from __future__ import annotations

from datetime import date, timedelta

from services.access_control import revoke_employee_access
from services.audit import record_event


EXIT_TASK_OWNERS = {
    "revoke_access": "IT",
    "recover_assets": "Facilities",
}

VALID_TASK_STATUSES = {
    "not_started",
    "in_progress",
    "completed",
    "blocked",
}

ALLOWED_TRANSITIONS = {
    "not_started": {"in_progress", "blocked", "completed"},
    "in_progress": {"not_started", "blocked", "completed"},
    "blocked": {"not_started", "in_progress"},
}


def _get_task(connection, task_id: str):
    """Retrieve a task or raise an error."""
    task = connection.execute(
        "SELECT * FROM task_instances WHERE task_id = ?",
        (task_id,),
    ).fetchone()

    if task is None:
        raise LookupError("Task not found")

    return task


def _validate_task_case(connection, task) -> None:
    """Ensure an onboarding task does not belong to a cancelled case."""
    if task["case_id"]:
        case = connection.execute(
            "SELECT status FROM onboarding_cases WHERE case_id = ?",
            (task["case_id"],),
        ).fetchone()

        if case is None:
            raise LookupError("Onboarding case not found")

        if case["status"] == "cancelled":
            raise ValueError(
                "Cannot update a task from a cancelled onboarding case"
            )


def _validate_prerequisites(connection, task_id: str) -> None:
    """Ensure every prerequisite has been completed on or before today."""
    prerequisites = connection.execute(
        """
        SELECT
            parent.task_id,
            parent.task_kind,
            parent.status,
            parent.completed_date
        FROM task_dependencies AS dependency
        JOIN task_instances AS parent
          ON parent.task_id = dependency.depends_on_task_id
        WHERE dependency.task_id = ?
        """,
        (task_id,),
    ).fetchall()

    today = date.today()

    incomplete = []

    for prerequisite in prerequisites:
        completed_date = prerequisite["completed_date"]

        valid_completion = (
            prerequisite["status"] == "completed"
            and completed_date is not None
        )

        if valid_completion:
            try:
                valid_completion = date.fromisoformat(
                    completed_date
                ) <= today
            except (TypeError, ValueError):
                valid_completion = False

        if not valid_completion:
            incomplete.append(prerequisite["task_kind"])

    if incomplete:
        raise ValueError(
            "Prerequisites are not complete: "
            + ", ".join(sorted(incomplete))
        )


def set_task_status(connection, task_id: str, status: str) -> None:
    """
    Change a task's status and write corresponding audit events.

    The caller owns the database transaction and must commit or roll it back.
    """
    if status not in VALID_TASK_STATUSES:
        raise ValueError("Unsupported task status")

    task = _get_task(connection, task_id)
    _validate_task_case(connection, task)

    current_status = task["status"]

    if current_status == "completed":
        if status == "completed":
            return
        raise ValueError("Completed tasks cannot be reopened")

    if status not in ALLOWED_TRANSITIONS.get(current_status, set()):
        raise ValueError(
            f"Invalid task transition: {current_status} -> {status}"
        )

    if status == "completed":
        if current_status == "blocked":
            raise ValueError(
                "Blocked tasks must be unblocked before completion"
            )

        _validate_prerequisites(connection, task_id)

    today = date.today()
    today_text = today.isoformat()

    if status == "completed":
        completed_date = today_text
        due_date = task["due_date"]

        breached = int(
            due_date is not None
            and date.fromisoformat(due_date) < today
        )
    else:
        completed_date = None
        due_date = task["due_date"]

        breached = int(
            due_date is not None
            and date.fromisoformat(due_date) < today
        )

    connection.execute(
        """
        UPDATE task_instances
        SET status = ?,
            completed_date = ?,
            sla_breached = ?
        WHERE task_id = ?
        """,
        (status, completed_date, breached, task_id),
    )

    record_event(
        connection,
        task["owner_employee_id"],
        "task_status_changed",
        "TaskInstance",
        task_id,
        current_status,
        status,
    )

    if status == "completed":
        record_event(
            connection,
            task["owner_employee_id"],
            "task_completed",
            "TaskInstance",
            task_id,
            current_status,
            status,
        )

    # Provision approved access only after provisioning is completed.
    if status == "completed" and task["task_kind"] == "access_provisioning":
        approved_requests = connection.execute(
            """
            SELECT a.access_request_id, a.employee_id
            FROM access_requests AS a
            JOIN approvals AS p
              ON p.access_request_id = a.access_request_id
            JOIN employees AS e
              ON e.employee_id = a.employee_id
            WHERE a.case_id = ?
              AND a.status = 'pending'
              AND p.decision = 'approved'
              AND e.lifecycle_state <> 'terminated'
            """,
            (task["case_id"],),
        ).fetchall()

        for request in approved_requests:
            connection.execute(
                """
                UPDATE access_requests
                SET status = 'active',
                    effective_from = DATE('now'),
                    effective_to = NULL
                WHERE access_request_id = ?
                  AND status = 'pending'
                """,
                (request["access_request_id"],),
            )

            record_event(
                connection,
                request["employee_id"],
                "access_provisioned",
                "AccessRequest",
                request["access_request_id"],
                "pending",
                "active",
            )

    # Close onboarding only when all tasks in the case are complete.
    if status == "completed" and task["case_id"]:
        remaining = connection.execute(
            """
            SELECT COUNT(*)
            FROM task_instances
            WHERE case_id = ?
              AND status <> 'completed'
            """,
            (task["case_id"],),
        ).fetchone()[0]

        if remaining == 0:
            connection.execute(
                """
                UPDATE onboarding_cases
                SET status = 'completed',
                    effective_to = DATE('now')
                WHERE case_id = ?
                  AND status <> 'cancelled'
                """,
                (task["case_id"],),
            )


def start_offboarding(connection, employee_id: str) -> str:
    """
    Start offboarding, create exit tasks, and revoke employee access.

    Returns the existing offboarding case ID if one already exists.
    The caller must execute this operation within a database transaction.
    """
    employee = connection.execute(
        "SELECT * FROM employees WHERE employee_id = ?",
        (employee_id,),
    ).fetchone()

    if employee is None:
        raise LookupError("Employee not found")

    existing = connection.execute(
        """
        SELECT offboarding_case_id
        FROM offboarding_cases
        WHERE employee_id = ?
        """,
        (employee_id,),
    ).fetchone()

    if existing is not None:
        return existing["offboarding_case_id"]

    if employee["lifecycle_state"] == "terminated":
        raise ValueError(
            "Employee is already terminated but has no offboarding case"
        )

    opened = date.today()

    if date.fromisoformat(employee["start_date"]) > opened:
        raise ValueError(
            "Cannot offboard an employee before their start date"
        )

    sequence = connection.execute(
        """
        SELECT COUNT(*)
        FROM offboarding_cases
        WHERE offboarding_case_id LIKE ?
        """,
        (f"OFF-{opened.year}-%",),
    ).fetchone()[0] + 1

    case_id = f"OFF-{opened.year}-{sequence:06d}"

    connection.execute(
        """
        UPDATE employees
        SET lifecycle_state = 'terminated',
            effective_to = ?
        WHERE employee_id = ?
        """,
        (opened.isoformat(), employee_id),
    )

    connection.execute(
        """
        INSERT INTO offboarding_cases (
            offboarding_case_id,
            employee_id,
            opened_date,
            status,
            effective_from,
            effective_to
        )
        VALUES (?, ?, ?, 'open', ?, NULL)
        """,
        (
            case_id,
            employee_id,
            opened.isoformat(),
            opened.isoformat(),
        ),
    )

    due_date = (opened + timedelta(days=1)).isoformat()

    for position, task_kind in enumerate(
        ("revoke_access", "recover_assets"),
        start=1,
    ):
        task_id = f"TASK-OFF-{case_id}-{position:03d}"

        connection.execute(
            """
            INSERT INTO task_instances (
                task_id,
                case_id,
                offboarding_case_id,
                template_id,
                task_kind,
                owner_team,
                owner_employee_id,
                status,
                created_date,
                due_date,
                completed_date,
                sla_breached
            )
            VALUES (?, NULL, ?, NULL, ?, ?, ?, 'not_started', ?, ?, NULL, 0)
            """,
            (
                task_id,
                case_id,
                task_kind,
                EXIT_TASK_OWNERS[task_kind],
                employee_id,
                opened.isoformat(),
                due_date,
            ),
        )

    # Revoke grants immediately when offboarding begins.
    revoke_employee_access(connection, employee_id)

    record_event(
        connection,
        employee_id,
        "offboarding_started",
        "OffboardingCase",
        case_id,
        employee["lifecycle_state"],
        "open",
    )

    return case_id


def complete_exit_task(connection, task_id: str) -> None:
    """Complete an exit task after its operational checks pass."""
    task = connection.execute(
        """
        SELECT *
        FROM task_instances
        WHERE task_id = ?
          AND offboarding_case_id IS NOT NULL
        """,
        (task_id,),
    ).fetchone()

    if task is None:
        raise LookupError("Offboarding task not found")

    task_kind = task["task_kind"]

    if task_kind not in EXIT_TASK_OWNERS:
        raise ValueError(
            f"Unsupported offboarding task type: {task_kind}"
        )

    if task["status"] == "completed":
        return

    if task["status"] == "blocked":
        raise ValueError(
            "Blocked exit tasks must be unblocked before completion"
        )

    if task["status"] not in {"not_started", "in_progress"}:
        raise ValueError(
            f"Cannot complete exit task with status {task['status']}"
        )

    employee_id = task["owner_employee_id"]

    if task_kind == "revoke_access":
        revoke_employee_access(connection, employee_id)

        active_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM access_requests
            WHERE employee_id = ?
              AND status = 'active'
            """,
            (employee_id,),
        ).fetchone()[0]

        if active_count:
            raise ValueError(
                "Cannot complete revocation task while active grants remain"
            )

    assignments = []

    if task_kind == "recover_assets":
        assignments = connection.execute(
            """
            SELECT assignment_id, asset_id
            FROM asset_assignments
            WHERE employee_id = ?
              AND recovered_date IS NULL
            """,
            (employee_id,),
        ).fetchall()

        # Do not recover an asset while another employee still has an
        # active assignment for the same asset.
        for assignment in assignments:
            other_owner_count = connection.execute(
                """
                SELECT COUNT(DISTINCT employee_id)
                FROM asset_assignments
                WHERE asset_id = ?
                  AND recovered_date IS NULL
                  AND employee_id <> ?
                """,
                (assignment["asset_id"], employee_id),
            ).fetchone()[0]

            if other_owner_count:
                raise ValueError(
                    f"Asset {assignment['asset_id']} has a conflicting "
                    "active assignment; recovery is blocked"
                )

    set_task_status(connection, task_id, "completed")

    if task_kind == "recover_assets":
        for assignment in assignments:
            connection.execute(
                """
                UPDATE asset_assignments
                SET recovered_date = DATE('now')
                WHERE assignment_id = ?
                  AND recovered_date IS NULL
                """,
                (assignment["assignment_id"],),
            )

            remaining_assignments = connection.execute(
                """
                SELECT COUNT(*)
                FROM asset_assignments
                WHERE asset_id = ?
                  AND recovered_date IS NULL
                """,
                (assignment["asset_id"],),
            ).fetchone()[0]

            if remaining_assignments == 0:
                connection.execute(
                    """
                    UPDATE assets
                    SET lifecycle_state = 'recovered'
                    WHERE asset_id = ?
                    """,
                    (assignment["asset_id"],),
                )

            record_event(
                connection,
                employee_id,
                "asset_recovered",
                "AssetAssignment",
                assignment["assignment_id"],
                "assigned",
                "recovered",
            )

    remaining_tasks = connection.execute(
        """
        SELECT COUNT(*)
        FROM task_instances
        WHERE offboarding_case_id = ?
          AND status <> 'completed'
        """,
        (task["offboarding_case_id"],),
    ).fetchone()[0]

    if remaining_tasks == 0:
        connection.execute(
            """
            UPDATE offboarding_cases
            SET status = 'completed',
                effective_to = DATE('now')
            WHERE offboarding_case_id = ?
              AND status <> 'completed'
            """,
            (task["offboarding_case_id"],),
        )

        record_event(
            connection,
            employee_id,
            "offboarding_completed",
            "OffboardingCase",
            task["offboarding_case_id"],
            "open",
            "completed",
        )
