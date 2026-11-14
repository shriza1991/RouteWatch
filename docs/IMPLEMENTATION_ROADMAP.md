# Implementation roadmap — RouteWatch transformation

Branch: `feat/routewatch-complete-transformation`

## Baseline (verified against main at 6b43abf)

- Legacy FastAPI agent, synthetic travel sandbox and dashboard remain the working default demo.
- V1 contracts and SQLite persistence exist as a separate runtime.
- `transport.api` exposes typed polling and approval/execution lifecycle routes, but its default factory injects no domain, credential resolver, inventory or management adapter.
- The management adapter is implemented but not connected to a live v1 domain service.
- Historical discovery inputs are explicitly synthetic and supplied independently: journey recording, reference inventory, historical traffic and archived-route candidate.
- The dashboard supports legacy and v1 adapters, but Compose defaults to legacy mode.
- Historical integration evidence reports 94 tests and two container smoke runs on 2026-11-09; these are historical results, not tests run during this transformation.

## Ordered implementation status

| Phase | Scope | Status |
|---|---|---|
| 1 | Runtime and persistence unification | In progress — v1 store/transport retained; full legacy/domain orchestration wiring remains |
| 2 | Discovery and inventory | In progress — normalized route, HAR and JS extraction, evidence-aware fixture inventory implemented; runtime reachability probing not implemented |
| 3 | Change-aware planning | In progress — deterministic endpoint snapshot diff and test-family prioritization implemented; deployment webhook/CI integration pending |
| 4 | Travel business logic | Pending — existing ownership and fare rules preserved; additional refund/cancellation/role tests pending |
| 5 | Execution safety and independent verification | Partial — existing SafeExecutor and management adapter preserved; end-to-end v1 verification wiring pending |
| 6 | Dashboard and demo | Partial — existing dashboard remains intact; v1 inventory integration and browser/E2E verification pending |

## Safety boundaries

- New inventory code consumes repository-owned synthetic fixtures only.
- It performs no network probes and does not classify an archived route as zombie without explicit positive reachability plus complete zero-traffic history.
- No production target, customer data, or real financial action is used.
- Existing management credentials remain server-side.

## Verification limitations

The current execution environment cannot resolve `github.com` from the shell, so local pytest, frontend build, Docker and container smoke tests cannot be run here. The new discovery tests are committed for execution in CI or a developer checkout. Do not treat the historical 94-test result as current verification.
