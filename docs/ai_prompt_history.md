# AI Prompt History

This document records the task specification and implementation decisions that guided the development of the Employee Lifecycle Workflow project. It documents the intended requirements and design choices; implementation status is verified separately through source code, validation results, and automated tests.

No real employee records, confidential information, or external personal data were used to create the synthetic dataset.

## 1. Challenge Request

Build an end-to-end employee onboarding and offboarding coordination solution for HR, IT, facilities, managers, approvers, process owners, operations analysts, and system administrators.

The solution should:

- Generate parent records before dependent records.
- Use deterministic identifiers and a fixed random seed.
- Export generated data in CSV, JSON, and SQL-compatible formats.
- Persist workflow state changes and maintain an audit history.
- Enforce task dependencies and access approval requirements.
- Include clearly labelled synthetic edge cases in a separate ground-truth dataset.
- Validate primary keys, foreign keys, joins, lifecycle transitions, and service-level agreement (SLA) rules.
- Document dataset reproducibility, provenance, schema design, validation, and implementation decisions.

## 2. Project Layout Request

Organize the deliverable as a maintainable Flask application with the following components:

- `app.py` — application initialization, routes, authentication, and dashboard APIs.
- `requirements.txt` — Python dependencies required to run the application.
- `database/` — SQLite schema, connection helpers, and persistent workflow state.
- `generator/` — deterministic synthetic-data generation and anomaly injection.
- `services/` — workflow coordination, access approvals, SLA handling, and audit logging.
- `validators/` — dataset integrity and workflow-rule validation.
- `templates/` — login page and operations dashboard.
- `static/` — application styles and frontend assets.
- `tests/` — automated tests for authentication, generation, validation, workflow rules, and application routes.
- `data/` — generated CSV and JSON datasets, ground-truth labels, provenance information, and reproducibility metadata.
- `docs/` — schema documentation, validation results, source manifest information, and AI-use documentation.

The repository should include the necessary source files and documentation while excluding virtual environments, local secrets, caches, and other generated development artifacts that do not belong in version control.

## 3. Login and Interface Request

Provide a sign-in page and a polished operations dashboard inspired at a high level by the supplied OffboardSafe login reference.

The interface must use original project branding and implementation rather than copying the reference site's branding or page implementation.

Authentication requirements:

- Protect the workflow dashboard and relevant APIs using Flask session-based authentication.
- Provide a local demo account for evaluation.
- Store passwords as secure hashes rather than plaintext.
- Keep the Flask secret key and production credentials configurable through environment variables or an equivalent deployment configuration.
- Document how to configure credentials and the secret key for production.
- Avoid exposing passwords, password hashes, or sensitive configuration values through the dashboard or APIs.

The local demo configuration is intended for evaluation only. Production deployments must use their own secret key and appropriately managed credentials.

## 4. Implementation Choices

### Framework and database

Flask and SQLite were selected to keep the application lightweight and straightforward to run locally. SQLite provides relational constraints and persistent storage without requiring a separately managed database server.

### Synthetic data

The dataset uses the fixed seed `20261022` to support reproducible generation. Records use deterministic identifiers and generic synthetic employee and manager labels.

No external employee dataset or real-world personal information was required.

### Generation and exports

Parent records should be created before dependent records to preserve referential integrity. Generated data should be available in the required CSV and JSON formats, with SQL-compatible output where specified.

Reproducibility metadata should record the seed, base date, record counts, and relevant file hashes. Hashes must be recalculated whenever the corresponding files change.

### Workflow integrity

Workflow services are responsible for enforcing task prerequisites, access approvals, asset assignment rules, offboarding actions, and audit logging.

Database constraints provide additional protection against invalid records, but application-level services and validators are also necessary to enforce business rules that cannot be expressed through simple schema constraints.

### Anomaly ground truth

Challenge-specific edge cases are labelled separately from normal operational records. The ground-truth file documents the expected handling of selected synthetic exceptions and should not be exposed through ordinary operational endpoints unless explicitly required.

### Validation and testing

Automated tests and dataset validation are used to check key integrity, relationships, deterministic generation, authentication, task dependencies, approval requirements, and relevant lifecycle rules.

Test results should be reported using the actual output of the test suite. Passing tests alone do not establish that every possible production scenario has been covered.

## 5. Security and Data Handling

- Use synthetic records for demonstration and testing.
- Hash passwords using a suitable password-hashing library.
- Keep production secrets outside source control.
- Protect dashboard and API endpoints that require authentication.
- Validate inputs before applying workflow changes.
- Use parameterized SQL queries for database operations.
- Preserve audit history and prevent unauthorized modification or deletion of audit events.
- Exclude `.venv/`, caches, local database files when appropriate, and secret configuration files from version control.
- Document any limitations of the local demonstration configuration.

## 6. Scope and