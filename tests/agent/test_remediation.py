import pytest
from agent.domain.models import Approval, DomainFinding
from agent.domain.remediation import create_proposal, execute_remediation


@pytest.fixture
def sample_finding():
    return DomainFinding(
        scan_id="scan-123",
        rule_id="cross_agency_access",
        title="Cross-agency booking access",
        business_impact="Agency A can access Agency B data.",
        minimal_proof={"foreign_request": {"path": "/api/v2/bookings/1"}},
        suggested_fix="Enforce agency ownership on every booking lookup.",
    )


def test_create_proposal_for_ownership(sample_finding):
    prop = create_proposal(sample_finding)
    assert prop.finding_id == sample_finding.id
    assert prop.action_key == "enforce_booking_ownership"
    assert prop.state == "proposed"


@pytest.mark.asyncio
async def test_execute_remediation_requires_approval(sample_finding):
    prop = create_proposal(sample_finding)
    rejected_approval = Approval(
        proposal_id=prop.id,
        approved_by="operator-admin",
        decision="rejected",
        reason="Not ready yet",
    )

    adapter_called = False

    async def fake_adapter(action_key: str, idempotency_key: str):
        nonlocal adapter_called
        adapter_called = True
        return {"state": "applied"}

    res = await execute_remediation(prop, rejected_approval, fake_adapter)
    assert res.state == "failed"
    assert not adapter_called
    assert prop.state == "proposed"


@pytest.mark.asyncio
async def test_execute_remediation_success_on_approved(sample_finding):
    prop = create_proposal(sample_finding)
    approved = Approval(
        proposal_id=prop.id,
        approved_by="operator-admin",
        decision="approved",
    )

    called_with = {}

    async def fake_adapter(action_key: str, idempotency_key: str):
        called_with["action_key"] = action_key
        called_with["idempotency_key"] = idempotency_key
        return {"state": "applied"}

    res = await execute_remediation(prop, approved, fake_adapter, idempotency_key="test-key-1")
    assert res.state == "applied"
    assert prop.state == "applied"
    assert called_with["action_key"] == "enforce_booking_ownership"
    assert called_with["idempotency_key"] == "test-key-1"


@pytest.mark.asyncio
async def test_execute_remediation_unsupported_action(sample_finding):
    sample_finding.rule_id = "non_existent_rule"
    prop = create_proposal(sample_finding)
    approved = Approval(proposal_id=prop.id, approved_by="admin", decision="approved")

    async def fake_adapter(action_key: str, idempotency_key: str):
        return {"state": "applied"}

    res = await execute_remediation(prop, approved, fake_adapter)
    assert res.state == "unsupported"
