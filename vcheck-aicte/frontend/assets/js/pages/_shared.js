import { h, icon, mount, clear } from "../dom.js";
import { api } from "../api.js";
import * as F from "../fmt.js";
import { badge, btn, appStatusBadge, validationBadge, severityBadge, outcomeBadge, findingStatusBadge, ruleKindBadge, stageBadge, simBadge, empty, docStatusBadge } from "../ui.js";
import { state } from "../state.js";

// ------------------------------------------------------------------ applications table
export function applicationsTable(items, { full = false, onOpen } = {}) {
  const head = ["Application ID", "Institution", ...(full ? ["Type"] : []), "Submitted", "Docs", ...(full ? ["Validation"] : []), full ? "Review status" : "Status", "Findings", "Reviewer", ""];
  return h("div", { class: "table-wrap" }, h("table", { class: "dt" },
    h("thead", null, h("tr", null, head.map((t) => h("th", { class: t === "" ? "right" : "" }, t)))),
    h("tbody", null, items.map((a) => {
      const open = () => (onOpen ? onOpen(a) : null);
      const draft = a.status === "draft";
      return h("tr", { "data-app": a.id },
        h("td", null, h("a", { class: "id", href: "/applications/" + a.id }, a.id), h("div", { class: "small muted" }, a.reference)),
        h("td", { class: "inst" }, h("div", { class: "strong" }, a.institution.name), h("div", { class: "small muted" }, [a.institution.state, a.institution.institution_id].filter(Boolean).join(" · "))),
        full ? h("td", { class: "small", title: a.application_type_label }, a.application_type_label.split(" (")[0]) : null,
        h("td", { class: "nowrap" }, draft ? h("span", { class: "muted" }, "Not submitted") : F.date(a.submitted_at)),
        h("td", null, a.document_count),
        full ? h("td", null, validationBadge(a.validation)) : null,
        h("td", null, appStatusBadge(a.status, a.status_label)),
        h("td", null, a.findings.total ? h("span", { class: "row", style: { gap: "6px" } }, h("span", { class: "strong" }, a.findings.total), a.findings.critical_open ? badge(a.findings.critical_open + " critical", "red", "alert") : a.findings.open ? badge(a.findings.open + " open", "amber") : badge("all triaged", "green", "check")) : h("span", { class: "muted" }, a.validation === "not_run" ? "—" : "None")),
        h("td", null, a.reviewer ? a.reviewer.name : h("span", { class: "muted" }, "Unassigned")),
        h("td", { class: "right nowrap" }, btn(draft && state.user.role === "applicant" ? "Continue" : "View", { size: "sm", href: draft && state.user.role === "applicant" ? "/applications/new?draft=" + a.id : "/applications/" + a.id, onClick: open })));
    }))));
}

// ------------------------------------------------------------------ finding card
export function findingCard(f, { open = false, triage, onChange, showApp = false } = {}) {
  const isXD = f.rule_id.startsWith("XD-");
  const closed = f.status === "resolved" || f.status === "accepted_with_explanation";
  const body = h("div", { class: "f-body hide" });
  const chev = icon("down");
  const header = h("div", { class: "f-h", role: "button", tabindex: "0", "aria-expanded": String(open), onClick: () => toggle(), onKeydown: (e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), toggle()) },
    h("div", { class: "stack sm grow" },
      h("div", { class: "row wrap", style: { gap: "6px" } }, severityBadge(f.severity, f.critical), outcomeBadge(f.outcome), findingStatusBadge(f.status), f.reviewer_only ? badge("Reviewer only", "navy", "lock") : null),
      h("div", { class: "strong", style: { fontSize: "14px" } }, f.title),
      h("div", { class: "small muted" }, h("span", { class: "mono" }, f.rule_id), " · ", f.id, showApp && f.application_reference ? ` · ${f.application_id} ${f.institution_name || ""}` : "")),
    chev);
  const el = h("article", { class: `finding sev-${f.severity}${closed ? " closed" : ""}`, "data-finding": f.id }, header, body);
  let built = false;
  function build() {
    built = true;
    const row = (label, value, cls = "") => h("div", { class: "ev-row" }, h("span", { class: "k" }, label), h("span", { class: "val " + cls }, value));
    const ev = [];
    if (f.expected != null || f.observed != null) {
      ev.push(row(isXD ? "Application value" : "Expected", f.expected ?? "—", "good"), row(isXD ? "Document value" : "Observed", f.observed ?? "—", "bad"));
    }
    f.evidence.forEach((e) => { ev.push(row("Source", `${e.filename || "document"} · page ${e.page ?? "?"}${e.line_no ? " · line " + e.line_no : ""}`)); if (e.snippet) ev.push(row("Excerpt", "\u201C" + e.snippet + "\u201D")); });
    if (!ev.length) ev.push(row("Evidence", f.documents.length ? f.documents.map((d) => d.filename).join(", ") : "No document value; the finding concerns a missing item."));
    body.append(h("div", { class: "f-b" },
      h("div", null, h("div", { class: "f-label" }, "Evidence"), h("div", { class: "evidence rows", "data-evidence": "" }, ...ev)),
      h("div", { class: "grid g2" },
        h("div", null, h("div", { class: "f-label" }, "Rule"), h("div", { class: "row wrap", style: { gap: "6px" } }, h("span", { class: "mono strong" }, f.rule_id), h("span", { class: "muted" }, "v" + f.rule_version), ruleKindBadge(f.rule_kind)), h("div", { class: "small", style: { marginTop: "4px" } }, f.rule_name)),
        h("div", null, h("div", { class: "f-label" }, "Source"), h("div", null, f.rule_source_ref || "—"), h("div", { class: "small muted" }, "Source status: " + (f.rule_source_status || "—").replace(/_/g, " ")))),
      h("div", null, h("div", { class: "f-label" }, "Explanation"), h("div", null, f.explanation)),
      h("div", null, h("div", { class: "f-label" }, "Recommended action"), h("div", { class: "rec" }, f.recommended_action)),
      f.limitations ? h("div", { class: "banner warn" }, icon("info"), h("div", null, h("b", null, "Limitations: "), f.limitations)) : null,
      f.documents.length ? h("div", null, h("div", { class: "f-label" }, "Documents involved"), h("div", { class: "row wrap" }, f.documents.map((d) => h("a", { class: "btn sm", href: "/documents/" + d.id }, icon("file"), d.filename)))) : null,
      closed ? h("div", { class: "banner ok" }, icon("check"), h("div", null, h("b", null, F.titleCase(f.status) + " by " + (f.resolved_by || "—") + ". "), f.resolution_note || "")) : null,
      triage ? triage(f, onChange) : null));
  }
  function toggle(force) {
    const show = force ?? body.classList.contains("hide");
    if (show && !built) build();
    body.classList.toggle("hide", !show); header.setAttribute("aria-expanded", String(show));
  }
  if (open) toggle(true);
  el.open = toggle;
  return el;
}

export function findingList(items, opts = {}) {
  if (!items.length) return empty({ icon: "checkc", title: "No findings", text: opts.emptyText || "Nothing needs attention in this view." });
  return h("div", { class: "stack" }, items.map((f, i) => findingCard(f, { ...opts, open: opts.openFirst && i === 0 })));
}

// ------------------------------------------------------------------ pipeline
const STAGE_ICON = { passed: "check", review: "warn", failed: "x", running: "loader", pending: "clock", skipped: "minus" };
export function pipelineView(p, { onFinding } = {}) {
  const stages = h("ol", { class: "pipe" }, p.stages.map((s) => h("li", { "data-stage": s.stage, "data-state": s.status },
    h("span", { class: "node " + s.status }, icon(STAGE_ICON[s.status] || "clock")),
    h("div", { class: "body" }, h("div", { class: "row wrap", style: { gap: "8px" } }, h("b", null, s.stage), stageBadge(s.status), s.scope === "document" ? badge("per document", "outline") : null),
      h("div", { class: "small", style: { marginTop: "3px", color: "var(--text-2)" } }, s.result),
      s.evidence?.length ? h("div", { class: "ev" }, s.evidence.map((e, i) => h("div", null, /^VF-/.test(e) ? h("a", { href: "#", onClick: (ev) => { ev.preventDefault(); onFinding?.(e); } }, e) : e))) : null,
      s.errors?.length ? h("div", { class: "small", style: { color: "var(--red)", marginTop: "4px" } }, "Flags: " + s.errors.join(", ")) : null),
    h("span", { class: "ms" }, s.duration_ms == null ? "" : F.ms(s.duration_ms)))));
  const run = p.latest_run;
  const meta = run ? h("div", { class: "row wrap small muted", style: { marginBottom: "14px", gap: "14px" } },
    h("span", null, "Run #" + run.id), h("span", null, "Ruleset v" + run.ruleset_version), h("span", null, `${run.rules_run} rules run`), h("span", null, "Total " + F.ms(run.duration_ms)), h("span", null, "Trigger: " + run.trigger), h("span", null, F.dateTime(run.finished_at))) : null;
  const ver = p.verification?.length ? h("div", { style: { marginTop: "18px" } },
    h("div", { class: "row", style: { marginBottom: "8px" } }, h("h3", null, "Source verification results"), simBadge()),
    h("div", { class: "table-wrap card" }, h("table", { class: "dt" }, h("thead", null, h("tr", null, ["Document", "Provider", "Result", "Detail"].map((t) => h("th", null, t)))),
      h("tbody", null, p.verification.map((v) => h("tr", null, h("td", null, v.filename), h("td", null, v.provider, v.simulated ? " (simulated)" : ""), h("td", null, badge(F.titleCase(v.display_status), v.display_status === "simulated_match" ? "green" : "amber"), ), h("td", { class: "small" }, v.detail))))))) : null;
  return h("div", null, meta, stages, ver);
}

// ------------------------------------------------------------------ document preview (authorised blob, never a public URL)
export function docPreview(doc, onCleanup) {
  const box = h("div", { class: "viewer", "data-viewer": doc.id }, h("div", { class: "nopreview" }, h("span", { class: "spinner" }), h("div", { class: "small", style: { marginTop: "8px" } }, "Loading preview…")));
  if (!doc.previewable) { mount(box, h("div", { class: "nopreview" }, icon("file", "xl"), h("div", { class: "strong" }, "No preview available"), h("div", { class: "small" }, doc.status === "rejected" ? "This file was rejected and is not stored." : "The file is no longer stored."))); return box; }
  api.blob(`/documents/${doc.id}/file`).then((blob) => {
    const url = URL.createObjectURL(blob);
    onCleanup?.(() => URL.revokeObjectURL(url));
    if (!box.isConnected && !box.parentNode) { /* still ok: mounted shortly after */ }
    const open = h("a", { class: "btn sm", href: url, target: "_blank", rel: "noopener", "data-external": "" }, icon("external"), "Open in new tab");
    const frame = doc.kind === "pdf" ? h("iframe", { src: url, title: "Document preview: " + doc.filename, sandbox: "allow-same-origin" }) : h("img", { src: url, alt: "Preview of " + doc.filename });
    mount(box, frame, h("div", { class: "vbar" }, h("span", null, doc.kind === "pdf" ? "Blank? Your browser's PDF viewer may be off. Use the Fields or Text view." : "Preview of the uploaded image."), open));
  }).catch((e) => mount(box, h("div", { class: "nopreview" }, icon("alert", "xl"), h("div", { class: "strong" }, "Preview unavailable"), h("div", { class: "small" }, e.message))));
  return box;
}

export function fieldRows(fields, { onCorrect, highlight } = {}) {
  if (!fields.length) return empty({ icon: "scan", title: "No fields extracted", text: "Nothing could be read from this document." });
  return h("div", null, fields.map((f) => h("div", { class: "field-row" + (highlight === f.name ? " hl" : ""), "data-field": f.name },
    h("div", { class: "nm" }, F.titleCase(f.name)),
    h("div", null, h("div", { class: "vl" }, f.effective_value, f.corrected_value != null ? h("span", { style: { marginLeft: "6px" } }, badge("Corrected", "blue", "pencil")) : null),
      f.corrected_value != null ? h("div", { class: "small muted" }, "Extracted as: ", h("span", { class: "mono" }, f.value)) : null,
      h("div", { class: "small muted" }, `Page ${f.page ?? "?"}${f.line_no ? " · line " + f.line_no : ""} · ${F.pct(f.confidence)} confidence · ${f.method === "ocr" ? "OCR" : "text layer"}`),
      f.snippet ? h("div", { class: "small mono muted", style: { marginTop: "2px", wordBreak: "break-word" } }, "\u201C" + f.snippet + "\u201D") : null),
    onCorrect ? btn("", { size: "sm", kind: "ghost", icon: "pencil", ariaLabel: "Correct " + f.name, title: "Correct this value", onClick: () => onCorrect(f) }) : h("span")
  )));
}

export function docRow(d) {
  return h("div", { class: "doc-card", "data-doc": d.id }, h("div", { class: "doc-ico" }, icon(d.kind === "pdf" ? "file" : "image", "lg")),
    h("div", null, h("div", { class: "strong" }, d.type_label), h("div", { class: "small muted" }, `${d.filename} · ${F.bytes(d.size)}`)), docStatusBadge(d.status));
}
