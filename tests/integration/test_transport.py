from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from persistence import V1Store, fingerprint
from shared.v1 import (Approval, Endpoint, ExecutionResult, Finding, MinimalProof,
                       RemediationProposal, RetestResult, ScanEvent, ScanRun)
from transport.api import create_app


class Resolver:
    def has_reference(self, reference): return reference in {'server:agency-a', 'server:agency-b'}


class Inventory:
    def list_endpoints(self, target_id):
        return [Endpoint(method='GET', normalized_path=f'/api/{target_id}', labels={'active'})]


class Adapter:
    def __init__(self): self.calls = []
    def execute(self, proposal, approval, attempt_id):
        self.calls.append((proposal, approval, attempt_id))
        return ExecutionResult(id=uuid4(), proposal_id=proposal.id, action_key=proposal.action_key,
                               state='indeterminate', requested_at=approval.at, detail='transport_uncertain_reconcile')


class Domain:
    def __init__(self): self.calls = []
    def start_scan(self, target, credentials):
        self.calls.append('start')
        return ScanRun(target_id=target.id, state='queued')
    def cancel_scan(self, scan):
        self.calls.append('cancel')
        return scan.model_copy(update={'state': 'cancelled'})
    def propose(self, finding):
        self.calls.append('propose')
        return RemediationProposal(finding_id=finding.id, action_key='enforce_booking_ownership', description='Enable predefined control')
    def approve(self, proposal, reviewer_id, decision):
        self.calls.append(('approve', reviewer_id))
        return Approval(proposal_id=proposal.id, approved_by=reviewer_id, decision=decision)
    def execute(self, proposal, approval, attempt_id, adapter):
        self.calls.append('execute')
        return adapter.execute(proposal, approval, attempt_id)
    def retest(self, finding):
        self.calls.append('retest')
        return RetestResult(finding_id=finding.id, scan_id=finding.scan_id,
                            exploit_outcome='inconclusive', legitimate_flow_outcome='passed', outcome='inconclusive')


def target():
    return {'id': 'local-sandbox', 'base_url': 'http://127.0.0.1:8000',
            'allowed_origins': ['http://127.0.0.1:8000'], 'accounts': [
                {'id': 'agency-a', 'agency_id': 'agency-a', 'user_id': 'a', 'credential_ref': 'server:agency-a'},
                {'id': 'agency-b', 'agency_id': 'agency-b', 'user_id': 'b', 'credential_ref': 'server:agency-b'}],
            'max_requests': 30, 'timeout_seconds': 3}


def prepared(store):
    scan = ScanRun(target_id='local-sandbox', state='completed')
    event = ScanEvent(scan_id=scan.id, stage='done', message='actual domain event')
    finding = Finding(scan_id=scan.id, rule_id='ownership', severity='high', business_impact='Disclosure',
                      minimal_proof=MinimalProof(request={'path': '/api/v2/bookings/{id}'},
                                                 response={'agency_id': 'agency-b'}, legitimate_control={'agency_id': 'agency-a'}))
    with store.transaction() as tx:
        tx.scans.save(scan); tx.scan_events.save(event); tx.findings.save(finding)
    return scan, event, finding


def test_default_capabilities_unavailable_and_validation(tmp_path):
    store = V1Store(tmp_path / 'v1.db')
    with TestClient(create_app(store=store)) as client:
        assert client.post('/v1/scans', json={'target': target()}, headers={'Idempotency-Key': 'a'}).status_code == 503
        assert client.get('/v1/inventory?target_id=local-sandbox').json()['code'] == 'capability_unavailable'
        invalid = client.post('/v1/scans', json={'target': {**target(), 'token': 'private'}}, headers={'Idempotency-Key': 'a'})
        assert invalid.status_code == 422 and 'private' not in invalid.text
        assert client.get('/v1/scans/not-a-uuid').status_code == 422
        assert client.get('/v1/scans/'+str(uuid4())).status_code == 404


def test_scan_polling_filtering_replay_conflict_and_restart(tmp_path):
    store = V1Store(tmp_path / 'v1.db'); domain = Domain()
    app = create_app(store=store, domain=domain, credential_resolver=Resolver())
    body = {'target': target()}
    with TestClient(app) as client:
        assert client.post('/v1/scans', json=body).status_code == 422
        first = client.post('/v1/scans', json=body, headers={'Idempotency-Key': 'scan-1'})
        assert first.status_code == 200 and first.json()['state'] == 'queued'
        same = client.post('/v1/scans', json=body, headers={'Idempotency-Key': 'scan-1'})
        assert same.json() == first.json() and domain.calls == ['start']
        changed = {'target': {**target(), 'max_requests': 31}}
        assert client.post('/v1/scans', json=changed, headers={'Idempotency-Key': 'scan-1'}).status_code == 409
        scan_id = first.json()['id']
        assert client.get('/v1/scans?target_id=local-sandbox').json() == [first.json()]
        assert client.get('/v1/scans?target_id=other').json() == []
        assert client.get(f'/v1/scans/{scan_id}/events').json() == []
        cancel = client.post(f'/v1/scans/{scan_id}/cancel', headers={'Idempotency-Key': 'cancel-1'})
        assert cancel.status_code == 200 and cancel.json()['state'] == 'cancelled'
        assert client.post(f'/v1/scans/{scan_id}/cancel', headers={'Idempotency-Key': 'cancel-1'}).json() == cancel.json()
    with TestClient(create_app(store=V1Store(store.path))) as restarted:
        assert restarted.get(f'/v1/scans/{scan_id}').json()['state'] == 'cancelled'


def test_findings_inventory_proposal_approval_execution_retest_and_parent_filters(tmp_path):
    store = V1Store(tmp_path / 'v1.db'); scan, event, finding = prepared(store)
    domain, adapter = Domain(), Adapter()
    app = create_app(store=store, domain=domain, inventory=Inventory(), management_adapter=adapter,
                     reviewer_id='server-reviewer')
    with TestClient(app) as client:
        assert len(client.get(f'/v1/scans/{scan.id}/events').json()) == 1
        assert len(client.get(f'/v1/findings?scan_id={scan.id}').json()) == 1
        assert client.get(f'/v1/findings?scan_id={uuid4()}').json() == []
        assert client.get('/v1/inventory?target_id=local-sandbox').json()[0]['labels'] == ['active']
        proposal = client.post(f'/v1/findings/{finding.id}/proposals', headers={'Idempotency-Key': 'p'})
        assert proposal.status_code == 200
        proposal_id = proposal.json()['id']
        assert client.get(f'/v1/proposals?finding_id={finding.id}').json() == [proposal.json()]
        assert client.post(f'/v1/proposals/{proposal_id}/execute', headers={'Idempotency-Key': 'x'}).status_code == 409
        assert adapter.calls == []
        approval = client.post(f'/v1/proposals/{proposal_id}/approval',
                               headers={'Idempotency-Key': 'a'}, json={'decision': 'approved'})
        assert approval.status_code == 200 and approval.json()['approved_by'] == 'server-reviewer'
        assert ('approve', 'server-reviewer') in domain.calls
        execution = client.post(f'/v1/proposals/{proposal_id}/execute', headers={'Idempotency-Key': 'x'})
        assert execution.status_code == 200 and execution.json()['state'] == 'indeterminate'
        assert len(adapter.calls) == 1
        assert client.post(f'/v1/proposals/{proposal_id}/execute', headers={'Idempotency-Key': 'x'}).json() == execution.json()
        assert len(adapter.calls) == 1
        uncertain_retry = client.post(f'/v1/proposals/{proposal_id}/execute', headers={'Idempotency-Key': 'new-attempt'})
        assert uncertain_retry.status_code == 409
        assert uncertain_retry.json()['code'] == 'execution_reconciliation'
        assert len(adapter.calls) == 1
        assert client.get(f'/v1/executions?proposal_id={proposal_id}').json() == [execution.json()]
        assert client.get(f'/v1/findings/{finding.id}').json()['state'] == 'verified'
        retest = client.post(f'/v1/findings/{finding.id}/retest', headers={'Idempotency-Key': 'r'})
        assert retest.json()['outcome'] == 'inconclusive'
        assert client.get(f'/v1/retests?finding_id={finding.id}').json() == [retest.json()]
        assert client.get(f'/v1/audit?scan_id={scan.id}').json() == []


def test_rejected_approval_and_absent_domain_never_call_adapter(tmp_path):
    store = V1Store(tmp_path / 'v1.db'); _, _, finding = prepared(store)
    domain, adapter = Domain(), Adapter()
    with TestClient(create_app(store=store, domain=domain, management_adapter=adapter)) as client:
        proposal = client.post(f'/v1/findings/{finding.id}/proposals', headers={'Idempotency-Key': 'p'}).json()
        pid = proposal['id']
        assert client.post(f'/v1/proposals/{pid}/approval', headers={'Idempotency-Key': 'a'},
                           json={'decision': 'rejected', 'approved_by': 'fake'}).status_code == 422
        assert client.post(f'/v1/proposals/{pid}/approval', headers={'Idempotency-Key': 'a'},
                           json={'decision': 'rejected'}).status_code == 200
        assert client.post(f'/v1/proposals/{pid}/execute', headers={'Idempotency-Key': 'x'}).status_code == 409
    with TestClient(create_app(store=store, management_adapter=adapter)) as client:
        assert client.post(f'/v1/proposals/{pid}/execute', headers={'Idempotency-Key': 'x2'}).status_code == 503
    assert adapter.calls == []


def test_pending_external_operation_blocks_duplicate_execution(tmp_path):
    store = V1Store(tmp_path / 'v1.db'); _, _, finding = prepared(store)
    domain, adapter = Domain(), Adapter()
    proposal = domain.propose(finding)
    store.proposals.save(proposal)
    store.approvals.save(domain.approve(proposal, 'server-reviewer', 'approved'))
    store.reserve('execute', str(proposal.id), 'request-key', fingerprint({}))
    with TestClient(create_app(store=store, domain=domain, management_adapter=adapter)) as client:
        response = client.post(f'/v1/proposals/{proposal.id}/execute', headers={'Idempotency-Key': 'request-key'})
        assert response.status_code == 409 and response.json()['code'] == 'pending_reconciliation'
        alternate = client.post(f'/v1/proposals/{proposal.id}/execute', headers={'Idempotency-Key': 'other-key'})
        assert alternate.status_code == 409 and alternate.json()['code'] == 'execution_reconciliation'
    assert adapter.calls == []


def test_secret_config_not_returned_or_persisted(tmp_path):
    store = V1Store(tmp_path / 'v1.db')
    with TestClient(create_app(store=store, domain=Domain(), credential_resolver=Resolver())) as client:
        body = {'target': {**target(), 'accounts': [
            {**target()['accounts'][0], 'token': 'very-private'}, target()['accounts'][1]]}}
        response = client.post('/v1/scans', json=body, headers={'Idempotency-Key': 'secret'})
        assert response.status_code == 422
        assert 'very-private' not in response.text
        assert 'very-private' not in store.path.read_bytes().decode('latin1')
