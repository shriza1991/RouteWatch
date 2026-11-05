# VoyageGuard project scope

## Repository assessment

This repository already implements a small RouteWatch prototype: `sandbox/app.py` provides a synthetic FastAPI target with vulnerable/fixed ownership and fare behavior; `agent/app.py` runs HTTP checks and persists scan data; `dashboard/` renders results; `shared/schemas.py` has an initial contract set. Docker Compose starts all three. The implemented flow is scan → finding → manual sandbox mode switch → fresh scan/retest. It does **not** yet implement approval-gated remediation, a separate management adapter, true traffic capture/import modules, a state machine, or the detailed contracts in this documentation.

VoyageGuard remains a prototype for a synthetic B2B travel sandbox only. It demonstrates: **observe traffic → discover APIs → plan relevant checks → test safely → verify → request an approved predefined sandbox remediation → independently retest → report**. Rule-driven planning is deliberate; there is no LLM, source repair, production deployment, real customer data, payment rail, or external target.

## Documentation index

- [Architecture](ARCHITECTURE.md): current and proposed boundaries.
- [Contracts](CONTRACTS.md): the sole normative shared-interface specification.
- [Ownership](OWNERSHIP.md): one owner for every path and deliverable.
- [Integration plan](INTEGRATION_PLAN.md): staged handoffs.
- [Demo acceptance](DEMO_ACCEPTANCE.md): 3–5 minute script and pass criteria.
- Role guides: [Shriraj](roles/SHRIRAJ.md), [Akshat](roles/AKSHAT.md), [Ram](roles/RAM.md), [Vikram](roles/VIKRAM.md), [Sujal](roles/SUJAL.md).

## Non-goals

Full marketplace behavior; real suppliers/payments; broad vulnerability scanning; OAuth/SSO; enterprise RBAC; arbitrary AI patches; complex multi-agent orchestration; distributed infrastructure; production security guarantees. An endpoint becoming documented reconciles inventory; it is not a security remediation.

## Terminology

“Implemented” means present in this repository at documentation time. “Proposed” means a required future deliverable and must not be represented as working in the demo. “Synthetic” applies to accounts, bookings, HAR/history fixtures, and all demonstration traffic.
