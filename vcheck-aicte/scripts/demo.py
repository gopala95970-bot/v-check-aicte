"""Command-line demo of the validation engine on synthetic applications.

    python scripts/demo.py            # clean case + four problem cases
    python scripts/demo.py C22 C30    # any case ids from data/synthetic/dataset.py

Shows what a reviewer would see: each finding, why it was raised, and the exact
evidence (document, page, line, snippet). Everything is synthetic.
"""
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "data" / "synthetic"), str(ROOT / "scripts")]

import dataset  # noqa: E402
import run_evaluation as ev  # noqa: E402
from vcheck.engine import validate_application  # noqa: E402
from vcheck.pipeline import process_document  # noqa: E402
from vcheck.verification import verify_documents  # noqa: E402

DEFAULT = ["C01", "C15", "C17", "C09", "C22"]
LABEL = {"failed": "FAILED VALIDATION", "review_required": "REVIEW REQUIRED"}


def show(case, corpus):
    print("=" * 78)
    print(f"{case.case_id}: {case.title}")
    print(f"Application {case.app.reference} | {case.app.institution_name} | {len(case.files)} document(s)")
    print("DEMONSTRATION RECORD - independent prototype, not an official AICTE portal")
    print("-" * 78)
    docs = [process_document(f.raw, f.name, f"{case.case_id}-D{i}", case.app.id, f.declared_type, ev.RULESET, ev.TODAY)
            for i, f in enumerate(case.files)]
    for d in docs:
        print(f"  [{d.status:10}] {d.original_filename:34} text:{d.text_source:10} detected:{d.detected_type}")
    rep = validate_application(case.app, docs, ev.RULESET, corpus, verify_documents(ev.provider_for(case, docs), docs), ev.TODAY)
    if not rep.findings:
        print("\nNo findings. Suggested status: validation complete (a human reviewer still decides).")
    for f in rep.findings:
        print(f"\n  {LABEL[f.outcome]} | {f.severity.upper()} | {f.rule_id} v{f.rule_version}: {f.title}")
        print(f"    Why: {f.explanation}")
        if f.observed or f.expected:
            print(f"    Observed: {f.observed}   Expected: {f.expected}")
        for e in f.evidence:
            print(f"    Evidence: {e.document_id} page {e.page} line {e.line_no} -> \"{e.snippet}\"")
        print(f"    Next step: {f.recommended_action}")
        if f.limitations:
            print(f"    Limitation: {f.limitations}")
        if f.reviewer_only:
            print("    (visible to reviewers only)")
    c = rep.counts()
    print(f"\nSummary: {c['failed']} failed, {c['review_required']} review required -> suggested status '{rep.suggested_status}'")


def main():
    ids = sys.argv[1:] or DEFAULT
    corpus = ev.build_corpus()
    cases = {c.case_id: c for c in dataset.build_cases()}
    for i in ids:
        show(cases[i], corpus)


if __name__ == "__main__":
    main()
