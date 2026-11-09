import pytest
import httpx
from agent.domain.executor import SafeExecutor
from agent.rules.ownership import OwnershipRule
from agent.rules.fare import FareTamperingRule
from sandbox import app as sandbox_app
from shared.schemas import TargetConfig, AccountContext, ObservedRequest


@pytest.fixture(autouse=True)
def setup_sandbox(tmp_path, monkeypatch):
    db_file = tmp_path / "test_sandbox.db"
    monkeypatch.setattr(sandbox_app, "DB", db_file)
    sandbox_app.init()
    sandbox_app.reset()


@pytest.fixture
def target_config():
    return TargetConfig(
        base_url="http://testserver",
        allowed_origins=["http://testserver"],
        accounts=[
            AccountContext(name="A", agency_id="agency-a", user_id="u-a", token="tok-a"),
            AccountContext(name="B", agency_id="agency-b", user_id="u-b", token="tok-b"),
        ],
        max_requests=20,
    )


@pytest.fixture
def observations():
    return [
        ObservedRequest(method="POST", path="/api/v2/quotes", body={"route": "DEL-BOM"}),
        ObservedRequest(method="POST", path="/api/v2/bookings", body={"route": "DEL-BOM"}),
        ObservedRequest(method="GET", path="/api/v2/bookings/{id}"),
    ]


@pytest.mark.asyncio
async def test_ownership_rule_detects_bola_in_vulnerable_mode(target_config, observations):
    # Ensure vulnerable mode
    sandbox_app.set_mode("vulnerable")

    transport = httpx.ASGITransport(app=sandbox_app.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        executor = SafeExecutor(target_config, scan_id="test-scan-1", client=client)
        rule = OwnershipRule()
        plan = rule.build_plan("test-scan-1", observations, target_config.accounts)
        assert plan.status == "pending"

        result = await rule.run_plan(plan, executor, target_config.accounts, observations)
        assert result.outcome == "finding"
        assert result.finding is not None
        assert result.finding.rule_id == "cross_agency_access"
        assert result.finding.minimal_proof["returned"]["agency_id"] == "agency-b"
        assert result.finding.minimal_proof["control"]["agency_id"] == "agency-a"


@pytest.mark.asyncio
async def test_ownership_rule_passes_in_fixed_mode(target_config, observations):
    # Enable fixed mode (enforces booking ownership)
    sandbox_app.set_mode("fixed")

    transport = httpx.ASGITransport(app=sandbox_app.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        executor = SafeExecutor(target_config, scan_id="test-scan-2", client=client)
        rule = OwnershipRule()
        plan = rule.build_plan("test-scan-2", observations, target_config.accounts)

        result = await rule.run_plan(plan, executor, target_config.accounts, observations)
        assert result.outcome == "pass"
        assert result.finding is None


@pytest.mark.asyncio
async def test_ownership_rule_inconclusive_with_single_account(target_config, observations):
    single_account = [target_config.accounts[0]]
    rule = OwnershipRule()
    plan = rule.build_plan("test-scan-3", observations, single_account)
    assert plan.status == "cancelled"

    transport = httpx.ASGITransport(app=sandbox_app.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        executor = SafeExecutor(target_config, scan_id="test-scan-3", client=client)
        result = await rule.run_plan(plan, executor, single_account, observations)
        assert result.outcome == "inconclusive"


@pytest.mark.asyncio
async def test_fare_rule_detects_tampering_in_vulnerable_mode(target_config, observations):
    sandbox_app.set_mode("vulnerable")

    transport = httpx.ASGITransport(app=sandbox_app.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        executor = SafeExecutor(target_config, scan_id="test-scan-4", client=client)
        rule = FareTamperingRule()
        plan = rule.build_plan("test-scan-4", observations, target_config.accounts)
        assert plan.status == "pending"

        result = await rule.run_plan(plan, executor, target_config.accounts, observations)
        assert result.outcome == "finding"
        assert result.finding is not None
        assert result.finding.rule_id == "fare_tampering"
        assert result.finding.minimal_proof["response"]["fare"] < result.finding.minimal_proof["response"]["quote_fare"]


@pytest.mark.asyncio
async def test_fare_rule_passes_in_fixed_mode(target_config, observations):
    sandbox_app.set_mode("fixed")

    transport = httpx.ASGITransport(app=sandbox_app.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        executor = SafeExecutor(target_config, scan_id="test-scan-5", client=client)
        rule = FareTamperingRule()
        plan = rule.build_plan("test-scan-5", observations, target_config.accounts)

        result = await rule.run_plan(plan, executor, target_config.accounts, observations)
        assert result.outcome == "pass"
        assert result.finding is None
