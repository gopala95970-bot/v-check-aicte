# Frontend notes

The web UI lives in `frontend/` and is **served by the API itself** (`python -m vcheck_api`, then open `http://127.0.0.1:8000`). There is no build step and no `npm`.

## Why it is not React/Vite/Tailwind

The original brief asked for React + TypeScript + Vite + Tailwind. The build environment for this project had no package registry access, so
those tools could not be installed, and untested framework code was not an acceptable deliverable for a live demo. The UI is therefore plain ES modules
(about 2,000 dense lines of JavaScript plus a 240-line stylesheet), written to be easy to port, and it is covered by 31 real-browser tests.

Trade-offs, stated honestly: no static typing (runtime response checks via `need()` in `api.js` instead), no component library, a hand-written SVG chart module
instead of Recharts, and a hand-written router instead of React Router. In return: it starts instantly, has zero dependencies to break on a demo laptop, and has a strict
Content-Security-Policy (`script-src 'self'; style-src 'self'`) that a typical Vite/Tailwind dev setup would not.

## Layout

```
frontend/index.html            single HTML shell (CSP-friendly: no inline script or style)
frontend/assets/styles.css     design system: navy/blue palette, semantic status colours (always icon + text), responsive rules
frontend/assets/js/
  dom.js     h() element builder (text only, never HTML), icon set, svg()      <- XSS safety by construction
  api.js     fetch client: bearer auth, errors, one GET retry, XHR upload progress, need() response checks
  ui.js      toasts, badges, modals, drawers, remarks/confirm dialogs, pager, skeletons, empty/error states
  charts.js  dependency-free SVG bar / donut / horizontal-bar charts      router.js  history-API router with cleanup hooks
  main.js    shell, role-aware navigation, notifications bell, route table, session expiry handling
  pages/     landing, login, dashboard, applications, wizard, appdetail, documents, docviewer, verification, review, rules, analytics, audit, settings
```

## Rules the code follows

* Data is only ever inserted with `textContent`/properties. There is no `innerHTML` with API data (a hostile institution name is tested to render inert).
* Every number comes from an endpoint. Empty states are shown instead of invented values.
* Anything simulated carries a "Simulation" badge; demonstration decisions are always labelled "(demonstration only)".
* Pollers (`setInterval`) are registered with `onCleanup` so they stop when you leave a page.
* The server is the authority for permissions; the UI only hides what the server would refuse anyway (both are tested).

## Porting to React later (optional)

`docs/API.md` is the contract. Each file in `pages/` maps to one route and one set of endpoints, so a port can go page by page. Keep the behaviours
asserted in `backend/tests_ui/test_ui.py`, which run against any front end served from the same origin.
