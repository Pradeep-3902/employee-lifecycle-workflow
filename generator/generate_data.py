
"""Generate a reproducible synthetic employee lifecycle dataset."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sqlite3
import sys
import uuid
from contextlib import closing
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.db import DATABASE_PATH, initialize
from generator.inject_anomalies import inject_anomalies

SEED_DEFAULT = 20261022
BASE_DATE = date(2026, 10, 22)

DEPARTMENTS = [
    "Engineering",
    "People",
    "Finance",
    "Sales",
    "Operations",
    "Legal",
    "Marketing",
    "IT",
]

ROLES = [
    "Software Engineer",
    "Data Scientist",
    "Product Manager",
    "Designer",
    "Recruiter",
    "Account Executive",
    "Financial Analyst",
    "IT Specialist",
    "Operations Associate",
    "Legal Counsel",
    "Marketing Manager",
    "Customer Engineer",
]

TASK_KINDS = [
    "identity_verification",
    "background_check",
    "manager_approval",
    "account_creation",
    "equipment_assignment",
    "access_provisioning",
    "security_training",
    "first_day_checkin",
]

TASK_OWNERS = {
    "identity_verification": "HR",
    "background_check": "HR",
    "manager_approval": "Manager",
    "account_creation": "IT",
    "equipment_assignment": "Facilities",
    "access_provisioning": "IT",
    "security_training": "HR",
    "first_day_checkin": "Manager",
    "revoke_access": "IT",
    "recover_assets": "Facilities",
}

DEPENDENCIES = {
    "account_creation": [
        "identity_verification",
        "manager_approval",
    ],
    "access_provisioning": [
        "account_creation",
        "manager_approval",
    ],
    "equipment_assignment": [
        "manager_approval",
    ],
    "security_training": [
        "account_creation",
    ],
    "first_day_checkin": [
        "security_training",
    ],
}

TABLES = [
    "departments",
    "roles",
    "managers",
    "employees",
    "employee_department_history",
    "onboarding_cases",
    "task_templates",
    "offboarding_cases",
    "task_instances",
    "task_dependencies",
    "assets",
    "asset_assignments",
    "access_requests",
    "approvals",
    "audit_events",
]

PRIMARY_KEYS = {
    "departments": ("department_id",),
    "roles": ("role_id",),
    "managers": ("manager_id",),
    "employees": ("employee_id",),
    "employee_department_history": (
        "employee_id",
        "effective_from",
    ),
    "onboarding_cases": ("case_id",),
    "task_templates": ("template_id",),
    "offboarding_cases": ("offboarding_case_id",),
    "task_instances": ("task_id",),
    "task_dependencies": (
        "task_id",
        "depends_on_task_id",
    ),
    "assets": ("asset_id",),
    "asset_assignments": ("assignment_id",),
    "access_requests": ("access_request_id",),
    "approvals": ("approval_id",),
}

ENTITY_TYPES = {
    "employees": "Employee",
    "employee_department_history": "EmployeeDepartmentHistory",
    "onboarding_cases": "OnboardingCase",
    "offboarding_cases": "OffboardingCase",
    "task_instances": "TaskInstance",
    "task_dependencies": "TaskDependency",
    "asset_assignments": "AssetAssignment",
    "access_requests": "AccessRequest",
    "approvals": "Approval",
}


def _iso(value: date | None) -> str | None:
    """Convert a date to ISO format, preserving None."""
    return value.isoformat() if value is not None else None


def _key_for(
    table: str,
    row: dict[str, Any],
) -> tuple[Any, ...]:
    """Return the configured primary-key tuple for a table row."""
    return tuple(row[field] for field in PRIMARY_KEYS[table])


def _audit_event(
    tables: dict[str, list[dict[str, Any]]],
    employee_id: str | None,
    event_type: str,
    event_date: str,
    entity_type: str,
    entity_id: str,
    old_value: Any = None,
    new_value: Any = None,
) -> None:
    """Append one deterministic audit event."""
    sequence = len(tables["audit_events"]) + 1

    if isinstance(old_value, (dict, list)):
        old_value = json.dumps(old_value, sort_keys=True)

    if isinstance(new_value, (dict, list)):
        new_value = json.dumps(new_value, sort_keys=True)

    tables["audit_events"].append(
        {
            "audit_event_id": (
                f"AUD-{BASE_DATE:%Y%m%d}-{sequence:06d}"
            ),
            "employee_id": employee_id,
            "event_type": event_type,
            "event_date": event_date,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "old_value": old_value,
            "new_value": new_value,
        }
    )


def _find_task(
    tasks: list[dict[str, Any]],
    employee_id: str,
    task_kind: str,
    case_id: str | None = None,
    offboarding_case_id: str | None = None,
) -> dict[str, Any]:
    """Find a task using employee, task kind, and optional case scope."""
    for task in tasks:
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
        return task

    raise ValueError(
        f"Missing task {task_kind!r} for employee {employee_id!r}"
    )


def _set_task_status(
    task: dict[str, Any],
    status: str,
    completed_on: date | None = None,
) -> None:
    """Update task status and keep completion-date constraints consistent."""
    task["status"] = status

    if status == "completed":
        if completed_on is None:
            raise ValueError(
                "completed_on is required for completed tasks."
            )

        created_on = date.fromisoformat(task["created_date"])
        if completed_on < created_on:
            task["created_date"] = completed_on.isoformat()

        task["completed_date"] = completed_on.isoformat()
        due_on = date.fromisoformat(task["due_date"])
        task["sla_breached"] = int(completed_on > due_on)
    else:
        task["completed_date"] = None
        due_on = date.fromisoformat(task["due_date"])
        task["sla_breached"] = int(due_on < BASE_DATE)


def generate_rows(
    employee_count: int = 500,
    seed: int = SEED_DEFAULT,
    inject: bool = True,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, str]]]:
    """Generate all tables using a local, reproducible random generator."""
    if employee_count < 1:
        raise ValueError("employee_count must be at least 1.")

    if inject and employee_count < 9:
        raise ValueError(
            "at least 9 employees are required when anomaly injection is enabled."
        )

    rng = random.Random(seed)
    tables: dict[str, list[dict[str, Any]]] = {
        table: [] for table in TABLES
    }

    # ------------------------------------------------------------------
    # Departments and roles
    # ------------------------------------------------------------------
    for index, name in enumerate(DEPARTMENTS, start=1):
        tables["departments"].append(
            {
                "department_id": f"DEPT-{index:03d}",
                "name": name,
                "lifecycle_state": "active",
                "effective_from": "2024-01-01",
                "effective_to": None,
            }
        )

    for index, name in enumerate(ROLES, start=1):
        tables["roles"].append(
            {
                "role_id": f"ROLE-{index:03d}",
                "name": name,
                "lifecycle_state": "active",
                "effective_from": "2024-01-01",
                "effective_to": None,
            }
        )

    department_ids = [
        row["department_id"] for row in tables["departments"]
    ]
    role_ids = [
        row["role_id"] for row in tables["roles"]
    ]

    # ------------------------------------------------------------------
    # Managers
    # ------------------------------------------------------------------
    manager_count = max(1, round(employee_count * 0.1))

    for index in range(1, manager_count + 1):
        tables["managers"].append(
            {
                "manager_id": f"MGR-{index:04d}",
                "department_id": department_ids[
                    (index - 1) % len(department_ids)
                ],
                "display_name": f"Manager {index:03d}",
                "lifecycle_state": "active",
                "effective_from": "2024-01-01",
                "effective_to": None,
            }
        )

    manager_ids = [
        row["manager_id"] for row in tables["managers"]
    ]

    managers_by_department: dict[str, list[str]] = defaultdict(list)
    for manager in tables["managers"]:
        managers_by_department[manager["department_id"]].append(
            manager["manager_id"]
        )

    # ------------------------------------------------------------------
    # Employees, department history, and onboarding cases
    # ------------------------------------------------------------------
    for index in range(1, employee_count + 1):
        employee_id = f"EMP-{index:06d}"

        start_date = BASE_DATE + timedelta(
            days=rng.randint(-90, 90)
        )

        if index % 20 == 0:
            start_date = BASE_DATE + timedelta(
                days=rng.randint(-2, 2)
            )

        lifecycle_state = (
            "terminated"
            if index % 9 == 0
            else "active"
            if start_date <= BASE_DATE
            else "preboarding"
        )

        termination_date = (
            BASE_DATE - timedelta(days=rng.randint(1, 30))
            if lifecycle_state == "terminated"
            else None
        )

        if (
            termination_date is not None
            and start_date >= termination_date
        ):
            start_date = termination_date - timedelta(
                days=rng.randint(1, 60)
            )

        department_id = rng.choice(department_ids)
        manager_options = (
            managers_by_department.get(department_id) or manager_ids
        )
        manager_id = rng.choice(manager_options)

        effective_from = start_date - timedelta(days=14)

        employee = {
            "employee_id": employee_id,
            "department_id": department_id,
            "role_id": rng.choice(role_ids),
            "manager_id": manager_id,
            "employment_type": rng.choice(
                ["permanent", "contractor"]
            ),
            "work_location": rng.choice(["remote", "on_site"]),
            "start_date": start_date.isoformat(),
            "lifecycle_state": lifecycle_state,
            "effective_from": effective_from.isoformat(),
            "effective_to": _iso(termination_date),
        }
        tables["employees"].append(employee)

        tables["employee_department_history"].append(
            {
                "employee_id": employee_id,
                "department_id": department_id,
                "effective_from": effective_from.isoformat(),
                "effective_to": None,
                "change_reason": "initial_assignment",
            }
        )

        case_id = f"ONB-{BASE_DATE.year}-{index:06d}"
        created_date = min(
            BASE_DATE,
            start_date - timedelta(days=12),
        )

        tables["onboarding_cases"].append(
            {
                "case_id": case_id,
                "employee_id": employee_id,
                "created_date": created_date.isoformat(),
                "status": "in_progress",
                "effective_from": created_date.isoformat(),
                "effective_to": None,
            }
        )

    employee_by_id = {
        row["employee_id"]: row for row in tables["employees"]
    }
    case_by_employee = {
        row["employee_id"]: row for row in tables["onboarding_cases"]
    }

    # ------------------------------------------------------------------
    # Task templates
    # ------------------------------------------------------------------
    template_map: dict[tuple[str, str, str], str] = {}

    for role_id in role_ids:
        for location in ("remote", "on_site"):
            for task_kind in TASK_KINDS:
                template_id = (
                    f"TPL-{role_id}-{location[0].upper()}-"
                    f"{task_kind.upper()}"
                )
                template_map[
                    (role_id, location, task_kind)
                ] = template_id

                tables["task_templates"].append(
                    {
                        "template_id": template_id,
                        "role_id": role_id,
                        "work_location": location,
                        "task_kind": task_kind,
                        "owner_team": TASK_OWNERS[task_kind],
                        "sla_days": (
                            1
                            if task_kind in {
                                "identity_verification",
                                "manager_approval",
                            }
                            else 3
                        ),
                        "effective_from": "2025-01-01",
                        "effective_to": None,
                    }
                )

    # ------------------------------------------------------------------
    # Onboarding task instances and dependency edges
    # ------------------------------------------------------------------
    task_lookup: dict[tuple[str, str], str] = {}

    for employee, case in zip(
        tables["employees"],
        tables["onboarding_cases"],
    ):
        start_date = date.fromisoformat(employee["start_date"])
        created_date = min(
            BASE_DATE,
            start_date - timedelta(days=12),
        )

        completed_dates: dict[str, date] = {}

        for position, task_kind in enumerate(TASK_KINDS, start=1):
            due_date = start_date - timedelta(
                days=max(1, 8 - position)
            )
            prerequisites = DEPENDENCIES.get(task_kind, [])

            prerequisites_completed = all(
                prerequisite in completed_dates
                for prerequisite in prerequisites
            )

            completed = (
                prerequisites_completed and rng.random() < 0.62
            )
            completed_date: date | None = None

            if completed:
                candidates = [
                    due_date - timedelta(days=rng.randint(0, 3))
                ]
                candidates.extend(
                    completed_dates[parent] + timedelta(days=1)
                    for parent in prerequisites
                )
                candidate_completion = max(candidates)

                if (
                    candidate_completion > BASE_DATE
                    or candidate_completion < created_date
                ):
                    completed = False
                else:
                    completed_date = candidate_completion
                    completed_dates[task_kind] = completed_date

            status = (
                "completed"
                if completed
                else rng.choice(
                    ["not_started", "in_progress", "blocked"]
                )
            )

            task_id = (
                f"TASK-ONB-{case['case_id']}-{position:03d}"
            )
            task_lookup[(case["case_id"], task_kind)] = task_id

            sla_breached = (
                completed_date > due_date
                if completed_date is not None
                else due_date < BASE_DATE
            )

            tables["task_instances"].append(
                {
                    "task_id": task_id,
                    "case_id": case["case_id"],
                    "offboarding_case_id": None,
                    "template_id": template_map[
                        (
                            employee["role_id"],
                            employee["work_location"],
                            task_kind,
                        )
                    ],
                    "task_kind": task_kind,
                    "owner_team": TASK_OWNERS[task_kind],
                    "assigned_to_manager_id": (
                        employee["manager_id"]
                        if task_kind == "manager_approval"
                        else None
                    ),
                    "owner_employee_id": employee["employee_id"],
                    "status": status,
                    "created_date": created_date.isoformat(),
                    "due_date": due_date.isoformat(),
                    "completed_date": _iso(completed_date),
                    "sla_breached": int(sla_breached),
                }
            )

    for case in tables["onboarding_cases"]:
        for task_kind, prerequisites in DEPENDENCIES.items():
            for prerequisite in prerequisites:
                tables["task_dependencies"].append(
                    {
                        "task_id": task_lookup[
                            (case["case_id"], task_kind)
                        ],
                        "depends_on_task_id": task_lookup[
                            (case["case_id"], prerequisite)
                        ],
                    }
                )

    # ------------------------------------------------------------------
    # Asset inventory and assignments
    # ------------------------------------------------------------------
    asset_count = max(12, round(employee_count * 1.2))

    for index in range(1, asset_count + 1):
        asset_type = rng.choice(
            ["laptop", "phone", "badge", "monitor"]
        )

        tables["assets"].append(
            {
                "asset_id": (
                    f"AST-{asset_type[:3].upper()}-{index:06d}"
                ),
                "asset_type": asset_type,
                "serial_number": f"SN-{index:08d}",
                "lifecycle_state": "available",
                "effective_from": "2025-01-01",
                "effective_to": None,
            }
        )

    assets_by_id = {
        row["asset_id"]: row for row in tables["assets"]
    }

    available_assets = list(assets_by_id)
    rng.shuffle(available_assets)

    for employee, case in zip(
        tables["employees"],
        tables["onboarding_cases"],
    ):
        should_assign = (
            employee["employee_id"] == "EMP-000001"
            or rng.random() < 0.72
        )

        if not should_assign:
            continue

        if not available_assets:
            break

        asset_id = available_assets.pop()
        assignment_id = (
            f"ASG-{len(tables['asset_assignments']) + 1:06d}"
        )

        tables["asset_assignments"].append(
            {
                "assignment_id": assignment_id,
                "asset_id": asset_id,
                "employee_id": employee["employee_id"],
                "case_id": case["case_id"],
                "assigned_date": employee["start_date"],
                "recovered_date": None,
            }
        )
        assets_by_id[asset_id]["lifecycle_state"] = "assigned"

    # ------------------------------------------------------------------
    # Access requests and approvals
    # ------------------------------------------------------------------
    access_count = round(employee_count * 0.6)

    eligible_employees = [
        row for row in tables["employees"]
        if row["lifecycle_state"] != "terminated"
    ]

    if access_count > len(eligible_employees):
        raise ValueError(
            "Not enough eligible employees to generate access requests."
        )

    selected_employees = rng.sample(
        eligible_employees,
        access_count,
    )

    for index, employee in enumerate(selected_employees, start=1):
        case = case_by_employee[employee["employee_id"]]
        request_id = f"ACCREQ-{BASE_DATE.year}-{index:06d}"

        requested_date = BASE_DATE - timedelta(
            days=rng.randint(1, 30)
        )

        decision = (
            "approved" if rng.random() < 0.82 else "pending"
        )

        decision_date = (
            min(
                BASE_DATE,
                requested_date + timedelta(
                    days=rng.randint(0, 5)
                ),
            )
            if decision == "approved"
            else None
        )

        approval_sla_breached = (
            (decision_date or BASE_DATE) - requested_date
        ).days > 2

        provisioning_task = next(
            task for task in tables["task_instances"]
            if task["task_id"] == task_lookup[
                (case["case_id"], "access_provisioning")
            ]
        )

        provisioned = (
            decision == "approved"
            and provisioning_task["status"] == "completed"
        )

        request_status = (
            "active" if provisioned else "pending"
        )

        tables["access_requests"].append(
            {
                "access_request_id": request_id,
                "employee_id": employee["employee_id"],
                "case_id": case["case_id"],
                "system_name": rng.choice(
                    [
                        "Email",
                        "HRIS",
                        "CRM",
                        "Cloud Console",
                        "Source Control",
                    ]
                ),
                "requested_date": requested_date.isoformat(),
                "status": request_status,
                "effective_from": (
                    decision_date.isoformat()
                    if provisioned and decision_date
                    else None
                ),
                "effective_to": None,
            }
        )

        # The schema requires a valid manager reference. A manager is assigned
        # for all baseline employees, before anomaly injection is performed.
        approver_manager_id = employee["manager_id"]
        if approver_manager_id is None:
            raise ValueError(
                f"Baseline employee {employee['employee_id']} has no manager."
            )

        tables["approvals"].append(
            {
                "approval_id": f"APR-{index:06d}",
                "access_request_id": request_id,
                "approver_manager_id": approver_manager_id,
                "decision": decision,
                "decision_date": _iso(decision_date),
                "sla_days": 2,
                "sla_breached": int(approval_sla_breached),
                "effective_from": _iso(decision_date),
                "effective_to": None,
            }
        )

    # ------------------------------------------------------------------
    # Offboarding cases and exit tasks
    # ------------------------------------------------------------------
    terminated_employees = [
        employee for employee in tables["employees"]
        if employee["lifecycle_state"] == "terminated"
    ]

    for index, employee in enumerate(
        terminated_employees,
        start=1,
    ):
        termination_date = date.fromisoformat(
            employee["effective_to"]
        )
        offboarding_case_id = (
            f"OFF-{BASE_DATE.year}-{index:06d}"
        )

        tables["offboarding_cases"].append(
            {
                "offboarding_case_id": offboarding_case_id,
                "employee_id": employee["employee_id"],
                "opened_date": termination_date.isoformat(),
                "status": "completed",
                "effective_from": termination_date.isoformat(),
                "effective_to": None,
            }
        )

        for position, task_kind in enumerate(
            ("revoke_access", "recover_assets"),
            start=1,
        ):
            tables["task_instances"].append(
                {
                    "task_id": (
                        f"TASK-OFF-{offboarding_case_id}-{position:03d}"
                    ),
                    "case_id": None,
                    "offboarding_case_id": offboarding_case_id,
                    "template_id": None,
                    "task_kind": task_kind,
                    "owner_team": TASK_OWNERS[task_kind],
                    "assigned_to_manager_id": None,
                    "owner_employee_id": employee["employee_id"],
                    "status": "completed",
                    "created_date": termination_date.isoformat(),
                    "due_date": (
                        termination_date + timedelta(days=1)
                    ).isoformat(),
                    "completed_date": termination_date.isoformat(),
                    "sla_breached": 0,
                }
            )

        for request in tables["access_requests"]:
            if (
                request["employee_id"] == employee["employee_id"]
                and request["status"] == "active"
            ):
                request["status"] = "revoked"
                request["effective_to"] = termination_date.isoformat()

        for assignment in tables["asset_assignments"]:
            if assignment["employee_id"] == employee["employee_id"]:
                assignment["recovered_date"] = termination_date.isoformat()
                assets_by_id[
                    assignment["asset_id"]
                ]["lifecycle_state"] = "recovered"

    # ------------------------------------------------------------------
    # Initial audit trail
    # ------------------------------------------------------------------
    for employee in tables["employees"]:
        _audit_event(
            tables=tables,
            employee_id=employee["employee_id"],
            event_type="employee_created",
            event_date=(BASE_DATE - timedelta(days=120)).isoformat(),
            entity_type="Employee",
            entity_id=employee["employee_id"],
            old_value=None,
            new_value=employee["lifecycle_state"],
        )

    for task in tables["task_instances"]:
        if task["status"] == "completed":
            _audit_event(
                tables=tables,
                employee_id=task["owner_employee_id"],
                event_type="task_completed",
                event_date=task["completed_date"],
                entity_type="TaskInstance",
                entity_id=task["task_id"],
                old_value="not_completed",
                new_value="completed",
            )

    for request in tables["access_requests"]:
        _audit_event(
            tables=tables,
            employee_id=request["employee_id"],
            event_type="access_requested",
            event_date=request["requested_date"],
            entity_type="AccessRequest",
            entity_id=request["access_request_id"],
            old_value=None,
            new_value=request["status"],
        )

        approval = next(
            row for row in tables["approvals"]
            if row["access_request_id"] == request["access_request_id"]
        )

        if approval["decision"] == "approved":
            _audit_event(
                tables=tables,
                employee_id=request["employee_id"],
                event_type="access_approved",
                event_date=approval["decision_date"],
                entity_type="AccessRequest",
                entity_id=request["access_request_id"],
                old_value="pending",
                new_value="approved",
            )

        if request["status"] == "active":
            _audit_event(
                tables=tables,
                employee_id=request["employee_id"],
                event_type="access_provisioned",
                event_date=request["effective_from"],
                entity_type="AccessRequest",
                entity_id=request["access_request_id"],
                old_value="pending",
                new_value="active",
            )
        elif request["status"] == "revoked":
            _audit_event(
                tables=tables,
                employee_id=request["employee_id"],
                event_type="access_revoked",
                event_date=request["effective_to"],
                entity_type="AccessRequest",
                entity_id=request["access_request_id"],
                old_value="active",
                new_value="revoked",
            )

    for assignment in tables["asset_assignments"]:
        recovered = assignment["recovered_date"] is not None

        _audit_event(
            tables=tables,
            employee_id=assignment["employee_id"],
            event_type=(
                "asset_recovered" if recovered else "asset_assigned"
            ),
            event_date=(
                assignment["recovered_date"]
                or assignment["assigned_date"]
            ),
            entity_type="AssetAssignment",
            entity_id=assignment["assignment_id"],
            old_value="assigned" if recovered else "available",
            new_value="recovered" if recovered else "assigned",
        )

    # ------------------------------------------------------------------
    # Inject labelled anomalies and record their state changes
    # ------------------------------------------------------------------
    before = {
        table: {
            _key_for(table, row): dict(row)
            for row in tables[table]
        }
        for table in PRIMARY_KEYS
    }

    previous_case_status = {
        row["case_id"]: row["status"]
        for row in tables["onboarding_cases"]
    }

    truth = inject_anomalies(tables) if inject else []

    if inject:
        for table, primary_keys in PRIMARY_KEYS.items():
            previous_rows = before[table]

            for row in tables[table]:
                key = _key_for(table, row)
                previous = previous_rows.get(key)

                if previous == row:
                    continue

                employee_id = (
                    row.get("employee_id")
                    or row.get("owner_employee_id")
                )
                entity_id = "|".join(str(part) for part in key)

                _audit_event(
                    tables=tables,
                    employee_id=employee_id,
                    event_type=(
                        "synthetic_record_added"
                        if previous is None
                        else "synthetic_state_changed"
                    ),
                    event_date=BASE_DATE.isoformat(),
                    entity_type=ENTITY_TYPES.get(table, table),
                    entity_id=entity_id,
                    old_value=previous,
                    new_value=row,
                )

    # Anomaly injection can change a task from incomplete to completed.
    # Those changes are recorded as synthetic_state_changed events above,
    # but every completed task must also have its canonical task_completed
    # event so validators and downstream audit consumers can find it.
    task_completion_event_ids = {
        event["entity_id"]
        for event in tables["audit_events"]
        if event.get("event_type") == "task_completed"
        and event.get("entity_type") == "TaskInstance"
    }

    for task in tables["task_instances"]:
        if (
            task.get("status") == "completed"
            and task["task_id"] not in task_completion_event_ids
        ):
            _audit_event(
                tables=tables,
                employee_id=task["owner_employee_id"],
                event_type="task_completed",
                event_date=task["completed_date"],
                entity_type="TaskInstance",
                entity_id=task["task_id"],
                old_value="not_completed",
                new_value="completed",
            )
            task_completion_event_ids.add(task["task_id"])

    # Refresh case status after anomaly injection.
    for case in tables["onboarding_cases"]:
        employee = employee_by_id[case["employee_id"]]
        case_tasks = [
            task for task in tables["task_instances"]
            if task["case_id"] == case["case_id"]
        ]

        if employee["lifecycle_state"] == "terminated":
            case["status"] = "cancelled"
        elif case_tasks and all(
            task["status"] == "completed"
            for task in case_tasks
        ):
            case["status"] = "completed"
        elif any(
            task["status"] == "blocked"
            for task in case_tasks
        ):
            case["status"] = "blocked"
        else:
            case["status"] = "in_progress"

    for case in tables["onboarding_cases"]:
        old_status = previous_case_status.get(case["case_id"])

        if old_status != case["status"]:
            _audit_event(
                tables=tables,
                employee_id=case["employee_id"],
                event_type="onboarding_case_status_changed",
                event_date=BASE_DATE.isoformat(),
                entity_type="OnboardingCase",
                entity_id=case["case_id"],
                old_value=old_status,
                new_value=case["status"],
            )

    return tables, truth


def _write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fieldnames: list[str] | None = None,
) -> None:
    """Write CSV rows with stable column ordering."""
    if fieldnames is None:
        if not rows:
            raise ValueError(
                f"Cannot infer CSV columns for empty dataset: {path}"
            )
        fieldnames = list(rows[0])

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            extrasaction="raise",
        )
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    """Return the SHA-256 digest of a file."""
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def export_data(
    tables: dict[str, list[dict[str, Any]]],
    truth: list[dict[str, str]],
    seed: int,
    database_path: Path = DATABASE_PATH,
) -> None:
    """Export generated tables and write database/reproducibility artifacts."""
    csv_dir = ROOT / "data" / "csv"
    json_dir = ROOT / "data" / "json"
    data_dir = ROOT / "data"

    csv_dir.mkdir(parents=True, exist_ok=True)
    json_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    # Validate that each required table has rows and a consistent row shape
    # before touching the database.
    table_columns: dict[str, list[str]] = {}

    for table in TABLES:
        rows = tables.get(table)

        if rows is None:
            raise ValueError(f"Missing generated table: {table}")

        if not rows:
            raise ValueError(
                f"Generated table {table!r} is empty; refusing export."
            )

        fields = list(rows[0])
        table_columns[table] = fields

        for row_number, row in enumerate(rows, start=1):
            if list(row) != fields:
                raise ValueError(
                    f"Inconsistent columns in {table}, row {row_number}."
                )

    # Export CSV and JSON artifacts.
    for table in TABLES:
        rows = tables[table]
        fields = table_columns[table]

        _write_csv(csv_dir / f"{table}.csv", rows, fields)

        (json_dir / f"{table}.json").write_text(
            json.dumps(
                rows,
                indent=2,
                sort_keys=True,
            ) + "\n",
            encoding="utf-8",
        )

    _write_csv(
        data_dir / "ground_truth.csv",
        truth,
        [
            "issue_type",
            "entity_type",
            "entity_id",
            "ground_truth",
        ],
    )

    (data_dir / "source_manifest.json").write_text(
        json.dumps(
            {
                "provenance": (
                    "Fully synthetic. No external, confidential, "
                    "or personal data used."
                ),
                "seed": seed,
                "base_date": BASE_DATE.isoformat(),
                "employee_count": len(tables["employees"]),
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    # Build the replacement database in a temporary file. The existing
    # database is not deleted until all inserts and integrity checks pass.
    database_path = Path(database_path).resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)

    # Use a unique temporary filename so a stale or externally locked
    # workflow.tmp.db cannot prevent generation on Windows.
    temporary_database = database_path.with_name(
        f"{database_path.stem}.{uuid.uuid4().hex}.tmp{database_path.suffix}"
    )

    try:
        initialize(temporary_database)

        # sqlite3's connection context manager commits/rolls back but does
        # not close the connection. closing() guarantees Windows releases
        # the database handle before the file is atomically replaced.
        with closing(
            sqlite3.connect(str(temporary_database), timeout=30.0)
        ) as connection:
            connection.execute("PRAGMA foreign_keys = ON")

            for table in TABLES:
                fields = table_columns[table]
                columns_sql = ", ".join(
                    f'"{field}"' for field in fields
                )
                placeholders = ", ".join("?" for _ in fields)

                sql = (
                    f'INSERT INTO "{table}" ({columns_sql}) '
                    f"VALUES ({placeholders})"
                )

                connection.executemany(
                    sql,
                    [
                        tuple(row.get(field) for field in fields)
                        for row in tables[table]
                    ],
                )

            # Verify referential integrity before replacing the old database.
            foreign_key_errors = connection.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()

            if foreign_key_errors:
                raise sqlite3.IntegrityError(
                    "Foreign-key validation failed: "
                    f"{foreign_key_errors[:10]}"
                )

            integrity_result = connection.execute(
                "PRAGMA integrity_check"
            ).fetchone()

            if not integrity_result or integrity_result[0] != "ok":
                raise sqlite3.IntegrityError(
                    f"SQLite integrity check failed: {integrity_result}"
                )

            connection.execute(
                """
                INSERT INTO audit_event_sequences(
                    event_date,
                    last_sequence
                )
                VALUES (?, ?)
                ON CONFLICT(event_date) DO UPDATE SET
                    last_sequence = MAX(
                        last_sequence,
                        excluded.last_sequence
                    )
                """,
                (
                    BASE_DATE.strftime("%Y%m%d"),
                    len(tables["audit_events"]),
                ),
            )

            # Commit before exporting SQL. closing() alone does not commit.
            connection.commit()
            seed_sql = "\n".join(connection.iterdump()) + "\n"

        (data_dir / "seed.sql").write_text(
            seed_sql,
            encoding="utf-8",
        )

        # Atomically replace the old database after the temporary database
        # has been created and checked.
        temporary_database.replace(database_path)

    finally:
        if temporary_database.exists():
            temporary_database.unlink()

    # Recompute hashes after all exported artifacts are finalized.
    files_to_hash = sorted(
        [
            *csv_dir.glob("*.csv"),
            *json_dir.glob("*.json"),
            data_dir / "ground_truth.csv",
            data_dir / "source_manifest.json",
            data_dir / "seed.sql",
        ],
        key=lambda path: path.relative_to(ROOT).as_posix(),
    )

    hashes = {
        path.relative_to(ROOT).as_posix(): _sha256(path)
        for path in files_to_hash
    }

    (data_dir / "reproducibility.json").write_text(
        json.dumps(
            {
                "seed": seed,
                "employees": len(tables["employees"]),
                "file_count": len(hashes),
                "sha256": hashes,
            },
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument(
        "--employees",
        type=int,
        default=500,
        help="Number of synthetic employees to generate (default: 500).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=SEED_DEFAULT,
        help=f"Random seed (default: {SEED_DEFAULT}).",
    )
    parser.add_argument(
        "--no-anomalies",
        action="store_true",
        help="Generate baseline data without injected anomalies.",
    )

    args = parser.parse_args()

    try:
        tables, truth = generate_rows(
            employee_count=args.employees,
            seed=args.seed,
            inject=not args.no_anomalies,
        )

        export_data(
            tables=tables,
            truth=truth,
            seed=args.seed,
            database_path=DATABASE_PATH,
        )

    except (ValueError, OSError, sqlite3.Error) as error:
        parser.error(str(error))

    print(
        json.dumps(
            {
                "status": "generated",
                "seed": args.seed,
                "employees": len(tables["employees"]),
                "departments": len(tables["departments"]),
                "roles": len(tables["roles"]),
                "managers": len(tables["managers"]),
                "onboarding_cases": len(tables["onboarding_cases"]),
                "task_templates": len(tables["task_templates"]),
                "offboarding_cases": len(tables["offboarding_cases"]),
                "task_instances": len(tables["task_instances"]),
                "task_dependencies": len(tables["task_dependencies"]),
                "assets": len(tables["assets"]),
                "asset_assignments": len(tables["asset_assignments"]),
                "access_requests": len(tables["access_requests"]),
                "approvals": len(tables["approvals"]),
                "audit_events": len(tables["audit_events"]),
                "labelled_anomalies": len(truth),
                "anomaly_types": [
                    row["issue_type"] for row in truth
                ],
            },
            indent=2,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
