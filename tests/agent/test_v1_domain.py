import json
from pathlib import Path

import httpx
import pytest

from agent.v1_domain import DemoCredentialResolver, RouteWatchDomainService
from discovery.runtime import FixtureInventoryService
from persistence import V1Store
from shared.v1 import TargetConfig


class SandboxState:
    def __init__(self):
        self.enforce_ownership = False
        self.enforce_fare = False
        self.quotes = {}
        self.bookings = {}
        self.sequence = 0

    def response(self, request):
        path = request.url.path
        agency = request.headers.get("X-Agency", "")
        if path == "/ui/traffic-recording":
            return httpx.Response(200, json={
                "schema_version": "1.0", "synthetic": True,
                "provenance": "pytest synthetic sandbox",
                "observation_window": {
                    "start": "2026-11-13T10:00:00Z",
                    "end": "2026-11-13T10:01:00Z",
                },
                "requests": [
                    {"method": "POST", "path": "/api/v2/quotes", "body": {"route": "DEL-BOM"}},
                    {"method": "POST", "path": "/api/v2/bookings", "body": {"route": "DEL-BOM"}},
                    {"method": "GET", "path": "/api/v2/bookings/{id}"},
                ],
            })
        if path == "/api/v2/quotes" and request.method == "POST":
            self.sequence += 1
            quote_id = f"q-{self.sequence}"
            quote = {"quote_id": quote_id, "route": "DEL-BOM", "fare": 120.0}
            self.quotes[quote_id] = {"agency_id": agency, **quote}
            return httpx.Response(200, json=quote)
        if path == "/api/v2/bookings" and request.method == "POST":
            data = json.loads(request.content)
            quote = self.quotes.get(data.get("quote_id"))
            if not quote or quote["agency_id"] != agency:
                return httpx.Response(404, json={"detail": "quote not found"})
            self.sequence += 1
            booking_id = f"b-{self.sequence}"
            fare = quote["fare"] if self.enforce_fare else float(data.get("fare", 0))
            booking = {
                "booking_id": booking_id, "agency_id": agency,
                "traveler": data.get("traveler", "Synthetic"),
                "route": quote["route"], "fare": fare, "quote_fare": quote["fare"],
            }
            self.bookings[booking_id] = booking
            return httpx.Response(200, json=booking)
        if path.startswith("/api/v2/bookings/") or path.startswith("/api/v1/bookings/"):
            booking_id = path.rsplit("/", 1)[-1]
            booking = self.bookings.get(booking_id)
            if not booking:
                return httpx.Response(404, json={"detail": "booking not found"})
            if self.enforce_ownership and booking["agency_id"] != agency:
                return httpx.Response(403, json={"detail": "booking belongs to another agency"})
            return httpx.Response(200, json=booking)
        return httpx.Response(404, json={"detail": "not found"})


def target():
    return TargetConfig(
        id="local-sandbox",
        base_url="http://127.0.0.1:8000",
        allowed_origins=["http://127.0.0.1:8000"],
        accounts=[
            {"id": "agency-a", "agency_id": "agency-a", "user_id": "a",
             "credential_ref": "server:agency-a"},
            {"id": "agency-b", "agency_id": "agency-b", "user_id": "b",
             "credential_ref": "server:agency-b"},
        ],
        max_requests=30,
        timeout_seconds=3,
        rate_per_minute=30,
    )


def service(tmp_path, state):
    store = V1Store(tmp_path / "v1-domain.db")
    inventory = FixtureInventoryService()
    domain = RouteWatchDomainService(store, inventory, transport=httpx.MockTransport(state.response))
    return store, domain


def run_scan(store, domain):
    config = target()
    scan = domain.start_scan(config, DemoCredentialResolver())
    store.scans.save(scan)
    store.save_scan_config(scan.id, config)
    domain.run_scan(scan.id, config, DemoCredentialResolver())
    return store.scans.get(scan.id)


def test_v1_scan_detects_idor_and_persisted_fare_tampering(tmp_path):
    state = SandboxState()
    store, domain = service(tmp_path, state)
    scan = run_scan(store, domain)

    assert scan.state == "completed"
    assert scan.request_count <= 30
    findings = store.findings.list(parent_id=scan.id)
    assert {finding.rule_id for finding in findings} == {"cross_agency_access", "fare_tampering"}
    assert all(finding.minimal_proof.request for finding in findings)
    assert all(finding.minimal_proof.legitimate_control for finding in findings)
    assert store.audit.list(parent_id=scan.id)
    snapshots = store.inventory_snapshots.list(parent_id="local-sandbox")
    assert snapshots and any(
        endpoint.labels == {"zombie"}
        for endpoint in snapshots[-1].endpoints
        if endpoint.normalized_path == "/api/v1/bookings/{id}"
    )
    assert any(
        endpoint.labels == {"active", "shadow"}
        for endpoint in snapshots[-1].endpoints
        if endpoint.normalized_path == "/api/ui/preferences"
    )


def test_independent_retest_requires_exploit_block_and_legitimate_success(tmp_path):
    state = SandboxState()
    store, domain = service(tmp_path, state)
    scan = run_scan(store, domain)
    findings = {item.rule_id: item for item in store.findings.list(parent_id=scan.id)}

    state.enforce_ownership = True
    state.enforce_fare = True

    idor_retest = domain.retest(findings["cross_agency_access"])
    fare_retest = domain.retest(findings["fare_tampering"])

    assert idor_retest.outcome == "resolved"
    assert idor_retest.exploit_outcome == "passed"
    assert idor_retest.legitimate_flow_outcome == "passed"
    assert fare_retest.outcome == "resolved"
    assert fare_retest.exploit_outcome == "passed"
    assert fare_retest.legitimate_flow_outcome == "passed"
    assert store.findings.get(findings["cross_agency_access"].id).state == "resolved"
    assert store.findings.get(findings["fare_tampering"].id).state == "resolved"
    assert store.retests.get(idor_retest.id) is None  # Transport persists the returned retest atomically.


def test_scope_policy_rejects_non_sandbox_target(tmp_path):
    state = SandboxState()
    store, domain = service(tmp_path, state)
    outside = target().model_copy(update={
        "base_url": "https://example.org",
        "allowed_origins": ["https://example.org"],
    })
    with pytest.raises(RuntimeError):
        domain.start_scan(outside, DemoCredentialResolver())


def test_kill_switch_stops_scan_without_marking_it_completed(tmp_path, monkeypatch):
    state = SandboxState()
    store, domain = service(tmp_path, state)
    config = target()
    scan = domain.start_scan(config, DemoCredentialResolver())
    store.scans.save(scan)
    store.save_scan_config(scan.id, config)
    monkeypatch.setenv("ROUTEWATCH_KILL_SWITCH", "true")
    domain.run_scan(scan.id, config, DemoCredentialResolver())
    result = store.scans.get(scan.id)
    assert result.state == "cancelled"
    assert result.state != "completed"
