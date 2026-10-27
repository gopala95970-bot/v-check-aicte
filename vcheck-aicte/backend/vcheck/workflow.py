"""Application workflow and role permissions.

These are enforced here (and will be called by every API route), not by hiding
buttons in the UI. "Approved"/"Rejected" exist only as DEMONSTRATION outcomes:
they never represent a real AICTE decision.
"""
from __future__ import annotations

from .models import Finding

DRAFT, SUBMITTED, PROCESSING = "draft", "submitted", "processing"
VALIDATION_COMPLETE, REVIEW_REQUIRED = "validation_complete", "review_required"
CORRECTIONS_REQUESTED, RESUBMITTED = "corrections_requested", "resubmitted"
APPROVED_DEMO, REJECTED_DEMO = "approved_demo", "rejected_demo"

STATUSES = (DRAFT, SUBMITTED, PROCESSING, VALIDATION_COMPLETE, REVIEW_REQUIRED,
            CORRECTIONS_REQUESTED, RESUBMITTED, APPROVED_DEMO, REJECTED_DEMO)
TERMINAL = {APPROVED_DEMO, REJECTED_DEMO}
DECISIONS = {APPROVED_DEMO, REJECTED_DEMO}
STATUS_LABELS = {
    DRAFT: "Draft", SUBMITTED: "Submitted", PROCESSING: "Processing",
    VALIDATION_COMPLETE: "Validation complete", REVIEW_REQUIRED: "Review required",
    CORRECTIONS_REQUESTED: "Corrections requested", RESUBMITTED: "Resubmitted",
    APPROVED_DEMO: "Approved (demonstration only)", REJECTED_DEMO: "Rejected (demonstration only)",
}

TRANSITIONS: dict[tuple[str, str], set[str]] = {
    (DRAFT, SUBMITTED): {"applicant"},
    (SUBMITTED, PROCESSING): {"system"},
    (PROCESSING, VALIDATION_COMPLETE): {"system"},
    (PROCESSING, REVIEW_REQUIRED): {"system"},
    (VALIDATION_COMPLETE, CORRECTIONS_REQUESTED): {"reviewer"},
    (VALIDATION_COMPLETE, APPROVED_DEMO): {"reviewer"},
    (VALIDATION_COMPLETE, REJECTED_DEMO): {"reviewer"},
    (REVIEW_REQUIRED, CORRECTIONS_REQUESTED): {"reviewer"},
    (REVIEW_REQUIRED, APPROVED_DEMO): {"reviewer"},
    (REVIEW_REQUIRED, REJECTED_DEMO): {"reviewer"},
    (CORRECTIONS_REQUESTED, RESUBMITTED): {"applicant"},
    (RESUBMITTED, PROCESSING): {"system"},
}

PERMISSIONS: dict[str, set[str]] = {
    "applicant": {"application.create", "application.view_own", "document.upload", "application.submit", "finding.view_own"},
    "reviewer": {"application.view_all", "finding.view_all", "finding.mark_reviewed", "extraction.correct",
                 "review.request_corrections", "review.decide", "audit.view", "stats.view", "document.view_all"},
    "admin": {"application.view_all", "finding.view_all", "rules.manage", "users.manage", "audit.view", "stats.view"},
    "system": {"pipeline.run"},
}


class WorkflowError(Exception):
    """Base class; carries a safe, user-presentable message."""


class PermissionDenied(WorkflowError):
    pass


class InvalidTransition(WorkflowError):
    pass


class ConfirmationRequired(WorkflowError):
    pass


def can(role: str, action: str) -> bool:
    return action in PERMISSIONS.get(role, set())


def require(role: str, action: str) -> None:
    if not can(role, action):
        raise PermissionDenied(f"The role '{role}' is not allowed to perform '{action}'.")


def allowed_targets(current: str, role: str) -> list[str]:
    return [t for (f, t), roles in TRANSITIONS.items() if f == current and role in roles]


def transition(current: str, target: str, role: str, *, confirm: bool = False, remarks: str = "",
               unreviewed_high_findings: int = 0) -> str:
    """Validate and return the new status, or raise. Never mutates anything."""
    if current in TERMINAL:
        raise InvalidTransition(f"'{STATUS_LABELS[current]}' is final and cannot be changed.")
    roles = TRANSITIONS.get((current, target))
    if roles is None:
        raise InvalidTransition(f"An application cannot move from '{STATUS_LABELS.get(current, current)}' to '{STATUS_LABELS.get(target, target)}'.")
    if role not in roles:
        raise PermissionDenied(f"The role '{role}' cannot move an application from '{current}' to '{target}'.")
    if target in DECISIONS or target == CORRECTIONS_REQUESTED:
        if len((remarks or "").strip()) < 5:
            raise WorkflowError("Remarks are required for this action (at least 5 characters).")
    if target in DECISIONS:
        if not confirm:
            raise ConfirmationRequired("This is a significant action and must be explicitly confirmed.")
        if target == APPROVED_DEMO and unreviewed_high_findings > 0:
            raise WorkflowError(f"{unreviewed_high_findings} high-severity finding(s) have not been marked as reviewed.")
    return target


def visible_findings(role: str, findings: list[Finding]) -> list[Finding]:
    """Applicants never see findings that mention other institutions' applications."""
    if can(role, "finding.view_all"):
        return list(findings)
    if can(role, "finding.view_own"):
        return [f for f in findings if not f.reviewer_only]
    return []
