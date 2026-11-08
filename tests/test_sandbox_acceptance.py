"""Target-only HTTP acceptance: proof, predefined control, independent retest."""

import json

import pytest
from fastapi.testclient import TestClient

from sandbox import app as travel
from sandbox.management.api import app as management_app


TOKEN = 'acceptance-local-token'


@pytest.fixture
def services(tmp_path, monkeypatch):
    monkeypatch.setattr(travel, 'DB', tmp_path / 'sandbox.db')
    monkeypatch.setenv('SANDBOX_MANAGEMENT_TOKEN', TOKEN)
    with TestClient(travel.app) as user, TestClient(management_app) as admin:
        yield user, admin


def headers(agency):
    return {'X-Agency': agency, 'X-User': 'synthetic-acceptance'}


def book(user, agency, submitted_fare=None):
    quoted = user.post('/api/v2/quotes', json={'route': 'DEL-BOM'}, headers=headers(agency))
    assert quoted.status_code == 200
    quote = quoted.json()
    fare = quote['fare'] if submitted_fare is None else submitted_fare
    confirmed = user.post('/api/v2/bookings', json={
        'quote_id': quote['quote_id'], 'traveler': 'Synthetic traveler', 'fare': fare,
    }, headers=headers(agency))
    assert confirmed.status_code == 200
    return quote, confirmed.json()


def read(user, booking_id, agency, version='v2'):
    return user.get(f'/api/{version}/bookings/{booking_id}', headers=headers(agency))


def action(admin, key, nonce):
    return admin.post('/management/actions', headers={'Authorization': f'Bearer {TOKEN}'},
                      json={'action_key': key, 'idempotency_key': nonce})


def flags(user):
    response = user.get('/sandbox/status')
    assert response.status_code == 200
    return response.json()['controls']


def test_ownership_proof_control_and_independent_retest(services):
    user, admin = services
    _, own_a = book(user, 'agency-a')
    _, own_b = book(user, 'agency-b')
    path = f"/api/v2/bookings/{own_b['booking_id']}"
    before = user.get(path, headers=headers('agency-a'))
    assert before.status_code == 200
    assert before.json()['booking_id'] == own_b['booking_id']
    assert before.json()['agency_id'] == 'agency-b'

    applied = action(admin, 'enforce_booking_ownership', 'ownership-cycle-1')
    assert applied.status_code == 200 and applied.json()['state'] == 'applied'
    assert user.get(path, headers=headers('agency-a')).status_code == 403
    for agency, own in (('agency-a', own_a), ('agency-b', own_b)):
        response = read(user, own['booking_id'], agency)
        assert response.status_code == 200
        assert response.json()['booking_id'] == own['booking_id']
        assert response.json()['agency_id'] == agency
    assert flags(user) == {'enforce_booking_ownership': True, 'validate_quote_fare': False, 'disable_legacy_booking': False}


def test_fare_proof_control_and_independent_retest(services):
    user, admin = services
    old_quote, old_booking = book(user, 'agency-a', submitted_fare=1)
    persisted = read(user, old_booking['booking_id'], 'agency-a')
    assert persisted.status_code == 200
    assert persisted.json()['fare'] == 1
    assert persisted.json()['quote_fare'] == old_quote['fare'] == 120

    applied = action(admin, 'validate_quote_fare', 'fare-cycle-1')
    assert applied.status_code == 200 and applied.json()['state'] == 'applied'
    new_quote, corrected = book(user, 'agency-a', submitted_fare=1)
    assert corrected['fare'] == new_quote['fare']
    assert read(user, corrected['booking_id'], 'agency-a').json()['fare'] == new_quote['fare']
    normal_quote, normal = book(user, 'agency-b')
    normal_read = read(user, normal['booking_id'], 'agency-b')
    assert normal_read.status_code == 200
    assert normal_read.json()['fare'] == normal_quote['fare']
    assert flags(user) == {'enforce_booking_ownership': False, 'validate_quote_fare': True, 'disable_legacy_booking': False}


def test_retired_route_proof_control_and_current_route_retest(services):
    user, admin = services
    _, own = book(user, 'agency-a')
    legacy = read(user, own['booking_id'], 'agency-a', 'v1')
    assert legacy.status_code == 200
    assert legacy.json()['booking_id'] == own['booking_id']
    applied = action(admin, 'disable_legacy_booking', 'legacy-cycle-1')
    assert applied.status_code == 200 and applied.json()['state'] == 'applied'
    assert read(user, own['booking_id'], 'agency-a', 'v1').status_code == 410
    current = read(user, own['booking_id'], 'agency-a')
    assert current.status_code == 200
    assert current.json()['booking_id'] == own['booking_id']
    assert flags(user) == {'enforce_booking_ownership': False, 'validate_quote_fare': False, 'disable_legacy_booking': True}


def test_sequence_auth_idempotency_reset_and_new_cycle(services):
    user, admin = services
    _, own_b = book(user, 'agency-b')
    for key in travel.CONTROLS:
        body = {'action_key': key, 'idempotency_key': f'sequence-{key}'}
        for credential in ({}, {'Authorization': 'Bearer incorrect'}):
            assert admin.post('/management/actions', headers=credential, json=body).status_code == 401
            assert flags(user)[key] is False
        applied = action(admin, key, body['idempotency_key'])
        assert applied.status_code == 200 and applied.json()['state'] == 'applied'
        before = flags(user)
        assert action(admin, key, body['idempotency_key']).json() == applied.json()
        assert flags(user) == before
    assert all(flags(user).values())
    assert read(user, own_b['booking_id'], 'agency-a').status_code == 403
    assert read(user, own_b['booking_id'], 'agency-b', 'v1').status_code == 410
    assert book(user, 'agency-a', submitted_fare=1)[1]['fare'] == 120

    reset = admin.post('/management/reset', headers={'Authorization': f'Bearer {TOKEN}'})
    assert reset.status_code == 200 and reset.json() == {'ok': True, 'mode': 'vulnerable'}
    assert not any(flags(user).values())
    _, fresh_b = book(user, 'agency-b')
    assert read(user, fresh_b['booking_id'], 'agency-a').json()['agency_id'] == 'agency-b'
    assert read(user, fresh_b['booking_id'], 'agency-b', 'v1').status_code == 200
    assert book(user, 'agency-a', submitted_fare=1)[1]['fare'] == 1
    reapplied = action(admin, 'enforce_booking_ownership', 'sequence-enforce_booking_ownership')
    assert reapplied.status_code == 200 and reapplied.json()['state'] == 'applied'
    assert read(user, fresh_b['booking_id'], 'agency-a').status_code == 403


def test_journey_recording_contains_no_management_operations(services):
    user, admin = services
    assert action(admin, 'enforce_booking_ownership', 'recording-separation').status_code == 200
    response = user.get('/ui/traffic-recording')
    assert response.status_code == 200
    serialized = json.dumps(response.json()).lower()
    assert '/management/' not in serialized
    assert '/sandbox/reset' not in serialized
    assert TOKEN.lower() not in serialized
    assert all(event['path'].startswith('/api/') for event in response.json()['requests'])
