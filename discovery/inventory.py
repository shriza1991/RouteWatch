"""Evidence-aware endpoint discovery and classification.

This module deliberately separates observations from conclusions. Missing or
incomplete history is never converted into a zero-traffic claim.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import unquote, urlsplit
from uuid import NAMESPACE_URL, uuid5

from shared.v1 import Endpoint, EvidenceKind, InventoryEvidence

_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
_COLLECTIONS = {
    "bookings", "quotes", "payments", "refunds", "cancellations",
    "travellers", "travelers", "suppliers", "invoices", "users",
    "agencies", "coupons", "holds",
}
_ROUTE_RE = re.compile(r"""(?P<quote>['"])(?P<path>/api/[A-Za-z0-9_./:{}-]+)(?P=quote)""")
_TEMPLATE_RE = re.compile(r":([A-Za-z_][A-Za-z0-9_]*)")


def _parse_time(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("timestamp must be an ISO-8601 string or datetime")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def normalize_path(method: str, path: str) -> tuple[str, str]:
    """Return a normalized HTTP method and route, rejecting unsafe paths."""
    normalized_method = str(method).upper()
    if normalized_method not in _METHODS:
        raise ValueError("unsupported HTTP method")
    if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
        raise ValueError("route must be an origin-relative absolute path")
    parsed = urlsplit(path)
    if parsed.scheme or parsed.netloc or parsed.fragment:
        raise ValueError("absolute URLs and fragments are not valid route observations")
    decoded = unquote(parsed.path)
    if "\\" in decoded or "\x00" in decoded:
        raise ValueError("unsafe route encoding")
    parts = [part for part in decoded.split("/") if part]
    if any(part in {".", ".."} for part in parts):
        raise ValueError("path traversal is not valid route evidence")
    result: list[str] = []
    for index, part in enumerate(parts):
        previous = parts[index - 1].lower() if index else ""
        if part.startswith(":"):
            result.append("{id}")
        elif part.startswith("{") and part.endswith("}"):
            result.append("{id}")
        elif previous in _COLLECTIONS:
            result.append("{id}")
        else:
            result.append(part)
    route = "/" + "/".join(result)
    if decoded.endswith("/") and route != "/":
        route += "/"
    return normalized_method, route


def extract_javascript_routes(source: str) -> set[str]:
    """Extract API-like route literals from supplied JavaScript text.

    This is evidence collection, not proof that a route is reachable.
    """
    if not isinstance(source, str):
        raise TypeError("JavaScript source must be text")
    routes: set[str] = set()
    for match in _ROUTE_RE.finditer(source):
        value = _TEMPLATE_RE.sub("{id}", match.group("path"))
        try:
            _, normalized = normalize_path("GET", value)
        except ValueError:
            continue
        routes.add(normalized)
    return routes


def parse_har(data: dict[str, Any], *, account_context_id: str = "unknown") -> list[dict[str, Any]]:
    """Convert a HAR 1.2 log into redacted endpoint observations."""
    if not isinstance(data, dict) or not isinstance(data.get("log"), dict):
        raise ValueError("invalid HAR document")
    entries = data["log"].get("entries")
    if not isinstance(entries, list):
        raise ValueError("HAR log.entries must be a list")
    observations: list[dict[str, Any]] = []
    for entry in entries:
        request = entry.get("request") if isinstance(entry, dict) else None
        if not isinstance(request, dict):
            continue
        try:
            method, path = normalize_path(request.get("method", ""), urlsplit(request.get("url", "")).path)
        except ValueError:
            continue
        timestamp = entry.get("startedDateTime")
        if not timestamp:
            continue
        observations.append({
            "method": method,
            "path": path,
            "timestamp": _parse_time(timestamp).isoformat(),
            "account_context_id": account_context_id,
            "source": "har",
            "status": entry.get("response", {}).get("status"),
        })
    return observations


def _add_evidence(
    grouped: dict[tuple[str, str], list[InventoryEvidence]],
    key: tuple[str, str],
    kind: EvidenceKind,
    observed_at: datetime,
    statement: str,
    *,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    coverage: str | None = None,
    synthetic: bool = True,
) -> None:
    endpoint_id = uuid5(NAMESPACE_URL, f"routewatch:{key[0]}:{key[1]}")
    grouped.setdefault(key, []).append(InventoryEvidence(
        endpoint_id=endpoint_id,
        kind=kind,
        observed_at=observed_at,
        statement=statement,
        window_start=window_start,
        window_end=window_end,
        coverage=coverage,
        synthetic=synthetic,
    ))


def build_inventory(
    recording: dict[str, Any],
    reference: dict[str, Any],
    history: dict[str, Any],
    archived: dict[str, Any],
    *,
    reachability: dict[tuple[str, str], str] | None = None,
) -> list[Endpoint]:
    """Build endpoint records from independent sources and explicit reachability.

    ACTIVE means observed legitimate traffic. SHADOW means observed in traffic
    but absent from the reference inventory. ZOMBIE requires all three:
    complete historical coverage with an explicit zero, a successful narrow
    reachability result, and no current journey observation.
    """
    for name, document in (("recording", recording), ("reference", reference),
                           ("history", history), ("archived", archived)):
        if not isinstance(document, dict) or document.get("schema_version") != "1.0":
            raise ValueError(f"invalid {name} schema version")
        if document.get("synthetic") is not True:
            raise ValueError(f"{name} provenance must be explicit")
        if not document.get("provenance"):
            raise ValueError(f"{name} provenance is required")

    window = recording.get("observation_window") or {}
    recording_start = _parse_time(window["start"]) if window.get("start") else None
    recording_end = _parse_time(window["end"]) if window.get("end") else None
    history_window = history.get("observation_window") or {}
    history_start = _parse_time(history_window["start"])
    history_end = _parse_time(history_window["end"])
    if history_start >= history_end:
        raise ValueError("historical observation window is invalid")
    if recording_start and recording_end and recording_start > recording_end:
        raise ValueError("journey observation window is invalid")

    grouped: dict[tuple[str, str], list[InventoryEvidence]] = {}
    traffic_keys: set[tuple[str, str]] = set()
    reference_keys: set[tuple[str, str]] = set()
    history_by_key: dict[tuple[str, str], dict[str, Any]] = {}

    requests = recording.get("requests")
    if not isinstance(requests, list):
        raise ValueError("journey recording requests must be a list")
    for item in requests:
        method, path = normalize_path(item.get("method", ""), item.get("path", ""))
        observed_at = _parse_time(item["timestamp"])
        if recording_start and not recording_start <= observed_at <= recording_end:
            raise ValueError("journey observation falls outside its declared window")
        key = (method, path)
        traffic_keys.add(key)
        _add_evidence(
            grouped, key, EvidenceKind.traffic, observed_at,
            f"Observed legitimate request from {item.get('source', 'journey recording')} "
            f"for account context {item.get('account_context_id', 'unknown')}; "
            f"HTTP {item.get('status', 'unknown')}.",
            synthetic=True,
        )

    items = reference.get("endpoints")
    if not isinstance(items, list):
        raise ValueError("reference inventory endpoints must be a list")
    reference_time = datetime.now(timezone.utc)
    for item in items:
        method, path = normalize_path(item.get("method", ""), item.get("path", ""))
        key = (method, path)
        reference_keys.add(key)
        _add_evidence(grouped, key, EvidenceKind.reference, reference_time,
                      "Present in the supplied reference inventory snapshot.", synthetic=True)

    history_items = history.get("endpoints")
    if not isinstance(history_items, list):
        raise ValueError("historical endpoints must be a list")
    for item in history_items:
        method, path = normalize_path(item.get("method", ""), item.get("path", ""))
        coverage = item.get("coverage")
        count = item.get("legitimate_requests_in_window")
        if coverage == "complete":
            if not isinstance(count, int) or count < 0:
                raise ValueError("complete history requires a non-negative count")
        elif coverage == "incomplete":
            if count is not None:
                raise ValueError("incomplete history cannot assert a traffic count")
        else:
            raise ValueError("historical coverage must be complete or incomplete")
        key = (method, path)
        history_by_key[key] = item
        last = item.get("last_legitimate_at")
        statement = (
            f"Historical window {history_start.isoformat()} to {history_end.isoformat()} "
            f"has {count} legitimate requests (coverage: {coverage})."
            if coverage == "complete"
            else f"Historical window {history_start.isoformat()} to {history_end.isoformat()} "
                 "has incomplete coverage; traffic count is unknown."
        )
        _add_evidence(grouped, key, EvidenceKind.history, history_end, statement,
                      window_start=history_start, window_end=history_end,
                      coverage=coverage, synthetic=True)
        if last:
            _parse_time(last)

    archived_routes = archived.get("routes")
    if not isinstance(archived_routes, list):
        raise ValueError("archived routes must be a list")
    for item in archived_routes:
        method, path = normalize_path(item.get("method", ""), item.get("path", ""))
        key = (method, path)
        _add_evidence(grouped, key, EvidenceKind.reference, reference_time,
                      "Listed as an archived-route candidate; this is not traffic evidence.",
                      synthetic=True)

    observed_reachability = reachability or {}
    endpoints: list[Endpoint] = []
    for method, path in sorted(grouped):
        key = (method, path)
        evidence = grouped[key]
        labels: set[str] = set()
        has_traffic = key in traffic_keys
        if has_traffic:
            labels.add("active")
            if key not in reference_keys:
                labels.add("shadow")
        reach = observed_reachability.get(key, "unprobed")
        if reach not in {"reachable", "blocked", "unreachable", "unprobed"}:
            reach = "unprobed"
        historical = history_by_key.get(key)
        if (not has_traffic and historical and historical.get("coverage") == "complete"
                and historical.get("legitimate_requests_in_window") == 0
                and reach == "reachable"):
            labels.add("zombie")
        if not labels:
            labels.add("unknown")
        endpoint_id = uuid5(NAMESPACE_URL, f"routewatch:{method}:{path}")
        endpoints.append(Endpoint(
            id=endpoint_id,
            method=method,
            normalized_path=path,
            labels=labels,
            reachability=reach,
            evidence=evidence,
        ))
    return endpoints
