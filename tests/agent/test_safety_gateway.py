import httpx
import pytest

from agent.v1_domain import DemoCredentialResolver, RouteWatchDomainService, ScopeViolation
from discovery.runtime import FixtureInventoryService
from persistence import V1Store
from shared.v1 import RemediationProposal, TargetConfig


def target():
    return TargetConfig(
        id="local-sandbox",
        base_url="http://127.0.0.1:8000",
        allowed_origins=["http://127.0.0.1:8000"],
        accounts=[
            {"id": "agency-a", "agency_id": "agency-a", "user_id": "a", "credential_ref": "server:agency-a"},
            {"id": "agency-b", "agency_id": "agency-b", "user_id": "b", "credential_ref": "server:agency-b"},
        ],
        max_requests=30,
        timeout_seconds=2,
        rate_per_minute=30,
    )


def test_scanner_rejects_non_api_and_management_paths_before_network(tmp_path):
    store = V1Store(tmp_path / "safety.db")
    scan = __import__("shared.v1", fromlist=["ScanRun"]).ScanRun(target_id="local-sandbox", state="running")
    store.scans.save(scan)

    def unexpected_request(_request):
        raise AssertionError("out-of-scope path reached the network transport")

    domain = RouteWatchDomainService(
        store, FixtureInventoryService(), transport=httpx.MockTransport(unexpected_request)
    )
    budget = {"used": 0, "max": 30, "rate": 30, "recent": []}

    with httpx.Client(transport=httpx.MockTransport(unexpected_request), trust_env=False) as client:
        for path in ("/sandbox/reset", "/management/actions", "//example.org/api/x", "/api/%2e%2e/management"):
            with pytest.raises(ScopeViolation):
                domain._request(
                    client=client, target=target(), scan_id=scan.id, method="POST",
                    path=path, body={}, purpose="scope_test", budget=budget,
                )
    assert budget["used"] == 0
    assert store.audit.list(parent_id=scan.id) == []


def test_scan_target_is_bound_to_the_two_server_side_demo_accounts(tmp_path):
    store = V1Store(tmp_path / "target.db")
    domain = RouteWatchDomainService(store, FixtureInventoryService())
    config = target().model_copy(update={
        "accounts": [target().accounts[0], target().accounts[0]],
    })
    with pytest.raises(ScopeViolation):
        domain.start_scan(config, DemoCredentialResolver())
