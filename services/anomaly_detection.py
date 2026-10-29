
"""Detect workflow exceptions in the employee lifecycle database."""

from __future__ import annotations


def detect_exceptions(connection):
    """Return detected workflow exceptions as a list of dictionaries."""

    checks = [
        (
            "manager_missing",
            "Employee",
            """
            SELECT e.employee_id AS entity_id,
                   'Assign an eligible manager to the employee.'
                       AS expected_action
            FROM employees AS e
            WHERE e.lifecycle_state <> 'terminated'
              AND e.manager_id IS NULL
            """,
        ),
        (
            "task_before_prerequisite",
            "TaskInstance",
            """
            SELECT DISTINCT child.task_id AS entity_id,
                   'Block completion until prerequisite tasks are complete.'
                       AS expected_action
            FROM task_dependencies AS d
            JOIN task_instances AS child
              ON child.task_id = d.task_id
            JOIN task_instances AS parent
              ON parent.task_id = d.depends_on_task_id
            WHERE child.status = 'completed'
              AND (
                    parent.status <> 'completed'
                    OR parent.completed_date IS NULL
                    OR child.completed_date IS NULL
                    OR child.completed_date < parent.completed_date
                  )
            """,
        ),
        (
            "asset_assigned_twice",
            "Asset",
            """
            SELECT aa.asset_id AS entity_id,
                   'Resolve conflicting active assignments before dispatch.'
                       AS expected_action
            FROM asset_assignments AS aa
            WHERE aa.recovered_date IS NULL
            GROUP BY aa.asset_id
            HAVING COUNT(DISTINCT aa.employee_id) > 1
            """,
        ),
        (
            "start_before_background_check",
            "Employee",
            """
            SELECT DISTINCT e.employee_id AS entity_id,
                   'Delay start or escalate the unverified employee.'
                       AS expected_action
            FROM employees AS e
            JOIN task_instances AS t
              ON t.owner_employee_id = e.employee_id
             AND t.task_kind = 'background_check'
            WHERE t.status <> 'completed'
               OR t.completed_date IS NULL
               OR e.start_date < t.completed_date
            """,
        ),
        (
            "offboarding_active_access",
            "AccessRequest",
            """
            SELECT a.access_request_id AS entity_id,
                   'Revoke active access immediately and verify the exit task.'
                       AS expected_action
            FROM access_requests AS a
            JOIN employees AS e
              ON e.employee_id = a.employee_id
            WHERE e.lifecycle_state = 'terminated'
              AND a.status = 'active'
            """,
        ),
        (
            "overdue_task",
            "TaskInstance",
            """
            SELECT t.task_id AS entity_id,
                   'Escalate the task and retain its SLA breach.'
                       AS expected_action
            FROM task_instances AS t
            WHERE t.status <> 'completed'
              AND (
                    t.sla_breached = 1
                    OR (
                        t.due_date IS NOT NULL
                        AND t.due_date < DATE('now')
                    )
                  )
            """,
        ),
        (
            "department_changed_mid_process",
            "Employee",
            """
            SELECT DISTINCT e.employee_id AS entity_id,
                   'Review ownership and retain the effective-dated transfer.'
                       AS expected_action
            FROM employees AS e
            JOIN employee_department_history AS h
              ON h.employee_id = e.employee_id
            JOIN onboarding_cases AS c
              ON c.employee_id = e.employee_id
            WHERE h.change_reason = 'department_transfer'
              AND c.status IN ('in_progress', 'blocked', 'completed')
            """,
        ),
    ]

    exceptions = []

    for issue_type, entity_type, query in checks:
        rows = connection.execute(query).fetchall()

        for row in rows:
            exceptions.append(
                {
                    "issue_type": issue_type,
                    "entity_type": entity_type,
                    "entity_id": row["entity_id"],
                    "expected_action": row["expected_action"],
                }
            )

    return exceptions
