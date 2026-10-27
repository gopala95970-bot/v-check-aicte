"""Audit trail.

Records who did what to which object and when. It deliberately never stores
passwords, tokens, secrets or document contents: `redact` strips them from any
structured detail, and descriptions are length-limited. The in-memory log is
the reference implementation; the API layer will persist the same events.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from .models import new_id, utcnow_iso
from .workflow import can

# Matched against the WORDS of a key (split on _, -, spaces and camelCase), so
# "access_token" and "apiKey" are caught but a harmless "filename" is kept.
FORBIDDEN_WORDS = {"password", "passwd", "token", "secret", "authorization", "apikey", "cookie",
                   "content", "text", "bytes", "body", "blob", "data", "file", "raw", "credential", "credentials"}
MAX_DESCRIPTION = 300


def _is_sensitive_key(key: str) -> bool:
    words = set(re.findall(r"[a-z]+", re.sub(r"([a-z])([A-Z])", r"\1_\2", str(key)).lower()))
    return bool(words & FORBIDDEN_WORDS) or {"api", "key"} <= words


def redact(details: Optional[dict[str, Any]]) -> dict[str, Any]:
    return {k: "[redacted]" if _is_sensitive_key(k) else v for k, v in (details or {}).items()}


@dataclass(frozen=True)
class AuditEvent:
    actor: str
    actor_role: str
    action: str
    object_type: str
    object_id: str
    description: str
    from_status: Optional[str] = None
    to_status: Optional[str] = None
    details: dict = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: new_id("AUD"))
    timestamp: str = field(default_factory=utcnow_iso)


class AuditLog:
    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    def record(self, actor: str, actor_role: str, action: str, object_type: str, object_id: str,
               description: str, from_status: Optional[str] = None, to_status: Optional[str] = None,
               details: Optional[dict[str, Any]] = None) -> AuditEvent:
        ev = AuditEvent(actor, actor_role, action, object_type, object_id,
                        (description or "")[:MAX_DESCRIPTION], from_status, to_status, redact(details))
        self._events.append(ev)
        return ev

    def search(self, viewer_role: str, *, actor: Optional[str] = None, action: Optional[str] = None,
               object_type: Optional[str] = None, object_id: Optional[str] = None,
               text: Optional[str] = None) -> list[AuditEvent]:
        if not can(viewer_role, "audit.view"):
            from .workflow import PermissionDenied
            raise PermissionDenied("The audit log is restricted to reviewers and administrators.")
        res = self._events
        if actor:
            res = [e for e in res if e.actor == actor]
        if action:
            res = [e for e in res if e.action == action]
        if object_type:
            res = [e for e in res if e.object_type == object_type]
        if object_id:
            res = [e for e in res if e.object_id == object_id]
        if text:
            res = [e for e in res if text.lower() in e.description.lower()]
        return list(reversed(res))

    def __len__(self) -> int:
        return len(self._events)
