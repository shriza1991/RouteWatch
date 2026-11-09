"""Client-side fare tampering rule implementation."""
from typing import Any
from agent.domain.models import DomainFinding, TestPlan, TestResult
from agent.domain.executor import SafeExecutor
from agent.rules.base import BaseRule
from shared.schemas import AccountContext, ObservedRequest


class FareTamperingRule(BaseRule):
    rule_id = "fare_tampering"
    name = "Client-controlled fare accepted"

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

        has_quote = any(o.method == "POST" and "quote" in o.path for o in observations)
        has_book = any(o.method == "POST" and "booking" in o.path for o in observations)

        if contexts and has_quote and has_book:
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
        if not contexts:
            return TestResult(plan_id=plan.id, outcome="inconclusive", error="Account required for fare test")

        account = contexts[0]
        quote_obs = next((o for o in observations if o.method == "POST" and "quote" in o.path), None)
        book_obs = next((o for o in observations if o.method == "POST" and "booking" in o.path), None)

        if not quote_obs or not book_obs:
            return TestResult(plan_id=plan.id, outcome="inconclusive", error="Missing quote or booking endpoints")

        quote_path = quote_obs.path
        book_path = book_obs.path
        route = (quote_obs.body or {}).get("route", "DEL-BOM")

        try:
            # 1. Obtain legitimate quote
            st_q, quote = await executor.request("POST", quote_path, account, {"route": route}, "legitimate quote baseline")
            if st_q >= 400 or "quote_id" not in quote:
                return TestResult(plan_id=plan.id, outcome="inconclusive", error="Failed to obtain quote")

            quoted_fare = float(quote.get("fare", 120.0))
            tampered_fare = max(1.0, quoted_fare - 1.0)

            # 2. Submit booking with tampered fare
            st_b, booking = await executor.request(
                "POST", book_path, account,
                {"quote_id": quote["quote_id"], "traveler": "Tamper Test", "fare": tampered_fare},
                "fare tampering test"
            )

            # Finding condition:
            # Server responded 200/201 and stored the client's tampered fare instead of the quote fare
            actual_fare = float(booking.get("fare", 0.0)) if isinstance(booking, dict) else 0.0
            server_quote_fare = float(booking.get("quote_fare", 0.0)) if isinstance(booking, dict) else 0.0

            if st_b < 400 and actual_fare == tampered_fare and actual_fare != quoted_fare:
                proof = {
                    "request": {
                        "method": "POST",
                        "path": book_path,
                        "body": {"quote_id": "[redacted]", "fare": tampered_fare},
                    },
                    "response": {
                        "booking_id": booking.get("booking_id"),
                        "fare": actual_fare,
                        "quote_fare": server_quote_fare or quoted_fare,
                    },
                }
                finding = DomainFinding(
                    scan_id=plan.scan_id,
                    rule_id=self.rule_id,
                    severity="high",
                    title="Client-controlled fare accepted",
                    business_impact="A booking can be confirmed for a modified synthetic fare.",
                    minimal_proof=proof,
                    suggested_fix="Calculate or validate the payable fare server-side from the quote.",
                    state="verified",
                )
                return TestResult(plan_id=plan.id, outcome="finding", finding=finding)

            # If server recalculated/enforced quote fare or rejected the booking
            return TestResult(plan_id=plan.id, outcome="pass")

        except RuntimeError as e:
            if "cancelled" in str(e):
                return TestResult(plan_id=plan.id, outcome="cancelled")
            return TestResult(plan_id=plan.id, outcome="error", error=str(e))
        except Exception as e:
            return TestResult(plan_id=plan.id, outcome="error", error=str(e))
