
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL COLLATE NOCASE UNIQUE,
    password_hash TEXT NOT NULL,
    account_role TEXT NOT NULL CHECK (account_role IN ('owner', 'member')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS departments (
    department_id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    lifecycle_state TEXT NOT NULL CHECK (lifecycle_state IN ('active', 'inactive')),
    effective_from TEXT NOT NULL,
    effective_to TEXT,
    CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

CREATE TABLE IF NOT EXISTS roles (
    role_id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    lifecycle_state TEXT NOT NULL CHECK (lifecycle_state IN ('active', 'inactive')),
    effective_from TEXT NOT NULL,
    effective_to TEXT,
    CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

CREATE TABLE IF NOT EXISTS managers (
    manager_id TEXT PRIMARY KEY,
    department_id TEXT NOT NULL REFERENCES departments(department_id),
    display_name TEXT NOT NULL,
    lifecycle_state TEXT NOT NULL CHECK (lifecycle_state IN ('active', 'inactive')),
    effective_from TEXT NOT NULL,
    effective_to TEXT,
    CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

CREATE TABLE IF NOT EXISTS employees (
    employee_id TEXT PRIMARY KEY,
    department_id TEXT NOT NULL REFERENCES departments(department_id),
    role_id TEXT NOT NULL REFERENCES roles(role_id),
    manager_id TEXT REFERENCES managers(manager_id),
    employment_type TEXT NOT NULL CHECK (employment_type IN ('permanent', 'contractor')),
    work_location TEXT NOT NULL CHECK (work_location IN ('remote', 'on_site')),
    start_date TEXT NOT NULL,
    lifecycle_state TEXT NOT NULL CHECK (lifecycle_state IN ('preboarding', 'active', 'terminated')),
    effective_from TEXT NOT NULL,
    effective_to TEXT,
    CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

CREATE INDEX IF NOT EXISTS idx_employees_state
ON employees(lifecycle_state);

CREATE INDEX IF NOT EXISTS idx_employees_manager
ON employees(manager_id);

CREATE TABLE IF NOT EXISTS employee_department_history (
    employee_id TEXT NOT NULL REFERENCES employees(employee_id),
    department_id TEXT NOT NULL REFERENCES departments(department_id),
    effective_from TEXT NOT NULL,
    effective_to TEXT,
    change_reason TEXT NOT NULL,
    PRIMARY KEY (employee_id, effective_from),
    CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

CREATE INDEX IF NOT EXISTS idx_department_history_employee_dates
ON employee_department_history(employee_id, effective_from, effective_to);

CREATE TABLE IF NOT EXISTS onboarding_cases (
    case_id TEXT PRIMARY KEY,
    employee_id TEXT NOT NULL UNIQUE REFERENCES employees(employee_id),
    created_date TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('in_progress', 'completed', 'blocked', 'cancelled')),
    effective_from TEXT NOT NULL,
    effective_to TEXT,
    CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

CREATE TABLE IF NOT EXISTS task_templates (
    template_id TEXT PRIMARY KEY,
    role_id TEXT NOT NULL REFERENCES roles(role_id),
    work_location TEXT NOT NULL CHECK (work_location IN ('remote', 'on_site')),
    task_kind TEXT NOT NULL,
    owner_team TEXT NOT NULL CHECK (owner_team IN ('HR', 'IT', 'Facilities', 'Manager')),
    sla_days INTEGER NOT NULL CHECK (sla_days > 0),
    effective_from TEXT NOT NULL,
    effective_to TEXT,
    UNIQUE(role_id, work_location, task_kind),
    CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

CREATE TABLE IF NOT EXISTS offboarding_cases (
    offboarding_case_id TEXT PRIMARY KEY,
    employee_id TEXT NOT NULL UNIQUE REFERENCES employees(employee_id),
    opened_date TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('open', 'completed')),
    effective_from TEXT NOT NULL,
    effective_to TEXT,
    CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

CREATE TABLE IF NOT EXISTS task_instances (
    task_id TEXT PRIMARY KEY,
    case_id TEXT REFERENCES onboarding_cases(case_id),
    offboarding_case_id TEXT REFERENCES offboarding_cases(offboarding_case_id),
    template_id TEXT REFERENCES task_templates(template_id),
    task_kind TEXT NOT NULL,
    owner_team TEXT NOT NULL CHECK (owner_team IN ('HR', 'IT', 'Facilities', 'Manager')),
    assigned_to_manager_id TEXT REFERENCES managers(manager_id),
    owner_employee_id TEXT NOT NULL REFERENCES employees(employee_id),
    status TEXT NOT NULL CHECK (status IN ('not_started', 'in_progress', 'completed', 'blocked')),
    created_date TEXT NOT NULL,
    due_date TEXT NOT NULL,
    completed_date TEXT,
    sla_breached INTEGER NOT NULL DEFAULT 0 CHECK (sla_breached IN (0, 1)),
    CHECK (
        (case_id IS NOT NULL AND offboarding_case_id IS NULL)
        OR
        (case_id IS NULL AND offboarding_case_id IS NOT NULL)
    ),
    CHECK (completed_date IS NULL OR completed_date >= created_date)
);

CREATE INDEX IF NOT EXISTS idx_tasks_status_due
ON task_instances(status, due_date);

CREATE INDEX IF NOT EXISTS idx_tasks_onboarding_case
ON task_instances(case_id);

CREATE INDEX IF NOT EXISTS idx_tasks_offboarding_case
ON task_instances(offboarding_case_id);

CREATE INDEX IF NOT EXISTS idx_tasks_owner_employee
ON task_instances(owner_employee_id);

CREATE TABLE IF NOT EXISTS task_dependencies (
    task_id TEXT NOT NULL REFERENCES task_instances(task_id),
    depends_on_task_id TEXT NOT NULL REFERENCES task_instances(task_id),
    PRIMARY KEY (task_id, depends_on_task_id),
    CHECK (task_id <> depends_on_task_id)
);

CREATE INDEX IF NOT EXISTS idx_dependencies_prerequisite
ON task_dependencies(depends_on_task_id);

CREATE TABLE IF NOT EXISTS assets (
    asset_id TEXT PRIMARY KEY,
    asset_type TEXT NOT NULL CHECK (asset_type IN ('laptop', 'phone', 'badge', 'monitor')),
    serial_number TEXT NOT NULL UNIQUE,
    lifecycle_state TEXT NOT NULL CHECK (lifecycle_state IN ('available', 'assigned', 'recovered')),
    effective_from TEXT NOT NULL,
    effective_to TEXT,
    CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

CREATE TABLE IF NOT EXISTS asset_assignments (
    assignment_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL REFERENCES assets(asset_id),
    employee_id TEXT NOT NULL REFERENCES employees(employee_id),
    case_id TEXT NOT NULL REFERENCES onboarding_cases(case_id),
    assigned_date TEXT NOT NULL,
    recovered_date TEXT,
    CHECK (recovered_date IS NULL OR recovered_date >= assigned_date)
);

-- Intentionally non-unique: the synthetic dataset includes a labelled
-- duplicate-active-assignment anomaly. Enforce uniqueness in normal workflow
-- operations and report collisions through anomaly detection.
CREATE INDEX IF NOT EXISTS idx_asset_assignments_asset_recovery
ON asset_assignments(asset_id, recovered_date);

CREATE INDEX IF NOT EXISTS idx_assignments_employee
ON asset_assignments(employee_id);

CREATE TABLE IF NOT EXISTS access_requests (
    access_request_id TEXT PRIMARY KEY,
    employee_id TEXT NOT NULL REFERENCES employees(employee_id),
    case_id TEXT NOT NULL REFERENCES onboarding_cases(case_id),
    system_name TEXT NOT NULL,
    requested_date TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'active', 'revoked', 'rejected')),
    effective_from TEXT,
    effective_to TEXT,
    CHECK (
        effective_to IS NULL
        OR effective_from IS NULL
        OR effective_to >= effective_from
    )
);

CREATE INDEX IF NOT EXISTS idx_access_employee_state
ON access_requests(employee_id, status);

CREATE TABLE IF NOT EXISTS approvals (
    approval_id TEXT PRIMARY KEY,
    access_request_id TEXT NOT NULL UNIQUE REFERENCES access_requests(access_request_id),
    approver_manager_id TEXT NOT NULL REFERENCES managers(manager_id),
    decision TEXT NOT NULL CHECK (decision IN ('approved', 'rejected', 'pending')),
    decision_date TEXT,
    sla_days INTEGER NOT NULL CHECK (sla_days > 0),
    sla_breached INTEGER NOT NULL DEFAULT 0 CHECK (sla_breached IN (0, 1)),
    effective_from TEXT,
    effective_to TEXT,
    CHECK (
        effective_to IS NULL
        OR effective_from IS NULL
        OR effective_to >= effective_from
    )
);

CREATE INDEX IF NOT EXISTS idx_approvals_decision
ON approvals(decision, sla_breached);

CREATE TABLE IF NOT EXISTS audit_events (
    audit_event_id TEXT PRIMARY KEY,
    employee_id TEXT REFERENCES employees(employee_id),
    event_type TEXT NOT NULL,
    event_date TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_employee_date
ON audit_events(employee_id, event_date);

CREATE INDEX IF NOT EXISTS idx_audit_entity
ON audit_events(entity_type, entity_id);

CREATE TABLE IF NOT EXISTS audit_event_sequences (
    event_date TEXT PRIMARY KEY,
    last_sequence INTEGER NOT NULL CHECK (last_sequence >= 0)
);

-- Audit events are append-only.
CREATE TRIGGER IF NOT EXISTS audit_events_no_update
BEFORE UPDATE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events are append-only');
END;

CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
BEFORE DELETE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events are append-only');
END;
