# SUJ-03B container integration status — 2026-11-09

## Actual verification

Docker Engine `29.6.1` was available. Two smoke runs passed in **isolated Compose projects** (`routewatch-suj03b-f81381a2` and `routewatch-suj03b-8606beac`) with new database volumes and separate host ports. The second run verified the repeatable dynamic-port runner. Both reused the operator-supplied token already inside the existing management container without printing it. No existing volume was removed or reset. The smoke containers were stopped after verification, with their volumes retained.

The runner is [scripts/container_smoke.py](../scripts/container_smoke.py). It requires `SANDBOX_MANAGEMENT_TOKEN` in its process environment and chooses unused host ports for each new project. From an operator PowerShell session with a token already set:

```powershell
python scripts/container_smoke.py
```

It executes bounded `docker compose -p <generated-project> up --build -d`, HTTP readiness polling, `docker compose exec -T management python scripts/management_request.py ...`, real travel/agent/v1 requests, `docker compose restart`, opt-in `--profile v1` startup, then `docker compose stop`. It does not delete any volume. For these verified runs the command was invoked with the token inherited privately from the already running operator-configured management container. Do not print `docker compose config` or container environments when using a real token.

Observed results, in order:

| Check | Result |
|---|---|
| Default build/start and readiness | All four services ready; authenticated reset returned `{"ok":true,"mode":"vulnerable"}` |
| Legacy scan | Scan `a7fe287a-ad30-4d7b-a9de-c6c610221f43` completed; both `cross_agency_access` and `fare_tampering` findings had matching response evidence |
| Finding proof | Ownership proof returned Agency B's booking ID/agency under Agency A's request, distinct from A's legitimate control; fare proof's modified amount matched a subsequent stored booking read and differed from the quote |
| Ownership action only | Management returned `applied`; A→B returned 403, A→A and B→B returned their IDs; a fresh modified fare still persisted; other controls remained false |
| Fare action | Management returned `applied`; a fresh modified confirmation stored the server quote amount; normal B booking succeeded |
| Legacy action | Management returned `applied`; retired booking read returned 410; current booking read still returned the booking; status became `fixed` |
| Legacy retest | Both `POST /findings/{id}/retest` calls produced completed fresh scans and persisted `passed=1, legitimate=1` rows |
| Restart | `docker compose restart` completed; sandbox remained `fixed`, and original scan/findings remained in agent history |
| Reset/repeat | Authenticated reset returned `vulnerable`; cross-agency read, fare tampering and retired route worked again; second scan `32b7ba15-fa64-4ac1-8694-2a91d8fb397c` reproduced both findings |
| Opt-in v1 | `v1-transport` became ready; `GET /v1/scans` returned `[]`; valid scan creation and inventory requests returned sanitized 503 `capability_unavailable` |
| Exposure | Management has no host-published port; dashboard and agent Compose configuration contain no management token; served dashboard source did not contain its value |

`python -m pytest -q` passed **94 tests** with two existing FastAPI startup deprecation warnings. `python -m py_compile scripts/container_smoke.py scripts/management_request.py` and `git diff --check` passed. Container image builds and restarts passed in both smoke runs. The manual browser interaction was not automated; the runner exercised the same legacy HTTP paths used by the dashboard.

## Implemented boundaries and limits

The **legacy** agent performs rule-driven synthetic scans through HTTP and persists scans, findings, audits and its retest rows in `AGENT_DB`. The three predefined sandbox actions are reachable only via authenticated management HTTP; travel `/sandbox/reset` and `/sandbox/mode/...` are absent. Sandbox controls and management records share `SANDBOX_DB`, separate from agent data.

The **standalone v1** store, contracts, polling routes and management adapter are implemented. The default v1 app has no injected domain, credential resolver, inventory service or management adapter. Its honest 503 is a capability boundary, not a successful detection/approval workflow. V1 records are in a separate persistent database and are not migrated from legacy data.

The legacy retest's `passed` flag means its fresh scan completed without generating a finding of the same kind. It does **not** replay and compare the original exploit proof, independently verify each legitimate workflow, consult an approval record, or produce a v1 resolution decision. The direct HTTP smoke assertions and sandbox acceptance tests provide stronger evidence of the three target controls. Historical traffic remains synthetic. No external target or customer data was used.

No container behavior failed in the verified run. Unverified: browser rendering/click path, real staging integration, reviewer identity, v1 live domain/discovery wiring, cross-service crash reconciliation, and production auth/scope isolation.

## Owner handoffs

- **Ram:** implement `transport.api.DomainService` using authoritative persisted proposal/approval lookup and policy. Provide real scan events, safe execution eligibility, original exploit replay, legitimate flow checks, cancellation, and finding transitions. The legacy same-kind absence heuristic is insufficient for verified resolution. Keep `ExecutionResult.applied` distinct from a passed retest.
- **Akshat:** implement `InventoryService.list_endpoints(target_id)` from the four distinct sandbox sources. Preserve complete versus incomplete synthetic history and reachability evidence; do not convert a missing history window into confirmed zero traffic. Supply actual `Endpoint` evidence to the v1 API.
- **Vikram:** keep management credentials and endpoints out of the browser. Once v1 live capabilities exist, migrate the dashboard to v1 polling/approval/retest models and display `503`, pending/indeterminate execution and separate exploit/legitimate outcomes accurately. The current dashboard was not browser-tested in this run.
- **Sujal:** inject real services and server-side credential references into the v1 factory, decide legacy data migration or coexistence, and add reconciliation and authenticated reviewer context at the transport boundary. Do not silently use the static `local-demo-reviewer` as authenticated identity.

**Reviewer identity decision required:** choose and document how a local reviewer is authenticated and bound to `Approval.approved_by` before calling v1 approval authenticated. The current server-configured demo reviewer string prevents browser spoofing but does not prove a human identity. Ram then owns approval policy and execution eligibility using that authoritative context.

## First live v1 loop checklist

1. Inject Akshat's inventory and Ram's domain service plus a server-side credential resolver into `create_app`; retain v1's separate database.
2. Establish authenticated reviewer context and policy; persist proposals/approvals and reject unrelated or rejected decisions.
3. Run a real scan and persist redacted observations, events, findings, request audit and inventory evidence.
4. Request one predefined proposal, approve it through the chosen reviewer boundary, and execute through Ram's domain eligibility interface and the server-only management adapter.
5. Reconcile pending/indeterminate attempts before retrying; preserve one management idempotency key per execution attempt.
6. Independently replay the exploit proof and legitimate baseline over HTTP, persist both outcomes, and mark resolved only when both pass.
7. Poll the v1 API and display actual states in Vikram's dashboard; repeat after restart.
