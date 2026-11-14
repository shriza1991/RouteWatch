"""SQLite v1 store. This module is not connected to the legacy agent."""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel

from shared.v1 import (
    Approval, ExecutionResult, Finding, RemediationProposal, RequestAuditEvent,
    RetestResult, ScanEvent, ScanRun, InventorySnapshot, ChangeEvent, TargetConfig,
)


class SchemaVersionError(RuntimeError):
    pass


class IdempotencyConflict(ValueError):
    pass


MIGRATIONS = ((
    'CREATE TABLE scans (id TEXT PRIMARY KEY, parent_id TEXT NOT NULL, sort_at TEXT NOT NULL, payload TEXT NOT NULL)',
    'CREATE TABLE scan_events (id TEXT PRIMARY KEY, parent_id TEXT NOT NULL REFERENCES scans(id), sort_at TEXT NOT NULL, payload TEXT NOT NULL)',
    'CREATE TABLE findings (id TEXT PRIMARY KEY, parent_id TEXT NOT NULL REFERENCES scans(id), sort_at TEXT NOT NULL, payload TEXT NOT NULL)',
    'CREATE TABLE proposals (id TEXT PRIMARY KEY, parent_id TEXT NOT NULL REFERENCES findings(id), sort_at TEXT NOT NULL, payload TEXT NOT NULL)',
    'CREATE TABLE approvals (id TEXT PRIMARY KEY, parent_id TEXT NOT NULL UNIQUE REFERENCES proposals(id), sort_at TEXT NOT NULL, payload TEXT NOT NULL)',
    'CREATE TABLE executions (id TEXT PRIMARY KEY, parent_id TEXT NOT NULL REFERENCES proposals(id), sort_at TEXT NOT NULL, payload TEXT NOT NULL)',
    'CREATE TABLE retests (id TEXT PRIMARY KEY, parent_id TEXT NOT NULL REFERENCES findings(id), scan_id TEXT NOT NULL REFERENCES scans(id), sort_at TEXT NOT NULL, payload TEXT NOT NULL, UNIQUE(parent_id,scan_id))',
    'CREATE TABLE audit (id TEXT PRIMARY KEY, parent_id TEXT NOT NULL REFERENCES scans(id), sort_at TEXT NOT NULL, payload TEXT NOT NULL)',
    'CREATE TABLE idempotency (operation TEXT NOT NULL, resource TEXT NOT NULL, key TEXT NOT NULL, fingerprint TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN (\'pending\',\'completed\')), result TEXT, PRIMARY KEY(operation,resource,key), CHECK((state=\'pending\' AND result IS NULL) OR (state=\'completed\' AND result IS NOT NULL)))',
    'CREATE INDEX idx_scan_events_parent ON scan_events(parent_id,sort_at,id)',
    'CREATE INDEX idx_findings_parent ON findings(parent_id,sort_at,id)',
    'CREATE INDEX idx_audit_parent ON audit(parent_id,sort_at,id)',
), (
    'CREATE TABLE inventory_snapshots (id TEXT PRIMARY KEY, parent_id TEXT NOT NULL, sort_at TEXT NOT NULL, payload TEXT NOT NULL)',
    'CREATE TABLE change_events (id TEXT PRIMARY KEY, parent_id TEXT NOT NULL REFERENCES scans(id), sort_at TEXT NOT NULL, payload TEXT NOT NULL)',
    'CREATE INDEX idx_inventory_snapshots_parent ON inventory_snapshots(parent_id,sort_at,id)',
    'CREATE INDEX idx_change_events_parent ON change_events(parent_id,sort_at,id)',
    'CREATE TABLE scan_configs (scan_id TEXT PRIMARY KEY REFERENCES scans(id), payload TEXT NOT NULL)',
))


def migrate(connection: sqlite3.Connection, migrations=MIGRATIONS) -> None:
    version = connection.execute('PRAGMA user_version').fetchone()[0]
    if version > len(migrations):
        raise SchemaVersionError(f'v1 store schema {version} is newer than supported {len(migrations)}')
    for index in range(version, len(migrations)):
        try:
            connection.execute('BEGIN IMMEDIATE')
            for statement in migrations[index]:
                connection.execute(statement)
            connection.execute(f'PRAGMA user_version = {index + 1}')
            connection.commit()
        except Exception:
            connection.rollback()
            raise


def fingerprint(request: dict) -> str:
    """Canonical fingerprint; callers must pass redacted, validated request data."""
    if not isinstance(request, dict):
        raise TypeError('request fingerprint input must be a dictionary')
    _reject_private(request)
    encoded = json.dumps(request, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def _reject_private(value):
    if isinstance(value, dict):
        for key, item in value.items():
            name = str(key).lower()
            if name == 'credential_ref':
                if not isinstance(item, str) or not item.startswith('server:'):
                    raise ValueError('only server-side credential references may be stored')
            elif any(term in name for term in ('token', 'authorization', 'password', 'cookie', 'secret', 'management_url', 'management_origin')):
                raise ValueError('credential or management configuration cannot be stored')
            _reject_private(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_private(item)
    elif isinstance(value, str) and value.lower().startswith('bearer '):
        raise ValueError('bearer credentials cannot be stored')


SPECS = {
    'scans': (ScanRun, 'target_id', 'started_at'),
    'scan_events': (ScanEvent, 'scan_id', 'at'),
    'findings': (Finding, 'scan_id', None),
    'proposals': (RemediationProposal, 'finding_id', None),
    'approvals': (Approval, 'proposal_id', 'at'),
    'executions': (ExecutionResult, 'proposal_id', 'requested_at'),
    'retests': (RetestResult, 'finding_id', 'created_at'),
    'audit': (RequestAuditEvent, 'scan_id', 'at'),
    'inventory_snapshots': (InventorySnapshot, 'target_id', 'captured_at'),
    'change_events': (ChangeEvent, 'scan_id', 'at'),
}


class Repository:
    def __init__(self, owner, table: str):
        self.owner, self.table = owner, table
        self.model, self.parent, self.time = SPECS[table]

    @contextmanager
    def _connection(self):
        if isinstance(self.owner, UnitOfWork):
            yield self.owner.connection
        else:
            with self.owner.transaction() as unit:
                yield unit.connection

    def save(self, value: BaseModel):
        if type(value) is not self.model:
            raise TypeError(f'{self.table} requires {self.model.__name__}')
        # Revalidation catches unsafe mutation inside nested dicts after construction.
        validated = self.model.model_validate_json(value.model_dump_json())
        payload = validated.model_dump_json()
        parent = str(getattr(validated, self.parent))
        sort_at = getattr(validated, self.time).isoformat() if self.time else ''
        scan_id = str(validated.scan_id) if self.table == 'retests' else None
        with self._connection() as conn:
            if self.table == 'retests':
                conn.execute('''INSERT INTO retests(id,parent_id,scan_id,sort_at,payload) VALUES(?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET parent_id=excluded.parent_id, scan_id=excluded.scan_id,
                    sort_at=excluded.sort_at,payload=excluded.payload''',
                    (str(validated.id), parent, scan_id, sort_at, payload))
            else:
                conn.execute(f'''INSERT INTO {self.table}(id,parent_id,sort_at,payload) VALUES(?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET parent_id=excluded.parent_id,
                    sort_at=excluded.sort_at,payload=excluded.payload''',
                    (str(validated.id), parent, sort_at, payload))
        return validated

    def get(self, entity_id: UUID | str):
        with self._connection() as conn:
            row = conn.execute(f'SELECT payload FROM {self.table} WHERE id=?', (str(entity_id),)).fetchone()
        return self.model.model_validate_json(row['payload']) if row else None

    def list(self, *, parent_id: UUID | str | None = None, limit: int = 100, offset: int = 0):
        if not 1 <= limit <= 1000 or offset < 0:
            raise ValueError('invalid pagination')
        where = 'WHERE parent_id=?' if parent_id is not None else ''
        args = (str(parent_id), limit, offset) if parent_id is not None else (limit, offset)
        with self._connection() as conn:
            rows = conn.execute(f'SELECT payload FROM {self.table} {where} ORDER BY sort_at ASC,id ASC LIMIT ? OFFSET ?', args).fetchall()
        return [self.model.model_validate_json(row['payload']) for row in rows]


class UnitOfWork:
    def __init__(self, connection):
        self.connection = connection
        for name in SPECS:
            setattr(self, name, Repository(self, name))

    def save_scan_config(self, scan_id: UUID | str, config: TargetConfig) -> None:
        if not isinstance(config, TargetConfig):
            raise TypeError('v1 TargetConfig is required')
        payload = TargetConfig.model_validate_json(config.model_dump_json()).model_dump_json()
        with self.transaction() as unit:
            unit.connection.execute(
                'INSERT INTO scan_configs(scan_id,payload) VALUES(?,?) '
                'ON CONFLICT(scan_id) DO UPDATE SET payload=excluded.payload',
                (str(scan_id), payload),
            )

    def get_scan_config(self, scan_id: UUID | str) -> TargetConfig | None:
        connection = self.connect()
        try:
            row = connection.execute('SELECT payload FROM scan_configs WHERE scan_id=?',
                                      (str(scan_id),)).fetchone()
        finally:
            connection.close()
        return TargetConfig.model_validate_json(row['payload']) if row else None

    def reserve(self, operation: str, resource: str, key: str, request_fingerprint: str):
        if not all(isinstance(x, str) and x.strip() for x in (operation, resource, key, request_fingerprint)):
            raise ValueError('operation, resource, key and fingerprint are required')
        row = self.connection.execute('SELECT fingerprint,state,result FROM idempotency WHERE operation=? AND resource=? AND key=?',
                                      (operation, resource, key)).fetchone()
        if row:
            if row['fingerprint'] != request_fingerprint:
                raise IdempotencyConflict('idempotency key reused with a different request')
            return {'state': row['state'], 'result': json.loads(row['result']) if row['result'] else None}
        self.connection.execute('INSERT INTO idempotency VALUES (?,?,?,?,?,NULL)',
                                (operation, resource, key, request_fingerprint, 'pending'))
        return {'state': 'pending', 'result': None}

    def complete(self, operation: str, resource: str, key: str, request_fingerprint: str, result: dict):
        if not isinstance(result, dict):
            raise TypeError('completed result must be a dictionary')
        _reject_private(result)
        encoded = json.dumps(result, sort_keys=True, allow_nan=False)
        existing = self.reserve(operation, resource, key, request_fingerprint)
        if existing['state'] == 'completed':
            if existing['result'] != result:
                raise IdempotencyConflict('completed result cannot be replaced')
            return existing
        self.connection.execute('UPDATE idempotency SET state=?,result=? WHERE operation=? AND resource=? AND key=?',
                                ('completed', encoded, operation, resource, key))
        return {'state': 'completed', 'result': result}


class V1Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if self.path.name in ('', ':memory:'):
            raise ValueError('a persistent v1 database path is required')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = self.connect()
        try:
            migrate(connection)
        finally:
            connection.close()
        for name in SPECS:
            setattr(self, name, Repository(self, name))

    def connect(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys = ON')
        return connection

    @contextmanager
    def transaction(self):
        connection = self.connect()
        try:
            connection.execute('BEGIN IMMEDIATE')
            yield UnitOfWork(connection)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def reserve(self, operation: str, resource: str, key: str, request_fingerprint: str):
        with self.transaction() as unit:
            return unit.reserve(operation, resource, key, request_fingerprint)

    def complete(self, operation: str, resource: str, key: str, request_fingerprint: str, result: dict):
        with self.transaction() as unit:
            return unit.complete(operation, resource, key, request_fingerprint, result)
