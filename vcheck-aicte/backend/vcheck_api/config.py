"""Runtime configuration. Everything comes from environment variables (or a .env file);
no secret is ever hard-coded. If JWT_SECRET is unset a random one is generated once and
stored in the storage directory (never in source control)."""
from __future__ import annotations

import os
import secrets
from datetime import date
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BACKEND_DIR.parent


def _load_dotenv() -> None:
    for candidate in (ROOT_DIR / ".env", BACKEND_DIR / ".env"):
        if candidate.is_file():
            for line in candidate.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


class Settings:
    """Read at construction so tests can build isolated instances."""

    def __init__(self, **over) -> None:
        env = os.environ.get
        storage = Path(over.get("storage_dir") or env("STORAGE_DIR") or ROOT_DIR / "storage")
        self.storage_dir = storage
        self.upload_dir = Path(over.get("upload_dir") or env("UPLOAD_DIR") or storage / "uploads")
        db_url = over.get("database_url") or env("DATABASE_URL") or ""
        if db_url.startswith("sqlite:///"):
            p = Path(db_url[len("sqlite:///"):])
            self.db_path = p if p.is_absolute() else (ROOT_DIR / p)
        else:
            self.db_path = Path(over.get("db_path") or storage / "vcheck.db")
        self.max_upload_mb = over.get("max_upload_mb") or _int("MAX_UPLOAD_MB", 10)
        self.max_pdf_pages = over.get("max_pdf_pages") or _int("MAX_PDF_PAGES", 50)
        self.token_ttl_minutes = over.get("token_ttl_minutes") or _int("TOKEN_TTL_MINUTES", 480)
        origins = over.get("cors_origins") or env("CORS_ORIGINS") or "http://localhost:5173,http://127.0.0.1:5173"
        self.cors_origins = [o.strip() for o in origins.split(",") if o.strip()]
        self.sync_processing = bool(over.get("sync_processing", env("SYNC_PROCESSING") == "1"))
        self.workers = over.get("workers") or _int("PROCESSING_WORKERS", 2)
        self.seed_demo = over.get("seed_demo", env("SEED_DEMO", "1") != "0")
        self.host = over.get("host") or env("API_HOST") or "127.0.0.1"
        self.port = over.get("port") or _int("API_PORT", _int("PORT", 8000))   # PORT is what most hosts inject
        self._jwt_secret = over.get("jwt_secret") or env("JWT_SECRET") or ""
        self._today = over.get("today") or env("VCHECK_TODAY") or ""
        self.login_max_failures = over.get("login_max_failures") or _int("LOGIN_MAX_FAILURES", 5)
        self.login_window_seconds = over.get("login_window_seconds") or _int("LOGIN_WINDOW_SECONDS", 300)
        self.ruleset_path = Path(over.get("ruleset_path") or BACKEND_DIR / "rules" / "demo_ruleset_v1.json")

    def ensure_dirs(self) -> None:
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    @property
    def jwt_secret(self) -> str:
        placeholder = "replace-with-a-long-random-value"
        if self._jwt_secret and self._jwt_secret != placeholder and len(self._jwt_secret) >= 32:
            return self._jwt_secret
        self.ensure_dirs()
        f = self.storage_dir / ".jwt_secret"
        if not f.exists():
            f.write_text(secrets.token_urlsafe(48), encoding="utf-8")
            try:
                f.chmod(0o600)
            except OSError:
                pass
        self._jwt_secret = f.read_text(encoding="utf-8").strip()
        return self._jwt_secret

    def today(self) -> date:
        return date.fromisoformat(self._today) if self._today else date.today()

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_mb) * 1024 * 1024
