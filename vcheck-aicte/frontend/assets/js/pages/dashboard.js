import { h, icon, mount } from "../dom.js";
import { api, need } from "../api.js";
import { state, isStaff } from "../state.js";
import { metric, card, empty, btn, skelCards, skelRows, load, errorState, badge } from "../ui.js";
import { barChart, donut, legend, hbars, COLORS } from "../charts.js";
import { applicationsTable } from "./_shared.js";
import * as F from "../fmt.js";

export default async function dashboard({ user }) {
  const root = h("div", { class: "stack lg" });
  const first = user.name.split(" ")[0];
  const head = h("div", { class: "page-h" },
    h("div", null, h("h1", null, `Welcome back, ${first}`), h("p", null, isStaff() ? "Live overview of applications, findings and review workload. Every figure comes from the database." : "Your applications, their validation status and anything that needs your attention.")),
    user.role === "applicant" ? btn("Create New Application", { kind: "primary", icon: "plus", href: "/applications/new" }) : btn("Open review queue", { kind: "primary", icon: "clipboard", href: "/review" }));
  const body = h("div", { class: "stack lg" });
  root.append(head, body);
  load(body, async () => need(await api.get("/dashboard"), ["metrics", "charts", "recent_applications"], "dashboard"), (d) => view(d, user), h("div", { class: "stack lg" }, skelCards(6, "g6"), h("div", { class: "grid g-main" }, skelRows(6), skelRows(6))));
  return root;
}

function view(d, user) {
  const m = d.metrics, c = d.charts, staff = user.role !== "applicant";
  const none = m.total_applications === 0;
  if (none && user.role === "applicant") {
    return h("div", { class: "card" }, empty({ icon: "folder", title: "No applications yet", text: "Create your first application, upload the supporting documents and V-Check will validate them in seconds.", action: btn("Create New Application", { kind: "primary", icon: "plus", href: "/applications/new" }) }));
  }
  const metrics = h("div", { class: "grid g6" },
    metric({ label: "Total Applications", value: m.total_applications, ic: "folder", sub: "all submitted" }),
    metric({ label: "Pending Review", value: m.pending_review, ic: "clipboard", tone: "amber", sub: "awaiting a reviewer" }),
    metric({ label: "Verification Required", value: m.verification_required, ic: "shield", tone: "amber", sub: "open items for a human" }),
    metric({ label: "Corrections Requested", value: m.corrections_requested, ic: "message", tone: "amber", sub: "with the applicant" }),
    metric({ label: "Validated Documents", value: m.validated_documents, ic: "check", tone: "green", sub: "read and extracted" }),
    metric({ label: "Critical Findings", value: m.critical_findings, ic: "alert", tone: m.critical_findings ? "red" : "green", sub: "failed, high severity, open" }));
  const vd = c.validation_distribution, vcolor = { passed: COLORS.green, review_required: COLORS.amber, failed: COLORS.red, not_run: COLORS.gray };
  const vlabel = { passed: "Passed", review_required: "Review required", failed: "Failed", not_run: "Not run" };
  const vitems = vd.map((x) => ({ label: vlabel[x.key], value: x.count, color: vcolor[x.key] }));
  const over = c.applications_over_time;
  const row1 = h("div", { class: "grid g-main" },
    card("Applications over time", over.length ? [barChart(over.map((x) => ({ label: x.date.slice(5), value: x.count }))), h("div", { class: "small muted", style: { marginTop: "6px" } }, "By submission (or creation) date, last 60 days.")] : empty({ icon: "chart", title: "No activity yet", text: "Submitted applications will appear here by date." })),
    card("Validation results", vitems.some((x) => x.value) ? h("div", { class: "row", style: { gap: "18px", flexWrap: "wrap" } }, donut(vitems.filter((x) => x.value > 0), { centerLabel: "applications" }), legend(vitems)) : empty({ icon: "shield", title: "Nothing validated yet" })));
  const cats = c.finding_categories;
  const ps = c.processing_status;
  const row2 = h("div", { class: "grid " + (staff ? "g3" : "g2") },
    card("Finding categories", cats.length ? hbars(cats.map((x) => ({ label: x.category, value: x.count })), { color: COLORS.navy }) : empty({ icon: "checkc", title: "No findings", text: "Applications with no findings show up as passed." })),
    card("Processing status", ps.applications.length ? h("div", { class: "stack sm" }, ps.applications.map((x) => h("div", { class: "row between" }, h("span", null, x.label), h("b", null, x.count))), h("hr", { class: "divider" }), h("div", { class: "f-label" }, "Documents"), ps.documents.map((x) => h("div", { class: "row between" }, h("span", null, F.titleCase(x.status)), h("b", null, x.count)))) : empty({ icon: "layers", title: "No data" })),
    staff ? card("Review workload", c.review_workload?.length ? [hbars(c.review_workload.map((x) => ({ label: x.reviewer, value: x.open })), { color: COLORS.blue }), h("div", { class: "small muted" }, "Open cases per reviewer.")] : empty({ icon: "users", title: "No open cases" })) : null);
  const recent = card("Recent applications", d.recent_applications.length ? applicationsTable(d.recent_applications) : empty({ icon: "folder", title: "No applications" }), { flush: true, actions: btn("View all", { size: "sm", href: "/applications", icon: "arrow" }) });
  return h("div", { class: "stack lg" }, metrics, row1, row2, recent);
}
