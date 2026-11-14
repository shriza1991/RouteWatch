"""Separate v1 polling transport. Domain/discovery implementations are injected."""

import os
from typing import Protocol
from uuid import UUID, uuid5

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from persistence import IdempotencyConflict, V1Store, fingerprint
from discovery.runtime import FixtureInventoryService
from shared.v1 import (Approval, Endpoint, ExecutionResult, Finding, RemediationProposal,
                       RequestAuditEvent, RetestResult, ScanEvent, ScanRun, TargetConfig)
from transport.management_adapter import SandboxManagementAdapter


class CredentialResolver(Protocol):
    def has_reference(self, reference: str) -> bool: ...


class DomainService(Protocol):
    def start_scan(self, target: TargetConfig, credentials: CredentialResolver) -> ScanRun: ...
    def cancel_scan(self, scan: ScanRun) -> ScanRun: ...
    def propose(self, finding: Finding) -> RemediationProposal: ...
    def approve(self, proposal: RemediationProposal, reviewer_id: str, decision: str) -> Approval: ...
    def execute(self, proposal: RemediationProposal, approval: Approval, attempt_id: UUID,
                adapter: SandboxManagementAdapter) -> ExecutionResult: ...
    def retest(self, finding: Finding) -> RetestResult: ...


class InventoryService(Protocol):
    def list_endpoints(self, target_id: str) -> list[Endpoint]: ...


class ScanCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    target: TargetConfig


class ApprovalCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    decision: str = Field(pattern=r'^(approved|rejected)$')


class ApiError(BaseModel):
    code: str
    message: str


def fail(status: int, code: str, message: str):
    raise HTTPException(status_code=status, detail={'code': code, 'message': message})


def create_app(*, store: V1Store, credential_resolver: CredentialResolver | None = None,
               domain: DomainService | None = None, inventory: InventoryService | None = None,
               management_adapter: SandboxManagementAdapter | None = None,
               reviewer_id: str = 'local-demo-reviewer') -> FastAPI:
    if not reviewer_id.strip():
        raise ValueError('server-side demo reviewer ID is required')
    app = FastAPI(title='VoyageGuard v1 transport', docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, error: HTTPException):
        detail = error.detail if isinstance(error.detail, dict) else {'code': 'request_failed', 'message': 'Request failed'}
        return JSONResponse(status_code=error.status_code, content=detail)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, _error: RequestValidationError):
        return JSONResponse(status_code=422, content={'code': 'invalid_request', 'message': 'Request validation failed'})

    @app.exception_handler(IdempotencyConflict)
    async def conflict_error(_request: Request, _error: IdempotencyConflict):
        return JSONResponse(status_code=409, content={'code': 'idempotency_conflict', 'message': 'Key reused with different request'})

    @app.exception_handler(Exception)
    async def unexpected_error(_request: Request, _error: Exception):
        return JSONResponse(status_code=500, content={'code': 'internal_error', 'message': 'Operation failed'})

    def capability(value, name):
        if value is None:
            fail(503, 'capability_unavailable', f'{name} capability unavailable')
        return value

    def required(repo, entity_id, name):
        value = repo.get(entity_id)
        if value is None:
            fail(404, 'not_found', f'{name} not found')
        return value

    def mutate(operation, resource, key, request_data, result_type, command, repository,
               relation_field=None, expected_id=None, precondition=None):
        request_hash = fingerprint(request_data)
        with store.transaction() as tx:
            prior = tx.connection.execute(
                'SELECT state FROM idempotency WHERE operation=? AND resource=? AND key=?',
                (operation, resource, key),
            ).fetchone()
            if prior is None and precondition is not None:
                precondition(tx)
            current = tx.reserve(operation, resource, key, request_hash)
        if current['state'] == 'completed':
            return result_type.model_validate(current['result'])
        if prior is not None:
            fail(409, 'pending_reconciliation', 'Operation requires reconciliation')
        result = command()
        if type(result) is not result_type:
            raise TypeError('Domain returned an incompatible result')
        if relation_field and str(getattr(result, relation_field)) != resource:
            raise ValueError('Domain result belongs to a different resource')
        if expected_id is not None and result.id != expected_id:
            raise ValueError('Domain result changed the resource ID')
        with store.transaction() as tx:
            getattr(tx, repository).save(result)
            tx.complete(operation, resource, key, request_hash, result.model_dump(mode='json'))
        return result

    @app.post('/v1/scans', response_model=ScanRun)
    def start(body: ScanCreate, idempotency_key: str = Header(min_length=1)):
        service = capability(domain, 'scan')
        resolver = capability(credential_resolver, 'credential resolver')
        if not all(resolver.has_reference(a.credential_ref) for a in body.target.accounts):
            fail(422, 'invalid_credential_reference', 'Unknown server credential reference')
        return mutate('start_scan', body.target.id, idempotency_key, body.model_dump(mode='json'),
                      ScanRun, lambda: service.start_scan(body.target, resolver), 'scans', 'target_id')

    @app.get('/v1/scans', response_model=list[ScanRun])
    def scans(target_id: str | None = None, limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)):
        return store.scans.list(parent_id=target_id, limit=limit, offset=offset)

    @app.get('/v1/scans/{scan_id}', response_model=ScanRun)
    def scan(scan_id: UUID): return required(store.scans, scan_id, 'scan')

    @app.post('/v1/scans/{scan_id}/cancel', response_model=ScanRun)
    def cancel(scan_id: UUID, idempotency_key: str = Header(min_length=1)):
        service = capability(domain, 'scan')
        current = required(store.scans, scan_id, 'scan')
        return mutate('cancel_scan', str(scan_id), idempotency_key, {}, ScanRun,
                      lambda: service.cancel_scan(current), 'scans', expected_id=scan_id)

    @app.get('/v1/scans/{scan_id}/events', response_model=list[ScanEvent])
    def events(scan_id: UUID):
        required(store.scans, scan_id, 'scan')
        return store.scan_events.list(parent_id=scan_id)

    @app.get('/v1/findings', response_model=list[Finding])
    def findings(scan_id: UUID | None = None): return store.findings.list(parent_id=scan_id)

    @app.get('/v1/findings/{finding_id}', response_model=Finding)
    def finding(finding_id: UUID): return required(store.findings, finding_id, 'finding')

    @app.get('/v1/inventory', response_model=list[Endpoint])
    def endpoints(target_id: str): return capability(inventory, 'inventory').list_endpoints(target_id)

    @app.post('/v1/findings/{finding_id}/proposals', response_model=RemediationProposal)
    def propose(finding_id: UUID, idempotency_key: str = Header(min_length=1)):
        service = capability(domain, 'proposal')
        current = required(store.findings, finding_id, 'finding')
        return mutate('propose', str(finding_id), idempotency_key, {}, RemediationProposal,
                      lambda: service.propose(current), 'proposals', 'finding_id')

    @app.get('/v1/proposals', response_model=list[RemediationProposal])
    def proposals(finding_id: UUID | None = None): return store.proposals.list(parent_id=finding_id)

    @app.post('/v1/proposals/{proposal_id}/approval', response_model=Approval)
    def approve(proposal_id: UUID, body: ApprovalCreate, idempotency_key: str = Header(min_length=1)):
        service = capability(domain, 'approval')
        current = required(store.proposals, proposal_id, 'proposal')
        return mutate('approval', str(proposal_id), idempotency_key, body.model_dump(), Approval,
                      lambda: service.approve(current, reviewer_id, body.decision), 'approvals', 'proposal_id')

    @app.get('/v1/approvals', response_model=list[Approval])
    def approvals(proposal_id: UUID | None = None): return store.approvals.list(parent_id=proposal_id)

    @app.post('/v1/proposals/{proposal_id}/execute', response_model=ExecutionResult)
    def execute(proposal_id: UUID, idempotency_key: str = Header(min_length=1)):
        service = capability(domain, 'execution')
        adapter = capability(management_adapter, 'management adapter')
        current = required(store.proposals, proposal_id, 'proposal')
        approvals = store.approvals.list(parent_id=proposal_id)
        if len(approvals) != 1 or approvals[0].decision != 'approved':
            fail(409, 'approval_required', 'Persisted approved decision required')
        approval = approvals[0]
        def execution_ready(tx):
            if any(item.state == 'indeterminate' for item in tx.executions.list(parent_id=proposal_id)):
                fail(409, 'execution_reconciliation', 'Prior execution requires reconciliation')
            pending = tx.connection.execute(
                "SELECT 1 FROM idempotency WHERE operation='execute' AND resource=? AND state='pending' LIMIT 1",
                (str(proposal_id),),
            ).fetchone()
            if pending:
                fail(409, 'execution_reconciliation', 'Prior execution requires reconciliation')
        attempt_id = uuid5(proposal_id, idempotency_key)
        return mutate('execute', str(proposal_id), idempotency_key, {}, ExecutionResult,
                      lambda: service.execute(current, approval, attempt_id, adapter), 'executions',
                      'proposal_id', precondition=execution_ready)

    @app.get('/v1/executions', response_model=list[ExecutionResult])
    def executions(proposal_id: UUID | None = None): return store.executions.list(parent_id=proposal_id)

    @app.post('/v1/findings/{finding_id}/retest', response_model=RetestResult)
    def retest(finding_id: UUID, idempotency_key: str = Header(min_length=1)):
        service = capability(domain, 'retest')
        current = required(store.findings, finding_id, 'finding')
        return mutate('retest', str(finding_id), idempotency_key, {}, RetestResult,
                      lambda: service.retest(current), 'retests', 'finding_id')

    @app.get('/v1/retests', response_model=list[RetestResult])
    def retests(finding_id: UUID | None = None): return store.retests.list(parent_id=finding_id)

    @app.get('/v1/audit', response_model=list[RequestAuditEvent])
    def audit(scan_id: UUID | None = None): return store.audit.list(parent_id=scan_id)

    return app


# Separate entrypoint. No fabricated domain or inventory service is installed.
app = create_app(
    store=V1Store(os.getenv('VOYAGEGUARD_V1_DB', 'data/voyageguard-v1.db')),
    inventory=FixtureInventoryService(),
)
