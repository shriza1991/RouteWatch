import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';
import { api, apiMode, type Approval, type AuditEvent, type Endpoint, type Execution, type Finding, type Proposal, type Retest, type Scan } from './api';

const defaultBase = import.meta.env.VITE_SANDBOX_URL || 'http://localhost:8000';
export function App() {
  const [scans, setScans] = useState<Scan[]>([]);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [audit, setAudit] = useState<AuditEvent[]>([]);
  const [retests, setRetests] = useState<Retest[]>([]);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [executions, setExecutions] = useState<Execution[]>([]);
  const [base, setBase] = useState(defaultBase);
  const [loading, setLoading] = useState(true);
  const [connected, setConnected] = useState(true);
  const [busy, setBusy] = useState(false);
  const [pendingRetests, setPendingRetests] = useState<string[]>([]);
  const [pendingActions, setPendingActions] = useState<string[]>([]);
  const [retestScanIds, setRetestScanIds] = useState<Record<string, string>>({});
  const [error, setError] = useState('');
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const load = useCallback(async (initial = false) => {
    if (initial) setLoading(true);
    const [scanResult, findingResult, auditResult, retestResult, proposalResult, approvalResult, executionResult] = await Promise.allSettled([api.scans(), api.findings(), api.audit(), api.retests(), api.proposals(), api.approvals(), api.executions()]);
    const messages: string[] = [];
    if (scanResult.status === 'fulfilled') setScans(scanResult.value); else messages.push(`Scans: ${scanResult.reason.message}`);
    if (findingResult.status === 'fulfilled') setFindings(findingResult.value); else messages.push(`Findings: ${findingResult.reason.message}`);
    if (auditResult.status === 'fulfilled') setAudit(auditResult.value); else messages.push(`Audit: ${auditResult.reason.message}`);
    if (retestResult.status === 'fulfilled') setRetests(retestResult.value); else messages.push(`Retests: ${retestResult.reason.message}`);
    if (proposalResult.status === 'fulfilled') setProposals(proposalResult.value); else if (apiMode === 'v1') messages.push(`Proposals: ${proposalResult.reason.message}`);
    if (approvalResult.status === 'fulfilled') setApprovals(approvalResult.value); else if (apiMode === 'v1') messages.push(`Approvals: ${approvalResult.reason.message}`);
    if (executionResult.status === 'fulfilled') setExecutions(executionResult.value); else if (apiMode === 'v1') messages.push(`Executions: ${executionResult.reason.message}`);
    if (scanResult.status === 'fulfilled' && retestResult.status === 'fulfilled') {
      const terminal = new Set(scanResult.value.filter(scan => !['running', 'queued', 'cancelling'].includes(scan.status)).map(scan => scan.id));
      const finished = Object.entries(retestScanIds).filter(([findingId, scanId]) => terminal.has(scanId) || retestResult.value.some(row => row.finding_id === findingId)).map(([findingId]) => findingId);
      if (finished.length) setPendingRetests(current => current.filter(id => !finished.includes(id)));
    }
    if (scanResult.status === 'fulfilled' && scanResult.value[0]) {
      try {
        const [events, inventory] = await Promise.all([api.scanEvents(scanResult.value[0].id), api.inventory('local-sandbox', scanResult.value[0].endpoints)]);
        setScans(current => current.map((scan, index) => index === 0 ? { ...scan, activity: events, endpoints: inventory } : scan));
      } catch (reason) { messages.push(`Inventory or scan events: ${reason instanceof Error ? reason.message : 'capability unavailable'}`); }
    }
    setConnected(scanResult.status === 'fulfilled' || findingResult.status === 'fulfilled');
    setError(messages.join(' ')); setLastUpdated(new Date()); setLoading(false);
  }, [retestScanIds]);

  useEffect(() => {
    void load(true);
    const timer = window.setInterval(() => void load(), 2000);
    return () => window.clearInterval(timer);
  }, [load]);

  const latest = scans[0];
  const scanActive = scans.some(scan => ['queued', 'running', 'cancelling'].includes(scan.status));
  const launch = async (simulated = false) => {
    setBusy(true); setError('');
    try { await api.startScan(base, simulated); await load(); }
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
    try {
      const result = await api.retest(id);
      if ('retest_scan_id' in result) setRetestScanIds(current => ({ ...current, [id]: result.retest_scan_id }));
      await load();
    }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not start retest.'); }
    finally { if (apiMode === 'v1') setPendingRetests(current => current.filter(item => item !== id)); }
  };
  const act = async (key: string, action: () => Promise<unknown>) => {
    setPendingActions(current => [...current, key]); setError('');
    try { await action(); await load(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Action failed.'); }
    finally { setPendingActions(current => current.filter(item => item !== key)); }
  };

  return <main>
    <header className="topbar">
      <a className="brand" href="#overview" aria-label="RouteWatch overview"><span className="brand-mark">RW</span><span>ROUTEWATCH <small>SECURITY CONSOLE</small></span></a>
      <div className="connection"><span className={`dot ${connected ? 'online' : 'offline'}`} />{loading ? 'Connecting' : connected ? 'API connected' : 'API disconnected'}<span className="separator">·</span>{lastUpdated ? `Updated ${lastUpdated.toLocaleTimeString()}` : 'Waiting for first response'}</div>
    </header>

    <section className="intro" id="overview">
      <div><div className="eyebrow">{apiMode === 'v1' ? 'VOYAGEGUARD V1 / CONTRACT API' : 'LOCAL DEMONSTRATION / SYNTHETIC DATA'}</div><h1>Travel API security loop</h1><p>Review scan evidence, inventory signals, and retest outcomes from the local sandbox.</p></div>
      <div className="hero-status"><span className={`state-dot ${latest?.status || 'idle'}`} />{latest?.status || (loading ? 'Loading state' : 'No scans yet')}</div>
    </section>

    {(error || !connected) && <div className="alert" role="alert"><strong>{connected ? 'Some data could not be refreshed.' : 'Agent unavailable.'}</strong> {error || 'Start the local agent, then retry.'}<button className="link-button" onClick={() => void load(true)}>Retry</button></div>}

    <section className="panel run-panel" aria-busy={busy}>
      <div className="panel-heading"><div><div className="eyebrow">SCAN CONTROL</div><h2>Run a scoped sandbox scan</h2></div><span className="tag">30 request budget · 3s timeout</span></div>
      <div className="run-row"><label htmlFor="target-origin">Sandbox origin<input id="target-origin" value={base} onChange={event => setBase(event.target.value)} aria-describedby="target-help" /></label><button disabled={loading || busy || !connected || scanActive} onClick={() => void launch()}>Start scan</button>{apiMode === 'legacy' && <button disabled={loading || busy || !connected || scanActive} className="button-secondary" onClick={() => void launch(true)}>Simulate deployment + scan</button>}{latest && ['running', 'queued'].includes(latest.status) && <button className="button-danger" disabled={pendingActions.includes(`cancel:${latest.id}`)} onClick={() => void act(`cancel:${latest.id}`, () => api.cancel(latest.id))}>Stop scan</button>}</div>
      <p id="target-help" className="help">{apiMode === 'v1' ? 'Only server-side credential references are sent. The browser never handles account tokens or management credentials.' : 'The legacy demo uses synthetic account values and traffic. This API has no proposal or approval workflow.'}</p>
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
      {loading && findings.length === 0 ? <div className="panel"><Empty title="Loading findings" copy="Checking persisted scan results." /></div> : findings.length === 0 ? <div className="panel"><Empty title="No confirmed findings" copy="Findings will appear here when a scan reproduces a security issue." /></div> : <div className="finding-list">{findings.map(finding => <FindingCard key={finding.id} mode={apiMode} finding={finding} retests={retests.filter(row => row.finding_id === finding.id)} proposal={proposals.find(row => row.finding_id === finding.id)} proposals={proposals.filter(row => row.finding_id === finding.id)} approvals={approvals} executions={executions} pending={pendingRetests.includes(finding.id) || pendingActions.some(key => key.endsWith(finding.id))} onRetest={() => void act(`retest:${finding.id}`, () => retest(finding.id))} onPropose={() => void act(`propose:${finding.id}`, () => api.propose(finding.id))} onApprove={(proposalId, decision) => void act(`approval:${finding.id}`, () => api.approve(proposalId, decision))} onExecute={proposalId => void act(`execute:${finding.id}`, () => api.execute(proposalId))} />)}</div>}
    </section>

    <section className="section-block">
      <SectionTitle eyebrow="REQUEST TRACE" title="Recent agent requests" trailing={`${audit.length} events`} />
      <div className="panel audit-panel">{loading && audit.length === 0 ? <Empty title="Loading request audit" copy="Checking persisted request events." /> : audit.length === 0 ? <Empty title="No requests recorded" copy="Agent requests will be listed here after a scan." /> : <div className="table-wrap"><table><thead><tr><th>Result</th><th>Method</th><th>Path</th><th>Purpose</th><th>Recorded</th></tr></thead><tbody>{audit.slice(0, 20).map(event => <tr key={event.id}><td><span className="http-code">{event.status ?? '—'}</span></td><td className="mono">{event.method}</td><td className="mono path-cell">{event.path}</td><td>{event.note}</td><td>{new Date(event.created).toLocaleTimeString()}</td></tr>)}</tbody></table></div>}</div>
    </section>

    <footer><span>ROUTEWATCH / {apiMode === 'v1' ? 'V1 API' : 'LOCAL SANDBOX'}</span><span>{apiMode === 'legacy' ? 'Legacy demo mode · approval workflow not connected' : 'Lifecycle and resolution states come from the API'}</span></footer>
  </main>;
}

function Summary({ label, value, detail }: { label: string; value: string; detail: string }) { return <article className="summary-card"><span>{label}</span><strong>{value}</strong><small>{detail}</small></article>; }
function SectionTitle({ eyebrow, title, trailing }: { eyebrow: string; title: string; trailing?: string }) { return <div className="section-title"><div><div className="eyebrow">{eyebrow}</div><h2>{title}</h2></div>{trailing && <span>{trailing}</span>}</div>; }
function Empty({ title, copy }: { title: string; copy: string }) { return <div className="empty"><strong>{title}</strong><p>{copy}</p></div>; }
function LifecycleStep({ label, value, state }: { label: string; value: string; state: string }) { return <li className={`lifecycle-step ${state}`}><span>{label}</span><strong>{value}</strong></li>; }
function redact(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(redact);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([key, item]) => {
    const sensitive = /token|authorization|password|cookie|secret|credential|api[_-]?key|access[_-]?key/i.test(key);
    return [key, sensitive ? '[redacted]' : redact(item)];
  }));
  if (typeof value === 'string' && /^bearer\s/i.test(value)) return '[redacted]';
  return value;
}

function Inventory({ endpoints, loading }: { endpoints: Endpoint[]; loading: boolean }) {
  if (loading) return <div className="panel"><Empty title="Loading inventory" copy="Reading endpoint evidence from the latest scan." /></div>;
  if (!endpoints.length) return <div className="panel"><Empty title="Inventory not available yet" copy="Endpoint labels appear after a scan completes." /></div>;
  return <div className="panel table-panel"><div className="table-wrap"><table><thead><tr><th>Endpoint</th><th>Classification</th><th>Reachability</th><th>Evidence and source</th></tr></thead><tbody>{endpoints.map((endpoint, index) => <tr key={`${endpoint.method}-${endpoint.path}-${index}`}><td className="mono endpoint-path"><b>{endpoint.method}</b> {endpoint.path}</td><td><div className="label-stack">{endpoint.labels.map(label => <span key={label} className={`label-chip ${label}`}>{label}</span>)}</div></td><td>{endpoint.reachable === null ? 'Not probed' : endpoint.reachable ? 'Reachable' : 'Not reachable'}</td><td><ul className="evidence-list">{endpoint.evidence.map((entry, itemIndex) => <li key={itemIndex}>{typeof entry === 'string' ? entry : <>{entry.statement}{entry.source && <span className="source-chip">{entry.source}</span>}{entry.synthetic && <span className="synthetic-chip">synthetic</span>}{entry.observedAt && <time>{new Date(entry.observedAt).toLocaleString()}</time>}</>}{typeof entry === 'string' && <span className="synthetic-chip">synthetic</span>}</li>)}</ul></td></tr>)}</tbody></table></div><p className="table-note">History and journey evidence in this demo are synthetic. Evidence timestamps and source metadata are only shown when supplied by the backend. Reachability is a point-in-time probe, not proof of normal use. A shadow label is an inventory reconciliation signal, not a vulnerability fix.</p></div>;
}

function FindingCard({ mode, finding, retests, proposal, proposals, approvals, executions, pending, onRetest, onPropose, onApprove, onExecute }: {
  mode: 'legacy' | 'v1'; finding: Finding; retests: Retest[]; proposal?: Proposal; proposals: Proposal[];
  approvals: Approval[]; executions: Execution[]; pending: boolean; onRetest: () => void;
  onPropose: () => void; onApprove: (proposalId: string, decision: 'approved' | 'rejected') => void; onExecute: (proposalId: string) => void;
}) {
  const [confirmingDecision, setConfirmingDecision] = useState(false);
  const latestRetest = retests[0];
  const approval = proposal ? approvals.find(item => item.proposal_id === proposal.id) : undefined;
  const execution = proposal ? executions.find(item => item.proposal_id === proposal.id) : undefined;
  const hasProposal = proposals.length > 0;
  const proposalCanBeReviewed = proposal && ['proposed', 'awaiting_approval'].includes(proposal.state);
  const findingCanPropose = ['open', 'verified'].includes(finding.status);
  const proof = useMemo(() => JSON.stringify(redact(finding.proof), null, 2), [finding.proof]);
  return <article className="panel finding-card">
    <div className="finding-main"><div className="finding-badges"><span className={`severity-chip ${finding.severity}`}>{finding.severity}</span><span className="finding-kind">{finding.kind.replace(/_/g, ' ')}</span><span className={`finding-state ${finding.status}`}>{finding.status.replace(/_/g, ' ')}</span></div><h3>{finding.title}</h3><p>{finding.business_impact}</p>{finding.suggested_fix && <div className="fix-note"><span>Suggested fix</span>{finding.suggested_fix}</div>}</div>
    <div className="finding-actions"><button className="button-secondary" disabled={pending} onClick={onRetest}>{pending ? 'Starting retest…' : 'Retest after fix'}</button><small>{mode === 'legacy' ? 'Fresh scan; legacy retest is not approval-gated.' : 'Independent exploit and legitimate-flow outcomes are reported separately.'}</small></div>
    <ol className="lifecycle" aria-label="Remediation lifecycle status">
      <LifecycleStep label="Finding" value={finding.status.replace(/_/g, ' ')} state="current" />
      <LifecycleStep label="Proposal" value={proposal ? `${proposal.action_key} · ${proposal.state}` : mode === 'legacy' ? 'Unavailable in legacy API' : 'Not proposed'} state={proposal ? 'current' : 'unavailable'} />
      <LifecycleStep label="Approval" value={approval ? `${approval.decision} by ${approval.approved_by}` : mode === 'legacy' ? 'Unavailable in legacy API' : proposal?.state === 'rejected' ? 'Rejected' : 'Awaiting decision'} state={approval?.decision || (proposal?.state === 'rejected' ? 'rejected' : 'pending')} />
      <LifecycleStep label="Remediation" value={execution?.state || (mode === 'legacy' ? 'Manual operator action' : approval?.decision === 'approved' ? 'Approved · ready to execute' : 'Not executed')} state={execution?.state || 'pending'} />
      <LifecycleStep label="Retest" value={latestRetest ? `${latestRetest.outcome ?? (latestRetest.passed ? 'legacy pass' : 'not passed')}` : 'Not run'} state={latestRetest?.passed ? 'passed' : 'pending'} />
    </ol>
    {mode === 'v1' ? <div className="lifecycle-actions">
      {!hasProposal && findingCanPropose && <button disabled={pending} onClick={onPropose}>Create remediation proposal</button>}
      {proposal && !approval && proposalCanBeReviewed && !confirmingDecision && <button disabled={pending} onClick={() => setConfirmingDecision(true)}>Review proposal decision</button>}
      {proposal && !approval && proposalCanBeReviewed && confirmingDecision && <div className="approval-confirm" role="group" aria-label="Confirm remediation decision"><strong>Review: {proposal.description}</strong><p>This local API uses a server-configured demo reviewer; it does not authenticate a human reviewer.</p><div><button disabled={pending} onClick={() => { setConfirmingDecision(false); onApprove(proposal.id, 'approved'); }}>Confirm approval</button><button className="button-secondary" disabled={pending} onClick={() => { setConfirmingDecision(false); onApprove(proposal.id, 'rejected'); }}>Reject proposal</button><button className="button-quiet" disabled={pending} onClick={() => setConfirmingDecision(false)}>Cancel</button></div></div>}
      {proposal && approval?.decision === 'approved' && !execution && <button disabled={pending} onClick={() => onExecute(proposal.id)}>Execute approved action</button>}
      {proposal && approval?.decision === 'rejected' && <span className="decision-note">Rejected proposals cannot execute.</span>}
      {execution?.state === 'indeterminate' && <span className="decision-note">Execution result is indeterminate. Reconcile before another attempt.</span>}
    </div> : <div className="workflow-note"><strong>Approval workflow unavailable</strong><span>This legacy demo does not create proposals or approvals. A retest pass means the same finding did not recur in a completed scan; it does not independently prove both exploit blocking and legitimate-flow success.</span></div>}
    {latestRetest && <div className="retest-result"><span className={`status-chip ${latestRetest.passed ? 'completed' : 'failed'}`}>{latestRetest.outcome ?? (latestRetest.passed ? 'Legacy retest passed' : 'Retest not passed')}</span>{mode === 'v1' ? <><span>Exploit check: {latestRetest.exploitOutcome}</span><span>Legitimate flow: {latestRetest.legitimateOutcome}</span></> : <span>Legitimate baseline: {latestRetest.legitimate ? 'completed' : 'not verified'}</span>}<span>{latestRetest.detail}</span></div>}
    <details className="proof-details"><summary>Inspect redacted finding evidence</summary><pre>{proof}</pre></details>
  </article>;
}

const mount = document.getElementById('root');
if (mount) createRoot(mount).render(<App />);
