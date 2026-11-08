# Shriraj sandbox handoff

## What is implemented

The synthetic travel target is a separate FastAPI app (`sandbox.app:app`). It has Agency A/B headers, quotes, bookings, current and retired booking reads, preferences, read-only status, and a validated custom journey recording. Three independent controls persist in SQLite. The management app (`sandbox.management.api:app`) is a second FastAPI app with bearer authentication, three predefined actions, idempotency records, authenticated reset and whole-mode operations. It is not mounted on the travel app. Both apps initialise the same database without clearing existing data. The 51 sandbox tests exercise the three vulnerable → action → ordinary HTTP retest scenarios.

The agent's approval, remediation decision, finding lifecycle, and inventory classification are **not** implemented here. `applied` means a predefined target control was enabled; it does not assert a security finding is resolved. There is no arbitrary patch generation.

## Local startup and demo commands

Install root `requirements.txt` in your chosen Python environment. Use an explicit local database path and a server-only secret. Each shell that launches an app needs the same `SANDBOX_DB` value. The default app ports are travel **8000** and management **8002** here, because the existing agent uses 8001; management itself can run on any separate loopback port.

Travel shell:

```powershell
$env:SANDBOX_DB = 'C:\Users\dyara\RouteWatch\sandbox-demo.db'
python -m uvicorn sandbox.app:app --host 127.0.0.1 --port 8000
```

Management shell:

```powershell
$env:SANDBOX_DB = 'C:\Users\dyara\RouteWatch\sandbox-demo.db'
$env:SANDBOX_MANAGEMENT_TOKEN = 'replace-with-a-private-local-token'
python -m uvicorn sandbox.management.api:app --host 127.0.0.1 --port 8002
```

Operator shell (supply the token securely to this shell; do not pass it to the browser or agent test executor):

```powershell
$headers = @{ Authorization = "Bearer $env:SANDBOX_MANAGEMENT_TOKEN" }
Invoke-RestMethod -Method Post http://127.0.0.1:8002/management/reset -Headers $headers
$body = @{ action_key = 'enforce_booking_ownership'; idempotency_key = 'demo-ownership-1' } | ConvertTo-Json
Invoke-RestMethod -Method Post http://127.0.0.1:8002/management/actions -Headers $headers -ContentType 'application/json' -Body $body
Invoke-RestMethod -Method Post http://127.0.0.1:8002/management/mode/fixed -Headers $headers
Invoke-RestMethod -Method Post http://127.0.0.1:8002/management/mode/vulnerable -Headers $headers
```

Fixture generation requires an explicit authenticated reset first. Then:

```powershell
python -m sandbox.fixtures.record --base-url http://127.0.0.1:8000 --output sandbox/fixtures/journey-recording.v1.json
```

The recorder never calls management or resets state. It uses real application HTTP requests and fails if a legitimate step fails. Run it from the repository root. The management process fails startup if `SANDBOX_MANAGEMENT_TOKEN` is missing or blank.

## HTTP contracts and examples

Travel requests use synthetic `X-Agency: agency-a|agency-b` and a nonempty `X-User`. These are demo identities, **not secure production authentication**. `POST /api/v2/quotes` with `{"route":"DEL-BOM"}` returns `{"quote_id":"<runtime UUID>","route":"DEL-BOM","fare":120.0}`. `POST /api/v2/bookings` with `{"quote_id":"<quote UUID>","traveler":"Synthetic traveler","fare":120.0}` returns `{"booking_id":"<runtime UUID>","agency_id":"agency-a","fare":120.0,"quote_fare":120.0}`. `GET /api/v2/bookings/{id}` returns the stored booking; `GET /api/v1/bookings/{id}` does likewise while enabled, then returns 410 when disabled. `GET /api/ui/preferences` returns currency data. `GET /sandbox/status` returns `{mode,synthetic,controls}`; mode is `vulnerable` (all false), `fixed` (all true), or `mixed`. `GET /ui/traffic-recording` serves the validated saved recording. No management path is registered on this app.

Management requires `Authorization: Bearer <SANDBOX_MANAGEMENT_TOKEN>` on every operation and has no CORS, OpenAPI or docs. `POST /management/actions` accepts exactly `{action_key,idempotency_key}`. A successful response is `{"execution_id":"<UUID>","action_key":"enforce_booking_ownership","state":"applied","requested_at":"<UTC timestamp>"}`. An unknown action returns `unsupported` without changing controls. Same key + same action returns the original result; same key + different action returns 409. Invalid bodies return 422; missing/wrong token returns 401. Unexpected execution errors roll back and return a sanitized `failed` response.

| Action key | Persisted control | Observable effect |
|---|---|---|
| `enforce_booking_ownership` | same name | A reading B's booking returns 403 on current and enabled retired routes; own reads succeed |
| `validate_quote_fare` | same name | stored fare comes from server quote despite changed submitted fare |
| `disable_legacy_booking` | same name | retired booking route returns 410; current route remains usable |

`POST /management/reset` atomically clears quotes, bookings and action records, then disables all controls. It returns `{"ok":true,"mode":"vulnerable"}`. `POST /management/mode/fixed|vulnerable` atomically sets all controls and clears prior action records, so an old idempotency result cannot be replayed after a manual mode change. Unsupported modes return 400 without mutation. These mode operations are demo controls, not approvals.

## Fixture handoff

See [fixtures/README.md](fixtures/README.md) for the version 1.0 custom recording schema, placeholders and generation procedure. All four inputs explicitly declare `synthetic: true` and provenance:

- [journey recording](fixtures/journey-recording.v1.json): A/B quote → normal booking → own read plus preferences, actual response/status and UTC capture time, normalized IDs. Served by `/ui/traffic-recording`.
- [reference inventory](fixtures/reference-inventory.v1.json): current and retired routes, with preferences intentionally absent; no classification labels.
- [simulated historical traffic](fixtures/historical-traffic.v1.json): explicit 2026-01-01–02 UTC window, positive counts for current routes/preferences, complete zero-window count and earlier last use for retired route. These counts are fabricated demonstration assumptions, not measured traffic.
- [archived route candidate](fixtures/archived-routes.v1.json): retired route for a narrow reachability probe; this is not legitimate traffic.

Incomplete history uses `coverage: incomplete` and a null count; it cannot establish zero traffic. The recording uses live capture timestamps, so file bytes change when regenerated even though the normalized journey is repeatable.

## Verification and handoffs

Run from the repository root:

```powershell
python -m pytest tests/test_sandbox.py tests/test_sandbox_management.py tests/test_sandbox_fixtures.py tests/test_sandbox_acceptance.py -q
```

Verified in this handoff: **51 passed, 2 FastAPI startup deprecation warnings**. The acceptance module proves each scenario separately, action sequencing, idempotent replay, denied unauthenticated actions, reset and another cycle, and absence of management traffic in the recording.

- **Akshat:** import the four fixture files as separate sources. Map `timestamp→observed_at`, `path→normalized_path`, and preserve `account_context_id`; classification and evidence synthesis belong to discovery.
- **Ram:** use fresh A/B baselines and compare returned booking identity/agency or persisted fare, not HTTP status alone. The management action contract above is server-side; approval enforcement, failure handling and independent retest lifecycle belong to the agent.
- **Sujal:** run management as a separate loopback process with a server-only token and the same `SANDBOX_DB`; wire it into deployment without exposing it to browser/test executors. Replace root README/DEMO references to removed travel `/sandbox/reset` and `/sandbox/mode/{mode}` routes. Existing Compose does not start management.
- **Vikram:** show `vulnerable`, `mixed`, and `fixed` status semantics and backend evidence shapes through the agent API. Never put the management token or direct management calls in frontend code.

## Known limits and compatibility breaks

Travel identity is a trusted synthetic header pair, not a real auth system. The root travel UI is informational and does not yet implement an interactive login/quote/booking journey; the recorder performs those HTTP steps. The fixture history is simulated. The sandbox management response is local and does not carry a proposal or approval ID from the proposed shared `ExecutionResult` contract; Sujal/Ram must map it when integrating. Root docs and Compose still use the pre-isolation startup flow. Old travel mutation routes now return 404; clients must use authenticated management routes. These are the remaining items before Shriraj's full documented scope, particularly the minimal interactive journey UI, can be called complete.
