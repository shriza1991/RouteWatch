# Implementation roadmap — RouteWatch transformation

Branch: `feat/routewatch-complete-transformation`

## Verified baseline

The transformation started from `main` commit `6b43abf68aa904b87a5beb2471cb5aa73483abf6`. The branch retains the legacy agent and sandbox while integrating the newer v1 transport, SQLite store, fixture-backed discovery and React dashboard.

## Ordered implementation status

| Priority | Workstream | Current implementation | Remaining work |
|---|---|---|---|
| 1 | Runtime and persistence | Default Compose stack starts v1 API; real bounded domain service is injected; separate v1 SQLite store, scan lifecycle, findings, events, audit, proposals, approvals, executions and retests are wired. | Legacy data migration is not implemented; v1 and legacy remain parallel runtimes. Add restart/reconciliation E2E coverage. |
| 2 | Discovery and inventory | Normalized endpoint identity, HAR parser, JS route-literal extraction, synthetic journey/reference/history/archive inputs, source evidence, active/shadow/zombie/unknown classification, latest snapshot persistence. | General browser crawling, gateway/CI logs, live source ingestion, parameter/role inference and production-grade reachability probes. |
| 3 | Change-aware planning | Deterministic snapshot comparison, risk scoring and travel test-family recommendations; changes persist and appear in dashboard. | Deployment webhooks, JS bundle diff integration, changed-route targeted test dispatch. Current scan still runs its fixed two-rule suite. |
| 4 | Travel business logic | Cross-agency booking IDOR and fare tampering with synthetic controls and persisted-state proof. | Duplicate refund, unauthorized cancellation, payment bypass, coupon reuse, role escalation, mass assignment, supplier boundary and excessive data exposure. |
| 5 | Execution safety and verification | Local-sandbox-only allowlist, GET/POST restriction, request/rate budgets, timeouts, response cap, redirects disabled, kill switch, audit events, server-side management adapter, reviewer shared-secret gate, independent supported retests. | DNS pinning/rebinding defenses, richer per-host concurrency controls, authenticated identity/SSO, comprehensive test catalogue, broader adversarial safety tests. |
| 6 | Dashboard and demo | Dashboard defaults to v1 in Compose; scans/findings/inventory/changes/audit/proposals/approvals/executions/retests are connected; reviewer token is in-memory only. | Browser E2E, richer status/filters and full workflow acceptance test in real Compose. |

## Non-negotiable scope

The default scanner refuses non-sandbox targets. All attack scenarios use repository-owned synthetic data and the two synthetic agencies. Do not add real targets or customer data to tests. The v1 reviewer token is only a local demonstration credential; it is not a production identity solution.

## Verification

GitHub Actions run 24 passed on the current branch head: Python compile plus full pytest suite (138 passed), dashboard tests, dashboard production build, and Docker Compose configuration validation. This validates CI on the synthetic demo stack; it does not establish production readiness or cover the explicitly deferred feature families.

The branch adds deterministic domain tests for cross-agency access, persisted fare tampering, retest resolution, scope rejection and kill-switch behavior, plus existing discovery tests. Run the full suite and dashboard build in GitHub Actions before treating the branch as ready. No current test result should be inferred from historical results in `docs/INTEGRATION_STATUS.md`.
