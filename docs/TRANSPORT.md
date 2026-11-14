# V1 transport (separate, incomplete runtime)

Run from the repository root with `VOYAGEGUARD_V1_DB` pointing to a **separate** SQLite file:

```powershell
$env:VOYAGEGUARD_V1_DB = 'C:\Users\dyara\RouteWatch\data\voyageguard-v1.db'
python -m uvicorn transport.api:app --host 127.0.0.1 --port 8012
```

This starts the polling API and durable store. The same default app can run with `docker compose --profile v1 up --build -d` on host port 8012, using its own persistent volume. The default runtime now injects a read-only `FixtureInventoryService` for the four repository-owned synthetic discovery inputs, so `GET /v1/inventory?target_id=local-sandbox` returns evidence-backed fixture inventory. It performs no network probes; the archived route remains `unknown` until positive reachability evidence is supplied. Scan, finding, proposal, approval, execution and retest commands still return an honest 503 where their domain capability is not injected. The legacy agent/dashboard entrypoints remain unchanged.

## Factory and owner interfaces

`create_app(*, store: V1Store, credential_resolver: CredentialResolver | None, domain: DomainService | None, inventory: InventoryService | None, management_adapter: SandboxManagementAdapter | None, reviewer_id='local-demo-reviewer') -> FastAPI` is in `transport.api`. `CredentialResolver.has_reference(reference) -> bool` checks a server-side reference without returning a token to the browser. `DomainService` must implement `start_scan(target, credentials)->ScanRun`, `cancel_scan(scan)->ScanRun`, `propose(finding)->RemediationProposal`, `approve(proposal, reviewer_id, decision)->Approval`, `execute(proposal, approval, attempt_id, adapter)->ExecutionResult`, and `retest(finding)->RetestResult`. `InventoryService.list_endpoints(target_id)->list[Endpoint]` supplies Akshat's results. See the Protocol definitions for exact annotations. Test doubles are in `tests/integration/test_transport.py` only.

The local-demo reviewer ID is set by the server factory, not accepted as `approved_by` from a browser. This is a demonstration context, not authenticated reviewer identity or enterprise access control. Ram must implement authoritative reviewer policy and eligibility checks. Transport loads the persisted proposal and approval and passes them to `DomainService.execute`; it does **not** call the management adapter directly. Missing/rejected approval returns 409 before domain/adapter execution. A previous `indeterminate` execution blocks a new execution key pending reconciliation; identical completed request retries replay the original response.

## Implemented routes

All routes are under `/v1`; mutations require `Idempotency-Key` and return v1 Pydantic models. Errors are sanitized `{code,message}`. Invalid request bodies return 422; missing records return 404; key conflicts and pending/reconciliation cases return 409.

| Method/path | Source or command |
|---|---|
| `POST /scans` | body `{"target":<v1 TargetConfig>}`; domain starts scan |
| `GET /scans?target_id=...`, `GET /scans/{id}`, `GET /scans/{id}/events` | durable polling |
| `POST /scans/{id}/cancel` | domain cancellation decision |
| `GET /findings?scan_id=...`, `GET /findings/{id}` | durable findings |
| `GET /inventory?target_id=...` | injected Akshat inventory interface |
| `POST /findings/{id}/proposals`, `GET /proposals?finding_id=...` | domain proposal, durable list |
| `POST /proposals/{id}/approval` | body `{"decision":"approved"}` or `rejected`; domain policy, server reviewer context |
| `GET /approvals?proposal_id=...` | durable approval |
| `POST /proposals/{id}/execute`, `GET /executions?proposal_id=...` | domain eligibility and adapter, durable outcome |
| `POST /findings/{id}/retest`, `GET /retests?finding_id=...` | domain retest decision and durable outcome |
| `GET /audit?scan_id=...` | durable redacted request audit |

Example scan request uses credential references only:

```json
{"target":{"id":"local-sandbox","base_url":"http://127.0.0.1:8000","allowed_origins":["http://127.0.0.1:8000"],"accounts":[{"id":"agency-a","agency_id":"agency-a","user_id":"a","credential_ref":"server:agency-a"},{"id":"agency-b","agency_id":"agency-b","user_id":"b","credential_ref":"server:agency-b"}],"max_requests":30,"timeout_seconds":3}}
```

Only server-side injection can provide a resolver or management adapter; management URL/token are not request fields, stored v1 payloads, or ordinary executor configuration. The API contains no management-control route. Polling lists use the v1 store's deterministic order and parent filters.

## Idempotency and crash window

Each mutation reserves `(operation,resource,Idempotency-Key)` with a canonical request fingerprint. Completed identical requests replay the persisted model; conflicting payloads return 409. An existing pending reservation returns 409 and does not invoke the domain again. For an execution, the attempt UUID is derived from proposal ID and HTTP key and passed to Ram's explicit `execute` interface; it is distinct from the HTTP key. An `indeterminate` result is stored as supplied and never changes the finding to resolved.

The reservation commits before a domain call. A crash after an external management HTTP request and before result persistence leaves `pending`; both the same key and a new key are blocked for execution. Transport cannot establish whether the action ran. Ram/Sujal must reconcile against sandbox state/idempotency before retry. Sandbox reset/manual mode changes clear its idempotency history. No exactly-once cross-service guarantee is claimed.

## Discovery inventory implementation on the transformation branch

`discovery.inventory` provides normalized route identity, HAR import, JavaScript route-literal extraction and evidence-aware classification. `discovery.runtime.FixtureInventoryService` loads the journey recording, reference inventory, historical traffic and archived-route candidate independently. The v1 app injects this service by default for `local-sandbox`; it never probes a host. `active` requires observed journey traffic, `shadow` means traffic absent from the reference snapshot, and `zombie` requires complete zero-traffic history plus an explicit reachable result. Missing/incomplete evidence remains `unknown`. `discovery.changes` compares normalized inventory snapshots and maps added travel routes to bounded test families; it is currently a library capability, not yet a deployment webhook or persisted change-event API.

## Remaining handoffs

- **Ram:** implement the `DomainService` protocol, authoritative approval/transition/eligibility checks, scan/retest orchestration and safe credential use. The test double is not a runtime service.
- **Akshat:** extend discovery beyond the initial synthetic inputs (real approved HAR/gateway/JS sources), add authenticated bounded reachability probes and persist snapshots/change events. The current default service is read-only fixture inventory.
- **Vikram:** switch to these polling models only when the domain and inventory capabilities are integrated; render `503`, `pending_reconciliation` and `indeterminate` explicitly. Do not call management directly.
- **Sujal:** inject real services, configure server-only credential references and management adapter, migrate or deliberately discard legacy runtime data, and add an authenticated reviewer mechanism before anything beyond the local demo. Compose now provides only the separate opt-in process and database; it does not supply missing domain implementations. Existing agent tables are untouched.

Verified on 2026-11-08: `python -m pytest tests/integration/test_transport.py -q` (6 passed) and `python -m pytest -q` (94 passed; two existing FastAPI deprecation warnings).
