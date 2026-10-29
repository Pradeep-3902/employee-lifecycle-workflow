# Validation Clean Report

## 1. Validation Summary

The following report records the validation results for the synthetic employee lifecycle dataset configured for 500 employees.

```json
{
  "status": "passed",
  "errors": [],
  "row_counts": {
    "departments": 8,
    "roles": 12,
    "managers": 50,
    "employees": 500,
    "employee_department_history": 500,
    "onboarding_cases": 500,
    "task_templates": 192,
    "offboarding_cases": 55,
    "task_instances": 4110,
    "task_dependencies": 3500,
    "assets": 600,
    "asset_assignments": 360,
    "access_requests": 300,
    "approvals": 300,
    "audit_events": 2424
  },
  "known_anomaly_count": 0,
  "anomalies_by_type": {},
  "dependency_edges": 3500,
  "task_sla_breaches": 1580,
  "approval_sla_breaches": 167,
  "access_requests_active": 16
}
```

## 2. Record Counts

| Entity | Reported rows |
|---|---:|
| Departments | 8 |
| Roles | 12 |
| Managers | 50 |
| Employees | 500 |
| Employee department history | 500 |
| Onboarding cases | 500 |
| Task templates | 192 |
| Offboarding cases | 55 |
| Task instances | 4,110 |
| Task dependencies | 3,500 |
| Assets | 600 |
| Asset assignments | 360 |
| Access requests | 300 |
| Approvals | 300 |
| Audit events | 2,424 |

## 3. Validation Results

- **Status:** `passed`
- **Reported errors:** 0
- **Reported detected known anomalies:** 0
- **Task dependency edges:** 3,500
- **Task SLA breaches:** 1,580
- **Approval SLA breaches:** 167
- **Active access requests:** 16

The validator reported no errors for this run. SLA breaches and active access requests are reported separately from validation errors because they represent operational states or conditions that may require follow-up.

## 4. Interpretation

A `passed` status indicates that the validator completed without reporting errors under its configured checks. It does not automatically establish that every business rule is satisfied or that every intentionally injected anomaly has been detected.

The reported `known_anomaly_count` of `0` and empty `anomalies_by_type` require particular attention because the challenge dataset includes labelled synthetic edge cases in `data/ground_truth.csv`.

Before treating this report as final evidence, confirm that:

1. The anomaly injector ran successfully.
2. The validator checks the intended anomaly types independently of the ground-truth labels.
3. The known anomalies are present in the generated operational data.
4. The validator's detected anomaly results are compared with the ground-truth expectations.
5. SLA breaches and active access requests are reviewed according to the intended workflow rules.

If known anomalies were expected in this run, zero detections should be investigated rather than described as proof that the dataset is anomaly-free.

## 5. Reproduction

Run the following commands from the project root in PowerShell:

```powershell
py generator/generate_data.py --employees 500 --seed 20261022
py validators/validate_data.py --employees 500 --seed 20261022
py -m pytest -q
```

Record the actual command output and update this report whenever a new validation run produces different results.

## 6. Report Provenance

This document records the validation output supplied for the reported run. The counts and status above should be considered reported results until reproduced against the current generated dataset and validator implementation.
