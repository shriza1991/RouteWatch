"""VoyageGuard integration contracts v1. Not wired into the legacy runtime."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


CONTRACT_VERSION = '1.0'


class ActionKey(str, Enum):
    enforce_booking_ownership = 'enforce_booking_ownership'
    validate_quote_fare = 'validate_quote_fare'
    disable_legacy_booking = 'disable_legacy_booking'


class EvidenceKind(str, Enum):
    traffic = 'traffic'
    reference = 'reference'
    history = 'history'
    probe = 'probe'


class CheckOutcome(str, Enum):
    passed = 'passed'
    failed = 'failed'
    inconclusive = 'inconclusive'
    cancelled = 'cancelled'


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key) == 'credential_ref' and (not isinstance(item, str) or not item.startswith('server:')):
                raise ValueError('credential references must point to server-side configuration')
            if str(key) != 'credential_ref' and any(term in str(key).lower() for term in ('token', 'authorization', 'password', 'cookie', 'secret', 'credential')):
                raise ValueError('credential material is not allowed in persistable data')
            _safe(item)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            _safe(item)
    elif isinstance(value, str) and value.lower().startswith('bearer '):
        raise ValueError('bearer credentials are not allowed in persistable data')


class ContractModel(BaseModel):
    model_config = ConfigDict(extra='forbid', validate_assignment=True)

    @model_validator(mode='after')
    def reject_credentials(self):
        _safe(self.model_dump(mode='python', exclude_none=True))
        return self

    @field_validator('*', mode='after')
    @classmethod
    def utc_timestamps(cls, value: Any):
        if isinstance(value, datetime) and value.utcoffset() != timezone.utc.utcoffset(None):
            raise ValueError('timestamps must be UTC')
        return value


@dataclass(repr=False)
class ServerCredentialConfig:
    """In-memory executor configuration only; never serialize or persist."""
    tokens_by_ref: dict[str, str] = field(repr=False)

    def resolve(self, credential_ref: str) -> str:
        return self.tokens_by_ref[credential_ref]


class AuthorizedAccount(ContractModel):
    id: str = Field(min_length=1)
    agency_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    credential_ref: str = Field(min_length=1)

    @model_validator(mode='after')
    def account_reference(self):
        if not self.credential_ref.startswith('server:'):
            raise ValueError('credential_ref must be a server-side reference')
        return self


class TargetConfig(ContractModel):
    id: str = Field(min_length=1)
    base_url: HttpUrl
    allowed_origins: list[HttpUrl] = Field(min_length=1)
    accounts: list[AuthorizedAccount] = Field(min_length=2)
    max_requests: int = Field(ge=1, le=200)
    timeout_seconds: float = Field(gt=0, le=15)
    rate_per_minute: int = Field(default=30, ge=1)
    reference_inventory_id: str | None = None


class ObservedRequest(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    capture_id: UUID
    method: str = Field(pattern=r'^(GET|POST|PUT|PATCH|DELETE)$')
    normalized_path: str = Field(pattern=r'^/')
    observed_at: AwareDatetime
    account_context_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    status: int | None = Field(default=None, ge=100, le=599)
    redacted_headers: dict[str, str] = Field(default_factory=dict)
    redacted_body_shape: dict[str, Any] = Field(default_factory=dict)


class InventoryEvidence(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    endpoint_id: UUID
    kind: EvidenceKind
    observed_at: AwareDatetime
    statement: str = Field(min_length=1)
    window_start: AwareDatetime | None = None
    window_end: AwareDatetime | None = None
    synthetic: bool = True
    coverage: str | None = Field(default=None, pattern=r'^(complete|incomplete)$')

    @model_validator(mode='after')
    def window_order(self):
        if self.window_start and self.window_end and self.window_start >= self.window_end:
            raise ValueError('invalid observation window')
        return self


class Endpoint(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    method: str = Field(pattern=r'^(GET|POST|PUT|PATCH|DELETE)$')
    normalized_path: str = Field(pattern=r'^/')
    labels: set[str] = Field(default_factory=set)
    reachability: str = Field(default='unprobed', pattern=r'^(reachable|blocked|unreachable|unprobed)$')
    evidence: list[InventoryEvidence] = Field(default_factory=list)

    @model_validator(mode='after')
    def valid_labels_and_links(self):
        if not self.labels <= {'active', 'zombie', 'shadow', 'unknown'} or ('unknown' in self.labels and len(self.labels) > 1):
            raise ValueError('invalid inventory labels')
        if any(item.endpoint_id != self.id for item in self.evidence):
            raise ValueError('evidence must refer to this endpoint')
        return self


class ScanRun(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    target_id: str = Field(min_length=1)
    state: str = Field(pattern=r'^(queued|running|cancelling|cancelled|failed|completed)$')
    started_at: AwareDatetime = Field(default_factory=utc_now)
    request_count: int = Field(default=0, ge=0)
    completed_at: AwareDatetime | None = None
    cancel_reason: str | None = None


class ScanEvent(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    scan_id: UUID
    at: AwareDatetime = Field(default_factory=utc_now)
    stage: str = Field(min_length=1)
    message: str = Field(min_length=1)
    progress: float | None = Field(default=None, ge=0, le=1)


class TestPlan(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    scan_id: UUID
    rule_id: str = Field(min_length=1)
    observed_request_ids: list[UUID] = Field(default_factory=list)
    account_context_ids: list[str] = Field(default_factory=list)
    budget: int = Field(ge=1)
    status: str = Field(default='planned', pattern=r'^(planned|running|completed|cancelled)$')


class TestResult(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    plan_id: UUID
    outcome: str = Field(pattern=r'^(pass|finding|inconclusive|cancelled|error)$')
    evidence_ids: list[UUID] = Field(default_factory=list)
    error: str | None = None


class MinimalProof(ContractModel):
    request: dict[str, Any]
    response: dict[str, Any]
    legitimate_control: dict[str, Any]


class Finding(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    scan_id: UUID
    rule_id: str = Field(min_length=1)
    title: str | None = None
    severity: str = Field(pattern=r'^(critical|high|medium|low)$')
    business_impact: str = Field(min_length=1)
    suggested_fix: str | None = None
    endpoint: str | None = None
    confidence: float = Field(default=0.95, ge=0, le=1)
    minimal_proof: MinimalProof
    state: str = Field(default='verified', pattern=r'^(open|verified|awaiting_approval|approved|remediating|retesting|resolved|unsupported|remediation_failed|retest_failed|inconclusive|cancelled)$')


class RemediationProposal(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    finding_id: UUID
    action_key: ActionKey
    description: str = Field(min_length=1)
    state: str = Field(default='proposed', pattern=r'^(proposed|awaiting_approval|approved|rejected|unsupported|executed)$')


class Approval(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    proposal_id: UUID
    approved_by: str = Field(min_length=1)
    at: AwareDatetime = Field(default_factory=utc_now)
    decision: str = Field(pattern=r'^(approved|rejected)$')
    reason: str | None = None


class ExecutionResult(ContractModel):
    id: UUID
    proposal_id: UUID
    action_key: ActionKey
    state: str = Field(pattern=r'^(requested|applied|unsupported|failed|cancelled|indeterminate)$')
    requested_at: AwareDatetime
    detail: str | None = None


class RetestResult(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    finding_id: UUID
    scan_id: UUID
    exploit_outcome: CheckOutcome
    legitimate_flow_outcome: CheckOutcome
    outcome: str = Field(pattern=r'^(resolved|failed|inconclusive|cancelled)$')
    created_at: AwareDatetime = Field(default_factory=utc_now)
    detail: str | None = None

    @model_validator(mode='after')
    def resolution_requires_both_checks(self):
        if self.outcome == 'resolved' and (self.exploit_outcome != CheckOutcome.passed or self.legitimate_flow_outcome != CheckOutcome.passed):
            raise ValueError('resolution requires passed exploit and legitimate-flow checks')
        return self


class RequestAuditEvent(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    scan_id: UUID
    at: AwareDatetime = Field(default_factory=utc_now)
    method: str = Field(pattern=r'^(GET|POST|PUT|PATCH|DELETE)$')
    normalized_path: str = Field(pattern=r'^/')
    purpose: str = Field(min_length=1)
    outcome: str = Field(min_length=1)
    status: int | None = Field(default=None, ge=100, le=599)
    redacted_body_shape: dict[str, Any] = Field(default_factory=dict)


def map_sandbox_execution(proposal: RemediationProposal, response: dict[str, Any], *, received_at: datetime | None = None) -> ExecutionResult:
    """Pure adapter; caller supplies the approved proposal and handles lifecycle decisions."""
    state = response.get('state')
    if state not in {'applied', 'unsupported', 'failed'}:
        raise ValueError('unsupported sandbox execution state')
    if response.get('action_key', proposal.action_key.value) != proposal.action_key.value:
        raise ValueError('sandbox action does not match proposal')
    if state in {'applied', 'unsupported'} and ('execution_id' not in response or 'requested_at' not in response):
        raise ValueError('sandbox execution response is incomplete')
    return ExecutionResult(
        id=response.get('execution_id', uuid4()), proposal_id=proposal.id,
        action_key=proposal.action_key, state=state,
        requested_at=response.get('requested_at', received_at or utc_now()),
        detail=response.get('detail'),
    )


class InventorySnapshot(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    target_id: str = Field(min_length=1)
    captured_at: AwareDatetime = Field(default_factory=utc_now)
    endpoints: list[Endpoint] = Field(default_factory=list)
    synthetic: bool = True


class ChangeEvent(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    scan_id: UUID
    target_id: str = Field(min_length=1)
    at: AwareDatetime = Field(default_factory=utc_now)
    method: str = Field(pattern=r'^(GET|POST|PUT|PATCH|DELETE)$')
    normalized_path: str = Field(pattern=r'^/')
    change: str = Field(pattern=r'^(added|removed|metadata_changed)$')
    risk_score: int = Field(ge=0, le=100)
    reasons: list[str] = Field(default_factory=list)
    recommended_test_families: list[str] = Field(default_factory=list)


class RemediationProposal(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    finding_id: UUID
    action_key: ActionKey
    description: str = Field(min_length=1)
    state: str = Field(default='proposed', pattern=r'^(proposed|awaiting_approval|approved|rejected|unsupported|executed)$')


class Approval(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    proposal_id: UUID
    approved_by: str = Field(min_length=1)
    at: AwareDatetime = Field(default_factory=utc_now)
    decision: str = Field(pattern=r'^(approved|rejected)$')
    reason: str | None = None


class ExecutionResult(ContractModel):
    id: UUID
    proposal_id: UUID
    action_key: ActionKey
    state: str = Field(pattern=r'^(requested|applied|unsupported|failed|cancelled|indeterminate)$')
    requested_at: AwareDatetime
    detail: str | None = None


class RetestResult(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    finding_id: UUID
    scan_id: UUID
    exploit_outcome: CheckOutcome
    legitimate_flow_outcome: CheckOutcome
    outcome: str = Field(pattern=r'^(resolved|failed|inconclusive|cancelled)$')
    created_at: AwareDatetime = Field(default_factory=utc_now)
    detail: str | None = None

    @model_validator(mode='after')
    def resolution_requires_both_checks(self):
        if self.outcome == 'resolved' and (self.exploit_outcome != CheckOutcome.passed or self.legitimate_flow_outcome != CheckOutcome.passed):
            raise ValueError('resolution requires passed exploit and legitimate-flow checks')
        return self


class RequestAuditEvent(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    scan_id: UUID
    at: AwareDatetime = Field(default_factory=utc_now)
    method: str = Field(pattern=r'^(GET|POST|PUT|PATCH|DELETE)$')
    normalized_path: str = Field(pattern=r'^/')
    purpose: str = Field(min_length=1)
    outcome: str = Field(min_length=1)
    status: int | None = Field(default=None, ge=100, le=599)
    redacted_body_shape: dict[str, Any] = Field(default_factory=dict)


def map_sandbox_execution(proposal: RemediationProposal, response: dict[str, Any], *, received_at: datetime | None = None) -> ExecutionResult:
    """Pure adapter; caller supplies the approved proposal and handles lifecycle decisions."""
    state = response.get('state')
    if state not in {'applied', 'unsupported', 'failed'}:
        raise ValueError('unsupported sandbox execution state')
    if response.get('action_key', proposal.action_key.value) != proposal.action_key.value:
        raise ValueError('sandbox action does not match proposal')
    if state in {'applied', 'unsupported'} and ('execution_id' not in response or 'requested_at' not in response):
        raise ValueError('sandbox execution response is incomplete')
    return ExecutionResult(
        id=response.get('execution_id', uuid4()), proposal_id=proposal.id,
        action_key=proposal.action_key, state=state,
        requested_at=response.get('requested_at', received_at or utc_now()),
        detail=response.get('detail'),
    )


class InventorySnapshot(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    target_id: str = Field(min_length=1)
    captured_at: AwareDatetime = Field(default_factory=utc_now)
    endpoints: list[Endpoint] = Field(default_factory=list)
    synthetic: bool = True


class ChangeEvent(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    scan_id: UUID
    target_id: str = Field(min_length=1)
    at: AwareDatetime = Field(default_factory=utc_now)
    method: str = Field(pattern=r'^(GET|POST|PUT|PATCH|DELETE)$')
    normalized_path: str = Field(pattern=r'^/')
    change: str = Field(pattern=r'^(added|removed|metadata_changed)$')
    risk_score: int = Field(ge=0, le=100)
    reasons: list[str] = Field(default_factory=list)
    recommended_test_families: list[str] = Field(default_factory=list)


class RemediationProposal(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    finding_id: UUID
    action_key: ActionKey
    description: str = Field(min_length=1)
    state: str = Field(default='proposed', pattern=r'^(proposed|awaiting_approval|approved|rejected|unsupported|executed)$')


class Approval(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    proposal_id: UUID
    approved_by: str = Field(min_length=1)
    at: AwareDatetime = Field(default_factory=utc_now)
    decision: str = Field(pattern=r'^(approved|rejected)$')
    reason: str | None = None


class ExecutionResult(ContractModel):
    id: UUID
    proposal_id: UUID
    action_key: ActionKey
    state: str = Field(pattern=r'^(requested|applied|unsupported|failed|cancelled|indeterminate)$')
    requested_at: AwareDatetime
    detail: str | None = None


class RetestResult(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    finding_id: UUID
    scan_id: UUID
    exploit_outcome: CheckOutcome
    legitimate_flow_outcome: CheckOutcome
    outcome: str = Field(pattern=r'^(resolved|failed|inconclusive|cancelled)$')
    created_at: AwareDatetime = Field(default_factory=utc_now)
    detail: str | None = None

    @model_validator(mode='after')
    def resolution_requires_both_checks(self):
        if self.outcome == 'resolved' and (self.exploit_outcome != CheckOutcome.passed or self.legitimate_flow_outcome != CheckOutcome.passed):
            raise ValueError('resolution requires passed exploit and legitimate-flow checks')
        return self


class RequestAuditEvent(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    scan_id: UUID
    at: AwareDatetime = Field(default_factory=utc_now)
    method: str = Field(pattern=r'^(GET|POST|PUT|PATCH|DELETE)$')
    normalized_path: str = Field(pattern=r'^/')
    purpose: str = Field(min_length=1)
    outcome: str = Field(min_length=1)
    status: int | None = Field(default=None, ge=100, le=599)
    redacted_body_shape: dict[str, Any] = Field(default_factory=dict)


def map_sandbox_execution(proposal: RemediationProposal, response: dict[str, Any], *, received_at: datetime | None = None) -> ExecutionResult:
    """Pure adapter; caller supplies the approved proposal and handles lifecycle decisions."""
    state = response.get('state')
    if state not in {'applied', 'unsupported', 'failed'}:
        raise ValueError('unsupported sandbox execution state')
    if response.get('action_key', proposal.action_key.value) != proposal.action_key.value:
        raise ValueError('sandbox action does not match proposal')
    if state in {'applied', 'unsupported'} and ('execution_id' not in response or 'requested_at' not in response):
        raise ValueError('sandbox execution response is incomplete')
    return ExecutionResult(
        id=response.get('execution_id', uuid4()), proposal_id=proposal.id,
        action_key=proposal.action_key, state=state,
        requested_at=response.get('requested_at', received_at or utc_now()),
        detail=response.get('detail'),
    )


class InventorySnapshot(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    target_id: str = Field(min_length=1)
    captured_at: AwareDatetime = Field(default_factory=utc_now)
    endpoints: list[Endpoint] = Field(default_factory=list)
    synthetic: bool = True


class ChangeEvent(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    scan_id: UUID
    target_id: str = Field(min_length=1)
    at: AwareDatetime = Field(default_factory=utc_now)
    method: str = Field(pattern=r'^(GET|POST|PUT|PATCH|DELETE)$')
    normalized_path: str = Field(pattern=r'^/')
    change: str = Field(pattern=r'^(added|removed|metadata_changed)$')
    risk_score: int = Field(ge=0, le=100)
    reasons: list[str] = Field(default_factory=list)
    recommended_test_families: list[str] = Field(default_factory=list)
