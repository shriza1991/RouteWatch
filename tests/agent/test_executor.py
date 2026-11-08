import httpx
import pytest
from agent.domain.executor import SafeExecutor
from shared.schemas import TargetConfig, AccountContext


@pytest.fixture
def config():
    return TargetConfig(
        base_url="http://127.0.0.1:8000",
        allowed_origins=["http://127.0.0.1:8000"],
        accounts=[
            AccountContext(name="A", agency_id="agency-a", user_id="u-a", token="tok-a"),
        ],
        max_requests=3,
        timeout_seconds=2,
    )


@pytest.mark.asyncio
async def test_scope_validation_blocks_external_url(config):
    executor = SafeExecutor(config, scan_id="test-scan")
    with pytest.raises(RuntimeError, match="target outside configured scope"):
        # Attempt to access external URL
        await executor.request("GET", "http://evil.com/leak")


@pytest.mark.asyncio
async def test_budget_exhaustion(config):
    mock_handler = httpx.MockTransport(lambda req: httpx.Response(200, json={"ok": True}))
    async with httpx.AsyncClient(transport=mock_handler) as client:
        executor = SafeExecutor(config, scan_id="test-scan", client=client)
        # Config max_requests is 3
        await executor.request("GET", "/api/1")
        await executor.request("GET", "/api/2")
        await executor.request("GET", "/api/3")
        assert executor.used == 3

        with pytest.raises(RuntimeError, match="request budget reached"):
            await executor.request("GET", "/api/4")


@pytest.mark.asyncio
async def test_cancellation_check(config):
    cancelled = True
    executor = SafeExecutor(
        config,
        scan_id="test-scan",
        is_cancelled_fn=lambda: cancelled,
    )
    with pytest.raises(RuntimeError, match="scan cancelled by operator"):
        await executor.request("GET", "/api/test")


@pytest.mark.asyncio
async def test_out_of_scope_redirect_rejected(config):
    def redirect_handler(request: httpx.Request):
        return httpx.Response(302, headers={"Location": "http://evil.com/steal"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(redirect_handler)) as client:
        executor = SafeExecutor(config, scan_id="test-scan", client=client)
        with pytest.raises(RuntimeError, match="out-of-scope redirect rejected"):
            await executor.request("GET", "/redirect")


@pytest.mark.asyncio
async def test_audit_redacts_credentials(config):
    def normal_handler(request: httpx.Request):
        assert request.headers.get("Authorization") == "Bearer [REDACTED]"
        return httpx.Response(200, json={"result": "success"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(normal_handler)) as client:
        executor = SafeExecutor(config, scan_id="test-scan", client=client)
        st, data = await executor.request(
            "POST",
            "/api/test",
            account=config.accounts[0],
            json_body={"token": "secret123", "data": "hello"},
            purpose="test probe",
        )
        assert st == 200
        assert len(executor.audits) == 1
        audit = executor.audits[0]
        assert audit.redacted_body_shape["token"] == "[redacted]"
