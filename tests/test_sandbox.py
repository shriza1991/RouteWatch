"""HTTP contract checks for the synthetic travel sandbox."""

import sqlite3
import pytest
from fastapi.testclient import TestClient
from sandbox import app as sandbox_module
from sandbox.app import app
from sandbox.management.api import app as management_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("sandbox.app.DB", tmp_path / "sandbox.db")
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def admin(client, monkeypatch):
    monkeypatch.setenv('SANDBOX_MANAGEMENT_TOKEN', 'sandbox-test-token')
    with TestClient(management_app) as management_client:
        yield management_client


def managed_post(admin, path):
    return admin.post(path, headers={'Authorization': 'Bearer sandbox-test-token'})


def headers(agency="agency-a"):
    return {"X-Agency": agency, "X-User": "synthetic-tester"}


def quote(client, agency="agency-a"):
    response = client.post("/api/v2/quotes", json={"route": "DEL-BOM"}, headers=headers(agency))
    assert response.status_code == 200
    return response.json()


def confirm(client, quote_id, fare, agency="agency-a"):
    return client.post(
        "/api/v2/bookings",
        json={"quote_id": quote_id, "traveler": "Synthetic traveler", "fare": fare},
        headers=headers(agency),
    )


def book(client, agency="agency-a", fare=None):
    offered = quote(client, agency)
    response = confirm(client, offered["quote_id"], offered["fare"] if fare is None else fare, agency)
    assert response.status_code == 200
    return offered, response.json()


def retrieve(client, booking_id, agency="agency-a", version="v2"):
    return client.get(f"/api/{version}/bookings/{booking_id}", headers=headers(agency))


def test_vulnerable_ownership_returns_foreign_booking_identity(client):
    _, own = book(client, "agency-a")
    _, foreign = book(client, "agency-b")
    response = retrieve(client, foreign["booking_id"], "agency-a")
    assert response.status_code == 200
    assert response.json()["booking_id"] == foreign["booking_id"]
    assert response.json()["agency_id"] == "agency-b"
    assert response.json()["booking_id"] != own["booking_id"]


def test_vulnerable_fare_is_persisted_on_booking(client):
    offered, booking = book(client, fare=1.0)
    stored = retrieve(client, booking["booking_id"])
    assert offered["fare"] == 120.0
    assert booking["fare"] == 1.0
    assert stored.status_code == 200
    assert stored.json()["booking_id"] == booking["booking_id"]
    assert stored.json()["fare"] == 1.0
    assert stored.json()["quote_fare"] == offered["fare"]


def test_fixed_ownership_blocks_foreign_but_preserves_both_own_bookings(client, admin):
    _, booking_a = book(client, "agency-a")
    _, booking_b = book(client, "agency-b")
    assert managed_post(admin, '/management/mode/fixed').status_code == 200
    assert retrieve(client, booking_b["booking_id"], "agency-a").status_code == 403
    assert retrieve(client, booking_a["booking_id"], "agency-b").status_code == 403
    for agency, booking in (("agency-a", booking_a), ("agency-b", booking_b)):
        response = retrieve(client, booking["booking_id"], agency)
        assert response.status_code == 200
        assert response.json()["booking_id"] == booking["booking_id"]
        assert response.json()["agency_id"] == agency


def test_fixed_fare_uses_quote_and_normal_booking_succeeds(client, admin):
    assert managed_post(admin, '/management/mode/fixed').status_code == 200
    offered, manipulated = book(client, fare=1.0)
    stored = retrieve(client, manipulated["booking_id"])
    assert manipulated["fare"] == offered["fare"]
    assert stored.status_code == 200
    assert stored.json()["fare"] == offered["fare"]
    assert stored.json()["quote_fare"] == offered["fare"]
    normal_quote, normal_booking = book(client, "agency-b")
    normal_stored = retrieve(client, normal_booking["booking_id"], "agency-b")
    assert normal_stored.status_code == 200
    assert normal_stored.json()["fare"] == normal_quote["fare"]
    assert normal_stored.json()["booking_id"] == normal_booking["booking_id"]


def test_legacy_endpoint_reachable_then_gone(client, admin):
    _, booking = book(client)
    old = retrieve(client, booking["booking_id"], version="v1")
    assert old.status_code == 200
    assert old.json()["booking_id"] == booking["booking_id"]
    managed_post(admin, '/management/mode/fixed')
    assert retrieve(client, booking["booking_id"], version="v1").status_code == 410
    assert retrieve(client, booking["booking_id"]).status_code == 200


@pytest.mark.parametrize("bad_headers", [{}, {"X-Agency": "unknown", "X-User": "synthetic-tester"}, {"X-Agency": "agency-a"}])
def test_identity_required_for_application_requests(client, bad_headers):
    assert client.post("/api/v2/quotes", json={"route": "DEL-BOM"}, headers=bad_headers).status_code == 401
    assert client.post("/api/v2/bookings", json={"quote_id": "missing", "traveler": "Synthetic", "fare": 1}, headers=bad_headers).status_code == 401
    assert client.get("/api/v2/bookings/missing", headers=bad_headers).status_code == 401


def test_missing_and_foreign_quotes_cannot_create_bookings(client):
    foreign_quote = quote(client, "agency-b")
    assert confirm(client, "missing-quote", 1.0).status_code == 404
    assert confirm(client, foreign_quote["quote_id"], 1.0).status_code == 404
    assert confirm(client, foreign_quote["quote_id"], foreign_quote["fare"], "agency-b").status_code == 200


def test_reset_clears_data_restores_vulnerable_mode_and_is_repeatable(client, admin):
    offered_a, booking_a = book(client, "agency-a")
    _, booking_b = book(client, "agency-b")
    unused_quote = quote(client, "agency-b")
    managed_post(admin, '/management/mode/fixed')
    for _ in range(2):
        response = managed_post(admin, '/management/reset')
        assert response.status_code == 200
        assert response.json() == {"ok": True, "mode": "vulnerable"}
        assert client.get("/sandbox/status").json()["mode"] == "vulnerable"
        for booking in (booking_a, booking_b):
            assert retrieve(client, booking["booking_id"], booking["agency_id"]).status_code == 404
        for quote_id, agency in ((offered_a["quote_id"], "agency-a"), (unused_quote["quote_id"], "agency-b")):
            assert confirm(client, quote_id, 1.0, agency).status_code == 404
    _, fresh_b = book(client, "agency-b")
    foreign = retrieve(client, fresh_b["booking_id"], "agency-a")
    assert foreign.status_code == 200
    assert foreign.json()["booking_id"] == fresh_b["booking_id"]
    assert foreign.json()["agency_id"] == "agency-b"


@pytest.mark.parametrize("initial_mode", ["vulnerable", "fixed"])
def test_unsupported_mode_does_not_change_existing_mode(client, admin, initial_mode):
    assert managed_post(admin, f'/management/mode/{initial_mode}').status_code == 200
    assert managed_post(admin, '/management/mode/unsupported').status_code == 400
    assert client.get("/sandbox/status").json()["mode"] == initial_mode


def flags(client):
    return client.get('/sandbox/status').json()['controls']


@pytest.mark.parametrize('control', sandbox_module.CONTROLS)
def test_each_control_changes_only_its_intended_behavior(client, control):
    offered_a, booking_a = book(client, 'agency-a', fare=1.0)
    _, booking_b = book(client, 'agency-b')
    sandbox_module.apply_control(control, True)
    assert flags(client) == {name: name == control for name in sandbox_module.CONTROLS}
    assert client.get('/sandbox/status').json()['mode'] == 'mixed'

    current_foreign = retrieve(client, booking_b['booking_id'], 'agency-a')
    legacy_foreign = retrieve(client, booking_b['booking_id'], 'agency-a', 'v1')
    assert current_foreign.status_code == (403 if control == 'enforce_booking_ownership' else 200)
    assert legacy_foreign.status_code == (410 if control == 'disable_legacy_booking' else 403 if control == 'enforce_booking_ownership' else 200)
    assert retrieve(client, booking_a['booking_id'], 'agency-a').status_code == 200
    if control != 'disable_legacy_booking':
        assert retrieve(client, booking_a['booking_id'], 'agency-a', 'v1').status_code == 200

    new_quote, new_booking = book(client, 'agency-a', fare=1.0)
    expected = new_quote['fare'] if control == 'validate_quote_fare' else 1.0
    assert new_booking['fare'] == expected
    assert retrieve(client, new_booking['booking_id']).json()['fare'] == expected
    assert offered_a['fare'] == 120.0


def test_controls_combine_repeat_and_reset_without_cross_effects(client, admin):
    _, booking_b = book(client, 'agency-b')
    sandbox_module.apply_control('enforce_booking_ownership', True)
    sandbox_module.apply_control('validate_quote_fare', True)
    sandbox_module.apply_control('validate_quote_fare', True)
    assert flags(client) == {'enforce_booking_ownership': True, 'validate_quote_fare': True, 'disable_legacy_booking': False}
    assert retrieve(client, booking_b['booking_id'], 'agency-a', 'v1').status_code == 403
    assert retrieve(client, booking_b['booking_id'], 'agency-b', 'v1').status_code == 200
    offered, confirmed = book(client, fare=1.0)
    assert confirmed['fare'] == offered['fare']

    sandbox_module.apply_control('disable_legacy_booking', True)
    assert client.get('/sandbox/status').json()['mode'] == 'fixed'
    assert retrieve(client, booking_b['booking_id'], 'agency-b', 'v1').status_code == 410
    sandbox_module.apply_control('validate_quote_fare', False)
    assert client.get('/sandbox/status').json()['mode'] == 'mixed'
    assert retrieve(client, booking_b['booking_id'], 'agency-a').status_code == 403
    assert retrieve(client, booking_b['booking_id'], 'agency-b', 'v1').status_code == 410
    assert book(client, fare=1.0)[1]['fare'] == 1.0

    managed_post(admin, '/management/reset')
    assert flags(client) == {name: False for name in sandbox_module.CONTROLS}
    assert client.get('/sandbox/status').json()['mode'] == 'vulnerable'
    assert retrieve(client, booking_b['booking_id'], 'agency-b').status_code == 404


def test_compatibility_modes_replace_mixed_state_atomically(client, admin):
    sandbox_module.apply_control('enforce_booking_ownership', True)
    assert client.get('/sandbox/status').json()['mode'] == 'mixed'
    response = managed_post(admin, '/management/mode/fixed')
    assert response.status_code == 200
    assert response.json() == {'mode': 'fixed', 'note': 'sandbox-only switch'}
    assert flags(client) == {name: True for name in sandbox_module.CONTROLS}
    response = managed_post(admin, '/management/mode/vulnerable')
    assert response.status_code == 200
    assert response.json() == {'mode': 'vulnerable', 'note': 'sandbox-only switch'}
    assert flags(client) == {name: False for name in sandbox_module.CONTROLS}


def test_controls_survive_app_restart_without_overwrite(client):
    sandbox_module.apply_control('enforce_booking_ownership', True)
    sandbox_module.apply_control('disable_legacy_booking', True)
    _, booking_b = book(client, 'agency-b')
    before = flags(client)
    with TestClient(app) as restarted:
        assert flags(restarted) == before
        assert restarted.get('/sandbox/status').json()['mode'] == 'mixed'
        assert retrieve(restarted, booking_b['booking_id'], 'agency-a').status_code == 403
        assert retrieve(restarted, booking_b['booking_id'], 'agency-b', 'v1').status_code == 410
        assert book(restarted, fare=1.0)[1]['fare'] == 1.0


@pytest.mark.parametrize('legacy_mode,expected', [('fixed', True), ('vulnerable', False)])
def test_legacy_mode_migrates_to_controls(tmp_path, monkeypatch, legacy_mode, expected):
    db = tmp_path / 'legacy.db'
    with sqlite3.connect(db) as connection:
        connection.execute('CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)')
        connection.execute('INSERT INTO settings VALUES (?,?)', ('mode', legacy_mode))
    monkeypatch.setattr('sandbox.app.DB', db)
    with TestClient(app) as migrated:
        assert flags(migrated) == {name: expected for name in sandbox_module.CONTROLS}
        assert migrated.get('/sandbox/status').json()['mode'] == legacy_mode
        with TestClient(app) as restarted:
            assert flags(restarted) == flags(migrated)
    with sqlite3.connect(db) as connection:
        assert connection.execute("SELECT value FROM settings WHERE key='mode'").fetchone() is None


def test_existing_controls_win_over_stale_legacy_mode(tmp_path, monkeypatch):
    db = tmp_path / 'partial.db'
    with sqlite3.connect(db) as connection:
        connection.execute('CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)')
        connection.execute("INSERT INTO settings VALUES ('mode','fixed')")
        connection.execute("INSERT INTO settings VALUES ('validate_quote_fare','0')")
    monkeypatch.setattr('sandbox.app.DB', db)
    with TestClient(app) as migrated:
        assert flags(migrated) == {'enforce_booking_ownership': True, 'validate_quote_fare': False, 'disable_legacy_booking': True}


@pytest.mark.parametrize('name,enabled', [('unknown', True), ('validate_quote_fare', 1), ('validate_quote_fare', 'true'), ('enforce_booking_ownership', None)])
def test_invalid_internal_control_input_does_not_mutate(client, name, enabled):
    sandbox_module.apply_control('disable_legacy_booking', True)
    before = flags(client)
    with pytest.raises(ValueError):
        sandbox_module.apply_control(name, enabled)
    assert flags(client) == before
    assert client.get('/sandbox/status').json()['mode'] == 'mixed'
