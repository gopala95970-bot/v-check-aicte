import { h, icon, mount } from "../dom.js";
import { api, need } from "../api.js";
import { query, setQuery } from "../router.js";
import { btn, empty, errorState, input, select, skelRows, pager, debounce, badge, roleBadge } from "../ui.js";
import * as F from "../fmt.js";

export default async function audit() {
  const q = { page: 1, page_size: 25, ...query() };
  let facets = { actions: [], roles: [] }; try { facets = await api.get("/audit/facets"); } catch { /* optional */ }
  const search = input({ type: "search", placeholder: "Search description or object…", "aria-label": "Search audit", value: q.q || "" });
  const user = input({ placeholder: "User email", "aria-label": "User", value: q.user || "", style: { width: "170px" } });
  const role = select([{ value: "", label: "All roles" }, ...facets.roles.map((x) => ({ value: x, label: F.titleCase(x) }))], { "aria-label": "Role", value: q.role || "" });
  const action = select([{ value: "", label: "All actions" }, ...facets.actions.map((x) => ({ value: x, label: x }))], { "aria-label": "Action", value: q.action || "" });
  const result = select([{ value: "", label: "Any result" }, { value: "success", label: "Success" }, { value: "failure", label: "Failure" }, { value: "error", label: "Error" }], { "aria-label": "Result", value: q.result || "" });
  const appId = input({ placeholder: "APP-001", "aria-label": "Application", value: q.application_id || "", style: { width: "110px" } });
  const from = input({ type: "date", class: "input date", "aria-label": "From", value: q.date_from || "" }), to = input({ type: "date", class: "input date", "aria-label": "To", value: q.date_to || "" });
  const results = h("div");
  async function go(reset = true) {
    if (reset) q.page = 1; Object.assign(q, { q: search.value.trim(), user: user.value.trim(), role: role.value, action: action.value, result: result.value, application_id: appId.value.trim().toUpperCase(), date_from: from.value, date_to: to.value });
    setQuery({ ...q, page_size: "", page: q.page > 1 ? q.page : "" }); mount(results, skelRows(8));
    try {
      const d = need(await api.get("/audit", q), ["items", "total"], "audit");
      mount(results, d.items.length ? [h("div", { class: "table-wrap" }, h("table", { class: "dt", "data-audit": "" }, h("thead", null, h("tr", null, ["Timestamp", "User", "Role", "Action", "Object", "Application", "Result"].map((t) => h("th", null, t)))),
        h("tbody", null, d.items.map((e) => { const det = h("tr", { class: "hide" }, h("td", { colspan: 7, style: { background: "var(--surface-2)" } }, h("div", { class: "stack sm" }, h("div", null, e.description), e.from_status || e.to_status ? h("div", { class: "small muted" }, `Status: ${e.from_status || "—"} → ${e.to_status || "—"}`) : null, Object.keys(e.details || {}).length ? h("pre", { class: "mono small", style: { margin: 0, whiteSpace: "pre-wrap" } }, JSON.stringify(e.details, null, 2)) : null)));
          const row = h("tr", { class: "clickable", "data-audit-row": e.action, onClick: () => det.classList.toggle("hide") }, h("td", { class: "nowrap mono small" }, F.dateTime(e.timestamp)), h("td", null, h("div", null, e.user_name), h("div", { class: "small muted" }, e.user)), h("td", null, e.role === "system" ? badge("System", "") : roleBadge(e.role === "anonymous" ? "applicant" : e.role)),
            h("td", { class: "mono small" }, e.action), h("td", null, h("div", { class: "small" }, F.titleCase(e.object_type)), h("div", { class: "small muted mono", style: { maxWidth: "190px", overflow: "hidden", textOverflow: "ellipsis" } }, e.object_id)), h("td", null, e.application_id ? h("a", { class: "id", href: "/applications/" + e.application_id, onClick: (ev) => ev.stopPropagation() }, e.application_id) : "—"),
            h("td", null, e.result === "success" ? badge("Success", "green", "check") : badge(F.titleCase(e.result), "red", "x"))); return [row, det]; })))), pager(d, (p) => { q.page = p; go(false); }, "events")]
        : empty({ icon: "history", title: "No audit events match", text: "Adjust or clear the filters." }));
    } catch (e) { mount(results, errorState(e, () => go(false))); }
  }
  const clear = btn("Clear", { size: "sm", kind: "ghost", onClick: () => { [search, user, appId, from, to].forEach((e) => (e.value = "")); [role, action, result].forEach((e) => (e.value = "")); go(true); } });
  search.addEventListener("input", debounce(() => go(true), 300)); user.addEventListener("input", debounce(() => go(true), 300)); appId.addEventListener("input", debounce(() => go(true), 300));
  [role, action, result, from, to].forEach((e) => e.addEventListener("change", () => go(true)));
  go(false);
  return h("div", { class: "stack lg" }, h("div", { class: "page-h" }, h("div", null, h("h1", null, "Audit Trail"), h("p", null, "Append-only record of who did what, when, to which object, with what result. Blocked actions are included. Click a row for details."))),
    h("section", { class: "card" }, h("div", { class: "toolbar" }, h("div", { class: "search" }, icon("search"), search), user, role, action, result, appId, from, to, clear), results));
}
