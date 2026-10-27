"""Runs the full SIH judge story against the LIVE HTTP API and prints each step.

    # terminal 1 (from backend/):   python -m vcheck_api
    # terminal 2 (project root):    python scripts/api_demo.py
    python scripts/api_demo.py --base http://127.0.0.1:8000/api/v1

Every line below is a real API call; nothing is simulated by this script except what the product itself labels as
simulation. It creates one new application, so it also works as an end-to-end smoke test.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request

PW = {"applicant@demo.vcheck": "Applicant@Demo2026", "reviewer@demo.vcheck": "Reviewer@Demo2026", "admin@demo.vcheck": "Admin@Demo2026"}


class Api:
    def __init__(self, base):
        self.base = base.rstrip("/")

    def call(self, method, path, body=None, token=None, query=""):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path + (("?" + query) if query else ""), data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", "Bearer " + token)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            raw = e.read()
            return e.code, (json.loads(raw) if raw else None)

    def login(self, email):
        s, r = self.call("POST", "/auth/login", {"email": email, "password": PW[email]})
        if s != 200:
            sys.exit(f"Login failed for {email}: {r}")
        return r["token"]


def step(n, title):
    print(f"\n{'=' * 78}\n STEP {n}: {title}\n{'=' * 78}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000/api/v1")
    api = Api(ap.parse_args().base)
    s, meta = api.call("GET", "/meta")
    if s != 200:
        sys.exit("API not reachable. Start it first:  cd backend ; python -m vcheck_api")
    print(meta["disclaimer"])

    step(1, "Applicant signs in")
    ta = api.login("applicant@demo.vcheck")
    s, me = api.call("GET", "/auth/me", token=ta)
    print(f"Signed in as {me['name']} ({me['role']})")

    step(2, "Create an application (institution + category + courses)")
    s, app = api.call("POST", "/applications", {
        "institution": {"name": "Demo Hills Institute of Technology", "institution_id": "1-9000000808", "state": "Tamil Nadu",
                        "district": "Demo District", "address": "8 Demo Road, Demo City", "contact_email": "registrar@demo.vcheck"},
        "application_type": "extension_of_approval", "academic_year": "2026-27",
        "courses": [{"name": "B.E. Computer Science and Engineering", "intake": "180"}, {"name": "B.Tech. Information Technology", "intake": "60"}]}, ta)
    app_id = app["id"]
    print(f"{app_id} ({app['reference']}) created as '{app['status_label']}'")

    step(2.5, "Required documents come from the rules, not from the UI")
    s, a = api.call("GET", f"/applications/{app_id}", token=ta)
    for r in a["required_documents"]:
        print(f"   [ ] {r['label']}   ({r['rule_id']})")

    step(3, "Upload documents. Scenario: affiliation letter carries a DIFFERENT institution ID (synthetic)")
    s, r = api.call("POST", f"/applications/{app_id}/demo-documents", {"scenario": "institution_id_mismatch"}, ta)
    for d in r["items"]:
        print(f"   uploaded {d['filename']:28} -> {d['status']}")

    step(4, "Watch processing (OCR/text read, classification, field extraction)")
    for _ in range(100):
        s, docs = api.call("GET", f"/applications/{app_id}/documents", token=ta)
        if all(d["status"] not in ("queued", "processing") for d in docs["items"]):
            break
        time.sleep(0.2)
    for d in docs["items"]:
        steps = " > ".join(f"{x['label']}:{x['state']}" for x in d["steps"])
        print(f"   {d['filename']:28} {d['status']:10} text={d['text_source']:10} detected={d['detected_type']}   [{steps}]")

    step(5, "Submit: the validation pipeline runs in the background")
    s, sub = api.call("POST", f"/applications/{app_id}/submit", token=ta)
    print("status ->", sub["status_label"])
    for _ in range(100):
        s, a = api.call("GET", f"/applications/{app_id}", token=ta)
        if a["status"] not in ("submitted", "processing"):
            break
        time.sleep(0.2)
    print("status ->", a["status_label"])
    s, p = api.call("GET", f"/applications/{app_id}/pipeline", token=ta)
    for st in p["stages"]:
        ms = "" if st["duration_ms"] is None else f"{st['duration_ms']:>4} ms"
        print(f"   {st['stage']:26} {st['status']:8} {ms:8} {st['result'][:70]}")

    step(6, "Explainable finding with evidence, rule and recommended action")
    s, fl = api.call("GET", f"/applications/{app_id}/findings", token=ta)
    f = fl["items"][0]
    print(f"   {f['id']}  {f['title']}   severity={f['severity']} outcome={f['outcome']}")
    print(f"   Rule: {f['rule_id']} v{f['rule_version']} ({f['rule_kind']} rule; source status: {f['rule_source_status']})")
    print(f"   Application value: {f['expected']}    Document value: {f['observed']}")
    for e in f["evidence"]:
        print(f"   Evidence: {e['filename']} page {e['page']} line {e['line_no']}: \"{e['snippet']}\"")
    print(f"   Why: {f['explanation']}")
    print(f"   Recommended action: {f['recommended_action']}")

    step(7, "Reviewer opens the queue and takes the case")
    tr = api.login("reviewer@demo.vcheck")
    s, q = api.call("GET", "/review/queue", token=tr)
    print("   queue:", ", ".join(f"{i['id']}({i['findings']['open']} open)" for i in q["items"][:6]))
    api.call("POST", f"/applications/{app_id}/review/actions", {"action": "assign", "reviewer_id": "self"}, tr)
    s, r = api.call("POST", f"/applications/{app_id}/review/actions", {"action": "approve_demo", "remarks": "Looks fine", "confirm": True}, tr)
    print(f"   Approve attempt BLOCKED by the workflow: {r['error']['message']}")

    step(8, "Reviewer requests a correction from the applicant")
    s, r = api.call("POST", f"/applications/{app_id}/review/actions",
                    {"action": "request_correction", "remarks": "Institution identifier on the affiliation letter does not match the application."}, tr)
    print("   status ->", r["status_label"])

    step(9, "Applicant replaces the documents and resubmits; the finding disappears")
    api.call("POST", f"/applications/{app_id}/demo-documents", {"scenario": "clean"}, ta)
    time.sleep(1)
    api.call("POST", f"/applications/{app_id}/submit", token=ta)
    for _ in range(100):
        s, a = api.call("GET", f"/applications/{app_id}", token=ta)
        if a["status"] not in ("resubmitted", "processing"):
            break
        time.sleep(0.2)
    print(f"   status -> {a['status_label']}; open findings: {a['findings']['open']}; correction cycles: {a['correction_cycles']}")

    step(10, "Reviewer records a DEMONSTRATION decision (explicit confirmation required)")
    s, r = api.call("POST", f"/applications/{app_id}/review/actions", {"action": "approve_demo", "remarks": "Documents consistent after correction.", "confirm": True}, tr)
    print("   status ->", r["status_label"])

    step(11, "Complete audit trail for this application")
    tadm = api.login("admin@demo.vcheck")
    s, aud = api.call("GET", "/audit", token=tadm, query=f"application_id={app_id}&page_size=100")
    for e in reversed(aud["items"]):
        print(f"   {e['timestamp'][:19]}  {e['role']:9} {e['action']:26} {e['result']:8} {e['description'][:60]}")
    print("\nDone. Everything above is synthetic demonstration data; no government system was contacted.")


if __name__ == "__main__":
    main()
