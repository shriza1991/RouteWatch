from uuid import uuid4

import httpx
import pytest

from shared.v1 import Approval, RemediationProposal
from transport.management_adapter import ManagementConfig, SandboxManagementAdapter


TOKEN = 'private-local-management-token'


def records(action='enforce_booking_ownership', decision='approved'):
    proposal = RemediationProposal(finding_id=uuid4(), action_key=action, description='Predefined sandbox control')
    approval = Approval(proposal_id=proposal.id, approved_by='reviewer', decision=decision)
    return proposal, approval


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def adapter(handler):
    return SandboxManagementAdapter(ManagementConfig('http://127.0.0.1:8002', TOKEN), client(handler))


def reply(request, state='applied'):
    body = __import__('json').loads(request.content)
    return httpx.Response(200, json={'execution_id': str(uuid4()), 'action_key': body['action_key'],
                                     'state': state, 'requested_at': '2026-11-08T12:00:00Z'})


def test_exact_request_header_and_stable_key_on_repeat():
    seen = []
    def handler(request):
        seen.append(request)
        return reply(request)
    proposal, approval = records()
    attempt = uuid4()
    executor = adapter(handler)
    assert executor.execute(proposal, approval, attempt).state == 'applied'
    assert executor.execute(proposal, approval, attempt).state == 'applied'
    assert len(seen) == 2
    assert all(str(r.url) == 'http://127.0.0.1:8002/management/actions' and r.method == 'POST' for r in seen)
    assert all(r.headers['Authorization'] == f'Bearer {TOKEN}' for r in seen)
    bodies = [__import__('json').loads(r.content) for r in seen]
    assert bodies[0] == bodies[1]
    assert set(bodies[0]) == {'action_key', 'idempotency_key'}
    assert bodies[0]['action_key'] == 'enforce_booking_ownership'
    assert bodies[0]['idempotency_key'] != str(attempt)


@pytest.mark.parametrize('state', ['applied', 'unsupported'])
def test_management_results_map_honestly(state):
    proposal, approval = records()
    result = adapter(lambda request: reply(request, state)).execute(proposal, approval, uuid4())
    assert result.state == state and result.proposal_id == proposal.id
    assert result.action_key == proposal.action_key
    assert 'resolved' not in result.model_dump_json()


def test_explicit_failure_maps_without_upstream_body():
    proposal, approval = records()
    executor = adapter(lambda _: httpx.Response(500, json={'state': 'failed', 'detail': f'private {TOKEN}'}))
    result = executor.execute(proposal, approval, uuid4())
    assert result.state == 'failed' and result.detail == 'management_reported_failure'
    assert TOKEN not in result.model_dump_json()


def test_missing_rejected_mismatched_approval_and_local_invalid_action_send_nothing():
    sent = []
    executor = adapter(lambda request: sent.append(request) or reply(request))
    proposal, approved = records()
    rejected = approved.model_copy(update={'decision': 'rejected'})
    mismatched = approved.model_copy(update={'proposal_id': uuid4()})
    for approval in (rejected, mismatched):
        with pytest.raises(ValueError):
            executor.execute(proposal, approval, uuid4())
    with pytest.raises(TypeError):
        executor.execute(proposal, None, uuid4())
    invalid = proposal.model_copy(update={'action_key': 'run_arbitrary_code'})
    with pytest.raises(ValueError):
        executor.execute(invalid, approved, uuid4())
    assert sent == []


@pytest.mark.parametrize('status,detail', [(401, 'authentication_rejected'), (403, 'authentication_rejected'),
                                          (409, 'idempotency_conflict')])
def test_rejected_http_statuses_are_distinct_and_sanitized(status, detail):
    proposal, approval = records()
    result = adapter(lambda _: httpx.Response(status, text=f'private {TOKEN}')).execute(proposal, approval, uuid4())
    assert result.state == 'failed' and result.detail == detail
    assert TOKEN not in result.model_dump_json()


@pytest.mark.parametrize('response,detail', [
    (httpx.Response(500, text='upstream private error'), 'upstream_error_reconcile'),
    (httpx.Response(200, text='not json'), 'invalid_response_reconcile'),
    (httpx.Response(200, json={'state': 'applied'}), 'invalid_response_reconcile'),
    (httpx.Response(302, headers={'Location': 'https://other.example/'}), 'redirect_rejected_reconcile'),
])
def test_unknown_outcomes_require_reconciliation(response, detail):
    proposal, approval = records()
    result = adapter(lambda _: response).execute(proposal, approval, uuid4())
    assert result.state == 'indeterminate' and result.detail == detail


def test_mismatched_action_response_and_timeout():
    proposal, approval = records()
    mismatch = adapter(lambda request: httpx.Response(200, json={
        'execution_id': str(uuid4()), 'action_key': 'validate_quote_fare',
        'state': 'applied', 'requested_at': '2026-11-08T12:00:00Z'}))
    result = mismatch.execute(proposal, approval, uuid4())
    assert result.state == 'indeterminate' and result.detail == 'invalid_response_reconcile'
    def timeout(request):
        raise httpx.ReadTimeout('private timeout', request=request)
    result = adapter(timeout).execute(proposal, approval, uuid4())
    assert result.state == 'indeterminate' and result.detail == 'transport_uncertain_reconcile'
    assert TOKEN not in result.model_dump_json()


@pytest.mark.parametrize('origin', ['http://example.com', 'https://evil.example:8002', 'http://management:8003', 'ftp://localhost:8002',
                                    'http://user:pass@localhost:8002',
                                    'http://localhost:8002/management',
                                    'http://localhost:8002?x=1', 'http://localhost:8002#frag',
                                    'http://localhost:bad'])
def test_invalid_management_origins_rejected(origin):
    with pytest.raises(ValueError):
        ManagementConfig(origin, TOKEN)


def test_missing_configuration_and_secret_free_repr(monkeypatch):
    monkeypatch.delenv('SANDBOX_MANAGEMENT_URL', raising=False)
    monkeypatch.delenv('SANDBOX_MANAGEMENT_TOKEN', raising=False)
    with pytest.raises(ValueError) as missing:
        ManagementConfig.from_env()
    assert TOKEN not in str(missing.value)
    with pytest.raises(ValueError):
        ManagementConfig('http://127.0.0.1:8002', '   ')
    config = ManagementConfig('http://127.0.0.1:8002', TOKEN)
    assert TOKEN not in repr(config)
