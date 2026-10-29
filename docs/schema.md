# Schema and Workflow

## 1. Cardinality and Relationships

The database models employee onboarding and offboarding as connected workflows with explicit ownership, approvals, dependencies, and audit history.

- **Department to Manager:** One department can have many managers. Each manager references one department.
- **Department to Employee:** One department can have many employees. Each employee references one current department.
- **Role to Employee:** One role can be assigned to many employees. Each employee references one role.
- **Role to TaskTemplate:** One role can have multiple task templates. Templates are selected using the role, work location, and task kind.
- **Manager to Employee:** One manager can be associated with many employees. The employee's manager reference is optional so that the designated missing-manager exception can be represented.
- **Employee to OnboardingCase:** Each employee has at most one onboarding case in the schema; the intended workflow creates one for each employee who requires onboarding.
- **Employee to OffboardingCase:** Each employee can have at most one offboarding case.
- **Employee to EmployeeDepartmentHistory:** An employee can have multiple department-history records to preserve transfers and effective-dated changes.
- **Employee to AccessRequest:** An employee can have multiple access requests.
- **Employee to AuditEvent:** An employee can be associated with multiple audit events. Events without a direct employee association may use a null employee reference.
- **Employee to AssetAssignment:** An employee can have multiple historical asset assignments.
- **Employee to TaskInstance:** An employee can be the subject of multiple tasks through `owner_employee_id`.
- **TaskTemplate to TaskInstance:** A template can be referenced by multiple task instances. Template references may be null for exit-specific tasks.
- **OnboardingCase to TaskInstance:** An onboarding case can contain multiple task instances.
- **OnboardingCase to AccessRequest:** An onboarding case can contain multiple access requests.
- **OnboardingCase to AssetAssignment:** An onboarding case can contain multiple asset assignments.
- **OffboardingCase to TaskInstance:** An offboarding case can contain multiple exit tasks.
- **TaskInstance to TaskInstance:** Tasks have a many-to-many dependency relationship through `TaskDependency`. The composite primary key prevents duplicate dependency edges, and self-dependencies are prohibited.
- **Asset to Employee:** Assets and employees have a many-to-many relationship over time through `AssetAssignment`. Assignment records retain assignment and recovery dates.
- **AccessRequest to Approval:** Each access request can have at most one approval record in the current schema. Approval decisions and subsequent workflow changes should also be recorded as audit events.

The database schema enforces declared primary keys, foreign keys, unique constraints, and supported checks. Rules involving workflow state, active manager eligibility, overlapping effective dates, and dependency cycles require additional service or validator logic.

## 2. Effective-Dated Records and Lifecycle History

The application uses the following convention for effective-dated records:

- `effective_from` is inclusive.
- `effective_to` is exclusive.
- A null `effective_to` means there is no recorded end date.

Department changes must preserve history. When an employee transfers, the application closes the prior department-history interval and appends a new record containing the new department, effective start date, and change reason. Historical rows must not be silently deleted.

State transitions should append `AuditEvent` records that identify the affected entity, event type, event date, and relevant old and new values.

The database includes triggers that reject updates and deletions from `audit_events`. Workflow services should write audit events as part of the same logical transaction as the corresponding state change wherever practical.

## 3. Onboarding Workflow

Onboarding tasks are selected from `TaskTemplate` records based on employee role and work location.

Each task instance contains:

- `owner_employee_id`, identifying the employee the task concerns.
- `owner_team`, identifying the responsible operational team.
- `assigned_to_manager_id`, optionally identifying a manager assigned to the task.
- `status`, `created_date`, `due_date`, `completed_date`, and `sla_breached`.
- The applicable onboarding case or offboarding case reference.
- An optional template reference for tasks generated from a template.

### Task dependencies

The following prerequisite relationships are required:

1. `identity_verification` and `manager_approval` precede `account_creation`.
2. `account_creation` and `manager_approval` precede `access_provisioning`.
3. Additional equipment, training, and check-in dependencies are represented explicitly in `TaskDependency`.

The dependency graph must be acyclic. A task cannot be marked completed until its required prerequisite tasks have completed. Workflow services enforce completion rules, and the validator checks dependency references and cycles.

Task due dates and SLA-breach flags must follow one documented calendar-day policy. The validator should compare the stored flags with the applicable due and completion dates.

## 4. Operational Ownership

Both `TaskTemplate` and `TaskInstance` contain an `owner_team` field. The allowed values are `HR`, `IT`, `Facilities`, and `Manager`.

| Task responsibility | Owner team |
|---|---|
| Identity and background verification | HR |
| Security training | HR |
| Account creation and access provisioning | IT |
| Equipment assignment and asset recovery | Facilities |
| Manager approval | Manager |
| First-day check-in | Manager |
| Exit access revocation | IT |

`owner_employee_id` does not identify the person or team responsible for performing the task. It identifies the affected employee. Operational ownership must be interpreted from `owner_team` and, where applicable, `assigned_to_manager_id`.

## 5. Access Approval Rules

Access requests remain pending until an eligible, active manager approves them.

- An approval must reference an existing access request and manager.
- A manager must satisfy the applicable active-state and effective-date requirements when approving.
- Access provisioning must not occur before the required approval is recorded.
- Rejected requests must not result in active access.
- Approval decisions and access-state changes must be recorded in the audit history.

The current schema enforces a maximum of one approval record per access request. If the workflow later requires multiple approval stages or immutable decision history in a dedicated table, the schema must be extended accordingly.

## 6. Offboarding Rules

When an employee is terminated, the workflow should open an offboarding case and initiate the required exit actions.

At minimum, the workflow creates or schedules:

1. **Access revocation**, owned by IT.
2. **Asset recovery**, owned by Facilities.

Active access grants must be revoked according to the offboarding policy. Exit completion is allowed only after both required tasks are complete.

Asset assignments retain their original assignment records and record recovery through `recovered_date`. Recovery must not delete assignment history.

The application and validator should check that employee lifecycle state, offboarding case status, task status, access state, and asset assignment history remain consistent.

## 7. Synthetic Exceptions and Ground Truth

Synthetic exceptions intentionally represent selected violations of business rules. Their affected entity keys and expected handling are documented in `data/ground_truth.csv`.

The ground-truth file is reserved for evaluation. It must not be used by ordinary operational anomaly detection to decide which anomalies to report.

The dashboard's Exceptions view evaluates operational records independently through `services/anomaly_detection.py`. This separation allows the evaluator to compare detected exceptions with the expected cases without the detection process simply reading the answer labels.

The validator may allow known, explicitly labelled synthetic exceptions when evaluating the challenge dataset. It must continue to report unexpected integrity violations rather than broadly ignoring errors.

Examples of challenge-specific exceptions include missing manager assignment, task completion before prerequisites, duplicate active asset assignment, start before background-check completion, active access during offboarding, overdue tasks, and department changes that require effective-dated history.

## 8. Persistence and Exports

`database/schema.sql` defines the relational schema, including primary keys, foreign keys, uniqueness constraints, enumerated-state checks, indexes, and append-only audit triggers.

`database/db.py` provides SQLite connection, initialization, and transaction helpers. Foreign-key enforcement is enabled on each connection.

The deliverable includes:

- Normalized CSV exports.
- Per-table JSON exports.
- `data/seed.sql` for the generated SQL-compatible dataset.
- `database/workflow.db` for local persistent workflow state.

Generated dataset exports and the operational SQLite database serve different purposes. CSV and JSON files support inspection, reproducibility, and evaluation; the SQLite database supports application operations and persisted state changes.

The project should document whether the database file is generated during setup or included as a local artifact. It should not accidentally commit a stale or machine-specific database when the documented workflow expects regeneration.

## 9. Integrity and Validation Responsibilities

Validation is divided between database constraints and application-level rules.

### Database constraints

The schema enforces declared keys, relationships, unique values, enumerated states, positive SLA values, valid boolean-like flags, and selected date-order checks.

### Application services and validator

The services and validator are responsible for checking:

- Valid ISO dates and correct effective-date boundaries.
- Non-overlapping effective-dated history where required.
- Active-manager eligibility for approvals.
- Required approval before access provisioning.
- Task prerequisite completion and dependency-cycle detection.
- SLA-breach calculation and consistency.
- Access revocation and asset recovery during offboarding.
- Consistency between asset assignments and asset lifecycle state.
- Audit records for workflow state changes.
- Reproducibility of generated files and their recorded hashes.
- Required anomaly coverage against the separately maintained ground truth.

A passing database insert or schema constraint does not, by itself, establish that every business rule has been satisfied.

## 10. Summary

The schema separates employee master records, workflow cases, task templates and instances, assets, access requests, approvals, and audit events. Effective-dated history preserves changes, task dependencies represent workflow prerequisites, and operational ownership identifies the responsible team.

Deterministic synthetic data, explicit challenge exceptions, independent anomaly detection, relational integrity, and reproducible exports support the evaluation requirements. The schema, services, validator, and documentation should be maintained together as the implementation evolves.
