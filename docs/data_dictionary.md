# Data Dictionary

## 1. Purpose and Conventions

This document defines the entities, fields, data types, identifiers, relationships, and validation rules used by the Employee Lifecycle Workflow application.

Types use SQLite-compatible names: `TEXT`, `INTEGER`, and ISO-8601 date strings in `YYYY-MM-DD` format. SQLite stores the dates as `TEXT`; date-format validation must be performed by the generator, validator, or application services.

Empty optional dates are represented by SQL `NULL`.

Effective ranges are start-inclusive and end-exclusive. A `NULL` value for `effective_to` indicates that the record has no recorded end date. Identifiers are immutable after creation.

Primary keys, foreign keys, enumerated values, and supported structural constraints are enforced by the relational schema where defined. Other business rules are enforced by application services and the validator.

Challenge-specific synthetic anomaly records are documented separately in `data/ground_truth.csv`. They should remain visible for validation rather than being silently removed from generated datasets.

## 2. Master Records

| Entity | Field | Type | Required | Allowed values / format | Uniqueness | Validation |
|---|---|---|---|---|---|---|
| Department | `department_id` | TEXT | Yes | `DEPT-` plus 3 digits | Primary key | Immutable deterministic identifier |
| Department | `name` | TEXT | Yes | Generated department catalog | Unique | Must match a catalog value |
| Department | `lifecycle_state` | TEXT | Yes | `active`, `inactive` | No | Enum constraint |
| Department | `effective_from` | TEXT | Yes | ISO date | No | Valid calendar date |
| Department | `effective_to` | TEXT | No | ISO date or NULL | No | Must not precede `effective_from` |
| Role | `role_id` | TEXT | Yes | `ROLE-` plus 3 digits | Primary key | Immutable deterministic identifier |
| Role | `name` | TEXT | Yes | Generated role catalog | Unique | Must match a catalog value |
| Role | `lifecycle_state` | TEXT | Yes | `active`, `inactive` | No | Enum constraint |
| Role | `effective_from` | TEXT | Yes | ISO date | No | Valid calendar date |
| Role | `effective_to` | TEXT | No | ISO date or NULL | No | Must not precede `effective_from` |
| Manager | `manager_id` | TEXT | Yes | `MGR-` plus 4 digits | Primary key | Generated manager identifier |
| Manager | `department_id` | TEXT | Yes | Department ID | No | Foreign key to Department |
| Manager | `display_name` | TEXT | Yes | Synthetic label | No | Must not contain real personnel data |
| Manager | `lifecycle_state` | TEXT | Yes | `active`, `inactive` | No | Active status required for new approvals |
| Manager | `effective_from` | TEXT | Yes | ISO date | No | Valid calendar date |
| Manager | `effective_to` | TEXT | No | ISO date or NULL | No | Must not precede `effective_from` |
| Employee | `employee_id` | TEXT | Yes | `EMP-` plus 6 digits | Primary key | Immutable deterministic identifier |
| Employee | `department_id` | TEXT | Yes | Department ID | No | Foreign key; represents current department |
| Employee | `role_id` | TEXT | Yes | Role ID | No | Foreign key to Role |
| Employee | `manager_id` | TEXT | No | Manager ID or NULL | No | Foreign key when present |
| Employee | `employment_type` | TEXT | Yes | `permanent`, `contractor` | No | Enum constraint |
| Employee | `work_location` | TEXT | Yes | `remote`, `on_site` | No | Determines task-template selection |
| Employee | `start_date` | TEXT | Yes | ISO date | No | Compared with onboarding and background-check dates |
| Employee | `lifecycle_state` | TEXT | Yes | `preboarding`, `active`, `terminated` | No | Enum constraint; termination must trigger exit workflow handling |
| Employee | `effective_from` | TEXT | Yes | ISO date | No | Valid calendar date |
| Employee | `effective_to` | TEXT | No | ISO date or NULL | No | Must not precede `effective_from` |
| EmployeeDepartmentHistory | `employee_id` | TEXT | Yes | Employee ID | Composite primary key with `effective_from` | Foreign key to Employee |
| EmployeeDepartmentHistory | `effective_from` | TEXT | Yes | ISO date | Composite primary key with `employee_id` | One record per employee and effective start date |
| EmployeeDepartmentHistory | `department_id` | TEXT | Yes | Department ID | No | Foreign key; records historical department |
| EmployeeDepartmentHistory | `effective_to` | TEXT | No | ISO date or NULL | No | Must not precede `effective_from` |
| EmployeeDepartmentHistory | `change_reason` | TEXT | Yes | `initial_assignment`, `department_transfer` | No | Documents the reason for the history entry |

A missing manager is permitted by the schema so that the designated synthetic anomaly can be represented. Normal workflow processing should flag or resolve missing manager assignments before approval steps that require a manager.

## 3. Workflow Records

### 3.1 OnboardingCase

| Field | Type | Required | Allowed values / format | Validation |
|---|---|---|---|---|
| `case_id` | TEXT | Yes | `ONB-YYYY-` plus 6 digits | Primary key; deterministic sequence |
| `employee_id` | TEXT | Yes | Employee ID | Foreign key; unique onboarding case per employee |
| `created_date` | TEXT | Yes | ISO date | Valid date consistent with case creation |
| `status` | TEXT | Yes | `in_progress`, `completed`, `blocked`, `cancelled` | Enum constraint |
| `effective_from` | TEXT | Yes | ISO date | Valid calendar date |
| `effective_to` | TEXT | No | ISO date or NULL | Must not precede `effective_from` |

### 3.2 TaskTemplate

`TaskTemplate.owner_team` defines the operational team responsible for a task.

| Field | Type | Required | Allowed values / format | Validation |
|---|---|---|---|---|
| `template_id` | TEXT | Yes | Deterministic catalog ID | Primary key |
| `role_id` | TEXT | Yes | Role ID | Foreign key to Role |
| `work_location` | TEXT | Yes | `remote`, `on_site` | Enum constraint |
| `task_kind` | TEXT | Yes | Workflow task catalog | Must match a supported task kind |
| `owner_team` | TEXT | Yes | `HR`, `IT`, `Facilities`, `Manager` | Enum constraint |
| `sla_days` | INTEGER | Yes | Positive calendar-day count | Must be greater than zero |
| `effective_from` | TEXT | Yes | ISO date | Valid calendar date |
| `effective_to` | TEXT | No | ISO date or NULL | Must not precede `effective_from` |

The schema enforces uniqueness for the combination of `role_id`, `work_location`, and `task_kind`.

### 3.3 TaskInstance

`TaskInstance.owner_employee_id` identifies the employee the task concerns, not the operational assignee. `assigned_to_manager_id` identifies the manager assigned to the task, where applicable.

| Field | Type | Required | Allowed values / format | Validation |
|---|---|---|---|---|
| `task_id` | TEXT | Yes | `TASK-ONB-...-NNN` or `TASK-OFF-...-NNN` | Primary key; deterministic within workflow |
| `case_id` | Conditional | TEXT | Onboarding case ID or NULL | Foreign key; set for onboarding tasks |
| `offboarding_case_id` | Conditional | TEXT | Offboarding case ID or NULL | Foreign key; set for offboarding tasks |
| `template_id` | TEXT | No | Template ID or NULL | Foreign key; may be NULL for exit-specific tasks |
| `task_kind` | TEXT | Yes | Task catalog, including `revoke_access` and `recover_assets` where applicable | Valid task for the relevant workflow |
| `owner_team` | TEXT | Yes | `HR`, `IT`, `Facilities`, `Manager` | Enum constraint |
| `assigned_to_manager_id` | TEXT | No | Manager ID or NULL | Foreign key when present |
| `owner_employee_id` | TEXT | Yes | Employee ID | Foreign key to Employee |
| `status` | TEXT | Yes | `not_started`, `in_progress`, `completed`, `blocked` | Enum constraint; prerequisite completion checked by service logic |
| `created_date` | TEXT | Yes | ISO date | Valid calendar date |
| `due_date` | TEXT | Yes | ISO date | Valid date; SLA calculations use the documented calendar-day policy |
| `completed_date` | TEXT | No | ISO date or NULL | Should be present when status is `completed` |
| `sla_breached` | INTEGER | Yes | `0`, `1` | Boolean-like flag derived from due and completion dates |

Exactly one of `case_id` and `offboarding_case_id` must be non-NULL. The schema enforces this condition.

A task should not be completed until its required dependencies have been completed. The dependency graph must be acyclic, and dependency enforcement is handled by workflow services and validation.

Exit revocation is owned by IT. Equipment recovery is owned by Facilities.

### 3.4 TaskDependency

| Field | Type | Required | Allowed values / format | Validation |
|---|---|---|---|---|
| `task_id` | TEXT | Yes | Task ID | Foreign key to TaskInstance |
| `depends_on_task_id` | TEXT | Yes | Task ID | Foreign key to TaskInstance |
| Composite key | TEXT pair | Yes | Both task IDs | Composite primary key |
| Dependency rule | — | Yes | Directed edge between tasks | No self-dependency; cycles rejected by validator |

### 3.5 OffboardingCase

| Field | Type | Required | Allowed values / format | Validation |
|---|---|---|---|---|
| `offboarding_case_id` | TEXT | Yes | `OFF-YYYY-` plus 6 digits | Primary key; deterministic sequence |
| `employee_id` | TEXT | Yes | Employee ID | Foreign key; unique exit case per employee |
| `opened_date` | TEXT | Yes | ISO date | Valid exit date |
| `status` | TEXT | Yes | `open`, `completed` | Enum constraint |
| `effective_from` | TEXT | Yes | ISO date | Valid calendar date |
| `effective_to` | TEXT | No | ISO date or NULL | Must not precede `effective_from` |

An open offboarding case should drive required access revocation, equipment recovery, and other exit tasks. Access must be revoked promptly according to the challenge's exit policy.

## 4. Asset Records

### 4.1 Asset

| Field | Type | Required | Allowed values / format | Validation |
|---|---|---|---|---|
| `asset_id` | TEXT | Yes | `AST-<type>-` plus 6 digits | Primary key; deterministic identifier |
| `asset_type` | TEXT | Yes | `laptop`, `phone`, `badge`, `monitor` | Enum constraint |
| `serial_number` | TEXT | Yes | Synthetic `SN-` value | Unique inventory serial |
| `lifecycle_state` | TEXT | Yes | `available`, `assigned`, `recovered` | Must agree with assignment state |
| `effective_from` | TEXT | Yes | ISO date | Valid calendar date |
| `effective_to` | TEXT | No | ISO date or NULL | Must not precede `effective_from` |

### 4.2 AssetAssignment

| Field | Type | Required | Allowed values / format | Validation |
|---|---|---|---|---|
| `assignment_id` | TEXT | Yes | `ASG-` plus 6 digits | Primary key; immutable record |
| `asset_id` | TEXT | Yes | Asset ID | Foreign key to Asset |
| `employee_id` | TEXT | Yes | Employee ID | Foreign key to Employee |
| `case_id` | TEXT | Yes | Onboarding case ID | Foreign key to OnboardingCase |
| `assigned_date` | TEXT | Yes | ISO date | Valid assignment date |
| `recovered_date` | TEXT | No | ISO date or NULL | Must not precede assignment date |

Assignments are retained as history; recovery must not delete the original assignment record. Normal operations should prevent multiple simultaneous unrecovered assignments for one asset.

The challenge includes a labelled asset-assignment collision. It should be retained as a synthetic anomaly for detection and review, not silently removed to make the data appear valid.

## 5. Access and Approval Records

### 5.1 AccessRequest

| Field | Type | Required | Allowed values / format | Validation |
|---|---|---|---|---|
| `access_request_id` | TEXT | Yes | `ACCREQ-YYYY-` plus 6 digits | Primary key; immutable identifier |
| `employee_id` | TEXT | Yes | Employee ID | Foreign key to Employee |
| `case_id` | TEXT | Yes | Onboarding case ID | Foreign key to OnboardingCase |
| `system_name` | TEXT | Yes | Synthetic system catalog | No credentials stored |
| `requested_date` | TEXT | Yes | ISO date | Approval SLA begins on this date |
| `status` | TEXT | Yes | `pending`, `active`, `revoked`, `rejected` | Enum constraint |
| `effective_from` | TEXT | No | ISO date or NULL | Grant effective date |
| `effective_to` | TEXT | No | ISO date or NULL | Revocation/end date, where applicable |

An access request may become active only after the required approval has been recorded. Offboarding must trigger the appropriate revocation action, even when access was previously approved.

### 5.2 Approval

| Field | Type | Required | Allowed values / format | Validation |
|---|---|---|---|---|
| `approval_id` | TEXT | Yes | `APR-` plus 6 digits | Primary key; immutable identifier |
| `access_request_id` | TEXT | Yes | Access request ID | Foreign key; unique in this schema |
| `approver_manager_id` | TEXT | Yes | Manager ID | Foreign key to Manager |
| `decision` | TEXT | Yes | `approved`, `rejected`, `pending` | Enum constraint |
| `decision_date` | TEXT | No | ISO date or NULL | Should be present for a final decision |
| `sla_days` | INTEGER | Yes | Positive calendar-day count | Must be greater than zero |
| `sla_breached` | INTEGER | Yes | `0`, `1` | Derived from request and decision dates |
| `effective_from` | TEXT | No | ISO date or NULL | Decision effective date |
| `effective_to` | TEXT | No | ISO date or NULL | Must not precede `effective_from` when both are present |

Only an eligible manager should approve a request. Manager eligibility, decision-date requirements, and approval-before-provisioning are business rules that require application-level enforcement.

The current schema allows one approval row per access request. If full approval-decision history is needed, the design should be extended to preserve multiple immutable decision events rather than overwriting a prior decision.

## 6. Audit Records

### 6.1 AuditEvent

| Field | Type | Required | Allowed values / format | Validation |
|---|---|---|---|---|
| `audit_event_id` | TEXT | Yes | `AUD-YYYYMMDD-` plus 6 digits | Primary key; deterministic event sequence |
| `employee_id` | TEXT | No | Employee ID or NULL | Foreign key when employee-associated |
| `event_type` | TEXT | Yes | Event catalog | Describes the recorded action |
| `event_date` | TEXT | Yes | ISO date or documented timestamp | Must follow the application's date convention |
| `entity_type` | TEXT | Yes | Entity discriminator | Identifies the affected entity type |
| `entity_id` | TEXT | Yes | Entity identifier | Identifies the affected record |
| `old_value` | TEXT | No | Previous scalar value or NULL | Snapshot of prior state |
| `new_value` | TEXT | No | New scalar value or NULL | Snapshot of resulting state |

Audit events are append-only. The database schema defines triggers that reject updates and deletions. Workflow services should record state-changing actions in the audit log with enough context to explain the change.

### 6.2 AuditEventSequence

| Field | Type | Required | Allowed values / format | Validation |
|---|---|---|---|---|
| `event_date` | TEXT | Yes | Date key | Primary key |
| `last_sequence` | INTEGER | Yes | Non-negative integer | Tracks the last allocated daily sequence |

Sequence allocation must be transaction-safe to avoid duplicate identifiers when concurrent operations occur.

## 7. Users and Authentication

### 7.1 User

| Field | Type | Required | Allowed values / format | Validation |
|---|---|---|---|---|
| `user_id` | INTEGER | Yes | Auto-increment integer | Primary key |
| `email` | TEXT | Yes | Email address | Unique, case-insensitive comparison |
| `password_hash` | TEXT | Yes | Secure password hash | Never store or expose plaintext passwords |
| `account_role` | TEXT | Yes | `owner`, `member` | Enum constraint |
| `created_at` | TEXT | Yes | SQLite timestamp default | Set automatically on insertion |

Demo credentials are intended only for local evaluation. Production deployments must configure their own secret key and credentials. Password hashes and secrets must not appear in ordinary API responses or logs.

## 8. Relationships and Integrity Rules

The principal relationships are:

- A Department can be referenced by multiple Managers and Employees.
- A Role can be referenced by multiple Employees and TaskTemplates.
- An Employee can have one OnboardingCase and one OffboardingCase.
- An OnboardingCase can contain multiple TaskInstances, AssetAssignments, and AccessRequests.
- An OffboardingCase can contain multiple exit TaskInstances.
- A TaskInstance can depend on other TaskInstances through TaskDependency.
- An AccessRequest can have one Approval row under the current schema.
- An Employee can have multiple department-history records and AuditEvents.
- An Asset can have multiple historical assignments, but normal operations must prevent overlapping active assignments.

## 9. Validation Rules

The generator and validator should check:

1. **Identifier integrity:** IDs match their documented patterns and are unique.
2. **Referential integrity:** Foreign keys reference existing parent records.
3. **Date validity:** Dates are valid ISO calendar dates and effective ranges are correctly ordered.
4. **Effective history:** Department transfers preserve historical records and avoid overlapping effective periods.
5. **Task dependencies:** All dependency references exist, no task depends on itself, and the graph is acyclic.
6. **Task completion:** Tasks cannot be completed before required prerequisites.
7. **SLA compliance:** Task and approval breaches follow a consistent, documented calendar-day policy.
8. **Access control:** Provisioning requires approval, and offboarding triggers access revocation.
9. **Asset integrity:** Normal operations prevent duplicate simultaneous assignments, while labelled challenge collisions remain detectable.
10. **Manager eligibility:** Approval operations verify manager existence, active state, and applicable department/effective-date rules.
11. **Audit integrity:** State changes produce audit records, and historical events cannot be updated or deleted through ordinary database operations.
12. **Reproducibility:** Repeated generation with the same seed and base date produces identical outputs, with matching SHA-256 hashes when the output files are unchanged.
13. **Ground truth:** Required synthetic anomaly cases are present in `data/ground_truth.csv` and are not silently excluded from validation.

## 10. Known Schema Boundaries

The schema enforces many structural constraints, but not every business rule can be guaranteed by table definitions alone.

In particular, the application and validator must handle task dependency completion, dependency cycles, manager eligibility, approval-before-provisioning, immediate exit revocation, lifecycle consistency, date-format validation, and consistency between asset assignment history and asset lifecycle state.

The schema and this dictionary should be updated together whenever fields, allowed values, identifiers, or relationship rules change.
