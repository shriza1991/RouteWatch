# Akshat — Traffic discovery and API inventory

## Mission

Turn permitted normal synthetic traffic, a separate reference inventory, and timestamped synthetic history into safe, redacted endpoint evidence. This powers Scenario C and gives Ram structures—not target internals.

## Ownership

Existing: `agent/reference_inventory.json`. Proposed: `discovery/`, `tests/discovery/`, `fixtures/discovery/`. Do not edit sandbox APIs/data, agent rules, dashboard, contracts, or root integration files.

## Ordered work

### AKS-01 — Capture/import and redaction
- **Purpose/behaviour:** import HAR/equivalent normal journeys, normalize IDs to `{id}`, preserve account context/body shape, redact authorization/cookie/token/password before persistence.
- **Files:** create `discovery/importer.py`, `discovery/redaction.py`, fixtures/tests.
- **I/O:** input capture + configured account alias; output `ObservedRequest[]` from [Contracts](../CONTRACTS.md).
- **Edges/dependencies:** malformed HAR → structured import error; unknown account → context `unknown`; Shriraj supplies fixture, Sujal supplies storage interface.
- **Acceptance/evidence:** test asserts raw secrets never occur in output or SQLite fixture.

### AKS-02 — Inventory and evidence
- **Purpose:** normalize endpoints and compare observed traffic, separate reference JSON, narrowly scoped reachability probe, and synthetic historical window.
- **Files:** create `discovery/inventory.py`; modify existing reference fixture only.
- **I/O:** produces `Endpoint(labels,evidence)`; Ram consumes observations, Vikram consumes rendered inventory.
- **Edges:** version path alone is not zombie; unavailable probe/absent history produces `unknown`; active and shadow may coexist.
- **Acceptance:** fixture produces current `active`, reachable/no-window-traffic retired `zombie`, UI-used/undocumented `shadow` (and active when observed).

### AKS-03 — Refresh and handoff
- **Purpose:** refresh after disable action or reference update, distinctly recording security remediation versus reconciliation.
- **Files:** proposed `discovery/service.py`, tests.
- **Edges:** documented shadow loses `shadow` only; it is never marked fixed finding.
- **Acceptance:** evidence timestamps/source remain visible; Ram has no source/db dependency.

## Contracts, fixtures, commands

Core signature: `import_capture(capture: bytes, contexts: list[AuthorizedAccount]) -> list[ObservedRequest]`; `classify(endpoints, reference, history, probe) -> list[Endpoint]`. Example evidence: `{kind:"history", synthetic:true, window_start:"…", statement:"no legitimate traffic"}`. Work locally with proposed `python -m pytest tests/discovery`; fixture stubs replace themselves when Shriraj’s exported normal-journey record arrives and Sujal persists records.

## Done and handoff

Done: redacted, repeatable discovery plus evidence-backed labels and tests. Hand off observations/inventory to **Ram**, API-ready objects to **Sujal**, display samples to **Vikram**. Avoid looking at sandbox source/OpenAPI or assigning severity. Must-have: three labels plus unknown; optional: browser proxy capture.
