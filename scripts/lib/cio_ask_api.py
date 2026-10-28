"""Ask the CIO — Command Center API (Phase 8). READ_ONLY_ADVISORY. Operator-only.

    POST /api/v2/cio/ask                         {question, thread_id?, depth?: quick|deep, client_request_id?}
    GET  /api/v2/cio/asks?limit=                 "My questions": thread summaries, newest first
         &group_by=security|sector|theme|date|none&q=&channel=   + grouped questions (scripts/lib/cio_ask_groups.py)
    GET  /api/v2/cio/asks/tracked                tracked entities (for Watch / Home / alert flags)
    GET  /api/v2/cio/asks/<thread_id|ask_id>     one thread: turns, answer versions, sources, tracking
    POST /api/v2/cio/asks/<thread_id>/deep       {ask_id?} — request the deep (Phase 9) answer
    POST /api/v2/cio/asks/<thread_id>/untrack    {entity_key}
    POST /api/v2/cio/asks/<thread_id>/regroup    {ask_id, group_by, group_key|null, group_label?} — ask.group_override

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
            data: dict[str, Any] = {"threads": core.list_threads(deps=deps, limit=lim), "as_of": _now()}
            gb = _first(q.get("group_by"))
            if gb is not None:
                from scripts.lib import cio_ask_groups as groups  # noqa: PLC0415

                channel = _first(q.get("channel")) or None
                if gb not in groups.GROUP_BYS or (channel is not None and channel not in groups.CHANNELS):
                    return _err(400, "BAD_GROUPING", f"group_by {'|'.join(groups.GROUP_BYS)}; channel cc|telegram")
                d = core._deps(deps)
                threads = d.store.threads() if d else {}
                events = d.store.events() if d else []
                data["grouped"] = groups.group_questions(
                    threads,
                    group_by=gb,
                    q=str(_first(q.get("q")) or ""),
                    channel=channel,
                    events=events,
                    facts_for=_facts_reader(ctx),
                    stance_for=_stance_reader(ctx),
                )
            return 200, {"ok": True, "data": data}
        sub = base[len(PREFIX_ASKS) + 1 :]
        if sub == "tracked":
            d = core._deps(deps)
            rows = d.store.tracked_entities() if d else []
            return 200, {"ok": True, "data": {"tracked": rows, "as_of": _now()}}
        if ID_RE.match(sub):
            t = _thread(core, deps, sub)
            if not t:
                return _err(404, "NOT_FOUND")
            from scripts.lib import cio_ask_groups as groups  # noqa: PLC0415

            d = core._deps(deps)
            related = groups.related_from_memory(t, d.store.threads() if d else {})
            return 200, {"ok": True, "data": {"thread": t, "related_from_memory": related}}
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
        if action == "regroup":
            return _regroup(core, deps, tid, b)
        if action == "deep":
            t = _thread(core, deps, tid)
            if not t:
                return _err(404, "NOT_FOUND")
            ask_id = str(b.get("ask_id") or (t["turns"][-1]["ask_id"] if t["turns"] else ""))
            r = core.request_deep(tid, ask_id, deps=deps, request_id=b.get("request_id"))
            return (200, {"ok": True, "data": r}) if r.get("ok") else _err(400 if r.get("error") == "BAD_REQUEST_ID" else 404, str(r.get("error")))
    return _err(404, "NOT_FOUND")


def _regroup(core, deps, tid: str, b: dict) -> tuple[int, dict]:
    """Append an ``ask.group_override`` event (operator manual regroup). Never edits an earlier event."""
    from scripts.lib import cio_ask_groups as groups  # noqa: PLC0415
    from scripts.lib.cio_ask_store import event_id_for  # noqa: PLC0415

    d = core._deps(deps)
    t = d.store.thread(tid) if d else None
    if not t:
        return _err(404, "NOT_FOUND")
    ask_id, gb, key = b.get("ask_id"), b.get("group_by"), b.get("group_key")
    if not (isinstance(ask_id, str) and any(turn.get("ask_id") == ask_id for turn in t["turns"])):
        return _err(400, "ASK_NOT_IN_THREAD")
    if gb not in groups.GROUP_BYS or gb == "none":
        return _err(400, "BAD_GROUPING", "security|sector|theme|date")
    if key is not None and not (isinstance(key, str) and 0 < len(key) <= 200):
        return _err(400, "BAD_GROUP_KEY")
    label = b.get("group_label")
    label = str(label)[:120] if isinstance(label, str) and label.strip() else None
    at = _now()
    ev, _created = d.store.append(
        "ask.group_override",
        {"thread_id": tid, "ask_id": ask_id, "group_by": gb, "group_key": key, "group_label": label, "by": "operator"},
        event_id=event_id_for("ask.group_override", ask_id, gb, key or "", at),
    )
    return 200, {"ok": True, "data": {"override": ev}}


def _facts_reader(ctx: Ctx):
    """security entity -> C1 company facts (GUID-bound CIO record). Injected readers win (tests, fixtures)."""
    injected = getattr(ctx.deps, "facts_for", None) if ctx.deps is not None else None
    if injected is not None:
        return injected
    cache: dict[str, Any] = {}

    def read(entity: dict) -> dict:
        guid = entity.get("security_guid")
        if not guid:
            return {}
        try:
            if "snapshot" not in cache:
                from scripts.lib.data_broker.cio_company_facts import load_snapshot  # noqa: PLC0415

                cache["snapshot"] = load_snapshot()
            from scripts.lib.data_broker.cio_company_facts import for_security  # noqa: PLC0415

            return for_security(cache["snapshot"], str(entity.get("symbol") or ""), guid)["company_facts"]
        except Exception:  # noqa: BLE001 — a missing record is an "Unclassified" group, never a guess
            return {}

    return read


def _stance_reader(ctx: Ctx):
    """symbols -> {SYM: {stance, conviction, as_of, source}} from the CIO prospect store, only when it is live."""
    injected = getattr(ctx.deps, "stance_for", None) if ctx.deps is not None else None
    if injected is not None:
        return injected

    def read(symbols: list[str]) -> dict[str, dict]:
        try:
            from scripts.lib.data_broker.trade_journey import _cio_prospects  # noqa: PLC0415

            rows, status = _cio_prospects(symbols)
        except Exception:  # noqa: BLE001
            rows, status = None, "error"
        if rows is None:
            why = f"CIO prospect store not live ({status})"
            return {s: {"missing_reason": why} for s in symbols}
        return {
            s: {
                "stance": r.get("stance"),
                "conviction": r.get("conviction"),
                "as_of": r.get("evidence_at") or r.get("updated_at"),
                "source": "cio_prospect",
            }
            for s, r in rows.items()
        }

    return read


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
