# Shriraj — Travel sandbox and remediation target

## Mission

Own the synthetic application the team can prove things against: a real HTTP booking journey, deliberately vulnerable/fixed branches, and a local predefined-remediation target. This makes Scenario A/B/C demonstrable without exposing answers to the scanner.

## Ownership

Existing: `sandbox/app.py`, `tests/test_sandbox.py`. Proposed: `sandbox/management/`, `sandbox/fixtures/`, `tests/sandbox/`. Do not edit `agent/`, `discovery/`, `dashboard/`, `shared/`, root Compose, or transport/persistence. See [ownership](../OWNERSHIP.md) and [contracts](../CONTRACTS.md).

## Ordered work

### SHR-01 — Separate application and management surfaces
- **Purpose/behaviour:** retain ordinary quote, confirm, booking, current/retired/shadow APIs; move reset/mode operations behind a proposed local management adapter with predefined action keys `enforce_booking_ownership`, `validate_quote_fare`, `disable_legacy_booking` only.
- **Files:** modify existing `sandbox/app.py`; create proposed `sandbox/management/api.py`.
- **Input/output/interfaces:** consumes server-only approved `action_key`; emits `ExecutionResult`, never finding truth. Application endpoints consume synthetic headers and return booking/quote data.
- **Edges:** duplicate action is idempotent; unsupported key returns `unsupported`; failed operation returns `failed`; management credentials/URL never appear in app responses.
- **Dependency:** Sujal provides contract; Ram calls adapter only after approval.
- **Acceptance/evidence:** application scanner cannot enumerate management route; curl/test proves each action, unsupported action, and reset.

### SHR-02 — Deterministic synthetic data and traffic fixtures
- **Purpose/behaviour:** seed Agency A/B, isolated bookings, quote price, timestamped synthetic traffic with explicit observation window.
- **Files:** existing `sandbox/app.py`; proposed `sandbox/fixtures/*.json`, seed/reset command.
- **I/O:** output normal journey records for Akshat; never seeded booking IDs or private expected finding to Ram.
- **Edges:** reset is repeatable; no real PII/payment; history marked synthetic.
- **Acceptance:** A/B own records differ; legacy reachable pre-fix; shadow UI route used; fixture validation test.

### SHR-03 — Scenario behavior and tests
- **Purpose:** vulnerable foreign read and client fare storage; fixed ownership and server quote fare; legacy disabled/restricted after action.
- **Files:** existing test plus proposed `tests/sandbox/test_management.py`.
- **I/O:** ordinary HTTP verifies behavior; management changes only preimplemented state.
- **Edges:** own access survives ownership fix; normal confirmation survives fare fix; management success alone proves nothing.
- **Acceptance:** unit/component test evidence for vulnerable/fixed/unsupported/reset.

## Interfaces and examples

Application: `POST /api/v2/quotes {route}` → `{quote_id,fare}`; `POST /api/v2/bookings {quote_id,traveler,fare}` → `{booking_id,agency_id,fare,quote_fare}`; `GET /api/v2/bookings/{id}`. Proposed management: `POST /management/actions {action_key,idempotency_key}` → `{execution_id,state:"applied"}`. It is server-to-server only.

## Independent development

Stub Akshat input with `sandbox/fixtures/normal-journey.json`; stub management caller with a local signed test request. Replace it when Sujal injects the adapter and Akshat imports the fixture, not by giving either source/database access. Existing command: `python -m pytest tests/test_sandbox.py`; proposed: `python -m pytest tests/sandbox`.

## Done and handoff

Done means all three scenarios are HTTP-verifiable, synthetic, resettable, and management is separate. Hand off fixture schema to **Akshat**, endpoint behavior/test evidence to **Ram**, management capability list to **Sujal**. Avoid the common mistake of returning “vulnerable” metadata or putting management credentials in traffic. Must-have: three scenarios and actions; optional: richer journey UI.
