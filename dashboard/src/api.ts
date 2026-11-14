const LEGACY_API = import.meta.env.VITE_AGENT_URL || 'http://localhost:8001';
const V1_API = import.meta.env.VITE_V1_API_URL || '/v1-api';
export const apiMode: 'legacy' | 'v1' = import.meta.env.VITE_DASHBOARD_API_MODE === 'v1' ? 'v1' : 'legacy';

export type ScanStatus = 'queued' | 'running' | 'cancelling' | 'completed' | 'cancelled' | 'failed';
export type EndpointLabel = 'active' | 'zombie' | 'shadow' | 'unknown';
export type Scan = { id: string; status: ScanStatus; started: string; completed: string | null; activity: string[]; endpoints: Endpoint[]; request_count: number };
export type Endpoint = { method: string; path: string; reachable: boolean | null; labels: EndpointLabel[]; evidence: Array<string | Evidence> };
export type Evidence = { statement: string; observedAt?: string; source?: string; synthetic: boolean };
export type Finding = { id: string; scan_id: string; kind: string; severity: 'critical' | 'high' | 'medium' | 'low'; title: string; business_impact: string; proof: Record<string, unknown>; suggested_fix: string; status: string; created_at: string };
export type AuditEvent = { id: string | number; scan_id: string; method: string; path: string; status: number | null; note: string; created: string };
export type Retest = { id: string; finding_id: string; scan_id: string; passed: boolean; detail: string; legitimate: boolean; created: string; exploitOutcome?: string; legitimateOutcome?: string; outcome?: string };
export type Proposal = { id: string; finding_id: string; action_key: string; description: string; state: string };
export type Approval = { id: string; proposal_id: string; approved_by: string; at: string; decision: 'approved' | 'rejected'; reason?: string };
export type Execution = { id: string; proposal_id: string; action_key: string; state: string; requested_at: string; detail?: string };
export type Change = { id: string; scan_id: string; target_id: string; at: string; method: string; normalized_path: string; change: string; risk_score: number; reasons: string[]; recommended_test_families: string[] };

export class ApiError extends Error {
  constructor(message: string, readonly status?: number, readonly code?: string) { super(message); this.name = 'ApiError'; }
}

async function request<T>(origin: string, path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try { response = await fetch(`${origin}${path}`, init); }
  catch { throw new ApiError('Service is disconnected. Check that the selected local API is running.'); }
  if (!response.ok) {
    let message = `Request failed (${response.status}).`; let code: string | undefined;
    try { const body = await response.json(); code = body.code; if (body.message) message = body.message; else if (typeof body.detail === 'string') message = body.detail; if (code) message = `${code}: ${message}`; }
    catch { /* Keep the status message. */ }
    if (response.status && !message.startsWith('Request failed')) message = `${response.status} ${message}`;
    throw new ApiError(message, response.status, code);
  }
  return response.json() as Promise<T>;
}

const json = (body?: unknown): RequestInit => ({ method: 'POST', headers: { 'content-type': 'application/json' }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
const idem = (): string => crypto.randomUUID();
const legacy = <T,>(path: string, init?: RequestInit) => request<T>(LEGACY_API, path, init);
const v1 = <T,>(path: string, init?: RequestInit) => request<T>(V1_API, path, init);
const newestFirst = <T,>(rows: T[], date: (row: T) => string | undefined) => rows.sort((a, b) => (Date.parse(date(b) ?? '') || 0) - (Date.parse(date(a) ?? '') || 0));

export const api = {
  scans: async (): Promise<Scan[]> => apiMode === 'legacy'
    ? (await legacy<Array<Record<string, any>>>('/scans')).map(row => ({ id: row.id, status: row.status, started: row.started, completed: row.completed, activity: row.activity ?? [], request_count: row.request_count ?? 0, endpoints: (row.endpoints ?? []).map((endpoint: any) => ({ method: endpoint.method, path: endpoint.path, reachable: endpoint.reachable, labels: endpoint.labels ?? [endpoint.classification ?? 'unknown'], evidence: endpoint.evidence ?? [] })) } as Scan))
    : newestFirst((await v1<Array<any>>('/v1/scans?limit=100')).map(row => ({ id: row.id, status: row.state, started: row.started_at, completed: row.completed_at, activity: [], request_count: row.request_count ?? 0, endpoints: [] } as Scan)), row => row.started),
  scanEvents: async (scanId: string): Promise<string[]> => apiMode === 'legacy' ? (await api.scans()).find(row => row.id === scanId)?.activity ?? [] : (await v1<Array<any>>(`/v1/scans/${scanId}/events`)).map(event => `${event.stage}: ${event.message}`),
  findings: async (): Promise<Finding[]> => apiMode === 'legacy'
    ? (await legacy<Array<Record<string, any>>>('/findings')).map(row => ({ id: row.id, scan_id: row.scan_id, kind: row.kind, severity: row.severity, title: row.title, business_impact: row.business_impact ?? row.impact ?? '', proof: row.proof ?? {}, suggested_fix: row.suggested_fix ?? row.fix ?? '', status: row.status ?? 'open', created_at: row.created_at ?? row.created } as Finding))
    : newestFirst((await v1<Array<any>>('/v1/findings')).map(row => ({ id: row.id, scan_id: row.scan_id, kind: row.rule_id, severity: row.severity, title: row.title || row.rule_id.replace(/_/g, ' '), business_impact: row.business_impact, proof: row.minimal_proof, suggested_fix: row.suggested_fix ?? '', status: row.state, created_at: row.created_at ?? '' } as Finding)), row => row.created_at),
  inventory: async (targetId: string, legacyEndpoints: Endpoint[] = []): Promise<Endpoint[]> => apiMode === 'legacy' ? legacyEndpoints : (await v1<Array<any>>(`/v1/inventory?target_id=${encodeURIComponent(targetId)}`)).map(endpoint => ({ method: endpoint.method, path: endpoint.normalized_path, reachable: endpoint.reachability === 'reachable' ? true : endpoint.reachability === 'unreachable' || endpoint.reachability === 'blocked' ? false : null, labels: endpoint.labels.length ? [...endpoint.labels] : ['unknown'], evidence: endpoint.evidence.map((item: any) => ({ statement: item.statement, source: item.kind, observedAt: item.observed_at, synthetic: item.synthetic })) })),
  audit: async (): Promise<AuditEvent[]> => apiMode === 'legacy' ? legacy<AuditEvent[]>('/audit') : newestFirst((await v1<Array<any>>('/v1/audit')).map(event => ({ id: event.id, scan_id: event.scan_id, method: event.method, path: event.normalized_path, status: event.status ?? null, note: `${event.purpose}: ${event.outcome}`, created: event.at })), row => row.created),
  changes: async (): Promise<Change[]> => apiMode === 'legacy' ? [] : newestFirst(await v1<Change[]>('/v1/changes'), row => row.at),
  retests: async (): Promise<Retest[]> => apiMode === 'legacy' ? legacy<Retest[]>('/retests') : newestFirst((await v1<Array<any>>('/v1/retests')).map(row => ({ id: row.id, finding_id: row.finding_id, scan_id: row.scan_id, passed: row.outcome === 'resolved', detail: row.detail ?? `Exploit ${row.exploit_outcome}; legitimate flow ${row.legitimate_flow_outcome}.`, legitimate: row.legitimate_flow_outcome === 'passed', created: row.created_at, exploitOutcome: row.exploit_outcome, legitimateOutcome: row.legitimate_flow_outcome, outcome: row.outcome })), row => row.created),
  proposals: async (): Promise<Proposal[]> => apiMode === 'legacy' ? [] : newestFirst(await v1<Proposal[]>('/v1/proposals'), row => row.id),
  approvals: async (): Promise<Approval[]> => apiMode === 'legacy' ? [] : newestFirst(await v1<Approval[]>('/v1/approvals'), row => row.at),
  executions: async (): Promise<Execution[]> => apiMode === 'legacy' ? [] : newestFirst(await v1<Execution[]>('/v1/executions'), row => row.requested_at),
  startScan: async (base: string, simulated = false): Promise<unknown> => apiMode === 'legacy'
    ? legacy(simulated ? '/deployments/simulate' : '/scans', { ...json({ id: 'local-sandbox', base_url: base, allowed_origins: [base], accounts: [{ name: 'Agency A tester', agency_id: 'agency-a', user_id: 'a-tester', token: '' }, { name: 'Agency B tester', agency_id: 'agency-b', user_id: 'b-tester', token: '' }], max_requests: 30, timeout_seconds: 3, reference_profile: simulated ? 'documented' : 'initial' }) })
    : v1('/v1/scans', { ...json({ target: { id: 'local-sandbox', base_url: base, allowed_origins: [base], accounts: [{ id: 'agency-a', agency_id: 'agency-a', user_id: 'a-tester', credential_ref: import.meta.env.VITE_AGENCY_A_CREDENTIAL_REF || 'server:agency-a' }, { id: 'agency-b', agency_id: 'agency-b', user_id: 'b-tester', credential_ref: import.meta.env.VITE_AGENCY_B_CREDENTIAL_REF || 'server:agency-b' }], max_requests: 30, timeout_seconds: 3 } }), headers: { 'content-type': 'application/json', 'Idempotency-Key': idem() } }),
  cancel: async (id: string): Promise<unknown> => apiMode === 'legacy' ? legacy(`/scans/${id}/cancel`, json()) : v1(`/v1/scans/${id}/cancel`, { method: 'POST', headers: { 'Idempotency-Key': idem() } }),
  propose: (findingId: string) => v1<Proposal>(`/v1/findings/${findingId}/proposals`, { method: 'POST', headers: { 'Idempotency-Key': idem() } }),
  approve: (proposalId: string, decision: 'approved' | 'rejected', reviewerToken: string) => v1<Approval>(`/v1/proposals/${proposalId}/approval`, { ...json({ decision }), headers: { 'content-type': 'application/json', 'Idempotency-Key': idem(), 'X-Reviewer-Token': reviewerToken } }),
  execute: (proposalId: string) => v1<Execution>(`/v1/proposals/${proposalId}/execute`, { method: 'POST', headers: { 'Idempotency-Key': idem() } }),
  retest: async (id: string): Promise<Retest | { finding_id: string; retest_scan_id: string }> => apiMode === 'legacy' ? legacy<{ finding_id: string; retest_scan_id: string }>(`/findings/${id}/retest`, json()) : v1<Retest>(`/v1/findings/${id}/retest`, { method: 'POST', headers: { 'Idempotency-Key': idem() } }),
};
