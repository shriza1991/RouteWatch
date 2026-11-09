"""Abstract base rule for security checks."""
from abc import ABC, abstractmethod
from typing import Any
from agent.domain.models import TestPlan, TestResult
from agent.domain.executor import SafeExecutor
from shared.schemas import AccountContext, ObservedRequest


class BaseRule(ABC):
    rule_id: str
    name: str

    @abstractmethod
    def build_plan(
        self,
        scan_id: str,
        observations: list[ObservedRequest],
        contexts: list[AccountContext],
        budget: int = 10,
    ) -> TestPlan:
        """Analyze observations and form an actionable test plan."""
        pass

    @abstractmethod
    async def run_plan(
        self,
        plan: TestPlan,
        executor: SafeExecutor,
        contexts: list[AccountContext],
        observations: list[ObservedRequest],
    ) -> TestResult:
        """Execute the plan safely and return verified finding or pass."""
        pass
