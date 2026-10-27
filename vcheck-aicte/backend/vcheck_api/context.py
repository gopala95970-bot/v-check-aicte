"""Application context: settings, database, active ruleset, audit log, notifications."""
from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import date
from typing import Any, Optional

from vcheck import audit as engine_audit
from vcheck.models import new_id, utcnow_iso
from vcheck.rules import RuleSet, ruleset_from_dict

from .config import Settings
from .db import Database
from .security import LoginThrottle

SYSTEM = {"id": None, "email": "system@vcheck.local", "role": "system", "name": "V-Check pipeline"}

DEFAULT_SETTINGS = {
    "verification_mode": "off",          # off | simulation | unavailable
    "demo_mode": "true",
    "max_upload_mb": None,               # falls back to Settings.max_upload_mb
    "max_pdf_pages": None,
}


def ruleset_to_dict(rs: RuleSet) -> dict[str, Any]:
    d = {"ruleset_id": rs.ruleset_id, "version": rs.version, "effective_date": rs.effective_date,
         "notice": rs.notice, "application_types": rs.application_types, "document_types": rs.document_types,
         "rules": []}
    for r in rs.rules:
        x = asdict(r)
        x["applies_to"] = list(r.applies_to)
        d["rules"].append(x)
    return d


class Context:
    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or Settings()
        self.settings.ensure_dirs()
        self.db = Database(self.settings.db_path)
        self.db.init()
        self.throttle = LoginThrottle(self.settings.login_max_failures, self.settings.login_window_seconds)
        self.executor = ThreadPoolExecutor(max_workers=max(1, self.settings.workers), thread_name_prefix="vcheck-proc")
        self._rs_cache: Optional[tuple[int, RuleSet]] = None
        self._lock = threading.Lock()
        self._pending: set[str] = set()
        self._pending_lock = threading.Lock()
        self._ensure_ruleset()

    # ---------------------------------------------------------------- time
    def today(self) -> date:
        return self.settings.today()

    # ---------------------------------------------------------------- settings
    def get_setting(self, key: str) -> Optional[str]:
        row = self.db.one("SELECT value FROM settings WHERE key=?", (key,))
        if row is not None:
            return row["value"]
        if key == "verification_mode":      # optional environment default; the admin setting (DB) always wins
            import os
            v = os.environ.get("VERIFICATION_MODE", "off")
            return v if v in ("off", "simulation", "unavailable") else "off"
        return DEFAULT_SETTINGS.get(key)

    def set_setting(self, key: str, value: str) -> None:
        with self.db.tx() as c:
            c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                      (key, str(value)))

    @property
    def max_upload_bytes(self) -> int:
        v = self.get_setting("max_upload_mb")
        return int(v) * 1024 * 1024 if v else self.settings.max_upload_bytes

    @property
    def max_pdf_pages(self) -> int:
        v = self.get_setting("max_pdf_pages")
        return int(v) if v else self.settings.max_pdf_pages

    # ---------------------------------------------------------------- ruleset
    def _ensure_ruleset(self) -> None:
        if self.db.scalar("SELECT COUNT(*) FROM rule_sets") == 0:
            body = json.loads(self.settings.ruleset_path.read_text(encoding="utf-8"))
            rs = ruleset_from_dict(body)            # validates before storing
            with self.db.tx() as c:
                c.execute("""INSERT INTO rule_sets(ruleset_id,version,effective_date,body_json,is_active,created_by,
                             change_note,changed_rules_json,created_at) VALUES(?,?,?,?,1,?,?,?,?)""",
                          (rs.ruleset_id, rs.version, rs.effective_date, json.dumps(body), "system",
                           "Initial demonstration ruleset loaded from the repository.", "[]", utcnow_iso()))

    def active_ruleset(self) -> RuleSet:
        row = self.db.one("SELECT id, body_json FROM rule_sets WHERE is_active=1")
        with self._lock:
            if self._rs_cache and self._rs_cache[0] == row["id"]:
                return self._rs_cache[1]
            rs = ruleset_from_dict(json.loads(row["body_json"]))
            self._rs_cache = (row["id"], rs)
            return rs

    # ---------------------------------------------------------------- audit
    def audit(self, actor: dict, action: str, object_type: str, object_id: str, description: str, *,
              application_id: Optional[str] = None, from_status: Optional[str] = None,
              to_status: Optional[str] = None, result: str = "success", details: Optional[dict] = None,
              conn=None) -> None:
        """Append-only. Reuses the engine's redaction so secrets/content never reach the log."""
        row = (new_id("AUD"), utcnow_iso(), actor["email"], actor["role"], action, object_type, str(object_id),
               application_id, (description or "")[: engine_audit.MAX_DESCRIPTION], from_status, to_status, result,
               json.dumps(engine_audit.redact(details)))
        sql = """INSERT INTO audit_logs(event_id,ts,actor_email,actor_role,action,object_type,object_id,application_id,
                 description,from_status,to_status,result,details_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)"""
        if conn is not None:
            conn.execute(sql, row)
        else:
            with self.db.tx() as c:
                c.execute(sql, row)

    # ---------------------------------------------------------------- notifications
    def notify(self, user_id: Optional[int], kind: str, title: str, body: str = "",
               application_id: Optional[str] = None, conn=None) -> None:
        if user_id is None:
            return
        u = self.db.one("SELECT notify_prefs FROM users WHERE id=?", (user_id,))
        if u is None:
            return
        prefs = json.loads(u["notify_prefs"] or "{}")
        if prefs.get(kind) is False:
            return
        sql = "INSERT INTO notifications(user_id,kind,title,body,application_id,created_at) VALUES(?,?,?,?,?,?)"
        args = (user_id, kind, title, body, application_id, utcnow_iso())
        if conn is not None:
            conn.execute(sql, args)
        else:
            with self.db.tx() as c:
                c.execute(sql, args)

    def notify_role(self, role: str, kind: str, title: str, body: str = "", application_id: Optional[str] = None) -> None:
        for r in self.db.all("SELECT id FROM users WHERE role=? AND active=1", (role,)):
            self.notify(r["id"], kind, title, body, application_id)

    # ---------------------------------------------------------------- in-flight tracking
    def mark_pending(self, key: str) -> None:
        with self._pending_lock:
            self._pending.add(key)

    def clear_pending(self, key: str) -> None:
        with self._pending_lock:
            self._pending.discard(key)

    def is_pending(self, key: str) -> bool:
        with self._pending_lock:
            return key in self._pending

    def wait_idle(self, timeout: float = 60.0) -> bool:
        import time
        end = time.time() + timeout
        while time.time() < end:
            with self._pending_lock:
                if not self._pending:
                    return True
            time.sleep(0.05)
        return False
