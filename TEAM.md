# Team contract and ownership

Shared schemas live in `shared/schemas.py`. Any contract change starts there and is agreed across owners before implementation.

1. **Sandbox owner** — `sandbox/`: synthetic travel API, minimal UI/traffic recording, seed/reset and vulnerable/fixed behaviors. Interface: HTTP sandbox routes only.
2. **Discovery owner** — traffic recording importer, normalisation and inventory classification in `agent/app.py`; consumes `ObservedRequest`, produces `Endpoint`.
3. **Agent owner** — safe orchestration, rule planner, ownership/fare checks, budgets and cancellation in `agent/app.py`; consumes `TargetConfig`, produces `ScanRun`/`Finding`.
4. **Dashboard owner** — `dashboard/`: renders only agent API results and sends scan/retest/deployment requests.
5. **Integration/QA owner** — `tests/`, Compose, persisted SQLite stores, README and demo. Interface: `/scans`, `/findings`, `/retests`, `/audit`.

The planner is explicitly rule-driven and replaceable; no LLM claim is made.
