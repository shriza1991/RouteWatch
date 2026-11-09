"""Safe HTTP executor enforcing scope, timeout, budget, redirect safety and audit logging."""
from typing import Any, Callable
from urllib.parse import urlparse
import httpx
from shared.schemas import TargetConfig, AccountContext
from agent.domain.models import RequestAuditEvent


class SafeExecutor:
    def __init__(
        self,
        config: TargetConfig,
        scan_id: str,
        is_cancelled_fn: Callable[[], bool] | None = None,
        audit_callback: Callable[[RequestAuditEvent], None] | None = None,
        client: httpx.AsyncClient | None = None,
    ):
        self.config = config
        self.scan_id = scan_id
        self.is_cancelled_fn = is_cancelled_fn
        self.audit_callback = audit_callback
        self.client = client
        self.used = 0
        self.audits: list[RequestAuditEvent] = []

        # Validate allowed origins on init
        self._allowed_netlocs = set()
        for origin in self.config.allowed_origins:
            parsed = urlparse(origin)
            self._allowed_netlocs.add(parsed.netloc)

    def _check_scope(self, url: str) -> None:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self.config.allowed_origins and parsed.netloc not in self._allowed_netlocs:
            raise RuntimeError(f"target outside configured scope: {origin}")

    def _record_audit(self, method: str, path: str, purpose: str, status: int | None, outcome: str, body: Any = None) -> RequestAuditEvent:
        shape = None
        if isinstance(body, dict):
            shape = {k: "[redacted]" if any(s in k.lower() for s in ("token", "secret", "auth", "password")) else type(v).__name__ for k, v in body.items()}

        evt = RequestAuditEvent(
            scan_id=self.scan_id,
            method=method,
            normalized_path=path,
            purpose=purpose,
            outcome=outcome,
            status=status,
            redacted_body_shape=shape,
        )
        self.audits.append(evt)
        if self.audit_callback:
            self.audit_callback(evt)
        return evt

    async def request(
        self,
        method: str,
        path: str,
        account: AccountContext | None = None,
        json_body: dict[str, Any] | None = None,
        purpose: str = "probe",
    ) -> tuple[int, Any]:
        if self.is_cancelled_fn and self.is_cancelled_fn():
            self._record_audit(method, path, purpose, None, "cancelled_before_request", json_body)
            raise RuntimeError("scan cancelled by operator")

        if self.used >= self.config.max_requests:
            self._record_audit(method, path, purpose, None, "budget_exhausted", json_body)
            raise RuntimeError("request budget reached")

        full_url = self.config.base_url.rstrip("/") + path
        self._check_scope(full_url)

        headers: dict[str, str] = {}
        if account:
            headers["X-Agency"] = account.agency_id
            headers["X-User"] = account.user_id
            headers["Authorization"] = "Bearer [REDACTED]"

        self.used += 1

        async def _do_req(xclient: httpx.AsyncClient) -> tuple[int, Any]:
            resp = await xclient.request(
                method,
                full_url,
                headers=headers,
                json=json_body,
                follow_redirects=False,
            )

            # Check redirect safety
            if resp.is_redirect:
                location = resp.headers.get("location", "")
                loc_netloc = urlparse(location).netloc
                if loc_netloc and loc_netloc not in self._allowed_netlocs:
                    self._record_audit(method, path, purpose, resp.status_code, "out_of_scope_redirect_rejected", json_body)
                    raise RuntimeError(f"out-of-scope redirect rejected: {location}")

            try:
                data = resp.json()
            except Exception:
                data = {"text": resp.text[:200]}

            self._record_audit(method, path, purpose, resp.status_code, "completed", json_body)
            return resp.status_code, data

        if self.client:
            return await _do_req(self.client)

        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
            return await _do_req(client)
