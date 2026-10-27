"""Trusted-source verification connectors.

Nothing here talks to a government service. Real integration (for example
DigiLocker as a requester partner) needs authorised credentials and onboarding
that a student team does not have, so the only working provider is a
SIMULATION backed by a local synthetic registry.

Hard rule enforced by the model and by tests: a simulated result is never
reported as "verified".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

from .models import ProcessedDocument, utcnow_iso
from .normalize import normalize_id

SIMULATION_BANNER = "SIMULATED verification against a local synthetic registry. This is NOT a government verification."


@dataclass(frozen=True)
class VerificationResult:
    document_id: str
    provider: str
    simulated: bool
    status: str          # verified | not_found | mismatch | unavailable | error
    detail: str
    checked_at: str = ""

    @property
    def is_trusted_verification(self) -> bool:
        """True only for a real (non-simulated) successful verification."""
        return self.status == "verified" and not self.simulated

    @property
    def display_status(self) -> str:
        if self.simulated and self.status == "verified":
            return "simulated_match"
        return self.status


class VerificationProvider(Protocol):
    name: str
    simulated: bool

    def verify(self, doc: ProcessedDocument) -> VerificationResult: ...


class SimulatedProvider:
    name = "Simulation (synthetic registry)"
    simulated = True

    def __init__(self, registry: dict[str, str]):
        """registry maps certificate number -> institution id (both synthetic)."""
        self._reg = {normalize_id(k): normalize_id(v) for k, v in registry.items()}

    def verify(self, doc: ProcessedDocument) -> VerificationResult:
        now = utcnow_iso()
        cert = doc.primary("certificate_number")
        if cert is None:
            return VerificationResult(doc.document_id, self.name, True, "unavailable",
                                      f"{SIMULATION_BANNER} No certificate number was extracted to look up.", now)
        key = normalize_id(cert.effective())
        if key not in self._reg:
            return VerificationResult(doc.document_id, self.name, True, "not_found",
                                      f"{SIMULATION_BANNER} Certificate number not present in the synthetic registry.", now)
        inst = doc.primary("institution_id")
        if inst is not None and normalize_id(inst.effective()) != self._reg[key]:
            return VerificationResult(doc.document_id, self.name, True, "mismatch",
                                      f"{SIMULATION_BANNER} Certificate exists but is registered to a different identifier.", now)
        return VerificationResult(doc.document_id, self.name, True, "verified",
                                  f"{SIMULATION_BANNER} Certificate number found in the synthetic registry.", now)


class UnavailableProvider:
    """Models an offline or unreachable verification source."""
    name = "Unavailable source"
    simulated = True

    def verify(self, doc: ProcessedDocument) -> VerificationResult:
        return VerificationResult(doc.document_id, self.name, True, "unavailable",
                                  "The verification source could not be reached.", utcnow_iso())


class DigiLockerProvider:
    """Placeholder for a future authorised integration. Does nothing without credentials."""
    name = "DigiLocker (not configured)"
    simulated = False

    def verify(self, doc: ProcessedDocument) -> VerificationResult:
        return VerificationResult(doc.document_id, self.name, False, "unavailable",
                                  "No authorised DigiLocker requester credentials are configured.", utcnow_iso())


def verify_documents(provider: Optional[VerificationProvider], docs: list[ProcessedDocument]) -> list[VerificationResult]:
    if provider is None:
        return []
    return [provider.verify(d) for d in docs if d.status == "processed"]
