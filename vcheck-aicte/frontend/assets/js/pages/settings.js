import { h, icon, mount } from "../dom.js";
import { api, need } from "../api.js";
import { state } from "../state.js";
import { query, setQuery, navigate } from "../router.js";
import { btn, busy, card, field, input, kv, tabs, toast, roleBadge, sw, badge, simBadge, confirmDialog, load, setFieldErrors, skelRows, select } from "../ui.js";
import * as F from "../fmt.js";
import { signOut } from "../main.js";

export default async function settings({ user }) {
  const admin = user.role === "admin";
  let tab = query().tab || "profile";
  const body = h("div");
  const items = [{ id: "profile", label: "Profile" }, { id: "organization", label: "Organization" }, { id: "notifications", label: "Notifications" }, { id: "security", label: "Security" }, { id: "system", label: "System information" }, ...(admin ? [{ id: "admin", label: "Administration" }] : [])];
  const draw = () => { const c = h("div"); mount(body, tabs(items, tab, (t) => { tab = t; setQuery({ tab: t }); draw(); }), c); ({ profile, organization, notifications, security, system, admin: adminTab })[tab]?.(c); };

  async function me() { return need(await api.get("/settings/profile"), ["name", "email", "role"], "profile"); }
  const profile = (c) => load(c, me, (p) => {
    const name = input({ name: "name", value: p.name, maxlength: 100 }), form = h("form", { class: "stack", style: { maxWidth: "460px" }, novalidate: true, onSubmit: async (e) => { e.preventDefault(); try { const r = await api.put("/settings/profile", { name: name.value }); state.user.name = r.name; toast("Profile saved."); } catch (ex) { setFieldErrors(form, ex.details); toast(ex.message, "err"); } } },
      field("Full name", name), field("Email", Object.assign(input({ value: p.email, disabled: true }), {}), { hint: "Your sign-in identity cannot be changed in the demo." }), h("div", null, h("div", { class: "label" }, "Role"), roleBadge(p.role)), h("div", null, btn("Save profile", { kind: "primary", type: "submit" })));
    return card("Profile", form);
  });
  const organization = (c) => load(c, me, (p) => {
    const org = input({ value: p.organization || "", maxlength: 150 });
    return h("div", { class: "grid g2" }, card("Organization", h("div", { class: "stack", style: { maxWidth: "460px" } }, field("Organization name", org), btn("Save", { kind: "primary", onClick: async (e) => busy(e.currentTarget, async () => { try { await api.put("/settings/profile", { organization: org.value }); toast("Organization saved."); } catch (ex) { toast(ex.message, "err"); } }) }))),
      card("What this role can do", h("ul", { class: "checklist", "data-permissions": "" }, p.permissions.map((x) => h("li", null, icon("check"), h("span", { class: "mono small" }, x))))));
  });
  const notifications = (c) => load(c, me, (p) => {
    const row = (key, title, desc) => h("div", { class: "row between", style: { padding: "12px 0", borderBottom: "1px solid var(--border)" } }, h("div", null, h("div", { class: "strong" }, title), h("div", { class: "small muted" }, desc)), sw(p.notifications[key], async (v, el) => { try { await api.put("/settings/notifications", { [key]: v }); toast("Preference saved."); } catch (e) { el.checked = !v; toast(e.message, "err"); } }, title));
    return card("Notifications", [row("processing", "Processing results", "Alert me when validation of my applications finishes."), row("review", "Review updates", "Alert me about assignments, escalations, corrections and decisions."), h("p", { class: "small muted", style: { margin: "12px 0 0" } }, "Alerts appear in the bell menu. This prototype does not send email or SMS.")]);
  });
  const security = (c) => {
    const cur = input({ type: "password", name: "current_password", autocomplete: "current-password" }), nw = input({ type: "password", name: "new_password", autocomplete: "new-password" }), cf = input({ type: "password", autocomplete: "new-password" });
    const form = h("form", { class: "stack", style: { maxWidth: "460px" }, novalidate: true, onSubmit: async (e) => { e.preventDefault(); setFieldErrors(form, null);
      if (nw.value !== cf.value) { cf.classList.add("invalid"); return toast("The new passwords do not match.", "err"); }
      try { await api.post("/auth/change-password", { current_password: cur.value, new_password: nw.value }); toast("Password changed."); form.reset(); } catch (ex) { setFieldErrors(form, ex.details); toast(ex.message, "err"); } } },
      field("Current password", cur), field("New password", nw, { hint: "At least 10 characters, with upper- and lower-case letters and a digit." }), field("Confirm new password", cf), h("div", null, btn("Change password", { kind: "primary", type: "submit" })));
    mount(c, h("div", { class: "grid g2" }, card("Password", form), card("Session", h("div", { class: "stack" }, h("p", { style: { margin: 0 } }, "Sessions expire automatically and are revoked server-side when you sign out. Demo passwords are public; never reuse them."), h("div", null, btn("Sign out of this session", { icon: "logout", onClick: signOut }))))));
  };
  const system = (c) => load(c, async () => api.get("/settings/system"), (s) => h("div", { class: "grid g2" }, card("System information", kv([["Product", s.product], ["Version", s.version], ["Problem statement", s.problem_statement], ["Database", s.database], ["OCR engine", s.ocr_available ? s.ocr_engine : h("span", { style: { color: "var(--red)" } }, "Unavailable")], ["Ruleset", "v" + s.ruleset_version], ["Python", s.python], ["Demo mode", s.demo_mode ? "On" : "Off"], ["Verification source", s.verification_mode], ["Max upload", s.max_upload_mb + " MB"], ["Session lifetime", s.token_ttl_minutes + " minutes"]])),
    card("Important", h("div", { class: "stack" }, h("div", { class: "banner" }, icon("info"), h("div", null, s.affiliation)), h("p", { class: "muted", style: { margin: 0 } }, "V-Check issues no government approval and performs no official verification. Simulated checks are always labelled as simulation.")))));
  const adminTab = (c) => load(c, async () => need(await api.get("/settings/admin"), ["providers"], "admin settings"), (s) => {
    let mode = s.verification_mode;
    const radios = s.providers.map((p) => h("label", { class: "radio-card" + (p.available ? "" : " off"), "data-provider": p.id }, h("input", { type: "radio", name: "provider", value: p.id, checked: p.id === mode, disabled: !p.available, onChange: () => (mode = p.id) }), h("span", null, h("span", { class: "strong" }, p.name, " "), p.simulated ? simBadge() : null, !p.available ? badge("Not configured", "", "lock") : null, h("span", { class: "small muted", style: { display: "block" } }, p.description))));
    const up = input({ type: "number", min: 1, max: 25, value: s.max_upload_mb, name: "max_upload_mb" }), pg = input({ type: "number", min: 1, max: 100, value: s.max_pdf_pages, name: "max_pdf_pages" });
    let demo = s.demo_mode;
    const save = btn("Save administrator settings", { kind: "primary", onClick: (e) => busy(e.currentTarget, async () => { try { const r = await api.put("/settings/admin", { verification_mode: mode, max_upload_mb: Number(up.value), max_pdf_pages: Number(pg.value), demo_mode: demo }); state.meta = await api.meta(); toast("Settings saved."); } catch (ex) { toast(ex.message, "err"); } }) });
    return h("div", { class: "stack lg" }, h("div", { class: "grid g2" }, card("Verification provider", h("div", { class: "stack" }, radios, h("p", { class: "small muted", style: { margin: 0 } }, "DigiLocker and other government sources require authorised credentials that this prototype does not have, so they cannot be enabled."))),
      card("Processing configuration", h("div", { class: "stack" }, field("Maximum upload size (MB)", up), field("Maximum PDF pages", pg), h("div", { class: "row between" }, h("div", null, h("div", { class: "strong" }, "Demo mode"), h("div", { class: "small muted" }, "Allows loading synthetic sample documents and resetting demo data.")), sw(s.demo_mode, (v) => (demo = v), "Demo mode")), save))),
      h("div", { class: "grid g2" }, card("Rule configuration", h("div", { class: "stack" }, h("p", { style: { margin: 0 } }, "Rules are deterministic and version-controlled. Enable, disable and version them from the Rules page."), btn("Open rules", { icon: "book", href: "/rules" }))),
        card("Demo data", h("div", { class: "stack" }, h("p", { style: { margin: 0 } }, "Rebuild the six scenario applications (APP-001 to APP-006). Applications created by users are kept."), btn("Reset demo applications", { kind: "danger", icon: "refresh", onClick: async () => { if (await confirmDialog({ title: "Reset demo applications?", message: "The six seeded scenarios, their review history and their documents will be rebuilt from scratch. User-created applications are not affected.", confirmLabel: "Reset", danger: true })) { try { await api.post("/demo/reset"); toast("Demo applications were reset."); } catch (e) { toast(e.message, "err"); } } } })))));
  });
  draw();
  return h("div", { class: "stack lg" }, h("div", { class: "page-h" }, h("div", null, h("h1", null, "Settings"), h("p", null, "Your profile, notifications and security" + (admin ? ", plus system administration." : ".")))), body);
}
