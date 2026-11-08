"""Domain data models for agent execution, rules, remediation and retesting."""
from datetime import datetime, timezone
from typing import Any, Literal
import uuid
from pydantic import BaseModel, Field
from shared.schemas import TargetConfig, AccountContext, ObservedRequest


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


ScanState = Literal["queued", "running", "cancelling", "cancelled", "failed", "completed"]
TestOutcome = Literal["pass", "finding", "inconclusive", "cancelled", "error"]
FindingState = Literal[
    "open", "verified", "awaiting_approval", "approved", "remediating", "retesting", "resolved",
    "unsupported", "remediation_failed", "retest_failed", "inconclusive", "cancelled"
]


class RequestAuditEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    scan_id: str
    at: str = Field(default_factory=utc_now)
    method: str
    normalized_path: str
    purpose: str
    outcome: str
    status: int | None = None
    redacted_body_shape: dict[str, Any] | None = None


class TestPlan(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    scan_id: str
    rule_id: str
    observed_request_ids: list[str] = Field(default_factory=list)
    account_context_ids: list[str] = Field(default_factory=list)
    budget: int = 10
    status: Literal["pending", "executing", "completed", "cancelled"] = "pending"


class DomainFinding(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    scan_id: str
    rule_id: str
    severity: Literal["critical", "high", "medium", "low"] = "high"
    title: str
    business_impact: str
    minimal_proof: dict[str, Any]
    suggested_fix: str
    state: FindingState = "verified"
    created_at: str = Field(default_factory=utc_now)


class TestResult(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    plan_id: str
    outcome: TestOutcome
    evidence_ids: list[str] = Field(default_factory=list)
    finding: DomainFinding | None = None
    error: str | None = None


class RemediationProposal(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    finding_id: str
    action_key: str
    description: str
    state: Literal["proposed", "approved", "rejected", "applied", "failed"] = "proposed"


class Approval(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    proposal_id: str
    approved_by: str
    at: str = Field(default_factory=utc_now)
    decision: Literal["approved", "rejected"]
    reason: str | None = None


class ExecutionResult(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    proposal_id: str
    state: Literal["requested", "applied", "unsupported", "failed", "cancelled"]
    requested_at: str = Field(default_factory=utc_now)
    detail: str | None = None


class RetestResult(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    finding_id: str
    scan_id: str
    exploit_blocked: bool
    legitimate_flow_ok: bool
    outcome: Literal["resolved", "failed", "inconclusive", "cancelled"]
    detail: str
    created_at: str = Field(default_factory=utc_now)
