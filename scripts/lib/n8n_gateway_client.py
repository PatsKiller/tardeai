"""Signed client for the loopback coordination gateway (2026-10-07, roadmap Phase 1).

Used by the pilot dispatcher and the incident fan-in. Every call mints a fresh claim
(nonce ≥ 8, life ≤ 300 s, scope coordination_read) and signs it with the gateway key from
the environment; the key is never written anywhere. Transport failures and gateway
refusals are returned as typed results, never raised past the caller.

AUTHORITY: READ_ONLY_ADVISORY. No effect is possible through this client: the gateway's
forbidden-route list and transition table decide; this file only speaks the envelope.
"""
from __future__ import annotations

import json
import os
import secrets
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from scripts.lib.n8n_coordination_gateway import sign_claim

DEFAULT_URL = "http://127.0.0.1:18091"
KEY_ENV = "TRADEAI_N8N_GATEWAY_HMAC_KEY"
URL_ENV = "TRADEAI_N8N_GATEWAY_URL"
CLAIM_LIFE_S = 120
CALLER_ID = "tradeai-dispatch"

Transport = Callable[[str, dict], tuple[int, dict]]


class GatewayClient:
    def __init__(self, *, url: str | None = None, key: bytes | None = None, caller_id: str = CALLER_ID,
                 project: str = "trade-ai", transport: Transport | None = None, timeout: float = 5.0):
        self.url = (url or os.environ.get(URL_ENV) or DEFAULT_URL).rstrip("/")
        self.key = key if key is not None else (os.environ.get(KEY_ENV) or "").encode("utf-8")
        self.caller_id = caller_id
        self.project = project
        self.timeout = timeout
        self._transport = transport or self._http

    @property
    def has_key(self) -> bool:
        return len(self.key) >= 32

    def claim(self, now: datetime | None = None) -> tuple[dict, str]:
        now = now or datetime.now(timezone.utc)
        body = {"v": 1, "caller_id": self.caller_id, "project": self.project, "iat": now.timestamp(),
                "exp": now.timestamp() + CLAIM_LIFE_S, "nonce": secrets.token_hex(8), "scope": "coordination_read"}
        return body, sign_claim(body, self.key)

    def call(self, operation: str, *, route: str = "coordination/status", **fields: Any) -> dict:
        if not self.has_key:
            return {"state": "REFUSED", "reason": "missing_gateway_key", "transport": "local"}
        claim, sig = self.claim()
        envelope = {"route": route, "operation": operation, "claim": claim, "signature": sig, **fields}
        try:
            status, body = self._transport(self.url + "/v1/coordination", envelope)
        except Exception as exc:  # transport failure is a typed outcome, not a crash
            return {"state": "UNREACHABLE", "reason": f"transport:{type(exc).__name__}", "transport": "http"}
        body = dict(body) if isinstance(body, Mapping) else {"state": "REFUSED", "reason": "malformed_response"}
        body.setdefault("http_status", status)
        return body

    def accept_event(self, event: Mapping[str, Any]) -> dict:
        return self.call("accept_event", route="coordination/event", event=dict(event))

    def status(self, idempotency_key: str) -> dict:
        return self.call("status", idempotency_key=idempotency_key)

    def transition(self, operation: str, idempotency_key: str, **fields: Any) -> dict:
        return self.call(operation, idempotency_key=idempotency_key, **fields)

    def healthz(self) -> dict:
        try:
            with urllib.request.urlopen(self.url + "/healthz", timeout=self.timeout) as r:  # noqa: S310 loopback
                return json.loads(r.read().decode("utf-8"))
        except Exception as exc:
            return {"ok": False, "reason": f"transport:{type(exc).__name__}"}

    def _http(self, url: str, envelope: dict) -> tuple[int, dict]:
        data = json.dumps(envelope).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:  # noqa: S310 loopback only
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, json.loads(exc.read().decode("utf-8"))
            except Exception:
                return exc.code, {"state": "REFUSED", "reason": f"http_{exc.code}"}


def walk_to_artifact(client: GatewayClient, idempotency_key: str, artifact_ref: Mapping[str, Any]) -> list[dict]:
    """ACCEPTED → CLAIMED → STARTED → ARTIFACT_WRITTEN, idempotently from whatever state the gateway holds."""
    out: list[dict] = []
    current = client.status(idempotency_key)
    out.append({"op": "status", **_brief(current)})
    state = current.get("state")
    order = ["ACCEPTED", "CLAIMED", "STARTED", "ARTIFACT_WRITTEN"]
    if state not in order:
        return out
    steps = {"ACCEPTED": ("claim", {}), "CLAIMED": ("start", {}), "STARTED": ("artifact", {"artifact_ref": dict(artifact_ref)})}
    while state in steps:
        op, extra = steps[state]
        r = client.transition(op, idempotency_key, **extra)
        out.append({"op": op, **_brief(r)})
        if r.get("state") in {"REFUSED", "UNREACHABLE"}:
            break
        state = r.get("state")
    return out


def _brief(r: Mapping[str, Any]) -> dict:
    return {"state": r.get("state"), "reason": r.get("reason"), "durable": r.get("durable")}
