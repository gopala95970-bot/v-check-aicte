import { h, icon, mount } from "../dom.js";
import { api, need } from "../api.js";
import { state, isStaff } from "../state.js";
import { navigate, query, setQuery, onCleanup } from "../router.js";
import { btn, busy, card, empty, errorState, kv, tabs, appStatusBadge, validationBadge, badge, toast, skelRows, docStatusBadge, load } from "../ui.js";
import { findingList, pipelineView, docRow, findingCard } from "./_shared.js";
import * as F from "../fmt.js";

export default async function appdetail({ params, user }) {
  const id = params.id;
  const root = h("div", { class: "stack lg" });
  let a;
  try { a = need(await api.get("/applications/" + id), ["id", "status", "institution", "findings"], "application"); }
  catch (e) { return e.status === 404 ? empty({ icon: "search", title: "Application not found", text: "It may not exist, or you may not have access to it.", action: btn("Back to applications", { href: "/applications", kind: "primary" }) }) : errorState(e, () => navigate(location.pathname)); }
  let tab = query().tab || "overview", timer = null;
  const header = h("div"), banner = h("div"), body = h("div");
  root.append(header, banner, body);
  onCleanup(() => clearInterval(timer));

  async function refresh(redraw = true) {
    a = await api.get("/applications/" + id);
    drawHeader();
    if (a.processing) { if (!timer) timer = setInterval(() => refresh(true).catch(() => {}), 1000); } else if (timer) { clearInterval(timer); timer = null; toast(`Validation finished: ${a.status_label}.`); }
    if (redraw) drawTab();
  }
  function drawHeader() {
    const editable = user.role === "applicant" && ["draft", "corrections_requested"].includes(a.status);
    mount(header, h("div", { class: "crumbs" }, h("a", { href: "/applications" }, "Applications"), " / ", a.id),
      h("div", { class: "page-h" }, h("div", null, h("h1", { "data-app-title": "" }, a.institution.name), h("div", { class: "row wrap", style: { marginTop: "8px", gap: "10px" } }, h("span", { class: "mono strong" }, a.id), h("span", { class: "muted" }, a.reference), appStatusBadge(a.status, a.status_label), validationBadge(a.validation), a.escalated ? badge("Escalated", "red", "flag") : null, a.demo_scenario ? badge("Demo scenario: " + F.titleCase(a.demo_scenario).replace(/\bId\b/, "ID"), "outline", "info") : null)),
        h("div", { class: "row wrap" }, editable ? btn(a.status === "draft" ? "Continue editing" : "Edit & resubmit", { kind: "primary", icon: "pencil", href: "/applications/new?draft=" + a.id }) : null,
          isStaff() ? btn("Open in reviewer workspace", { kind: "primary", icon: "clipboard", href: "/review?app=" + a.id }) : null)));
    const msgs = [];
    if (a.processing) msgs.push(h("div", { class: "banner", "data-processing": "", role: "status" }, h("span", { class: "spinner" }), h("div", null, h("b", null, "Validation is running. "), "This page updates automatically.")));
    if (a.status === "corrections_requested" && a.correction_request) msgs.push(h("div", { class: "banner warn", "data-correction": "" }, icon("message"), h("div", null, h("b", null, "Corrections requested: "), a.correction_request.remarks, h("div", { class: "small", style: { marginTop: "4px" } }, "Update the application or replace documents, then resubmit."))));
    if (a.decision) msgs.push(h("div", { class: "banner " + (a.status === "approved_demo" ? "ok" : "err") }, icon(a.status === "approved_demo" ? "checkc" : "xc"), h("div", null, h("b", null, a.status_label + ". "), a.decision.remarks, h("div", { class: "small", style: { marginTop: "4px" } }, `Recorded by ${a.decision.by} on ${F.dateTime(a.decision.at)}. This is a demonstration outcome, not an official AICTE decision.`))));
    mount(banner, h("div", { class: "stack sm" }, msgs)); banner.classList.toggle("hide", !msgs.length);
  }
  function drawTab() {
    const items = [{ id: "overview", label: "Overview" }, { id: "documents", label: "Documents", count: a.document_count }, { id: "findings", label: "Findings", count: a.findings.total }, { id: "pipeline", label: "Pipeline" }, ...(isStaff() ? [{ id: "history", label: "Review history" }] : [])];
    const content = h("div");
    mount(body, tabs(items, tab, (t) => { tab = t; setQuery({ tab: t }); drawTab(); }), content);
    const T = { overview, documents, findings, pipeline, history }[tab] || overview;
    T(content);
  }
  const overview = (c) => mount(c, h("div", { class: "grid g-main" }, h("div", { class: "stack" },
    card("Institution", kv([["Name", a.institution.name], ["Institution ID", a.institution.institution_id || h("span", { class: "muted" }, "Not provided")], ["State / district", [a.institution.state, a.institution.district].filter(Boolean).join(" / ") || "—"], ["Address", a.institution.address || "—"], ["Contact", [a.institution.contact_name, a.institution.contact_email, a.institution.contact_phone].filter(Boolean).join(" · ") || "—"]])),
    card("Application", [kv([["Category", a.application_type_label], ["Academic year", a.academic_year || "—"], ["Submitted", F.dateTime(a.submitted_at)], ["Reviewer", a.reviewer?.name || "Unassigned"], ["Correction cycles", a.correction_cycles], ["Notes", a.notes || "—"]]),
      a.courses.length ? h("div", { class: "table-wrap", style: { marginTop: "14px" } }, h("table", { class: "dt" }, h("thead", null, h("tr", null, h("th", null, "Course"), h("th", null, "Stated intake"))), h("tbody", null, a.courses.map((cr) => h("tr", null, h("td", null, cr.name), h("td", null, cr.intake || "—")))))) : null])),
    card("Required documents", h("ul", { class: "checklist" }, a.required_documents.map((r) => h("li", { "data-req": r.doc_type }, r.uploaded ? h("span", { style: { color: "var(--green)" } }, icon("checkc", "lg")) : h("span", { style: { color: "var(--red)" } }, icon("xc", "lg")), h("span", { class: "grow" }, r.label), r.uploaded ? r.document_id ? h("a", { class: "small", href: "/documents/" + r.document_id }, "Open") : null : badge("Missing", "red", "x")))))));
  const documents = async (c) => load(c, async () => api.get(`/applications/${id}/documents`), (d) => d.items.length ? h("div", { class: "stack sm" }, d.items.map((x) => h("div", { class: "doc-card", "data-doc": x.id }, h("div", { class: "doc-ico" }, icon(x.kind === "pdf" ? "file" : "image", "lg")),
    h("div", null, h("div", { class: "row wrap" }, h("span", { class: "strong" }, x.type_label), docStatusBadge(x.status), x.finding_count ? badge(F.plural(x.finding_count, "finding"), "amber", "warn") : null), h("div", { class: "small muted" }, `${x.filename} · ${F.bytes(x.size)} · ${x.page_count || 0} page(s)${x.text_source ? " · " + (x.text_source === "ocr" ? "OCR" : "text layer") : ""}`), h("div", { class: "steps" }, x.steps.map((s) => h("span", { class: "s " + s.state }, icon({ done: "check", review: "warn", failed: "x", pending: "clock", skipped: "minus", running: "loader" }[s.state] || "clock"), s.label)))),
    btn("Open viewer", { size: "sm", icon: "eye", href: "/documents/" + x.id })))) : empty({ icon: "file", title: "No documents", text: "No documents have been uploaded to this application." }));
  const findings = (c) => load(c, async () => api.get(`/applications/${id}/findings`, { page_size: 100 }), (d) => d.items.length ? h("div", { class: "stack" }, h("div", { class: "muted small" }, `${F.plural(d.total, "finding")} in the latest validation run. Findings are prompts for human review, not verdicts.`), findingList(d.items, { openFirst: true })) : empty({ icon: "checkc", title: a.validation === "not_run" ? "Validation has not run yet" : "No findings", text: a.validation === "not_run" ? "Findings appear after the application is submitted (or when you run a pre-check)." : "All checks passed for the latest run." }));
  const pipeline = (c) => load(c, async () => api.get(`/applications/${id}/pipeline`), (p) => h("div", { class: "grid g-main" }, card("Verification pipeline", pipelineView(p, { onFinding: (fid) => { tab = "findings"; setQuery({ tab }); drawTab(); setTimeout(() => document.querySelector(`[data-finding="${fid}"]`)?.open?.(true), 400); } }), { actions: btn(user.role === "applicant" ? "Run pre-check" : "Re-run validation", { size: "sm", icon: "refresh", disabled: user.role === "applicant" && !["draft", "corrections_requested"].includes(a.status), onClick: (e) => busy(e.currentTarget, async () => { try { await api.post(`/applications/${id}/validate`); toast("Validation re-run complete."); await refresh(true); } catch (ex) { toast(ex.message, "err"); } }) }) }),
    card("Documents in this run", h("div", { class: "stack sm" }, p.documents.map((d) => h("div", null, h("div", { class: "row between" }, h("a", { href: "/documents/" + d.id, class: "strong" }, d.type_label), docStatusBadge(d.status)), h("div", { class: "small muted" }, d.stages.map((s) => `${s.stage}: ${s.status}`).join(" · ")), h("hr", { class: "divider" })))))));
  const history = (c) => load(c, async () => api.get(`/applications/${id}/review/history`), (d) => d.items.length ? card("Review history", h("ul", { class: "timeline" }, d.items.map((x) => h("li", null, h("div", null, h("b", null, F.titleCase(x.action.replace("finding.", "finding "))), " · ", h("span", { class: "muted" }, x.actor_email, " (", x.actor_role, ")")), x.remarks ? h("div", null, x.remarks) : null, x.to_status ? h("div", { class: "small muted" }, `${x.from_status || ""} → ${x.to_status}`) : null, h("div", { class: "small muted" }, F.dateTime(x.created_at)))))) : empty({ icon: "history", title: "No review activity yet", text: "Assignments, comments, triage and decisions will be listed here." }));

  drawHeader(); drawTab();
  if (a.processing) timer = setInterval(() => refresh(true).catch(() => {}), 1000);
  return root;
}
