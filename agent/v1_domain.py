"""Integrated v1 scan, remediation and independent retest domain service.

This runtime is intentionally restricted to the repository's synthetic RouteWatch
sandbox. It is not a production DAST runner and refuses arbitrary internet targets.
"""
from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import unquote, urlsplit
from uuid import UUID, uuid4

import httpx

from discovery.changes import compare_inventory, recommended_test_families
from discovery.runtime import FixtureInventoryService
from persistence import V1Store
from shared.v1 import (
    ActionKey, Approval, CheckOutcome, ChangeEvent, Endpoint, ExecutionResult,
    Finding, InventorySnapshot, MinimalProof, RemediationProposal,
    RequestAuditEvent, RetestResult, ScanEvent, ScanRun, TargetConfig, utc_now,
)
from transport.management_adapter import SandboxManagementAdapter


_METHODS = {"GET", "POST"}
MAX_RESPONSE_BYTES = 256 * 1024
SENSITIVE_FIELDS = ("token", "authorization", "password", "cookie", "secret", "credential")


class ScopeViolation(RuntimeError):
    pass


class ScanStopped(RuntimeError):
    pass


class DemoCredentialResolver:
    """Server-side allowlist of synthetic account references; no secrets are persisted."""
    _REFERENCES = {"server:agency-a", "server:agency-b"}

    def has_reference(self, reference: str) -> bool:
        return reference in self._REFERENCES


def _origin(value: str) -> tuple[str, str, int]:
    parsed = urlsplit(str(value))
    if (parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ScopeViolation("Only plain HTTP local sandbox origins are supported by this demo")
    try:
        port = parsed.port or 80
    except ValueError:
        raise ScopeViolation("Invalid sandbox port") from None
    return parsed.scheme, parsed.hostname.lower(), port


def _safe_json(response: httpx.Response) -> Any:
    raw = response.content[:MAX_RESPONSE_BYTES]
    if len(response.content) > MAX_RESPONSE_BYTES:
        return {"_truncated": True}
    try:
        value = response.json()
    except ValueError:
        return {"text": response.text[:500]}
    if isinstance(value, dict):
        return {key: item for key, item in value.items()
                if not any(term in key.lower() for term in SENSITIVE_FIELDS)}
    return value


class RouteWatchDomainService:
    """Synchronous bounded runner used by FastAPI's background-task interface."""

    def __init__(self, store: V1Store, inventory: FixtureInventoryService):
        self.store = store
        self.inventory = inventory

    def _validate_target(self, target: TargetConfig) -> tuple[str, str, int]:
        if target.id != "local-sandbox":
            raise ScopeViolation("This runtime only accepts target_id=local-sandbox")
        origin = _origin(str(target.base_url))
        allowed_hosts = {
            item.strip().lower()
            for item in os.getenv("ROUTEWATCH_ALLOWED_SANDBOX_HOSTS", "sandbox,localhost,127.0.0.1").split(",")
            if item.strip()
        }
        if origin[1] not in allowed_hosts or origin[2] != 8000:
            raise ScopeViolation("Target is outside the configured local sandbox allowlist")
        allowed = {_origin(str(item)) for item in target.allowed_origins}
        if allowed != {origin}:
            raise ScopeViolation("Allowed origins must exactly match the configured sandbox origin")
        if target.max_requests > 30:
            raise ScopeViolation("The local demo request budget cannot exceed 30")
        if target.timeout_seconds > 10:
            raise ScopeViolation("The local demo timeout cannot exceed 10 seconds")
        if len(target.accounts) != 2 or {item.agency_id for item in target.accounts} != {"agency-a", "agency-b"}:
            raise ScopeViolation("Exactly the two supplied synthetic agency accounts are required")
        return origin

    def _event(self, scan_id: UUID, stage: str, message: str, progress: float | None = None) -> None:
        self.store.scan_events.save(ScanEvent(
            scan_id=scan_id, stage=stage, message=message, progress=progress,
        ))

    def _shape(self, body: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(body, dict):
            return {}
        return {
            key: "[redacted]" if any(term in key.lower() for term in SENSITIVE_FIELDS) else type(value).__name__
            for key, value in body.items()
        }

    def _is_cancelled(self, scan_id: UUID) -> bool:
        current = self.store.scans.get(scan_id)
        return current is None or current.state in {"cancelled", "cancelling"}

    def _request(
        self,
        *,
        client: httpx.Client,
        target: TargetConfig,
        scan_id: UUID,
        method: str,
        path: str,
        account: Any = None,
        body: dict[str, Any] | None = None,
        purpose: str,
        budget: dict[str, Any],
    ) -> tuple[int, Any]:
        normalized_method = method.upper()
        if normalized_method not in _METHODS:
            raise ScopeViolation("Only bounded GET and POST sandbox operations are permitted")
        if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
            raise ScopeViolation("Request path must be origin-relative")
        parsed_path = urlsplit(path)
        decoded_path = unquote(parsed_path.path)
        if parsed_path.scheme or parsed_path.netloc or parsed_path.fragment or "\\" in decoded_path:
            raise ScopeViolation("Unsafe path rejected")
        if any(segment in {".", ".."} for segment in decoded_path.split("/")):
            raise ScopeViolation("Path traversal rejected")
        if os.getenv("ROUTEWATCH_KILL_SWITCH", "").strip().lower() in {"1", "true", "yes", "on"}:
            raise ScanStopped("Global scanner kill switch is enabled")
        if self._is_cancelled(scan_id):
            raise ScanStopped("Scan cancelled")
        if budget["used"] >= budget["max"]:
            raise ScanStopped("Per-scan request budget exhausted")
        now = time.monotonic()
        budget["recent"] = [stamp for stamp in budget["recent"] if now - stamp < 60]
        if len(budget["recent"]) >= budget["rate"]:
            raise ScanStopped("Per-minute request limit reached")
        url = str(target.base_url).rstrip("/") + path
        parsed_url = urlsplit(url)
        try:
            request_origin = (parsed_url.scheme, parsed_url.hostname.lower(), parsed_url.port or 80)
        except (AttributeError, ValueError):
            raise ScopeViolation("Invalid request origin") from None
        if request_origin != _origin(str(target.base_url)):
            raise ScopeViolation("Request escaped the configured origin")
        headers: dict[str, str] = {"Accept": "application/json"}
        if account is not None:
            headers.update({"X-Agency": account.agency_id, "X-User": account.user_id})
        budget["used"] += 1
        budget["recent"].append(now)
        status: int | None = None
        outcome = "transport_error"
        data: Any = None
        try:
            with client.stream(normalized_method, url, headers=headers, json=body) as response:
                status = response.status_code
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > MAX_RESPONSE_BYTES:
                        outcome = "response_size_limit"
                        data = {"_truncated": True}
                        break
                    chunks.append(chunk)
                if outcome != "response_size_limit":
                    raw = b"".join(chunks)
                    if not raw:
                        data = {}
                    else:
                        try:
                            data = __import__("json").loads(raw)
                        except (ValueError, UnicodeDecodeError):
                            data = {"text": raw[:500].decode("utf-8", errors="replace")}
                    outcome = "redirect_rejected" if 300 <= status < 400 else "completed"
        except httpx.RequestError:
            outcome = "transport_error"
            raise
        finally:
            from discovery.inventory import normalize_path
            try:
                _, normalized_path = normalize_path(normalized_method, path)
            except ValueError:
                normalized_path = decoded_path or "/"
            self.store.audit.save(RequestAuditEvent(
                scan_id=scan_id,
                method=normalized_method,
                normalized_path=normalized_path,
                purpose=purpose,
                outcome=outcome,
                status=status,
                redacted_body_shape=self._shape(body),
            ))
        if outcome == "redirect_rejected":
            return status or 0, {"_redirect_rejected": True}
        if outcome == "response_size_limit":
            return status or 0, data
        return status or 0, data

    def _new_client(self, target: TargetConfig) -> httpx.Client:
        return httpx.Client(
            timeout=httpx.Timeout(target.timeout_seconds),
            follow_redirects=False,
            limits=httpx.Limits(max_connections=2, max_keepalive_connections=1),
            trust_env=False,
        )

    def _must_object(self, status: int, data: Any, description: str) -> dict[str, Any]:
        if status < 200 or status >= 300 or not isinstance(data, dict) or data.get("_truncated"):
            raise RuntimeError(description)
        return data

    def start_scan(self, target: TargetConfig, credentials: DemoCredentialResolver) -> ScanRun:
        self._validate_target(target)
        if not all(credentials.has_reference(account.credential_ref) for account in target.accounts):
            raise ScopeViolation("Unknown server-side credential reference")
        return ScanRun(target_id=target.id, state="queued", started_at=utc_now())

    def run_scan(self, scan_id: UUID, target: TargetConfig, credentials: DemoCredentialResolver) -> None:
        current = self.store.scans.get(scan_id)
        if current is None or current.state == "cancelled":
            return
        self._validate_target(target)
        if not all(credentials.has_reference(account.credential_ref) for account in target.accounts):
            raise ScopeViolation("Unknown server-side credential reference")
        running = current.model_copy(update={"state": "running", "started_at": utc_now(), "completed_at": None})
        self.store.scans.save(running)
        self._event(scan_id, "start", "Starting bounded synthetic travel API scan.", 0.02)
        budget = {"used": 0, "max": min(target.max_requests, 30), "rate": min(target.rate_per_minute, 30), "recent": []}
        findings: list[Finding] = []
        reachability: dict[tuple[str, str], str] = {}
        a, b = target.accounts
        try:
            with self._new_client(target) as client:
                status, recording = self._request(
                    client=client, target=target, scan_id=scan_id, method="GET",
                    path="/ui/traffic-recording", purpose="discover_synthetic_journey",
                    budget=budget,
                )
                recording = self._must_object(status, recording, "Synthetic journey recording unavailable")
                if recording.get("synthetic") is not True:
                    raise RuntimeError("Discovery input provenance is not explicitly synthetic")
                requests = recording.get("requests", [])
                quote_path = next(item["path"] for item in requests if item.get("method") == "POST" and item.get("path", "").endswith("/quotes"))
                booking_path = next(item["path"] for item in requests if item.get("method") == "POST" and item.get("path", "").endswith("/bookings"))
                read_path = next(item["path"] for item in requests if item.get("method") == "GET" and "/bookings/" in item.get("path", ""))
                route = next((item.get("body", {}).get("route") for item in requests
                              if isinstance(item.get("body"), dict) and item["body"].get("route")), "DEL-BOM")
                self._event(scan_id, "discovery", f"Loaded {len(requests)} synthetic journey observations.", 0.12)

                def baseline(account: Any, suffix: str):
                    q_status, quote = self._request(
                        client=client, target=target, scan_id=scan_id, method="POST",
                        path=quote_path, account=account, body={"route": route},
                        purpose=f"legitimate_quote_{suffix}", budget=budget,
                    )
                    quote = self._must_object(q_status, quote, "Legitimate quote could not be created")
                    b_status, booking = self._request(
                        client=client, target=target, scan_id=scan_id, method="POST",
                        path=booking_path, account=account,
                        body={"quote_id": quote["quote_id"], "traveler": f"Synthetic {suffix}", "fare": quote["fare"]},
                        purpose=f"legitimate_booking_{suffix}", budget=budget,
                    )
                    booking = self._must_object(b_status, booking, "Legitimate booking could not be created")
                    return quote, booking

                quote_a, booking_a = baseline(a, "agency-a")
                quote_b, booking_b = baseline(b, "agency-b")
                own_status, own_body = self._request(
                    client=client, target=target, scan_id=scan_id, method="GET",
                    path=read_path.replace("{id}", booking_a["booking_id"]), account=a,
                    purpose="legitimate_ownership_control", budget=budget,
                )
                own_control = self._must_object(own_status, own_body, "Agency A could not read its own booking")
                foreign_path = read_path.replace("{id}", booking_b["booking_id"])
                foreign_status, foreign_body = self._request(
                    client=client, target=target, scan_id=scan_id, method="GET",
                    path=foreign_path, account=a, purpose="cross_agency_ownership_test", budget=budget,
                )
                if (foreign_status == 200 and isinstance(foreign_body, dict)
                        and foreign_body.get("booking_id") == booking_b["booking_id"]
                        and foreign_body.get("agency_id") == b.agency_id):
                    findings.append(Finding(
                        scan_id=scan_id, rule_id="cross_agency_access", severity="high",
                        business_impact="One travel agency can read another agency's booking and traveller information.",
                        minimal_proof=MinimalProof(
                            request={"method": "GET", "path": foreign_path, "account": a.agency_id},
                            response={"status": foreign_status, "booking_id": foreign_body.get("booking_id"),
                                      "agency_id": foreign_body.get("agency_id")},
                            legitimate_control={"status": own_status, "booking_id": own_control.get("booking_id"),
                                                "agency_id": own_control.get("agency_id")},
                        ),
                    ))
                self._event(scan_id, "authorization", "Completed cross-agency access test with an own-booking control.", 0.48)

                tampered_fare = max(1.0, float(quote_a["fare"]) - 1.0)
                tamper_status, tamper_response = self._request(
                    client=client, target=target, scan_id=scan_id, method="POST",
                    path=booking_path, account=a,
                    body={"quote_id": quote_a["quote_id"], "traveler": "Synthetic fare test", "fare": tampered_fare},
                    purpose="fare_tampering_test", budget=budget,
                )
                persisted_fare: Any = None
                fare_booking_id = tamper_response.get("booking_id") if isinstance(tamper_response, dict) else None
                if tamper_status < 300 and fare_booking_id:
                    verify_status, verify_body = self._request(
                        client=client, target=target, scan_id=scan_id, method="GET",
                        path=read_path.replace("{id}", fare_booking_id), account=a,
                        purpose="verify_persisted_fare", budget=budget,
                    )
                    if verify_status == 200 and isinstance(verify_body, dict):
                        persisted_fare = verify_body.get("fare")
                if (tamper_status < 300 and fare_booking_id and persisted_fare == tampered_fare
                        and persisted_fare != quote_a["fare"]):
                    findings.append(Finding(
                        scan_id=scan_id, rule_id="fare_tampering", severity="high",
                        business_impact="A synthetic booking can persist a client-modified fare instead of the server quote.",
                        minimal_proof=MinimalProof(
                            request={"method": "POST", "path": booking_path,
                                     "body": {"quote_id": "[synthetic quote]", "fare": tampered_fare}},
                            response={"status": tamper_status, "booking_id": fare_booking_id,
                                      "persisted_fare": persisted_fare, "quoted_fare": quote_a["fare"]},
                            legitimate_control={"status": 200, "booking_id": booking_a["booking_id"],
                                                "fare": booking_a.get("fare"), "quote_fare": quote_a["fare"]},
                        ),
                    ))
                self._event(scan_id, "business_logic", "Verified fare outcome against a persisted booking read.", 0.7)

                archived_path = "/api/v1/bookings/{id}"
                archived_status, _archived_body = self._request(
                    client=client, target=target, scan_id=scan_id, method="GET",
                    path=archived_path.replace("{id}", booking_a["booking_id"]), account=a,
                    purpose="scoped_archived_route_reachability", budget=budget,
                )
                reachability[("GET", archived_path)] = (
                    "reachable" if 100 <= archived_status < 500 else "unreachable"
                )

            if hasattr(self.inventory, "record_reachability"):
                for (method, path), value in reachability.items():
                    self.inventory.record_reachability(method, path, value)
            endpoints = self.inventory.list_endpoints(target.id)
            previous = self.store.inventory_snapshots.list(parent_id=target.id, limit=1000)
            snapshot = InventorySnapshot(target_id=target.id, endpoints=endpoints, synthetic=True)
            changes = compare_inventory(previous[-1].endpoints, endpoints) if previous else []
            self.store.inventory_snapshots.save(snapshot)
            for change in changes:
                self.store.change_events.save(ChangeEvent(
                    scan_id=scan_id, target_id=target.id, method=change.method,
                    normalized_path=change.path, change=change.change,
                    risk_score=change.risk_score, reasons=list(change.reasons),
                    recommended_test_families=list(recommended_test_families(change)),
                ))
            for finding in findings:
                self.store.findings.save(finding)
            completed = self.store.scans.get(scan_id)
            if completed is None or completed.state == "cancelled":
                return
            self.store.scans.save(completed.model_copy(update={
                "state": "completed", "completed_at": utc_now(), "request_count": budget["used"],
            }))
            self._event(scan_id, "complete", f"Scan completed with {len(findings)} verified finding(s).", 1.0)
        except (ScopeViolation, ScanStopped) as error:
            latest = self.store.scans.get(scan_id)
            if latest and latest.state not in {"cancelled", "cancelling"}:
                self.store.scans.save(latest.model_copy(update={
                    "state": "cancelled", "completed_at": utc_now(),
                    "cancel_reason": str(error)[:180], "request_count": budget["used"],
                }))
                self._event(scan_id, "cancelled", "Scan stopped by a safety or operator control.", 1.0)
        except Exception:
            latest = self.store.scans.get(scan_id)
            if latest and latest.state not in {"cancelled", "cancelling"}:
                self.store.scans.save(latest.model_copy(update={
                    "state": "failed", "completed_at": utc_now(), "request_count": budget["used"],
                    "cancel_reason": "Scan failed; inspect request audit for sanitized outcomes.",
                }))
                self._event(scan_id, "failed", "Scan failed; no unresolved result was marked as passed.", 1.0)

    def cancel_scan(self, scan: ScanRun) -> ScanRun:
        if scan.state in {"completed", "failed", "cancelled"}:
            return scan
        cancelled = scan.model_copy(update={"state": "cancelled", "completed_at": utc_now(),
                                            "cancel_reason": "Cancelled by operator"})
        self.store.scans.save(cancelled)
        self._event(scan.id, "cancelled", "Cancellation requested by operator.", 1.0)
        return cancelled

    def propose(self, finding: Finding) -> RemediationProposal:
        action = {
            "cross_agency_access": ActionKey.enforce_booking_ownership,
            "fare_tampering": ActionKey.validate_quote_fare,
        }.get(finding.rule_id)
        if action is None:
            raise ValueError("No predefined safe remediation exists for this finding class")
        return RemediationProposal(
            finding_id=finding.id, action_key=action,
            description=f"Enable the predefined sandbox control for {finding.rule_id}.",
            state="proposed",
        )

    def approve(self, proposal: RemediationProposal, reviewer_id: str, decision: str) -> Approval:
        if proposal.state not in {"proposed", "awaiting_approval"}:
            raise ValueError("Proposal is not eligible for review")
        if decision not in {"approved", "rejected"} or not reviewer_id.strip():
            raise ValueError("A valid reviewer decision is required")
        updated = proposal.model_copy(update={"state": "approved" if decision == "approved" else "rejected"})
        self.store.proposals.save(updated)
        return Approval(proposal_id=proposal.id, approved_by=reviewer_id, decision=decision,
                        reason="Reviewed in the authenticated local demonstration console")

    def execute(self, proposal: RemediationProposal, approval: Approval, attempt_id: UUID,
                adapter: SandboxManagementAdapter) -> ExecutionResult:
        if approval.proposal_id != proposal.id or approval.decision != "approved":
            raise ValueError("Matching persisted approval is required")
        if proposal.state not in {"approved", "proposed"}:
            raise ValueError("Proposal is not eligible for execution")
        result = adapter.execute(proposal, approval, attempt_id)
        if result.state == "applied":
            self.store.proposals.save(proposal.model_copy(update={"state": "executed"}))
            finding = self.store.findings.get(proposal.finding_id)
            if finding:
                self.store.findings.save(finding.model_copy(update={"state": "remediating"}))
        elif result.state == "failed":
            finding = self.store.findings.get(proposal.finding_id)
            if finding:
                self.store.findings.save(finding.model_copy(update={"state": "remediation_failed"}))
        return result

    def retest(self, finding: Finding) -> RetestResult:
        config = self.store.get_scan_config(finding.scan_id)
        if config is None:
            raise ValueError("Original scan configuration is unavailable for independent retest")
        self._validate_target(config)
        scan = ScanRun(target_id=config.id, state="running")
        self.store.scans.save(scan)
        self.store.save_scan_config(scan.id, config)
        self._event(scan.id, "retest", f"Independently replaying {finding.rule_id} with synthetic controls.", 0.05)
        budget = {"used": 0, "max": min(config.max_requests, 30), "rate": min(config.rate_per_minute, 30), "recent": []}
        exploit = CheckOutcome.inconclusive
        legitimate = CheckOutcome.inconclusive
        detail = "Retest did not complete."
        a, b = config.accounts
        try:
            with self._new_client(config) as client:
                if finding.rule_id == "cross_agency_access":
                    recording_status, recording = self._request(
                        client=client, target=config, scan_id=scan.id, method="GET",
                        path="/ui/traffic-recording", purpose="retest_discovery", budget=budget,
                    )
                    recording = self._must_object(recording_status, recording, "Retest discovery input unavailable")
                    reqs = recording.get("requests", [])
                    quote_path = next(item["path"] for item in reqs if item.get("method") == "POST" and item.get("path", "").endswith("/quotes"))
                    booking_path = next(item["path"] for item in reqs if item.get("method") == "POST" and item.get("path", "").endswith("/bookings"))
                    read_path = next(item["path"] for item in reqs if item.get("method") == "GET" and "/bookings/" in item.get("path", ""))
                    def book(account, label):
                        qs, q = self._request(client=client, target=config, scan_id=scan.id, method="POST",
                            path=quote_path, account=account, body={"route": "DEL-BOM"},
                            purpose=f"retest_quote_{label}", budget=budget)
                        q = self._must_object(qs, q, "Retest quote failed")
                        bs, bk = self._request(client=client, target=config, scan_id=scan.id, method="POST",
                            path=booking_path, account=account,
                            body={"quote_id": q["quote_id"], "traveler": f"Retest {label}", "fare": q["fare"]},
                            purpose=f"retest_booking_{label}", budget=budget)
                        return q, self._must_object(bs, bk, "Retest booking failed")
                    _qa, ba = book(a, "agency-a")
                    _qb, bb = book(b, "agency-b")
                    own_status, own = self._request(client=client, target=config, scan_id=scan.id,
                        method="GET", path=read_path.replace("{id}", ba["booking_id"]), account=a,
                        purpose="retest_legitimate_ownership", budget=budget)
                    foreign_status, foreign = self._request(client=client, target=config, scan_id=scan.id,
                        method="GET", path=read_path.replace("{id}", bb["booking_id"]), account=a,
                        purpose="retest_cross_agency_exploit", budget=budget)
                    own_ok = own_status == 200 and isinstance(own, dict) and own.get("booking_id") == ba["booking_id"] and own.get("agency_id") == a.agency_id
                    blocked = foreign_status in {401, 403, 404}
                    leaked = foreign_status == 200 and isinstance(foreign, dict) and foreign.get("booking_id") == bb["booking_id"] and foreign.get("agency_id") == b.agency_id
                    legitimate = CheckOutcome.passed if own_ok else CheckOutcome.failed
                    exploit = CheckOutcome.passed if blocked else CheckOutcome.failed if leaked else CheckOutcome.inconclusive
                    detail = "Cross-agency exploit blocked and own-agency read verified." if exploit == legitimate == CheckOutcome.passed else "Cross-agency or legitimate control did not meet its expected outcome."
                elif finding.rule_id == "fare_tampering":
                    quote_status, quote = self._request(client=client, target=config, scan_id=scan.id,
                        method="POST", path="/api/v2/quotes", account=a, body={"route": "DEL-BOM"},
                        purpose="retest_quote", budget=budget)
                    quote = self._must_object(quote_status, quote, "Retest quote failed")
                    quoted = float(quote["fare"])
                    tamper = max(1.0, quoted - 1.0)
                    tamper_status, tampered = self._request(client=client, target=config, scan_id=scan.id,
                        method="POST", path="/api/v2/bookings", account=a,
                        body={"quote_id": quote["quote_id"], "traveler": "Retest tamper", "fare": tamper},
                        purpose="retest_fare_exploit", budget=budget)
                    if tamper_status < 300 and isinstance(tampered, dict) and tampered.get("booking_id"):
                        verify_status, persisted = self._request(client=client, target=config, scan_id=scan.id,
                            method="GET", path=f"/api/v2/bookings/{tampered['booking_id']}", account=a,
                            purpose="retest_persisted_fare", budget=budget)
                        persisted_fare = persisted.get("fare") if verify_status == 200 and isinstance(persisted, dict) else None
                        exploit = CheckOutcome.passed if persisted_fare == quoted else CheckOutcome.failed if persisted_fare == tamper else CheckOutcome.inconclusive
                    elif tamper_status in {400, 403, 404, 409, 422}:
                        exploit = CheckOutcome.passed
                    else:
                        exploit = CheckOutcome.inconclusive
                    legit_quote_status, legit_quote = self._request(client=client, target=config, scan_id=scan.id,
                        method="POST", path="/api/v2/quotes", account=a, body={"route": "DEL-BOM"},
                        purpose="retest_legitimate_quote", budget=budget)
                    legit_quote = self._must_object(legit_quote_status, legit_quote, "Legitimate quote failed")
                    legit_status, legit_booking = self._request(client=client, target=config, scan_id=scan.id,
                        method="POST", path="/api/v2/bookings", account=a,
                        body={"quote_id": legit_quote["quote_id"], "traveler": "Retest legitimate", "fare": legit_quote["fare"]},
                        purpose="retest_legitimate_booking", budget=budget)
                    legitimate = CheckOutcome.passed if legit_status in {200, 201} and isinstance(legit_booking, dict) and legit_booking.get("fare") == legit_quote["fare"] else CheckOutcome.failed
                    detail = "Tampered amount is no longer persisted and a normal booking succeeds." if exploit == legitimate == CheckOutcome.passed else "Fare exploit or legitimate booking control did not meet its expected outcome."
                else:
                    exploit = CheckOutcome.inconclusive
                    legitimate = CheckOutcome.inconclusive
                    detail = "No independent replay routine exists for this finding class."
        except ScanStopped:
            exploit, legitimate, detail = CheckOutcome.cancelled, CheckOutcome.cancelled, "Retest was cancelled or stopped by a safety limit."
        except Exception:
            exploit, legitimate, detail = CheckOutcome.inconclusive, CheckOutcome.inconclusive, "Retest could not establish a reliable outcome; no resolution was claimed."
        outcome = ("resolved" if exploit == CheckOutcome.passed and legitimate == CheckOutcome.passed
                   else "cancelled" if CheckOutcome.cancelled in {exploit, legitimate}
                   else "failed" if CheckOutcome.failed in {exploit, legitimate}
                   else "inconclusive")
        final_scan = self.store.scans.get(scan.id)
        if final_scan:
            state = "cancelled" if outcome == "cancelled" else "completed" if outcome in {"resolved", "failed", "inconclusive"} else "failed"
            self.store.scans.save(final_scan.model_copy(update={"state": state, "completed_at": utc_now(),
                                                                 "request_count": budget["used"]}))
        self._event(scan.id, "retest_complete", detail, 1.0)
        updated_finding = finding.model_copy(update={"state": "resolved" if outcome == "resolved"
            else "retest_failed" if outcome == "failed" else "inconclusive" if outcome == "inconclusive" else "cancelled"})
        self.store.findings.save(updated_finding)
        return RetestResult(
            finding_id=finding.id, scan_id=scan.id, exploit_outcome=exploit,
            legitimate_flow_outcome=legitimate, outcome=outcome, detail=detail,
        )
