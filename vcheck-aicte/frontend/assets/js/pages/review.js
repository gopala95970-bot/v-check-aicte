import { h, icon, mount, clear } from "../dom.js";
import { api, need } from "../api.js";
import { state } from "../state.js";
import { navigate, query, setQuery, onCleanup } from "../router.js";
import { btn, busy, empty, errorState, input, select, skelRows, debounce, appStatusBadge, validationBadge, badge, toast, remarksDialog, confirmDialog, modal, field, findingStatusBadge, load } from "../ui.js";
import { findingCard, docPreview, fieldRows } from "./_shared.js";
import * as F from "../fmt.js";

const SCOPES = [["open", "Open"], ["mine", "Mine"], ["unassigned", "Unassigned"], ["corrections", "With applicant"], ["decided", "Decided"]];
const TERMINAL = ["approved_demo", "rejected_demo"];

export default async function review({ user }) {
  const S = { scope: query().scope || "open", q: "", appId: query().app || null, app: null, findings: [], docs: [], docId: null, doc: null, hl: null, mode: "preview", history: [], cleanups: [] };
  const queuePane = h("div", { class: "pane", "data-pane": "queue" }), evidencePane = h("div", { class: "pane", "data-pane": "evidence" }), findingsPane = h("div", { class: "pane", "data-pane": "findings" });
  onCleanup(() => S.cleanups.forEach((f) => f()));

  // ------------------------------------------------------------ queue
  async function loadQueue(keepSelection = true) {
    mount(queuePane.querySelector(".pb") || queuePane, skelRows(6));
    let d;
    try { d = need(await api.get("/review/queue", { scope: S.scope, q: S.q }), ["items"], "queue"); } catch (e) { return mount(queuePane, errorState(e, () => loadQueue())); }
    drawQueue(d.items);
    if (!S.appId && d.items.length) selectApp(d.items[0].id); else if (S.appId) selectApp(S.appId, false); else drawEmptyCenter();
  }
  function drawQueue(items) {
    const search = input({ type: "search", placeholder: "Search…", "aria-label": "Search queue", value: S.q, class: "input sm" }); search.addEventListener("input", debounce(() => { S.q = search.value.trim(); loadQueue(); }, 300));
    mount(queuePane, h("div", { class: "ph", style: { flexDirection: "column", alignItems: "stretch", gap: "8px" } }, h("div", { class: "row between" }, h("b", null, "Review queue"), badge(String(items.length), "outline")),
      h("div", { class: "seg", style: { flexWrap: "wrap" } }, SCOPES.map(([k, t]) => h("button", { type: "button", "aria-pressed": String(S.scope === k), "data-scope": k, onClick: () => { S.scope = k; setQuery({ scope: k }); loadQueue(); } }, t))), search),
      h("div", { class: "pb", "data-queue": "" }, items.length ? items.map((a) => h("button", { class: "qitem", "data-app": a.id, "aria-current": String(a.id === S.appId), onClick: () => selectApp(a.id) },
        h("div", { class: "row between" }, h("span", { class: "mono strong" }, a.id), h("span", { class: "row", style: { gap: "4px" } }, a.escalated ? badge("Escalated", "red", "flag") : null, a.findings.critical_open ? badge(String(a.findings.critical_open), "red", "alert") : a.findings.open ? badge(String(a.findings.open), "amber", "warn") : badge("0", "green", "check"))),
        h("div", { class: "strong small", style: { margin: "3px 0" } }, a.institution.name), h("div", { class: "row wrap", style: { gap: "6px" } }, appStatusBadge(a.status, a.status_label)),
        a.top_findings[0] ? h("div", { class: "small muted", style: { marginTop: "5px" } }, a.top_findings[0].title) : null, h("div", { class: "small muted" }, a.reviewer ? "Reviewer: " + a.reviewer.name : "Unassigned"))) : empty({ icon: "clipboard", title: "Nothing in this view", text: S.scope === "open" ? "No applications are waiting for review." : "Try another filter." })));
  }
  const drawEmptyCenter = () => { mount(evidencePane, empty({ icon: "clipboard", title: "Select an application", text: "Choose a case from the queue to see its documents and findings." })); mount(findingsPane, h("div")); };

  // ------------------------------------------------------------ selection
  async function selectApp(id, pushUrl = true) {
    S.appId = id; if (pushUrl) setQuery({ app: id });
    queuePane.querySelectorAll(".qitem").forEach((b) => b.setAttribute("aria-current", String(b.dataset.app === id)));
    mount(evidencePane, skelRows(8)); mount(findingsPane, skelRows(8));
    try {
      const [app, f, docs, hist] = await Promise.all([api.get("/applications/" + id), api.get(`/applications/${id}/findings`, { page_size: 100 }), api.get(`/applications/${id}/documents`), api.get(`/applications/${id}/review/history`)]);
      Object.assign(S, { app, findings: f.items, docs: docs.items, history: hist.items });
      const pick = S.docs.find((d) => d.id === S.docId) || S.docs.find((d) => f.items[0]?.documents?.some((x) => x.id === d.id)) || S.docs[0];
      await selectDoc(pick?.id || null, null, false);
      drawFindings();
    } catch (e) { mount(evidencePane, errorState(e, () => selectApp(id, false))); mount(findingsPane, h("div")); }
  }
  async function selectDoc(id, field, redraw = true) {
    S.docId = id; S.hl = field; S.doc = null; S.cleanups.splice(0).forEach((f) => f());
    if (id) { try { S.doc = await api.get("/documents/" + id); } catch { S.doc = null; } }
    drawEvidence();
  }

  // ------------------------------------------------------------ center: evidence
  function drawEvidence() {
    const a = S.app, d = S.doc;
    const modes = [["preview", "Preview"], ["fields", "Extracted fields"], ...(d?.pages ? [["text", "Text"]] : [])];
    const chips = h("div", { class: "row", style: { padding: "8px 14px", borderBottom: "1px solid var(--border)", gap: "6px", overflowX: "auto", flexWrap: "nowrap" }, "data-doc-chips": "" }, S.docs.length ? S.docs.map((x) => h("button", { class: "btn sm" + (x.id === S.docId ? " navy" : ""), "data-docbtn": x.declared_type || x.id, onClick: () => selectDoc(x.id) }, icon(x.kind === "pdf" ? "file" : "image"), x.type_label, x.finding_count ? h("span", { class: "badge amber", style: { height: "16px", padding: "0 5px" } }, x.finding_count) : null)) : h("span", { class: "muted small" }, "No documents uploaded."));
    const seg = h("div", { class: "row between", style: { padding: "8px 14px", borderBottom: "1px solid var(--border)" } }, h("div", { class: "seg", "data-modes": "" }, modes.map(([k, t]) => h("button", { type: "button", "data-mode": k, "aria-pressed": String(S.mode === k), onClick: () => { S.mode = k; drawEvidence(); } }, t))), d ? h("span", { class: "small muted" }, `${d.page_count} page(s) · ${d.text_source === "ocr" ? "OCR " + F.pct(d.ocr_mean_conf) : "text layer"}`) : null);
    const canCorrect = user.role === "reviewer" && S.app && !TERMINAL.includes(S.app.status) && d?.status === "processed";
    let main;
    if (!d) main = h("div", { class: "viewer" }, h("div", { class: "nopreview" }, icon("file", "xl"), h("div", null, S.docs.length ? "Select a document" : "This application has no documents.")));
    else if (S.mode === "fields") main = h("div", { class: "pb", "data-fields": "" }, fieldRows(d.fields, { highlight: S.hl, onCorrect: canCorrect ? correctField : null }),
      d.courses?.length ? h("div", { style: { padding: "12px 14px" } }, h("div", { class: "f-label" }, "Courses read from the document"), d.courses.map((c) => h("div", { class: "row between small" }, h("span", null, c.course), h("b", null, c.intake || "—")))) : null);
    else if (S.mode === "text" && d.pages) main = h("div", { class: "pb", style: { padding: "12px 14px" } }, d.pages.map((p) => h("div", null, h("div", { class: "f-label" }, `Page ${p.page} · ${p.source === "ocr" ? "OCR " + F.pct(p.mean_conf) : "text layer"}`), h("pre", { class: "mono", style: { whiteSpace: "pre-wrap", margin: "0 0 12px" } }, p.text))));
    else main = docPreview(d, (fn) => S.cleanups.push(fn));
    mount(evidencePane, h("div", { class: "ph" }, h("div", { style: { minWidth: 0 } }, h("div", { class: "row wrap", style: { gap: "8px" } }, h("b", { style: { fontSize: "15px" } }, a.institution.name), appStatusBadge(a.status, a.status_label)), h("div", { class: "small muted" }, `${a.id} · ${a.reference} · ${a.application_type_label.split(" (")[0]} · Stated intake: ${a.courses.map((c) => c.intake || "—").join(", ") || "—"}`))),
      chips, seg, main);
    const act = chips.querySelector(".navy"); if (act) chips.scrollLeft = Math.max(0, act.offsetLeft - 40);
    if (S.hl) setTimeout(() => evidencePane.querySelector(".field-row.hl")?.scrollIntoView({ block: "nearest" }), 50);
  }
  function correctField(f) {
    const v = input({ value: f.effective_value, maxlength: 300, name: "value", "aria-label": "Corrected value" });
    modal({ title: "Correct extracted value", body: h("div", { class: "stack" }, h("div", { class: "banner" }, icon("info"), h("div", null, "Original value ", h("span", { class: "mono" }, f.value), " is preserved. Validation re-runs with the corrected value.")), field(F.titleCase(f.name), v)),
      actions: [{ label: "Cancel" }, { label: "Save correction", kind: "primary", onClick: async () => { if (!v.value.trim()) { v.classList.add("invalid"); return false; } try { const r = await api.patch(`/documents/${S.docId}/fields/${f.id}`, { value: v.value.trim() }); toast(`Saved. Re-validated: ${r.findings.total} finding(s) now.`); await selectApp(S.appId, false); await refreshQueueOnly(); } catch (ex) { toast(ex.message, "err"); return false; } } }] });
  }

  // ------------------------------------------------------------ right: findings + actions
  function triage(f, onChange) {
    if (user.role !== "reviewer" || TERMINAL.includes(S.app.status) || !f.is_current) return h("div", { class: "row wrap" }, f.documents[0] ? btn("Show evidence in viewer", { size: "sm", icon: "eye", onClick: () => showEvidence(f) }) : null);
    const st = select([["open", "Open"], ["under_review", "Under review"], ["resolved", "Resolved"], ["accepted_with_explanation", "Accepted with explanation"]].map(([value, label]) => ({ value, label })), { value: f.status, "aria-label": "Finding status", class: "select sm" });
    const note = h("textarea", { class: "textarea", placeholder: "Note (required to resolve or accept)", "aria-label": "Resolution note", style: { minHeight: "56px" } }); note.value = f.resolution_note || "";
    const save = btn("Save status", { kind: "primary", size: "sm", onClick: (e) => busy(e.currentTarget, async () => { try { await api.patch("/findings/" + f.id, { status: st.value, note: note.value.trim() }); toast(`${f.id} set to ${F.titleCase(st.value)}.`); await selectApp(S.appId, false); await refreshQueueOnly(); } catch (ex) { toast(ex.message, "err"); note.classList.add("invalid"); } }) });
    return h("div", { class: "stack sm", style: { borderTop: "1px dashed var(--border-strong)", paddingTop: "10px" }, "data-triage": f.id }, h("div", { class: "f-label" }, "Reviewer triage"), st, note, h("div", { class: "row wrap" }, save, f.documents[0] ? btn("Show evidence in viewer", { size: "sm", icon: "eye", onClick: () => showEvidence(f) }) : null));
  }
  const showEvidence = async (f) => { S.mode = "fields"; await selectDoc(f.documents[0].id, f.fields[0]); };
  function drawFindings() {
    const a = S.app, final = TERMINAL.includes(a.status), busyApp = a.processing;
    const open = S.findings.filter((f) => ["open", "under_review"].includes(f.status)).length;
    const act = (label, ic, kind, fn, extra = {}) => btn(label, { size: "sm", icon: ic, kind, onClick: fn, disabled: extra.disabled ?? (final || busyApp), title: extra.title });
    const actions = user.role === "reviewer" ? h("div", { class: "stack sm", "data-actions": "" },
      h("div", { class: "row wrap" }, act("Assign to me", "usercheck", "", () => doAction("assign", { reviewer_id: "self" }, { noDialog: true })), act("Comment", "message", "", () => doAction("comment", {}, { title: "Add a comment", label: "Comment", minLen: 2, confirmLabel: "Add comment" })), act("Mark reviewed", "check", "", () => doAction("mark_reviewed", {}, { title: "Mark as reviewed", label: "Remarks (optional)", optional: true, confirmLabel: "Mark reviewed" })), act("Escalate", "flag", "", () => doAction("escalate", {}, { title: "Escalate to a senior reviewer", label: "Why is this being escalated?", confirmLabel: "Escalate" }))),
      h("div", { class: "row wrap" }, act("Request correction", "message", "", () => doAction("request_correction", {}, { title: "Request corrections from the applicant", message: "The applicant will be notified and can edit and resubmit.", label: "What needs to be corrected?", placeholder: "Be specific: which document, which value, what to provide.", confirmLabel: "Request correction" })),
        act("Approve (demo)", "checkc", "primary", () => doAction("approve_demo", {}, { title: "Record a DEMONSTRATION approval", message: `${a.institution.name} (${a.id})`, label: "Reason for approval", confirmLabel: "Record demonstration approval", notice: "This records a demonstration outcome only. It is not an official AICTE approval and issues nothing." })),
        act("Reject (demo)", "xc", "danger", () => doAction("reject_demo", {}, { title: "Record a DEMONSTRATION rejection", message: `${a.institution.name} (${a.id})`, label: "Reason for rejection", confirmLabel: "Record demonstration rejection", danger: true, notice: "This records a demonstration outcome only. It is not an official AICTE decision." })))) : null;
    const adminAssign = user.role === "admin" ? (() => {
      const sel = select([{ value: "", label: "Choose reviewer…" }], { "aria-label": "Assign reviewer" });
      api.get("/review/reviewers").then((r) => r.items.forEach((x) => sel.append(h("option", { value: x.id }, x.name))));
      return h("div", { class: "stack sm", "data-admin-assign": "" }, h("div", { class: "banner" }, icon("info"), h("div", null, "Administrators can assign reviewers. Decisions are recorded by reviewers.")), h("div", { class: "row" }, h("div", { class: "grow" }, sel), btn("Assign", { kind: "primary", size: "sm", disabled: final, onClick: () => sel.value ? doAction("assign", { reviewer_id: Number(sel.value) }, { noDialog: true }) : toast("Choose a reviewer first.", "err") })));
    })() : null;
    mount(findingsPane, h("div", { class: "ph" }, h("div", null, h("b", null, "Findings"), h("div", { class: "small muted" }, `${S.findings.length} total · ${open} open`)), h("div", { class: "row", style: { gap: "6px" } }, a.reviewer ? badge(a.reviewer.name, "outline", "user") : badge("Unassigned", "outline"), validationBadge(a.validation))),
      h("div", { class: "pb", style: { padding: "12px" }, "data-findings-list": "" }, h("div", { class: "stack" },
        busyApp ? h("div", { class: "banner" }, h("span", { class: "spinner" }), h("div", null, "Validation is running…")) : null,
        a.status === "corrections_requested" ? h("div", { class: "banner warn" }, icon("message"), h("div", null, "Waiting for the applicant to correct and resubmit.")) : null,
        a.decision ? h("div", { class: "banner " + (a.status === "approved_demo" ? "ok" : "err") }, icon("info"), h("div", null, h("b", null, a.status_label + ". "), a.decision.remarks)) : null,
        S.findings.length ? S.findings.map((f, i) => findingCard(f, { open: i === 0, triage, showApp: false })) : h("div", { class: "banner ok" }, icon("checkc"), h("div", null, a.validation === "not_run" ? "Validation has not run yet." : "No findings: all checks passed.")),
        h("details", { "data-history": "" }, h("summary", { class: "strong", style: { cursor: "pointer", padding: "6px 0" } }, `Review history (${S.history.length})`), S.history.length ? h("ul", { class: "timeline" }, S.history.map((x) => h("li", null, h("b", null, F.titleCase(x.action.replace("finding.", "finding "))), " · ", h("span", { class: "muted" }, x.actor_email), x.remarks ? h("div", null, x.remarks) : null, h("div", { class: "small muted" }, F.dateTime(x.created_at))))) : h("div", { class: "muted small" }, "No activity yet.")))),
      h("div", { style: { padding: "12px", borderTop: "1px solid var(--border)", background: "var(--surface-2)", flex: "none" } }, actions, adminAssign, final ? h("div", { class: "small muted", style: { marginTop: "6px" } }, "A final demonstration decision has been recorded. The case is read-only.") : null));
  }
  async function doAction(action, extra, dlg = {}) {
    let remarks = "";
    if (!dlg.noDialog) { remarks = await remarksDialog({ title: dlg.title, message: dlg.message, label: dlg.label, placeholder: dlg.placeholder, minLen: dlg.minLen ?? 5, optional: dlg.optional, confirmLabel: dlg.confirmLabel, danger: dlg.danger, notice: dlg.notice }); if (remarks === null) return; }
    try {
      const body = { action, remarks, confirm: true, ...extra };
      await api.post(`/applications/${S.appId}/review/actions`, body);
      toast({ assign: "Assigned.", comment: "Comment added.", mark_reviewed: "Marked as reviewed.", escalate: "Escalated.", request_correction: "Correction requested. The applicant was notified.", approve_demo: "Demonstration approval recorded.", reject_demo: "Demonstration rejection recorded." }[action]);
      await selectApp(S.appId, false); await refreshQueueOnly();
    } catch (e) {
      const el = findingsPane.querySelector("[data-actions]") || findingsPane;
      toast(e.message, "err");
      if (e.code === "workflow_error") findingsPane.querySelector("[data-findings-list]")?.scrollTo({ top: 0, behavior: "smooth" });
    }
  }
  async function refreshQueueOnly() { try { const d = await api.get("/review/queue", { scope: S.scope, q: S.q }); drawQueue(d.items); } catch { /* ignore */ } }

  const root = h("div", { class: "stack" }, h("div", { class: "page-h", style: { marginBottom: "4px" } }, h("div", null, h("h1", null, "Reviewer workspace"), h("p", null, "Queue, evidence and findings side by side. Every action is confirmed and audited.")),
    h("div", { class: "banner warn", style: { padding: "6px 12px" } }, icon("info"), h("span", { class: "small" }, "Approve / Reject record demonstration outcomes only."))), h("div", { class: "review" }, queuePane, evidencePane, findingsPane));
  mount(queuePane, skelRows(6)); mount(evidencePane, skelRows(6)); mount(findingsPane, skelRows(6));
  loadQueue();
  return root;
}
