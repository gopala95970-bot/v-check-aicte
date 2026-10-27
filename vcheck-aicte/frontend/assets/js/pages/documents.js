import { h, icon, mount } from "../dom.js";
import { api, need } from "../api.js";
import { state } from "../state.js";
import { query, setQuery } from "../router.js";
import { btn, empty, errorState, input, select, skelRows, pager, debounce, docStatusBadge, badge } from "../ui.js";
import * as F from "../fmt.js";

export default async function documents({ user }) {
  const q = { page: 1, page_size: 15, ...query() };
  const search = input({ type: "search", placeholder: "Search file, application, institution…", "aria-label": "Search documents", value: q.q || "" });
  const status = select([{ value: "", label: "All statuses" }, ...["queued", "processing", "processed", "unreadable", "rejected"].map((s) => ({ value: s, label: F.titleCase(s) }))], { "aria-label": "Status", value: q.status || "" });
  const type = select([{ value: "", label: "All document types" }, ...state.meta.document_types.map((t) => ({ value: t.id, label: t.label }))], { "aria-label": "Type", value: q.type || "" });
  const results = h("div");
  async function go(reset = true) {
    if (reset) q.page = 1; Object.assign(q, { q: search.value.trim(), status: status.value, type: type.value });
    setQuery({ ...q, page_size: "", page: q.page > 1 ? q.page : "" }); mount(results, skelRows(7));
    try {
      const d = need(await api.get("/documents", q), ["items", "total"], "documents");
      mount(results, d.items.length ? [h("div", { class: "table-wrap" }, h("table", { class: "dt" }, h("thead", null, h("tr", null, ["Document", "Application", "Status", "Text source", "Pages", "Findings", "Uploaded", ""].map((t) => h("th", null, t)))),
        h("tbody", null, d.items.map((x) => h("tr", { "data-doc": x.id }, h("td", null, h("div", { class: "strong" }, x.type_label), h("div", { class: "small muted" }, x.filename + " · " + F.bytes(x.size))),
          h("td", null, h("a", { class: "id", href: "/applications/" + x.application_id }, x.application_id), h("div", { class: "small muted" }, x.institution_name)), h("td", null, docStatusBadge(x.status)),
          h("td", null, x.text_source ? (x.text_source === "ocr" ? `OCR (${F.pct(x.ocr_mean_conf)})` : "Text layer") : "—"), h("td", null, x.page_count || "—"),
          h("td", null, x.finding_count ? badge(String(x.finding_count), "amber", "warn") : h("span", { class: "muted" }, "0")), h("td", { class: "nowrap" }, F.date(x.uploaded_at)), h("td", { class: "right" }, btn("Open", { size: "sm", icon: "eye", href: "/documents/" + x.id }))))))), pager(d, (p) => { q.page = p; go(false); }, "documents")]
        : empty({ icon: "file", title: q.q || q.status || q.type ? "No documents match" : "No documents yet", text: q.q || q.status || q.type ? "Adjust the filters." : "Uploaded documents appear here with their processing status." }));
    } catch (e) { mount(results, errorState(e, () => go(false))); }
  }
  const deb = debounce(() => go(true), 300); search.addEventListener("input", deb); [status, type].forEach((e) => e.addEventListener("change", () => go(true)));
  go(false);
  return h("div", { class: "stack lg" }, h("div", { class: "page-h" }, h("div", null, h("h1", null, "Documents"), h("p", null, "Every uploaded document, its processing state and whether it has findings."))),
    h("section", { class: "card" }, h("div", { class: "toolbar" }, h("div", { class: "search" }, icon("search"), search), status, type), results));
}
