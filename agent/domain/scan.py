"""Scan state machine and lifecycle manager."""
from typing import Any
import uuid
from agent.domain.models import ScanState, utc_now
from shared.schemas import TargetConfig


class ScanStateMachine:
    VALID_TRANSITIONS: dict[ScanState, set[ScanState]] = {
        "queued": {"running", "cancelling", "cancelled", "failed"},
        "running": {"cancelling", "cancelled", "failed", "completed"},
        "cancelling": {"cancelled", "failed"},
        "cancelled": set(),
        "failed": set(),
        "completed": set(),
    }

    def __init__(self, scan_id: str | None = None, config: TargetConfig | None = None):
        self.id = scan_id or str(uuid.uuid4())
        self.config = config
        self.state: ScanState = "queued"
        self.started_at = utc_now()
        self.completed_at: str | None = None
        self.cancel_reason: str | None = None
        self.activity: list[str] = ["Scan queued."]
        self.findings: list[Any] = []
        self.request_count = 0

    def transition_to(self, new_state: ScanState, reason: str | None = None) -> None:
        allowed = self.VALID_TRANSITIONS.get(self.state, set())
        if new_state not in allowed:
            raise ValueError(f"Invalid state transition from {self.state} to {new_state}")

        self.state = new_state
        if new_state == "cancelling":
            self.cancel_reason = reason or "Cancelled by operator."
            self.log_activity(self.cancel_reason)
        elif new_state == "cancelled":
            self.completed_at = utc_now()
            self.cancel_reason = reason or self.cancel_reason or "Cancelled by operator."
            self.log_activity(f"Scan cancelled: {self.cancel_reason}")
        elif new_state in ("completed", "failed"):
            self.completed_at = utc_now()
            if reason:
                self.log_activity(reason)

    def log_activity(self, message: str) -> None:
        self.activity.append(message)

    def cancel(self, reason: str = "Cancelled by operator.") -> None:
        if self.state in ("cancelled", "completed", "failed"):
            return  # Already in terminal state
        if self.state == "queued":
            self.transition_to("cancelled", reason)
        elif self.state == "running":
            self.transition_to("cancelling", reason)
            self.transition_to("cancelled", reason)

    def is_cancelled(self) -> bool:
        return self.state in ("cancelling", "cancelled")

    def is_terminal(self) -> bool:
        return self.state in ("cancelled", "completed", "failed")
