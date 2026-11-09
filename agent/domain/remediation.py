"""Approval-gated remediation orchestration."""
from typing import Any, Awaitable, Callable
import uuid
from agent.domain.models import Approval, DomainFinding, ExecutionResult, RemediationProposal, utc_now

SUPPORTED_ACTIONS: dict[str, str] = {
    "cross_agency_access": "enforce_booking_ownership",
    "fare_tampering": "validate_quote_fare",
    "legacy_booking": "disable_legacy_booking",
}

ACTION_DESCRIPTIONS: dict[str, str] = {
    "enforce_booking_ownership": "Enforce strict tenant and agency ownership checks on booking retrieval endpoints.",
    "validate_quote_fare": "Enforce server-side verification of quoted fare when creating bookings.",
    "disable_legacy_booking": "Retire and disable deprecated legacy v1 booking route.",
}


def create_proposal(finding: DomainFinding) -> RemediationProposal:
    action_key = SUPPORTED_ACTIONS.get(finding.rule_id, "unknown_action")
    desc = ACTION_DESCRIPTIONS.get(action_key, finding.suggested_fix)
    return RemediationProposal(
        finding_id=finding.id,
        action_key=action_key,
        description=desc,
        state="proposed",
    )


async def execute_remediation(
    proposal: RemediationProposal,
    approval: Approval,
    management_adapter: Callable[[str, str], Awaitable[dict[str, Any]]],
    idempotency_key: str | None = None,
) -> ExecutionResult:
    """Execute remediation ONLY with valid approval.
    
    Management credentials and URLs must never leak to audits, browser or test plans.
    """
    if approval.proposal_id != proposal.id:
        raise ValueError("Approval does not match the remediation proposal")

    if approval.decision != "approved":
        return ExecutionResult(
            proposal_id=proposal.id,
            state="failed",
            detail=f"Proposal was not approved (decision: {approval.decision})",
        )

    if proposal.action_key not in ACTION_DESCRIPTIONS:
        proposal.state = "failed"
        return ExecutionResult(
            proposal_id=proposal.id,
            state="unsupported",
            detail=f"Action '{proposal.action_key}' is not a supported predefined action",
        )

    proposal.state = "approved"
    idem_key = idempotency_key or str(uuid.uuid4())

    try:
        adapter_res = await management_adapter(proposal.action_key, idem_key)
        state = adapter_res.get("state", "applied")
        proposal.state = "applied" if state == "applied" else "failed"
        return ExecutionResult(
            proposal_id=proposal.id,
            state="applied" if state == "applied" else "failed",
            detail=f"Management adapter returned state: {state}",
        )
    except Exception as e:
        proposal.state = "failed"
        return ExecutionResult(
            proposal_id=proposal.id,
            state="failed",
            detail=f"Management adapter failed: {str(e)}",
        )
