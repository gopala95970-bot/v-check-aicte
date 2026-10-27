"""Run the synthetic evaluation and write docs/evaluation_results.json.

Usage (from the project root):
    python scripts/run_evaluation.py            # full run (OCR, ~2-4 minutes)
    python scripts/run_evaluation.py --quick    # skip the extraction-accuracy section

Everything reported is measured by this script on the synthetic dataset. No
numbers are estimated or copied from elsewhere.
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "data" / "synthetic")]

import dataset  # noqa: E402
import synth  # noqa: E402
from vcheck.duplicates import corpus_entry_from  # noqa: E402
from vcheck.engine import validate_application  # noqa: E402
from vcheck.normalize import normalize_id, normalize_name, parse_date  # noqa: E402
from vcheck.pipeline import process_document  # noqa: E402
from vcheck.rules import DEFAULT_RULESET_PATH, load_ruleset  # noqa: E402
from vcheck.verification import SimulatedProvider, UnavailableProvider, verify_documents  # noqa: E402

TODAY = date.fromisoformat(dataset.TODAY_ISO)
RULESET = load_ruleset(DEFAULT_RULESET_PATH)


def build_corpus():
    prior_app = dataset.make_app(900, dataset.RB)
    specs = dataset.prior_corpus_specs()
    entries = []
    for i, (t, spec) in enumerate(specs.items()):
        doc = process_document(synth.digital_pdf(spec), f"{t}.pdf", f"PRIOR-{i}", prior_app.id, t, RULESET, TODAY)
        entries.append(corpus_entry_from(doc, prior_app))
    return tuple(entries)


def provider_for(case, docs):
    if case.provider is None:
        return None
    if case.provider == "unavailable":
        return UnavailableProvider()
    registry = {}
    for d in docs:
        c = d.primary("certificate_number")
        if c:
            registry[c.effective()] = case.app.institution_id
    if case.provider == "simulated_mismatch":
        for d in docs:
            if d.declared_type == "affiliation_letter" and d.primary("certificate_number"):
                registry[d.primary("certificate_number").effective()] = "1-9000000999"
    return SimulatedProvider(registry)


def run_cases(corpus):
    results = []
    for case in dataset.build_cases():
        t0 = time.time()
        docs = [process_document(f.raw, f.name, f"{case.case_id}-D{i}", case.app.id, f.declared_type, RULESET, TODAY)
                for i, f in enumerate(case.files)]
        vers = verify_documents(provider_for(case, docs), docs)
        report = validate_application(case.app, docs, RULESET, corpus, vers, TODAY)
        actual = Counter(f.rule_id for f in report.findings)
        actual_set = set(actual)
        failed = [f.rule_id for f in report.findings if f.outcome == "failed"]
        if case.kind == "deterministic":
            passed = actual_set == case.expected
            missing, extra = sorted(case.expected - actual_set), sorted(actual_set - case.expected)
        else:
            missing = sorted(case.must_include - actual_set)
            extra = sorted(actual_set - case.must_include)
            passed = not missing and not (case.forbid_failed and failed)
        results.append({
            "case_id": case.case_id, "title": case.title, "kind": case.kind, "passed": passed,
            "expected": sorted(case.expected or case.must_include), "actual": dict(sorted(actual.items())),
            "missing": missing, "unexpected": extra if case.kind == "deterministic" else [],
            "extra_allowed_ocr": extra if case.kind != "deterministic" else [],
            "hard_failures": sorted(failed), "n_files": len(case.files),
            "doc_status": dict(Counter(d.status for d in docs)),
            "seconds": round(time.time() - t0, 1), "note": case.note,
        })
        flag = "PASS" if passed else "FAIL"
        print(f"{case.case_id} {flag}  {case.title[:70]:70}  actual={dict(sorted(actual.items()))}", flush=True)
    return results


def norm_for(field, v):
    if v is None:
        return None
    if field in ("institution_name", "course_name"):
        return normalize_name(v)
    if field in ("institution_id", "certificate_number", "application_ref"):
        return normalize_id(v)
    if field in ("issue_date", "expiry_date"):
        p = parse_date(v)
        return p.value.isoformat() if p.ok else v.strip().lower()
    return str(v).strip()


MODES = [
    ("digital PDF (text layer)", "pdf", {}),
    ("scanned PDF, clean 150 dpi", "scan", {}),
    ("PNG, clean 150 dpi", "png", {}),
    ("JPEG q70, clean 150 dpi", "jpg", {}),
    ("PNG rotated 2 deg + noise", "png", dict(rotate=2.0, noise=0.002)),
    ("JPEG 70 dpi + blur 1.2", "jpg", dict(dpi=70, blur=1.2)),
]


def extraction_accuracy():
    """Per scan quality: correct / wrong (extracted but different) / missing / unreadable.

    "wrong" is the dangerous category: a value that is present, different from the
    truth, and might be trusted. Its confidence is recorded so we can see whether
    low confidence actually warns the reviewer.
    """
    app = dataset.make_app(1, dataset.GF)
    specs = dataset.specs_for(app)
    out = []
    for label, mode, kw in MODES:
        tally = Counter()
        confs, wrong_confs, misses = [], [], Counter()
        unreadable_docs = 0
        t0 = time.time()
        for t, spec in specs.items():
            name, raw = dataset.render(spec, mode, **kw)
            doc = process_document(raw, name, "X", app.id, t, RULESET, TODAY)
            if doc.ocr_mean_conf is not None:
                confs.append(doc.ocr_mean_conf)
            unreadable = doc.status != "processed"
            unreadable_docs += unreadable
            truth = [(k, spec[k]) for k in ("institution_name", "institution_id", "application_ref",
                                           "certificate_number", "issue_date", "expiry_date") if spec.get(k)]
            rows = {norm_for("course_name", r.course.effective()): r for r in doc.course_rows}
            for cname, intake in spec.get("courses", []):
                truth.append(("course_name", cname))
                if intake:
                    truth.append(("approved_intake", (cname, intake)))
            for k, v in truth:
                if unreadable:
                    tally["unreadable"] += 1
                    continue
                if k == "approved_intake":
                    cname, intake = v
                    row = rows.get(norm_for("course_name", cname))
                    got, conf = (row.intake.effective(), row.intake.confidence) if row and row.intake else (None, None)
                    ok = got == intake
                elif k == "course_name":
                    row = rows.get(norm_for("course_name", v))
                    got, conf = (row.course.effective(), row.course.confidence) if row else (None, None)
                    ok = row is not None
                else:
                    f = doc.primary(k)
                    got, conf = (f.effective(), f.confidence) if f else (None, None)
                    ok = got is not None and norm_for(k, got) == norm_for(k, v)
                if ok:
                    tally["correct"] += 1
                elif got is None:
                    tally["missing"] += 1
                    misses[k] += 1
                else:
                    tally["wrong"] += 1
                    wrong_confs.append(round(conf, 2))
                    misses[k] += 1
        total = sum(tally.values())
        out.append({"mode": label, "fields_total": total, "correct": tally["correct"], "wrong_value": tally["wrong"],
                    "missing": tally["missing"], "in_unreadable_documents": tally["unreadable"],
                    "documents_unreadable": f"{unreadable_docs}/{len(specs)}",
                    "accuracy_of_all_fields": round(tally["correct"] / total, 3),
                    "mean_ocr_confidence": round(sum(confs) / len(confs), 3) if confs else None,
                    "wrong_value_confidences": sorted(wrong_confs), "missed_by_field": dict(misses),
                    "seconds": round(time.time() - t0, 1)})
        print(f"extraction  {label:30} correct={tally['correct']:2} wrong={tally['wrong']:2} missing={tally['missing']:2} "
              f"in_unreadable_docs={tally['unreadable']:2} (unreadable docs {unreadable_docs}/4) wrong_conf={sorted(wrong_confs)}", flush=True)
    return out


def main():
    quick = "--quick" in sys.argv
    corpus = build_corpus()
    results = run_cases(corpus)
    det = [r for r in results if r["kind"] == "deterministic"]
    ocr = [r for r in results if r["kind"] != "deterministic"]
    summary = {
        "generated_on": dataset.TODAY_ISO, "cases_total": len(results),
        "deterministic_total": len(det), "deterministic_passed": sum(r["passed"] for r in det),
        "ocr_dependent_total": len(ocr), "ocr_dependent_passed": sum(r["passed"] for r in ocr),
        "files_total": sum(r["n_files"] for r in results),
    }
    print("\nSUMMARY", json.dumps(summary))
    payload = {"summary": summary, "cases": results,
               "extraction_accuracy": [] if quick else extraction_accuracy(),
               "ruleset": {"id": RULESET.ruleset_id, "version": RULESET.version, "rules": len(RULESET.rules)}}
    out = ROOT / "docs" / "evaluation_results.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main()
