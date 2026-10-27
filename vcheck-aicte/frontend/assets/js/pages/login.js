import { h, icon } from "../dom.js";
import { api, setToken, need } from "../api.js";
import { state } from "../state.js";
import { navigate, query } from "../router.js";
import { btn, busy, field, input, setFieldErrors, disclaimer } from "../ui.js";

const ACCOUNTS = [
  { role: "Applicant", email: "applicant@demo.vcheck", pw: "Applicant@Demo2026", note: "Files applications, uploads documents" },
  { role: "Reviewer", email: "reviewer@demo.vcheck", pw: "Reviewer@Demo2026", note: "Triages findings, records demonstration decisions" },
  { role: "Administrator", email: "admin@demo.vcheck", pw: "Admin@Demo2026", note: "Rules, settings, audit" },
];

export default async function login() {
  const email = input({ type: "email", name: "email", autocomplete: "username", placeholder: "you@example.org", required: true });
  const pw = input({ type: "password", name: "password", autocomplete: "current-password", placeholder: "Password", required: true });
  const err = h("div", { class: "banner err hide", role: "alert" }, icon("alert"), h("div", { id: "login-err" }));
  const submit = btn("Sign in", { kind: "primary lg", type: "submit", icon: "lock" });
  const form = h("form", { class: "stack", novalidate: true, onSubmit: async (e) => {
    e.preventDefault(); err.classList.add("hide");
    if (!email.value.trim() || !pw.value) { err.querySelector("#login-err").textContent = "Enter your email and password."; err.classList.remove("hide"); return; }
    await busy(submit, async () => {
      try {
        const r = need(await api.login(email.value.trim(), pw.value), ["token", "user"], "login");
        setToken(r.token); state.user = null;
        await navigate(safeNext(query().next) || "/dashboard", { replace: true });
      } catch (ex) {
        err.querySelector("#login-err").textContent = ex.code === "too_many_attempts" ? ex.message : ex.status === 401 ? "Incorrect email or password." : ex.message;
        err.classList.remove("hide"); pw.value = ""; pw.focus();
      }
    });
  } },
    field("Email", email), field("Password", pw), err, submit);
  return h("div", { class: "login" },
    h("section", { class: "login-art" },
      h("a", { href: "/", class: "row", style: { color: "#fff", textDecoration: "none", gap: "10px" } }, h("span", { class: "brand-mark" }, icon("shield", "lg")), h("b", { style: { fontSize: "16px" } }, "V-CHECK AICTE")),
      h("div", { class: "stack lg" }, h("h2", null, "Evidence-driven validation for every application."),
        h("p", null, "Every finding points to the exact rule and the exact line in the document. Humans decide; V-Check shows the evidence."),
        h("div", { class: "stack sm", style: { color: "#b8c9e6" } }, ["Rules are deterministic and version-controlled", "Reviewer actions are confirmed and audited", "Demonstration data only: nothing here is an official decision"].map((t) => h("div", { class: "row" }, icon("check"), t)))),
      h("p", { class: "small", style: { color: "#8ba0c2", margin: 0 } }, disclaimer())),
    h("section", { class: "login-form" }, h("div", { class: "box stack lg" },
      h("div", null, h("h1", { style: { fontSize: "26px" } }, "Sign in"), h("p", { class: "muted", style: { margin: "6px 0 0" } }, "Launch the Verification Console")),
      form,
      h("div", { class: "stack sm" }, h("div", { class: "f-label" }, "Demo accounts (synthetic data) — click to fill"),
        ACCOUNTS.map((a) => h("button", { type: "button", class: "demo-acct", "data-demo": a.role.toLowerCase(), onClick: () => { email.value = a.email; pw.value = a.pw; pw.focus(); } },
          h("span", null, h("span", { class: "strong" }, a.role), h("span", { class: "small muted", style: { display: "block" } }, a.note)), h("span", { class: "small mono muted" }, a.email)))),
      h("a", { href: "/", class: "small" }, "← Back to product overview"))));
}
const safeNext = (n) => (n && n.startsWith("/") && !n.startsWith("//") && !n.startsWith("/login") ? n : null);
