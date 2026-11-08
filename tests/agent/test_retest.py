import pytest
from agent.domain.models import DomainFinding
from agent.domain.retest import decide_retest


@pytest.fixture
def finding():
    return DomainFinding(
        scan_id="scan-123",
        rule_id="cross_agency_access",
        title="Cross-agency booking access",
        business_impact="Impact description",
        minimal_proof={},
        suggested_fix="Fix description",
        state="verified",
    )


def test_retest_resolves_when_exploit_blocked_and_legitimate_ok(finding):
    res = decide_retest(finding, scan_id="scan-retest-1", exploit_blocked=True, legitimate_flow_ok=True)
    assert res.outcome == "resolved"
    assert res.exploit_blocked is True
    assert res.legitimate_flow_ok is True
    assert finding.state == "resolved"


def test_retest_fails_when_exploit_still_reproduces(finding):
    res = decide_retest(finding, scan_id="scan-retest-2", exploit_blocked=False, legitimate_flow_ok=True)
    assert res.outcome == "failed"
    assert res.exploit_blocked is False
    assert finding.state == "retest_failed"


def test_retest_fails_when_legitimate_flow_broken(finding):
    # E.g. someone fixed the bug by disabling the whole endpoint, breaking legitimate users!
    res = decide_retest(finding, scan_id="scan-retest-3", exploit_blocked=True, legitimate_flow_ok=False)
    assert res.outcome == "failed"
    assert res.legitimate_flow_ok is False
    assert finding.state == "retest_failed"


def test_retest_cancelled_leaves_finding_unresolved(finding):
    res = decide_retest(finding, scan_id="scan-retest-4", exploit_blocked=False, legitimate_flow_ok=False, cancelled=True)
    assert res.outcome == "cancelled"
    # Finding must NOT be resolved or marked retest_failed if the test was cancelled
    assert finding.state == "verified"
