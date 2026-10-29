
"""Inject deterministic, labelled anomalies into synthetic lifecycle data."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

BASE_DATE = date(2026, 10, 22)

EXPECTED_ANOMALY_TYPES = {
    "manager_missing",
    "task_before_prerequisite",
    "asset_assigned_twice",
    "start_before_background_check",
    "offboarding_active_access",
    "overdue_task",
    "department_changed_mid_process",
}


def _date(value: str) -> date:
    """Parse an ISO-format date."""
    return date.fromisoformat(value)


def _set_completed(
    task: dict[str, Any],
    completed_on: date,
) -> None:
    """Set a task completed without violating its date constraint."""
    created_on = _date(task["created_date"])

    if completed_on < created_on:
        task["created_date"] = completed_on.isoformat()

    task["status"] = "completed"
    task["completed_date"] = completed_on.isoformat()
    task["sla_breached"] = int(
        completed_on > _date(task["due_date"])
    )


def _set_incomplete(
    task: dict[str, Any],
    status: str = "not_started",
) -> None:
    """Reset a task to an incomplete state."""
    if status not in {"not_started", "in_progress", "blocked"}:
        raise ValueError(f"Invalid incomplete task status: {status}")

    task["status"] = status
    task["completed_date"] = None
    task["sla_breached"] = int(
        _date(task["due_date"]) < BASE_DATE
    )


def _find_case(
    tables: dict[str, list[dict[str, Any]]],
    employee_id: str,
) -> dict[str, Any]:
    """Find an employee's onboarding case."""
    for case in tables["onboarding_cases"]:
        if case["employee_id"] == employee_id:
            return case

    raise ValueError(f"No onboarding case for employee {employee_id!r}")


def _find_task(
    tables: dict[str, list[dict[str, Any]]],
    employee_id: str,
    task_kind: str,
    *,
    case_id: str | None = None,
    offboarding_case_id: str | None = None,
) -> dict[str, Any]:
    """Find a task using employee, kind, and optional case scope."""
    matches = []

    for task in tables["task_instances"]:
        if task["owner_employee_id"] != employee_id:
            continue
        if task["task_kind"] != task_kind:
            continue
        if case_id is not None and task["case_id"] != case_id:
            continue
        if (
            offboarding_case_id is not None
            and task["offboarding_case_id"] != offboarding_case_id
        ):
            continue

        matches.append(task)

    if not matches:
        raise ValueError(
            f"Missing task {task_kind!r} for employee {employee_id!r}"
        )

    return matches[0]


def _find_approval(
    tables: dict[str, list[dict[str, Any]]],
    access_request_id: str,
) -> dict[str, Any]:
    """Find the approval associated with an access request."""
    for approval in tables["approvals"]:
        if approval["access_request_id"] == access_request_id:
            return approval

    raise ValueError(
        f"No approval for access request {access_request_id!r}"
    )


def _label(
    issue_type: str,
    entity_type: str,
    entity_id: str,
    expected_action: str,
) -> dict[str, str]:
    """Create one ground-truth label."""
    return {
        "issue_type": issue_type,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "ground_truth": expected_action,
    }


def inject_anomalies(
    tables: dict[str, list[dict[str, Any]]],
) -> list[dict[str, str]]:
    """Inject seven deterministic anomalies and return their ground truth.

    This function mutates the supplied tables. Call it once per newly
    generated dataset, not repeatedly on the same tables.
    """
    employees = tables["employees"]

    if len(employees) < 9:
        raise ValueError(
            "Anomaly injection requires at least 9 employees."
        )

    required_tables = (
        "onboarding_cases",
        "task_instances",
        "task_dependencies",
        "employee_department_history",
        "asset_assignments",
        "assets",
        "access_requests",
        "approvals",
        "managers",
        "offboarding_cases",
        "departments",
    )

    missing_tables = [
        name for name in required_tables if name not in tables
    ]
    if missing_tables:
        raise ValueError(
            f"Missing required tables: {', '.join(missing_tables)}"
        )

    # Employee and case lookup maps are used only for the baseline records.
    employees_by_id = {
        row["employee_id"]: row for row in employees
    }

    labels: list[dict[str, str]] = []

    # ---------------------------------------------------------------
    # 1. Missing manager assignment
    # ---------------------------------------------------------------
    employee = employees[0]
    employee_id = employee["employee_id"]
    case = _find_case(tables, employee_id)

    employee["manager_id"] = None

    manager_task = _find_task(
        tables,
        employee_id,
        "manager_approval",
        case_id=case["case_id"],
    )
    manager_task["assigned_to_manager_id"] = None
    _set_incomplete(manager_task, "blocked")

    # Reset every completed task that depends directly or indirectly on
    # manager approval. A blocked approval cannot have completed descendants.
    task_by_id = {
        task["task_id"]: task for task in tables["task_instances"]
    }
    descendants: set[str] = set()
    frontier = {manager_task["task_id"]}

    while frontier:
        next_frontier: set[str] = set()

        for edge in tables["task_dependencies"]:
            if edge["depends_on_task_id"] not in frontier:
                continue

            dependent_id = edge["task_id"]
            if dependent_id in descendants:
                continue

            descendants.add(dependent_id)
            next_frontier.add(dependent_id)

        frontier = next_frontier

    for task_id in descendants:
        dependent_task = task_by_id.get(task_id)
        if dependent_task is not None and dependent_task["status"] == "completed":
            _set_incomplete(dependent_task)

    # A manager-dependent approval must remain pending until a manager
    # is assigned.
    for request in tables["access_requests"]:
        if request["employee_id"] != employee_id:
            continue

        request["status"] = "pending"
        request["effective_from"] = None
        request["effective_to"] = None

        approval = _find_approval(
            tables,
            request["access_request_id"],
        )
        approval["decision"] = "pending"
        approval["decision_date"] = None
        approval["effective_from"] = None
        approval["effective_to"] = None
        approval["sla_breached"] = int(
            (
                BASE_DATE - _date(request["requested_date"])
            ).days > approval["sla_days"]
        )

    labels.append(
        _label(
            "manager_missing",
            "Employee",
            employee_id,
            "assign_manager_before_approval",
        )
    )

    # ---------------------------------------------------------------
    # 2. A task completes before its prerequisite
    # ---------------------------------------------------------------
    employee = employees[1]
    employee_id = employee["employee_id"]
    case = _find_case(tables, employee_id)
    case_id = case["case_id"]

    account_task = _find_task(
        tables,
        employee_id,
        "account_creation",
        case_id=case_id,
    )
    identity_task = _find_task(
        tables,
        employee_id,
        "identity_verification",
        case_id=case_id,
    )
    manager_task = _find_task(
        tables,
        employee_id,
        "manager_approval",
        case_id=case_id,
    )

    # Give the three tasks a shared, earlier creation date so their
    # completion timestamps satisfy the schema's date constraint.
    early_created = (BASE_DATE - timedelta(days=14)).isoformat()

    for task in (account_task, identity_task, manager_task):
        task["created_date"] = early_created

    # Account creation precedes identity verification: this is the
    # deliberate dependency violation.
    _set_completed(account_task, BASE_DATE - timedelta(days=1))
    _set_completed(identity_task, BASE_DATE)
    _set_completed(manager_task, BASE_DATE - timedelta(days=2))

    # Find every descendant of the account-creation task in the dependency
    # graph, then reset completed downstream tasks to avoid unrelated
    # completion-order violations.
    task_by_id = {
        task["task_id"]: task for task in tables["task_instances"]
    }
    descendants: set[str] = set()
    frontier = {account_task["task_id"]}

    while frontier:
        next_frontier: set[str] = set()

        for edge in tables["task_dependencies"]:
            if edge["depends_on_task_id"] not in frontier:
                continue

            dependent_id = edge["task_id"]

            if dependent_id in descendants:
                continue

            descendants.add(dependent_id)
            next_frontier.add(dependent_id)

        frontier = next_frontier

    for task_id in descendants:
        task = task_by_id.get(task_id)
        if task is None:
            continue

        # Keep the explicitly injected violation intact.
        if task_id == account_task["task_id"]:
            continue

        if task["status"] == "completed":
            _set_incomplete(task)

    # Do not leave already-active access provisioned for this onboarding
    # case after resetting its downstream tasks.
    for request in tables["access_requests"]:
        if (
            request["case_id"] == case_id
            and request["status"] == "active"
        ):
            request["status"] = "pending"
            request["effective_from"] = None
            request["effective_to"] = None

            approval = _find_approval(
                tables,
                request["access_request_id"],
            )
            approval["decision"] = "pending"
            approval["decision_date"] = None
            approval["effective_from"] = None
            approval["effective_to"] = None

    labels.append(
        _label(
            "task_before_prerequisite",
            "TaskInstance",
            account_task["task_id"],
            "block_completion_until_prerequisite_complete",
        )
    )

    # ---------------------------------------------------------------
    # 3. Duplicate active asset assignment
    # ---------------------------------------------------------------
    active_assignment = next(
        (
            row for row in tables["asset_assignments"]
            if row["recovered_date"] is None
        ),
        None,
    )

    if active_assignment is None:
        raise ValueError(
            "Cannot inject duplicate asset assignment: "
            "no active baseline assignment exists."
        )

    duplicate = dict(active_assignment)
    duplicate["assignment_id"] = (
        f"ASG-{len(tables['asset_assignments']) + 1:06d}"
    )

    # Use employee 3's case for the duplicate row, while retaining the
    # same asset ID to create the intentional collision.
    duplicate_employee = employees[2]
    duplicate_case = _find_case(
        tables,
        duplicate_employee["employee_id"],
    )

    duplicate["employee_id"] = duplicate_employee["employee_id"]
    duplicate["case_id"] = duplicate_case["case_id"]
    duplicate["recovered_date"] = None

    tables["asset_assignments"].append(duplicate)

    asset = next(
        row for row in tables["assets"]
        if row["asset_id"] == duplicate["asset_id"]
    )
    asset["lifecycle_state"] = "assigned"

    labels.append(
        _label(
            "asset_assigned_twice",
            "Asset",
            duplicate["asset_id"],
            "hold_second_assignment_for_asset_review",
        )
    )

    # ---------------------------------------------------------------
    # 4. Employee starts before background check completes
    # ---------------------------------------------------------------
    employee = employees[1]
    employee_id = employee["employee_id"]

    employee["start_date"] = (
        BASE_DATE - timedelta(days=1)
    ).isoformat()
    employee["lifecycle_state"] = "active"
    employee["effective_from"] = (
        BASE_DATE - timedelta(days=15)
    ).isoformat()

    initial_history = next(
        (
            row for row in tables["employee_department_history"]
            if row["employee_id"] == employee_id
            and row["change_reason"] == "initial_assignment"
        ),
        None,
    )

    if initial_history is None:
        raise ValueError(
            f"Missing initial department history for {employee_id}"
        )

    initial_history["effective_from"] = employee["effective_from"]

    background_task = _find_task(
        tables,
        employee_id,
        "background_check",
        case_id=_find_case(tables, employee_id)["case_id"],
    )

    background_task["created_date"] = (
        BASE_DATE - timedelta(days=14)
    ).isoformat()
    _set_completed(background_task, BASE_DATE)

    labels.append(
        _label(
            "start_before_background_check",
            "Employee",
            employee_id,
            "delay_start_or_escalate_unverified_employee",
        )
    )

    # ---------------------------------------------------------------
    # 5. A terminated employee still has active system access
    # ---------------------------------------------------------------
    terminated_employee = next(
        (
            row for row in employees
            if row["lifecycle_state"] == "terminated"
        ),
        None,
    )

    if terminated_employee is None:
        raise ValueError(
            "Cannot inject offboarding access anomaly: "
            "no terminated employee exists."
        )

    terminated_id = terminated_employee["employee_id"]
    offboarding_case = next(
        (
            row for row in tables["offboarding_cases"]
            if row["employee_id"] == terminated_id
        ),
        None,
    )

    if offboarding_case is None:
        raise ValueError(
            f"Missing offboarding case for {terminated_id}"
        )

    # Use a request and its existing approval to preserve unique IDs and
    # the one-approval-per-request relationship.
    if not tables["access_requests"]:
        raise ValueError(
            "Cannot inject offboarding access anomaly: no access requests."
        )

    request = tables["access_requests"][0]
    request["employee_id"] = terminated_id
    request["case_id"] = _find_case(tables, terminated_id)["case_id"]
    request["status"] = "active"
    request["effective_from"] = BASE_DATE.isoformat()
    request["effective_to"] = None

    approval = _find_approval(
        tables,
        request["access_request_id"],
    )

    # The schema requires a manager reference on approvals. If this
    # terminated employee has no manager, select a valid manager so that
    # the intended anomaly remains active access, not a foreign-key error.
    if terminated_employee["manager_id"] is None:
        valid_managers = tables["managers"]
        if not valid_managers:
            raise ValueError(
                "No manager records exist for the approval foreign key."
            )
        approval["approver_manager_id"] = valid_managers[0]["manager_id"]
    else:
        approval["approver_manager_id"] = terminated_employee["manager_id"]

    approval["decision"] = "approved"
    approval["decision_date"] = BASE_DATE.isoformat()
    approval["effective_from"] = BASE_DATE.isoformat()
    approval["effective_to"] = None
    approval["sla_breached"] = int(
        (
            BASE_DATE - _date(request["requested_date"])
        ).days > approval["sla_days"]
    )

    revoke_task = _find_task(
        tables,
        terminated_id,
        "revoke_access",
        offboarding_case_id=offboarding_case["offboarding_case_id"],
    )
    _set_incomplete(revoke_task)

    recovery_task = _find_task(
        tables,
        terminated_id,
        "recover_assets",
        offboarding_case_id=offboarding_case["offboarding_case_id"],
    )
    _set_incomplete(recovery_task)

    offboarding_case["status"] = "open"
    offboarding_case["effective_to"] = None

    for assignment in tables["asset_assignments"]:
        if assignment["employee_id"] != terminated_id:
            continue

        assignment["recovered_date"] = None
        asset = next(
            row for row in tables["assets"]
            if row["asset_id"] == assignment["asset_id"]
        )
        asset["lifecycle_state"] = "assigned"

    labels.append(
        _label(
            "offboarding_active_access",
            "AccessRequest",
            request["access_request_id"],
            "revoke_access_immediately",
        )
    )

    # ---------------------------------------------------------------
    # 6. An incomplete onboarding task is overdue
    # ---------------------------------------------------------------
    overdue_task = next(
        (
            row for row in tables["task_instances"]
            if row["case_id"] is not None
            and row["status"] != "completed"
        ),
        None,
    )

    if overdue_task is None:
        raise ValueError(
            "Cannot inject overdue-task anomaly: "
            "no incomplete onboarding task exists."
        )

    overdue_task["due_date"] = (
        BASE_DATE - timedelta(days=2)
    ).isoformat()
    overdue_task["sla_breached"] = 1

    labels.append(
        _label(
            "overdue_task",
            "TaskInstance",
            overdue_task["task_id"],
            "escalate_and_mark_sla_breach",
        )
    )

    # ---------------------------------------------------------------
    # 7. Department changes during the employee lifecycle
    # ---------------------------------------------------------------
    employee = employees[2]
    employee_id = employee["employee_id"]
    old_department_id = employee["department_id"]

    new_department = next(
        (
            row for row in tables["departments"]
            if row["department_id"] != old_department_id
        ),
        None,
    )

    if new_department is None:
        raise ValueError(
            "Cannot inject department transfer: "
            "no alternative department exists."
        )

    current_history = next(
        (
            row for row in tables["employee_department_history"]
            if row["employee_id"] == employee_id
            and row["effective_to"] is None
        ),
        None,
    )

    if current_history is None:
        raise ValueError(
            f"No open department history for employee {employee_id}"
        )

    change_date = max(
        BASE_DATE,
        _date(current_history["effective_from"]) + timedelta(days=1),
    )

    current_history["effective_to"] = (
        change_date - timedelta(days=1)
    ).isoformat()

    tables["employee_department_history"].append(
        {
            "employee_id": employee_id,
            "department_id": new_department["department_id"],
            "effective_from": change_date.isoformat(),
            "effective_to": None,
            "change_reason": "department_transfer",
        }
    )

    employee["department_id"] = new_department["department_id"]
    employee["effective_from"] = change_date.isoformat()

    labels.append(
        _label(
            "department_changed_mid_process",
            "Employee",
            employee_id,
            "retain_effective_dated_department_history",
        )
    )

    # Final consistency checks on the ground-truth labels.
    observed_types = [row["issue_type"] for row in labels]

    if len(observed_types) != len(EXPECTED_ANOMALY_TYPES):
        raise RuntimeError(
            f"Expected {len(EXPECTED_ANOMALY_TYPES)} anomaly labels; "
            f"generated {len(observed_types)}."
        )

    if set(observed_types) != EXPECTED_ANOMALY_TYPES:
        raise RuntimeError(
            "Unexpected anomaly labels: "
            f"{sorted(set(observed_types))}"
        )

    if len(set(observed_types)) != len(observed_types):
        raise RuntimeError("Duplicate anomaly types were generated.")

    return labels
