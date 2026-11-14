import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { approvalFixture, endpointFixture, executionFixture, findingFixture, proposalFixture, retestFixtures, scanFixture } from './fixtures/contractStates';

const mocks = vi.hoisted(() => ({
  mode: 'legacy' as 'legacy' | 'v1',
  api: {
    scans: vi.fn(), scanEvents: vi.fn(), findings: vi.fn(), inventory: vi.fn(), audit: vi.fn(), changes: vi.fn(), retests: vi.fn(),
    proposals: vi.fn(), approvals: vi.fn(), executions: vi.fn(), startScan: vi.fn(), cancel: vi.fn(),
    propose: vi.fn(), approve: vi.fn(), execute: vi.fn(), retest: vi.fn(),
  },
}));

vi.mock('./api', () => ({ api: mocks.api, get apiMode() { return mocks.mode; } }));

async function mount() {
  const { App } = await import('./main');
  return render(<App />);
}

describe('dashboard operational states', () => {
  beforeEach(() => {
    vi.resetModules(); mocks.mode = 'legacy';
    Object.values(mocks.api).forEach(mock => mock.mockReset());
    mocks.api.scans.mockResolvedValue([]); mocks.api.scanEvents.mockResolvedValue([]);
    mocks.api.findings.mockResolvedValue([]); mocks.api.inventory.mockResolvedValue([]);
    mocks.api.audit.mockResolvedValue([]); mocks.api.changes.mockResolvedValue([]); mocks.api.retests.mockResolvedValue([]);
    mocks.api.proposals.mockResolvedValue([]); mocks.api.approvals.mockResolvedValue([]); mocks.api.executions.mockResolvedValue([]);
    mocks.api.cancel.mockResolvedValue({}); mocks.api.retest.mockResolvedValue({ finding_id: findingFixture.id, retest_scan_id: 'scan-retest' });
  });

  it('shows a loading state until the first poll completes', async () => {
    let resolveScans!: (value: ReturnType<typeof scanFixture>[]) => void;
    mocks.api.scans.mockReturnValue(new Promise(resolve => { resolveScans = resolve; }));
    await mount();
    expect(screen.getByText('Loading scan history')).toBeInTheDocument();
    resolveScans([]);
    expect(await screen.findByText('No scans yet')).toBeInTheDocument();
  });

  it('shows a helpful empty state', async () => {
    await mount();
    expect(await screen.findByText('No scan activity yet')).toBeInTheDocument();
    expect(screen.getByText('No confirmed findings')).toBeInTheDocument();
  });

  it('shows disconnected and backend error states, including the backend code', async () => {
    mocks.api.scans.mockRejectedValue(new Error('503 capability_unavailable: scan capability unavailable'));
    mocks.api.findings.mockRejectedValue(new Error('503 capability_unavailable: scan capability unavailable'));
    mocks.api.audit.mockRejectedValue(new Error('503 capability_unavailable: scan capability unavailable'));
    mocks.api.retests.mockRejectedValue(new Error('503 capability_unavailable: scan capability unavailable'));
    await mount();
    expect(await screen.findByText(/API disconnected/)).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('capability_unavailable');
  });

  it.each(['queued', 'running', 'cancelling', 'cancelled', 'failed', 'completed'] as const)('renders scan state %s without invented progress', async status => {
    mocks.api.scans.mockResolvedValue([scanFixture(status)]);
    mocks.api.scanEvents.mockResolvedValue(['Observed event from API']);
    await mount();
    await waitFor(() => expect(screen.getAllByText(status).length).toBeGreaterThan(0));
    expect(screen.getByText('Observed event from API')).toBeInTheDocument();
    if (status === 'running' || status === 'queued') expect(screen.getByRole('button', { name: 'Stop scan' })).toBeInTheDocument();
    if (status === 'cancelling' || status === 'cancelled') expect(screen.queryByRole('button', { name: 'Stop scan' })).not.toBeInTheDocument();
  });

  it('disables duplicate scans and redacts credential-shaped proof before display', async () => {
    mocks.api.scans.mockResolvedValue([scanFixture('running')]); mocks.api.findings.mockResolvedValue([findingFixture]);
    await mount();
    expect(await screen.findByRole('button', { name: 'Start scan' })).toBeDisabled();
    fireEvent.click(screen.getByText('Inspect redacted finding evidence'));
    expect(await screen.findByText(/\[redacted\]/)).toBeInTheDocument();
    expect(screen.queryByText(/fixture-secret/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/token|secret|credential/i)).not.toBeInTheDocument();
  });

  it('shows overlapping endpoint labels, source timestamps, and synthetic history', async () => {
    mocks.api.scans.mockResolvedValue([scanFixture('completed')]);
    mocks.api.inventory.mockResolvedValue([endpointFixture]);
    await mount();
    expect((await screen.findAllByText('active')).length).toBeGreaterThan(0);
    expect(screen.getAllByText('shadow').length).toBeGreaterThan(0);
    expect(screen.getByText('traffic')).toBeInTheDocument();
    expect(screen.getAllByText('synthetic').length).toBeGreaterThan(0);
    expect(screen.getByText(/A shadow label is an inventory reconciliation signal/)).toBeInTheDocument();
  });
});

describe('v1 approval and retest flow', () => {
  beforeEach(() => {
    vi.resetModules(); mocks.mode = 'v1';
    Object.values(mocks.api).forEach(mock => mock.mockReset());
    mocks.api.scans.mockResolvedValue([scanFixture('completed')]); mocks.api.scanEvents.mockResolvedValue(['scan completed']);
    mocks.api.findings.mockResolvedValue([findingFixture]); mocks.api.inventory.mockResolvedValue([endpointFixture]);
    mocks.api.audit.mockResolvedValue([]); mocks.api.changes.mockResolvedValue([]); mocks.api.retests.mockResolvedValue([]);
    mocks.api.proposals.mockResolvedValue([]); mocks.api.approvals.mockResolvedValue([]); mocks.api.executions.mockResolvedValue([]);
    mocks.api.propose.mockResolvedValue(proposalFixture); mocks.api.approve.mockResolvedValue(approvalFixture); mocks.api.execute.mockResolvedValue(executionFixture);
    mocks.api.retest.mockResolvedValue(retestFixtures[0]);
  });

  it('requires proposal review and a persisted approved decision before execute', async () => {
    let proposalExists = false; let approved = false; let executed = false;
    mocks.api.proposals.mockImplementation(() => Promise.resolve(proposalExists ? [proposalFixture] : []));
    mocks.api.approvals.mockImplementation(() => Promise.resolve(approved ? [approvalFixture] : []));
    mocks.api.executions.mockImplementation(() => Promise.resolve(executed ? [executionFixture] : []));
    mocks.api.propose.mockImplementation(() => { proposalExists = true; return Promise.resolve(proposalFixture); });
    mocks.api.approve.mockImplementation(() => { approved = true; return Promise.resolve(approvalFixture); });
    mocks.api.execute.mockImplementation(() => { executed = true; return Promise.resolve(executionFixture); });
    await mount();
    fireEvent.click(await screen.findByRole('button', { name: 'Create remediation proposal' }));
    await waitFor(() => expect(mocks.api.propose).toHaveBeenCalledWith(findingFixture.id));
    fireEvent.change(await screen.findByLabelText('Reviewer token'), { target: { value: 'reviewer-test-token' } });
    fireEvent.click(await screen.findByRole('button', { name: 'Review proposal decision' }));
    expect(await screen.findByText(/shared local-demo credential, not enterprise identity management/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Execute approved action' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Confirm approval' }));
    await waitFor(() => expect(mocks.api.approve).toHaveBeenCalledWith(proposalFixture.id, 'approved', 'reviewer-test-token'));
    fireEvent.click(await screen.findByRole('button', { name: 'Execute approved action' }));
    await waitFor(() => expect(mocks.api.execute).toHaveBeenCalledWith(proposalFixture.id));
    expect(await screen.findByText('indeterminate')).toBeInTheDocument();
    expect(screen.getByText(/Reconcile before another attempt/)).toBeInTheDocument();
  });

  it('renders exploit and legitimate-flow outcomes independently and uses server resolution', async () => {
    mocks.api.retests.mockResolvedValue(retestFixtures);
    await mount();
    expect((await screen.findAllByText('resolved')).length).toBeGreaterThan(0);
    expect(screen.getByText('Exploit check: passed')).toBeInTheDocument();
    expect(screen.getByText('Legitimate flow: passed')).toBeInTheDocument();
    expect(screen.queryByText('Approval workflow unavailable')).not.toBeInTheDocument();
  });

  it('keeps rejected proposals from reaching execution', async () => {
    const rejected = { ...approvalFixture, decision: 'rejected' as const };
    mocks.api.proposals.mockResolvedValue([proposalFixture]); mocks.api.approvals.mockResolvedValue([rejected]);
    await mount();
    expect(await screen.findByText(/rejected by local-demo-reviewer/)).toBeInTheDocument();
    expect(screen.getByText('Rejected proposals cannot execute.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Execute approved action' })).not.toBeInTheDocument();
    expect(mocks.api.execute).not.toHaveBeenCalled();
  });

  it.each(['failed', 'inconclusive', 'cancelled'] as const)('renders retest outcome %s without converting it to resolved', async outcome => {
    const result = { ...retestFixtures[1], id: `retest-${outcome}`, outcome, exploitOutcome: outcome === 'failed' ? 'failed' : outcome, passed: false };
    mocks.api.retests.mockResolvedValue([result]);
    await mount();
    expect(await screen.findAllByText(outcome)).not.toHaveLength(0);
    expect(screen.getByText('Retest', { selector: 'span' })).toBeInTheDocument();
    expect(screen.queryByText('resolved')).not.toBeInTheDocument();
  });
});
