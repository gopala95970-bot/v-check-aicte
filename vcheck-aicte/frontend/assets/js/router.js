// History-API router with per-route role guards and cleanup hooks (so polling timers never leak between pages).
const routes = [];
let current = { cleanup: [] };
let renderFn = null;
let guard = () => true;

export const route = (path, page, opts = {}) => {
  const keys = [];
  const rx = new RegExp("^" + path.replace(/:(\w+)/g, (_, k) => (keys.push(k), "([^/]+)")) + "/?$");
  routes.push({ path, rx, keys, page, ...opts });
};
export function match(pathname) {
  for (const r of routes) {
    const m = r.rx.exec(pathname);
    if (m) return { route: r, params: Object.fromEntries(r.keys.map((k, i) => [k, decodeURIComponent(m[i + 1])])) };
  }
  return null;
}
export function navigate(url, { replace = false } = {}) {
  if (replace) history.replaceState({}, "", url); else history.pushState({}, "", url);
  return run();
}
export const currentPath = () => location.pathname;
export const query = () => Object.fromEntries(new URLSearchParams(location.search));
export function setQuery(params, { replace = true } = {}) {
  const u = new URLSearchParams(location.search);
  for (const [k, v] of Object.entries(params)) { if (v === "" || v == null) u.delete(k); else u.set(k, v); }
  const s = u.toString();
  history[replace ? "replaceState" : "pushState"]({}, "", location.pathname + (s ? "?" + s : ""));
}
export function onCleanup(fn) { current.cleanup.push(fn); }

export async function run() {
  current.cleanup.splice(0).forEach((fn) => { try { fn(); } catch { /* ignore */ } });
  const m = match(location.pathname);
  const token = {}; current = { cleanup: [], token };
  await renderFn(m, token);
}
export function start(render, g) {
  renderFn = render; guard = g || guard;
  addEventListener("popstate", run);
  document.addEventListener("click", (e) => {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey) return;
    const a = e.target.closest?.("a[href]");
    if (!a || a.target || a.hasAttribute("download") || a.dataset.external !== undefined) return;
    const u = new URL(a.href, location.href);
    if (u.origin !== location.origin || u.pathname.startsWith("/api/")) return;
    e.preventDefault();
    navigate(u.pathname + u.search);
  });
  return run();
}
export const isCurrent = (token) => current.token === token;
