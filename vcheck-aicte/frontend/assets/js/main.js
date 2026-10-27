import { h, icon, mount, clear } from "./dom.js";
import { api, setToken, token, setUnauthorizedHandler, need } from "./api.js";
import { state } from "./state.js";
import { start, route, navigate, onCleanup, isCurrent, query } from "./router.js";
import { toast, roleBadge, empty, btn, disclaimer, errorState } from "./ui.js";
import * as F from "./fmt.js";

const NAV = [
  { label: "Workspace", items: [
    { path: "/dashboard", text: "Dashboard", ic: "dashboard" },
    { path: "/applications", text: "Applications", ic: "folder" },
    { path: "/documents", text: "Documents", ic: "file" },
    { path: "/verification", text: "Verification", ic: "shield" } ] },
  { label: "Compliance", staff: true, items: [
    { path: "/review", text: "Review Queue", ic: "clipboard", counter: true },
    { path: "/rules", text: "Rules", ic: "book" },
    { path: "/analytics", text: "Analytics", ic: "chart" },
    { path: "/audit", text: "Audit Trail", ic: "history" } ] },
  { label: "System", items: [{ path: "/settings", text: "Settings", ic: "settings" }] },
];
const lazy = (file, fn = "default") => async (ctx) => (await import(file))[fn](ctx);
const STAFF = ["reviewer", "admin"];

route("/", lazy("./pages/landing.js"), { public: true, bare: true, title: "V-Check AICTE" });
route("/login", lazy("./pages/login.js"), { public: true, bare: true, title: "Sign in" });
route("/dashboard", lazy("./pages/dashboard.js"), { title: "Dashboard" });
route("/applications", lazy("./pages/applications.js"), { title: "Applications" });
route("/applications/new", lazy("./pages/wizard.js"), { title: "New application", roles: ["applicant"] });
route("/applications/:id", lazy("./pages/appdetail.js"), { title: "Application", nav: "/applications" });
route("/documents", lazy("./pages/documents.js"), { title: "Documents" });
route("/documents/:id", lazy("./pages/docviewer.js"), { title: "Document viewer", nav: "/documents" });
route("/verification", lazy("./pages/verification.js"), { title: "Verification Center" });
route("/review", lazy("./pages/review.js"), { title: "Reviewer workspace", roles: STAFF, nav: "/review" });
route("/rules", lazy("./pages/rules.js"), { title: "Rules", roles: STAFF });
route("/analytics", lazy("./pages/analytics.js"), { title: "Analytics", roles: STAFF });
route("/audit", lazy("./pages/audit.js"), { title: "Audit Trail", roles: STAFF });
route("/settings", lazy("./pages/settings.js"), { title: "Settings" });

setUnauthorizedHandler(() => {
  if (!state.user) return;
  setToken(null); state.user = null; teardownShell();
  toast("Your session has ended. Please sign in again.", "err");
  navigate("/login?next=" + encodeURIComponent(location.pathname + location.search), { replace: true });
});

// ------------------------------------------------------------------ shell
let shell = null, notifTimer = null;
function teardownShell() { shell = null; clearInterval(notifTimer); notifTimer = null; }

function ensureShell() {
  if (shell) return shell;
  const u = state.user;
  const content = h("main", { class: "content", id: "main", tabindex: "-1" });
  const title = h("h1", null, "");
  const side = h("aside", { class: "sidebar", id: "sidebar", "aria-label": "Primary" });
  const nav = h("nav", { class: "nav" });
  const links = {};
  NAV.filter((g) => !g.staff || STAFF.includes(u.role)).forEach((g) => {
    nav.append(h("div", { class: "nav-label" }, g.label));
    g.items.forEach((it) => {
      const count = it.counter ? h("span", { class: "count hide", id: "queue-count" }) : null;
      const a = h("a", { href: it.path, onClick: () => side.classList.remove("open") }, icon(it.ic), it.text, count);
      links[it.path] = a; nav.append(a);
    });
  });
  side.append(h("a", { class: "brand", href: "/dashboard" }, h("span", { class: "brand-mark" }, icon("shield", "lg")), h("span", null, h("b", null, "V-CHECK AICTE"), h("span", null, "Verification console"))),
    nav, h("div", { class: "side-foot" }, h("strong", { style: { color: "#d7e2f5" } }, "Demonstration prototype"), h("div", null, "Synthetic data only. Not an official AICTE portal.")));
  const bell = notificationBell();
  const menu = userMenu();
  const top = h("header", { class: "topbar" },
    h("button", { class: "iconbtn menu-btn", "aria-label": "Open navigation", onClick: () => side.classList.toggle("open") }, icon("menu")),
    title, h("div", { class: "grow" }), roleBadge(u.role), bell.el, menu);
  const root = document.getElementById("app");
  mount(root, h("div", { class: "demo-bar" }, h("strong", null, "DEMO MODE"), " · Independent demonstration prototype — not an official AICTE portal · synthetic data"),
    h("div", { class: "shell", "data-shell": "1" }, side, h("div", { class: "main-col" }, top, content)));
  shell = { content, title, links, bell };
  refreshQueueCount();
  notifTimer = setInterval(() => { bell.refresh(); refreshQueueCount(); }, 20000);
  return shell;
}

async function refreshQueueCount() {
  if (!STAFF.includes(state.user?.role)) return;
  try {
    const r = await api.get("/review/queue", { scope: "open" });
    const el = document.getElementById("queue-count");
    if (el) { el.textContent = r.total; el.classList.toggle("hide", !r.total); }
  } catch { /* non-critical */ }
}

function userMenu() {
  const u = state.user;
  const wrap = h("div", { style: { position: "relative" } });
  const pop = h("div", { class: "menu hide", style: { width: "240px" } },
    h("div", { class: "mh" }, h("div", null, h("div", { class: "strong" }, u.name), h("div", { class: "small muted" }, u.email))),
    h("a", { class: "mi", href: "/settings", style: { display: "block", textDecoration: "none" } }, "Settings"),
    h("button", { class: "mi", onClick: signOut }, "Sign out"));
  const chip = h("button", { class: "userchip", "aria-haspopup": "true", "aria-label": "Account menu", onClick: (e) => { e.stopPropagation(); pop.classList.toggle("hide"); } },
    h("span", { class: "avatar" }, F.initials(u.name)), h("span", { class: "small strong nowrap" }, u.name.split(" ")[0]), icon("down"));
  document.addEventListener("click", () => pop.classList.add("hide"));
  wrap.append(chip, pop);
  return wrap;
}

function notificationBell() {
  const wrap = h("div", { style: { position: "relative" } });
  const pip = h("span", { class: "pip hide" });
  const pop = h("div", { class: "menu hide" });
  const btnEl = h("button", { class: "iconbtn", "aria-label": "Notifications", "aria-haspopup": "true", onClick: (e) => { e.stopPropagation(); pop.classList.toggle("hide"); draw(); } }, icon("bell", "lg"), pip);
  let data = { items: [], unread: 0 };
  const draw = () => {
    mount(pop, h("div", { class: "mh" }, h("b", null, "Alerts"), btn("Mark all read", { size: "sm", kind: "ghost", onClick: async (e) => { e.stopPropagation(); data = await api.post("/notifications/read", {}); draw(); } })),
      data.items.length ? data.items.slice(0, 8).map((n) => h("button", { class: "mi" + (n.read ? "" : " unread"), onClick: async () => {
        pop.classList.add("hide"); if (!n.read) { data = await api.post("/notifications/read", { id: n.id }); draw(); }
        if (n.application_id) navigate("/applications/" + n.application_id); } },
        h("div", { class: "strong small" }, n.title), n.body ? h("div", { class: "small muted" }, n.body.slice(0, 90)) : null, h("div", { class: "small muted" }, F.ago(n.created_at))))
        : h("div", { class: "empty", style: { padding: "22px" } }, h("b", null, "No alerts yet"), h("p", { class: "small" }, "Processing results and review updates appear here.")));
    pip.textContent = data.unread; pip.classList.toggle("hide", !data.unread);
  };
  const refresh = async () => { try { data = await api.get("/notifications"); draw(); } catch { /* ignore */ } };
  document.addEventListener("click", () => pop.classList.add("hide"));
  pop.addEventListener("click", (e) => e.stopPropagation());
  wrap.append(btnEl, pop); refresh();
  return { el: wrap, refresh };
}

export async function signOut() {
  try { await api.post("/auth/logout"); } catch { /* token may already be invalid */ }
  setToken(null); state.user = null; teardownShell();
  navigate("/login", { replace: true }); toast("You have been signed out.");
}

// ------------------------------------------------------------------ rendering
async function render(m, tok) {
  const root = document.getElementById("app");
  if (!m) { teardownShell(); return mount(root, h("div", { style: { padding: "64px 20px" } }, empty({ icon: "search", title: "Page not found", text: "That address does not exist in this console.", action: btn("Go to the start", { kind: "primary", href: "/" }) }))); }
  const { route: r, params } = m;
  if (!state.meta) { try { state.meta = await api.meta(); } catch { /* landing still renders */ } }
  if (token() && !state.user) {
    try { state.user = need(await api.get("/auth/me"), ["role", "permissions"], "profile"); } catch { setToken(null); }
  }
  if (!r.public && !state.user) return navigate("/login?next=" + encodeURIComponent(location.pathname + location.search), { replace: true });
  if (r.public && r.path === "/login" && state.user) return navigate("/dashboard", { replace: true });
  document.title = (r.title ? r.title + " · " : "") + "V-Check AICTE";
  if (r.bare) { teardownShell(); const ctx = { params, query: query(), user: state.user, onCleanup }; const node = await r.page(ctx); if (isCurrent(tok)) { mount(root, node); window.scrollTo(0, 0); } return; }
  const sh = ensureShell();
  const nav = r.nav || r.path;
  Object.entries(sh.links).forEach(([p, a]) => (nav === p || (p !== "/dashboard" && nav.startsWith(p + "/")) ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current")));
  sh.title.textContent = r.title;
  if (r.roles && !r.roles.includes(state.user.role)) {
    return mount(sh.content, empty({ icon: "lock", title: "Access restricted", text: `The ${F.titleCase(state.user.role)} role cannot open this page. The server enforces this independently of the interface.`, action: btn("Back to dashboard", { kind: "primary", href: "/dashboard" }) }));
  }
  mount(sh.content, h("div", { class: "stack" }, h("span", { class: "skel h-lg", style: { width: "30%" } }), h("span", { class: "skel block" })));
  try {
    const node = await r.page({ params, query: query(), user: state.user, onCleanup, token: tok });
    if (!isCurrent(tok)) return;
    mount(sh.content, node); sh.content.style.animation = "none"; void sh.content.offsetWidth; sh.content.style.animation = "";
    window.scrollTo(0, 0);
  } catch (e) {
    if (!isCurrent(tok) || e.status === 401) return;
    mount(sh.content, errorState(e, () => navigate(location.pathname + location.search)));
  }
}

start(render);
window.addEventListener("unhandledrejection", (e) => { if (e.reason?.status === 401) return; console.error(e.reason); });
