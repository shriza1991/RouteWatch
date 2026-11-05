# Sujal — Contracts, backend transport, persistence and integration QA

## Mission

Own the stable seam between every module: versioned contracts, durable storage, polling API, Compose, integrated tests, release documentation, and coordination—not other owners’ algorithms.

## Ownership

Existing: `shared/`, Dockerfiles, `docker-compose.yml`, `.env.example`, `requirements.txt`, `README.md`, `DEMO.md`, `TEAM.md`, `.gitignore`; proposed `transport/`, `persistence/`, `tests/integration/`, CI. Do not alter sandbox behavior, discovery algorithm, agent decisions, or frontend components.

## Ordered work

### SUJ-01 — Version contracts and persistence
- **Purpose/behaviour:** implement [Contracts](../CONTRACTS.md) in `shared/`, migrations and repositories; persist decisions rather than derive them.
- **Files:** modify `shared/schemas.py`; create proposed `persistence/` and migration tests.
- **I/O:** stores all stable IDs/relations/audits/redacted proof; domain inputs/outputs are owner-defined.
- **Edges:** schema version mismatch/error, migration rollback, secret rejection; idempotency keys unique.
- **Acceptance:** restart retains run/finding/audit/retest; contract validation tests.

### SUJ-02 — Transport and adapter wiring
- **Purpose:** expose minimal polling API, delegate discovery/agent calls, inject server-only management adapter after approval.
- **Files:** split transport from existing `agent/app.py` into proposed `transport/api.py`; create `management_adapter.py`.
- **Edges:** no arbitrary action, no management URL to browser/executor, repeat mutation returns original response.
- **Dependencies/evidence:** consume Akshat/Ram interfaces, Shriraj capability keys; API contract/integration test.

### SUJ-03 — Compose, QA and release docs
- **Purpose:** reproducible local startup, root env rules, CI, E2E scenarios, reconcile README/DEMO/TEAM with these docs.
- **Files:** owned root files and proposed tests/CI.
- **Acceptance:** startup, restart, vulnerable/fixed, failed/unsupported remediation, scope/budget/cancel, secret redaction, fixture isolation all exercised.

## Interfaces, stubs and commands

Repository examples: `save_scan(ScanRun)`, `append_event(ScanEvent)`, `POST /proposals/{id}/approval`. Use in-memory repositories and fake module ports until each owner hands off; replace through dependency injection, never by importing private files. Existing commands: `docker compose up --build`, `python -m pytest -q`, `npm run build` in `dashboard`; proposed: `python -m pytest tests/integration`.

## Done and handoff

Done: APIs persist owner decisions, environment/Compose is reproducible, and E2E evidence is recorded. Hand released contract/version notes to **all members**; return module defects to their sole owner. Avoid reimplementing Ram lifecycle logic or silently changing contracts. Must-have: polling/restart/E2E/docs; optional: event streaming/CI matrix.
