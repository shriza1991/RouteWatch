from uuid import uuid4

from fastapi.testclient import TestClient

from persistence import V1Store
from shared.v1 import Approval, Finding, MinimalProof, RemediationProposal, ScanRun
from transport.api import create_app


class ApprovalDomain:
    def approve(self, proposal, reviewer_id, decision):
        return Approval(
            proposal_id=proposal.id,
            approved_by=reviewer_id,
            decision=decision,
        )


def test_v1_approval_requires_configured_reviewer_token(tmp_path):
    store = V1Store(tmp_path / "reviewer.db")
    scan = ScanRun(target_id="local-sandbox", state="completed")
    finding = Finding(
        scan_id=scan.id,
        rule_id="cross_agency_access",
        severity="high",
        business_impact="Synthetic cross-agency booking disclosure",
        minimal_proof=MinimalProof(
            request={"method": "GET", "path": "/api/v2/bookings/{id}"},
            response={"agency_id": "agency-b"},
            legitimate_control={"agency_id": "agency-a"},
        ),
    )
    proposal = RemediationProposal(
        finding_id=finding.id,
        action_key="enforce_booking_ownership",
        description="Enable the predefined synthetic ownership control",
    )
    with store.transaction() as tx:
        tx.scans.save(scan)
        tx.findings.save(finding)
        tx.proposals.save(proposal)

    app = create_app(
        store=store,
        domain=ApprovalDomain(),
        reviewer_id="local-demo-reviewer",
        reviewer_token="reviewer-secret-for-test",
    )
    with TestClient(app) as client:
        route = f"/v1/proposals/{proposal.id}/approval"
        body = {"decision": "approved"}
        assert client.post(route, json=body, headers={"Idempotency-Key": "missing"}).status_code == 401
        assert client.post(route, json=body, headers={
            "Idempotency-Key": "wrong", "X-Reviewer-Token": "not-the-token"
        }).status_code == 401
        accepted = client.post(route, json=body, headers={
            "Idempotency-Key": "correct", "X-Reviewer-Token": "reviewer-secret-for-test"
        })
        assert accepted.status_code == 200
        assert accepted.json()["approved_by"] == "local-demo-reviewer"
        assert accepted.json()["decision"] == "approved"
