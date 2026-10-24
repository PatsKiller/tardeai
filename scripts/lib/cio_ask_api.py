"""Ask the CIO — Command Center API (Phase 8). READ_ONLY_ADVISORY. Operator-only.

    POST /api/v2/cio/ask                         {question, thread_id?, depth?: quick|deep, client_request_id?}
    GET  /api/v2/cio/asks?limit=                 "My questions": thread summaries, newest first
    GET  /api/v2/cio/asks/tracked                tracked entities (for Watch / Home / alert flags)
    GET  /api/v2/cio/asks/<thread_id|ask_id>     one thread: turns, answer versions, sources, tracking
    POST /api/v2/cio/asks/<thread_id>/deep       {ask_id?} — request the deep (Phase 9) answer
    POST /api/v2/cio/asks/<thread_id>/untrack    {entity_key}

Auth (the Ops Controls convention, ``scripts/lib/ops_controls_api.py``): every route answers only the operator's
tailnet identity on the serve proxy; agents, n8n and the service token are refused. POSTs re-check same-origin CSRF
(``cc_auth.command_csrf_check``) and are listed in ``config/cc_auth.yaml`` ``csrf.hard_routes`` (``cio_ask_command``).
No route sizes, orders, stops or weights.
"""

from __future__ import annotations

import re
import sys as _sys
from dataclasses import dataclass
from pathlib import Path as _Path
from typing import Any, Callable, Optional

_ROOT = str(_Path(__file__).resolve().parents[2])
if _ROOT not in _sys.path:  # one module identity (scripts.lib.*) whether served as lib.* or imported in tests
    _sys.path.insert(0, _ROOT)

PREFIX_ASK = "/api/v2/cio/ask"
PREFIX_ASKS = "/api/v2/cio/asks"
SERVE_PROXY = "serve_proxy"
ID_RE = re.compile(r"^(thr|ask)_[0-9a-f]{16}$")


@dataclass
class Ctx:
    principal: Callable[[], str]
    listener: Callable[[], Optional[str]]
    csrf: Callable[[str, str], tuple[bool, str]]
    allowed_logins: frozenset
    deps: Any = None  # cio_ask_core.AskDeps; None → defaults
    converse: Optional[Callable[..., dict]] = None


def _default_ctx() -> Ctx:
    try:
        from lib import cc_auth  # type: ignore
    except ImportError:  # pragma: no cover
        from scripts.lib import cc_auth  # type: ignore
    auth_cfg = cc_auth.load_config()
    return Ctx(
        principal=cc_auth.current_principal,
        listener=lambda: (cc_auth.current_request_context() or {}).get("listener"),
        csrf=lambda m, p: cc_auth.command_csrf_check(auth_cfg, m, p),
        allowed_logins=auth_cfg.allowed_logins,
    )


def _err(status: int, code: str, detail: str = "") -> tuple[int, dict]:
    return status, {"ok": False, "error": code, "detail": detail}


def _operator(ctx: Ctx) -> Optional[str]:
    p = ctx.principal() or ""
    if not p.startswith("tailnet:") or ctx.listener() != SERVE_PROXY:
        return None
    login = p[len("tailnet:") :].strip().lower()
    return p if login and login in ctx.allowed_logins else None


def handle(path: str, method: str, body: Any = None, query: Any = None, *, ctx: Optional[Ctx] = None):
    base = (path or "").split("?", 1)[0].rstrip("/")
    if not (base == PREFIX_ASK or base == PREFIX_ASKS or base.startswith(PREFIX_ASKS + "/")):
        return None
    m = (method or "GET").upper()
    try:
        ctx = ctx or _default_ctx()
    except Exception as exc:  # noqa: BLE001
        return _err(503, "AUTH_CONFIG_UNAVAILABLE", type(exc).__name__)
    if not _operator(ctx):
        return _err(403, "AGENT_CALLER_REFUSED", "Ask the CIO answers only the operator's tailnet identity")
    from scripts.lib import cio_ask_core as core  # noqa: PLC0415

    deps = ctx.deps
    q = query if isinstance(query, dict) else {}
    if m == "GET":
        if base == PREFIX_ASKS:
            lim = _int(_first(q.get("limit")), 50)
            return 200, {"ok": True, "data": {"threads": core.list_threads(deps=deps, limit=lim), "as_of": _now()}}
        sub = base[len(PREFIX_ASKS) + 1 :]
        if sub == "tracked":
            d = core._deps(deps)
            rows = d.store.tracked_entities() if d else []
            return 200, {"ok": True, "data": {"tracked": rows, "as_of": _now()}}
        if ID_RE.match(sub):
            t = _thread(core, deps, sub)
            return (200, {"ok": True, "data": {"thread": t}}) if t else _err(404, "NOT_FOUND")
        return _err(404, "NOT_FOUND")
    if m != "POST":
        return _err(405, "METHOD_NOT_ALLOWED")
    ok, why = ctx.csrf("POST", base)
    if not ok:
        return _err(403, "CSRF_REFUSED", why)
    b = body if isinstance(body, dict) else {}
    if base == PREFIX_ASK:
        tid = b.get("thread_id")
        if tid is not None and not (isinstance(tid, str) and ID_RE.match(tid) and tid.startswith("thr_")):
            return _err(400, "BAD_THREAD_ID")
        depth = b.get("depth") or "quick"
        if depth not in ("quick", "deep"):
            return _err(400, "BAD_DEPTH", "quick | deep")
        rid = b.get("client_request_id")
        rid = ("cc_" + re.sub(r"[^A-Za-z0-9_-]", "", str(rid))[:40]) if rid else None
        res = core.ask_from_cc(
            str(b.get("question") or ""), request_id=rid, thread_id=tid, depth=depth, deps=deps, converse=ctx.converse
        )
        if not res.get("ok"):
            return _err(
                400 if res.get("error") != "ASK_DISABLED" else 503,
                str(res.get("error")),
                str(res.get("max_chars") or ""),
            )
        return 200, {"ok": True, "data": res}
    parts = base[len(PREFIX_ASKS) + 1 :].split("/")
    if len(parts) == 2 and parts[0].startswith("thr_") and ID_RE.match(parts[0]):
        tid, action = parts
        if action == "untrack":
            key = str(b.get("entity_key") or "")
            if not key:
                return _err(400, "ENTITY_KEY_REQUIRED")
            r = core.untrack(tid, key, deps=deps)
            return (200, {"ok": True, "data": r}) if r.get("ok") else _err(404, str(r.get("error")))
        if action == "deep":
            t = _thread(core, deps, tid)
            if not t:
                return _err(404, "NOT_FOUND")
            ask_id = str(b.get("ask_id") or (t["turns"][-1]["ask_id"] if t["turns"] else ""))
            r = core.request_deep(tid, ask_id, deps=deps)
            return (200, {"ok": True, "data": r}) if r.get("ok") else _err(404, str(r.get("error")))
    return _err(404, "NOT_FOUND")


def _thread(core, deps, ident: str) -> Optional[dict]:
    d = core._deps(deps)
    if d is None:
        return None
    tid = ident if ident.startswith("thr_") else d.store.thread_for_ask(ident)
    return d.store.thread(tid) if tid else None


def _first(v: Any) -> Any:
    return v[0] if isinstance(v, list) and v else v


def _int(v: Any, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _now() -> str:
    from scripts.lib.cio_ask_contract import utc_now_iso  # noqa: PLC0415

    return utc_now_iso()


__all__ = ["handle", "Ctx", "PREFIX_ASK", "PREFIX_ASKS"]
