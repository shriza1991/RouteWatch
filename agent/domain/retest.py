"""Independent retest decision logic."""
from agent.domain.models import DomainFinding, RetestResult


def decide_retest(
    finding: DomainFinding,
    scan_id: str,
    exploit_blocked: bool,
    legitimate_flow_ok: bool,
    cancelled: bool = False,
) -> RetestResult:
    """Decide retest outcome independently.
    
    A finding transitions to 'resolved' ONLY IF:
    1. The exploit attempt is confirmed blocked (`exploit_blocked == True`), AND
    2. The normal, legitimate baseline workflow succeeds (`legitimate_flow_ok == True`).
    
    If cancelled, the finding remains unresolved.
    """
    if cancelled:
        # Finding state remains unchanged
        return RetestResult(
            finding_id=finding.id,
            scan_id=scan_id,
            exploit_blocked=False,
            legitimate_flow_ok=False,
            outcome="cancelled",
            detail="Retest cancelled by operator.",
        )

    if exploit_blocked and legitimate_flow_ok:
        finding.state = "resolved"
        return RetestResult(
            finding_id=finding.id,
            scan_id=scan_id,
            exploit_blocked=True,
            legitimate_flow_ok=True,
            outcome="resolved",
            detail="Original proof no longer reproduced; legitimate baseline workflow completed.",
        )

    # Exploit still reproducible or legitimate baseline broke
    finding.state = "retest_failed"
    detail = "Exploit still reproduces." if not exploit_blocked else "Legitimate workflow failed."
    return RetestResult(
        finding_id=finding.id,
        scan_id=scan_id,
        exploit_blocked=exploit_blocked,
        legitimate_flow_ok=legitimate_flow_ok,
        outcome="failed",
        detail=f"Retest failed: {detail}",
    )
