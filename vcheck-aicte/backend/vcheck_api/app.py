"""WSGI application: routing, auth, JSON/multipart parsing, CORS, security headers, safe errors.

Pure stdlib so it runs (and is tested) anywhere. The URL/JSON contract is stable (see docs/API.md) so the
React frontend, or a later FastAPI port, can rely on it."""
from __future__ import annotations

import json
import logging
import mimetypes
import re
import uuid
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, unquote

from vcheck import workflow

from . import seed, services_admin as adm, services_core as core
from .config import ROOT_DIR, Settings
from .context import Context
from .errors import ApiError, bad_request, forbidden, not_found, too_large, unauthorized, unprocessable

log = logging.getLogger("vcheck.api")
PREFIX = "/api/v1"
JSON_LIMIT = 1_000_000
STATUS_TEXT = {200: "OK", 201: "Created", 202: "Accepted", 204: "No Content", 400: "Bad Request", 401: "Unauthorized",
               403: "Forbidden", 404: "Not Found", 405: "Method Not Allowed", 409: "Conflict", 411: "Length Required",
               413: "Payload Too Large", 422: "Unprocessable Entity", 429: "Too Many Requests", 500: "Internal Server Error"}


class Request:
    def __init__(self, environ: dict, ctx: Context) -> None:
        self.environ, self.ctx = environ, ctx
        self.method = environ["REQUEST_METHOD"].upper()
        self.path = unquote(environ.get("PATH_INFO", "/"))
        self.query = {k: v[0] for k, v in parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=False).items()}
        self.content_type = environ.get("CONTENT_TYPE", "")
        self.ip = environ.get("REMOTE_ADDR", "-")
        self.user: Optional[dict] = None
        self.params: dict[str, str] = {}
        self._body: Optional[bytes] = None

    @property
    def authorization(self) -> str:
        return self.environ.get("HTTP_AUTHORIZATION", "")

    def body(self, limit: int) -> bytes:
        if self._body is None:
            try:
                n = int(self.environ.get("CONTENT_LENGTH") or 0)
            except ValueError:
                raise bad_request("Invalid Content-Length.")
            if n > limit:
                raise too_large(f"The request is larger than the allowed {limit // (1024 * 1024) or 1} MB." if limit > 1_048_576 else "The request body is too large.")
            self._body = self.environ["wsgi.input"].read(n) if n else b""
        return self._body

    def json(self) -> dict:
        raw = self.body(JSON_LIMIT)
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise bad_request("The request body is not valid JSON.", code="invalid_json")
        if not isinstance(data, dict):
            raise bad_request("The request body must be a JSON object.", code="invalid_json")
        return data

    def multipart(self, limit: int) -> tuple[dict[str, str], Optional[tuple[str, bytes]]]:
        """Parse multipart/form-data with the stdlib email parser. Returns (text fields, (filename, bytes))."""
        raw = self.body(limit)
        head = b"Content-Type: " + self.content_type.encode("latin-1", "ignore") + b"\r\nMIME-Version: 1.0\r\n\r\n"
        msg = BytesParser(policy=policy.HTTP).parsebytes(head + raw)
        if not msg.is_multipart():
            raise bad_request("Expected multipart/form-data.", code="invalid_multipart")
        fields, file = {}, None
        for part in msg.iter_parts():
            name = part.get_param("name", header="content-disposition")
            fname = part.get_filename()
            payload = part.get_payload(decode=True) or b""
            if fname is not None and name == "file":
                file = (fname, payload)
            elif name and fname is None:
                fields[name] = payload.decode("utf-8", "replace")[:500]
        return fields, file


class Response:
    def __init__(self, status: int = 200, body: Any = None, headers: Optional[list] = None, raw: Optional[bytes] = None, mime: str = "application/json") -> None:
        self.status, self.headers = status, list(headers or [])
        if raw is not None:
            self.raw, self.mime = raw, mime
        elif body is None:
            self.raw, self.mime = b"", mime
        else:
            self.raw, self.mime = json.dumps(body, ensure_ascii=False, default=str).encode("utf-8"), "application/json; charset=utf-8"


# ------------------------------------------------------------------ routing
Handler = Callable[[Request], Response]
ROUTES: list[tuple[str, re.Pattern, Handler, bool]] = []


def route(method: str, pattern: str, public: bool = False):
    rx = re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", pattern) + "$")

    def deco(fn: Handler) -> Handler:
        ROUTES.append((method, rx, fn, public))
        return fn
    return deco


def _page(req: Request) -> dict:
    return req.query


# ---- public
@route("GET", "/health", public=True)
def health(req): return Response(200, {"status": "ok", "service": "vcheck-api"})


@route("GET", "/meta", public=True)
def meta(req): return Response(200, adm.meta(req.ctx))


@route("POST", "/auth/login", public=True)
def login(req):
    b = req.json()
    return Response(200, core.login(req.ctx, str(b.get("email", ""))[:200], str(b.get("password", ""))[:200], req.ip))


# ---- auth
@route("POST", "/auth/logout")
def logout(req): core.logout(req.ctx, req.user); return Response(204)
@route("GET", "/auth/me")
def me(req): return Response(200, adm.get_profile(req.ctx, req.user))
@route("POST", "/auth/change-password")
def chpw(req):
    b = req.json(); core.change_password(req.ctx, req.user, str(b.get("current_password", "")), str(b.get("new_password", "")))
    return Response(200, {"ok": True})


# ---- dashboard / analytics
@route("GET", "/dashboard")
def dashboard(req): return Response(200, adm.dashboard(req.ctx, req.user))
@route("GET", "/analytics")
def analytics(req): return Response(200, adm.analytics(req.ctx, req.user))


# ---- applications
@route("GET", "/applications")
def apps_list(req): return Response(200, core.list_applications(req.ctx, req.user, _page(req)))
@route("POST", "/applications")
def apps_create(req): return Response(201, core.create_application(req.ctx, req.user, req.json()))
@route("GET", "/applications/{id}")
def apps_get(req): return Response(200, core.get_application(req.ctx, req.user, req.params["id"]))
@route("PATCH", "/applications/{id}")
def apps_patch(req): return Response(200, core.update_application(req.ctx, req.user, req.params["id"], req.json()))
@route("POST", "/applications/{id}/submit")
def apps_submit(req): return Response(202, core.submit_application(req.ctx, req.user, req.params["id"]))
@route("POST", "/applications/{id}/validate")
def apps_validate(req): return Response(200, core.revalidate(req.ctx, req.user, req.params["id"]))
@route("GET", "/applications/{id}/pipeline")
def apps_pipeline(req): return Response(200, adm.pipeline(req.ctx, req.user, req.params["id"]))
@route("GET", "/applications/{id}/findings")
def apps_findings(req): return Response(200, core.list_findings(req.ctx, req.user, _page(req), req.params["id"]))
@route("GET", "/applications/{id}/documents")
def apps_docs(req): return Response(200, core.list_documents(req.ctx, req.user, req.params["id"], {**_page(req), "page_size": 100}))
@route("GET", "/applications/{id}/review/history")
def apps_hist(req): return Response(200, {"items": core.review_history(req.ctx, req.user, req.params["id"])})
@route("POST", "/applications/{id}/review/actions")
def apps_review(req): return Response(200, core.review_action(req.ctx, req.user, req.params["id"], req.json()))


@route("POST", "/applications/{id}/documents")
def doc_upload(req):
    limit = req.ctx.max_upload_bytes + 64 * 1024
    ct = req.content_type.lower()
    if ct.startswith("multipart/form-data"):
        fields, file = req.multipart(limit)
        if file is None:
            raise unprocessable("Choose a file to upload.", fields={"file": "required"})
        fname, raw = file
        dtype, repl = fields.get("document_type") or None, fields.get("replaces") or None
    else:        # raw body: ?filename=&document_type=
        raw = req.body(limit)
        fname = req.query.get("filename") or "upload"
        dtype, repl = req.query.get("document_type"), req.query.get("replaces")
    return Response(201, core.upload_document(req.ctx, req.user, req.params["id"], raw, fname, dtype, repl))


@route("POST", "/applications/{id}/demo-documents")
def doc_demo(req):
    items = adm.generate_demo_documents(req.ctx, req.user, req.params["id"], str(req.json().get("scenario", "clean")))
    return Response(201, {"items": items})


# ---- documents
@route("GET", "/documents")
def docs_list(req): return Response(200, core.list_documents(req.ctx, req.user, None, _page(req)))
@route("GET", "/documents/{id}")
def docs_get(req): return Response(200, core.get_document(req.ctx, req.user, req.params["id"]))
@route("DELETE", "/documents/{id}")
def docs_del(req): core.remove_document(req.ctx, req.user, req.params["id"]); return Response(204)


@route("GET", "/documents/{id}/file")
def docs_file(req):
    raw, mime, name = core.document_file(req.ctx, req.user, req.params["id"])
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return Response(200, raw=raw, mime=mime, headers=[("Content-Disposition", f'inline; filename="{safe}"'),
                                                      ("Content-Security-Policy", "sandbox; default-src 'none'"),
                                                      ("Cache-Control", "private, no-store")])


@route("PATCH", "/documents/{id}/fields/{fid}")
def field_patch(req):
    b = req.json()
    if not str(req.params["fid"]).isdigit():
        raise bad_request("Invalid field id.")
    return Response(200, core.correct_field(req.ctx, req.user, req.params["id"], int(req.params["fid"]), b.get("value"), b.get("revalidate", True)))


# ---- findings / review / verification
@route("GET", "/findings")
def find_list(req): return Response(200, core.list_findings(req.ctx, req.user, _page(req)))
@route("GET", "/findings/{id}")
def find_get(req): return Response(200, core.get_finding(req.ctx, req.user, req.params["id"]))
@route("PATCH", "/findings/{id}")
def find_patch(req):
    b = req.json(); return Response(200, core.update_finding(req.ctx, req.user, req.params["id"], str(b.get("status", "")), str(b.get("note", ""))))
@route("GET", "/review/queue")
def rev_queue(req): return Response(200, core.review_queue(req.ctx, req.user, _page(req)))
@route("GET", "/review/reviewers")
def rev_list(req): return Response(200, {"items": core.list_reviewers(req.ctx, req.user)})
@route("GET", "/verification")
def verif(req): return Response(200, adm.verification_overview(req.ctx, req.user))


# ---- rules
@route("GET", "/rules")
def rules_list(req): return Response(200, adm.list_rules(req.ctx, req.user))
@route("GET", "/rules/versions")
def rules_versions(req): return Response(200, {"items": adm.rule_versions(req.ctx, req.user)})
@route("POST", "/rules/versions")
def rules_new(req):
    b = req.json(); return Response(201, adm.create_rule_version(req.ctx, req.user, b.get("changes"), b.get("new_version"), str(b.get("note", ""))))
@route("GET", "/rules/{id}")
def rules_get(req): return Response(200, adm.get_rule(req.ctx, req.user, req.params["id"]))
@route("PATCH", "/rules/{id}")
def rules_patch(req):
    b = req.json()
    if not isinstance(b.get("enabled"), bool):
        raise unprocessable("Provide enabled as true or false.", fields={"enabled": "required"})
    return Response(200, adm.set_rule_enabled(req.ctx, req.user, req.params["id"], b["enabled"], str(b.get("note", ""))))


# ---- audit / settings / notifications / demo
@route("GET", "/audit")
def audit(req): return Response(200, adm.audit_list(req.ctx, req.user, _page(req)))
@route("GET", "/audit/facets")
def audit_f(req): return Response(200, adm.audit_facets(req.ctx, req.user))
@route("GET", "/settings/profile")
def prof(req): return Response(200, adm.get_profile(req.ctx, req.user))
@route("PUT", "/settings/profile")
def prof_put(req): return Response(200, adm.update_profile(req.ctx, req.user, req.json()))
@route("PUT", "/settings/notifications")
def notif_put(req): return Response(200, adm.update_notifications(req.ctx, req.user, req.json()))
@route("GET", "/settings/system")
def sysinfo(req): return Response(200, adm.system_info(req.ctx, req.user))
@route("GET", "/settings/admin")
def adm_get(req): return Response(200, adm.get_admin_settings(req.ctx, req.user))
@route("PUT", "/settings/admin")
def adm_put(req): return Response(200, adm.update_admin_settings(req.ctx, req.user, req.json()))
@route("GET", "/notifications")
def notes(req): return Response(200, adm.list_notifications(req.ctx, req.user))
@route("POST", "/notifications/read")
def notes_read(req):
    nid = req.json().get("id"); return Response(200, adm.mark_notifications(req.ctx, req.user, int(nid) if isinstance(nid, int) else None))
@route("GET", "/demo/scenarios")
def demo_sc(req): return Response(200, adm.demo_scenarios(req.ctx, req.user))


@route("POST", "/demo/reset")
def demo_reset(req):
    from .permissions import require
    require(req.user["role"], "demo.manage")
    if req.ctx.get_setting("demo_mode") != "true":
        raise forbidden("Demo mode is switched off.")
    prev = req.ctx.settings.sync_processing
    seed.reset_demo(req.ctx, req.user)
    return Response(200, {"ok": True, "message": "Demo applications were reset."})


# ------------------------------------------------------------------ WSGI app
SECURITY_HEADERS = [("X-Content-Type-Options", "nosniff"), ("X-Frame-Options", "DENY"), ("Referrer-Policy", "no-referrer"),
                    ("Cross-Origin-Resource-Policy", "same-site"), ("Permissions-Policy", "camera=(), microphone=(), geolocation=()")]


class VCheckApp:
    def __init__(self, settings: Optional[Settings] = None, ctx: Optional[Context] = None) -> None:
        self.ctx = ctx or Context(settings)
        seed.ensure_users(self.ctx)
        if self.ctx.settings.seed_demo:
            seed.seed_demo(self.ctx)
        self.static_dir = ROOT_DIR / "frontend"

    # -- CORS
    def _cors(self, environ: dict) -> list:
        origin = environ.get("HTTP_ORIGIN")
        if origin and origin in self.ctx.settings.cors_origins:
            return [("Access-Control-Allow-Origin", origin), ("Vary", "Origin"),
                    ("Access-Control-Allow-Headers", "Authorization, Content-Type"),
                    ("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS"),
                    ("Access-Control-Expose-Headers", "Content-Disposition"), ("Access-Control-Max-Age", "600")]
        return []

    def __call__(self, environ: dict, start_response):
        rid = uuid.uuid4().hex[:10]
        try:
            resp = self._handle(environ, rid)
        except ApiError as e:
            resp = Response(e.status, {"error": {"code": e.code, "message": e.message, **({"details": e.details} if e.details else {}), "request_id": rid}})
            if e.status == 429:
                resp.headers.append(("Retry-After", str(e.details.get("retry_after_seconds", 60))))
            if e.status == 401:
                resp.headers.append(("WWW-Authenticate", "Bearer"))
        except workflow.WorkflowError as e:
            ae = core._map_workflow(e)
            resp = Response(ae.status, {"error": {"code": ae.code, "message": ae.message, "request_id": rid}})
        except Exception:
            log.exception("unhandled error [%s]", rid)
            resp = Response(500, {"error": {"code": "internal_error", "message": "Something went wrong on our side. Please try again; if it persists, quote the request id.", "request_id": rid}})
        headers = [("Content-Type", resp.mime), ("Content-Length", str(len(resp.raw))), ("X-Request-Id", rid)] + SECURITY_HEADERS + self._cors(environ) + resp.headers
        if not any(h[0] == "Cache-Control" for h in headers):
            headers.append(("Cache-Control", "no-store"))
        start_response(f"{resp.status} {STATUS_TEXT.get(resp.status, '')}", headers)
        return [resp.raw] if environ["REQUEST_METHOD"] != "HEAD" else [b""]

    def _handle(self, environ: dict, rid: str) -> Response:
        method, path = environ["REQUEST_METHOD"].upper(), unquote(environ.get("PATH_INFO", "/"))
        if method == "OPTIONS":
            return Response(204)
        if not path.startswith(PREFIX):
            return self._static(path, method)
        req = Request(environ, self.ctx)
        sub = path[len(PREFIX):] or "/"
        allowed = []
        for m, rx, fn, public in ROUTES:
            mo = rx.match(sub)
            if not mo:
                continue
            if m != method:
                allowed.append(m)
                continue
            req.params = mo.groupdict()
            if not public:
                auth = req.authorization
                if not auth.startswith("Bearer ") or len(auth) < 20:
                    raise unauthorized()
                req.user = core.authenticate(self.ctx, auth[7:].strip())
            return fn(req)
        if allowed:
            raise ApiError(405, "method_not_allowed", f"{method} is not supported here.")
        raise not_found("Unknown endpoint.", code="unknown_endpoint")

    def _static(self, path: str, method: str) -> Response:
        """Serve the built React app if present (production-style single-origin deployment)."""
        if method not in ("GET", "HEAD") or not self.static_dir.is_dir():
            raise not_found("Not found.")
        rel = path.lstrip("/") or "index.html"
        f = (self.static_dir / rel).resolve()
        base = self.static_dir.resolve()
        if base not in f.parents and f != base or not f.is_file():
            if "." in rel.rsplit("/", 1)[-1]:   # a missing asset is a 404, not the app shell
                raise not_found("Not found.")
            f = base / "index.html"            # SPA fallback for client-side routes
            if not f.is_file():
                raise not_found("Not found.")
        mime = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
        if f.suffix == ".js":
            mime = "text/javascript; charset=utf-8"
        extra = [("Cache-Control", "no-cache")]
        if f.suffix in (".html", ""):
            # Strict CSP: only our own scripts/styles; PDFs/images previewed from blob: URLs created in the page.
            extra.append(("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; "
                          "frame-src blob:; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"))
        return Response(200, raw=f.read_bytes(), mime=mime, headers=extra)


def create_app(settings: Optional[Settings] = None) -> VCheckApp:
    return VCheckApp(settings)
