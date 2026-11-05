# Ram — Security agent, verification and remediation orchestration

## Mission

Own the deterministic safety-critical decisions: choose checks from observations, prove findings with controls, enforce approval before predefined remediation, and independently resolve only successful retests. This is rule-driven, not LLM-driven.

## Ownership

Existing mixed file: `agent/app.py`; proposed owned split: `agent/domain/`, `agent/rules/`, `tests/agent/`. Do not edit sandbox behavior, discovery parsing/classification, dashboard, shared models, or transport/persistence.

## Ordered work

### RAM-01 — Scan state machine and safe executor
- **Purpose/behaviour:** implement `queued→running→cancelling/cancelled|failed|completed`; apply allowed-origin validation, no out-of-scope redirects, timeout/rate/budget, explicit account ownership and request audit.
- **Files:** split existing `agent/app.py` into proposed `agent/domain/scan.py`, `executor.py`.
- **I/O:** consumes `TargetConfig`, `ObservedRequest`, inventory; produces `ScanRun`, `TestPlan`, `RequestAuditEvent` through Sujal interface.
- **Edges:** budget/cancel gives non-success state; unknown route/credential produces `inconclusive`, never implicit discovery.
- **Dependencies/evidence:** Sujal contract/persistence, Akshat observations; test redirect/budget/cancel/scope with fake HTTP server.

### RAM-02 — Cross-agency and fare rules
- **Purpose:** form checks from observed structures and fresh legitimate A/B baselines; foreign booking is a finding only if response identity and agency show B while A requested; fare finding requires stored synthetic fare differing from quote. Retest includes normal own booking/normal confirmation.
- **Files:** proposed `agent/rules/ownership.py`, `fare.py`, tests.
- **I/O:** `plan(observations,contexts)->TestPlan`; `execute(plan)->TestResult/Finding`.
- **Edges:** no two accounts/missing identity/ambiguous confirmation = inconclusive; never hardcode seeded IDs/path/finding.
- **Acceptance:** vulnerable and fixed fixture tests prove both exploit and legitimate control requirements.

### RAM-03 — Approval-gated remediation and independent retest
- **Purpose:** propose supported action, require `Approval.approved`, request management adapter, then ordinary-app HTTP retest; decide lifecycle.
- **Files:** proposed `agent/domain/remediation.py`, `retest.py`.
- **I/O:** consumes proposal/approval and a server-side adapter from Sujal; emits `ExecutionResult`, `RetestResult`.
- **Edges:** unsupported/failed execution/retest/cancel remains unresolved; execution 2xx does not resolve.
- **Acceptance:** tests prove adapter is never called without approval and management URL is absent from plans/audits.

## Interfaces, stubs and commands

`build_plan(observed, config) -> TestPlan`; `run_plan(plan) -> TestResult`; `decide_retest(finding, exploit_blocked, legitimate_flow_ok) -> RetestResult`. Example proof: `{foreign_request:{path:"/…/{id}",account:"A"}, returned:{booking_id:"…",agency_id:"B"}, control:{agency_id:"A"}}`. Use fake discovery objects and fake management adapter locally; replace with Akshat objects and Sujal adapter at integration. Proposed command: `python -m pytest tests/agent`.

## Done and handoff

Done: state decisions are deterministic, safe, auditable, and unsupported/inconclusive paths visible. Hand `ScanRun/Finding/Proposal/RetestResult` to **Sujal** and state semantics to **Vikram**. Avoid trusting status codes, treating cancel as success, or letting management credentials enter executor. Must-have: two rules/approval/retest; optional: additional rule plugins.
