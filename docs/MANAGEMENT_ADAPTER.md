# Server-only sandbox management adapter

Implemented in `transport.management_adapter`. It is **not connected to public routes or the running agent**. Ram's domain layer chooses a predefined proposal and performs authoritative approval lookup/policy. This adapter checks that the supplied `Approval` is approved and references the supplied `RemediationProposal`; it does not approve, choose a fix, or resolve a finding.

## Configuration and call

Set `SANDBOX_MANAGEMENT_URL` to a bare origin such as `http://127.0.0.1:8002`, and set `SANDBOX_MANAGEMENT_TOKEN` in the server process only. `ManagementConfig.from_env()` rejects missing/blank values. HTTPS origins are accepted; prototype HTTP is limited to loopback. Embedded user credentials, path, query, fragment, invalid ports and other schemes are rejected. Configuration is separate from `TargetConfig`, account credential references, browser payloads and the attack executor. Never persist the token or pass it to the dashboard.

```python
from uuid import uuid4
from transport.management_adapter import ManagementConfig, SandboxManagementAdapter

adapter = SandboxManagementAdapter(ManagementConfig.from_env())
attempt_id = uuid4()  # persist with the proposal before the first call
result = adapter.execute(proposal, approval, attempt_id)
```

Signature: `SandboxManagementAdapter(config: ManagementConfig, client: httpx.Client | None = None)` and `execute(proposal: RemediationProposal, approval: Approval, attempt_id: UUID) -> ExecutionResult`. An injected HTTPX client/MockTransport supports tests. The method sends exactly one bounded `POST` to `/management/actions`, with a bearer header and `{action_key,idempotency_key}`. It disables redirect following even if the injected client enables it. The idempotency key is a deterministic UUID derived from `proposal.id` and `attempt_id`; reuse that attempt ID on retry. It never accepts a path or URL from a proposal or browser.

## Outcome meanings

`applied`, `unsupported`, and explicit sanitized management `failed` responses map through the pure v1 response adapter. `failed` with `authentication_rejected` means 401/403; `idempotency_conflict` means 409. Unexpected 5xx, malformed response, redirect, and transport errors return `indeterminate` with a fixed reason code. A timeout can occur after the sandbox applied the control, so `indeterminate` requires reconciliation and never means definitely not applied. No upstream error body, token or Authorization header is copied into `ExecutionResult` or exceptions. `ExecutionResult` has no finding-resolution field; ordinary HTTP exploit and legitimate-flow retests are separate Ram-owned decisions.

There is no automatic retry. For an indeterminate result, the caller may retry with **the same** `attempt_id` after checking state or reconciling. The sandbox deduplicates by key while its management history exists. Authenticated reset and manual mode changes clear that history, so a later same-key call may execute again. Persist attempt IDs and outcomes in Sujal's v1 store when transport is wired; do not claim exactly-once effects across SQLite and HTTP or complete crash recovery.

Test: `python -m pytest tests/integration/test_management_adapter.py -q`. Ram still owns authoritative approval enforcement and lifecycle; Sujal still owns server-only environment wiring, persistence integration and public transport routes. The current agent imports legacy contracts and does not use this adapter.
