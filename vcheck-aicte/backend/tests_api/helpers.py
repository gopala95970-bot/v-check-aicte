"""Test client that drives the real WSGI app (no mocks of the API layer)."""
import io
import json
import tempfile
import time
import uuid

from vcheck_api.app import create_app
from vcheck_api.config import Settings
from vcheck_api.seed import DEMO_PASSWORDS

TODAY = "2026-10-22"


class Client:
    def __init__(self, app):
        self.app = app

    def call(self, method, path, body=None, token=None, query="", ctype="application/json", raw=None, headers=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else b"")
        env = {"REQUEST_METHOD": method, "PATH_INFO": "/api/v1" + path, "QUERY_STRING": query, "CONTENT_TYPE": ctype,
               "CONTENT_LENGTH": str(len(data)), "wsgi.input": io.BytesIO(data), "REMOTE_ADDR": "10.0.0.1"}
        if token:
            env["HTTP_AUTHORIZATION"] = "Bearer " + token
        for k, v in (headers or {}).items():
            env["HTTP_" + k.upper().replace("-", "_")] = v
        out = {}
        self_headers = {}

        def sr(status, hdrs):
            out["status"] = int(status.split()[0])
            self_headers.update(dict(hdrs))
        body_bytes = b"".join(self.app(env, sr))
        ct = self_headers.get("Content-Type", "")
        parsed = json.loads(body_bytes) if body_bytes and ct.startswith("application/json") else body_bytes
        self.last_headers = self_headers
        return out["status"], parsed

    def login(self, email, password=None):
        s, r = self.call("POST", "/auth/login", {"email": email, "password": password or DEMO_PASSWORDS[email]})
        assert s == 200, (s, r)
        return r["token"]

    def upload(self, token, app_id, filename, raw, doc_type=None, replaces=None):
        boundary = "----vcheck" + uuid.uuid4().hex
        parts = []
        for k, v in (("document_type", doc_type), ("replaces", replaces)):
            if v:
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode() + raw + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        return self.call("POST", f"/applications/{app_id}/documents", token=token, raw=b"".join(parts),
                         ctype=f"multipart/form-data; boundary={boundary}")


def make_app(**over):
    settings = Settings(storage_dir=tempfile.mkdtemp(prefix="vcheck-test-"), sync_processing=over.pop("sync_processing", True),
                        today=TODAY, **over)
    return create_app(settings)


def wait_until(fn, timeout=60, step=0.1):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(step)
    raise AssertionError("timed out waiting for condition")


NEW_APP = {
    "institution": {"name": "Test Valley Institute of Technology", "institution_id": "1-9000000777", "state": "Tamil Nadu",
                    "district": "Demo District", "address": "1 Test Road", "contact_email": "x@demo.vcheck"},
    "application_type": "extension_of_approval", "academic_year": "2026-27",
    "courses": [{"name": "B.E. Computer Science and Engineering", "intake": "120"}],
}
