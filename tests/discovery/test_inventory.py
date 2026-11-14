import json
from pathlib import Path
import pytest
from discovery.changes import compare_inventory, recommended_test_families
from discovery.inventory import build_inventory, extract_javascript_routes, normalize_path, parse_har
from discovery.runtime import FixtureInventoryService

FIXTURES = Path(__file__).resolve().parents[2] / "sandbox" / "fixtures"
def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))
def inventory(**kwargs):
    values = {"recording": fixture("journey-recording.v1.json"),
              "reference": fixture("reference-inventory.v1.json"),
              "history": fixture("historical-traffic.v1.json"),
              "archived": fixture("archived-routes.v1.json")}
    values.update(kwargs)
    return build_inventory(**values)

def test_normalizes_ids_without_merging_different_resources():
    assert normalize_path("get", "/api/v2/bookings/123?expand=traveller") == ("GET", "/api/v2/bookings/{id}")
    assert normalize_path("GET", "/api/v2/quotes/123") == ("GET", "/api/v2/quotes/{id}")
    assert normalize_path("GET", "/api/v2/suppliers/123/bookings/456") == ("GET", "/api/v2/suppliers/{id}/bookings/{id}")

@pytest.mark.parametrize("path", ["https://evil.example/api/bookings/1", "//evil.example/x",
                                  "/api/%2e%2e/admin", "/api/%5cadmin"])
def test_rejects_unsafe_route_observations(path):
    with pytest.raises(ValueError): normalize_path("GET", path)

def test_har_import_is_redacted_and_normalized():
    har = {"log": {"entries": [{"startedDateTime": "2026-11-13T10:00:00Z",
        "request": {"method": "GET", "url": "https://sandbox.example/api/bookings/abc?token=secret",
                    "headers": [{"name": "Authorization", "value": "Bearer secret"}]},
        "response": {"status": 200}}]}}
    rows = parse_har(har, account_context_id="agency-a")
    assert rows == [{"method": "GET", "path": "/api/bookings/{id}",
        "timestamp": "2026-11-13T10:00:00+00:00", "account_context_id": "agency-a",
        "source": "har", "status": 200}]
    assert "secret" not in json.dumps(rows)

def test_extracts_javascript_routes_without_claiming_reachability():
    routes = extract_javascript_routes('fetch("/api/v2/bookings/" + bookingId); const x = "/api/v2/refunds/{id}";')
    assert routes == {"/api/v2/bookings/{id}", "/api/v2/refunds/{id}"}

def test_fixture_inventory_preserves_active_shadow_and_unknown_zombie_candidate():
    rows = inventory()
    by_key = {(item.method, item.normalized_path): item for item in rows}
    assert by_key[("POST", "/api/v2/quotes")].labels == {"active"}
    assert by_key[("GET", "/api/ui/preferences")].labels == {"active", "shadow"}
    archived = by_key[("GET", "/api/v1/bookings/{id}")]
    assert archived.labels == {"unknown"} and archived.reachability == "unprobed"
    assert all(e.synthetic for endpoint in rows for e in endpoint.evidence)

def test_zombie_requires_complete_zero_history_and_positive_reachability():
    rows = inventory(reachability={("GET", "/api/v1/bookings/{id}"): "reachable"})
    archived = next(item for item in rows if item.normalized_path == "/api/v1/bookings/{id}")
    assert archived.labels == {"zombie"}

def test_incomplete_history_never_becomes_zombie():
    history = fixture("historical-traffic.v1.json")
    item = next(x for x in history["endpoints"] if x["path"] == "/api/v1/bookings/{id}")
    item["coverage"], item["legitimate_requests_in_window"] = "incomplete", None
    rows = inventory(history=history, reachability={("GET", "/api/v1/bookings/{id}"): "reachable"})
    archived = next(item for item in rows if item.normalized_path == "/api/v1/bookings/{id}")
    assert archived.labels == {"unknown"}

def test_incomplete_history_with_zero_is_rejected():
    history = fixture("historical-traffic.v1.json")
    item = next(x for x in history["endpoints"] if x["path"] == "/api/v1/bookings/{id}")
    item["coverage"] = "incomplete"
    with pytest.raises(ValueError): inventory(history=history)

def test_fixture_service_is_read_only_and_target_scoped():
    service = FixtureInventoryService(FIXTURES)
    assert service.list_endpoints("local-sandbox")
    with pytest.raises(ValueError): service.list_endpoints("arbitrary-host")

def test_change_planner_prioritizes_new_refund_endpoint():
    before = inventory()
    after = before + [type(before[0])(method="POST", normalized_path="/api/v2/refunds",
        labels={"active", "shadow"}, reachability="unprobed", evidence=[])]
    changes = compare_inventory(before, after)
    refund = next(item for item in changes if item.path == "/api/v2/refunds")
    assert refund.change == "added" and refund.risk_score >= 80
    assert "workflow_state_transition" in recommended_test_families(refund)

def test_unchanged_inventory_has_no_change_events():
    before = inventory()
    assert compare_inventory(before, before) == []
