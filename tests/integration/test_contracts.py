import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from shared.schemas import TargetConfig as LegacyTargetConfig
from shared.v1 import (
    CONTRACT_VERSION, ActionKey, Approval, AuthorizedAccount, CheckOutcome,
    Endpoint, ExecutionResult, Finding, InventoryEvidence, MinimalProof,
    ObservedRequest, RemediationProposal, RequestAuditEvent, RetestResult,
    ScanEvent, ScanRun, ServerCredentialConfig, TargetConfig, TestPlan as PlanContract, TestResult as ResultContract,
    map_sandbox_execution,
)


NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
FIXTURES = Path(__file__).resolve().parents[2] / 'sandbox' / 'fixtures'


def account(name):
    return AuthorizedAccount(id=name, agency_id=name, user_id=f'{name}-tester', credential_ref=f'server:{name}')


def proposal():
    return RemediationProposal(finding_id=uuid4(), action_key=ActionKey.enforce_booking_ownership,
                               description='Enable ownership enforcement')


def test_legacy_dashboard_payload_remains_accepted_and_serialized():
    payload = {'id': 'local-sandbox', 'base_url': 'http://localhost:8000',
               'allowed_origins': ['http://localhost:8000'], 'accounts': [
                   {'name': 'Agency A tester', 'agency_id': 'agency-a', 'user_id': 'a-tester', 'token': 'synthetic-a'},
                   {'name': 'Agency B tester', 'agency_id': 'agency-b', 'user_id': 'b-tester', 'token': 'synthetic-b'}],
               'max_requests': 30, 'timeout_seconds': 3, 'reference_profile': 'initial'}
    legacy = LegacyTargetConfig.model_validate(payload)
    assert legacy.model_dump()['accounts'][0]['token'] == 'synthetic-a'
    assert legacy.model_dump()['reference_profile'] == 'initial'
    assert LegacyTargetConfig.model_validate_json(legacy.model_dump_json()).model_dump() == legacy.model_dump()


def test_v1_target_uses_references_and_rejects_raw_credentials():
    assert CONTRACT_VERSION == '1.0'
    target = TargetConfig(id='local-sandbox', base_url='http://localhost:8000',
                          allowed_origins=['http://localhost:8000'],
                          accounts=[account('agency-a'), account('agency-b')],
                          max_requests=30, timeout_seconds=3)
    serialized = target.model_dump_json()
    assert 'credential_ref' in serialized and 'token' not in serialized
    assert TargetConfig.model_validate_json(serialized) == target
    with pytest.raises(ValidationError):
        AuthorizedAccount(id='a', agency_id='a', user_id='u', credential_ref='raw-token')
    with pytest.raises(ValidationError):
        TargetConfig.model_validate({**target.model_dump(mode='json'), 'token': 'raw'})
    server = ServerCredentialConfig(tokens_by_ref={'server:agency-a': 'private-value'})
    assert server.resolve('server:agency-a') == 'private-value'
    assert 'private-value' not in repr(server)


def test_fixture_observations_round_trip_without_runtime_ids():
    fixture = json.loads((FIXTURES / 'journey-recording.v1.json').read_text(encoding='utf-8'))
    capture_id = uuid4()
    observations = [ObservedRequest(capture_id=capture_id, method=item['method'],
                  normalized_path=item['path'], observed_at=item['timestamp'],
                  account_context_id=item['account_context_id'], source=item['source'],
                  status=item['status'], redacted_body_shape=item.get('body', {}))
                  for item in fixture['requests']]
    assert len(observations) == 7
    assert observations[1].redacted_body_shape['quote_id'] == '{quote:agency-a}'
    assert observations[4].redacted_body_shape['quote_id'] == '{quote:agency-b}'
    assert all('/management/' not in item.model_dump_json() for item in observations)
    assert ObservedRequest.model_validate_json(observations[0].model_dump_json()) == observations[0]


def test_all_entity_contracts_construct_and_round_trip():
    scan = ScanRun(target_id='local-sandbox', state='running', started_at=NOW)
    event = ScanEvent(scan_id=scan.id, stage='discover', message='capture loaded', at=NOW)
    observed = ObservedRequest(capture_id=uuid4(), method='GET', normalized_path='/api/v2/bookings/{id}',
                               observed_at=NOW, account_context_id='agency-a', source='synthetic journey recording')
    endpoint_id = uuid4()
    evidence = InventoryEvidence(endpoint_id=endpoint_id, kind='history', observed_at=NOW,
                                 statement='complete synthetic window', window_start=NOW-timedelta(days=1),
                                 window_end=NOW, coverage='complete')
    endpoint = Endpoint(id=endpoint_id, method='GET', normalized_path='/api/v2/bookings/{id}',
                        labels={'active', 'shadow'}, evidence=[evidence])
    plan = PlanContract(scan_id=scan.id, rule_id='ownership', observed_request_ids=[observed.id],
                    account_context_ids=['agency-a', 'agency-b'], budget=8)
    result = ResultContract(plan_id=plan.id, outcome='finding', evidence_ids=[evidence.id])
    finding = Finding(scan_id=scan.id, rule_id='ownership', severity='high',
                      business_impact='Other agency booking disclosure',
                      minimal_proof=MinimalProof(request={'path': '/api/v2/bookings/{id}'},
                                                 response={'agency_id': 'agency-b'},
                                                 legitimate_control={'agency_id': 'agency-a'}))
    remediation = proposal()
    approval = Approval(proposal_id=remediation.id, approved_by='reviewer', decision='approved', at=NOW)
    execution = ExecutionResult(id=uuid4(), proposal_id=remediation.id,
                                action_key=remediation.action_key, state='applied', requested_at=NOW)
    retest = RetestResult(finding_id=finding.id, scan_id=scan.id,
                          exploit_outcome=CheckOutcome.passed,
                          legitimate_flow_outcome=CheckOutcome.passed, outcome='resolved')
    audit = RequestAuditEvent(scan_id=scan.id, method='GET', normalized_path='/api/v2/bookings/{id}',
                              purpose='ownership test', outcome='200', at=NOW)
    for entity in (scan, event, observed, evidence, endpoint, plan, result, finding,
                   remediation, approval, execution, retest, audit):
        assert type(entity).model_validate_json(entity.model_dump_json()) == entity


def test_invalid_identifiers_timestamps_enums_and_links():
    with pytest.raises(ValidationError):
        ScanEvent(scan_id='not-a-uuid', stage='discover', message='x')
    with pytest.raises(ValidationError):
        ObservedRequest(capture_id=uuid4(), method='GET', normalized_path='/x',
                        observed_at=datetime(2026, 11, 8), account_context_id='a', source='capture')
    with pytest.raises(ValidationError):
        ScanRun(target_id='x', state='invented')
    with pytest.raises(ValidationError):
        Endpoint(method='GET', normalized_path='/x', labels={'unknown', 'active'})
    with pytest.raises(ValidationError):
        Endpoint(method='GET', normalized_path='/x', evidence=[InventoryEvidence(
            endpoint_id=uuid4(), kind='probe', observed_at=NOW, statement='reachable')])
    with pytest.raises(ValidationError):
        RemediationProposal(finding_id=uuid4(), action_key='run_code', description='bad')


def test_mutable_defaults_are_independent_and_secret_shapes_rejected():
    first, second = Endpoint(method='GET', normalized_path='/a'), Endpoint(method='GET', normalized_path='/b')
    first.labels.add('active')
    first.evidence.append(InventoryEvidence(endpoint_id=first.id, kind='probe', observed_at=NOW, statement='reachable'))
    assert second.labels == set() and second.evidence == []
    one = ObservedRequest(capture_id=uuid4(), method='POST', normalized_path='/x',
                          observed_at=NOW, account_context_id='a', source='capture')
    two = ObservedRequest(capture_id=uuid4(), method='POST', normalized_path='/x',
                          observed_at=NOW, account_context_id='a', source='capture')
    one.redacted_body_shape['route'] = 'DEL-BOM'
    assert two.redacted_body_shape == {}
    with pytest.raises(ValidationError):
        RequestAuditEvent(scan_id=uuid4(), method='POST', normalized_path='/x',
                          purpose='test', outcome='200', redacted_body_shape={'Authorization': 'Bearer private'})


def test_management_mapping_applied_unsupported_failed_and_mismatch():
    p = proposal()
    base = {'execution_id': str(uuid4()), 'action_key': p.action_key.value,
            'requested_at': '2026-11-08T12:00:00Z'}
    for state in ('applied', 'unsupported'):
        mapped = map_sandbox_execution(p, {**base, 'state': state})
        assert mapped.proposal_id == p.id and mapped.state == state
        assert str(mapped.id) == base['execution_id']
    failed = map_sandbox_execution(p, {'state': 'failed', 'detail': 'Management action failed'}, received_at=NOW)
    assert failed.state == 'failed' and failed.proposal_id == p.id
    with pytest.raises(ValueError):
        map_sandbox_execution(p, {**base, 'state': 'applied', 'action_key': 'validate_quote_fare'})
    with pytest.raises(ValueError):
        map_sandbox_execution(p, {'state': 'applied'})


def test_retest_keeps_inconclusive_failure_and_resolution_distinct():
    common = {'finding_id': uuid4(), 'scan_id': uuid4()}
    unresolved = RetestResult(**common, exploit_outcome='inconclusive',
                              legitimate_flow_outcome='passed', outcome='inconclusive')
    broken_flow = RetestResult(**common, exploit_outcome='passed',
                               legitimate_flow_outcome='failed', outcome='failed')
    resolved = RetestResult(**common, exploit_outcome='passed',
                            legitimate_flow_outcome='passed', outcome='resolved')
    assert len({unresolved.outcome, broken_flow.outcome, resolved.outcome}) == 3
    with pytest.raises(ValidationError):
        RetestResult(**common, exploit_outcome='inconclusive',
                     legitimate_flow_outcome='passed', outcome='resolved')
