"""Cross-agency access (BOLA / IDOR) rule implementation."""
from typing import Any
from agent.domain.models import DomainFinding, TestPlan, TestResult
from agent.domain.executor import SafeExecutor
from agent.rules.base import BaseRule
from shared.schemas import AccountContext, ObservedRequest


class OwnershipRule(BaseRule):
    rule_id = "cross_agency_access"
    name = "Cross-agency booking access"

    def build_plan(
        self,
        scan_id: str,
        observations: list[ObservedRequest],
        contexts: list[AccountContext],
        budget: int = 10,
    ) -> TestPlan:
        plan = TestPlan(
            scan_id=scan_id,
            rule_id=self.rule_id,
            budget=budget,
            account_context_ids=[c.agency_id for c in contexts],
        )

        if len(contexts) < 2:
            plan.status = "cancelled"
            return plan

        # Check required observed paths
        has_quote = any(o.method == "POST" and "quote" in o.path for o in observations)
        has_book = any(o.method == "POST" and "booking" in o.path for o in observations)
        has_get = any(o.method == "GET" and "booking" in o.path and "{id}" in o.path or "bookings/" in o.path for o in observations)

        if has_quote and has_book and has_get:
            plan.status = "pending"
        else:
            plan.status = "cancelled"
        return plan

    async def run_plan(
        self,
        plan: TestPlan,
        executor: SafeExecutor,
        contexts: list[AccountContext],
        observations: list[ObservedRequest],
    ) -> TestResult:
        if len(contexts) < 2:
            return TestResult(plan_id=plan.id, outcome="inconclusive", error="Two accounts required for BOLA check")

        account_a = contexts[0]
        account_b = contexts[1]

        # Extract endpoints from observations
        quote_obs = next((o for o in observations if o.method == "POST" and "quote" in o.path), None)
        book_obs = next((o for o in observations if o.method == "POST" and "booking" in o.path), None)
        read_obs = next(
            (o for o in observations if o.method == "GET" and "booking" in o.path and ("v2" in o.path or "{id}" in o.path)),
            None
        )

        if not quote_obs or not book_obs or not read_obs:
            return TestResult(plan_id=plan.id, outcome="inconclusive", error="Missing required observed endpoints")

        quote_path = quote_obs.path
        book_path = book_obs.path
        read_pattern = read_obs.path if "{id}" in read_obs.path else "/api/v2/bookings/{id}"
        route = (quote_obs.body or {}).get("route", "DEL-BOM")

        try:
            # 1. Baseline for Agency A
            st, qa = await executor.request("POST", quote_path, account_a, {"route": route}, "quote baseline A")
            if st >= 400 or "quote_id" not in qa:
                return TestResult(plan_id=plan.id, outcome="inconclusive", error="Baseline quote for Agency A failed")

            st, ba = await executor.request(
                "POST", book_path, account_a,
                {"quote_id": qa["quote_id"], "traveler": "Baseline A", "fare": qa.get("fare", 120.0)},
                "booking baseline A"
            )
            if st >= 400 or "booking_id" not in ba:
                return TestResult(plan_id=plan.id, outcome="inconclusive", error="Baseline booking for Agency A failed")

            # 2. Baseline for Agency B
            st, qb = await executor.request("POST", quote_path, account_b, {"route": route}, "quote baseline B")
            if st >= 400 or "quote_id" not in qb:
                return TestResult(plan_id=plan.id, outcome="inconclusive", error="Baseline quote for Agency B failed")

            st, bb = await executor.request(
                "POST", book_path, account_b,
                {"quote_id": qb["quote_id"], "traveler": "Baseline B", "fare": qb.get("fare", 120.0)},
                "booking baseline B"
            )
            if st >= 400 or "booking_id" not in bb:
                return TestResult(plan_id=plan.id, outcome="inconclusive", error="Baseline booking for Agency B failed")

            # 3. Control check: Agency A reads Agency A's own booking
            own_path = read_pattern.replace("{id}", ba["booking_id"])
            st_control, body_control = await executor.request("GET", own_path, account_a, purpose="legitimate ownership control")
            if st_control != 200 or body_control.get("agency_id") != account_a.agency_id:
                return TestResult(plan_id=plan.id, outcome="inconclusive", error="Legitimate control read failed")

            # 4. Exploit check: Agency A reads Agency B's booking
            foreign_path = read_pattern.replace("{id}", bb["booking_id"])
            st_foreign, body_foreign = await executor.request("GET", foreign_path, account_a, purpose="cross-agency ownership test")

            # Evaluate finding condition:
            # Foreign read returned 200 AND returned B's booking data to Agency A
            if st_foreign == 200 and body_foreign.get("booking_id") == bb["booking_id"] and body_foreign.get("agency_id") == account_b.agency_id:
                proof = {
                    "foreign_request": {"method": "GET", "path": foreign_path, "account": account_a.agency_id},
                    "returned": {
                        "booking_id": body_foreign.get("booking_id"),
                        "agency_id": body_foreign.get("agency_id"),
                        "traveler": body_foreign.get("traveler"),
                    },
                    "control": {
                        "booking_id": body_control.get("booking_id"),
                        "agency_id": body_control.get("agency_id"),
                    },
                }
                finding = DomainFinding(
                    scan_id=plan.scan_id,
                    rule_id=self.rule_id,
                    severity="high",
                    title="Cross-agency booking access",
                    business_impact="One travel agency can view another agency's booking and traveler data.",
                    minimal_proof=proof,
                    suggested_fix="Enforce agency ownership on every booking lookup, including legacy routes.",
                    state="verified",
                )
                return TestResult(plan_id=plan.id, outcome="finding", finding=finding)

            # Exploit was blocked (e.g. 403 Forbidden) and control succeeded
            return TestResult(plan_id=plan.id, outcome="pass")

        except RuntimeError as e:
            if "cancelled" in str(e):
                return TestResult(plan_id=plan.id, outcome="cancelled")
            return TestResult(plan_id=plan.id, outcome="error", error=str(e))
        except Exception as e:
            return TestResult(plan_id=plan.id, outcome="error", error=str(e))
