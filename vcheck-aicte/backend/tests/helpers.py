"""Shared test helpers. Tests run from the backend/ directory."""
import pathlib
import sys
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data" / "synthetic"))

import dataset  # noqa: E402
import synth  # noqa: E402
from vcheck.engine import validate_application  # noqa: E402
from vcheck.models import Application, CourseRow  # noqa: E402
from vcheck.pipeline import process_document  # noqa: E402
from vcheck.rules import DEFAULT_RULESET_PATH, load_ruleset  # noqa: E402

RULESET = load_ruleset(DEFAULT_RULESET_PATH)
TODAY = date(2026, 10, 22)
GF, RB = dataset.GF, dataset.RB


def make_app(n=1, inst=None, **kw):
    return dataset.make_app(n, inst or GF, **kw)


def specs(app=None, key="GF", **over):
    return dataset.specs_for(app or make_app(), key, **over)


def doc_from(spec, mode="pdf", app_id="APP-001", doc_id="D1", declared="same", **kw):
    name, raw = dataset.render(spec, mode, **kw)
    return process_document(raw, name, doc_id, app_id, spec["type"] if declared == "same" else declared, RULESET, TODAY)


def docs_for(app, spec_map, skip=(), mode="pdf"):
    return [doc_from(s, mode, app.id, f"D{i}") for i, (t, s) in enumerate(spec_map.items()) if t not in skip]


def validate(app, spec_map=None, docs=None, skip=(), corpus=(), verifications=(), ruleset=None):
    spec_map = spec_map if spec_map is not None else specs(app)
    docs = docs if docs is not None else docs_for(app, spec_map, skip)
    return validate_application(app, docs, ruleset or RULESET, corpus, verifications, TODAY)


def rule_ids(report):
    return sorted({f.rule_id for f in report.findings})
