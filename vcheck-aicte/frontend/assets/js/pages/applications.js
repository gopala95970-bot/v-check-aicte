import { h, icon, mount } from "../dom.js";
import { api, need } from "../api.js";
import { state } from "../state.js";
import { btn, card, empty, errorState, input, select, skelRows, pager, debounce } from "../ui.js";
import { applicationsTable } from "./_shared.js";
import { setQuery, query } from "../router.js";

export default async function applications({ user }) {
  const q = { page: 1, page_size: 10, ...query() };
  const st = (state.meta?.statuses || []).filter((s) => user.role === "applicant" || s.id !== "draft");
  const search = input({ type: "search", placeholder: "Search ID, reference, institution…", "aria-label": "Search applications", value: q.q || "" });
  const status = select([{ value: "", label: "All statuses" }, ...st.map((s) => ({ value: s.id, label: s.label }))], { "aria-label": "Status", value: q.status || "" });
  const sev = select([{ value: "", label: "Any severity" }, { value: "high", label: "High" }, { value: "medium", label: "Medium" }, { value: "low", label: "Low" }], { "aria-label": "Finding severity", value: q.severity || "" });
  const from = input({ type: "date", class: "input date", "aria-label": "From date", value: q.date_from || "" });
  const to = input({ type: "date", class: "input date", "aria-label": "To date", value: q.date_to || "" });
  const sort = select([{ value: "", label: "Newest first" }, { value: "oldest", label: "Oldest first" }, { value: "institution", label: "Institution A–Z" }], { "aria-label": "Sort", value: q.sort || "" });
  const results = h("div", null);
  const reset = btn("Reset", { size: "sm", kind: "ghost", onClick: () => { [search, from, to].forEach((e) => (e.value = "")); [status, sev, sort].forEach((e) => (e.value = "")); go(true); } });

  async function go(resetPage = true) {
    if (resetPage) q.page = 1;
    Object.assign(q, { q: search.value.trim(), status: status.value, severity: sev.value, date_from: from.value, date_to: to.value, sort: sort.value });
    setQuery({ ...q, page_size: "", page: q.page > 1 ? q.page : "" });
    mount(results, skelRows(6));
    try {
      const d = need(await api.get("/applications", { ...q }), ["items", "total"], "applications");
      const filtered = q.q || q.status || q.severity || q.date_from || q.date_to;
      mount(results, d.items.length ? [applicationsTable(d.items, { full: true }), pager(d, (p) => { q.page = p; go(false); }, "applications")]
        : empty({ icon: filtered ? "search" : "folder", title: filtered ? "No applications match these filters" : "No applications yet",
          text: filtered ? "Try removing a filter or searching for something else." : user.role === "applicant" ? "Create an application to get started." : "Applications appear here once an applicant submits them.",
          action: filtered ? btn("Clear filters", { onClick: () => reset.click() }) : user.role === "applicant" ? btn("Create New Application", { kind: "primary", icon: "plus", href: "/applications/new" }) : null }));
    } catch (e) { mount(results, errorState(e, () => go(false))); }
  }
  const deb = debounce(() => go(true), 300);
  search.addEventListener("input", deb);
  [status, sev, from, to, sort].forEach((e) => e.addEventListener("change", () => go(true)));
  go(false);
  return h("div", { class: "stack lg" },
    h("div", { class: "page-h" }, h("div", null, h("h1", null, "Applications"), h("p", null, user.role === "applicant" ? "Everything you have filed, with live validation status." : "All submitted applications. Drafts stay private to the applicant.")),
      user.role === "applicant" ? btn("Create New Application", { kind: "primary", icon: "plus", href: "/applications/new" }) : null),
    h("section", { class: "card" }, h("div", { class: "toolbar" }, h("div", { class: "search" }, icon("search"), search), status, sev, from, to, sort, reset), results));
}
