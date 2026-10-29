# Validation Report

## 1. Validation Summary

This report records the validation results for the synthetic employee lifecycle workflow dataset containing 500 employees. The validator reported a passed status, no validation errors, and seven known anomalies across seven anomaly types.

```json
{
  "status": "passed",
  "errors": [],
  "row_counts": {
    "departments": 8,
    "roles": 12,
    "managers": 50,
    "employees": 500,
    "employee_department_history": 501,
    "onboarding_cases": 500,
    "task_templates": 192,
    "offboarding_cases": 55,
    "task_instances": 4110,
    "task_dependencies": 3500,
    "assets": 600,
    "asset_assignments": 361,
    "access_requests": 300,
    "approvals": 300,
    "audit_events": 2455
  },
  "known_anomaly_count": 7,
  "anomalies_by_type": {
    "asset_assigned_twice": 1,
    "department_changed_mid_process": 1,
    "manager_missing": 1,
    "offboarding_active_access": 1,
    "overdue_task": 1,
    "start_before_background_check": 1,
    "task_before_prerequisite": 1
  },
  "dependency_edges": 3500,
  "task_sla_breaches": 1586,
  "approval_sla_breaches": 168,
  "access_requests_active": 17
}
```

## 2. Entity Row Counts

| Entity | Row count |
|---|---:|
| Departments | 8 |
| Roles | 12 |
| Managers | 50 |
| Employees | 500 |
| Employee department history | 501 |
| Onboarding cases | 500 |
| Task templates | 192 |
| Offboarding cases | 55 |
| Task instances | 4,110 |
| Task dependencies | 3,500 |
| Assets | 600 |
| Asset assignments | 361 |
| Access requests | 300 |
| Approvals | 300 |
| Audit events | 2,455 |

## 3. Known Anomaly Detection

The validator reported seven known anomalies, with one instance of each expected anomaly type.

| Anomaly type | Count | Expected handling |
|---|---:|---|
| `asset_assigned_twice` | 1 | Hold the conflicting assignment for asset review. |
| `department_changed_mid_process` | 1 | Preserve effective-dated department history. |
| `manager_missing` | 1 | Assign a manager before approval. |
| `offboarding_active_access` | 1 | Revoke active access promptly. |
| `overdue_task` | 1 | Escalate the task and record the SLA breach. |
| `start_before_background_check` | 1 | Delay the start or escalate the unverified employee. |
| `task_before_prerequisite` | 1 | Block task completion until prerequisites are complete. |
| **Total** | **7** | |

The expected handling describes the intended business response. Detection alone does not prove that every remediation action was successfully executed.

## 4. Workflow and SLA Metrics

| Metric | Reported value |
|---|---:|
| Task dependency edges | 3,500 |
| Task SLA breaches | 1,586 |
| Approval SLA breaches | 168 |
| Active access requests | 17 |

SLA breaches identify tasks or approvals requiring review under the configured deadlines. Active access requests represent the reported current state and should be checked against employee lifecycle status and approval decisions.

These metrics are not automatically validation errors. Their significance depends on the workflow rules and whether the relevant records are expected to remain open or overdue.

## 5. Interpretation

The validator reported `passed` with an empty error list and seven detected known anomalies. This indicates that the reported run completed without errors under its configured validation rules while identifying the expected anomaly categories.

The employee department history count is 501 for 500 employees. This is consistent with at least one employee having multiple history records, but the count alone does not prove that the department-change anomaly was represented correctly. Verify the employee's effective dates and history transitions.

Before treating the report as final, confirm that:

- The anomaly counts match `data/ground_truth.csv`.
- Anomaly detection operates on operational records rather than reading the ground-truth labels to produce its results.
- Foreign keys, joins, effective dates, task dependencies, and lifecycle constraints pass validation.
- The seven anomaly records have the expected remediation or escalation behavior.
- SLA metrics and active access requests are consistent with the generated data.

## 6. Reproduction

From the project root in PowerShell, run the commands supported by the project:

```powershell
py generator/generate_data.py --employees 500 --seed 20261022
py validators/validate_data.py --employees 500 --seed 20261022
py -m pytest -q
```

Regenerating data may overwrite existing generated outputs or database state. Preserve any run you need before regenerating, and confirm that the generator and validator support these command-line arguments.

## 7. Provenance

This report documents the supplied validation output for the synthetic employee lifecycle workflow project. The dataset is intended to use deterministic synthetic records and a fixed seed of `20261022`.

The counts and status should be reproducible against the corresponding generated artifacts, validator implementation, and configuration. Update this report whenever a subsequent validation run changes the results.
