import { h, icon } from "../dom.js";
import { api, need } from "../api.js";
import { card, empty, load, skelRows, skelCards, metric } from "../ui.js";
import { barChart, donut, legend, hbars, COLORS } from "../charts.js";
import * as F from "../fmt.js";

export default async function analytics() {
  const body = h("div", { class: "stack lg" });
  load(body, async () => need(await api.get("/analytics"), ["sufficient_data", "issue_types"], "analytics"), view, h("div", { class: "grid g2" }, skelRows(6), skelRows(6)));
  return h("div", { class: "stack lg" }, h("div", { class: "page-h" }, h("div", null, h("h1", null, "Analytics"), h("p", null, "Computed from the application database. No placeholder statistics; demonstration data is synthetic."))), body);
}
function view(a) {
  if (!a.sufficient_data) return card(null, empty({ icon: "chart", title: "Not enough data yet", text: "Analytics appear once applications have been submitted and validated. Nothing is estimated or fabricated.", }));
  const vc = { passed: COLORS.green, review_required: COLORS.amber, failed: COLORS.red, not_run: COLORS.gray }, vl = { passed: "Passed", review_required: "Review required", failed: "Failed", not_run: "Not run" };
  const dist = a.validation_findings.distribution.map((x) => ({ label: vl[x.key], value: x.count, color: vc[x.key] }));
  const dc = { processed: COLORS.green, unreadable: COLORS.amber, rejected: COLORS.red, queued: COLORS.blue, processing: COLORS.blue };
  const noData = (t) => empty({ icon: "chart", title: t });
  return h("div", { class: "stack lg" },
    h("div", { class: "grid g4" }, metric({ label: "Applications", value: a.applications_processed.applications, ic: "folder", sub: "with activity" }), metric({ label: "Validation runs", value: a.applications_processed.total, ic: "refresh", sub: "completed" }),
      metric({ label: "Avg. document read", value: a.processing_time.avg_document_read_ms == null ? "—" : F.ms(a.processing_time.avg_document_read_ms), ic: "clock", sub: "OCR / text read, measured" }), metric({ label: "Distinct issue types", value: a.issue_types.length, ic: "alert", sub: "seen in current findings" })),
    h("div", { class: "grid g2" },
      card("Applications processed", a.applications_processed.by_day.length ? barChart(a.applications_processed.by_day.map((x) => ({ label: x.date.slice(5), value: x.count }))) : noData("No dated activity")),
      card("Validation results", dist.some((x) => x.value) ? h("div", { class: "row", style: { gap: "18px", flexWrap: "wrap" } }, donut(dist.filter((x) => x.value), { centerLabel: "applications" }), legend(dist)) : noData("No validated applications"))),
    h("div", { class: "grid g2" },
      card("Most common issue types", a.issue_types.length ? hbars(a.issue_types.map((x) => ({ label: `${x.rule_id} · ${x.title}`, value: x.count })), { color: COLORS.navy }) : empty({ icon: "checkc", title: "No findings", text: "Every validated application passed." })),
      card("Validation findings by category", a.validation_findings.by_category.length ? hbars(a.validation_findings.by_category.map((x) => ({ label: x.category, value: x.count })), { color: COLORS.blue }) : empty({ icon: "checkc", title: "No findings" }))),
    h("div", { class: "grid g3" },
      card("Documents by status", a.documents_by_status.length ? hbars(a.documents_by_status.map((x) => ({ label: F.titleCase(x.status), value: x.count, color: dc[x.status] })), {}) : noData("No documents")),
      card("Review workload", a.review_workload.length ? hbars(a.review_workload.map((x) => ({ label: x.reviewer, value: x.open })), { color: COLORS.blue }) : empty({ icon: "users", title: "No open cases" })),
      card("Correction cycles", a.correction_cycles.length ? [barChart(a.correction_cycles.map((x) => ({ label: x.cycles + " cycle" + (x.cycles === 1 ? "" : "s"), value: x.applications })), { height: 170, color: COLORS.navy }), h("div", { class: "small muted" }, "Applications by number of correction cycles.")] : noData("No data"))),
    card("Processing time", a.processing_time.validation_by_day.length ? [barChart(a.processing_time.validation_by_day.map((x) => ({ label: x.date.slice(5), value: x.avg_ms })), { height: 170, color: COLORS.sky }), h("div", { class: "small muted" }, "Average end-to-end validation run duration in milliseconds, by day.")] : noData("No runs")),
    h("div", { class: "small muted" }, a.note));
}
