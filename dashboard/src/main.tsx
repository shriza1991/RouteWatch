import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';
import { api, ApiError, type AuditEvent, type Endpoint, type Finding, type Retest, type Scan } from './api';

const defaultBase = import.meta.env.VITE_SANDBOX_URL || 'http://localhost:8000';
const config = (base: string, profile: 'initial' | 'documented' = 'initial') => ({
  id: 'local-sandbox', base_url: base, allowed_origins: [base],
  accounts: [
    { name: 'Agency A tester', agency_id: 'agency-a', user_id: 'a-tester', token: 'synthetic-a' },
    { name: 'Agency B tester', agency_id: 'agency-b', user_id: 'b-tester', token: 'synthetic-b' },
  ], max_requests: 30, timeout_seconds: 3, reference_profile: profile,
});

function App() {
  const [scans, setScans] = useState<Scan[]>([]);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [audit, setAudit] = useState<AuditEvent[]>([]);
  const [retests, setRetests] = useState<Retest[]>([]);
  const [base, setBase] = useState(defaultBase);
  const [loading, setLoading] = useState(true);
  const [connected, setConnected] = useState(true);
  const [busy, setBusy] = useState(false);
  const [pendingRetests, setPendingRetests] = useState<string[]>([]);
  const [retestScanIds, setRetestScanIds] = useState<Record<string, string>>({});
  const [error, setError] = useState('');
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const load = useCallback(async (initial = false) => {
    if (initial) setLoading(true);
    const results = await Promise.allSettled([api.scans(), api.findings(), api.audit(), api.retests()]);
    const messages: string[] = [];
    if (results[0].status === 'fulfilled') setScans(results[0].value); else messages.push(`Scans: ${results[0].reason.message}`);
    if (results[1].status === 'fulfilled') setFindings(results[1].value); else messages.push(`Findings: ${results[1].reason.message}`);
    if (results[2].status === 'fulfilled') setAudit(results[2].value); else messages.push(`Audit: ${results[2].reason.message}`);
    if (results[3].status === 'fulfilled') setRetests(results[3].value); else messages.push(`Retests: ${results[3].reason.message}`);
    if (results[0].status === 'fulfilled' && results[3].status === 'fulfilled') {
      const terminal = new Set(results[0].value.filter(scan => scan.status !== 'running').map(scan => scan.id));
      const finished = Object.entries(retestScanIds).filter(([findingId, scanId]) => terminal.has(scanId) || results[3].status === 'fulfilled' && results[3].value.some(row => row.finding_id === findingId)).map(([findingId]) => findingId);
      if (finished.length) setPendingRetests(current => current.filter(id => !finished.includes(id)));
    }
    setConnected(results.some(result => result.status === 'fulfilled'));
    setError(messages.join(' ')); setLastUpdated(new Date()); setLoading(false);
  }, [retestScanIds]);

  useEffect(() => {
    void load(true);
    const timer = window.setInterval(() => void load(), 2000);
    return () => window.clearInterval(timer);
  }, [load]);

  const latest = scans[0];
  const launch = async (simulated = false) => {
    setBusy(true); setError('');
    try { await api.startScan(config(base, simulated ? 'documented' : 'initial'), simulated); await load(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not start the scan.'); }
    finally { setBusy(false); }
  };
  const cancel = async (id: string) => {
    setError('');
    try { await api.cancel(id); await load(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not cancel the scan.'); }
  };
  const retest = async (id: string) => {
    setPendingRetests(current => [...current, id]); setError('');
    try { const result = await api.retest(id); setRetestScanIds(current => ({ ...current, [id]: result.retest_scan_id })); await load(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not start retest.'); }
    finally { setPendingRetests(current => current.filter(item => item !== id)); }
  };

  return <main>
    <header className="topbar">
      <a className="brand" href="#overview" aria-label="RouteWatch overview"><span className="brand-mark">RW</span><span>ROUTEWATCH <small>SECURITY CONSOLE</small></span></a>
      <div className="connection"><span className={`dot ${connected ? 'online' : 'offline'}`} />{loading ? 'Connecting' : connected ? 'Agent connected' : 'Agent disconnected'}<span className="separator">·</span>{lastUpdated ? `Updated ${lastUpdated.toLocaleTimeString()}` : 'Waiting for first response'}</div>
    </header>

    <section className="intro" id="overview">
      <div><div className="eyebrow">LOCAL DEMONSTRATION / SYNTHETIC DATA</div><h1>Travel API security loop</h1><p>Review scan evidence, inventory signals, and retest outcomes from the local sandbox.</p></div>
      <div className="hero-status"><span className={`state-dot ${latest?.status || 'idle'}`} />{latest?.status || (loading ? 'Loading state' : 'No scans yet')}</div>
    </section>

    {(error || !connected) && <div className="alert" role="alert"><strong>{connected ? 'Some data could not be refreshed.' : 'Agent unavailable.'}</strong> {error || 'Start the local agent, then retry.'}<button className="link-button" onClick={() => void load(true)}>Retry</button></div>}

    <section className="panel run-panel" aria-busy={busy}>
      <div className="panel-heading"><div><div className="eyebrow">SCAN CONTROL</div><h2>Run a scoped sandbox scan</h2></div><span className="tag">30 request budget · 3s timeout</span></div>
      <div className="run-row"><label htmlFor="target-origin">Sandbox origin<input id="target-origin" value={base} onChange={event => setBase(event.target.value)} aria-describedby="target-help" /></label><button disabled={busy || !connected} onClick={() => void launch()}>Start scan</button><button disabled={busy || !connected} className="button-secondary" onClick={() => void launch(true)}>Simulate deployment + scan</button>{latest?.status === 'running' && <button className="button-danger" onClick={() => void cancel(latest.id)}>Stop scan</button>}</div>
      <p id="target-help" className="help">The agent targets this origin only. Demo accounts and traffic are synthetic. Deployment simulation records a local event and does not change sandbox controls.</p>
      {busy && <p className="inline-status" role="status">Submitting scan request…</p>}
    </section>

    <section className="summary-grid" aria-label="Current scan summary">
      <Summary label="Latest scan" value={latest?.status || (loading ? 'Loading' : 'No scans')} detail={latest ? latest.id.slice(0, 8) : 'Start a scan to begin'} />
      <Summary label="Confirmed findings" value={String(findings.length)} detail="Across persisted scans" />
      <Summary label="Requests made" value={String(latest?.request_count ?? 0)} detail="Current scan run" />
      <Summary label="Inventory endpoints" value={String(latest?.endpoints.length ?? 0)} detail="Evidence from synthetic fixtures" />
    </section>

    <section className="section-block">
      <SectionTitle eyebrow="OBSERVABILITY" title="Live activity" trailing={latest?.started ? new Date(latest.started).toLocaleString() : undefined} />
      <div className="panel activity-panel">{loading && !latest ? <Empty title="Loading scan history" copy="Connecting to the local agent." /> : latest ? <><div className="activity-meta"><span className={`status-chip ${latest.status}`}>{latest.status}</span><span>{latest.request_count} requests recorded</span>{latest.completed && <span>Completed {new Date(latest.completed).toLocaleTimeString()}</span>}</div><ol className="activity-list">{latest.activity.map((item, index) => <li key={`${index}-${item}`}><span className="timeline-dot" />{item}</li>)}</ol></> : <Empty title="No scan activity yet" copy="Start a scan to see each observed step and its outcome." />}</div>
    </section>

    <section className="section-block">
      <SectionTitle eyebrow="INVENTORY" title="Endpoint evidence" trailing="Synthetic observation sources" />
      <Inventory endpoints={latest?.endpoints || []} loading={loading && !latest} />
    </section>

    <section className="section-block">
      <SectionTitle eyebrow="FINDINGS" title="Security findings" trailing={`${findings.length} recorded`} />
      {loading && findings.length === 0 ? <div className="panel"><Empty title="Loading findings" copy="Checking persisted scan results." /></div> : findings.length === 0 ? <div className="panel"><Empty title="No confirmed findings" copy="Findings will appear here when a scan reproduces a security issue." /></div> : <div className="finding-list">{findings.map(finding => <FindingCard key={finding.id} finding={finding} retests={retests.filter(row => row.finding_id === finding.id)} pending={pendingRetests.includes(finding.id)} onRetest={() => void retest(finding.id)} />)}</div>}
    </section>

    <section className="section-block">
      <SectionTitle eyebrow="REQUEST TRACE" title="Recent agent requests" trailing={`${audit.length} events`} />
      <div className="panel audit-panel">{loading && audit.length === 0 ? <Empty title="Loading request audit" copy="Checking persisted request events." /> : audit.length === 0 ? <Empty title="No requests recorded" copy="Agent requests will be listed here after a scan." /> : <div className="table-wrap"><table><thead><tr><th>Result</th><th>Method</th><th>Path</th><th>Purpose</th><th>Recorded</th></tr></thead><tbody>{audit.slice(0, 20).map(event => <tr key={event.id}><td><span className="http-code">{event.status ?? '—'}</span></td><td className="mono">{event.method}</td><td className="mono path-cell">{event.path}</td><td>{event.note}</td><td>{new Date(event.created).toLocaleTimeString()}</td></tr>)}</tbody></table></div>}</div>
    </section>

    <footer><span>ROUTEWATCH / LOCAL SANDBOX</span><span>Legacy demo mode · approval workflow not connected</span></footer>
  </main>;
}

function Summary({ label, value, detail }: { label: string; value: string; detail: string }) { return <article className="summary-card"><span>{label}</span><strong>{value}</strong><small>{detail}</small></article>; }
function SectionTitle({ eyebrow, title, trailing }: { eyebrow: string; title: string; trailing?: string }) { return <div className="section-title"><div><div className="eyebrow">{eyebrow}</div><h2>{title}</h2></div>{trailing && <span>{trailing}</span>}</div>; }
function Empty({ title, copy }: { title: string; copy: string }) { return <div className="empty"><strong>{title}</strong><p>{copy}</p></div>; }
function LifecycleStep({ label, value, state }: { label: string; value: string; state: string }) { return <li className={`lifecycle-step ${state}`}><span>{label}</span><strong>{value}</strong></li>; }

function Inventory({ endpoints, loading }: { endpoints: Endpoint[]; loading: boolean }) {
  if (loading) return <div className="panel"><Empty title="Loading inventory" copy="Reading endpoint evidence from the latest scan." /></div>;
  if (!endpoints.length) return <div className="panel"><Empty title="Inventory not available yet" copy="Endpoint labels appear after a scan completes." /></div>;
  return <div className="panel table-panel"><div className="table-wrap"><table><thead><tr><th>Endpoint</th><th>Classification</th><th>Reachability</th><th>Evidence and source</th></tr></thead><tbody>{endpoints.map((endpoint, index) => <tr key={`${endpoint.method}-${endpoint.path}-${index}`}><td className="mono endpoint-path"><b>{endpoint.method}</b> {endpoint.path}</td><td><div className="label-stack">{endpoint.labels.map(label => <span key={label} className={`label-chip ${label}`}>{label}</span>)}</div></td><td>{endpoint.reachable === null ? 'Not probed' : endpoint.reachable ? 'Reachable' : 'Not reachable'}</td><td><ul className="evidence-list">{endpoint.evidence.map((entry, itemIndex) => <li key={itemIndex}>{typeof entry === 'string' ? entry : <>{entry.statement}{entry.source && <span className="source-chip">{entry.source}</span>}{entry.observedAt && <time>{new Date(entry.observedAt).toLocaleString()}</time>}</>}{typeof entry === 'string' && <span className="synthetic-chip">synthetic</span>}</li>)}</ul></td></tr>)}</tbody></table></div><p className="table-note">History and journey evidence in this demo are synthetic. Evidence timestamps and source metadata are only shown when supplied by the backend. Reachability is a point-in-time probe, not proof of normal use.</p></div>;
}

function FindingCard({ finding, retests, pending, onRetest }: { finding: Finding; retests: Retest[]; pending: boolean; onRetest: () => void }) {
  const latestRetest = retests[0];
  const proof = useMemo(() => JSON.stringify(finding.proof, null, 2), [finding.proof]);
  return <article className="panel finding-card">
    <div className="finding-main"><div className="finding-badges"><span className={`severity-chip ${finding.severity}`}>{finding.severity}</span><span className="finding-kind">{finding.kind.replaceAll('_', ' ')}</span><span className={`finding-state ${finding.status}`}>{finding.status.replaceAll('_', ' ')}</span></div><h3>{finding.title}</h3><p>{finding.business_impact}</p><div className="fix-note"><span>Suggested fix</span>{finding.suggested_fix}</div></div>
    <div className="finding-actions"><button className="button-secondary" disabled={pending} onClick={onRetest}>{pending ? 'Starting retest…' : 'Retest after fix'}</button><small>Starts a fresh scan; this legacy check is not approval-gated.</small></div>
    <ol className="lifecycle" aria-label="Remediation lifecycle status">
      <LifecycleStep label="Finding" value={finding.status.replaceAll('_', ' ')} state="current" />
      <LifecycleStep label="Proposal" value="Unavailable in legacy API" state="unavailable" />
      <LifecycleStep label="Approval" value="Unavailable in legacy API" state="unavailable" />
      <LifecycleStep label="Remediation" value="Manual operator action" state="manual" />
      <LifecycleStep label="Retest" value={latestRetest ? (latestRetest.passed ? 'Legacy pass' : 'Not passed') : 'Not run'} state={latestRetest?.passed ? 'passed' : 'pending'} />
    </ol>
    <div className="workflow-note"><strong>Approval workflow unavailable</strong><span>This legacy demo does not create proposals or approvals. A retest pass means the same finding did not recur in a completed scan; it does not independently prove both exploit blocking and legitimate-flow success.</span></div>
    {latestRetest && <div className="retest-result"><span className={`status-chip ${latestRetest.passed ? 'completed' : 'failed'}`}>{latestRetest.passed ? 'Legacy retest passed' : 'Retest not passed'}</span><span>Legitimate baseline: {latestRetest.legitimate ? 'completed' : 'not verified'}</span><span>{latestRetest.detail}</span></div>}
    <details className="proof-details"><summary>Inspect redacted finding evidence</summary><pre>{proof}</pre></details>
  </article>;
}

createRoot(document.getElementById('root')!).render(<App />);
