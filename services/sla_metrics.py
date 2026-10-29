
"""Derived operational metrics calculated from persisted source records."""

from __future__ import annotations

from datetime import date
from typing import Any

# Fixed evaluation date for reproducible synthetic-data reporting.
SLA_REFERENCE_DATE = "2026-10-22"


def dashboard_metrics(connection) -> dict[str, int | float | str]:
    """Return high-level operational metrics from persisted database records."""
    reference_date = date.fromisoformat(SLA_REFERENCE_DATE).isoformat()

    queries = {
        "employees": """
            SELECT COUNT(*)
            FROM employees
        """,
        "onboarding_open": """
            SELECT COUNT(*)
            FROM onboarding_cases
            WHERE status IN ('in_progress', 'blocked')
        """,
        "overdue_tasks": """
            SELECT COUNT(*)
            FROM task_instances
            WHERE status <> 'completed'
              AND due_date IS NOT NULL
              AND due_date < ?
        """,
        "sla_breaches": """
            SELECT COUNT(*)
            FROM task_instances
            WHERE sla_breached = 1
        """,
        "late_approvals": """
            SELECT COUNT(*)
            FROM approvals
            WHERE sla_breached = 1
        """,
        "active_access": """
            SELECT COUNT(*)
            FROM access_requests
            WHERE status = 'active'
        """,
        "terminated_active_access": """
            SELECT COUNT(*)
            FROM access_requests AS a
            JOIN employees AS e
              ON e.employee_id = a.employee_id
            WHERE e.lifecycle_state = 'terminated'
              AND a.status = 'active'
        """,
        "unrecovered_assets": """
            SELECT COUNT(*)
            FROM asset_assignments AS aa
            JOIN employees AS e
              ON e.employee_id = aa.employee_id
            WHERE aa.recovered_date IS NULL
              AND e.lifecycle_state = 'terminated'
        """,
        "completion_rate": """
            SELECT COALESCE(
                ROUND(
                    100.0 * SUM(
                        CASE WHEN t.status = 'completed' THEN 1 ELSE 0 END
                    ) / NULLIF(COUNT(*), 0),
                    1
                ),
                0
            )
            FROM task_instances AS t
            JOIN onboarding_cases AS c
              ON c.case_id = t.case_id
            WHERE c.status <> 'cancelled'
        """,
    }

    metrics: dict[str, int | float | str] = {}

    for name, query in queries.items():
        if name == "overdue_tasks":
            value = connection.execute(query, (reference_date,)).fetchone()[0]
        else:
            value = connection.execute(query).fetchone()[0]

        metrics[name] = value if value is not None else 0

    metrics["sla_reference_date"] = reference_date
    return metrics


def dashboard_overview(connection) -> dict[str, Any]:
    """Return offboarding run summaries and a six-month activity timeline."""
    as_of = date.fromisoformat(SLA_REFERENCE_DATE)
    as_of_text = as_of.isoformat()

    raw_runs = connection.execute(
        """
        SELECT
            o.offboarding_case_id,
            o.employee_id,
            o.opened_date,
            o.status,
            COUNT(t.task_id) AS task_count,
            COALESCE(
                SUM(
                    CASE WHEN t.status = 'completed' THEN 1 ELSE 0 END
                ),
                0
            ) AS completed_tasks,
            COALESCE(
                SUM(
                    CASE
                        WHEN t.status <> 'completed'
                         AND t.due_date IS NOT NULL
                         AND t.due_date < ?
                        THEN 1
                        ELSE 0
                    END
                ),
                0
            ) AS overdue_tasks,
            e.department_id
        FROM offboarding_cases AS o
        JOIN employees AS e
          ON e.employee_id = o.employee_id
        LEFT JOIN task_instances AS t
          ON t.offboarding_case_id = o.offboarding_case_id
        GROUP BY
            o.offboarding_case_id,
            o.employee_id,
            o.opened_date,
            o.status,
            e.department_id
        ORDER BY o.opened_date DESC, o.offboarding_case_id DESC
        """,
        (as_of_text,),
    ).fetchall()

    runs = [dict(row) for row in raw_runs]

    for run in runs:
        if run["status"] == "completed":
            display_status = "completed"
        elif run["overdue_tasks"] > 0:
            display_status = "overdue"
        elif run["completed_tasks"] > 0:
            display_status = "in_progress"
        else:
            display_status = "pending"

        run["display_status"] = display_status

    status_names = ("completed", "in_progress", "pending", "overdue")
    breakdown = {
        status: sum(run["display_status"] == status for run in runs)
        for status in status_names
    }

    timeline = []

    # Six calendar months, including the reference month.
    for offset in range(5, -1, -1):
        month_index = as_of.year * 12 + (as_of.month - 1) - offset
        year, zero_based_month = divmod(month_index, 12)
        month = zero_based_month + 1
        month_key = f"{year:04d}-{month:02d}"

        month_runs = sum(
            1
            for run in runs
            if run["opened_date"]
            and str(run["opened_date"])[:7] == month_key
        )

        timeline.append(
            {
                "month": month_key,
                "label": date(year, month, 1).strftime("%b"),
                "runs": month_runs,
            }
        )

    return {
        "as_of_date": as_of_text,
        "run_breakdown": breakdown,
        "timeline": timeline,
        "active_runs": sum(run["status"] == "open" for run in runs),
        "recent_runs": runs[:8],
    }
