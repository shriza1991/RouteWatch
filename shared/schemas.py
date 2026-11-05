"""Shared, versioned API contracts. Owners coordinate changes here first."""
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field

class AccountContext(BaseModel):
    name: str
    agency_id: str
    user_id: str
    token: str

class TargetConfig(BaseModel):
    id: str = "local-sandbox"
    base_url: str
    allowed_origins: list[str]
    accounts: list[AccountContext]
    max_requests: int = Field(default=40, ge=1, le=200)
    timeout_seconds: float = Field(default=3, gt=0, le=15)
    reference_profile: Literal["initial", "documented"] = "initial"

class ObservedRequest(BaseModel):
    method: str
    path: str
    status: int | None = None
    body: dict[str, Any] | None = None
    timestamp: datetime | None = None
    source: str = "synthetic HAR"

class Endpoint(BaseModel):
    method: str
    path: str
    reachable: bool | None = None
    classification: Literal["active", "zombie", "shadow", "unknown"] = "unknown"
    evidence: list[str] = []

class Finding(BaseModel):
    id: str
    scan_id: str
    kind: str
    severity: Literal["critical", "high", "medium", "low"]
    title: str
    business_impact: str
    proof: dict[str, Any]
    suggested_fix: str
    status: Literal["open", "fixed", "retest_passed"] = "open"
    created_at: datetime

class RetestResult(BaseModel):
    finding_id: str
    passed: bool
    detail: str
    legitimate_access_ok: bool
    created_at: datetime

class ScanRun(BaseModel):
    id: str
    target_id: str
    status: Literal["running", "completed", "cancelled", "failed"]
    started_at: datetime
    completed_at: datetime | None = None
    activity: list[str] = []
    endpoints: list[Endpoint] = []
    finding_ids: list[str] = []
    request_count: int = 0
