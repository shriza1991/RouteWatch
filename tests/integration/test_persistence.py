import sqlite3
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from persistence import IdempotencyConflict, SchemaVersionError, V1Store, fingerprint
from persistence.sqlite import MIGRATIONS, migrate
from shared.v1 import (Approval, ExecutionResult, Finding, MinimalProof, RemediationProposal,
                       RequestAuditEvent, RetestResult, ScanEvent, ScanRun)


NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    return V1Store(tmp_path / 'voyageguard-v1.db')


def chain(store):
    scan = ScanRun(target_id='sandbox', state='completed', started_at=NOW, completed_at=NOW)
    event = ScanEvent(scan_id=scan.id, at=NOW, stage='discover', message='complete')
    finding = Finding(scan_id=scan.id, rule_id='ownership', severity='high',
                      business_impact='Other-agency booking disclosure',
                      minimal_proof=MinimalProof(request={'path': '/api/v2/bookings/{id}'},
                                                 response={'agency_id': 'agency-b'},
                                                 legitimate_control={'agency_id': 'agency-a'}))
    proposal = RemediationProposal(finding_id=finding.id, action_key='enforce_booking_ownership',
                                   description='Enable ownership check')
    approval = Approval(proposal_id=proposal.id, approved_by='reviewer', decision='approved', at=NOW)
    execution = ExecutionResult(id=uuid4(), proposal_id=proposal.id,
                                action_key=proposal.action_key, state='applied', requested_at=NOW)
    retest = RetestResult(finding_id=finding.id, scan_id=scan.id,
                          exploit_outcome='passed', legitimate_flow_outcome='passed', outcome='resolved', created_at=NOW)
    audit = RequestAuditEvent(scan_id=scan.id, at=NOW, method='GET',
                              normalized_path='/api/v2/bookings/{id}', purpose='ownership', outcome='403', status=403)
    values = {'scans': scan, 'scan_events': event, 'findings': finding, 'proposals': proposal,
              'approvals': approval, 'executions': execution, 'retests': retest, 'audit': audit}
    with store.transaction() as tx:
        for name, item in values.items():
            getattr(tx, name).save(item)
    return values


def test_every_repository_round_trip_relationship_and_reopen(store):
    values = chain(store)
    reopened = V1Store(store.path)
    for name, expected in values.items():
        repo = getattr(reopened, name)
        assert repo.get(expected.id) == expected
        assert repo.list() == [expected]
        parent = expected.target_id if name == 'scans' else str(getattr(expected, {
            'scan_events': 'scan_id', 'findings': 'scan_id', 'proposals': 'finding_id',
            'approvals': 'proposal_id', 'executions': 'proposal_id', 'retests': 'finding_id',
            'audit': 'scan_id'}[name]))
        assert repo.list(parent_id=parent) == [expected]
        assert repo.list(parent_id='other') == []
    assert reopened.scans.get(uuid4()) is None
    assert reopened.findings.list(limit=1, offset=1) == []


def test_updates_store_supplied_decisions_without_transitions(store):
    values = chain(store)
    scan = values['scans'].model_copy(update={'state': 'failed'})
    finding = values['findings'].model_copy(update={'state': 'inconclusive'})
    store.scans.save(scan)
    store.findings.save(finding)
    assert store.scans.get(scan.id).state == 'failed'
    assert store.findings.get(finding.id).state == 'inconclusive'


def test_foreign_keys_uniqueness_and_no_partial_transaction(store):
    orphan = ScanEvent(scan_id=uuid4(), stage='test', message='orphan', at=NOW)
    with pytest.raises(sqlite3.IntegrityError):
        store.scan_events.save(orphan)
    assert store.scan_events.list() == []
    scan = ScanRun(target_id='sandbox', state='running', started_at=NOW)
    with pytest.raises(sqlite3.IntegrityError):
        with store.transaction() as tx:
            tx.scans.save(scan)
            tx.scan_events.save(orphan)
    assert store.scans.get(scan.id) is None
    values = chain(store)
    second = Approval(proposal_id=values['proposals'].id, approved_by='second', decision='rejected', at=NOW)
    with pytest.raises(sqlite3.IntegrityError):
        store.approvals.save(second)
    assert store.approvals.list() == [values['approvals']]


def test_deterministic_order_and_filtering(store):
    later = ScanRun(target_id='same', state='queued', started_at=NOW + timedelta(hours=1))
    early_b = ScanRun(target_id='same', state='queued', started_at=NOW)
    early_a = ScanRun(target_id='other', state='queued', started_at=NOW)
    for value in (later, early_b, early_a):
        store.scans.save(value)
    expected = sorted((early_b, early_a), key=lambda x: str(x.id)) + [later]
    assert store.scans.list() == expected
    assert store.scans.list(parent_id='same') == [early_b, later]
    assert store.scans.list(limit=1, offset=1) == expected[1:2]


def test_migration_rerun_rollback_and_newer_version_rejection(tmp_path):
    path = tmp_path / 'migration.db'
    first = V1Store(path)
    second = V1Store(path)
    assert first.path == second.path
    connection = sqlite3.connect(tmp_path / 'failed.db')
    try:
        with pytest.raises(sqlite3.OperationalError):
            migrate(connection, (('CREATE TABLE temporary(id TEXT)', 'THIS IS INVALID SQL'),))
        assert connection.execute('PRAGMA user_version').fetchone()[0] == 0
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='temporary'").fetchone() is None
    finally:
        connection.close()
    connection = first.connect()
    try:
        connection.execute('PRAGMA user_version = 99')
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(SchemaVersionError):
        V1Store(path)


def test_idempotency_pending_replay_conflict_scoping_and_completed_result(store):
    one = fingerprint({'action_key': 'validate_quote_fare', 'proposal_id': 'p'})
    assert one == fingerprint({'proposal_id': 'p', 'action_key': 'validate_quote_fare'})
    assert store.reserve('execute', 'proposal-p', 'key-1', one) == {'state': 'pending', 'result': None}
    assert store.reserve('execute', 'proposal-p', 'key-1', one) == {'state': 'pending', 'result': None}
    with pytest.raises(IdempotencyConflict):
        store.reserve('execute', 'proposal-p', 'key-1', fingerprint({'action_key': 'other'}))
    assert store.reserve('execute', 'proposal-q', 'key-1', one)['state'] == 'pending'
    result = {'execution_id': str(uuid4()), 'state': 'applied'}
    assert store.complete('execute', 'proposal-p', 'key-1', one, result)['state'] == 'completed'
    assert V1Store(store.path).reserve('execute', 'proposal-p', 'key-1', one)['result'] == result
    assert store.complete('execute', 'proposal-p', 'key-1', one, result)['result'] == result
    with pytest.raises(IdempotencyConflict):
        store.complete('execute', 'proposal-p', 'key-1', one, {'state': 'failed'})


def test_pending_reservation_survives_restart_without_claiming_execution(store):
    request_hash = fingerprint({'action_key': 'enforce_booking_ownership'})
    store.reserve('execute', 'proposal-p', 'retry-key', request_hash)
    restarted = V1Store(store.path)
    assert restarted.reserve('execute', 'proposal-p', 'retry-key', request_hash) == {'state': 'pending', 'result': None}


def test_safe_payload_boundary_rejects_mutated_raw_credentials(store):
    values = chain(store)
    finding = values['findings']
    finding.minimal_proof.request['authorization'] = 'Bearer private'
    with pytest.raises(ValidationError):
        store.findings.save(finding)
    assert 'private' not in store.path.read_bytes().decode('latin1')
    with pytest.raises(ValueError):
        fingerprint({'token': 'private'})
    with pytest.raises(ValueError):
        fingerprint({'request': {'management_url': 'http://127.0.0.1:8002'}})
    with pytest.raises(ValueError):
        store.complete('execute', 'proposal', 'key', fingerprint({'x': 1}), {'authorization': 'Bearer private'})
