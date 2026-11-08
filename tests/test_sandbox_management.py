import sqlite3

import pytest
from fastapi.testclient import TestClient

from sandbox import app as travel
from sandbox.management import api as management


TOKEN = 'local-test-secret'


@pytest.fixture
def services(tmp_path, monkeypatch):
    monkeypatch.setattr(travel, 'DB', tmp_path / 'sandbox.db')
    monkeypatch.setenv('SANDBOX_MANAGEMENT_TOKEN', TOKEN)
    with TestClient(travel.app) as user, TestClient(management.app) as admin:
        yield user, admin


def auth(token=TOKEN):
    return {'Authorization': f'Bearer {token}'}


def action(admin, key, nonce):
    return admin.post('/management/actions', json={'action_key': key, 'idempotency_key': nonce}, headers=auth())


def reset(admin):
    return admin.post('/management/reset', headers=auth())


def mode(admin, value):
    return admin.post(f'/management/mode/{value}', headers=auth())


def booking(user, agency, fare=120):
    headers = {'X-Agency': agency, 'X-User': 'tester'}
    quote = user.post('/api/v2/quotes', json={'route': 'DEL-BOM'}, headers=headers).json()
    confirmed = user.post('/api/v2/bookings', json={'quote_id': quote['quote_id'], 'traveler': 'Synthetic', 'fare': fare}, headers=headers)
    assert confirmed.status_code == 200
    return quote, confirmed.json()


def read(user, booking_id, agency='agency-a', version='v2'):
    return user.get(f'/api/{version}/bookings/{booking_id}', headers={'X-Agency': agency, 'X-User': 'tester'})


def test_missing_token_fails_startup(tmp_path, monkeypatch):
    monkeypatch.setattr(travel, 'DB', tmp_path / 'sandbox.db')
    monkeypatch.delenv('SANDBOX_MANAGEMENT_TOKEN', raising=False)
    with pytest.raises(RuntimeError, match='SANDBOX_MANAGEMENT_TOKEN'):
        with TestClient(management.app):
            pass
    monkeypatch.setenv('SANDBOX_MANAGEMENT_TOKEN', '   ')
    with pytest.raises(RuntimeError, match='SANDBOX_MANAGEMENT_TOKEN'):
        with TestClient(management.app):
            pass


def test_authentication_and_no_secret_exposure(services):
    user, admin = services
    body = {'action_key': 'enforce_booking_ownership', 'idempotency_key': 'auth-1'}
    for headers in ({}, auth('wrong')):
        response = admin.post('/management/actions', json=body, headers=headers)
        assert response.status_code == 401
        assert TOKEN not in response.text
    assert user.get('/management/actions').status_code == 404
    assert user.post('/management/actions', json=body, headers=auth()).status_code == 404
    assert admin.get('/openapi.json', headers=auth()).status_code == 404
    assert admin.get('/docs', headers=auth()).status_code == 404
    assert travel.controls() == {name: False for name in travel.CONTROLS}
    assert TOKEN not in user.get('/sandbox/status').text
    assert TOKEN not in action(admin, 'enforce_booking_ownership', 'auth-2').text
    for path in ('/management/reset', '/management/mode/fixed', '/management/mode/vulnerable'):
        for credentials in ({}, auth('wrong')):
            denied = admin.post(path, headers=credentials)
            assert denied.status_code == 401
            assert TOKEN not in denied.text


@pytest.mark.parametrize('key', travel.CONTROLS)
def test_each_action_changes_only_its_http_behavior(services, key):
    user, admin = services
    _, foreign = booking(user, 'agency-b')
    response = action(admin, key, f'key-{key}')
    assert response.status_code == 200
    assert response.json()['state'] == 'applied'
    assert response.json()['execution_id']
    assert TOKEN not in response.text
    assert travel.controls() == {name: name == key for name in travel.CONTROLS}
    assert read(user, foreign['booking_id']).status_code == (403 if key == 'enforce_booking_ownership' else 200)
    assert read(user, foreign['booking_id'], 'agency-b', 'v1').status_code == (410 if key == 'disable_legacy_booking' else 200)
    assert read(user, foreign['booking_id'], 'agency-b').status_code == 200
    quote, confirmed = booking(user, 'agency-a', fare=1)
    assert read(user, confirmed['booking_id']).json()['fare'] == (quote['fare'] if key == 'validate_quote_fare' else 1)


def test_duplicate_conflict_and_restart_persist(services):
    user, admin = services
    first = action(admin, 'enforce_booking_ownership', 'stable-key').json()
    duplicate = action(admin, 'enforce_booking_ownership', 'stable-key')
    assert duplicate.status_code == 200
    assert duplicate.json() == first
    conflict = action(admin, 'validate_quote_fare', 'stable-key')
    assert conflict.status_code == 409
    assert travel.controls()['validate_quote_fare'] is False
    with TestClient(management.app) as restarted:
        assert action(restarted, 'enforce_booking_ownership', 'stable-key').json() == first
        assert action(restarted, 'validate_quote_fare', 'stable-key').status_code == 409
    assert travel.controls()['enforce_booking_ownership'] is True


def test_unsupported_and_malformed_do_not_change_controls(services):
    _, admin = services
    unsupported = action(admin, 'run-arbitrary-code', 'unsupported-1')
    assert unsupported.status_code == 200
    assert unsupported.json()['state'] == 'unsupported'
    assert action(admin, 'run-arbitrary-code', 'unsupported-1').json() == unsupported.json()
    for body in ({'action_key': 'validate_quote_fare'}, {'action_key': '', 'idempotency_key': 'x'},
                 {'action_key': 7, 'idempotency_key': 'x'},
                 {'action_key': 'validate_quote_fare', 'idempotency_key': ' '},
                 {'action_key': 'validate_quote_fare', 'idempotency_key': 'x', 'enabled': False}):
        assert admin.post('/management/actions', json=body, headers=auth()).status_code == 422
    assert travel.controls() == {name: False for name in travel.CONTROLS}


def test_execution_failure_rolls_back_control_and_record(services, monkeypatch):
    _, admin = services
    original = travel.apply_control

    def fail_after_update(name, enabled, *, connection=None):
        original(name, enabled, connection=connection)
        raise RuntimeError('private simulated failure')

    monkeypatch.setattr(travel, 'apply_control', fail_after_update)
    failed = action(admin, 'validate_quote_fare', 'retry-key')
    assert failed.status_code == 500
    assert failed.json()['state'] == 'failed'
    assert 'private simulated failure' not in failed.text
    assert travel.controls()['validate_quote_fare'] is False
    monkeypatch.setattr(travel, 'apply_control', original)
    retry = action(admin, 'validate_quote_fare', 'retry-key')
    assert retry.status_code == 200
    assert retry.json()['state'] == 'applied'


def test_reset_allows_fresh_cycle_with_same_key(services):
    user, admin = services
    first = action(admin, 'disable_legacy_booking', 'demo-key').json()
    assert reset(admin).json() == {'ok': True, 'mode': 'vulnerable'}
    assert travel.controls()['disable_legacy_booking'] is False
    second = action(admin, 'disable_legacy_booking', 'demo-key').json()
    assert second['state'] == 'applied'
    assert second['execution_id'] != first['execution_id']
    assert travel.controls()['disable_legacy_booking'] is True


def test_travel_mutation_routes_are_absent_and_cannot_change_state(services):
    user, admin = services
    _, existing = booking(user, 'agency-a')
    assert mode(admin, 'fixed').status_code == 200
    before = user.get('/sandbox/status').json()
    for path in ('/sandbox/reset', '/sandbox/mode/vulnerable', '/sandbox/mode/fixed',
                 '/management/reset', '/management/mode/vulnerable', '/management/actions'):
        assert user.post(path, headers=auth()).status_code in (404, 405)
    assert user.get('/sandbox/status').json() == before
    assert read(user, existing['booking_id']).status_code == 200


def test_management_reset_and_modes_preserve_data_semantics(services):
    user, admin = services
    offered, existing = booking(user, 'agency-b')
    assert mode(admin, 'fixed').json()['mode'] == 'fixed'
    assert all(travel.controls().values())
    assert mode(admin, 'vulnerable').json()['mode'] == 'vulnerable'
    assert not any(travel.controls().values())
    assert read(user, existing['booking_id'], 'agency-a').status_code == 200
    assert reset(admin).json() == {'ok': True, 'mode': 'vulnerable'}
    assert read(user, existing['booking_id'], 'agency-b').status_code == 404
    headers = {'X-Agency': 'agency-b', 'X-User': 'tester'}
    assert user.post('/api/v2/bookings', json={'quote_id': offered['quote_id'], 'traveler': 'Synthetic', 'fare': 1}, headers=headers).status_code == 404
    assert not any(travel.controls().values())
    assert reset(admin).status_code == 200


def test_invalid_mode_preserves_data_controls_and_execution_records(services):
    user, admin = services
    _, existing = booking(user, 'agency-b')
    result = action(admin, 'enforce_booking_ownership', 'retained-key').json()
    before = travel.controls()
    invalid = mode(admin, 'unsupported')
    assert invalid.status_code == 400
    assert travel.controls() == before
    assert read(user, existing['booking_id'], 'agency-b').status_code == 200
    assert action(admin, 'enforce_booking_ownership', 'retained-key').json() == result


def test_manual_vulnerable_mode_invalidates_stale_action_replay(services):
    user, admin = services
    _, foreign = booking(user, 'agency-b')
    first = action(admin, 'enforce_booking_ownership', 'replay-key').json()
    assert read(user, foreign['booking_id'], 'agency-a').status_code == 403
    assert mode(admin, 'vulnerable').status_code == 200
    assert read(user, foreign['booking_id'], 'agency-a').status_code == 200
    second = action(admin, 'enforce_booking_ownership', 'replay-key').json()
    assert second['execution_id'] != first['execution_id']
    assert second['state'] == 'applied'
    assert read(user, foreign['booking_id'], 'agency-a').status_code == 403


def test_reset_then_new_scan_data_and_remediation(services):
    user, admin = services
    action(admin, 'validate_quote_fare', 'fresh-key')
    assert reset(admin).status_code == 200
    quote, fresh = booking(user, 'agency-a', fare=1)
    assert fresh['fare'] == 1
    assert action(admin, 'validate_quote_fare', 'fresh-key').json()['state'] == 'applied'
    new_quote, corrected = booking(user, 'agency-a', fare=1)
    assert corrected['fare'] == new_quote['fare']
    assert read(user, corrected['booking_id']).json()['fare'] == new_quote['fare']
