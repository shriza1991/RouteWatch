# Vikram — Security dashboard and demonstration UX

## Mission

Render the real system state so a viewer can see evidence, approval, remediation, retest, inventory, and failure modes without the browser making security decisions.

## Ownership

Existing: all `dashboard/` files. Proposed: `dashboard/src/api.ts`, `components/`, `tests/`. Do not edit backend routes, sandbox UI, domain decisions, inventory algorithms, contracts, or Compose.

## Ordered work

### VIK-01 — Contract client and operational states
- **Purpose/behaviour:** replace inline calls in existing `dashboard/src/main.tsx` with typed polling client; render loading, empty, error, disconnected, running, cancelling/cancelled and duplicate-action-disabled states.
- **Files:** modify owned dashboard files; create proposed API/component files.
- **I/O:** consumes Sujal’s polling API; sends configuration, scan/cancel, proposal/approval/execute/retest intent only.
- **Edges/dependencies:** expired/failed request shows backend code; polling never invents progress; Sujal supplies endpoint fixture.
- **Acceptance:** component test for each state and no browser secret fields.

### VIK-02 — Evidence and inventory
- **Purpose:** show redacted proof/control, severity/impact, endpoint label set and timestamped source evidence; label synthetic history.
- **Files:** proposed `InventoryTable.tsx`, `FindingDetail.tsx`.
- **Edges:** unknown is displayed; shadow documentation update says reconciliation, not fixed vulnerability; labels can coexist.
- **Acceptance:** screenshot/component tests use contract fixtures and show no token/raw credential.

### VIK-03 — Approval/remediation/retest demo path
- **Purpose:** proposal → confirmation → approved/rejected → remediating → retesting → resolved/failed/inconclusive, with explicit local-demo explanation.
- **Files:** proposed `RemediationPanel.tsx`, tests.
- **I/O:** consumes `Finding/Proposal/Approval/ExecutionResult/RetestResult`; never calculates resolution.
- **Edges:** unsupported/failure stays unresolved; idempotency/disabled action avoids duplicate click.
- **Acceptance:** UI calls execute only after actual approved state; displays independent legitimate-flow result.

## Contracts, stubs and commands

Component contract: `<FindingDetail finding proposal execution retest onApprove onExecute onRetest />`. Example displayed state: `retest_failed — exploit blocked: true; legitimate flow: false`. Use MSW/static contract fixtures during development, isolated under `dashboard/src/fixtures`; replace with Sujal polling client before demo. Existing command: `npm run build`; proposed: `npm test`.

## Done and handoff

Done: dashboard only renders backend decisions and clearly explains simulated/local actions. Hand accepted UI payload expectations to **Sujal** and demo screenshots/state checklist to **Ram**. Avoid displaying mock data in integrated mode or calling management directly. Must-have: all lifecycle/error states; optional: charts/theme polish.
