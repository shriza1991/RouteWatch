# 2–3 minute local demo

Start from [README.md](README.md): set a private `SANDBOX_MANAGEMENT_TOKEN`, then `docker compose up --build -d`. Open <http://localhost:5173>. This is the **working legacy demo**, with synthetic accounts and simulated historical traffic.

1. **Reset (operator):** `docker compose exec -T management python scripts/management_request.py reset`. This authenticated command clears target quotes/bookings and action keys, and disables all controls. It does not clear agent scan history.
2. **Discover and scan:** click **Start scan**. Wait for completion. Show cross-agency evidence containing B's booking identity under A's request, the stored fare proof, inventory evidence and request audit. The agent uses a custom recorded journey; archived endpoint, reference list and simulated history are separate fixture inputs.
3. **Remediate manually:** run the three predefined actions with fresh idempotency keys:

   ```powershell
   docker compose exec -T management python scripts/management_request.py action enforce_booking_ownership demo-ownership-1
   docker compose exec -T management python scripts/management_request.py action validate_quote_fare demo-fare-1
   docker compose exec -T management python scripts/management_request.py action disable_legacy_booking demo-legacy-1
   ```

   Check <http://localhost:8000/sandbox/status> for `fixed` and all controls true. `applied` only means a target control was enabled.
4. **Retest:** click **Retest after fix** on both findings and wait for fresh scans. The legacy implementation reports pass when a scan completes without the same finding kind. This is not v1 independent proof replay or approved remediation. Sandbox acceptance tests separately verify legitimate and exploit HTTP behavior after each control.
5. **Inventory change:** click **Simulate deployment + scan**. This local event/reference profile change does not deploy code or alter controls. The retired route is disabled and preferences are documented in the second profile. Historical logs are simulated, not measured traffic.

To repeat, run authenticated reset, then launch a new scan. Ordinary Compose restarts retain database volumes. To regenerate the normal journey fixture, reset first and run `python -m sandbox.fixtures.record --base-url http://127.0.0.1:8000 --output sandbox/fixtures/journey-recording.v1.json` from the host, then rebuild the sandbox image. The recorder never calls management.

The separate `v1-transport` profile on port 8012 is **not** part of this live loop. It has polling and persistence but no Ram domain service, Akshat inventory service, or connected approval/execution/retest orchestration; unavailable commands return 503. Management credentials remain inside management and are never sent to the dashboard or legacy scanner.
