
"""Flask dashboard and API for employee lifecycle operations."""

from __future__ import annotations

import csv
import io
import os
import secrets
import sqlite3
from pathlib import Path

from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from database.db import DATABASE_PATH, initialize, transaction
from generator.generate_data import TABLES, export_data, generate_rows
from services.access_control import decide_access
from services.anomaly_detection import detect_exceptions
from services.sla_metrics import dashboard_metrics, dashboard_overview
from services.workflow import complete_exit_task, set_task_status, start_offboarding


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__)

    app.config.from_mapping(
        DATABASE=str(DATABASE_PATH),
        AUTO_SEED=True,
        APP_ENV=os.environ.get("APP_ENV", "development"),
        SECRET_KEY=os.environ.get("APP_SECRET_KEY") or secrets.token_hex(32),
        LOGIN_EMAIL="",
        DEMO_LOGIN_PASSWORD="",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=(
            os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"
        ),
    )

    if test_config:
        app.config.update(test_config)

    initialize(app.config["DATABASE"])

    # Create a test/demo account only when credentials are explicitly configured.
    # Passwords are hashed and existing accounts are never overwritten.
    demo_email = (app.config.get("LOGIN_EMAIL") or "").strip().lower()
    demo_password = app.config.get("DEMO_LOGIN_PASSWORD") or ""

    if demo_email and demo_password:
        with transaction(app.config["DATABASE"]) as connection:
            existing_user = connection.execute(
                "SELECT user_id FROM users WHERE email = ? COLLATE NOCASE",
                (demo_email,),
            ).fetchone()

            if existing_user is None:
                connection.execute(
                    """
                    INSERT INTO users (email, password_hash, account_role)
                    VALUES (?, ?, ?)
                    """,
                    (
                        demo_email,
                        generate_password_hash(demo_password),
                        "owner",
                    ),
                )

    with transaction(app.config["DATABASE"]) as connection:
        has_employees = connection.execute(
            "SELECT 1 FROM employees LIMIT 1"
        ).fetchone()

    if app.config["AUTO_SEED"] and not has_employees:
        tables, truth = generate_rows()

        if Path(app.config["DATABASE"]).resolve() == DATABASE_PATH.resolve():
            export_data(
                tables,
                truth,
                20261022,
                Path(app.config["DATABASE"]),
            )
        else:
            _insert_rows(app.config["DATABASE"], tables)

    def database():
        return transaction(app.config["DATABASE"])

    @app.before_request
    def require_login():
        # Public endpoints required for account creation, authentication,
        # health checks, and static assets.
        if request.endpoint in {"login", "register", "health", "static"}:
            return None

        if session.get("user_id") and session.get("user_email"):
            return None

        if request.path.startswith("/api/") or request.is_json:
            return jsonify({"error": "Authentication required"}), 401

        return redirect(url_for("login"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if session.get("user_id"):
            return redirect(url_for("index"))

        error = None
        email = ""

        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")

            with database() as connection:
                user = connection.execute(
                    """
                    SELECT user_id, email, account_role, password_hash
                    FROM users
                    WHERE email = ? COLLATE NOCASE
                    """,
                    (email,),
                ).fetchone()

            if user and check_password_hash(user["password_hash"], password):
                session.clear()
                session["user_id"] = user["user_id"]
                session["user_email"] = user["email"]
                session["account_role"] = user["account_role"]
                session.permanent = True

                return redirect(url_for("index"))

            error = "The email or password was not recognized."

        return render_template("login.html", error=error, email=email)

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if session.get("user_id"):
            return redirect(url_for("index"))

        error = None
        email = ""

        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            password_confirm = request.form.get("password_confirm", "")

            if not email or "@" not in email or len(email) > 254:
                error = "Enter a valid email address."
            elif len(password) < 10:
                error = "Password must be at least 10 characters long."
            elif password != password_confirm:
                error = "The passwords do not match."
            else:
                try:
                    with database() as connection:
                        user_count = connection.execute(
                            "SELECT COUNT(*) FROM users"
                        ).fetchone()[0]

                        account_role = "owner" if user_count == 0 else "member"

                        cursor = connection.execute(
                            """
                            INSERT INTO users (email, password_hash, account_role)
                            VALUES (?, ?, ?)
                            """,
                            (
                                email,
                                generate_password_hash(password),
                                account_role,
                            ),
                        )
                        user_id = cursor.lastrowid

                    session.clear()
                    session["user_id"] = user_id
                    session["user_email"] = email
                    session["account_role"] = account_role
                    session.permanent = True

                    return redirect(url_for("index"))

                except sqlite3.IntegrityError as error_value:
                    if "UNIQUE constraint failed: users.email" in str(
                        error_value
                    ):
                        error = (
                            "An account with that email already exists. "
                            "Sign in instead."
                        )
                    else:
                        raise

        return render_template("register.html", error=error, email=email)

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            user_email=session.get("user_email"),
            account_role=session.get("account_role", "member"),
        )

    @app.get("/api/summary")
    def summary():
        with database() as connection:
            return jsonify(dashboard_metrics(connection))

    @app.get("/api/dashboard-overview")
    def dashboard_overview_api():
        with database() as connection:
            return jsonify(dashboard_overview(connection))

    @app.get("/api/employees")
    def employees():
        with database() as connection:
            rows = connection.execute(
                """
                SELECT
                    e.employee_id,
                    e.lifecycle_state,
                    e.employment_type,
                    e.work_location,
                    e.start_date,
                    d.name AS department,
                    r.name AS role,
                    m.display_name AS manager
                FROM employees e
                LEFT JOIN departments d USING (department_id)
                LEFT JOIN roles r USING (role_id)
                LEFT JOIN managers m USING (manager_id)
                ORDER BY e.employee_id
                LIMIT 500
                """
            ).fetchall()

            return jsonify([dict(row) for row in rows])

    @app.get("/api/runs")
    def runs():
        with database() as connection:
            rows = connection.execute(
                """
                SELECT
                    o.offboarding_case_id,
                    o.employee_id,
                    o.opened_date,
                    o.status,
                    e.department_id,
                    COUNT(t.task_id) AS task_count,
                    SUM(
                        CASE WHEN t.status = 'completed' THEN 1 ELSE 0 END
                    ) AS completed_tasks,
                    SUM(
                        CASE
                            WHEN t.status <> 'completed'
                             AND t.due_date < '2026-10-22'
                            THEN 1 ELSE 0
                        END
                    ) AS overdue_tasks
                FROM offboarding_cases o
                JOIN employees e USING (employee_id)
                LEFT JOIN task_instances t
                    ON t.offboarding_case_id = o.offboarding_case_id
                GROUP BY o.offboarding_case_id
                ORDER BY o.opened_date DESC
                LIMIT 200
                """
            ).fetchall()

            return jsonify([dict(row) for row in rows])

    @app.get("/api/assets")
    def assets():
        with database() as connection:
            rows = connection.execute(
                """
                SELECT
                    a.asset_id,
                    a.asset_type,
                    a.serial_number,
                    a.lifecycle_state,
                    aa.employee_id,
                    aa.assigned_date,
                    aa.recovered_date,
                    CASE
                        WHEN aa.recovered_date IS NULL
                         AND aa.employee_id IS NOT NULL
                        THEN 1 ELSE 0
                    END AS currently_assigned
                FROM assets a
                LEFT JOIN asset_assignments aa USING (asset_id)
                ORDER BY a.asset_id
                LIMIT 800
                """
            ).fetchall()

            return jsonify([dict(row) for row in rows])

    @app.get("/api/audit")
    def audit_events():
        with database() as connection:
            rows = connection.execute(
                """
                SELECT
                    audit_event_id,
                    employee_id,
                    event_type,
                    event_date,
                    entity_type,
                    entity_id,
                    old_value,
                    new_value
                FROM audit_events
                ORDER BY event_date DESC, audit_event_id DESC
                LIMIT 200
                """
            ).fetchall()

            return jsonify([dict(row) for row in rows])

    @app.get("/api/tasks")
    def tasks():
        status = request.args.get("status", "all")

        query = """
            SELECT
                t.*,
                e.department_id,
                e.work_location,
                e.lifecycle_state AS subject_lifecycle_state
            FROM task_instances t
            LEFT JOIN employees e
                ON e.employee_id = t.owner_employee_id
        """
        params: tuple = ()

        if status != "all":
            query += " WHERE t.status = ?"
            params = (status,)

        query += " ORDER BY t.due_date ASC LIMIT 150"

        with database() as connection:
            rows = connection.execute(query, params).fetchall()
            return jsonify([dict(row) for row in rows])

    @app.get("/api/access")
    def access_requests():
        with database() as connection:
            rows = connection.execute(
                """
                SELECT
                    a.*,
                    e.lifecycle_state,
                    e.department_id,
                    p.decision,
                    p.approver_manager_id,
                    p.sla_breached,
                    CASE
                        WHEN p.approval_id IS NULL THEN 1 ELSE 0
                    END AS approval_missing
                FROM access_requests a
                LEFT JOIN employees e USING (employee_id)
                LEFT JOIN approvals p USING (access_request_id)
                ORDER BY a.requested_date DESC
                LIMIT 100
                """
            ).fetchall()

            return jsonify([dict(row) for row in rows])

    @app.get("/api/exceptions")
    def exceptions():
        with database() as connection:
            return jsonify(detect_exceptions(connection))

    @app.post("/api/tasks/<task_id>/status")
    def update_task(task_id: str):
        payload = request.get_json(silent=True) or {}

        if not isinstance(payload, dict) or not isinstance(
            payload.get("status"), str
        ):
            return jsonify(
                {"error": "JSON body must contain a string status"}
            ), 400

        try:
            with database() as connection:
                if (
                    task_id.startswith("TASK-OFF-")
                    and payload.get("status") == "completed"
                ):
                    complete_exit_task(connection, task_id)
                else:
                    set_task_status(connection, task_id, payload["status"])

            return jsonify({"ok": True})

        except (ValueError, LookupError) as error:
            return jsonify({"error": str(error)}), 400

    @app.post("/api/access/<request_id>/decision")
    def access_decision(request_id: str):
        payload = request.get_json(silent=True) or {}

        if not isinstance(payload, dict) or not isinstance(
            payload.get("decision"), str
        ):
            return jsonify(
                {"error": "JSON body must contain a string decision"}
            ), 400

        supplied_manager_id = payload.get("approver_manager_id")

        if supplied_manager_id is not None and not isinstance(
            supplied_manager_id, str
        ):
            return jsonify(
                {"error": "approver_manager_id must be a string"}
            ), 400

        try:
            with database() as connection:
                approval = connection.execute(
                    """
                    SELECT approver_manager_id
                    FROM approvals
                    WHERE access_request_id = ?
                    """,
                    (request_id,),
                ).fetchone()

                if approval is None:
                    return jsonify({"error": "Approval record not found"}), 404

                recorded_manager_id = approval["approver_manager_id"]

                # Do not let the caller substitute a different approver.
                if (
                    supplied_manager_id
                    and recorded_manager_id
                    and supplied_manager_id != recorded_manager_id
                ):
                    return jsonify(
                        {"error": "Approver does not match the recorded approval"}
                    ), 403

                manager_id = recorded_manager_id or supplied_manager_id or ""

                decide_access(
                    connection,
                    request_id,
                    payload["decision"],
                    manager_id,
                )

            return jsonify({"ok": True})

        except (ValueError, LookupError) as error:
            return jsonify({"error": str(error)}), 400

    @app.post("/api/employees/<employee_id>/offboard")
    def offboard(employee_id: str):
        try:
            with database() as connection:
                case_id = start_offboarding(connection, employee_id)

            return jsonify({"ok": True, "offboarding_case_id": case_id})

        except (ValueError, LookupError) as error:
            return jsonify({"error": str(error)}), 400

    @app.get("/api/export/<table_name>.csv")
    def export_table(table_name: str):
        if table_name not in TABLES:
            return jsonify({"error": "Unknown table"}), 404

        with database() as connection:
            cursor = connection.execute(f"SELECT * FROM {table_name}")
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow([column[0] for column in cursor.description])
            writer.writerows(cursor.fetchall())

        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={table_name}.csv"
            },
        )

    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok"})

    return app


def _insert_rows(database_path: str, tables: dict) -> None:
    with transaction(database_path) as connection:
        for table, rows in tables.items():
            if not rows:
                continue

            columns = list(rows[0])
            placeholders = ",".join("?" for _ in columns)
            column_sql = ",".join(columns)

            connection.executemany(
                f"INSERT INTO {table} ({column_sql}) VALUES ({placeholders})",
                [
                    tuple(row.get(column) for column in columns)
                    for row in rows
                ],
            )


if __name__ == "__main__":
    application = create_app()
    application.run(debug=False, port=5000)
