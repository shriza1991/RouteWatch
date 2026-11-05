# Integration plan

## 1. Contract agreement and skeletons

Entry: all members have read [Contracts](CONTRACTS.md). Sujal creates versioned contract skeletons, transport/persistence interfaces and fixtures; each owner creates their empty module boundary. Exit: validated sample JSON traverses dashboard fixture → transport → domain fixture. Blocking: no production code against unagreed fields. Independent: role-local test harnesses.

## 2. Fixture-based development

Shriraj supplies synthetic app and management fixtures; Akshat supplies redacted traffic/reference/history fixtures; Ram supplies deterministic `TestPlan` fixtures; Vikram renders fixture states; Sujal supplies SQLite/API fakes. Integrate in this order: schemas, discovery output, agent domain output, transport, dashboard. Exit: every module works without another module’s source. 

## 3. Cross-agency vertical slice

Entry: two configured accounts and observed booking request shape. Ram verifies foreign returned booking identity plus own control; Vikram presents proposal/approval/retest states; Shriraj implements `enforce_booking_ownership`; Sujal wires approval-gated management adapter/persistence; Akshat refreshes observations. Exit: vulnerable finding, approved action, blocked exploit, retained legitimate access, resolved only after both checks. Blocking: management separation and contracts.

## 4. Fare tampering

Add quote/confirmation rule and `validate_quote_fare` predefined action. Exit: stored synthetic fare proof, correction/rejection after approval, normal booking passes. Work can proceed independently in Shriraj/Ram fixtures until transport integration.

## 5. Inventory case

Akshat integrates reachability/reference/history evidence; Shriraj disables retired API; Vikram shows coexisting labels/evidence; Ram does not convert inventory reconciliation into finding resolution. Exit: active current route, reachable/no-traffic retired route zombie, undocumented UI route shadow; documented shadow changes inventory only.

## 6. Rehearsal

Sujal resets state, runs Compose/restart/cancellation/scope tests, and leads the script in [Demo acceptance](DEMO_ACCEPTANCE.md). Exit: all actual results rendered, no secret leakage, known reset path. Failures return to the owning module; Sujal coordinates verification rather than editing it.
