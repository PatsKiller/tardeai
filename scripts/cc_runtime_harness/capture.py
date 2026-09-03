"""HTTP capture helpers with identity + freshness metadata."""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .safety import assert_method_allowed, redact_secrets


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def capture_get(
    base_url: str,
    path: str,
    *,
    expected_build_sha: str | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    decision = assert_method_allowed("GET", base_url)
    corr = str(uuid4())
    observed_at = _now_iso()
    record: dict[str, Any] = {
        "endpoint": path,
        "method": "GET",
        "correlation_id": corr,
        "observed_at_utc": observed_at,
        "safety": decision.reason,
        "host_class": decision.host_class,
        "status": None,
        "schema": None,
        "value": None,
        "source_identity": None,
        "account_scope": None,
        "business_date": None,
        "received_at_utc": None,
        "normalized_at_utc": None,
        "freshness": None,
        "quality": None,
        "entitlement": None,
        "fallback": None,
        "build_sha_header": None,
        "error": None,
        "body_sha256": None,
    }
    if not decision.allowed:
        record["error"] = decision.reason
        record["status"] = 0
        return record

    url = base_url.rstrip("/") + path
    req_headers = {"Accept": "application/json", "X-Correlation-Id": corr}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            received = _now_iso()
            record["status"] = resp.status
            record["received_at_utc"] = received
            record["build_sha_header"] = resp.headers.get("X-CC-Harness-Build-Sha") or resp.headers.get(
                "X-CC-Build-Sha"
            )
            record["body_sha256"] = hashlib.sha256(raw).hexdigest()
            ctype = resp.headers.get("Content-Type", "")
            if "json" in ctype or path.endswith(".json") or path.startswith("/api/"):
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except json.JSONDecodeError:
                    record["quality"] = "malformed_json"
                    record["value"] = redact_secrets(raw[:200].decode("utf-8", errors="replace"))
                    return record
                record["schema"] = _infer_schema(payload, path)
                record["value"] = _summarize_value(payload, path)
                record["source_identity"] = _source_identity(payload, path)
                record["account_scope"] = _account_scope(payload)
                record["business_date"] = _business_date(payload)
                record["normalized_at_utc"] = _now_iso()
                record["freshness"] = _freshness_hint(payload)
                record["quality"] = "ok"
                record["entitlement"] = (
                    "harness_fixture" if decision.host_class in {"loopback", "ephemeral"} else "preview_readonly"
                )
                record["fallback"] = False
                if (
                    expected_build_sha
                    and record["build_sha_header"]
                    and record["build_sha_header"] != expected_build_sha
                ):
                    record["quality"] = "wrong_build_sha"
            else:
                record["schema"] = "text/html"
                record["value"] = {
                    "bytes": len(raw),
                    "preview": redact_secrets(raw[:80].decode("utf-8", errors="replace")),
                }
                record["quality"] = "ok"
                record["normalized_at_utc"] = _now_iso()
    except urllib.error.HTTPError as e:
        record["status"] = e.code
        record["error"] = f"http_{e.code}"
        record["received_at_utc"] = _now_iso()
        if e.code == 304:
            record["quality"] = "not_modified"
            record["fallback"] = "etag_304"
        else:
            record["quality"] = "http_error"
    except Exception as e:  # noqa: BLE001
        record["status"] = 0
        record["error"] = type(e).__name__ + ":" + redact_secrets(str(e))[:200]
        record["quality"] = "network_failure"
        record["received_at_utc"] = _now_iso()
    return record


def attempt_live_write(base_url: str, path: str = "/api/v2/overview") -> dict[str, Any]:
    """Negative control: attempt POST and expect refusal."""
    decision = assert_method_allowed("POST", base_url)
    result = {
        "attempted_method": "POST",
        "path": path,
        "safety_allowed": decision.allowed,
        "safety_reason": decision.reason,
        "host_class": decision.host_class,
        "http_status": None,
        "detected": False,
    }
    if not decision.allowed:
        result["detected"] = True
        result["detection"] = "preflight_refused"
        return result
    # If somehow allowed (fixture flag), still hit server which should 403
    url = base_url.rstrip("/") + path
    req = urllib.request.Request(
        url,
        data=b'{"probe":true}',
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            result["http_status"] = resp.status
            result["detected"] = resp.status >= 400
            result["detection"] = "server_accepted_unexpected" if resp.status < 400 else "server_refused"
    except urllib.error.HTTPError as e:
        result["http_status"] = e.code
        result["detected"] = e.code in {403, 405, 401}
        result["detection"] = f"http_{e.code}"
    except Exception as e:  # noqa: BLE001
        result["detected"] = True
        result["detection"] = f"error:{type(e).__name__}"
    return result


def _infer_schema(payload: Any, path: str) -> str:
    if isinstance(payload, dict):
        if payload.get("ok") is True and "data" in payload:
            return "ApiEnvelope@v1"
        if "git_sha" in payload or "build_sha" in payload:
            return "BuildMeta@v1"
        if path.endswith("/overview"):
            return "Overview@inferred"
    return type(payload).__name__


def _summarize_value(payload: Any, path: str) -> Any:
    data = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else payload
    if not isinstance(data, dict):
        return {"type": type(data).__name__}
    keys_of_interest = [
        "portfolio_value",
        "total_cash",
        "position_count",
        "today_change",
        "data_as_of",
        "as_of",
        "pipeline_status",
        "pct_protected",
        "vix",
        "go_count",
        "pending_count",
        "regime_label",
        "status",
        "git_sha",
        "build_sha",
        "current_value",
        "win_rate",
    ]
    out = {k: data.get(k) for k in keys_of_interest if k in data}
    if "journal" in data and isinstance(data["journal"], dict):
        out["journal.realized_pnl"] = data["journal"].get("realized_pnl")
        out["journal.win_rate"] = data["journal"].get("win_rate")
    return out


def _source_identity(payload: Any, path: str) -> str | None:
    data = payload.get("data") if isinstance(payload, dict) else payload
    if isinstance(data, dict):
        for k in ("reprice_source", "source", "data_as_of_account", "provider"):
            if data.get(k):
                return str(data.get(k))
    return path


def _account_scope(payload: Any) -> str | None:
    data = payload.get("data") if isinstance(payload, dict) else payload
    if isinstance(data, dict):
        if data.get("data_as_of_account"):
            return redact_secrets(str(data["data_as_of_account"]))
        if isinstance(data.get("today_by_account"), dict):
            return "multi_account:" + str(len(data["today_by_account"]))
    return None


def _business_date(payload: Any) -> str | None:
    data = payload.get("data") if isinstance(payload, dict) else payload
    if isinstance(data, dict):
        return data.get("data_as_of") or data.get("as_of") or data.get("run_date")
    return None


def _freshness_hint(payload: Any) -> str | None:
    data = payload.get("data") if isinstance(payload, dict) else payload
    if isinstance(data, dict):
        if data.get("pipeline_status"):
            return str(data["pipeline_status"])
        if data.get("stale") is True:
            return "stale"
        if data.get("status"):
            return str(data["status"])
    return None
