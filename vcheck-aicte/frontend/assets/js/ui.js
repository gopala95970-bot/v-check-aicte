import { h, icon, mount, clear } from "./dom.js";
import * as F from "./fmt.js";

// ------------------------------------------------------------------ toasts
export function toast(message, kind = "ok", action) {
  const root = document.getElementById("toasts");
  const el = h("div", { class: "toast " + kind, role: kind === "err" ? "alert" : "status" },
    icon(kind === "err" ? "alert" : "checkc", "lg"),
    h("div", { class: "grow" }, h("div", null, message),
      action ? h("button", { class: "t-act", onClick: () => { action.fn(); el.remove(); } }, action.label) : null));
  while (root.children.length >= 3) root.firstChild.remove();       // never let alerts bury the page
  root.append(el);
  setTimeout(() => el.remove(), action ? 8000 : 4200);
}

// ------------------------------------------------------------------ badges
export function badge(text, variant = "", ic = null, extra = "") {
  return h("span", { class: `badge ${variant} ${extra}` }, ic ? icon(ic) : null, text);
}
const APP_STATUS = {
  draft: ["", "pencil"], submitted: ["blue", "clock"], processing: ["blue", "loader"], validation_complete: ["green", "checkc"],
  review_required: ["amber", "warn"], corrections_requested: ["amber", "message"], resubmitted: ["blue", "refresh"],
  approved_demo: ["green", "checkc"], rejected_demo: ["red", "xc"],
};
export const appStatusBadge = (status, label) => { const [v, i] = APP_STATUS[status] || ["", "info"]; return badge(label || F.titleCase(status), v, i); };
const VALID = { passed: ["green", "check", "Passed"], review_required: ["amber", "warn", "Review required"], failed: ["red", "x", "Failed"], not_run: ["", "minus", "Not run"] };
export const validationBadge = (v) => { const [c, i, t] = VALID[v] || ["", "minus", F.titleCase(v)]; return badge(t, c, i); };
export const severityBadge = (sev, critical) => critical ? badge("Critical", "red", "alert") :
  badge(F.titleCase(sev), { high: "red", medium: "amber", low: "blue" }[sev] || "", { high: "alert", medium: "warn", low: "info" }[sev] || "info");
export const outcomeBadge = (o) => o === "failed" ? badge("Failed", "red", "x") : badge("Review required", "amber", "warn");
const STAGE = { passed: ["green", "check", "Passed"], review: ["amber", "warn", "Review"], failed: ["red", "x", "Failed"], running: ["blue", "loader", "Running"], pending: ["", "clock", "Pending"], skipped: ["", "minus", "Skipped"],
  done: ["green", "check", "Done"] };
export const stageBadge = (s) => { const [c, i, t] = STAGE[s] || ["", "info", s]; return badge(t, c, i); };
const FSTAT = { open: ["red", "alert", "Open"], under_review: ["blue", "eye", "Under review"], resolved: ["green", "check", "Resolved"], accepted_with_explanation: ["green", "check", "Accepted with explanation"] };
export const findingStatusBadge = (s) => { const [c, i, t] = FSTAT[s] || ["", "info", s]; return badge(t, c, i); };
const DSTAT = { queued: ["blue", "clock", "Queued"], processing: ["blue", "loader", "Processing"], processed: ["green", "check", "Processed"], unreadable: ["amber", "warn", "Needs manual review"], rejected: ["red", "x", "Rejected"] };
export const docStatusBadge = (s) => { const [c, i, t] = DSTAT[s] || ["", "info", s]; return badge(t, c, i); };
export const ruleKindBadge = (k) => k === "official" ? badge("Officially sourced", "green", "shield") : badge("Demonstration rule", "amber", "info");
export const simBadge = () => badge("Simulation", "navy", "info", "sq");
export const roleBadge = (r) => badge(F.titleCase(r), r === "admin" ? "navy" : r === "reviewer" ? "blue" : "", "user");

// ------------------------------------------------------------------ buttons / forms
export function btn(label, { kind = "", icon: ic, onClick, size = "", href, title, type = "button", disabled, ariaLabel } = {}) {
  const props = { class: `btn ${kind} ${size}`, title, "aria-label": ariaLabel, disabled };
  const kids = [ic ? icon(ic) : null, label];
  if (href) return h("a", { ...props, href }, ...kids);
  return h("button", { ...props, type, onClick }, ...kids);
}
/** Run an async action with the button disabled + spinner so double-clicks cannot double-submit. */
export async function busy(button, fn) {
  if (button.disabled) return;
  const old = [...button.childNodes];
  button.disabled = true;
  clear(button).append(h("span", { class: "spinner" }), " ", old.map((n) => n.textContent).join("").trim() || "Working…");
  try { return await fn(); } finally { clear(button).append(...old); button.disabled = false; }
}
export function field(label, control, { hint, error, id } = {}) {
  const fid = id || "f" + Math.random().toString(36).slice(2, 8);
  control.id = control.id || fid;
  return h("div", { class: "field" }, h("label", { for: control.id }, label),
    control, hint ? h("div", { class: "hint" }, hint) : null, error ? h("div", { class: "err", role: "alert" }, error) : null);
}
export const input = (props = {}) => h("input", { class: "input", ...props });
export const select = (options, props = {}) => {
  const s = h("select", { class: "select", ...props, value: undefined }, options.map((o) => h("option", { value: o.value ?? o }, o.label ?? o)));
  if (props.value != null) s.value = props.value;
  return s;
};
export const sw = (checked, onChange, label) => {
  const i = h("input", { type: "checkbox", checked: !!checked, "aria-label": label, onChange: () => onChange(i.checked, i) });
  return h("span", { class: "switch" }, i, h("span", { class: "track" }));
};
export function setFieldErrors(form, details) {
  form.querySelectorAll(".err.srv").forEach((e) => e.remove());
  const f = (details && details.fields) || {};
  for (const [k, msg] of Object.entries(f)) {
    const el = form.querySelector(`[name="${k}"]`);
    if (el) { el.classList.add("invalid"); el.closest(".field")?.append(h("div", { class: "err srv", role: "alert" }, msg)); }
  }
}

// ------------------------------------------------------------------ states
export const skelRows = (n = 5) => h("div", { class: "stack", style: { padding: "16px" } }, Array.from({ length: n }, () => h("span", { class: "skel", style: { height: "18px" } })));
export const skelCards = (n = 4, cls = "g4") => h("div", { class: "grid " + cls }, Array.from({ length: n }, () => h("div", { class: "card metric" }, h("span", { class: "skel", style: { width: "50%" } }), h("span", { class: "skel h-lg", style: { width: "35%" } }), h("span", { class: "skel", style: { width: "70%" } }))));
export function empty({ icon: ic = "folder", title, text, action }) {
  return h("div", { class: "empty" }, h("div", { class: "ei" }, icon(ic, "lg")), h("b", null, title), text ? h("p", null, text) : null, action || null);
}
export function errorState(err, retry) {
  return h("div", { class: "empty" }, h("div", { class: "ei", style: { background: "var(--red-bg)", color: "var(--red)" } }, icon("alert", "lg")),
    h("b", null, "We couldn't load this"), h("p", null, err?.message || "Something went wrong."),
    err?.requestId ? h("p", { class: "small muted" }, "Reference: " + err.requestId) : null,
    retry ? btn("Try again", { icon: "refresh", onClick: retry }) : null);
}
/** Skeleton -> content with a human-readable error + retry. `render` returns a Node. */
export async function load(container, loader, render, skeleton = skelRows()) {
  mount(container, skeleton);
  try {
    const data = await loader();
    mount(container, render(data));          // rendering into a detached node is harmless if the user navigated away
  } catch (e) {
    if (e.status === 401) return;
    mount(container, errorState(e, () => load(container, loader, render, skeleton)));
  }
}
export function pager(meta, onPage, noun = "results") {
  const pages = Math.max(1, Math.ceil(meta.total / meta.page_size));
  const from = meta.total ? (meta.page - 1) * meta.page_size + 1 : 0, to = Math.min(meta.total, meta.page * meta.page_size);
  return h("div", { class: "pager" }, h("span", null, `${from}–${to} of ${meta.total} ${noun}`),
    h("div", { class: "row" }, btn("Previous", { size: "sm", icon: "left", disabled: meta.page <= 1, onClick: () => onPage(meta.page - 1) }),
      h("span", null, `Page ${meta.page} of ${pages}`),
      btn("Next", { size: "sm", disabled: meta.page >= pages, onClick: () => onPage(meta.page + 1) })));
}
export const debounce = (fn, wait = 300) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), wait); }; };

// ------------------------------------------------------------------ overlays
const root = () => document.getElementById("overlay-root");
export function modal({ title, body, actions = [], wide = false, onClose }) {
  const prev = document.activeElement;
  const scrim = h("div", { class: "scrim", onMousedown: (e) => e.target === scrim && close() });
  const close = () => { scrim.remove(); document.removeEventListener("keydown", esc); prev?.focus?.(); onClose?.(); };
  const esc = (e) => e.key === "Escape" && close();
  document.addEventListener("keydown", esc);
  const foot = actions.length ? h("div", { class: "mf" }, actions.map((a) => {
    const b = btn(a.label, { kind: a.kind || "", icon: a.icon, onClick: async () => { if (a.keepOpen) return a.onClick?.(b, ctl); const r = await busy(b, () => a.onClick?.(b, ctl)); if (r !== false) close(); } });
    return b;
  })) : null;
  const ctl = { close, el: scrim };
  scrim.append(h("div", { class: "modal" + (wide ? " wide" : ""), role: "dialog", "aria-modal": "true", "aria-label": title },
    h("div", { class: "mh row between" }, h("h2", null, title), h("button", { class: "iconbtn", "aria-label": "Close", onClick: close }, icon("x"))),
    h("div", { class: "mb" }, body), foot));
  root().append(scrim);
  (scrim.querySelector("textarea,input,select") || scrim.querySelector(".mf .btn:last-child") || scrim.querySelector(".iconbtn"))?.focus();
  return ctl;
}
export function confirmDialog({ title, message, confirmLabel = "Confirm", danger = false, extra }) {
  return new Promise((resolve) => {
    let done = false; const fin = (v) => { if (!done) { done = true; resolve(v); } };
    modal({ title, body: h("div", { class: "stack" }, h("p", { style: { margin: 0 } }, message), extra || null),
      actions: [{ label: "Cancel", onClick: () => { fin(false); } }, { label: confirmLabel, kind: danger ? "danger solid" : "primary", onClick: () => { fin(true); } }], onClose: () => fin(false) });
  });
}
/** Ask for remarks (textarea). Resolves to the text, or null if cancelled. */
export function remarksDialog({ title, message, label = "Remarks", placeholder = "", minLen = 5, confirmLabel = "Submit", danger = false, optional = false, notice }) {
  return new Promise((resolve) => {
    let done = false; const fin = (v) => { if (!done) { done = true; resolve(v); } };
    const ta = h("textarea", { class: "textarea", placeholder, "aria-label": label, name: "remarks" });
    const err = h("div", { class: "err hide", role: "alert" });
    const check = () => { const v = ta.value.trim(); if (!optional && v.length < minLen) { err.textContent = `Please enter at least ${minLen} characters.`; err.classList.remove("hide"); ta.classList.add("invalid"); ta.focus(); return false; } return true; };
    modal({ title,
      body: h("div", { class: "stack" }, message ? h("p", { style: { margin: 0 } }, message) : null, notice ? h("div", { class: "banner warn" }, icon("warn"), h("div", null, notice)) : null, h("div", { class: "field" }, h("label", null, label), ta, err)),
      actions: [{ label: "Cancel", onClick: () => { fin(null); } },
        { label: confirmLabel, kind: danger ? "danger solid" : "primary", onClick: () => { if (!check()) return false; fin(ta.value.trim()); } }], onClose: () => fin(null) });
  });
}
export function drawer({ title, subtitle, body }) {
  const scrim = h("div", { class: "drawer-scrim", onMousedown: () => close() });
  const el = h("aside", { class: "drawer", role: "dialog", "aria-modal": "true", "aria-label": title },
    h("div", { class: "dh" }, h("div", null, h("h2", null, title), subtitle ? h("div", { class: "muted small", style: { marginTop: "2px" } }, subtitle) : null),
      h("button", { class: "iconbtn", "aria-label": "Close", onClick: () => close() }, icon("x"))), h("div", { class: "db" }, body));
  const esc = (e) => e.key === "Escape" && close();
  const close = () => { scrim.remove(); el.remove(); document.removeEventListener("keydown", esc); };
  document.addEventListener("keydown", esc);
  root().append(scrim, el);
  el.querySelector(".iconbtn")?.focus();
  return { close };
}

export const metric = ({ label, value, sub, ic, tone = "" }) => h("div", { class: `card metric ${tone}` },
  h("div", { class: "m-top" }, h("span", null, label), h("span", { class: "m-ico" }, icon(ic))), h("div", { class: "m-val", "data-metric": label }, value), sub ? h("div", { class: "m-sub" }, sub) : null);
export const kv = (pairs) => h("dl", { class: "kv" }, pairs.filter(Boolean).map(([k, v]) => [h("dt", null, k), h("dd", null, v ?? "—")]));
export const card = (title, body, { actions, flush = false } = {}) => h("section", { class: "card" },
  title ? h("div", { class: "card-h" }, h("h3", null, title), actions || null) : null, h("div", { class: "card-b" + (flush ? " flush" : "") }, body));
export const tabs = (items, current, onSelect) => h("div", { class: "tabs", role: "tablist" }, items.map((t) =>
  h("button", { class: "tab", role: "tab", "aria-selected": String(t.id === current), "data-tab": t.id, onClick: () => onSelect(t.id) }, t.label, t.count != null ? h("span", { class: "n" }, t.count) : null)));
export const disclaimer = () => "V-Check AICTE is an independent demonstration prototype developed for Smart India Hackathon. It is not an official AICTE portal and does not issue government approvals or official verification.";
