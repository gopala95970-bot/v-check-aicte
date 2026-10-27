import { h, icon, mount } from "../dom.js";
import { api, need } from "../api.js";
import { state, isStaff } from "../state.js";
import { navigate, onCleanup } from "../router.js";
import { btn, busy, card, empty, errorState, badge, docStatusBadge, stageBadge, modal, field, input, toast, findingStatusBadge } from "../ui.js";
import { docPreview, fieldRows, findingCard } from "./_shared.js";
import * as F from "../fmt.js";

export default async function docviewer({ params, user }) {
  let d;
  try { d = need(await api.get("/documents/" + params.id), ["id", "fields", "application_id"], "document"); }
  catch (e) { return e.status === 404 ? empty({ icon: "search", title: "Document not found", text: "It may have been removed, or you may not have access.", action: btn("Back to documents", { href: "/documents", kind: "primary" }) }) : errorState(e, () => navigate(location.pathname)); }
  let app = null; try { app = await api.get("/applications/" + d.application_id); } catch { /* optional */ }
  const final = app && ["approved_demo", "rejected_demo"].includes(app.status);
  const canCorrect = user.role === "reviewer" && !final && d.status === "processed";
  let mode = "preview", highlight = null;
  const left = h("div", { class: "pane" }), right = h("div", { class: "pane" });
  const viewerBox = h("div", { style: { display: "flex", flex: 1, minHeight: 0, flexDirection: "column" } });

  const drawViewer = () => {
    const seg = isStaff() && d.pages ? h("div", { class: "seg" }, [["preview", "Preview"], ["text", "Extracted text"]].map(([k, t]) => h("button", { type: "button", "aria-pressed": String(mode === k), onClick: () => { mode = k; drawViewer(); } }, t))) : null;
    mount(left, h("div", { class: "ph" }, h("div", { style: { minWidth: 0 } }, h("div", { class: "strong", style: { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, d.filename), h("div", { class: "small muted" }, `${d.type_label} · ${F.bytes(d.size)} · ${d.page_count} page(s)`)), seg),
      mode === "preview" ? docPreview(d, onCleanup) : h("div", { class: "pb" }, d.pages.map((p) => h("div", { style: { padding: "14px 16px", borderBottom: "1px solid var(--border)" } }, h("div", { class: "row between", style: { marginBottom: "6px" } }, h("b", null, "Page " + p.page), badge(p.source === "ocr" ? `OCR · ${F.pct(p.mean_conf)}` : "Text layer", "outline", "scan")), h("pre", { class: "mono", style: { whiteSpace: "pre-wrap", margin: 0, color: "var(--text-2)" }, "data-pagetext": "" }, p.text || "(no text)")))));
  };
  const correct = (f) => {
    const v = input({ value: f.effective_value, maxlength: 300, name: "value", "aria-label": "Corrected value" });
    modal({ title: "Correct extracted value", body: h("div", { class: "stack" }, h("div", { class: "banner" }, icon("info"), h("div", null, "The original extracted value (", h("span", { class: "mono" }, f.value), ") is kept for the audit trail. Validation re-runs with your corrected value.")), field(F.titleCase(f.name), v)),
      actions: [{ label: "Cancel" }, ...(f.corrected_value != null ? [{ label: "Reset to extracted", onClick: async () => { await api.patch(`/documents/${d.id}/fields/${f.id}`, { value: null }); toast("Correction cleared; validation re-run."); navigate(location.pathname + location.search); } }] : []),
        { label: "Save correction", kind: "primary", onClick: async () => { if (!v.value.trim()) { v.classList.add("invalid"); return false; } try { const r = await api.patch(`/documents/${d.id}/fields/${f.id}`, { value: v.value.trim() }); toast(`Correction saved. Validation re-run: ${r.findings.total} finding(s).`); navigate(location.pathname + location.search); } catch (ex) { toast(ex.message, "err"); return false; } } }] });
  };
  const drawRight = () => mount(right, h("div", { class: "ph" }, h("b", null, "Extracted information"), h("div", { class: "row" }, docStatusBadge(d.status), d.text_source ? badge(d.text_source === "ocr" ? "OCR" : "Text layer", "outline", "scan") : null)),
    h("div", { class: "pb" }, d.errors.length ? h("div", { class: "banner err", style: { margin: "12px" } }, icon("alert"), h("div", null, d.errors.map((e) => e.message).join(" "))) : null,
      h("div", { style: { padding: "10px 14px" }, class: "small muted" }, d.detected_type_label ? ["Classified as ", h("b", null, d.detected_type_label), ` (score ${d.detected_confidence?.toFixed(2)})`] : "Not classified", d.declared_type && d.detected_type && d.declared_type !== d.detected_type ? h("span", { style: { color: "var(--amber)", marginLeft: "6px" } }, "Differs from the declared type.") : null),
      fieldRows(d.fields, { onCorrect: canCorrect ? correct : null, highlight }),
      d.courses?.length ? h("div", { style: { padding: "12px 14px" } }, h("div", { class: "f-label" }, "Courses read from the document"), d.courses.map((c) => h("div", { class: "row between small" }, h("span", null, c.course), h("b", null, c.intake || "—")))) : null,
      h("div", { style: { padding: "14px" } }, h("div", { class: "f-label" }, `Validation findings (${d.findings.length})`),
        d.findings.length ? h("div", { class: "stack" }, d.findings.map((f, i) => findingCard(f, { open: i === 0 }))) : h("div", { class: "banner ok" }, icon("checkc"), h("div", null, "No findings reference this document."))),
      h("div", { style: { padding: "0 14px 16px" } }, h("div", { class: "f-label" }, "Processing stages"), d.stages.map((s) => h("div", { class: "row between small", style: { padding: "5px 0", borderBottom: "1px solid var(--border)" } }, h("span", null, s.stage), h("span", { class: "row" }, h("span", { class: "muted mono" }, s.duration_ms == null ? "" : F.ms(s.duration_ms)), stageBadge(s.status)))))));
  drawViewer(); drawRight();
  return h("div", { class: "stack lg" }, h("div", null, h("div", { class: "crumbs" }, h("a", { href: "/documents" }, "Documents"), " / ", d.filename), h("div", { class: "page-h", style: { marginBottom: 0 } }, h("div", null, h("h1", null, d.type_label), h("p", null, "Application ", h("a", { href: "/applications/" + d.application_id, class: "mono strong" }, d.application_id), app ? " · " + app.institution.name : "")), h("div", { class: "row" }, btn("Back to application", { icon: "left", href: "/applications/" + d.application_id }), isStaff() ? btn("Open in reviewer workspace", { kind: "primary", icon: "clipboard", href: "/review?app=" + d.application_id }) : null))), h("div", { class: "docsplit" }, left, right));
}
