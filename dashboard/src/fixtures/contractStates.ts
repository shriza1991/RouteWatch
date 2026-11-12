import type { Approval, Endpoint, Execution, Finding, Proposal, Retest, Scan } from '../api';

export const endpointFixture: Endpoint = {
  method: 'GET', path: '/api/v2/bookings/{id}', reachable: true,
  labels: ['active', 'shadow'],
  evidence: [{ statement: 'Seen in the synthetic journey window', source: 'traffic', observedAt: '2026-11-09T10:00:00Z', synthetic: true }],
};

export const scanFixture = (status: Scan['status']): Scan => ({
  id: `scan-${status}`, status, started: '2026-11-09T10:00:00Z', completed: status === 'running' || status === 'queued' || status === 'cancelling' ? null : '2026-11-09T10:01:00Z',
  activity: ['Loaded synthetic journey evidence'], endpoints: [endpointFixture], request_count: status === 'running' ? 2 : 0,
});

export const findingFixture: Finding = {
  id: 'finding-1', scan_id: 'scan-completed', kind: 'cross_agency_access', severity: 'high',
  title: 'Cross-agency booking access', business_impact: 'One agency can access another agency’s booking.',
  proof: { request: { path: '/api/v2/bookings/{id}' }, response: { agency_id: 'agency-b' }, legitimate_control: { agency_id: 'agency-a' }, authorization: 'Bearer fixture-secret' },
  suggested_fix: 'Enforce booking ownership.', status: 'verified', created_at: '2026-11-09T10:01:00Z',
};

export const proposalFixture: Proposal = { id: 'proposal-1', finding_id: findingFixture.id, action_key: 'enforce_booking_ownership', description: 'Enable booking ownership enforcement', state: 'proposed' };
export const approvalFixture: Approval = { id: 'approval-1', proposal_id: proposalFixture.id, approved_by: 'local-demo-reviewer', at: '2026-11-09T10:02:00Z', decision: 'approved' };
export const executionFixture: Execution = { id: 'execution-1', proposal_id: proposalFixture.id, action_key: proposalFixture.action_key, state: 'indeterminate', requested_at: '2026-11-09T10:03:00Z', detail: 'transport_uncertain_reconcile' };
export const retestFixtures: Retest[] = [
  { id: 'retest-resolved', finding_id: findingFixture.id, scan_id: 'scan-completed', passed: true, detail: 'Both checks passed.', legitimate: true, created: '2026-11-09T10:04:00Z', exploitOutcome: 'passed', legitimateOutcome: 'passed', outcome: 'resolved' },
  { id: 'retest-inconclusive', finding_id: findingFixture.id, scan_id: 'scan-completed', passed: false, detail: 'Exploit check is inconclusive.', legitimate: true, created: '2026-11-09T10:03:00Z', exploitOutcome: 'inconclusive', legitimateOutcome: 'passed', outcome: 'inconclusive' },
];
