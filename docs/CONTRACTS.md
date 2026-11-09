# VoyageGuard contracts: implemented v1 and legacy runtime

`shared/v1.py` now implements the version **`CONTRACT_VERSION = "1.0"`**. Import domain models from `shared.v1`, e.g. `from shared.v1 import TargetConfig, ObservedRequest, RemediationProposal, ExecutionResult, map_sandbox_execution`. A separate v1 SQLite store is implemented in [`persistence/`](PERSISTENCE.md), but it is **not wired into the runtime agent or dashboard**. `shared/schemas.py` remains the unchanged legacy import used by `agent/app.py`; the dashboard still sends its existing payload, including synthetic tokens. Do not persist or expose that legacy payload as a v1 target config. Sujal owns contract changes after agreement with affected consumers.

V1 entity IDs and foreign keys are UUIDs; meaningful target/account/agency/user identifiers remain strings. Timestamps require timezone-aware UTC and serialize as ISO 8601. Mutable collections use independent factories. V1 models reject unknown fields and credential-shaped fields in nested dictionaries. `AuthorizedAccount.credential_ref` (for example `server:agency-a`) names a server-side lookup; raw tokens belong only in the non-persistable `ServerCredentialConfig`. Do not serialize that configuration. An in-memory reference map is sufficient for this prototype; no vault is specified.

## Implemented v1 models

| Model | Required fields | Optional fields / example |
|---|---|---|
| `TargetConfig` | `id`, `base_url`, `allowed_origins:string[]`, `accounts:AuthorizedAccount[]`, `max_requests:int`, `timeout_seconds:number` | `rate_per_minute=30`, `reference_inventory_id`; account: `{id:"agency-a", agency_id:"agency-a", user_id:"a", credential_ref:"server:agency-a"}` |
| `ObservedRequest` | `capture_id`, `method`, `normalized_path`, `observed_at`, `account_context_id`, `source` | generated `id`, `redacted_headers`, `redacted_body_shape`, `status`; never credentials or raw tokens |
| `Endpoint` | `method`, `normalized_path` | generated `id`, `labels:set<active|zombie|shadow|unknown>`, `evidence:InventoryEvidence[]`, `reachability=unprobed`; active and shadow may coexist, unknown stands alone |
| `InventoryEvidence` | `endpoint_id`, `kind: traffic|reference|history|probe`, `observed_at`, `statement` | generated `id`, `window_start`, `window_end`, `synthetic=true`, `coverage=complete|incomplete` |
| `ScanRun` | `target_id`, `state` | generated `id`, `started_at`, `request_count=0`, `completed_at`, `cancel_reason`; states `queued,running,cancelling,cancelled,failed,completed` |
| `ScanEvent` | `id`, `scan_id`, `at`, `stage`, `message` | `progress` only when measured; polling endpoint is sufficient |
| `TestPlan` | `id`, `scan_id`, `rule_id`, `observed_request_ids`, `account_context_ids`, `budget` | `status`; no seed IDs, management URLs, or expected finding |
| `TestResult` | `plan_id`, `outcome: pass|finding|inconclusive|cancelled|error` | generated `id`, `evidence_ids`, `error` |
| `Finding` | `scan_id`, `rule_id`, `severity`, `business_impact`, `minimal_proof` | generated `id`, `state=verified`; `MinimalProof` has redacted `request`, `response` and `legitimate_control` |
| `RemediationProposal` | `finding_id`, `action_key`, `description` | generated `id`, `state=proposed`; `ActionKey` allows exactly `enforce_booking_ownership`, `validate_quote_fare`, `disable_legacy_booking` |
| `Approval` | `id`, `proposal_id`, `approved_by`, `at`, `decision: approved|rejected` | reason |
| `ExecutionResult` | `id`, `proposal_id`, `action_key`, `state`, `requested_at` | `detail`; states `requested,applied,unsupported,failed,cancelled,indeterminate`; `indeterminate` means an HTTP attempt may have reached management and needs reconciliation; management response redacted |
| `RetestResult` | `finding_id`, `scan_id`, `exploit_outcome`, `legitimate_flow_outcome`, `outcome` | generated `id`, `created_at`, `detail`; each check is `passed,failed,inconclusive,cancelled`, overall outcome is `resolved,failed,inconclusive,cancelled` |
| `RequestAuditEvent` | `id`, `scan_id`, `at`, `method`, `normalized_path`, `purpose`, `outcome` | status, redacted body shape |

## States and APIs

Finding transitions: `verified -> awaiting_approval -> approved -> remediating -> retesting -> resolved`; terminal/non-success states: `open`, `unsupported`, `remediation_failed`, `retest_failed`, `inconclusive`, `cancelled`. Only Ram decides transitions; Sujal persists/transports them. “Resolved” requires `exploit_blocked=true` **and** `legitimate_flow_ok=true`; a 2xx remediation response is not sufficient.

The separate v1 polling transport now implements the routes listed in [Transport](TRANSPORT.md), backed by v1 persistence. Its default app has no domain or inventory implementation and returns 503 for those capabilities. The existing legacy agent API is different. Domain lifecycle enforcement and live service integration remain future work.

## Concrete handoff examples

Akshat: `from shared.v1 import ObservedRequest`. A sandbox custom journey item `{method:"POST",path:"/api/v2/bookings",timestamp:"2026-11-08T10:43:05Z",account_context_id:"agency-a",body:{quote_id:"{quote:agency-a}"}}` maps to `ObservedRequest(capture_id=<UUID>, method="POST", normalized_path="/api/v2/bookings", observed_at=<timestamp>, account_context_id="agency-a", source="synthetic journey recording", redacted_body_shape={"quote_id":"{quote:agency-a}"})`. `capture_id` is assigned by the importer; do not turn placeholders into runtime IDs. The separate simulated history has `coverage=complete|incomplete`; incomplete or missing coverage is not zero traffic. The separate reference inventory and archived route candidate are distinct evidence sources.

Ram: `from shared.v1 import ActionKey, RemediationProposal, map_sandbox_execution, RetestResult`. The sandbox returns `{execution_id,action_key,state,requested_at}` for applied/unsupported. Call `map_sandbox_execution(proposal, response)` with the explicitly approved proposal; it validates action correspondence and sets `proposal_id`. A sanitized failure `{state:"failed",detail:"Management action failed"}` maps with a generated result ID and receipt time. This adapter performs **no approval check, action call, or finding transition**. `RetestResult(exploit_outcome="passed", legitimate_flow_outcome="failed", outcome="failed", ...)` remains distinct from resolution. Ram decides state transitions only after independent HTTP retest.

Vikram: consume future transport JSON, not `shared.schemas` or management credentials. Minimal redacted example: `{"state":"retesting","minimal_proof":{"request":{"path":"/api/v2/bookings/{id}"},"response":{"agency_id":"agency-b"},"legitimate_control":{"agency_id":"agency-a"}}}`. `ExecutionResult.state="applied"` is a control execution state; display `RetestResult.outcome` separately. Current dashboard still uses the legacy agent payload and has not migrated. The server-only HTTP adapter and its `indeterminate` outcome are documented in [Management adapter](MANAGEMENT_ADAPTER.md).
