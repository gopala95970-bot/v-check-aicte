"""Rule definitions. Rules are data (JSON / database rows), not code.

A RuleSet is immutable. Changing a rule produces a NEW RuleSet with a bumped
version, so every finding can say exactly which rule version produced it and
older results stay explainable.
"""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Optional

from .models import SEVERITIES

SOURCE_STATUSES = ("illustrative", "state_circular_derived", "official_confirmed", "system")
REQUIRED_KEYS = ("rule_id", "name", "description", "check", "applies_to", "params", "severity",
                 "enabled", "version", "effective_date", "source_ref", "source_status", "remediation")


class RuleSetError(ValueError):
    pass


@dataclass(frozen=True)
class Rule:
    rule_id: str
    name: str
    description: str
    check: str
    applies_to: tuple
    params: dict
    severity: str
    enabled: bool
    version: str
    effective_date: str
    source_ref: str
    source_status: str
    remediation: str

    def applies(self, application_type: str) -> bool:
        return "*" in self.applies_to or application_type in self.applies_to


@dataclass(frozen=True)
class RuleSet:
    ruleset_id: str
    version: str
    effective_date: str
    notice: str
    application_types: dict
    document_types: dict
    rules: tuple = field(default_factory=tuple)

    def rule(self, rule_id: str) -> Optional[Rule]:
        return next((r for r in self.rules if r.rule_id == rule_id), None)

    def derive(self, changes: dict[str, dict[str, Any]], new_version: str) -> "RuleSet":
        """Return a new RuleSet with per-rule changes applied.

        Only whitelisted fields can change; each changed rule's version is set to
        new_version. The original RuleSet is untouched.
        """
        editable = {"enabled", "severity", "params", "remediation", "description", "name"}
        if new_version == self.version:
            raise RuleSetError("a changed ruleset needs a new version")
        new_rules = []
        for r in self.rules:
            if r.rule_id in changes:
                bad = set(changes[r.rule_id]) - editable
                if bad:
                    raise RuleSetError(f"fields not editable: {sorted(bad)}")
                r = replace(r, **copy.deepcopy(changes[r.rule_id]), version=new_version)
                _validate_rule(r)
            new_rules.append(r)
        unknown = set(changes) - {r.rule_id for r in self.rules}
        if unknown:
            raise RuleSetError(f"unknown rules: {sorted(unknown)}")
        return replace(self, version=new_version, rules=tuple(new_rules))

    def enabled_rules(self, application_type: str) -> list[Rule]:
        return [r for r in self.rules if r.enabled and r.applies(application_type)]


def _validate_rule(r: Rule) -> None:
    if r.severity not in SEVERITIES:
        raise RuleSetError(f"{r.rule_id}: bad severity {r.severity!r}")
    if r.source_status not in SOURCE_STATUSES:
        raise RuleSetError(f"{r.rule_id}: bad source_status {r.source_status!r}")
    if not re.fullmatch(r"\d+\.\d+\.\d+", r.version):
        raise RuleSetError(f"{r.rule_id}: version must look like 1.0.0")
    if r.source_status == "official_confirmed" and not r.source_ref.startswith("http"):
        raise RuleSetError(f"{r.rule_id}: an officially confirmed rule must cite a URL")


def ruleset_from_dict(d: dict) -> RuleSet:
    rules, seen = [], set()
    for raw in d["rules"]:
        missing = [k for k in REQUIRED_KEYS if k not in raw]
        if missing:
            raise RuleSetError(f"{raw.get('rule_id', '?')}: missing keys {missing}")
        if raw["rule_id"] in seen:
            raise RuleSetError(f"duplicate rule id {raw['rule_id']}")
        seen.add(raw["rule_id"])
        r = Rule(**{**raw, "applies_to": tuple(raw["applies_to"])})
        _validate_rule(r)
        rules.append(r)
    for name in ("ruleset_id", "version", "effective_date", "notice", "application_types", "document_types"):
        if name not in d:
            raise RuleSetError(f"ruleset missing '{name}'")
    return RuleSet(d["ruleset_id"], d["version"], d["effective_date"], d["notice"],
                   d["application_types"], d["document_types"], tuple(rules))


def load_ruleset(path: str | Path) -> RuleSet:
    with open(path, "r", encoding="utf-8") as fh:
        return ruleset_from_dict(json.load(fh))


DEFAULT_RULESET_PATH = Path(__file__).resolve().parent.parent / "rules" / "demo_ruleset_v1.json"
