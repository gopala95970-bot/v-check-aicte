import { h, icon, mount, clear } from "../dom.js";
import { api, need } from "../api.js";
import { state } from "../state.js";
import { navigate, query, setQuery, onCleanup } from "../router.js";
import { btn, busy, field, input, select, badge, card, empty, errorState, toast, confirmDialog, modal, drawer, setFieldErrors, kv, docStatusBadge, stageBadge, simBadge } from "../ui.js";
import { docPreview, fieldRows, findingList } from "./_shared.js";
import * as F from "../fmt.js";

const STEPS = ["Institution", "Application", "Documents", "Review", "Submit"];
const GUESS = [[/occup/i, "occupancy_certificate"], [/affil/i, "affiliation_letter"], [/eoa|extension/i, "eoa_letter"], [/gov|noc|approval/i, "government_approval"]];
const guess = (name) => (GUESS.find(([rx]) => rx.test(name)) || [])[1] || "";
const ACCEPT = ["pdf", "png", "jpg", "jpeg"];

export default async function wizard({ user }) {
  const S = { appId: null, step: 0, inst: { name: "", institution_id: "", state: "", district: "", address: "", contact_name: "", contact_email: "", contact_phone: "" },
    application_type: "extension_of_approval", academic_year: "2026-27", courses: [{ name: "", intake: "" }], notes: "", docs: [], required: [], confirmed: false };
  const root = h("div", { class: "stack lg" });
  const stepperEl = h("ol", { class: "stepper", "aria-label": "Progress" });
  const stage = h("div", null);
  root.append(h("div", { class: "page-h" }, h("div", null, h("div", { class: "crumbs" }, h("a", { href: "/applications" }, "Applications"), " / New"), h("h1", null, "New application"), h("p", null, "Enter institution details, upload supporting documents, then submit for validation."))), stepperEl, stage);
  let timer = null;
  onCleanup(() => clearInterval(timer));

  const draft = query().draft;
  if (draft) {
    try {
      const a = need(await api.get("/applications/" + draft), ["id", "status", "institution"], "application");
      if (!["draft", "corrections_requested"].includes(a.status)) return navigate("/applications/" + a.id, { replace: true }), root;
      S.appId = a.id; S.inst = { ...S.inst, ...a.institution }; S.application_type = a.application_type; S.academic_year = a.academic_year || ""; S.notes = a.notes || "";
      S.courses = a.courses.length ? a.courses : [{ name: "", intake: "" }]; S.required = a.required_documents; S.resubmit = a.status === "corrections_requested";
      S.step = 2;
    } catch (e) { return errorState(e, () => navigate(location.pathname + location.search)); }
  }

  const drawStepper = () => mount(stepperEl, STEPS.map((t, i) => h("li", { class: i < S.step ? "done" : i === S.step ? "cur" : "", "aria-current": i === S.step ? "step" : null },
    h("span", { class: "n" }, i < S.step ? icon("check") : i + 1), h("span", { class: "t" }, t))));
  const go = (n) => { S.step = n; draw(); window.scrollTo(0, 0); };
  const nav = (back, next) => h("div", { class: "row between", style: { marginTop: "18px" } }, back ? btn("Back", { icon: "left", onClick: back }) : h("span"), next);
  function draw() { drawStepper(); mount(stage, [step1, step2, step3, step4, step5][S.step]()); }

  // ---------------------------------------------------------------- step 1
  function step1() {
    const f = (key, label, extra = {}, hint) => { const i = input({ name: "institution." + key, value: S.inst[key] || "", ...extra }); i.addEventListener("input", () => (S.inst[key] = i.value)); return field(label, i, { hint }); };
    const form = h("form", { class: "stack", novalidate: true }, 
      h("div", { class: "grid g2" }, f("name", "Institution name *", { required: true, maxlength: 200 }), f("institution_id", "Institution ID *", { placeholder: "e.g. 1-9000000808", maxlength: 40 }, "Required by rule APP-001. You can continue without it, but it will be flagged for the reviewer.")),
      f("address", "Address *", { maxlength: 400 }, "Required by rule APP-001; flagged for the reviewer if missing."),
      h("div", { class: "grid g2" }, f("state", "State *", { required: true }), f("district", "District")),
      h("div", { class: "grid g3" }, f("contact_name", "Contact person"), f("contact_email", "Contact email", { type: "email" }), f("contact_phone", "Contact phone", { type: "tel" })));
    const next = btn("Continue", { kind: "primary", onClick: () => { if (validate1(form)) go(1); } });
    return card("Step 1 · Institution", [form, nav(null, next)]);
  }
  function validate1(form) {
    form.querySelectorAll(".err.cl").forEach((e) => e.remove()); form.querySelectorAll(".invalid").forEach((e) => e.classList.remove("invalid"));
    let ok = true; const bad = (k, m) => { const el = form.querySelector(`[name="institution.${k}"]`); el.classList.add("invalid"); el.closest(".field").append(h("div", { class: "err cl", role: "alert" }, m)); if (ok) el.focus(); ok = false; };
    if (!S.inst.name.trim()) bad("name", "Enter the institution name.");
    if (!S.inst.state.trim()) bad("state", "Enter the state.");
    if (S.inst.contact_email && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(S.inst.contact_email)) bad("contact_email", "Enter a valid email address.");
    return ok;
  }

  // ---------------------------------------------------------------- step 2
  function step2() {
    const types = state.meta.application_types;
    const cat = select(types.map((t) => ({ value: t.id, label: t.label })), { name: "application_type", value: S.application_type });
    cat.addEventListener("change", () => (S.application_type = cat.value));
    const year = input({ name: "academic_year", value: S.academic_year, placeholder: "2026-27" }); year.addEventListener("input", () => (S.academic_year = year.value));
    const notes = h("textarea", { class: "textarea", name: "notes", maxlength: 1000, placeholder: "Anything the reviewer should know (optional)" }); notes.value = S.notes; notes.addEventListener("input", () => (S.notes = notes.value));
    const list = h("div", { class: "stack sm" });
    const drawCourses = () => mount(list, S.courses.map((c, i) => {
      const n = input({ placeholder: "Course / programme name", "aria-label": "Course name " + (i + 1), value: c.name, name: `courses[${i}].name` }); n.addEventListener("input", () => (c.name = n.value));
      const t = input({ placeholder: "Approved intake", "aria-label": "Intake " + (i + 1), value: c.intake, inputmode: "numeric", style: { maxWidth: "150px" }, name: `courses[${i}].intake` }); t.addEventListener("input", () => (c.intake = t.value));
      return h("div", { class: "row" }, h("div", { class: "grow" }, n), t, btn("", { icon: "trash", kind: "ghost", ariaLabel: "Remove course " + (i + 1), onClick: () => { S.courses.splice(i, 1); if (!S.courses.length) S.courses.push({ name: "", intake: "" }); drawCourses(); } }));
    }));
    drawCourses();
    const form = h("form", { class: "stack", novalidate: true }, h("div", { class: "grid g2" }, field("Application category *", cat), field("Academic year", year, { hint: "Format 2026-27" })),
      h("div", { class: "field" }, h("label", null, "Courses and intake"), list, btn("Add course", { icon: "plus", size: "sm", onClick: () => { S.courses.push({ name: "", intake: "" }); drawCourses(); } }), h("div", { class: "hint" }, "Intake figures are compared with the approval documents.")), field("Notes", notes));
    const next = btn("Save and continue", { kind: "primary", type: "button", onClick: (e) => busy(e.currentTarget, async () => {
      setFieldErrors(form, null);
      const payload = { institution: S.inst, application_type: S.application_type, academic_year: S.academic_year, notes: S.notes, courses: S.courses.filter((c) => c.name.trim()) };
      try {
        if (!S.appId) { const a = await api.post("/applications", payload); S.appId = a.id; S.required = a.required_documents || []; setQuery({ draft: a.id }); toast(`Draft ${a.id} created.`); }
        else await api.patch("/applications/" + S.appId, payload);
        await refreshApp(); go(2);
      } catch (ex) { setFieldErrors(form, ex.details); toast(ex.message, "err"); }
    }) });
    return card("Step 2 · Application", [form, nav(() => go(0), next)]);
  }
  async function refreshApp() { const a = await api.get("/applications/" + S.appId); S.required = a.required_documents; S.app = a; }

  // ---------------------------------------------------------------- step 3
  function step3() {
    const checklist = h("ul", { class: "checklist", "data-checklist": "" });
    const staged = h("div", { class: "stack sm" }), list = h("div", { class: "stack sm", "data-doclist": "" });
    const meta = state.meta, docTypes = meta.document_types;
    const typeSelect = (val) => select([{ value: "", label: "Detect automatically" }, ...docTypes.map((t) => ({ value: t.id, label: t.label }))], { value: val, "aria-label": "Document type" });
    const fileInput = h("input", { type: "file", multiple: true, accept: ".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg", class: "sr-only", "aria-label": "Choose files", onChange: () => { addStaged([...fileInput.files]); fileInput.value = ""; } });
    const zone = h("div", { class: "dropzone", "data-dropzone": "", onDragover: (e) => { e.preventDefault(); zone.classList.add("over"); }, onDragleave: () => zone.classList.remove("over"), onDrop: (e) => { e.preventDefault(); zone.classList.remove("over"); addStaged([...e.dataTransfer.files]); } },
      h("div", { class: "ei" }, icon("upload", "lg")), h("div", { class: "strong" }, "Drag and drop documents here"), h("div", { class: "small muted", style: { margin: "4px 0 12px" } }, `PDF, PNG or JPEG · up to ${meta.limits.max_upload_mb} MB each`),
      btn("Choose files", { icon: "plus", onClick: () => fileInput.click() }), fileInput);
    let queue = [];
    function addStaged(files) {
      for (const f of files) {
        const ext = f.name.split(".").pop().toLowerCase();
        if (!ACCEPT.includes(ext)) { toast(`${f.name}: only PDF, PNG or JPEG files are accepted.`, "err"); continue; }
        if (f.size > meta.limits.max_upload_mb * 1048576) { toast(`${f.name} is larger than ${meta.limits.max_upload_mb} MB.`, "err"); continue; }
        queue.push({ file: f, type: guess(f.name) });
      }
      drawStaged();
    }
    function drawStaged() {
      mount(staged, queue.length ? [h("div", { class: "row between" }, h("b", null, `${queue.length} file${queue.length > 1 ? "s" : ""} ready to upload`), btn("Upload all", { kind: "primary", icon: "upload", onClick: (e) => busy(e.currentTarget, uploadAll) })),
        queue.map((q, i) => { const s = typeSelect(q.type); s.addEventListener("change", () => (q.type = s.value));
          return h("div", { class: "doc-card", "data-staged": q.file.name }, h("div", { class: "doc-ico" }, icon("file", "lg")),
            h("div", null, h("div", { class: "strong" }, q.file.name), h("div", { class: "small muted" }, F.bytes(q.file.size)), h("div", { style: { marginTop: "8px", maxWidth: "280px" } }, s), q.progress != null ? h("div", { style: { marginTop: "8px" } }, h("div", { class: "progress" + (q.progress >= 1 ? " ok" : "") }, h("i", { style: { width: Math.round(q.progress * 100) + "%" } })), h("div", { class: "small muted" }, q.progress >= 1 ? "Uploaded. Processing…" : `Uploading ${Math.round(q.progress * 100)}%`)) : null,
              q.error ? h("div", { class: "err small", role: "alert" }, q.error) : null),
            btn("", { icon: "x", kind: "ghost", ariaLabel: "Remove " + q.file.name, onClick: () => { queue.splice(i, 1); drawStaged(); } })); })] : null);
    }
    async function uploadAll() {
      const pending = [...queue];
      for (const q of pending) {
        q.error = null; q.progress = 0; drawStaged();
        try { await api.upload(S.appId, q.file, q.type, (p) => { q.progress = p; drawStaged(); }); queue = queue.filter((x) => x !== q); }
        catch (e) { q.progress = null; q.error = e.message; }
      }
      drawStaged(); await reload();
    }
    async function reload() {
      try {
        const [d] = await Promise.all([api.get(`/applications/${S.appId}/documents`), refreshApp()]);
        S.docs = d.items; drawChecklist(); drawDocs();
        clearInterval(timer);
        if (S.docs.some((x) => ["queued", "processing"].includes(x.status))) timer = setInterval(reload, 1000);
      } catch (e) { clearInterval(timer); }
    }
    function drawChecklist() {
      mount(checklist, S.required.map((r) => h("li", { "data-req": r.doc_type, "data-uploaded": String(r.uploaded) }, r.uploaded ? h("span", { style: { color: "var(--green)" } }, icon("checkc", "lg")) : h("span", { style: { color: "var(--text-3)" } }, icon("minus", "lg")),
        h("span", { class: "grow" }, r.label), r.uploaded ? badge("Uploaded", "green", "check") : badge("Required", "amber", "warn"))));
    }
    function drawDocs() {
      mount(list, S.docs.length ? S.docs.map(docCard) : empty({ icon: "file", title: "No documents uploaded yet", text: "Upload the supporting documents, or load the demo sample set below." }));
    }
    function docCard(d) {
      const fresh = h("input", { type: "file", accept: ".pdf,.png,.jpg,.jpeg", class: "sr-only", "aria-label": "Replace " + d.filename, onChange: async () => { const f = fresh.files[0]; if (!f) return; try { await api.upload(S.appId, f, d.declared_type, null, d.id); toast("Document replaced. Re-processing…"); await reload(); } catch (e) { toast(e.message, "err"); } } });
      return h("div", { class: "doc-card", "data-doc": d.id }, h("div", { class: "doc-ico" }, icon(d.kind === "pdf" ? "file" : "image", "lg")),
        h("div", null, h("div", { class: "row wrap" }, h("span", { class: "strong" }, d.type_label), docStatusBadge(d.status)), h("div", { class: "small muted" }, `${d.filename} · ${F.bytes(d.size)}`),
          d.errors.length ? h("div", { class: "err small", role: "alert", style: { marginTop: "4px" } }, d.errors.map((e) => e.message).join(" ")) : null,
          d.declared_type && d.detected_type && d.declared_type !== d.detected_type ? h("div", { class: "small", style: { color: "var(--amber)", marginTop: "4px" } }, `Looks like a ${d.detected_type_label}, but you chose ${d.type_label}.`) : null,
          h("div", { class: "steps" }, d.steps.map((s) => h("span", { class: "s " + s.state }, s.state === "running" ? h("span", { class: "spinner", style: { width: "12px", height: "12px" } }) : icon({ done: "check", review: "warn", failed: "x", pending: "clock", skipped: "minus" }[s.state] || "clock"), s.label)))),
        h("div", { class: "row wrap", style: { justifyContent: "flex-end", maxWidth: "260px" } },
          btn("Preview", { size: "sm", icon: "eye", disabled: !d.previewable, onClick: () => { const m = modal({ title: d.filename, wide: true, body: h("div", { style: { height: "62vh", display: "flex" } }, docPreview(d, onCleanup)) }); } }),
          btn("Extracted data", { size: "sm", icon: "scan", disabled: d.status === "queued" || d.status === "processing", onClick: async () => { const full = await api.get("/documents/" + d.id); drawer({ title: d.type_label, subtitle: d.filename, body: [kvInfo(full), h("div", { class: "card", style: { marginTop: "14px" } }, fieldRows(full.fields))] }); } }),
          btn("Replace", { size: "sm", icon: "replace", onClick: () => fresh.click() }), fresh,
          btn("Remove", { size: "sm", icon: "trash", kind: "danger", onClick: async () => { if (await confirmDialog({ title: "Remove document?", message: `“${d.filename}” will be removed from this application and its stored file deleted.`, confirmLabel: "Remove", danger: true })) { try { await api.del("/documents/" + d.id); toast("Document removed."); await reload(); } catch (e) { toast(e.message, "err"); } } } })));
    }
    // demo helper (clearly labelled)
    const scen = select([["clean", "Clean set: everything consistent"], ["institution_id_mismatch", "Institution ID mismatch"], ["expired_affiliation", "Expired affiliation letter"], ["missing_occupancy", "Missing occupancy certificate"], ["intake_conflict", "Intake conflict"], ["duplicate_reuse", "Reused occupancy certificate"]].map(([value, label]) => ({ value, label })), { "aria-label": "Demo scenario" });
    const demo = h("div", { class: "banner", "data-demo-panel": "" }, icon("info"), h("div", { class: "grow stack sm" }, h("div", null, badge("Demo mode", "navy", "info", "sq"), " ", h("b", null, "Load a synthetic sample set"), ". Fictional documents are generated for this application and sent through the same real upload, OCR and validation pipeline."),
      h("div", { class: "row wrap" }, h("div", { style: { minWidth: "260px" } }, scen), btn("Load sample documents", { icon: "plus", onClick: (e) => busy(e.currentTarget, async () => { try { await api.post(`/applications/${S.appId}/demo-documents`, { scenario: scen.value }); toast("Sample documents uploaded. Processing…"); await reload(); } catch (ex) { toast(ex.message, "err"); } }) }))));
    reload();
    const next = btn("Continue", { kind: "primary", onClick: () => { clearInterval(timer); go(3); } });
    return h("div", { class: "grid g-main" }, h("div", { class: "stack" }, card("Step 3 · Documents", [zone, staged, h("div", { style: { marginTop: "14px" } }, list), nav(() => { clearInterval(timer); go(1); }, next)]), state.meta.demo_mode ? demo : null),
      card("Required documents", [checklist, h("p", { class: "small muted", style: { margin: "10px 0 0" } }, "This list comes from the active ruleset. Missing items are reported as findings, never silently ignored.")]));
  }
  const kvInfo = (d) => h("div", { class: "stack sm" }, h("div", { class: "row wrap" }, docStatusBadge(d.status), d.text_source ? badge(d.text_source === "ocr" ? `OCR · ${F.pct(d.ocr_mean_conf)}` : "Text layer", "outline", "scan") : null, d.page_count ? badge(F.plural(d.page_count, "page"), "outline") : null),
    d.detected_type_label ? h("div", { class: "small muted" }, "Classified as ", h("b", null, d.detected_type_label)) : null);

  // ---------------------------------------------------------------- step 4
  function step4() {
    const out = h("div", { class: "stack", "data-precheck": "" });
    const run = btn("Run pre-check", { icon: "shield", onClick: (e) => busy(e.currentTarget, async () => {
      try { const r = await api.post(`/applications/${S.appId}/validate`); const f = await api.get(`/applications/${S.appId}/findings`); const a = r.application;
        mount(out, h("div", { class: "banner " + (f.total ? "warn" : "ok") }, icon(f.total ? "warn" : "checkc"), h("div", null, f.total ? `Pre-check found ${F.plural(f.total, "finding")}. You can fix them now or submit as they are; a reviewer will see everything.` : "Pre-check found no findings.")), findingList(f.items, { emptyText: "All documents are consistent with the application." })); }
      catch (ex) { mount(out, errorState(ex)); }
    }) });
    const missing = S.required.filter((r) => !r.uploaded);
    const next = btn("Continue to submit", { kind: "primary", onClick: () => go(4) });
    const inst = S.inst;
    return h("div", { class: "grid g-main" }, h("div", { class: "stack" }, card("Step 4 · Review your application", [
      h("div", { class: "grid g2" }, h("div", null, h("div", { class: "f-label" }, "Institution"), kv([["Name", inst.name], ["Institution ID", inst.institution_id || "Not provided"], ["State / district", [inst.state, inst.district].filter(Boolean).join(" / ")], ["Address", inst.address || "—"], ["Contact", [inst.contact_name, inst.contact_email, inst.contact_phone].filter(Boolean).join(" · ") || "—"]])),
        h("div", null, h("div", { class: "f-label" }, "Application"), kv([["Category", state.meta.application_types.find((t) => t.id === S.application_type)?.label], ["Academic year", S.academic_year || "—"], ["Courses", S.courses.filter((c) => c.name).map((c) => `${c.name} (${c.intake || "—"})`).join("; ") || "—"], ["Reference", S.app?.reference || S.appId], ["Documents", F.plural(S.docs.length || S.app?.document_count || 0, "file")]]))),
      missing.length ? h("div", { class: "banner warn", style: { marginTop: "14px" } }, icon("warn"), h("div", null, h("b", null, "Missing required documents: "), missing.map((m) => m.label).join(", "), ". You can still submit; the reviewer will see this as a finding.")) : null,
      nav(() => go(2), next)]),
      card("Pre-check (optional)", [h("p", { class: "muted", style: { marginTop: 0 } }, "Run the validation rules now to catch inconsistencies before you submit. This does not submit the application."), run, h("div", { style: { marginTop: "14px" } }, out)])),
      card("Documents", h("div", { class: "stack sm" }, (S.docs.length ? S.docs : []).map((d) => h("div", { class: "row between" }, h("span", null, d.type_label), docStatusBadge(d.status))), !S.docs.length ? h("span", { class: "muted" }, "No documents.") : null)));
  }

  // ---------------------------------------------------------------- step 5
  function step5() {
    const sure = h("input", { type: "checkbox", id: "confirm-accurate" });
    const submit = btn(S.resubmit ? "Resubmit for validation" : "Submit for validation", { kind: "primary lg", icon: "arrow", onClick: (e) => { if (!sure.checked) { toast("Please confirm the declaration first.", "err"); sure.focus(); return; } busy(e.currentTarget, async () => {
      try { await api.post(`/applications/${S.appId}/submit`); toast("Submitted. Validation is running.", "ok", { label: "View application", fn: () => navigate("/applications/" + S.appId) }); await navigate("/applications/" + S.appId); }
      catch (ex) { toast(ex.message, "err"); } }); } });
    return card("Step 5 · Submit", h("div", { class: "stack lg" }, h("div", { class: "banner" }, icon("info"), h("div", null, "Submitting starts automated validation: file checks, OCR, field extraction, cross-document and rule checks. A reviewer then sees the findings. ", h("b", null, "Nothing is sent to any government system."))),
      h("label", { class: "row top", for: "confirm-accurate", style: { cursor: "pointer", alignItems: "flex-start" } }, sure, h("span", null, "I confirm that the details and documents are accurate to the best of my knowledge. I understand this is a demonstration prototype and the outcome is not an official decision.")),
      nav(() => go(3), submit)));
  }
  draw();
  return root;
}
