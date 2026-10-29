
"use strict";

/* =========================================================
   EMPLOYEE LIFECYCLE WORKFLOW
   Main dashboard application
   ========================================================= */

/* ---------- 1. Application state ---------- */

const state = {
  view: "dashboard",
  summary: null,
  overview: null,
  employees: [],
  runs: [],
  assets: [],
  tasks: [],
  access: [],
  audit: [],
  exceptions: [],
  loading: false,
};

const $ = (selector) => document.querySelector(selector);

const escapeHtml = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[character]);

const labels = {
  dashboard: "Dashboard",
  employees: "Employees",
  runs: "Runs",
  assets: "Assets",
  tasks: "My Tasks",
  access: "Accounts & access",
  audit: "Audit logs",
  exceptions: "Exceptions",
  reports: "Reports",
};

const exports = [
  "employees",
  "onboarding_cases",
  "task_instances",
  "assets",
  "asset_assignments",
  "access_requests",
  "approvals",
  "offboarding_cases",
  "audit_events",
];

const viewConfig = {
  dashboard: {
    title: "Dashboard",
    description: "Overview of employee lifecycle operations.",
    kicker: "PEOPLE OPERATIONS",
  },
  employees: {
    title: "Employees",
    description: "Review workforce records, departments, roles, and managers.",
    kicker: "PEOPLE DIRECTORY",
  },
  runs: {
    title: "Offboarding runs",
    description: "Track exit progress, access removal, and equipment recovery.",
    kicker: "EMPLOYEE EXITS",
  },
  assets: {
    title: "Assets",
    description: "Review inventory assignments and recovery status.",
    kicker: "EQUIPMENT INVENTORY",
  },
  tasks: {
    title: "My Tasks",
    description: "Work through assigned HR, IT, Facilities, and manager tasks.",
    kicker: "WORK QUEUE",
  },
  access: {
    title: "Accounts & access",
    description: "Review decisions and active system grants.",
    kicker: "ACCESS CONTROL",
  },
  audit: {
    title: "Audit logs",
    description: "Trace recorded workflow and lifecycle changes.",
    kicker: "APPEND-ONLY HISTORY",
  },
  exceptions: {
    title: "Exceptions",
    description: "Review workflow issues detected from operational records.",
    kicker: "RULE-BASED DETECTION",
  },
  reports: {
    title: "Reports",
    description: "Export operational tables for analysis.",
    kicker: "DATA EXPORTS",
  },
};


/* ---------- 2. Shared utilities ---------- */

function setText(selector, value) {
  const element = $(selector);
  if (element) element.textContent = String(value ?? "");
}

function setHidden(selector, hidden) {
  const element = $(selector);
  if (element) element.hidden = hidden;
}

function setHealth(healthy, message) {
  const indicator = $("#health-indicator");
  if (!indicator) return;

  indicator.title = message;
  indicator.style.background = healthy ? "" : "#bd5149";
  indicator.setAttribute("aria-label", message);
}

function showToast(message, isError = false) {
  const toast = $("#toast");
  if (!toast) return;

  toast.textContent = String(message ?? "");
  toast.style.background = isError ? "#9e463c" : "#263d46";
  toast.setAttribute("role", isError ? "alert" : "status");
  toast.classList.add("show");

  if (showToast.timeout) {
    window.clearTimeout(showToast.timeout);
  }

  showToast.timeout = window.setTimeout(() => {
    toast.classList.remove("show");
  }, 2800);
}


/* ---------- 3. API requests ---------- */

async function api(url, options = {}) {
  const headers = {
    Accept: "application/json",
    ...(options.body ? { "Content-Type": "application/json" } : {}),
    ...(options.headers || {}),
  };

  const response = await fetch(url, {
    ...options,
    headers,
    credentials: "same-origin",
  });

  const contentType = response.headers.get("content-type") || "";
  let body = {};

  if (contentType.includes("application/json")) {
    try {
      body = await response.json();
    } catch {
      throw new Error("The server returned invalid JSON.");
    }
  } else {
    const text = await response.text();

    if (!response.ok) {
      throw new Error(
        text.slice(0, 250) || `Request failed (${response.status}).`
      );
    }

    if (text) {
      throw new Error(
        "Expected a JSON response. Check your Flask route and login session."
      );
    }
  }

  if (!response.ok) {
    throw new Error(
      body.error ||
      body.message ||
      `Request failed (${response.status}).`
    );
  }

  return body;
}

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function asNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

function formatNumber(value) {
  return asNumber(value).toLocaleString();
}

function percentOf(completed, total) {
  if (!asNumber(total)) return 0;

  return Math.min(
    100,
    Math.max(0, Math.round((asNumber(completed) / asNumber(total)) * 100))
  );
}

function getDateLabel() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");

  return `${year}-${month}-${day}`;
}


/* ---------- 4. Status badges and table helpers ---------- */

function badge(value) {
  const original = String(value || "unknown");
  const key = original.toLowerCase().replaceAll(" ", "_");
  const label = original.replaceAll("_", " ");

  return `
    <span class="status status-${escapeHtml(key)}">
      ${escapeHtml(label)}
    </span>
  `;
}

function setTable(headers, rows, emptyMessage, footerText) {
  const tableHead = $("#table-head");
  const tableBody = $("#table-body");

  if (!tableHead || !tableBody) return;

  tableHead.innerHTML = `
    <tr>
      ${headers.map((header) =>
        `<th scope="col">${escapeHtml(header)}</th>`
      ).join("")}
    </tr>
  `;

  tableBody.innerHTML = rows.length
    ? rows.join("")
    : `
      <tr>
        <td class="empty-cell" colspan="${headers.length}">
          ${escapeHtml(emptyMessage)}
        </td>
      </tr>
    `;

  setText("#queue-meta", `${rows.length} RECORDS`);
  setText("#table-footer-text", footerText || `${rows.length} records`);
}

function filtered(rows, fields) {
  const query = ($("#search-input")?.value || "").trim().toLowerCase();

  if (!query) return rows;

  return rows.filter((row) =>
    fields.some((field) =>
      String(row[field] ?? "").toLowerCase().includes(query)
    )
  );
}

function renderEmptyOverview() {
  [
    "#metric-employees",
    "#metric-onboarding",
    "#completion-rate",
    "#metric-attention",
    "#sla-breaches",
    "#late-approvals",
    "#active-access",
    "#metric-exposure",
    "#unrecovered-assets",
  ].forEach((selector) => setText(selector, "—"));
}


/* ---------- 5. Dashboard overview ---------- */

function renderOverview() {
  const summary = state.summary;
  const overview = state.overview;

  if (!summary || !overview) {
    renderEmptyOverview();
    return;
  }

  setText("#metric-employees", formatNumber(summary.employees));
  setText("#metric-onboarding", formatNumber(summary.onboarding_open));

  const completionRate = Math.min(
    100,
    Math.max(0, asNumber(summary.completion_rate))
  );

  setText("#completion-rate", `${completionRate}%`);

  const completionBar = $("#completion-bar");
  if (completionBar) {
    completionBar.style.width = `${completionRate}%`;
    completionBar.setAttribute("role", "progressbar");
    completionBar.setAttribute("aria-valuemin", "0");
    completionBar.setAttribute("aria-valuemax", "100");
    completionBar.setAttribute("aria-valuenow", String(completionRate));
  }

  setText(
    "#metric-attention",
    formatNumber(
      asNumber(summary.overdue_tasks) +
      asNumber(summary.terminated_active_access)
    )
  );

  setText("#sla-breaches", formatNumber(summary.sla_breaches));
  setText("#late-approvals", formatNumber(summary.late_approvals));
  setText("#active-access", formatNumber(summary.active_access));

  setText(
    "#metric-exposure",
    formatNumber(summary.terminated_active_access)
  );

  setText(
    "#unrecovered-assets",
    formatNumber(summary.unrecovered_assets)
  );

  setText("#as-of-date", overview.as_of_date || getDateLabel());

  const taskCount = state.tasks.filter(
    (task) => task.status !== "completed"
  ).length;

  setText("#nav-task-count", taskCount);
  setText("#nav-exception-count", state.exceptions.length);

  /* Task and run status breakdown. */
  const runBreakdown = overview.run_breakdown || {};

  const totalRuns = Object.values(runBreakdown).reduce(
    (sum, value) => sum + asNumber(value),
    0
  );

  const runBreakdownElement = $("#run-breakdown");

  if (runBreakdownElement) {
    runBreakdownElement.innerHTML = [
      ["completed", "Completed"],
      ["in_progress", "In progress"],
      ["pending", "Pending"],
      ["overdue", "Overdue"],
    ].map(([key, title]) => {
      const count = asNumber(runBreakdown[key]);
      const percent = totalRuns
        ? Math.min(100, (count / totalRuns) * 100)
        : 0;

      return `
        <div class="status-row" data-status="${escapeHtml(key)}">
          <span>${escapeHtml(title)}</span>
          <div class="status-track">
            <span style="width:${percent}%"></span>
          </div>
          <strong>${count}</strong>
        </div>
      `;
    }).join("");
  }

  const activeRuns = asNumber(overview.active_runs);

  setText(
    "#active-run-summary",
    activeRuns
      ? `${activeRuns} active offboarding ${
          activeRuns === 1 ? "run" : "runs"
        }`
      : "No active offboarding runs"
  );

  /* Six-month timeline. */
  const timeline = asArray(overview.timeline);
  const timelineChart = $("#timeline-chart");

  if (timelineChart) {
    const maxRuns = Math.max(
      1,
      ...timeline.map((item) => asNumber(item.runs))
    );

    timelineChart.innerHTML = timeline.map((item) => {
      const runs = asNumber(item.runs);
      const height = runs
        ? Math.max(8, (runs / maxRuns) * 88)
        : 3;

      return `
        <div class="timeline-column">
          <span class="timeline-count">${runs || ""}</span>
          <div class="timeline-bar-wrap">
            <span
              class="timeline-bar"
              style="height:${height}%"
              title="${escapeHtml(runs)} runs"
            ></span>
          </div>
          <span class="timeline-month">
            ${escapeHtml(item.label || "")}
          </span>
        </div>
      `;
    }).join("");
  }

  const firstMonth = timeline[0];
  const lastMonth = timeline[timeline.length - 1];

  setText(
    "#timeline-period",
    firstMonth && lastMonth
      ? `${firstMonth.label} – ${lastMonth.label} ${
          String(lastMonth.month || "").slice(0, 4)
        }`
      : "Last six months"
  );

  /* Recent offboarding runs. */
  const recentRuns = asArray(overview.recent_runs);

  setHidden("#empty-runs", recentRuns.length > 0);

  const recentRunsBody = $("#recent-runs-body");

  if (recentRunsBody) {
    recentRunsBody.innerHTML = recentRuns.map((run, index) => {
      const status = run.display_status || run.status || "pending";
      const progress = percentOf(
        run.completed_tasks,
        run.task_count
      );

      return `
        <tr style="animation-delay:${Math.min(index, 8) * 18}ms">
          <td>
            <span class="task-title">
              ${escapeHtml(run.offboarding_case_id)}
            </span>
            <span class="table-subline">
              ${asNumber(run.task_count)} exit tasks
            </span>
          </td>
          <td>${escapeHtml(run.employee_id)}</td>
          <td>${escapeHtml(run.department_id)}</td>
          <td>${escapeHtml(run.opened_date)}</td>
          <td>${progress}%</td>
          <td>${badge(status)}</td>
        </tr>
      `;
    }).join("");
  }
}


/* ---------- 6. Employee directory ---------- */

function renderEmployees() {
  const rows = filtered(state.employees, [
    "employee_id",
    "department",
    "role",
    "manager",
    "lifecycle_state",
    "employment_type",
  ]);

  setTable(
    [
      "EMPLOYEE",
      "DEPARTMENT",
      "ROLE",
      "MANAGER",
      "TYPE",
      "START DATE",
      "STATUS",
    ],
    rows.map((row) => `
      <tr>
        <td>
          <span class="task-title">
            ${escapeHtml(row.employee_id)}
          </span>
        </td>
        <td>${escapeHtml(row.department)}</td>
        <td>${escapeHtml(row.role)}</td>
        <td>${escapeHtml(row.manager || "Unassigned")}</td>
        <td>${escapeHtml(row.employment_type)}</td>
        <td>${escapeHtml(row.start_date)}</td>
        <td>${badge(row.lifecycle_state)}</td>
      </tr>
    `),
    "No employee records match this search.",
    `${rows.length} employees`
  );
}


/* ---------- 7. Offboarding runs ---------- */

function renderRuns() {
  const rows = filtered(state.runs, [
    "offboarding_case_id",
    "employee_id",
    "department_id",
    "opened_date",
    "status",
  ]);

  setTable(
    [
      "RUN",
      "EMPLOYEE",
      "DEPARTMENT",
      "OPENED",
      "TASKS",
      "PROGRESS",
      "STATUS",
    ],
    rows.map((row) => {
      const progress = percentOf(
        row.completed_tasks,
        row.task_count
      );

      const runStatus = row.status === "completed"
        ? "completed"
        : asNumber(row.overdue_tasks) > 0
          ? "overdue"
          : asNumber(row.completed_tasks) > 0
            ? "in_progress"
            : "pending";

      return `
        <tr>
          <td class="mono">
            ${escapeHtml(row.offboarding_case_id)}
          </td>
          <td>${escapeHtml(row.employee_id)}</td>
          <td>${escapeHtml(row.department_id)}</td>
          <td>${escapeHtml(row.opened_date)}</td>
          <td>
            ${asNumber(row.completed_tasks)}/${asNumber(row.task_count)}
          </td>
          <td>${progress}%</td>
          <td>${badge(runStatus)}</td>
        </tr>
      `;
    }),
    "No offboarding runs yet. Start an exit from the dashboard.",
    `${rows.length} runs`
  );
}


/* ---------- 8. Asset inventory ---------- */

function renderAssets() {
  const rows = filtered(state.assets, [
    "asset_id",
    "asset_type",
    "serial_number",
    "lifecycle_state",
    "employee_id",
  ]);

  setTable(
    [
      "ASSET",
      "TYPE",
      "SERIAL NUMBER",
      "ASSIGNED TO",
      "ASSIGNED DATE",
      "STATE",
    ],
    rows.map((row) => {
      const status = row.recovered_date
        ? "recovered"
        : row.employee_id
          ? "assigned"
          : row.lifecycle_state || "available";

      return `
        <tr>
          <td class="mono">${escapeHtml(row.asset_id)}</td>
          <td>${escapeHtml(row.asset_type)}</td>
          <td class="mono">${escapeHtml(row.serial_number)}</td>
          <td>${escapeHtml(row.employee_id || "—")}</td>
          <td>${escapeHtml(row.assigned_date || "—")}</td>
          <td>${badge(status)}</td>
        </tr>
      `;
    }),
    "No assets match this search.",
    `${rows.length} assignment and inventory records`
  );
}


/* ---------- 9. Workflow tasks ---------- */

function renderTasks() {
  const selectedStatus = $("#status-filter")?.value || "all";

  const matchingStatus = state.tasks.filter(
    (row) => selectedStatus === "all" || row.status === selectedStatus
  );

  const rows = filtered(matchingStatus, [
    "task_id",
    "task_kind",
    "owner_team",
    "owner_employee_id",
    "department_id",
  ]);

  setTable(
    [
      "TASK / CASE",
      "RESPONSIBLE TEAM",
      "SUBJECT",
      "DUE DATE",
      "STATE",
      "ACTION",
    ],
    rows.map((row, index) => {
      const taskId = escapeHtml(row.task_id);
      const completed = row.status === "completed";

      return `
        <tr style="animation-delay:${Math.min(index, 10) * 18}ms">
          <td>
            <span class="task-title">
              ${escapeHtml(String(row.task_kind || "").replaceAll("_", " "))}
            </span>
            <span class="table-subline mono">${taskId}</span>
          </td>
          <td>${escapeHtml(row.owner_team)}</td>
          <td>
            ${escapeHtml(row.owner_employee_id)}
            ·
            ${escapeHtml(row.department_id || "—")}
          </td>
          <td class="mono ${row.sla_breached ? "text-alert" : ""}">
            ${escapeHtml(row.due_date)}
          </td>
          <td>${badge(row.status)}</td>
          <td>
            ${
              completed
                ? "—"
                : `
                  <button
                    type="button"
                    class="row-action"
                    data-action="complete-task"
                    data-id="${taskId}"
                  >
                    Complete
                  </button>
                `
            }
          </td>
        </tr>
      `;
    }),
    "No tasks match this search.",
    `${rows.length} tasks`
  );
}


/* ---------- 10. Accounts and access ---------- */

function renderAccess() {
  const rows = filtered(state.access, [
    "access_request_id",
    "employee_id",
    "system_name",
    "department_id",
    "approver_manager_id",
  ]);

  setTable(
    [
      "REQUEST / SYSTEM",
      "EMPLOYEE",
      "APPROVER",
      "REQUESTED",
      "STATUS",
      "DECISION",
    ],
    rows.map((row) => {
      const canDecide =
        row.status === "pending" &&
        (row.decision || "pending") === "pending";

      const actionButtons = canDecide
        ? `
          <button
            type="button"
            class="row-action"
            data-action="approve"
            data-id="${escapeHtml(row.access_request_id)}"
          >
            Approve
          </button>
          <button
            type="button"
            class="row-action"
            data-action="reject"
            data-id="${escapeHtml(row.access_request_id)}"
          >
            Reject
          </button>
        `
        : badge(row.decision || "missing");

      return `
        <tr>
          <td>
            <span class="task-title">
              ${escapeHtml(row.system_name)}
            </span>
            <span class="table-subline mono">
              ${escapeHtml(row.access_request_id)}
            </span>
          </td>
          <td>
            ${escapeHtml(row.employee_id)}
            ·
            ${escapeHtml(row.department_id)}
          </td>
          <td>${escapeHtml(row.approver_manager_id || "Missing")}</td>
          <td>${escapeHtml(row.requested_date)}</td>
          <td>${badge(row.status)}</td>
          <td>${actionButtons}</td>
        </tr>
      `;
    }),
    "No access requests match this search.",
    `${rows.length} access requests`
  );
}


/* ---------- 11. Audit history ---------- */

function renderAudit() {
  const rows = filtered(state.audit, [
    "audit_event_id",
    "employee_id",
    "event_type",
    "entity_type",
    "entity_id",
  ]);

  setTable(
    [
      "EVENT",
      "DATE",
      "EMPLOYEE",
      "ACTION",
      "RECORD",
      "CHANGE",
    ],
    rows.map((row) => `
      <tr>
        <td class="mono">${escapeHtml(row.audit_event_id)}</td>
        <td>${escapeHtml(row.event_date)}</td>
        <td>${escapeHtml(row.employee_id || "—")}</td>
        <td>
          ${escapeHtml(String(row.event_type || "").replaceAll("_", " "))}
        </td>
        <td>
          ${escapeHtml(row.entity_type)}
          ·
          ${escapeHtml(row.entity_id)}
        </td>
        <td>
          ${escapeHtml(row.old_value || "—")}
          →
          ${escapeHtml(row.new_value || "—")}
        </td>
      </tr>
    `),
    "No audit events match this search.",
    `${rows.length} recent audit events`
  );
}


/* ---------- 12. Exception monitoring ---------- */

function renderExceptions() {
  const rows = filtered(state.exceptions, [
    "issue_type",
    "entity_id",
    "expected_action",
  ]);

  setTable(
    [
      "EXCEPTION",
      "RECORD",
      "RECOMMENDED ACTION",
      "STATE",
    ],
    rows.map((row) => `
      <tr>
        <td>
          <span class="task-title">
            ${escapeHtml(String(row.issue_type || "").replaceAll("_", " "))}
          </span>
        </td>
        <td class="mono">
          ${escapeHtml(row.entity_type)}
          ·
          ${escapeHtml(row.entity_id)}
        </td>
        <td>${escapeHtml(row.expected_action)}</td>
        <td>${badge("detected")}</td>
      </tr>
    `),
    "No detected exceptions match this search.",
    `${rows.length} detected exceptions`
  );
}


/* ---------- 13. Reports and CSV exports ---------- */

function renderReports() {
  const reportLinks = $("#report-links");
  if (!reportLinks) return;

  reportLinks.innerHTML = exports.map((table) => `
    <a
      class="report-link"
      href="/api/export/${encodeURIComponent(table)}.csv"
    >
      <span>${escapeHtml(table.replaceAll("_", " "))}</span>
      <span aria-hidden="true">↓</span>
    </a>
  `).join("");
}


/* ---------- 14. View switching ---------- */

function renderView() {
  const config = viewConfig[state.view] || viewConfig.dashboard;

  setText("#page-title", config.title);
  setText("#breadcrumb-current", config.title);
  setText("#page-description", config.description);
  setText("#page-eyebrow", config.kicker);

  let hideWelcome = false;

  try {
    hideWelcome = sessionStorage.getItem("hide-welcome") === "1";
  } catch {
    // The dashboard remains usable if session storage is unavailable.
  }

  const isDashboard = state.view === "dashboard";

  setHidden("#welcome-banner", !isDashboard || hideWelcome);
  setHidden("#metric-grid", !isDashboard);
  setHidden("#overview-grid", !isDashboard);
  setHidden("#recent-panel", !isDashboard);
  setHidden("#dashboard-bottom", !isDashboard);

  setHidden(
    "#directory-panel",
    isDashboard || state.view === "reports"
  );

  setHidden("#report-panel", state.view !== "reports");

  setHidden(
    "#quick-action-panel",
    !isDashboard && state.view !== "runs"
  );

  setHidden("#task-filters", state.view !== "tasks");

  setHidden(
    "#create-run-button",
    !["dashboard", "runs"].includes(state.view)
  );

  switch (state.view) {
    case "dashboard":
      renderOverview();
      break;
    case "employees":
      renderEmployees();
      break;
    case "runs":
      renderRuns();
      break;
    case "assets":
      renderAssets();
      break;
    case "tasks":
      renderTasks();
      break;
    case "access":
      renderAccess();
      break;
    case "audit":
      renderAudit();
      break;
    case "exceptions":
      renderExceptions();
      break;
    case "reports":
      renderReports();
      break;
  }
}

function navigate(view) {
  if (!viewConfig[view]) return;

  state.view = view;

  document.querySelectorAll(".nav-item").forEach((item) => {
    const active = item.dataset.view === view;

    item.classList.toggle("active", active);

    if (active) {
      item.setAttribute("aria-current", "page");
    } else {
      item.removeAttribute("aria-current");
    }
  });

  $("#sidebar")?.classList.remove("open");

  renderView();
}


/* ---------- 15. Load and refresh dashboard data ---------- */

async function refresh() {
  if (state.loading) return;

  state.loading = true;

  const refreshButton = $("#refresh-button");

  if (refreshButton) {
    refreshButton.disabled = true;
    refreshButton.setAttribute("aria-busy", "true");
  }

  try {
    const endpoints = [
      ["summary", "/api/summary", true],
      ["overview", "/api/dashboard-overview", true],
      ["employees", "/api/employees", false],
      ["runs", "/api/runs", false],
      ["assets", "/api/assets", false],
      ["tasks", "/api/tasks", false],
      ["access", "/api/access", false],
      ["audit", "/api/audit", false],
      ["exceptions", "/api/exceptions", false],
    ];

    const results = await Promise.allSettled(
      endpoints.map(([, url]) => api(url))
    );

    const failedRequired = [];

    results.forEach((result, index) => {
      const [key, , required] = endpoints[index];

      if (result.status === "fulfilled") {
        if (key === "summary" || key === "overview") {
          state[key] = result.value;
        } else {
          state[key] = asArray(result.value);
        }
      } else {
        if (required) {
          failedRequired.push(key);
        } else {
          state[key] = [];
        }
      }
    });

    if (failedRequired.length) {
      throw new Error(
        `Unable to load ${failedRequired.join(" and ")}. Check your Flask API and login session.`
      );
    }

    setHealth(true, "Workflow database connected");
    renderView();

    const optionalFailures = results
      .map((result, index) =>
        result.status === "rejected" ? endpoints[index][0] : null
      )
      .filter(Boolean);

    if (optionalFailures.length) {
      showToast(
        `Some sections could not load: ${optionalFailures.join(", ")}.`,
        true
      );
    }
  } catch (error) {
    setHealth(false, "Workflow service unavailable");
    showToast(error.message || "Unable to load dashboard.", true);
  } finally {
    state.loading = false;

    if (refreshButton) {
      refreshButton.disabled = false;
      refreshButton.removeAttribute("aria-busy");
    }
  }
}


/* ---------- 16. Navigation event listeners ---------- */

document.querySelectorAll(".nav-item").forEach((item) => {
  item.addEventListener("click", () => {
    navigate(item.dataset.view);
  });
});

document.querySelectorAll("[data-navigate]").forEach((item) => {
  item.addEventListener("click", () => {
    navigate(item.dataset.navigate);
  });
});

document.querySelectorAll("[data-action='create-run']").forEach((item) => {
  item.addEventListener("click", () => {
    navigate("dashboard");
    $("#employee-id")?.focus();
  });
});


/* ---------- 17. Search and filters ---------- */

$("#status-filter")?.addEventListener("change", renderTasks);

$("#search-input")?.addEventListener("input", () => {
  switch (state.view) {
    case "employees":
      renderEmployees();
      break;
    case "runs":
      renderRuns();
      break;
    case "assets":
      renderAssets();
      break;
    case "tasks":
      renderTasks();
      break;
    case "access":
      renderAccess();
      break;
    case "audit":
      renderAudit();
      break;
    case "exceptions":
      renderExceptions();
      break;
  }
});


/* ---------- 18. Refresh and download controls ---------- */

$("#refresh-button")?.addEventListener("click", refresh);

$("#download-queue")?.addEventListener("click", () => {
  const tableByView = {
    employees: "employees",
    runs: "offboarding_cases",
    assets: "assets",
    tasks: "task_instances",
    access: "access_requests",
    audit: "audit_events",
    exceptions: "audit_events",
  };

  const table = tableByView[state.view] || "task_instances";

  window.location.assign(
    `/api/export/${encodeURIComponent(table)}.csv`
  );
});

$("#create-run-button")?.addEventListener("click", () => {
  if (!["dashboard", "runs"].includes(state.view)) {
    navigate("dashboard");
  }

  $("#employee-id")?.focus();

  $("#quick-action-panel")?.scrollIntoView({
    behavior: "smooth",
    block: "center",
  });
});

$("#mobile-menu")?.addEventListener("click", () => {
  $("#sidebar")?.classList.toggle("open");
});

$("#dismiss-welcome")?.addEventListener("click", () => {
  try {
    sessionStorage.setItem("hide-welcome", "1");
  } catch {
    // Dismissal still works for the current page.
  }

  setHidden("#welcome-banner", true);
});


/* ---------- 19. Task completion and access decisions ---------- */

$("#table-body")?.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");

  if (!button || button.disabled) return;

  const action = button.dataset.action;
  const recordId = button.dataset.id;

  if (!recordId) {
    showToast("Missing record identifier.", true);
    return;
  }

  button.disabled = true;
  button.setAttribute("aria-busy", "true");

  try {
    if (action === "complete-task") {
      await api(
        `/api/tasks/${encodeURIComponent(recordId)}/status`,
        {
          method: "POST",
          body: JSON.stringify({ status: "completed" }),
        }
      );

      showToast("Task completion recorded.");
    } else if (action === "approve" || action === "reject") {
      await api(
        `/api/access/${encodeURIComponent(recordId)}/decision`,
        {
          method: "POST",
          body: JSON.stringify({
            decision: action === "approve" ? "approved" : "rejected",
          }),
        }
      );

      showToast(
        action === "approve"
          ? "Access decision submitted."
          : "Access request rejected."
      );
    } else {
      return;
    }

    await refresh();
  } catch (error) {
    showToast(error.message || "Unable to update workflow.", true);
    button.disabled = false;
    button.removeAttribute("aria-busy");
  }
});


/* ---------- 20. Start employee offboarding ---------- */

$("#offboard-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();

  const employeeInput = $("#employee-id");
  const submitButton = event.submitter ||
    $("#offboard-form button[type='submit']");

  const employeeId = employeeInput?.value.trim();
  const message = $("#offboard-message");

  if (!employeeId) {
    if (message) {
      message.textContent = "Enter an employee ID.";
      message.classList.add("error");
    }

    employeeInput?.focus();
    return;
  }

  if (submitButton?.disabled) return;

  if (message) {
    message.textContent = "";
    message.classList.remove("error");
  }

  if (submitButton) {
    submitButton.disabled = true;
    submitButton.setAttribute("aria-busy", "true");
  }

  try {
    const result = await api(
      `/api/employees/${encodeURIComponent(employeeId)}/offboard`,
      {
        method: "POST",
        body: JSON.stringify({}),
      }
    );

    const caseId = result.offboarding_case_id || "created";

    if (message) {
      message.textContent =
        `Exit ${caseId} opened; active access revoked.`;
    }

    if (employeeInput) employeeInput.value = "";

    showToast("Offboarding request processed.");

    await refresh();
  } catch (error) {
    if (message) {
      message.textContent = error.message || "Unable to start offboarding.";
      message.classList.add("error");
    }

    showToast(error.message || "Offboarding failed.", true);
  } finally {
    if (submitButton) {
      submitButton.disabled = false;
      submitButton.removeAttribute("aria-busy");
    }
  }
});


/* ---------- 21. Initial application startup ---------- */

setText("#as-of-date", getDateLabel());

try {
  setHidden(
    "#welcome-banner",
    sessionStorage.getItem("hide-welcome") === "1"
  );
} catch {
  // Continue normally if browser storage is unavailable.
}

refresh();
