"""Deterministic change intelligence and safe test-plan prioritization."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable
from shared.v1 import Endpoint

@dataclass(frozen=True)
class EndpointChange:
    method: str
    path: str
    change: str
    risk_score: int
    reasons: tuple[str, ...]

_BUSINESS_TERMS = (
    "booking", "refund", "payment", "cancel", "traveller", "traveler",
    "supplier", "agency", "invoice", "quote", "coupon",
)

def _identity(endpoint: Endpoint) -> tuple[str, str]:
    return endpoint.method, endpoint.normalized_path

def compare_inventory(previous: Iterable[Endpoint], current: Iterable[Endpoint]) -> list[EndpointChange]:
    """Compare normalized inventories; no change is inferred from missing data."""
    old = {_identity(item): item for item in previous}
    new = {_identity(item): item for item in current}
    changes: list[EndpointChange] = []
    for key in sorted(new.keys() - old.keys()):
        endpoint = new[key]
        path = endpoint.normalized_path.lower()
        reasons = ["new endpoint observed"]
        score = 35
        if any(term in path for term in _BUSINESS_TERMS):
            reasons.append("travel business workflow endpoint")
            score += 30
        if endpoint.method in {"POST", "PUT", "PATCH", "DELETE"}:
            reasons.append("state-changing HTTP method")
            score += 20
        if "shadow" in endpoint.labels:
            reasons.append("not present in supplied reference inventory")
            score += 15
        changes.append(EndpointChange(*key, "added", min(score, 100), tuple(reasons)))
    for key in sorted(old.keys() - new.keys()):
        changes.append(EndpointChange(*key, "removed", 20, ("endpoint absent from current snapshot",)))
    for key in sorted(old.keys() & new.keys()):
        before, after = old[key], new[key]
        if (before.reachability, tuple(sorted(before.labels))) != (after.reachability, tuple(sorted(after.labels))):
            changes.append(EndpointChange(*key, "metadata_changed", 25,
                                          ("endpoint classification or reachability changed",)))
    return sorted(changes, key=lambda item: (-item.risk_score, item.method, item.path))

def recommended_test_families(change: EndpointChange) -> tuple[str, ...]:
    """Map endpoint changes to a bounded, deterministic test catalogue."""
    path = change.path.lower()
    families: list[str] = []
    if any(term in path for term in ("booking", "traveller", "traveler", "invoice")):
        families.append("object_level_authorization")
    if any(term in path for term in ("quote", "fare", "payment", "refund", "coupon")):
        families.append("price_and_transaction_integrity")
    if any(term in path for term in ("cancel", "refund", "payment", "booking")):
        families.append("workflow_state_transition")
    if change.change == "added" and not families:
        families.append("authenticated_access_boundary")
    return tuple(dict.fromkeys(families))
