# Employee Lifecycle Workflow

A small Flask operations console and deterministic synthetic dataset for coordinating employee onboarding, access approvals, equipment, and offboarding. It uses only synthetic records; no personal or external data is collected.

## Run locally

Python 3.10 or later is recommended.

```powershell
cd employee-lifecycle-workflow
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000 and create an account from the registration screen. The first account becomes the workspace owner; subsequent accounts are workspace members. The first app startup initializes `database/workflow.db` and seeds the 500-employee baseline if the database is empty. The local SQLite database is ignored by Git; deterministic CSV/JSON/SQL exports and evaluation ground truth are included.

For deployment, set `APP_ENV=production` and `APP_SECRET_KEY` to a stable, strong random secret. Accounts are stored in the `users` table with Werkzeug salted password hashes. This challenge build supports registration and sign-in; add email verification, password recovery, account administration, and rate limiting before production use.

## Generate and validate data

```powershell
## Generate and validate data

```powershell
python generator/generate_data.py --employees 500 --seed 20261022
python -m validators.validate_data --employees 500 --seed 20261022
python -m validators.validate_data --employees 500 --seed 20261022 --no-anomalies
python -m pytest -q
```

Every generation also writes `data/reproducibility.json`, which records SHA-256 checksums for generated CSV/JSON/SQL inputs and the source manifest. Rerunning the generator with the same seed should produce the same checksum map.
```

Every generation also writes `data/reproducibility.json`, which records SHA-256 checksums for all generated CSV/JSON/SQL inputs and the source manifest. Rerunning the command with the same seed should produce the same checksum map.

Use `--employees 20` for a quick run. All table sizes scale from employee count using the same fixed-seed generator. Use `--no-anomalies` to export a clean baseline. The normal generator injects seven documented edge cases after generating valid baseline records. `data/ground_truth.csv` is kept separate from operational table exports and is never read by the dashboard or anomaly detector. The Exceptions tab runs independent rules over operational records.

## Operational behaviors

- Onboarding task templates are selected by role and remote/on-site location and assigned to HR, IT, Facilities, or Manager. The affected employee is recorded separately from the operational team owner. Task dependency edges are explicit, acyclic, and enforced on completion.
- Access requests require an active manager decision, an assigned employee manager, and a completed access-provisioning task before a grant becomes active. Approval and provisioning are separate audited transitions.
- Offboarding sets the employee state, immediately revokes active access, creates access-revocation and asset-recovery tasks, and records the transition. Completing both tasks closes the exit case.
- Assets use assignment bridge rows. Recoveries retain the assignment and recovery date rather than erasing history.
- Metrics are SQL-derived from current workflow records. Live overdue work uses the system date; stored task/approval SLA flags use the deterministic generator reference date (`2026-10-22`), reported as `sla_reference_date`. Known synthetic anomalies are separately labelled in ground truth.
- The anomaly detector checks manager assignment, dependency order, duplicate active assets, background-check timing, termination access, overdue work, and department transfers without using evaluation labels.

## API

`GET /api/summary`, `/api/tasks`, `/api/access`, `/api/exceptions`, `/api/health`

`POST /api/tasks/<task_id>/status` with `{"status":"completed"}`

`POST /api/access/<request_id>/decision` with `{"decision":"approved"}` or `{"decision":"rejected"}`

`POST /api/employees/<employee_id>/offboard`

`GET /api/export/<table_name>.csv` exports a whitelisted operational table.

See [docs/schema.md](docs/schema.md), [docs/data_dictionary.md](docs/data_dictionary.md), and [docs/validation_report.md](docs/validation_report.md) for modeling rules and generated validation evidence.

## Repository publication

Before submission, create a public GitHub repository, push this folder's source and documentation, and submit that repository URL. Do not commit `.venv/`, the live SQLite database, or generated bulk exports unless you explicitly want reviewers to inspect that snapshot; the generator reproduces them from source.