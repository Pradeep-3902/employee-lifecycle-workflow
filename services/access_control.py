
"""Access approval, provisioning, and removal rules."""

from __future__ import annotations

from services.audit import record_event


VALID_DECISIONS = {"approved", "rejected"}
ACTIVE_MANAGER_STATE = "active"
TERMINATED_EMPLOYEE_STATE = "terminated"


def _get_employee(connection, employee_id: str):
    """Return the employee record or raise an error."""
    employee = connection.execute(
        """
        SELECT employee_id, lifecycle_state, manager_id
        FROM employees
        WHERE employee_id = ?
        """,
        (employee_id,),
    ).fetchone()

    if employee is None:
        raise LookupError("Employee for access request not found")

    return employee


def _get_access_request(connection, request_id: str):
    """Return the access request or raise an error."""
    request = connection.execute(
        """
        SELECT *
        FROM access_requests
        WHERE access_request_id = ?
        """,
        (request_id,),
    ).fetchone()

    if request is None:
        raise LookupError("Access request not found")

    return request


def _get_approval(connection, request_id: str):
    """Return the approval record or raise an error."""
    approval = connection.execute(
        """
        SELECT *
        FROM approvals
        WHERE access_request_id = ?
        """,
        (request_id,),
    ).fetchone()

    if approval is None:
        raise LookupError("Approval record not found")

    return approval


def _get_provisioning_task(connection, case_id: str):
    """Find the onboarding access-provisioning task."""
    task = connection.execute(
        """
        SELECT task_id, status
        FROM task_instances
        WHERE case_id = ?
          AND task_kind = 'access_provisioning'
        LIMIT 1
        """,
        (case_id,),
    ).fetchone()

    if task is None:
        raise LookupError("Access-provisioning task not found")

    return task


def _check_provisioning_prerequisites(connection, task_id: str) -> bool:
    """Return True when all dependencies of the task are completed."""
    dependencies = connection.execute(
        """
        SELECT prerequisite.status
        FROM task_dependencies AS dependency
        JOIN task_instances AS prerequisite
          ON prerequisite.task_id = dependency.depends_on_task_id
        WHERE dependency.task_id = ?
        """,
        (task_id,),
    ).fetchall()

    return all(row["status"] == "completed" for row in dependencies)


def decide_access(
    connection,
    request_id: str,
    decision: str,
    approver_manager_id: str,
) -> None:
    """
    Approve or reject a pending access request.

    An approved request becomes active only when the access-provisioning
    task and its prerequisites are complete. Otherwise, approval is
    recorded while the request remains pending.
    """
    if decision not in VALID_DECISIONS:
        raise ValueError("decision must be approved or rejected")

    request = _get_access_request(connection, request_id)
    employee = _get_employee(connection, request["employee_id"])

    if (
        decision == "approved"
        and employee["lifecycle_state"] == TERMINATED_EMPLOYEE_STATE
    ):
        raise ValueError("Cannot provision access for a terminated employee")

    approval = _get_approval(connection, request_id)

    if approval["decision"] != "pending" or request["status"] != "pending":
        raise ValueError("Only pending access requests can receive a new decision")

    approver = connection.execute(
        """
        SELECT manager_id, lifecycle_state
        FROM managers
        WHERE manager_id = ?
        """,
        (approver_manager_id,),
    ).fetchone()

    if approver is None or approver["lifecycle_state"] != ACTIVE_MANAGER_STATE:
        raise ValueError("Approver must be an active manager")

    if employee["manager_id"] is None:
        if decision == "approved":
            raise ValueError(
                "Employee must have an assigned manager before access approval"
            )
    elif approver_manager_id != employee["manager_id"]:
        raise ValueError("Only the assigned manager can approve this request")

    if decision == "approved":
        case_id = request["case_id"]
        if not case_id:
            raise ValueError(
                "Access request must be associated with an onboarding case"
            )

        task = _get_provisioning_task(connection, case_id)
        prerequisites_complete = _check_provisioning_prerequisites(
            connection, task["task_id"]
        )

        is_provisioned = (
            task["status"] == "completed" and prerequisites_complete
        )
        next_status = "active" if is_provisioned else "pending"
    else:
        is_provisioned = False
        next_status = "rejected"

    connection.execute(
        """
        UPDATE approvals
        SET approver_manager_id = ?,
            decision = ?,
            decision_date = DATE('now'),
            effective_from = DATE('now')
        WHERE access_request_id = ?
        """,
        (approver_manager_id, decision, request_id),
    )

    connection.execute(
        """
        UPDATE access_requests
        SET status = ?,
            effective_from = CASE
                WHEN ? = 1 THEN DATE('now')
                ELSE NULL
            END,
            effective_to = NULL
        WHERE access_request_id = ?
        """,
        (next_status, int(is_provisioned), request_id),
    )

    record_event(
        connection,
        request["employee_id"],
        f"access_{decision}",
        "AccessRequest",
        request_id,
        request["status"],
        decision,
    )

    if is_provisioned:
        record_event(
            connection,
            request["employee_id"],
            "access_provisioned",
            "AccessRequest",
            request_id,
            "pending",
            "active",
        )


def revoke_employee_access(connection, employee_id: str) -> int:
    """
    Revoke active access and cancel pending requests for an employee.

    Returns the number of active or pending requests processed.
    The caller is responsible for committing or rolling back the transaction.
    """
    employee = connection.execute(
        """
        SELECT employee_id
        FROM employees
        WHERE employee_id = ?
        """,
        (employee_id,),
    ).fetchone()

    if employee is None:
        raise LookupError("Employee not found")

    requests = connection.execute(
        """
        SELECT access_request_id, status
        FROM access_requests
        WHERE employee_id = ?
          AND status IN ('active', 'pending')
        ORDER BY access_request_id
        """,
        (employee_id,),
    ).fetchall()

    for request in requests:
        request_id = request["access_request_id"]
        old_status = request["status"]

        if old_status == "active":
            connection.execute(
                """
                UPDATE access_requests
                SET status = 'revoked',
                    effective_to = DATE('now')
                WHERE access_request_id = ?
                  AND status = 'active'
                """,
                (request_id,),
            )

            record_event(
                connection,
                employee_id,
                "access_revoked",
                "AccessRequest",
                request_id,
                "active",
                "revoked",
            )
        else:
            connection.execute(
                """
                UPDATE access_requests
                SET status = 'rejected',
                    effective_from = NULL,
                    effective_to = NULL
                WHERE access_request_id = ?
                  AND status = 'pending'
                """,
                (request_id,),
            )

            connection.execute(
                """
                UPDATE approvals
                SET decision = 'rejected',
                    decision_date = DATE('now'),
                    effective_from = DATE('now')
                WHERE access_request_id = ?
                  AND decision = 'pending'
                """,
                (request_id,),
            )

            record_event(
                connection,
                employee_id,
                "access_request_cancelled_on_exit",
                "AccessRequest",
                request_id,
                "pending",
                "rejected",
            )

    return len(requests)
