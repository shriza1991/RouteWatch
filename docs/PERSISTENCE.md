# V1 SQLite persistence (wired to the separate v1 transport only)

Import `from persistence import V1Store, fingerprint, IdempotencyConflict, SchemaVersionError`. Construct `V1Store(path)` with a dedicated path such as `data/voyageguard-v1.db`; never point it at the current `AGENT_DB` file. The store creates its parent directory and applies versioned migrations on construction. It does not import or modify the legacy agent tables. Reopening an existing v1 file preserves records. A database with `PRAGMA user_version` newer than supported raises `SchemaVersionError`; each migration runs in a transaction and rolls back on failure.

All connections enable SQLite foreign keys. `store.connect()` returns a connection the caller must close. `store.transaction()` yields a unit of work and commits on successful exit or rolls back on exception. The store and unit expose repositories named `scans`, `scan_events`, `findings`, `proposals`, `approvals`, `executions`, `retests`, and `audit`. Each supports `save(v1_model)`, `get(id) -> model | None`, and `list(parent_id=None, limit=100, offset=0) -> list[model]`. Lists sort by the model's UTC timestamp where present, then ID; records without a timestamp sort by ID. Filtering uses `target_id` for scans and the relevant parent ID for other repositories. `save` revalidates the v1 model, inserts by stable UUID or updates the supplied record with the same UUID; it does not compute or change domain decisions.

```python
from persistence import V1Store
from shared.v1 import ScanRun, ScanEvent

store = V1Store('data/voyageguard-v1.db')
scan = ScanRun(target_id='local-sandbox', state='queued')
event = ScanEvent(scan_id=scan.id, stage='queued', message='Waiting to start')
with store.transaction() as tx:
    tx.scans.save(scan)
    tx.scan_events.save(event)
assert store.scan_events.list(parent_id=scan.id) == [event]
```

Foreign keys enforce scan → events/findings/audit; finding → proposals/retests; proposal → approvals/executions; retest → scan. One approval per proposal and one retest per finding/scan are unique. A failed related write rolls back the entire unit of work. The v1 models and persistence boundary reject raw credential-shaped fields and management URLs in stored payloads. Persist only credential references (`server:...`), never `ServerCredentialConfig` or legacy `shared.schemas.TargetConfig`.

## Durable idempotency for future transport

`fingerprint(redacted_request_dict) -> sha256 hex` canonicalizes JSON key order. A key is scoped by `(operation, resource, key)` and bound to that fingerprint. `store.reserve(operation, resource, key, fingerprint)` returns `{state:'pending', result:None}` for a new or still-pending request; a different fingerprint under the same scope raises `IdempotencyConflict`. `store.complete(..., result_dict)` stores a completed result; identical replay returns it, while changing it raises a conflict. These methods also exist on `tx` for combining a record write and reservation/result in one SQLite transaction.

Pending means **no completed result is known**. If a process crashes after an external HTTP action but before completion, the pending row cannot prove whether the action ran. Transport must reconcile with the external service's own idempotency key or require operator review; SQLite and HTTP cannot provide exactly-once execution together. No execution or approval policy is implemented by this store.

## Integration boundary

The separate `transport.api:app` constructs this store using `VOYAGEGUARD_V1_DB`; the opt-in Compose profile mounts a dedicated `v1-data` volume. The current agent still reads and writes its own `AGENT_DB` tables and imports `shared.schemas`. Future Sujal/Ram work must supply domain/discovery services, decide how to handle legacy rows, and migrate consumers deliberately. No old data is migrated. Tests: `python -m pytest tests/integration/test_persistence.py -q`.
