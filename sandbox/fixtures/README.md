# Synthetic discovery handoff (schema 1.0)

All files here are demonstration data, not measurements of real customers or production traffic. `journey-recording.v1.json` is a **custom journey recording**, not HAR. The recorder makes ordinary HTTP requests and records their actual statuses/responses with UTC timestamps. It then replaces live quote and booking IDs with per-agency placeholders. No management request, credential, or vulnerability answer is part of the recording.

Reset first through the separate authenticated management app; generation does not reset or change controls. With travel on port 8000 and management on port 8001:

```powershell
$headers = @{ Authorization = "Bearer $env:SANDBOX_MANAGEMENT_TOKEN" }
Invoke-RestMethod -Method Post http://127.0.0.1:8001/management/reset -Headers $headers
python -m sandbox.fixtures.record --base-url http://127.0.0.1:8000 --output sandbox/fixtures/journey-recording.v1.json
```

`SANDBOX_DB` must point both services to the same SQLite database. The script is safe to repeat after each explicit reset. It performs A/B quote → legitimate confirmation → own read, then preferences. It captures responses and replaces `quote_id`/`booking_id` with `{quote:agency-a}`, `{booking:agency-a}`, etc. `path` for a read is `/api/v2/bookings/{id}`. `account_context_id` is the explicitly supplied synthetic agency; `ui` denotes the preferences request. `timestamp` is a recorded UTC instant. `observation_window` bounds those instants. `schema_version`, `synthetic`, `provenance`, and `format` identify the artifact. The legacy `requests[].method/path/body/status` fields remain for the current agent consumer. New fields are `requests[].timestamp/account_context_id/source/response` and top-level metadata. This is a sandbox-owned recording format; mapping to proposed `ObservedRequest` is Akshat's responsibility (`timestamp→observed_at`, `path→normalized_path`, `account_context_id` unchanged).

`reference-inventory.v1.json` is a separate supplied inventory; it includes current and retired routes, and omits preferences. `historical-traffic.v1.json` is **simulated** over 2026-01-01 through 2026-01-02 UTC. Current routes and preferences have positive legitimate counts. The retired route's last legitimate request precedes the window and its complete-window count is zero. A history record with `coverage: incomplete` must have `legitimate_requests_in_window: null`; this means unknown, never confirmed zero. `archived-routes.v1.json` is a separate candidate for a narrow reachability probe, not traffic evidence. None of these files contains classification labels.

Handoff to Akshat: import recording, reference, historical traffic, and archived candidate as four distinct sources. Validate with `sandbox.fixtures.validate`; do not infer the target's private control state from these files. The recording is served at `/ui/traffic-recording` after validation. Because timestamps are generated at recording time, byte-for-byte output varies; the journey sequence, account relations, paths and amounts are repeatable after reset.
