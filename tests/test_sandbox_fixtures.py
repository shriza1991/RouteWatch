import copy
import json

import pytest
from fastapi.testclient import TestClient

from sandbox import app as travel
from sandbox.fixtures.record import record
from sandbox.fixtures.validate import HERE, load_recording, validate_history, validate_recording
from sandbox.management.api import app as management_app


@pytest.fixture
def services(tmp_path, monkeypatch):
    monkeypatch.setattr(travel, 'DB', tmp_path / 'sandbox.db')
    monkeypatch.setenv('SANDBOX_MANAGEMENT_TOKEN', 'fixture-test-secret')
    with TestClient(travel.app) as user, TestClient(management_app) as admin:
        yield user, admin


def management_post(admin, path):
    return admin.post(path, headers={'Authorization': 'Bearer fixture-test-secret'})


def test_recorded_fixture_is_valid_and_served_with_agent_compatibility(services):
    user, _ = services
    saved = load_recording()
    response = user.get('/ui/traffic-recording')
    assert response.status_code == 200
    assert response.json() == saved
    assert saved['synthetic'] is True
    assert saved['format'] == 'routewatch-journey-recording-v1'
    assert len(saved['requests']) == 7
    assert saved['requests'][0]['body']['route'] == 'DEL-BOM'
    assert saved['requests'][1]['body']['quote_id'] == '{quote:agency-a}'
    assert saved['requests'][2]['path'] == '/api/v2/bookings/{id}'
    assert saved['requests'][4]['body']['quote_id'] == '{quote:agency-b}'
    assert all('status' in item and 'method' in item and 'source' in item for item in saved['requests'])


@pytest.mark.parametrize('mode', ['vulnerable', 'fixed'])
def test_recorder_runs_real_normal_http_journeys_without_changing_controls(services, mode):
    user, admin = services
    assert management_post(admin, '/management/reset').status_code == 200
    assert management_post(admin, f'/management/mode/{mode}').status_code == 200
    before = user.get('/sandbox/status').json()['controls']
    captured = record(user, 'http://testserver')
    validate_recording(captured)
    assert user.get('/sandbox/status').json()['controls'] == before
    assert [r['status'] for r in captured['requests']] == [200] * 7
    assert captured['requests'][2]['response']['agency_id'] == 'agency-a'
    assert captured['requests'][5]['response']['agency_id'] == 'agency-b'
    assert captured['requests'][6]['response']['currency'] == 'INR'
    assert user.post('/sandbox/reset').status_code in (404, 405)


def test_repeat_generation_has_same_normalized_journey_after_explicit_reset(services):
    user, admin = services
    first = record(user, 'http://testserver')
    assert management_post(admin, '/management/reset').status_code == 200
    second = record(user, 'http://testserver')
    def stable(data):
        events = copy.deepcopy(data['requests'])
        for event in events:
            event.pop('timestamp')
            event['response'].pop('created_at', None)
        return events
    assert stable(first) == stable(second)
    assert first['observation_window'] != second['observation_window']


def test_recording_validator_rejects_credentials_management_and_broken_relationships():
    base = load_recording()
    for change in (
        lambda d: d['requests'][1]['body'].update(quote_id='{quote:agency-b}'),
        lambda d: d['requests'][2].update(path='/management/actions'),
        lambda d: d['requests'][0].update(headers={'Authorization': 'Bearer secret'}),
        lambda d: d['requests'][0].update(timestamp='2020-01-01T00:00:00Z'),
    ):
        bad = copy.deepcopy(base)
        change(bad)
        with pytest.raises(ValueError):
            validate_recording(bad)


def test_simulated_history_distinguishes_complete_zero_from_incomplete_unknown():
    history = json.loads((HERE / 'historical-traffic.v1.json').read_text(encoding='utf-8'))
    validate_history(history)
    retired = next(x for x in history['endpoints'] if '/v1/' in x['path'])
    assert retired['coverage'] == 'complete'
    assert retired['legitimate_requests_in_window'] == 0
    assert retired['last_legitimate_at'] < history['observation_window']['start']
    incomplete = copy.deepcopy(history)
    incomplete['endpoints'][-1]['coverage'] = 'incomplete'
    incomplete['endpoints'][-1]['legitimate_requests_in_window'] = None
    validate_history(incomplete)
    incomplete['endpoints'][-1]['legitimate_requests_in_window'] = 0
    with pytest.raises(ValueError):
        validate_history(incomplete)


def test_reference_and_archived_candidates_are_separate_without_answers():
    reference = json.loads((HERE / 'reference-inventory.v1.json').read_text(encoding='utf-8'))
    archived = json.loads((HERE / 'archived-routes.v1.json').read_text(encoding='utf-8'))
    recording = load_recording()
    assert all(x['synthetic'] is True and x['schema_version'] == '1.0' for x in (reference, archived, recording))
    assert ('GET', '/api/v1/bookings/{id}') in {(x['method'], x['path']) for x in reference['endpoints']}
    assert ('GET', '/api/ui/preferences') not in {(x['method'], x['path']) for x in reference['endpoints']}
    assert archived['routes'] == [{'method': 'GET', 'path': '/api/v1/bookings/{id}'}]
    assert all('/v1/' not in x['path'] for x in recording['requests'])
    assert not any('classification' in json.dumps(x) or 'vulnerability' in json.dumps(x) for x in (reference, archived, recording))
