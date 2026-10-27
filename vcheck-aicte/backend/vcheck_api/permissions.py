"""Role permissions for the API, layered on the engine's workflow.PERMISSIONS.

Authorisation is always enforced server-side, per route, using `require`.
"""
from __future__ import annotations

from vcheck import workflow

from .errors import forbidden

EXTRA = {
    "applicant": {"document.view_own", "application.edit_own", "notification.view", "settings.profile"},
    "reviewer": {"review.assign", "finding.resolve", "comment.add", "review.escalate", "rules.view",
                 "notification.view", "settings.profile", "document.correct_fields", "application.revalidate"},
    "admin": {"rules.view", "settings.admin", "demo.manage", "notification.view", "settings.profile",
              "document.view_all", "application.revalidate", "review.assign"},
}


def perms(role: str) -> set[str]:
    return set(workflow.PERMISSIONS.get(role, set())) | EXTRA.get(role, set())


def has(role: str, perm: str) -> bool:
    return perm in perms(role)


def require(role: str, perm: str) -> None:
    if not has(role, perm):
        raise forbidden(f"The {role} role is not allowed to perform '{perm}'.")
