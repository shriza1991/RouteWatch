# Authoritative contracts (proposed v1)

`shared/schemas.py` is an **existing but incomplete** precursor. Sujal owns the future versioned definitions; consumers request changes from Sujal. All IDs are UUID strings, timestamps are RFC 3339 UTC (`2026-11-05T12:00:00Z`), and API errors are `{code, message, details?, correlation_id}`. Secrets are accepted only in server-side target configuration and are replaced with `[REDACTED]` before storage, events, proofs, or browser responses.

## Models

| Model | Required fields | Optional fields / example |
|---|---|---|
| `TargetConfig` | `id`, `base_url`, `allowed_origins:string[]`, `accounts:AuthorizedAccount[]`, `max_requests:int`, `timeout_seconds:number` | `rate_per_minute`, `reference_inventory_id`; account: `{id:"agency-a", agency_id:"agency-a", user_id:"a", credential_ref:"vault:..."}` |
| `ObservedRequest` | `id`, `capture_id`, `method`, `normalized_path`, `observed_at`, `account_context_id`, `source` | `redacted_headers`, `redacted_body_shape`, `status`; never credentials or raw tokens |
| `Endpoint` | `id`, `method`, `normalized_path`, `labels:set<active|zombie|shadow|unknown>`, `evidence:InventoryEvidence[]` | `reachability: reachable|blocked|unreachable|unprobed` |
| `InventoryEvidence` | `id`, `endpoint_id`, `kind: traffic|reference|history|probe`, `observed_at`, `statement` | `window_start`, `window_end`, `synthetic:boolean` |
| `ScanRun` | `id`, `target_id`, `state`, `started_at`, `request_count` | `completed_at`, `cancel_reason`; states `queued,running,cancelling,cancelled,failed,completed` |
| `ScanEvent` | `id`, `scan_id`, `at`, `stage`, `message` | `progress` only when measured; polling endpoint is sufficient |
| `TestPlan` | `id`, `scan_id`, `rule_id`, `observed_request_ids`, `account_context_ids`, `budget` | `status`; no seed IDs, management URLs, or expected finding |
| `TestResult` | `id`, `plan_id`, `outcome: pass|finding|inconclusive|cancelled|error`, `evidence_ids` | `error` |
| `Finding` | `id`, `scan_id`, `rule_id`, `severity`, `business_impact`, `minimal_proof`, `state` | states below; proof has redacted request, response identity/price evidence, and legitimate control evidence |
| `RemediationProposal` | `id`, `finding_id`, `action_key`, `description`, `state` | action key e.g. `enforce_booking_ownership`; no arbitrary code |
| `Approval` | `id`, `proposal_id`, `approved_by`, `at`, `decision: approved|rejected` | reason |
| `ExecutionResult` | `id`, `proposal_id`, `state`, `requested_at` | states `requested,applied,unsupported,failed,cancelled`; management response redacted |
| `RetestResult` | `id`, `finding_id`, `scan_id`, `exploit_blocked`, `legitimate_flow_ok`, `outcome` | `resolved,failed,inconclusive,cancelled` |
| `RequestAuditEvent` | `id`, `scan_id`, `at`, `method`, `normalized_path`, `purpose`, `outcome` | status, redacted body shape |

## States and APIs

Finding transitions: `verified -> awaiting_approval -> approved -> remediating -> retesting -> resolved`; terminal/non-success states: `open`, `unsupported`, `remediation_failed`, `retest_failed`, `inconclusive`, `cancelled`. Only Ram decides transitions; Sujal persists/transports them. “Resolved” requires `exploit_blocked=true` **and** `legitimate_flow_ok=true`; a 2xx remediation response is not sufficient.

Proposed smallest polling API: `POST /targets`, `POST /scans` (idempotency key), `POST /scans/{id}/cancel`, `GET /scans/{id}`, `GET /scans/{id}/events`, `GET /findings`, `POST /findings/{id}/proposals`, `POST /proposals/{id}/approval`, `POST /proposals/{id}/execute`, `POST /findings/{id}/retest`, `GET /inventory`, `GET /audit`. Mutations require `Idempotency-Key`; repeating returns the original result. Cancellation halts future requests, records `cancelled`, and never resolves findings.
