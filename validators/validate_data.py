"""Validation utilities for Employee Lifecycle Workflow."""

from collections import defaultdict

EXPECTED_ANOMALY_TYPES = {
    "manager_missing",
    "task_before_prerequisite",
    "asset_assigned_twice",
    "start_before_background_check",
    "offboarding_active_access",
    "overdue_task",
    "department_changed_mid_process",
}

PRIMARY_KEYS = {
    "departments": ("department_id",),
    "roles": ("role_id",),
    "managers": ("manager_id",),
    "employees": ("employee_id",),
    "employee_department_history": ("employee_id", "effective_from"),
    "onboarding_cases": ("case_id",),
    "task_templates": ("template_id",),
    "offboarding_cases": ("offboarding_case_id",),
    "task_instances": ("task_id",),
    "task_dependencies": ("task_id", "depends_on_task_id"),
    "assets": ("asset_id",),
    "asset_assignments": ("assignment_id",),
    "access_requests": ("access_request_id",),
    "approvals": ("approval_id",),
    "audit_events": (),
}

FOREIGN_KEYS = {
    "roles": {"department_id": ("departments", "department_id")},
    "employees": {
        "department_id": ("departments", "department_id"),
        "role_id": ("roles", "role_id"),
        "manager_id": ("managers", "manager_id"),
    },
    "employee_department_history": {
        "employee_id": ("employees", "employee_id"),
        "department_id": ("departments", "department_id"),
    },
    "onboarding_cases": {
        "employee_id": ("employees", "employee_id"),
    },
    "offboarding_cases": {
        "employee_id": ("employees", "employee_id"),
    },
    "task_instances": {
        "employee_id": ("employees", "employee_id"),
        "case_id": ("onboarding_cases", "case_id"),
        "offboarding_case_id": (
            "offboarding_cases", "offboarding_case_id"
        ),
        "template_id": ("task_templates", "template_id"),
        "assigned_to_manager_id": ("managers", "manager_id"),
    },
    "task_dependencies": {
        "task_id": ("task_instances", "task_id"),
        "depends_on_task_id": ("task_instances", "task_id"),
    },
    "asset_assignments": {
        "asset_id": ("assets", "asset_id"),
        "employee_id": ("employees", "employee_id"),
    },
    "access_requests": {
        "employee_id": ("employees", "employee_id"),
    },
    "approvals": {
        "employee_id": ("employees", "employee_id"),
        "access_request_id": ("access_requests", "access_request_id"),
        "manager_id": ("managers", "manager_id"),
    },
    "audit_events": {
        "employee_id": ("employees", "employee_id"),
    },
}

def validate_tables(tables, truth, expect_anomalies=None):
    """Return a validation report for generated tables."""
    errors = []
    warnings = []
    counts = {}
    tables = tables or {}
    truth = truth or []

    # Normalize rows to lists of dictionaries.
    normalized = {}
    for name in PRIMARY_KEYS:
        value = tables.get(name, [])
        if hasattr(value, "to_dict"):
            value = value.to_dict(orient="records")
        normalized[name] = list(value or [])
        counts[name] = len(normalized[name])

        if name not in tables:
            errors.append(f"missing required table: {name}")

    # Check primary keys.
        # Check primary keys only for tables that define primary-key columns.
    for table_name, columns in PRIMARY_KEYS.items():
        if not columns:
            continue

        seen = set()

        for index, row in enumerate(normalized[table_name], start=1):
            missing = [
                col for col in columns
                if row.get(col) is None or row.get(col) == ""
            ]

            if missing:
                errors.append(
                    f"{table_name} row {index} missing primary key: "
                    + ", ".join(missing)
                )
                continue

            key = tuple(row[col] for col in columns)

            if key in seen:
                errors.append(
                    f"{table_name} duplicate primary key: {key}"
                )

            seen.add(key)

    # Check foreign keys. Empty optional references are allowed.
    for table_name, relationships in FOREIGN_KEYS.items():
        for column, (parent_table, parent_column) in relationships.items():
            parent_ids = {
                row.get(parent_column)
                for row in normalized[parent_table]
                if row.get(parent_column) not in (None, "")
            }

            for index, row in enumerate(normalized[table_name], start=1):
                value = row.get(column)

                if value not in (None, "") and value not in parent_ids:
                    errors.append(
                        f"invalid foreign key: {table_name}.{column}="
                        f"{value!r} at row {index}; no matching "
                        f"{parent_table}.{parent_column}"
                    )

    # Normalize ground-truth anomaly labels.
    if hasattr(truth, "to_dict"):
        truth = truth.to_dict(orient="records")

    labels = list(truth) if isinstance(truth, (list, tuple)) else []

    label_types = set()
    for label in labels:
        if isinstance(label, dict):
            issue = label.get(
                "issue_type",
                label.get("anomaly_type", label.get("label")),
            )
            if issue:
                label_types.add(str(issue))
        # When unspecified, infer whether anomalies are expected from truth labels.
    if expect_anomalies is None:
        expect_anomalies = bool(labels)

    if expect_anomalies:
        missing_types = EXPECTED_ANOMALY_TYPES - label_types
        if missing_types:
            errors.append(
                "missing expected ground-truth anomaly type(s): "
                + ", ".join(sorted(missing_types))
            )
    elif labels:
        errors.append(
            f"expected a clean dataset, but ground truth contains "
            f"{len(labels)} anomaly label(s)"
        )

    # Basic anomaly checks apply only to datasets expected to be clean.
    if not expect_anomalies:
        for employee in normalized["employees"]:
            if employee.get("manager_id") in (None, ""):
                errors.append(
                    "manager_missing: employee "
                    + str(employee.get("employee_id"))
                    + " has no manager"
                )

        assignments = defaultdict(set)

        for row in normalized["asset_assignments"]:
            asset_id = row.get("asset_id")
            employee_id = row.get("employee_id")
            returned = (
                row.get("returned_at")
                or row.get("recovered_at")
                or row.get("return_date")
            )
            status = str(row.get("status", "")).lower()

            if (
                asset_id
                and employee_id
                and not returned
                and status not in {"returned", "recovered", "closed"}
            ):
                assignments[asset_id].add(employee_id)

        for asset_id, employee_ids in assignments.items():
            if len(employee_ids) > 1:
                errors.append(
                    f"asset_assigned_twice: asset {asset_id} "
                    "has multiple unrecovered assignments"
                )

    return {
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "warnings": warnings,
        "counts": counts,
        "tables": counts,
        "ground_truth_labels": len(labels),
    }

def main():
    """Generate and validate synthetic employee lifecycle data."""
    import argparse
    import json
    from generator.generate_data import generate_rows

    parser = argparse.ArgumentParser(
        description="Validate synthetic employee lifecycle data."
    )
    parser.add_argument("--employees", type=int, default=500)
    parser.add_argument("--seed", type=int, default=20261022)
    parser.add_argument(
        "--no-anomalies",
        action="store_true",
        help="Generate a clean dataset without injected anomalies.",
    )
    args = parser.parse_args()

    try:
        tables, truth = generate_rows(
            args.employees,
            seed=args.seed,
            inject=not args.no_anomalies,
        )
        report = validate_tables(
            tables,
            truth,
            expect_anomalies=not args.no_anomalies,
        )
    except (ValueError, OSError) as exc:
        print(json.dumps({
            "status": "failed",
            "errors": [str(exc)],
        }, indent=2))
        return 1

    print(json.dumps(report, indent=2, default=str))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
