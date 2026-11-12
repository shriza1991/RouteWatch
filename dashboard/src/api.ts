const API = import.meta.env.VITE_AGENT_URL || 'http://localhost:8001';

export type ScanStatus = 'running' | 'completed' | 'cancelled' | 'failed';
export type EndpointLabel = 'active' | 'zombie' | 'shadow' | 'unknown';
export type Scan = {
  id: string; status: ScanStatus; started: string; completed: string | null;
  activity: string[]; endpoints: Endpoint[]; request_count: number;
};
export type Endpoint = {
  method: string; path: string; reachable: boolean | null;
  labels: EndpointLabel[]; evidence: Array<string | Evidence>;
};
export type Evidence = { statement: string; observedAt?: string; source?: string; synthetic: boolean };
export type Finding = {
  id: string; scan_id: string; kind: string; severity: 'critical' | 'high' | 'medium' | 'low';
  title: string; business_impact: string; proof: Record<string, unknown>; suggested_fix: string;
  status: 'open' | 'fixed' | 'retest_passed'; created_at: string;
};
export type AuditEvent = { id: number; scan_id: string; method: string; path: string; status: number | null; note: string; created: string };
export type Retest = { id: string; finding_id: string; scan_id: string; passed: boolean; detail: string; legitimate: boolean; created: string };

export class ApiError extends Error {
  constructor(message: string, readonly status?: number) { super(message); this.name = 'ApiError'; }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try { response = await fetch(`${API}${path}`, init); }
  catch { throw new ApiError('Agent is disconnected. Check that the local agent is running.'); }
  if (!response.ok) {
    let message = `Request failed (${response.status}).`;
    try { const body = await response.json(); if (typeof body.detail === 'string') message = body.detail; else if (body.message) message = body.message; }
    catch { /* Keep the safe status message. */ }
    throw new ApiError(message, response.status);
  }
  return response.json() as Promise<T>;
}

export const api = {
  scans: () => request<Array<Record<string, any>>>('/scans').then(rows => rows.map(row => ({
    id: row.id, status: row.status, started: row.started, completed: row.completed,
    activity: row.activity ?? [], request_count: row.request_count ?? 0,
    endpoints: (row.endpoints ?? []).map((endpoint: any) => ({
      method: endpoint.method, path: endpoint.path, reachable: endpoint.reachable,
      labels: endpoint.labels ?? [endpoint.classification ?? 'unknown'], evidence: endpoint.evidence ?? [],
    })),
  } as Scan))),
  findings: () => request<Array<Record<string, any>>>('/findings').then(rows => rows.map(row => ({
    id: row.id, scan_id: row.scan_id, kind: row.kind, severity: row.severity, title: row.title,
    business_impact: row.business_impact ?? row.impact ?? '', proof: row.proof ?? {},
    suggested_fix: row.suggested_fix ?? row.fix ?? '', status: row.status ?? 'open',
    created_at: row.created_at ?? row.created,
  } as Finding))),
  audit: () => request<AuditEvent[]>('/audit'),
  retests: () => request<Retest[]>('/retests'),
  startScan: (config: unknown, simulated = false) => request<{ scan_id: string; event?: string }>(simulated ? '/deployments/simulate' : '/scans', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(config) }),
  cancel: (id: string) => request<Scan>(`/scans/${id}/cancel`, { method: 'POST' }),
  retest: (id: string) => request<{ finding_id: string; retest_scan_id: string }>('/findings/' + id + '/retest', { method: 'POST' }),
};
