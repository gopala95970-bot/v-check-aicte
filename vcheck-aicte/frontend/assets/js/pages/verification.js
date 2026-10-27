import { h, icon, mount } from "../dom.js";
import { api, need } from "../api.js";
import { state, isStaff } from "../state.js";
import { query, setQuery, onCleanup } from "../router.js";
import { btn, card, empty, errorState, input, select, skelRows, pager, debounce, tabs, appStatusBadge, validationBadge, badge, simBadge, load } from "../ui.js";
import { pipelineView, findingCard } from "./_shared.js";
import * as F from "../fmt.js";

const MODE = { off: ["warn", "Source verification is switched off. No external or simulated source is consulted, and nothing is reported as verified."],
  simulation: ["", "Simulation mode: certificates are looked up in a local SYNTHETIC registry. This is not a government verification."], unavailable: ["warn", "Simulated outage: the verification source is treated as unreachable, so checks go to human review."] };

export default async function verification({ user }) {
  let tab = query().tab || "pipeline", timer = null;
  onCleanup(() => clearInterval(timer));
  const body = h("div");
  const mode = state.meta.verification_mode || "off";
  const root = h("div", { class: "stack lg" }, h("div", { class: "page-h" }, h("div", null, h("h1", null, "Verification Center"), h("p", null, "The ten-stage pipeline for every application, with measured timings and the evidence behind each result."))),
    h("div", { class: "banner " + MODE[mode][0], "data-verification-mode": mode }, icon("info"), h("div", null, simBadge(), " ", MODE[mode][1])), h("div", { id: "vtabs" }), body);
  const drawTabs = () => mount(root.querySelector("#vtabs"), tabs([{ id: "pipeline", label: "Pipeline" }, { id: "findings", label: "All findings" }], tab, (t) => { tab = t; setQuery({ tab: t }); clearInterval(timer); drawTabs(); draw(); }));
  function draw() { mount(body, tab === "pipeline" ? pipelineTab() : findingsTab()); }

  function pipelineTab() {
    const side = h("div", { class: "pane", style: { maxHeight: "70vh" } }), main = h("div", { "data-pipeline-view": "" });
    let sel = query().app;
    async function select_(id) {
      sel = id; setQuery({ app: id }); clearInterval(timer);
      const paint = async () => {          // returns true while the pipeline is still busy
        try {
          const p = need(await api.get(`/applications/${id}/pipeline`), ["stages"], "pipeline");
          mount(main, card(`Pipeline · ${id}`, pipelineView(p, {}), { actions: h("a", { class: "btn sm", href: "/applications/" + id }, "Open application") }));
          return p.processing || p.documents.some((d) => ["queued", "processing"].includes(d.status));
        } catch (e) { mount(main, errorState(e, () => select_(id))); return false; }
      };
      side.querySelectorAll(".qitem").forEach((b) => b.setAttribute("aria-current", String(b.dataset.id === id)));
      mount(main, skelRows(8));
      if (await paint()) timer = setInterval(async () => { if (!(await paint())) clearInterval(timer); }, 1000);
    }
    load(side, async () => need(await api.get("/applications", { page_size: 100, sort: "oldest" }), ["items"], "applications"), (d) => {
      if (!d.items.length) return empty({ icon: "folder", title: "No applications", text: "Submit an application to see its pipeline." });
      if (!sel) sel = d.items[0].id; queueMicrotask(() => select_(sel));
      return h("div", null, h("div", { class: "ph" }, h("b", null, "Applications")), h("div", { class: "pb" }, d.items.map((a) => h("button", { class: "qitem", "data-id": a.id, "aria-current": String(a.id === sel), onClick: () => select_(a.id) },
        h("div", { class: "row between" }, h("span", { class: "mono strong" }, a.id), validationBadge(a.validation)), h("div", { class: "small", style: { marginTop: "2px" } }, a.institution.name), h("div", { class: "small muted" }, a.status_label)))));
    });
    return h("div", { class: "grid", style: { gridTemplateColumns: "300px minmax(0,1fr)", alignItems: "start" } }, side, main);
  }

  function findingsTab() {
    const q = { page: 1, page_size: 10 };
    const search = input({ type: "search", placeholder: "Search findings, rules…", "aria-label": "Search findings" });
    const sev = select([{ value: "", label: "Any severity" }, "high", "medium", "low"].map((x) => (x.value !== undefined ? x : { value: x, label: F.titleCase(x) })), { "aria-label": "Severity" });
    const st = select([{ value: "", label: "Any status" }, ...["open", "under_review", "resolved", "accepted_with_explanation"].map((x) => ({ value: x, label: F.titleCase(x) }))], { "aria-label": "Finding status" });
    const out = select([{ value: "", label: "Any outcome" }, { value: "failed", label: "Failed" }, { value: "review_required", label: "Review required" }], { "aria-label": "Outcome" });
    const res = h("div", { style: { padding: "14px" } });
    async function go(reset = true) {
      if (reset) q.page = 1; Object.assign(q, { q: search.value.trim(), severity: sev.value, status: st.value, outcome: out.value }); mount(res, skelRows(5));
      try { const d = need(await api.get("/findings", q), ["items", "total"], "findings");
        mount(res, d.items.length ? [h("div", { class: "stack" }, d.items.map((f) => findingCard(f, { showApp: true }))), pager(d, (p) => { q.page = p; go(false); }, "findings")] : empty({ icon: "checkc", title: "No findings match", text: "Nothing needs attention with these filters." })); }
      catch (e) { mount(res, errorState(e, () => go(false))); } }
    search.addEventListener("input", debounce(() => go(true), 300)); [sev, st, out].forEach((e) => e.addEventListener("change", () => go(true))); go(false);
    return h("section", { class: "card" }, h("div", { class: "toolbar" }, h("div", { class: "search" }, icon("search"), search), sev, st, out), res);
  }
  drawTabs(); draw();
  return root;
}
