import { h, icon } from "../dom.js";
import { btn, badge, disclaimer, severityBadge, outcomeBadge, findingStatusBadge } from "../ui.js";
import { state } from "../state.js";

const STAGES = [
  ["Document received", "Safe name, SHA-256, size and type limits"], ["File integrity", "Content sniffing, structure, active-content flags"],
  ["OCR / text read", "Embedded text first; Tesseract for scans"], ["Classification", "Is it the document type it claims to be?"],
  ["Field extraction", "Values with page, line and confidence"], ["Cross-document validation", "Names, IDs, dates, intakes must agree"],
  ["Duplicate detection", "Reused files, cloned text, reused numbers"], ["Compliance rules", "Versioned, deterministic, source-labelled"],
  ["Source verification", "Simulated here, always labelled"], ["Human review", "A reviewer decides, with the evidence"],
];
const FEATS = [
  ["filesearch", "Evidence-linked findings", "Each finding shows the rule, the application value, the document value, the page and line, and what to do next."],
  ["compare", "Cross-document consistency", "Institution name, identifier, validity dates and approved intake are compared across every document in the file."],
  ["book", "Versioned rules, not guesswork", "Compliance checks are data with a version history. An AI model never changes a rule or decides an outcome."],
  ["copy", "Duplicate and reuse signals", "Identical files, near-identical text and reused certificate numbers are surfaced as review prompts, never as proof."],
  ["clipboard", "Reviewer workspace", "Queue, evidence and findings side by side, with confirmed actions and a reason recorded for every decision."],
  ["history", "Complete audit trail", "Who did what, when, to which object, with what result. Blocked actions are recorded too."],
];

export default async function landing() {
  const loggedIn = !!state.user;
  const cta = (size = "lg") => btn("Launch Verification Console", { kind: "primary " + size, icon: "arrow", href: loggedIn ? "/dashboard" : "/login" });
  return h("div", { class: "land" },
    h("header", { class: "land-nav" }, h("div", { class: "container" },
      h("a", { href: "/", class: "row", style: { textDecoration: "none", color: "var(--navy-900)" } }, h("span", { class: "brand-mark", style: { background: "var(--navy-900)", color: "#8fbaf7" } }, icon("shield", "lg")), h("b", { style: { fontSize: "16px" } }, "V-CHECK AICTE")),
      h("nav", null, [["problem", "Problem"], ["how", "How it works"], ["capabilities", "Capabilities"], ["security", "Security"], ["reviewers", "Reviewers"]].map(([id, t]) => h("a", { href: "#" + id, dataExternal: "", "data-external": "", onClick: (e) => { e.preventDefault(); document.getElementById(id)?.scrollIntoView({ behavior: "smooth" }); } }, t))),
      btn(loggedIn ? "Open console" : "Sign in", { href: loggedIn ? "/dashboard" : "/login" }))),
    h("section", { class: "hero" }, h("div", { class: "container" },
      h("div", null, h("div", { class: "eyebrow" }, icon("target"), "Smart India Hackathon · SIH26261"),
        h("h1", null, "Don't just store institutional documents. Validate them."),
        h("p", { class: "lead" }, "V-Check turns approval applications into an evidence-driven pipeline: read every document, compare them against each other and against versioned rules, and hand the reviewer findings they can verify in seconds."),
        h("div", { class: "row wrap" }, cta(), h("a", { class: "btn lg ghost", href: "#how", onClick: (e) => { e.preventDefault(); document.getElementById("how").scrollIntoView({ behavior: "smooth" }); } }, "See how it works")),
        h("p", { class: "small", style: { color: "#8ba0c2", marginTop: "18px" } }, "Independent demonstration prototype — not an official AICTE portal. Synthetic data only.")),
      h("div", { class: "preview-card", "aria-label": "Illustrative example of a finding" },
        h("div", { class: "row between", style: { marginBottom: "10px" } }, badge("Illustrative example", "outline", "info"), h("span", { class: "small muted mono" }, "XD-002")),
        h("div", { class: "row", style: { marginBottom: "8px" } }, severityBadge("high", true), outcomeBadge("failed"), findingStatusBadge("open")),
        h("h3", { style: { marginBottom: "10px" } }, "Institution identifier matches the application"),
        h("div", { class: "evidence" }, "Application   ", h("span", { class: "good" }, "1-9000000808"), "\nDocument      ", h("span", { class: "bad" }, "1-9000000999"), "\nSource        affiliation_letter.pdf · page 1 · line 5\n              \u201CAICTE Permanent Id: 1-9000000999\u201D"),
        h("div", { class: "rec", style: { marginTop: "10px", fontSize: "13px" } }, h("b", null, "Recommended action: "), "Confirm the identifier, or upload the correct document.")))),
    section("problem", "alt", "Approval review is mostly manual cross-checking", "Reviewers read stacks of PDFs and scans, then compare names, identifiers, dates and intake figures by eye. Mistakes and reused documents are easy to miss, and the reasoning behind a decision is rarely recorded.",
      h("div", { class: "grid g3" }, [["file", "Documents are stored, not understood", "A portal that only collects files leaves every consistency check to a person."], ["compare", "Inconsistencies hide across documents", "A name that differs by one word, or an ID that differs by one digit, only shows up when two documents are read side by side."], ["history", "Decisions leave a thin trail", "Without the evidence and the rule behind each finding, review is hard to repeat, explain or audit."]].map(([i, t, d]) => feat(i, t, d)))),
    section("how", "", "How V-Check works", "Ten stages from upload to a human decision. Each one reports its status, its measured time and its evidence in the Verification Center.",
      h("div", { class: "flow" }, STAGES.map(([t, d], i) => h("div", { class: "st" }, h("span", { class: "n" }, String(i + 1).padStart(2, "0")), h("b", null, t), h("span", { class: "muted" }, d))))),
    section("capabilities", "alt", "Core capabilities", "Built to assist reviewers, never to replace them.", h("div", { class: "grid g3" }, FEATS.map(([i, t, d]) => feat(i, t, d)))),
    section("workflow", "", "A validation workflow with clear states", "Statuses always carry a label and an icon, never colour alone.",
      h("div", { class: "row wrap", style: { gap: "10px" } }, [["Draft", ""], ["Submitted", "blue"], ["Processing", "blue"], ["Review required", "amber"], ["Validation complete", "green"], ["Corrections requested", "amber"], ["Approved (demonstration only)", "green"], ["Rejected (demonstration only)", "red"]].map(([t, v]) => badge(t, v + " outline", v === "green" ? "check" : v === "red" ? "x" : v === "amber" ? "warn" : v === "blue" ? "clock" : "pencil"))),
      h("p", { class: "muted", style: { marginTop: "16px" } }, "\u201CApproved\u201D and \u201Crejected\u201D are demonstration outcomes. This prototype issues no government approval and performs no official verification.")),
    section("security", "alt", "Security basics, implemented and tested", "Not a checklist of promises. Each item below has an automated test.",
      h("div", { class: "grid g3" }, [["lock", "Authentication", "Passwords hashed with scrypt, expiring and revocable session tokens, login throttling."], ["users", "Role-based access", "Applicant, reviewer and administrator permissions enforced on the server for every route."], ["file", "Safe uploads", "Content sniffing, size and page limits, generated storage names, path-traversal protection. Files are never publicly addressable."], ["history", "Audit logging", "Append-only record of actions, outcomes and blocked attempts, with secrets redacted."], ["shield", "Honest labelling", "Simulated verification is always marked as simulation and never reported as verified."], ["db", "No hidden data", "Every number in the console is computed from the database. No placeholder statistics."]].map(([i, t, d]) => feat(i, t, d)))),
    section("reviewers", "", "The reviewer workflow", "Queue on the left, document evidence in the middle, findings on the right. Important actions need confirmation and a reason.",
      h("div", { class: "grid g4" }, [["usercheck", "Assign", "Claim a case or assign a reviewer."], ["flag", "Triage", "Mark findings under review, resolved, or accepted with an explanation."], ["message", "Request correction", "Send precise corrections back to the applicant."], ["checkc", "Demonstration decision", "Record an approval or rejection, clearly labelled as a demonstration."]].map(([i, t, d]) => feat(i, t, d)))),
    section("impact", "alt", "What changes for a reviewer", "Instead of hunting for discrepancies, reviewers start from them.",
      h("div", { class: "grid g3" }, [["Seconds, not minutes, to the evidence", "Findings link to the page and line that caused them."], ["Consistent rules", "The same version of the same rule applies to every application, and changes are recorded."], ["Explainable outcomes", "Every decision has the findings, the notes and the audit trail behind it."]].map(([t, d]) => h("div", { class: "feat" }, h("h3", null, t), h("p", null, d)))),
      h("p", { class: "muted small", style: { marginTop: "14px" } }, "No performance claims are made here: this is a prototype evaluated on synthetic documents only. See the repository's testing report for what was and was not measured.")),
    h("section", { class: "cta" }, h("h2", null, "See the pipeline on real demonstration data"), h("p", null, "Six synthetic applications are ready: clean, missing document, inconsistent, expired, duplicate evidence and verification unavailable."), cta()),
    h("footer", { class: "footer" }, h("div", { class: "container stack" },
      h("div", null, h("strong", null, "V-CHECK AICTE"), " · AI-Powered Application Validation, Document Authentication & Regulatory Compliance Assistant"),
      h("div", null, disclaimer()),
      h("div", null, "Existing government systems are acknowledged and are not replaced or connected. This prototype uses no AICTE logo or seal and makes no claim of affiliation or endorsement. Problem statement: SIH26261."))));
}
function feat(i, t, d) { return h("div", { class: "feat" }, h("div", { class: "fi" }, icon(i, "lg")), h("h3", null, t), h("p", null, d)); }
function section(id, alt, title, sub, ...body) { return h("section", { id, class: "sect " + alt }, h("div", { class: "container" }, h("h2", null, title), h("p", { class: "sub" }, sub), ...body)); }
