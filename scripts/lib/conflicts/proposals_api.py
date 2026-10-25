"""GET /api/v3/conflicts/proposals and POST /api/v3/conflicts/proposals/{id}/decision.

Same identity mechanism as the conflict decision endpoint (scripts/lib/conflicts/api.py): the operator's tailnet
identity through the serve proxy plus same-origin CSRF; agents and service tokens are refused 403 before any
validation or write. Shapes: docs/ops/CONFLICT_RULE_PROPOSALS.md.
"""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import unquote

from . import proposals as P

PREFIX = "/api/v3/conflicts/proposals"
STATUSES = {"PENDING", "APPROVED", "REJECTED", "ALL"}


def _first(value, default=None):
    if isinstance(value, list):
        return value[0] if value else default
    return default if value is None else value


def handle(path, method, body=None, query=None, *, ctx=None, root=None, config=None, now=None, write_enabled=None):
    base = (path or "").split("?", 1)[0].rstrip("/")
    if base != PREFIX and not base.startswith(PREFIX + "/"):
        return None
    method = (method or "GET").upper()
    config = config or P.load_config()
    if method == "POST":
        from scripts.lib.cio_ask_api import _default_ctx, _operator
        try:
            ctx = ctx or _default_ctx()
            actor = _operator(ctx)
        except Exception:
            return 503, {"error": "AUTH_CONFIG_UNAVAILABLE"}
        if not actor:
            return 403, {"error": "AGENT_CALLER_REFUSED", "reason": "only the operator decides rule proposals"}
        ok, why = ctx.csrf(method, base)
        if not ok:
            return 403, {"error": "CSRF_REFUSED", "reason": why}
    elif method != "GET":
        return 405, {"error": "METHOD_NOT_ALLOWED"}
    root = root or P.default_root()
    q = {k: _first(v) for k, v in (query or {}).items()}
    if base == PREFIX:
        if method != "GET":
            return 405, {"error": "METHOD_NOT_ALLOWED"}
        status = str(q.get("status") or "ALL").upper()
        if status not in STATUSES:
            return 400, {"error": "INVALID_STATUS"}
        try:
            limit = min(max(int(q.get("limit", 50)), 1), 200)
            offset = max(int(q.get("offset", 0)), 0)
        except (TypeError, ValueError):
            return 400, {"error": "INVALID_PAGING"}
        try:
            data = P.collection(root, status=status, limit=limit, offset=offset, config=config)
            data["rulebook"] = {k: v for k, v in P.effective_rulebook(root).items() if k != "overlay"}
        except (OSError, ValueError) as exc:
            return 503, {"error": "PROPOSAL_STORE_UNAVAILABLE", "reason": str(exc)[:160]}
        return 200, data
    tail = base[len(PREFIX) + 1:]
    deciding = tail.endswith("/decision")
    proposal_id = unquote(tail[: -len("/decision")] if deciding else tail)
    if not proposal_id or len(proposal_id) > 64 or not all(c.isalnum() or c == "-" for c in proposal_id):
        return 400, {"error": "INVALID_ID"}
    if method == "GET":
        if deciding:
            return 405, {"error": "METHOD_NOT_ALLOWED"}
        try:
            proposal = P.ProposalStore(root).state()["proposals"].get(proposal_id)
        except (OSError, ValueError) as exc:
            return 503, {"error": "PROPOSAL_STORE_UNAVAILABLE", "reason": str(exc)[:160]}
        return (200, P.proposal_view(proposal)) if proposal else (404, {"error": "NOT_FOUND"})
    if not deciding:
        return 405, {"error": "METHOD_NOT_ALLOWED"}
    body = body if isinstance(body, dict) else {}
    if set(body) - {"decision", "reason", "expected_revision", "edited", "apply_current_case"}:
        return 400, {"error": "UNKNOWN_OR_ACTOR_FIELD"}
    if type(body.get("expected_revision")) is not int:
        return 400, {"error": "EXPECTED_REVISION_REQUIRED"}
    if "apply_current_case" in body and type(body["apply_current_case"]) is not bool:
        return 400, {"error": "APPLY_CURRENT_CASE_INVALID"}
    enabled = config.get("decision_writes_enabled") if write_enabled is None else write_enabled
    if not enabled:
        return 503, {"error": "PROPOSAL_DECISIONS_NOT_ACTIVATED",
                     "reason": "operator activation of the proposal store is pending (config decision_writes_enabled)"}
    try:
        result = P.decide(root, proposal_id, decision=body.get("decision"), reason=body.get("reason"), actor=actor,
                          at=now or datetime.now(timezone.utc), expected_revision=body["expected_revision"],
                          edited=body.get("edited"), apply_current_case=bool(body.get("apply_current_case")))
    except P.DecisionRefused as exc:
        return exc.status, {"error": exc.code, **({"reason": exc.reason} if exc.reason else {})}
    except (OSError, ValueError) as exc:
        return 503, {"error": "PROPOSAL_STORE_UNAVAILABLE", "reason": str(exc)[:160]}
    state = P.ProposalStore(root).state()
    return 200, {"ok": True, "proposal": P.proposal_view(state["proposals"][proposal_id]),
                 "amendment": result["amendment"], "current_case": result["current_case"],
                 "rulebook": {k: v for k, v in P.effective_rulebook(root).items() if k != "overlay"}}
