# Demo acceptance

The authoritative current walkthrough and acceptance matrix are maintained in [DEMO.md](DEMO.md).

## Current v1 demonstration

1. Start the default Docker Compose stack with distinct generated values for `SANDBOX_MANAGEMENT_TOKEN` and `VOYAGEGUARD_REVIEWER_TOKEN`.
2. Reset only the bundled synthetic sandbox to vulnerable mode using the private management service.
3. Open the dashboard and start a scan against `http://sandbox:8000`.
4. Inspect persisted scan events, request audit, fixture-backed endpoint inventory and findings.
5. Verify the cross-agency proof: Agency A can read its own synthetic booking, but the vulnerable behavior discloses Agency B's booking.
6. Verify fare tampering using a subsequent persisted booking read, not only the immediate response.
7. Create a predefined proposal, approve it with the reviewer token, execute the server-side management action, and independently retest.
8. Show exploit and legitimate-flow outcomes separately. Only both passing permits a `resolved` result.

## Verified CI acceptance

GitHub Actions run 33 passed on implementation commit `1fb96d75465343025db547078b749edcf7f1a051`:
- Python compile and test suite: 140 passed.
- Dashboard component tests: passed.
- Dashboard production build: passed.
- Docker Compose configuration validation: passed.

## Boundaries

The v1 scanner currently verifies cross-agency booking access and persisted fare tampering in the synthetic sandbox. Change intelligence compares persisted inventory snapshots; live deployment hooks and automatic targeted dispatch are not implemented. Duplicate refunds, cancellation abuse, payment bypass, coupon reuse, role escalation and supplier-boundary tests remain outstanding. Browser E2E and production identity/SSO are also outstanding.

Never use production targets, real TBO services, customer records or real financial operations in this demo.
