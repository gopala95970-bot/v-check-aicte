"""Synthetic evaluation dataset.

Expectations are written here BEFORE the engine is run against them. A case is
either:
  deterministic  digital PDFs / known-bad files: the set of triggered rule IDs
                 must equal `expected` exactly.
  ocr_dependent  degraded scans: results depend on OCR quality, so we assert
                 `must_include` is present and (optionally) that no hard
                 "failed" finding was produced by a possible misread.

All institutions, identifiers and numbers are fictional.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Optional

import synth
from vcheck.models import Application, CourseRow

TODAY_ISO = "2026-10-22"

GF = dict(name="Greenfield Institute of Technology", id="1-9000000101", state="Tamil Nadu", addr="12 Demo Road, Demo City")
RB = dict(name="Riverbend College of Engineering", id="1-9000000202", state="Karnataka", addr="48 Sample Avenue, Example Town")
COURSES = [("B.E. Computer Science and Engineering", "180"), ("B.Tech. Information Technology", "60")]
CERTS = {"GF": ("EOA/GF/2026/100", "OCC/GF/2026/101", "AFF/GF/2026/102", "GOV/GF/2026/103"),
         "RB": ("EOA/RB/2026/200", "OCC/RB/2026/201", "AFF/RB/2026/202", "GOV/RB/2026/203")}


@dataclass
class FileSpec:
    name: str
    raw: bytes
    declared_type: Optional[str]


@dataclass
class Case:
    case_id: str
    title: str
    kind: str                       # deterministic | ocr_dependent
    app: Application
    files: list[FileSpec]
    expected: set = field(default_factory=set)       # deterministic: exact set of rule ids
    must_include: set = field(default_factory=set)   # ocr_dependent
    forbid_failed: bool = False                      # ocr_dependent: no hard failures allowed
    provider: Optional[str] = None                   # None | simulated_ok | simulated_mismatch | unavailable
    note: str = ""


def make_app(n: int, inst: dict, app_type: str = "extension_of_approval", **over) -> Application:
    base = dict(id=f"APP-{n:03d}", reference=f"VC-DEMO-{n:04d}", institution_name=inst["name"],
                institution_id=inst["id"], state=inst["state"], address=inst["addr"],
                application_type=app_type, courses=[CourseRow(c, i) for c, i in COURSES])
    base.update(over)
    return Application(**base)


def specs_for(app: Application, key: str = "GF", **over) -> dict:
    eoa, occ, aff, gov = CERTS[key]
    common = dict(institution_name=app.institution_name, institution_id=app.institution_id,
                  issue_date="15-May-2026", issuer="Demo Issuing Office")
    d = {
        "eoa_letter": dict(common, type="eoa_letter", application_ref=app.reference, certificate_number=eoa,
                           courses=list(COURSES)),
        "occupancy_certificate": dict(common, type="occupancy_certificate", certificate_number=occ, courses=[],
                                      institution_id=None),
        "affiliation_letter": dict(common, type="affiliation_letter", certificate_number=aff,
                                   expiry_date="31-May-2027", courses=list(COURSES)),
        "government_approval": dict(common, type="government_approval", certificate_number=gov,
                                    expiry_date="31-May-2027", courses=[(c, "") for c, _ in COURSES],
                                    institution_id=None),
    }
    for t, upd in over.items():
        d[t] = dict(d[t], **upd)
    return d


def render(spec: dict, mode: str = "pdf", **kw) -> tuple[str, bytes]:
    t = spec["type"]
    if mode == "pdf":
        return f"{t}.pdf", synth.digital_pdf(spec, **kw)
    if mode == "scan":
        return f"{t}_scan.pdf", synth.scanned_pdf(spec, **kw)
    if mode == "png":
        return f"{t}.png", synth.image_bytes(synth.page_image(spec, **kw))
    if mode == "jpg":
        return f"{t}.jpg", synth.image_bytes(synth.page_image(spec, **kw), "JPEG")
    raise ValueError(mode)


def files_from(specs: dict, modes: Optional[dict] = None, skip: tuple = ()) -> list[FileSpec]:
    out = []
    for t, spec in specs.items():
        if t in skip:
            continue
        name, raw = render(spec, (modes or {}).get(t, "pdf"))
        out.append(FileSpec(name, raw, t))
    return out


def prior_corpus_specs() -> dict:
    """The earlier application of a DIFFERENT institution that the corpus remembers."""
    return specs_for(make_app(900, RB), "RB")


def build_cases() -> list[Case]:
    cases: list[Case] = []
    n = 0

    def add(case_id, title, specs=None, *, app=None, kind="deterministic", expected=(), must_include=(),
            forbid_failed=False, provider=None, modes=None, skip=(), files=None, note=""):
        nonlocal n
        n += 1
        a = app or make_app(n, GF)
        s = specs if specs is not None else specs_for(a)
        cases.append(Case(case_id, title, kind, a, files if files is not None else files_from(s, modes, skip),
                          set(expected), set(must_include), forbid_failed, provider, note))
        return a

    # ---- clean applications (also test false-positive resistance vs the corpus)
    add("C01", "Complete, consistent application (digital PDFs)")
    add("C02", "Complete application, all four documents as scanned PDFs", kind="ocr_dependent",
        modes={t: "scan" for t in ("eoa_letter", "occupancy_certificate", "affiliation_letter", "government_approval")},
        forbid_failed=True, note="Clean 150-dpi renders: OCR is expected to read these correctly.")
    add("C03", "Complete application in mixed formats (PNG, JPEG, scanned PDF, digital PDF)", kind="ocr_dependent",
        modes={"eoa_letter": "png", "occupancy_certificate": "jpg", "affiliation_letter": "scan", "government_approval": "pdf"},
        forbid_failed=True)
    a = make_app(4, GF)
    add("C04", "Abbreviated institution name on documents ('Inst. of Tech.') must NOT raise a flag", app=a,
        specs=specs_for(a, **{t: {"institution_name": "Greenfield Inst. of Tech."} for t in
                              ("eoa_letter", "occupancy_certificate", "affiliation_letter", "government_approval")}))
    # ---- missing documents
    add("C05", "Missing occupancy certificate", expected={"REQ-DOC-001"}, skip=("occupancy_certificate",))
    add("C06", "Missing affiliation letter", expected={"REQ-DOC-003"}, skip=("affiliation_letter",))
    add("C07", "Missing government approval", expected={"REQ-DOC-004"}, skip=("government_approval",))
    add("C08", "Only the approval letter uploaded", expected={"REQ-DOC-001", "REQ-DOC-003", "REQ-DOC-004"},
        skip=("occupancy_certificate", "affiliation_letter", "government_approval"))
    # ---- dates
    a = make_app(9, GF)
    add("C09", "Expired affiliation letter", app=a, expected={"DATE-002"},
        specs=specs_for(a, affiliation_letter={"issue_date": "01-Apr-2025", "expiry_date": "31-Mar-2026"}))
    a = make_app(10, GF)
    add("C10", "Contradictory dates (issued after validity end)", app=a, expected={"DATE-002", "DATE-003"},
        specs=specs_for(a, affiliation_letter={"issue_date": "15-May-2026", "expiry_date": "10-Jan-2026"}))
    a = make_app(11, GF)
    add("C11", "Issue date in the future", app=a, expected={"DATE-004"},
        specs=specs_for(a, occupancy_certificate={"issue_date": "15-Dec-2026"}))
    a = make_app(12, GF)
    add("C12", "Impossible calendar date (31-02-2026)", app=a, expected={"DATE-001"},
        specs=specs_for(a, occupancy_certificate={"issue_date": "31-02-2026"}))
    # ---- cross-document consistency
    a = make_app(13, GF)
    add("C13", "Different institution name on occupancy certificate", app=a, expected={"XD-001"},
        specs=specs_for(a, occupancy_certificate={"institution_name": "Lakeside College of Pharmacy"}))
    a = make_app(14, GF)
    add("C14", "Near-identical institution name (spelling variant) -> review, not failure", app=a, expected={"XD-001"},
        specs=specs_for(a, affiliation_letter={"institution_name": "Greenfeld Institute of Technology"}))
    a = make_app(15, GF)
    add("C15", "Institution identifier mismatch", app=a, expected={"XD-002"},
        specs=specs_for(a, affiliation_letter={"institution_id": "1-9000000999"}))
    a = make_app(16, GF)
    add("C16", "Identifier differs only by OCR-confusable characters (O vs 0)", app=a, expected={"XD-002"},
        specs=specs_for(a, eoa_letter={"institution_id": "1-9OO0000101"}))
    a = make_app(17, GF)
    add("C17", "Intake conflict (document 120 vs application 180)", app=a, expected={"XD-005"},
        specs=specs_for(a, eoa_letter={"courses": [(COURSES[0][0], "120"), COURSES[1]]}))
    a = make_app(18, GF)
    add("C18", "Course on affiliation letter not in application", app=a, expected={"XD-004"},
        specs=specs_for(a, affiliation_letter={"courses": [COURSES[0], ("B.Sc. Nursing", "40")]}))
    a = make_app(19, GF)
    second = render(dict(specs_for(a)["occupancy_certificate"], certificate_number="OCC/GF/2026/777"))
    add("C19", "Two occupancy certificates with different numbers", app=a, expected={"XD-006", "DUP-004"},
        files=files_from(specs_for(a)) + [FileSpec("occupancy_second.pdf", second[1], "occupancy_certificate")],
        note="Second certificate differs only in its number. AMENDED after measurement: originally expected {XD-006} only, under an a-priori 0.9 similarity threshold that measurement showed would miss this (similarity 0.855).")
    a = make_app(20, GF)
    add("C20", "Approval letter refers to a different application", app=a, expected={"XD-003"},
        specs=specs_for(a, eoa_letter={"application_ref": "VC-DEMO-9999"}))
    # ---- duplicates / reuse (checked against the prior application of another institution)
    a = make_app(21, GF)
    base = files_from(specs_for(a))
    occ = next(f for f in base if f.declared_type == "occupancy_certificate")
    add("C21", "Same occupancy certificate file uploaded twice", app=a, expected={"DUP-001"},
        files=base + [FileSpec("occupancy_copy.pdf", occ.raw, "occupancy_certificate")])
    a = make_app(22, GF)
    prior = prior_corpus_specs()
    other = dict(zip(prior, [synth.digital_pdf(s) for s in prior.values()]))
    base = [f for f in files_from(specs_for(a)) if f.declared_type != "occupancy_certificate"]
    add("C22", "Exact file reused from another institution's application", app=a, expected={"DUP-002", "XD-001"},
        files=base + [FileSpec("occupancy.pdf", other["occupancy_certificate"], "occupancy_certificate")])
    a = make_app(23, GF)
    base = [f for f in files_from(specs_for(a)) if f.declared_type != "occupancy_certificate"]
    name, raw = render(prior["occupancy_certificate"], "png")
    add("C23", "Another institution's certificate re-saved as an image (different bytes, same content)", app=a,
        kind="ocr_dependent", must_include={"DUP-003", "DUP-004", "XD-001"}, files=base + [FileSpec(name, raw, "occupancy_certificate")],
        note="Content reused in a new file format; found through text, not hashes. AMENDED after measurement: DUP-004 added once the threshold was set to 0.80.")
    # ---- file problems
    a = make_app(25, GF)
    add("C25", "Executable renamed to .pdf", app=a, expected={"SYS-001", "REQ-DOC-001"},
        files=[f for f in files_from(specs_for(a)) if f.declared_type != "occupancy_certificate"] +
              [FileSpec("occupancy.pdf", b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 200, "occupancy_certificate")])
    a = make_app(26, GF)
    _, png = render(specs_for(a)["occupancy_certificate"], "png")
    add("C26", "PNG image named .pdf (extension mismatch)", app=a, expected={"SYS-001", "REQ-DOC-001"},
        files=[f for f in files_from(specs_for(a)) if f.declared_type != "occupancy_certificate"] +
              [FileSpec("occupancy.pdf", png, "occupancy_certificate")])
    a = make_app(27, GF)
    good = synth.digital_pdf(specs_for(a)["occupancy_certificate"])
    add("C27", "Truncated (corrupt) PDF", app=a, expected={"SYS-001", "REQ-DOC-001"},
        files=[f for f in files_from(specs_for(a)) if f.declared_type != "occupancy_certificate"] +
              [FileSpec("occupancy.pdf", good[:len(good) // 3], "occupancy_certificate")])
    a = make_app(28, GF)
    add("C28", "File larger than the upload limit", app=a, expected={"SYS-001", "REQ-DOC-001"},
        files=[f for f in files_from(specs_for(a)) if f.declared_type != "occupancy_certificate"] +
              [FileSpec("occupancy.pdf", b"%PDF-1.4\n" + b"0" * (11 * 1024 * 1024), "occupancy_certificate")])
    a = make_app(29, GF)
    add("C29", "Empty file", app=a, expected={"SYS-001", "REQ-DOC-001"},
        files=[f for f in files_from(specs_for(a)) if f.declared_type != "occupancy_certificate"] +
              [FileSpec("occupancy.pdf", b"", "occupancy_certificate")])
    # ---- scan quality (OCR dependent)
    a = make_app(30, GF)
    s = specs_for(a)
    name, raw = render(s["affiliation_letter"], "scan", blur=7.0, noise=0.03)
    add("C30", "Unreadable scan (heavy blur and noise)", app=a, kind="ocr_dependent", must_include={"SYS-002"},
        forbid_failed=False, files=[f for f in files_from(s) if f.declared_type != "affiliation_letter"] +
        [FileSpec(name, raw, "affiliation_letter")], note="Expected to yield no usable text; routed to manual review.")
    a = make_app(31, GF)
    s = specs_for(a)
    name, raw = render(s["affiliation_letter"], "png", rotate=2.0, noise=0.002)
    add("C31", "Slightly rotated, noisy scan", app=a, kind="ocr_dependent", forbid_failed=True,
        files=[f for f in files_from(s) if f.declared_type != "affiliation_letter"] + [FileSpec(name, raw, "affiliation_letter")],
        note="OCR misreads must produce review items, never hard failures.")
    a = make_app(32, GF)
    s = specs_for(a)
    name, raw = render(s["eoa_letter"], "jpg", dpi=70, blur=1.2)
    add("C32", "Low-resolution blurry JPEG", app=a, kind="ocr_dependent", forbid_failed=False, must_include=set(),
        files=[f for f in files_from(s) if f.declared_type != "eoa_letter"] + [FileSpec(name, raw, "eoa_letter")],
        note="Result depends on OCR; recorded as measured. Hard failures here would indicate over-confidence.")
    # ---- verification
    add("C33", "Verification source unavailable", provider="unavailable", expected={"VER-001"})
    a = make_app(34, GF)
    add("C34", "Simulated registry holds a different identifier for the affiliation letter", app=a,
        provider="simulated_mismatch", expected={"VER-001"})
    add("C35", "Simulated registry confirms every document (labelled simulation, not 'verified')", provider="simulated_ok")
    # ---- metadata / active content
    a = make_app(36, GF)
    add("C36", "PDF produced by an image editor (metadata anomaly)", app=a, expected={"META-001"},
        files=[f for f in files_from(specs_for(a)) if f.declared_type != "occupancy_certificate"] +
              [FileSpec("occupancy.pdf", synth.digital_pdf(specs_for(a)["occupancy_certificate"], producer="Adobe Photoshop 25.0"),
                        "occupancy_certificate")])
    a = make_app(37, GF)
    add("C37", "PDF containing JavaScript", app=a, expected={"META-002"},
        files=[f for f in files_from(specs_for(a)) if f.declared_type != "occupancy_certificate"] +
              [FileSpec("occupancy.pdf", synth.digital_pdf(specs_for(a)["occupancy_certificate"], javascript=True),
                        "occupancy_certificate")])
    # ---- application-level problems
    a = make_app(38, GF, institution_id="")
    add("C38", "Application has no institution identifier", app=a, expected={"APP-001"},
        specs=specs_for(make_app(38, GF)))
    a = make_app(39, GF)
    a.courses[0] = CourseRow(COURSES[0][0], "-5")
    add("C39", "Negative intake entered in the application", app=a, expected={"NUM-001"})
    a = make_app(40, GF, institution_id="GF-101")
    add("C40", "Institution identifier in the wrong format (consistently)", app=a, expected={"APP-002"})
    a = make_app(41, GF)
    s = specs_for(a)
    s["occupancy_certificate"].pop("certificate_number")
    add("C41", "Certificate number missing on a digital certificate", app=a, expected={"FLD-003"}, specs=s)
    a = make_app(42, GF)
    s = specs_for(a)
    f = files_from(s)
    swap = {"occupancy_certificate": "affiliation_letter", "affiliation_letter": "occupancy_certificate"}
    add("C42", "Occupancy and affiliation documents uploaded under each other's category", app=a,
        expected={"SYS-004", "FLD-002", "FLD-005", "FLD-006"},
        files=[FileSpec(x.name, x.raw, swap.get(x.declared_type, x.declared_type)) for x in f])
    a = make_app(43, GF, institution_id="1-9000000999")
    add("C43", "Several problems at once (wrong id + expired + missing document)", app=a,
        expected={"XD-002", "DATE-002", "REQ-DOC-001"}, skip=("occupancy_certificate",),
        specs=specs_for(a, affiliation_letter={"issue_date": "01-Apr-2025", "expiry_date": "31-Mar-2026",
                                               "institution_id": "1-9000000101"},
                        eoa_letter={"institution_id": "1-9000000101"}))
    a = make_app(44, GF, app_type="new_institution")
    add("C44", "Different checklist for a 'new institution' application (only two documents required)", app=a,
        skip=("eoa_letter", "affiliation_letter"))
    return cases
