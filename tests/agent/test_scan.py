import pytest
from agent.domain.scan import ScanStateMachine
from shared.schemas import TargetConfig, AccountContext


@pytest.fixture
def target_config():
    return TargetConfig(
        base_url="http://127.0.0.1:8000",
        allowed_origins=["http://127.0.0.1:8000"],
        accounts=[
            AccountContext(name="A", agency_id="agency-a", user_id="u-a", token="tok-a"),
            AccountContext(name="B", agency_id="agency-b", user_id="u-b", token="tok-b"),
        ],
    )


def test_scan_lifecycle_normal(target_config):
    sm = ScanStateMachine(config=target_config)
    assert sm.state == "queued"
    assert not sm.is_terminal()

    sm.transition_to("running")
    assert sm.state == "running"

    sm.transition_to("completed", reason="All tests completed successfully.")
    assert sm.state == "completed"
    assert sm.is_terminal()
    assert sm.completed_at is not None


def test_scan_cancellation_from_running(target_config):
    sm = ScanStateMachine(config=target_config)
    sm.transition_to("running")
    sm.cancel("Operator aborted scan.")

    assert sm.state == "cancelled"
    assert sm.is_cancelled()
    assert sm.is_terminal()
    assert sm.cancel_reason == "Operator aborted scan."


def test_scan_cancellation_from_queued(target_config):
    sm = ScanStateMachine(config=target_config)
    sm.cancel("Cancelled before start.")
    assert sm.state == "cancelled"
    assert sm.is_terminal()


def test_invalid_transitions(target_config):
    sm = ScanStateMachine(config=target_config)
    sm.transition_to("running")
    sm.transition_to("completed")

    with pytest.raises(ValueError, match="Invalid state transition"):
        sm.transition_to("running")

    with pytest.raises(ValueError, match="Invalid state transition"):
        sm.transition_to("queued")
