"""SQLite persistence (stdlib sqlite3). One connection per thread, WAL mode, explicit
transactions. The schema is created idempotently and versioned through `schema_version`.
PostgreSQL is a later swap: all SQL here is plain and parameterised."""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL UNIQUE COLLATE NOCASE,
  name TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('applicant','reviewer','admin')),
  organization TEXT NOT NULL DEFAULT '',
  password_hash TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  notify_prefs TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  last_login_at TEXT
);
CREATE TABLE IF NOT EXISTS revoked_tokens (jti TEXT PRIMARY KEY, expires_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS institutions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_id INTEGER NOT NULL REFERENCES users(id),
  name TEXT NOT NULL,
  institution_id TEXT NOT NULL DEFAULT '',
  address TEXT NOT NULL DEFAULT '',
  state TEXT NOT NULL DEFAULT '',
  district TEXT NOT NULL DEFAULT '',
  contact_name TEXT NOT NULL DEFAULT '',
  contact_email TEXT NOT NULL DEFAULT '',
  contact_phone TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS applications (
  id TEXT PRIMARY KEY,
  seq INTEGER NOT NULL UNIQUE,
  reference TEXT NOT NULL UNIQUE,
  institution_pk INTEGER NOT NULL REFERENCES institutions(id),
  owner_id INTEGER NOT NULL REFERENCES users(id),
  reviewer_id INTEGER REFERENCES users(id),
  application_type TEXT NOT NULL,
  academic_year TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL,
  verification_mode TEXT,
  escalated INTEGER NOT NULL DEFAULT 0,
  is_demo INTEGER NOT NULL DEFAULT 1,
  demo_scenario TEXT,
  decision_remarks TEXT,
  decided_by TEXT,
  decided_at TEXT,
  correction_cycles INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  submitted_at TEXT,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_app_owner ON applications(owner_id);
CREATE INDEX IF NOT EXISTS ix_app_status ON applications(status);
CREATE TABLE IF NOT EXISTS application_courses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  application_id TEXT NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  name TEXT NOT NULL,
  intake TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY,
  application_id TEXT NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
  declared_type TEXT,
  original_filename TEXT NOT NULL,
  storage_name TEXT,
  kind TEXT,
  size INTEGER NOT NULL DEFAULT 0,
  sha256 TEXT,
  status TEXT NOT NULL,
  detected_type TEXT,
  detected_confidence REAL,
  text_source TEXT,
  ocr_mean_conf REAL,
  page_count INTEGER NOT NULL DEFAULT 0,
  text_fingerprint TEXT,
  phash TEXT,
  certificate_numbers TEXT NOT NULL DEFAULT '[]',
  processed_json TEXT,
  issues_json TEXT NOT NULL DEFAULT '[]',
  active INTEGER NOT NULL DEFAULT 1,
  uploaded_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL,
  processed_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_doc_app ON documents(application_id);
CREATE TABLE IF NOT EXISTS extracted_fields (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  idx INTEGER NOT NULL DEFAULT 0,
  value TEXT NOT NULL,
  corrected_value TEXT,
  corrected_by TEXT,
  corrected_at TEXT,
  page INTEGER,
  line_no INTEGER,
  snippet TEXT,
  confidence REAL,
  method TEXT,
  bbox TEXT
);
CREATE INDEX IF NOT EXISTS ix_fld_doc ON extracted_fields(document_id);
CREATE TABLE IF NOT EXISTS validation_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  application_id TEXT NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
  ruleset_id TEXT NOT NULL,
  ruleset_version TEXT NOT NULL,
  triggered_by TEXT NOT NULL,
  trigger TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  duration_ms INTEGER,
  status TEXT NOT NULL,
  counts_json TEXT NOT NULL DEFAULT '{}',
  suggested_status TEXT,
  rules_run_json TEXT NOT NULL DEFAULT '[]',
  rules_skipped_json TEXT NOT NULL DEFAULT '[]',
  error TEXT
);
CREATE INDEX IF NOT EXISTS ix_run_app ON validation_runs(application_id);
CREATE TABLE IF NOT EXISTS findings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  public_id TEXT NOT NULL UNIQUE,
  run_id INTEGER NOT NULL REFERENCES validation_runs(id) ON DELETE CASCADE,
  application_id TEXT NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
  signature TEXT NOT NULL,
  rule_id TEXT NOT NULL,
  rule_version TEXT NOT NULL,
  title TEXT NOT NULL,
  outcome TEXT NOT NULL,
  severity TEXT NOT NULL,
  explanation TEXT NOT NULL,
  recommended_action TEXT NOT NULL,
  observed TEXT,
  expected TEXT,
  confidence REAL,
  limitations TEXT,
  reviewer_only INTEGER NOT NULL DEFAULT 0,
  document_ids_json TEXT NOT NULL DEFAULT '[]',
  fields_json TEXT NOT NULL DEFAULT '[]',
  evidence_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'open',
  resolution_note TEXT,
  resolved_by TEXT,
  resolved_at TEXT,
  is_current INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_find_app ON findings(application_id, is_current);
CREATE TABLE IF NOT EXISTS verification_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL REFERENCES validation_runs(id) ON DELETE CASCADE,
  application_id TEXT NOT NULL,
  document_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  simulated INTEGER NOT NULL,
  status TEXT NOT NULL,
  display_status TEXT NOT NULL,
  detail TEXT NOT NULL,
  checked_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stage_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  application_id TEXT NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
  run_id INTEGER,
  document_id TEXT,
  scope TEXT NOT NULL,
  stage TEXT NOT NULL,
  status TEXT NOT NULL,
  duration_ms INTEGER,
  result TEXT NOT NULL DEFAULT '',
  evidence_json TEXT NOT NULL DEFAULT '[]',
  errors_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_stage_app ON stage_events(application_id);
CREATE TABLE IF NOT EXISTS rule_sets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ruleset_id TEXT NOT NULL,
  version TEXT NOT NULL,
  effective_date TEXT NOT NULL,
  body_json TEXT NOT NULL,
  is_active INTEGER NOT NULL DEFAULT 0,
  created_by TEXT NOT NULL,
  change_note TEXT NOT NULL DEFAULT '',
  changed_rules_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  UNIQUE (ruleset_id, version)
);
CREATE TABLE IF NOT EXISTS review_actions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  application_id TEXT NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
  finding_id TEXT,
  actor_id INTEGER,
  actor_email TEXT NOT NULL,
  actor_role TEXT NOT NULL,
  action TEXT NOT NULL,
  remarks TEXT NOT NULL DEFAULT '',
  from_status TEXT,
  to_status TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_rev_app ON review_actions(application_id);
CREATE TABLE IF NOT EXISTS audit_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL UNIQUE,
  ts TEXT NOT NULL,
  actor_email TEXT NOT NULL,
  actor_role TEXT NOT NULL,
  action TEXT NOT NULL,
  object_type TEXT NOT NULL,
  object_id TEXT NOT NULL,
  application_id TEXT,
  description TEXT NOT NULL,
  from_status TEXT,
  to_status TEXT,
  result TEXT NOT NULL DEFAULT 'success',
  details_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_aud_ts ON audit_logs(ts);
CREATE INDEX IF NOT EXISTS ix_aud_app ON audit_logs(application_id);
CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  body TEXT NOT NULL DEFAULT '',
  application_id TEXT,
  read INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS verification_registry (
  certificate_number TEXT PRIMARY KEY,
  institution_id TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT 'synthetic'
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._local = threading.local()
        self._write_lock = threading.RLock()

    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            c = sqlite3.connect(str(self.path), timeout=15, isolation_level=None, check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA foreign_keys=ON")
            c.execute("PRAGMA busy_timeout=15000")
            self._local.conn = c
        return c

    def init(self) -> None:
        c = self.conn()
        c.executescript(SCHEMA)
        if c.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == 0:
            c.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))

    @contextmanager
    def tx(self):
        """Serialised write transaction (SQLite has a single writer anyway)."""
        with self._write_lock:
            c = self.conn()
            c.execute("BEGIN IMMEDIATE")
            try:
                yield c
            except BaseException:
                c.execute("ROLLBACK")
                raise
            else:
                c.execute("COMMIT")

    def one(self, sql: str, args: tuple = ()) -> sqlite3.Row | None:
        return self.conn().execute(sql, args).fetchone()

    def all(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        return self.conn().execute(sql, args).fetchall()

    def scalar(self, sql: str, args: tuple = ()):
        r = self.conn().execute(sql, args).fetchone()
        return r[0] if r else None

    def close_thread(self) -> None:
        c = getattr(self._local, "conn", None)
        if c is not None:
            c.close()
            self._local.conn = None
