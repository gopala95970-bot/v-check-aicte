import { h, icon, mount } from "../dom.js";
import { api, need } from "../api.js";
import { state } from "../state.js";
import { navigate, query, setQuery } from "../router.js";
import { btn, busy, card, empty, errorState, input, select, skelRows, debounce, tabs, badge, ruleKindBadge, sw, toast, remarksDialog, drawer, kv, modal, field, severityBadge, load } from "../ui.js";
import * as F from "../fmt.js";

export default async function rules({ user }) {
  const admin = user.role === "admin";
  let tab = query().tab || "rules", data = null;
  const body = h("div"), top = h("div");
  const root = h("div", { class: "stack lg" }, top, body);
  async function reload() {
    data = need(await api.get("/rules"), ["rules", "ruleset"], "rules");
    mount(top, h("div", { class: "page-h" }, h("div", null, h("h1", null, "Rules"), h("p", null, `Ruleset ${data.ruleset.id} · version `, h("b", { "data-ruleset-version": "" }, data.ruleset.version), ` · effective ${data.ruleset.effective_date}. Rules are deterministic and version-controlled; an AI model never edits them.`)),
      admin ? btn("Create new rule version", { kind: "primary", icon: "plus", onClick: newVersion }) : null),
      h("div", { class: "banner warn" }, icon("warn"), h("div", null, data.ruleset.notice)),
      h("div", { class: "grid g2" }, h("div", { class: "row top" }, ruleKindBadge("official"), h("span", { class: "small muted" }, data.legend.official.replace("Officially sourced: ", ""))), h("div", { class: "row top" }, ruleKindBadge("demonstration"), h("span", { class: "small muted" }, data.legend.demonstration.replace("Demonstration rule: ", "")))));
    draw();
  }
  function draw() {
    const items = [{ id: "rules", label: "Rules", count: data.rules.length }, { id: "history", label: "Version history" }];
    const content = h("div"); mount(body, tabs(items, tab, (t) => { tab = t; setQuery({ tab: t }); draw(); }), content);
    tab === "rules" ? rulesTab(content) : historyTab(content);
  }
  function rulesTab(c) {
    const cats = [...new Set(data.rules.map((r) => r.category))];
    const q = input({ type: "search", placeholder: "Search rules…", "aria-label": "Search rules", class: "input" });
    const cat = select([{ value: "", label: "All categories" }, ...cats.map((x) => ({ value: x, label: x }))], { "aria-label": "Category" });
    const kind = select([{ value: "", label: "All kinds" }, { value: "official", label: "Officially sourced" }, { value: "demonstration", label: "Demonstration" }], { "aria-label": "Kind" });
    const en = select([{ value: "", label: "Enabled & disabled" }, { value: "1", label: "Enabled" }, { value: "0", label: "Disabled" }], { "aria-label": "Status" });
    const tbl = h("div");
    const paint = () => {
      const t = q.value.toLowerCase();
      const rows = data.rules.filter((r) => (!t || (r.rule_id + r.name + r.category).toLowerCase().includes(t)) && (!cat.value || r.category === cat.value) && (!kind.value || r.kind === kind.value) && (!en.value || String(+r.enabled) === en.value));
      mount(tbl, rows.length ? h("div", { class: "table-wrap" }, h("table", { class: "dt" }, h("thead", null, h("tr", null, ["Rule ID", "Name", "Category", "Version", "Status", "Kind", "Effective", "Source", "Last updated"].map((x) => h("th", null, x)))),
        h("tbody", null, rows.map((r) => h("tr", { class: "clickable", "data-rule": r.rule_id, onClick: (e) => { if (!e.target.closest(".switch")) detail(r.rule_id); } },
          h("td", null, h("span", { class: "id" }, r.rule_id)), h("td", { style: { minWidth: "200px", maxWidth: "280px" } }, h("div", { class: "strong" }, r.name), h("div", { class: "small muted" }, "Severity " + r.severity)), h("td", { class: "small" }, r.category), h("td", { class: "mono small" }, "v" + r.version),
          h("td", null, admin ? h("span", { class: "row" }, sw(r.enabled, (v, el) => toggle(r, v, el), `Enable ${r.rule_id}`), h("span", { class: "small" }, r.enabled ? "Enabled" : "Disabled")) : (r.enabled ? badge("Enabled", "green", "check") : badge("Disabled", "", "minus"))),
          h("td", null, ruleKindBadge(r.kind)), h("td", { class: "nowrap small" }, r.effective_date), h("td", { class: "small" }, h("span", { class: "clip", title: r.source_ref }, r.source_ref)), h("td", { class: "nowrap small" }, r.last_updated ? F.date(r.last_updated) : "Initial")))))) : empty({ icon: "search", title: "No rules match", text: "Adjust the filters." }));
    };
    q.addEventListener("input", debounce(paint, 200)); [cat, kind, en].forEach((e) => e.addEventListener("change", paint)); paint();
    mount(c, h("section", { class: "card" }, h("div", { class: "toolbar" }, h("div", { class: "search" }, icon("search"), q), cat, kind, en), tbl));
  }
  async function toggle(r, value, el) {
    const note = await remarksDialog({ title: `${value ? "Enable" : "Disable"} ${r.rule_id}`, message: "This creates a new immutable ruleset version. Existing findings keep the rule version they were produced with; re-run validation to apply the change.", label: "Reason for the change", minLen: 5, confirmLabel: `${value ? "Enable" : "Disable"} rule` });
    if (note === null) { el.checked = !value; return; }
    try { const res = await api.patch("/rules/" + r.rule_id, { enabled: value, note }); toast(`Ruleset is now v${res.ruleset.version}.`); await reload(); } catch (e) { el.checked = !value; toast(e.message, "err"); }
  }
  async function detail(id) {
    const body = h("div", null, h("span", { class: "spinner" }));
    drawer({ title: id, subtitle: "Rule details", body });
    try {
      const r = need(await api.get("/rules/" + id), ["rule_id", "params"], "rule");
      mount(body, h("div", { class: "stack lg", "data-rule-detail": id }, h("div", null, h("h3", { style: { marginBottom: "6px" } }, r.name), h("div", { class: "row wrap" }, ruleKindBadge(r.kind), severityBadge(r.severity), r.enabled ? badge("Enabled", "green", "check") : badge("Disabled", "", "minus"))),
        h("p", { style: { margin: 0 } }, r.description),
        kv([["Category", r.category], ["Check type", r.check], ["Version", "v" + r.version], ["Effective", r.effective_date], ["Applies to", r.applies_to.join(", ")], ["Source", r.source_ref], ["Source status", r.source_status.replace(/_/g, " ")], ["Open findings", r.open_findings]]),
        h("div", null, h("div", { class: "f-label" }, "Parameters"), h("pre", { class: "evidence" }, JSON.stringify(r.params, null, 2))),
        h("div", null, h("div", { class: "f-label" }, "Recommended action shown to users"), h("div", { class: "rec" }, r.remediation)),
        h("div", null, h("div", { class: "f-label" }, "Change history"), r.history.length ? h("ul", { class: "timeline" }, r.history.map((x) => h("li", null, h("b", null, "v" + x.version), " · ", x.created_by, h("div", null, x.change_note), h("div", { class: "small muted" }, F.dateTime(x.created_at))))) : h("div", { class: "muted small" }, "No changes since the initial ruleset."))));
    } catch (e) { mount(body, errorState(e)); }
  }
  function newVersion() {
    const rs = select(data.rules.map((r) => ({ value: r.rule_id, label: `${r.rule_id} · ${r.name}` })), { name: "rule" });
    const sev = select([{ value: "", label: "Keep current" }, "high", "medium", "low", "info"].map((x) => (x.value !== undefined ? x : { value: x, label: F.titleCase(x) })), { name: "severity" });
    const en = select([{ value: "", label: "Keep current" }, { value: "1", label: "Enable" }, { value: "0", label: "Disable" }], { name: "enabled" });
    const rem = h("textarea", { class: "textarea", name: "remediation", placeholder: "Leave blank to keep the current text" });
    const ver = input({ name: "new_version", placeholder: `Auto (next patch after ${data.ruleset.version})` });
    const note = h("textarea", { class: "textarea", name: "note", placeholder: "Why is this change being made? (required)" });
    modal({ title: "Create new rule version", body: h("div", { class: "stack" }, h("div", { class: "banner" }, icon("info"), h("div", null, "Only severity, enabled state and the recommended-action text can be changed here. Provenance (source status) can never be edited.")),
      field("Rule", rs), h("div", { class: "grid g2" }, field("Severity", sev), field("State", en)), field("Recommended action text", rem), field("New ruleset version", ver, { hint: "x.y.z, greater than the current version." }), field("Change note *", note)),
      actions: [{ label: "Cancel" }, { label: "Create version", kind: "primary", onClick: async () => {
        const ch = {}; if (sev.value) ch.severity = sev.value; if (en.value) ch.enabled = en.value === "1"; if (rem.value.trim()) ch.remediation = rem.value.trim();
        if (!Object.keys(ch).length) { toast("Choose at least one change.", "err"); return false; }
        if (note.value.trim().length < 5) { note.classList.add("invalid"); toast("Add a change note.", "err"); return false; }
        try { const res = await api.post("/rules/versions", { changes: { [rs.value]: ch }, new_version: ver.value.trim() || undefined, note: note.value.trim() }); toast(`Ruleset is now v${res.new_version}.`); await reload(); } catch (e) { toast(e.message, "err"); return false; } } }] });
  }
  function historyTab(c) {
    load(c, async () => api.get("/rules/versions"), (d) => h("section", { class: "card" }, h("div", { class: "table-wrap" }, h("table", { class: "dt" }, h("thead", null, h("tr", null, ["Version", "State", "Created by", "Created", "Changed rules", "Note"].map((x) => h("th", null, x)))),
      h("tbody", null, d.items.map((v) => h("tr", { "data-version": v.version }, h("td", { class: "mono strong" }, "v" + v.version), h("td", null, v.active ? badge("Active", "green", "check") : badge("Superseded", "")), h("td", null, v.created_by), h("td", { class: "nowrap" }, F.dateTime(v.created_at)), h("td", { class: "mono small" }, v.changed_rules.join(", ") || "—"), h("td", null, v.change_note))))))));
  }
  await reload();
  return root;
}
