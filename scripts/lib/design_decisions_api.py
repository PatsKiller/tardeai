"""Thin handlers for Approvals → Designs (/api/v2/design). Agents may read; only the operator decides.

    GET  /api/v2/design/approvals                         PROPOSED versions, DSN PROPOSED, decided recently
    GET  /api/v2/design/asset?page=&version=&path=        a private mockup image (PNG/JPEG data URI)
    POST /api/v2/design/decide  {page, version, fingerprint, decision: APPROVE|REJECT, reason, request_id}

Reads need the operator or an authenticated reader (the same rule as /api/v2/governance). Decisions need the
operator's tailnet identity through the serve proxy and a hard same-origin CSRF check (enforced even in report-only
auth mode). No submitted actor, path outside status.json, URL or command is trusted.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from scripts.lib import design_decisions as dd
from scripts.lib import operator_approvals as core

PREFIX = "/api/v2/design"
ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Ctx:
    principal: Callable[[], str]
    listener: Callable[[], str | None]
    csrf: Callable[[str, str], tuple[bool, str]]
    allowed_logins: frozenset
    ledger: core.DecisionLedger
    root: Path = ROOT
    private_root: Callable[[], Path] = dd.private_design_root
    clock: Callable[[], datetime] = core.utc_now
    can_read: Callable[[], bool] = field(default=lambda: False)


def default_ctx() -> Ctx:
    from scripts.lib import cc_auth
    from scripts.lib.approval_package import governance_dir
    cfg = cc_auth.load_config()

    def approved():
        registry = json.loads((ROOT / "config/data_source_authority.json").read_text(encoding="utf-8"))
        return core.writes_approved(registry)

    return Ctx(principal=cc_auth.current_principal,
               listener=lambda: (cc_auth.current_request_context() or {}).get("listener"),
               csrf=lambda m, p: cc_auth.command_csrf_check(cfg, m, p), allowed_logins=cfg.allowed_logins,
               ledger=core.DecisionLedger(governance_dir() / "operator_decisions.jsonl", approved=approved),
               can_read=lambda: cc_auth.current_principal() == "service-token")


def _operator(ctx: Ctx) -> str | None:
    """Same rule as operator_approvals_api._operator: tailnet login via the serve proxy, in allowed_logins."""
    actor = ctx.principal() or ""
    if (actor.startswith("tailnet:") and ctx.listener() == "serve_proxy"
            and actor[8:].strip().lower() in ctx.allowed_logins):
        return actor
    return None


def _q(query, key: str) -> str:
    value = (query or {}).get(key) if isinstance(query, dict) else None
    if isinstance(value, list):
        value = value[0] if value else None
    return value if isinstance(value, str) else ""


def handle(path: str, method: str, body=None, query=None, *, ctx: Ctx | None = None):
    base = (path or "").split("?", 1)[0].rstrip("/")
    if not (base == PREFIX or base.startswith(PREFIX + "/")):
        return None
    try:
        ctx = ctx or default_ctx()
        method = (method or "GET").upper()
        sub = base[len(PREFIX):]
        actor = _operator(ctx)
        if method == "GET":
            if not actor and not ctx.can_read():
                raise core.Refused("AUTHENTICATED_READER_REQUIRED", 403)
            if sub == "/approvals":
                data = dd.projection(ctx.root, ledger_rows=ctx.ledger.rows(), now=ctx.clock())
                data["can_decide"] = bool(actor)
                return 200, {"ok": True, "data": data}
            if sub == "/asset":
                return 200, {"ok": True, "data": dd.image(ctx.root, ctx.private_root(), _q(query, "page"),
                                                         _q(query, "version"), _q(query, "path"))}
            raise core.Refused("NOT_FOUND", 404)
        if method != "POST":
            raise core.Refused("METHOD_NOT_ALLOWED", 405)
        if not actor:
            raise core.Refused("AGENT_CALLER_REFUSED", 403)
        ok, _why = ctx.csrf("POST", base)
        if not ok:
            raise core.Refused("CSRF_REFUSED", 403)
        if sub != "/decide":
            raise core.Refused("NOT_FOUND", 404)
        result = dd.decide(actor, body, root=ctx.root, ledger=ctx.ledger, private_root=ctx.private_root())
        return 200, {"ok": True, "data": result}
    except core.Refused as exc:
        return exc.status, {"ok": False, "error": exc.code}
    except Exception as exc:  # noqa: BLE001 — never leak a traceback to the page
        return 503, {"ok": False, "error": "SOURCE_UNAVAILABLE", "detail": type(exc).__name__}
