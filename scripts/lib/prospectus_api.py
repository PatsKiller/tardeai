"""Ticker Prospectus — portfolio-server API (contract: coordination/handoffs/prospectus-20261026/CONTRACT.md).

    GET  /api/v2/prospectus/index                         {items, totals, budget}
    GET  /api/v2/prospectus/<SYMBOL>                      latest prospectus.json + {versions}
    GET  /api/v2/prospectus/<SYMBOL>/file/<html|pdf|docx>?version=<stamp>   file from disk (Content-Disposition)
    POST /api/v2/prospectus/<SYMBOL>/refresh              queue a rewrite (operator tailnet identity only)

Reads are small: index.json, queue.json, universe.json, one prospectus.json and one versions.json — never all
prospectuses (portfolio server MemoryHigh 1.6 GB). Nothing is generated in the request path: refresh only queues.
The POST follows the Ops Controls / Ask the CIO convention: the operator's tailnet identity on the serve proxy, and a
same-origin CSRF re-check (``config/cc_auth.yaml`` hard route ``prospectus_command``); agents, n8n and the service
token are refused. READ_ONLY_ADVISORY: no route sizes, orders, stops or weights.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
import sys as _sys
from typing import Any, Callable, Optional

_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)

from scripts.lib.prospectus import load_config, store  # noqa: E402

PREFIX = "/api/v2/prospectus"
SERVE_PROXY = "serve_proxy"
CONTENT_TYPES = {"html": "text/html; charset=utf-8", "pdf": "application/pdf",
                 "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
_PATH_RE = re.compile(r"^/api/v2/prospectus/([A-Za-z0-9.\-]{1,12})(?:/(refresh|file/(html|pdf|docx)))?$")


@dataclass
class Ctx:
    principal: Callable[[], str]
    listener: Callable[[], Optional[str]]
    csrf: Callable[[str, str], tuple[bool, str]]
    allowed_logins: frozenset
    state_root: Optional[Path] = None


@dataclass
class FileResult:
    """A file to stream from disk; the server writes the headers and the bytes."""
    path: Path
    filename: str
    content_type: str
    disposition: str


def _default_ctx() -> Ctx:
    try:
        from lib import cc_auth  # type: ignore
    except ImportError:  # pragma: no cover
        from scripts.lib import cc_auth  # type: ignore
    cfg = cc_auth.load_config()
    return Ctx(principal=cc_auth.current_principal,
               listener=lambda: (cc_auth.current_request_context() or {}).get("listener"),
               csrf=lambda m, p: cc_auth.command_csrf_check(cfg, m, p), allowed_logins=cfg.allowed_logins)


def _state_root(ctx: Ctx) -> Path:
    if ctx.state_root is not None:
        return Path(ctx.state_root)
    from scripts.lib.prospectus.inputs import _imp_any
    return Path(_imp_any("scripts.lib.anthropic_routing", "lib.anthropic_routing").state_root())


def _err(status: int, code: str, detail: str = "") -> tuple[int, dict]:
    return status, {"ok": False, "error": code, "detail": detail}


def _operator(ctx: Ctx) -> Optional[str]:
    p = ctx.principal() or ""
    if not p.startswith("tailnet:") or ctx.listener() != SERVE_PROXY:
        return None
    login = p[len("tailnet:"):].strip().lower()
    return p if login and login in ctx.allowed_logins else None


def _safe_operator(ctx: Ctx) -> Optional[str]:
    try:
        return _operator(ctx)
    except Exception:  # noqa: BLE001 - an unknown identity is never the operator
        return None


def _q(query: Any, key: str) -> Optional[str]:
    if not isinstance(query, dict):
        return None
    v = query.get(key)
    if isinstance(v, list):
        v = v[0] if v else None
    return str(v) if v not in (None, "") else None


def budget(root: Path) -> dict:
    try:
        from scripts.lib.anthropic_credit import CreditBook
        from scripts.lib.anthropic_transport import load_policy
        snap = CreditBook(root, load_policy()).snapshot(now=datetime.now(timezone.utc))
        return {"credit_remaining_usd": snap.get("estimated_credit_remaining_usd"),
                "today_used_usd": snap.get("today_used_usd"), "daily_cap_usd": snap.get("daily_cap_usd"),
                "status": snap.get("status")}
    except Exception as exc:  # noqa: BLE001 - the budget panel degrades; the list still renders
        return {"credit_remaining_usd": None, "today_used_usd": None, "daily_cap_usd": None,
                "status": "UNAVAILABLE", "error": type(exc).__name__}


QUEUE_STATUS = {"running": "running", "failed": "failed", "blocked_data": "blocked_data"}


def index_payload(root: Path, *, now: datetime | None = None, operator: bool = False) -> dict:
    now = now or datetime.now(timezone.utc)
    cfg = load_config()
    base = store.base_dir(root, cfg)
    idx = store.read_index(base)["items"]
    queue = {r["symbol"]: r for r in store.read_queue(base)["items"] if isinstance(r, dict) and r.get("symbol")}
    universe = store.read_universe(base)
    order = [r["symbol"] for r in universe] + sorted(set(idx) - {r["symbol"] for r in universe})
    scopes = {r["symbol"]: r.get("scope") for r in universe}
    items = []
    for sym in order:
        e = idx.get(sym) or {}
        q = queue.get(sym)
        if q is not None:
            status = QUEUE_STATUS.get(q.get("state"), "queued")
        else:
            status = e.get("status") if e.get("status") in store.STATUSES else ("ready" if e.get("version") else "missing")
            if status in ("queued", "running"):
                status = "ready" if e.get("version") else "missing"
        due = e.get("next_due")
        stale = bool(e.get("version")) and bool(due) and str(due) <= now.isoformat()
        items.append({"symbol": sym, "name": e.get("name") or sym,
                      "scope": "holding" if (scopes.get(sym) or e.get("scope")) == "holding" else "watch",
                      "version": e.get("version"), "generated_at": e.get("generated_at"), "model": e.get("model"),
                      "cost_usd": e.get("cost_usd"), "status": status, "stale": stale, "next_due": due,
                      "verdict_line": e.get("verdict_line"),
                      "failure_reason": ((q or {}).get("last_error") or e.get("failure_reason")) if status == "failed" else None,
                      "partial_gaps": (e.get("partial_gaps") or []) if status == "partial" else [],
                      # data-quality gate (scripts/lib/prospectus/quality_gate.py): pass / soft_fail / hard_fail + why
                      "gate_status": e.get("gate_status"), "gate_reasons": e.get("gate_reasons") or [],
                      "gate_checked_at": e.get("gate_checked_at")})
    totals = {k: sum(1 for i in items if i["status"] == k) for k in ("ready", "partial", "queued", "running", "missing", "failed", "blocked_data")}
    return {"items": items, "totals": totals, "budget": budget(root), "viewer": {"operator": bool(operator)}}


def handle(path: str, method: str, body: Any = None, query: Any = None, *, ctx: Optional[Ctx] = None):
    """Return (status, dict), a FileResult, or None when the path is not ours."""
    base_path = (path or "").split("?", 1)[0].rstrip("/")
    if not (base_path == PREFIX or base_path.startswith(PREFIX + "/")):
        return None
    m = (method or "GET").upper()
    try:
        ctx = ctx or _default_ctx()
    except Exception as exc:  # noqa: BLE001
        return _err(503, "AUTH_CONFIG_UNAVAILABLE", type(exc).__name__)
    root = _state_root(ctx)
    if base_path == PREFIX + "/index":
        return (200, index_payload(root, operator=bool(_safe_operator(ctx)))) if m == "GET" else _err(405, "METHOD_NOT_ALLOWED")
    match = _PATH_RE.match(base_path)
    if not match:
        return _err(404, "NOT_FOUND")
    sym = store.norm_symbol(match.group(1))
    if not sym:
        return _err(400, "INVALID_SYMBOL")
    base = store.base_dir(root, load_config())
    action, kind = match.group(2), match.group(3)
    if action == "refresh":
        if m != "POST":
            return _err(405, "METHOD_NOT_ALLOWED")
        who = _operator(ctx)
        if not who:
            return _err(403, "AGENT_CALLER_REFUSED", "refresh is operator-only (tailnet identity on the serve proxy)")
        ok, why = ctx.csrf("POST", base_path)
        if not ok:
            return _err(403, "CSRF_REFUSED", why)
        scope = next((r.get("scope") for r in store.read_universe(base) if r["symbol"] == sym), None)
        prem = next((bool(r.get("premium")) for r in store.read_universe(base) if r["symbol"] == sym), False)
        store.enqueue(base, [{"symbol": sym, "scope": scope or "watch", "premium": prem, "priority": 1,
                              "mode": "full", "reason": "operator_refresh", "requested_by": who}])
        position = next((i for i, r in enumerate(store.read_queue(base)["items"]) if r["symbol"] == sym), None)
        return 202, {"ok": True, "queued": True, "symbol": sym, "position": position}
    if m != "GET":
        return _err(405, "METHOD_NOT_ALLOWED")
    version = _q(query, "version")
    if version is not None and not store.STAMP_RE.match(version):
        return _err(400, "INVALID_VERSION")
    if kind:
        target = store.file_path(base, sym, kind, version)
        if target is None:
            return _err(404, "NOT_FOUND", f"no {kind} for {sym}")
        ver = target.parent.name
        return FileResult(path=target, filename=f"{sym}-prospectus-{ver}.{kind}", content_type=CONTENT_TYPES[kind],
                          disposition="inline" if kind in ("html", "pdf") else "attachment")
    doc = store.read_prospectus(base, sym, version)
    if doc is None:
        q = next((r for r in store.read_queue(base)["items"] if r.get("symbol") == sym), None)
        return 404, {"ok": False, "error": "NOT_FOUND", "symbol": sym,
                     "status": (QUEUE_STATUS.get(q.get("state"), "queued") if q else "missing"),
                     "failure_reason": (q or {}).get("last_error"), "viewer": {"operator": bool(_safe_operator(ctx))}}
    doc["versions"] = [{k: r.get(k) for k in ("version", "generated_at", "model")} for r in store.versions(base, sym)]
    doc["viewer"] = {"operator": bool(_safe_operator(ctx))}
    entry = store.read_index(base)["items"].get(sym) or {}
    doc.setdefault("failure_reason", entry.get("failure_reason") if entry.get("status") == "failed" else None)
    doc["gate_status"] = (doc.get("gate") or {}).get("status") or entry.get("gate_status")
    doc["gate_reasons"] = (doc.get("gate") or {}).get("reasons") or entry.get("gate_reasons") or []
    if entry.get("status") == "blocked_data":  # a newer attempt was blocked on data; the stored version predates it
        doc["latest_attempt"] = {"status": "blocked_data", "gate_reasons": entry.get("gate_reasons") or []}
    return 200, doc


def stream_file(handler: Any, result: FileResult, *, chunk: int = 256 * 1024) -> None:
    """Write a FileResult to a BaseHTTPRequestHandler in chunks (no whole-file read)."""
    size = result.path.stat().st_size
    handler.send_response(200)
    handler.send_header("Content-Type", result.content_type)
    handler.send_header("Content-Length", str(size))
    handler.send_header("Content-Disposition", f'{result.disposition}; filename="{result.filename}"')
    handler.send_header("Cache-Control", "private, no-cache")
    handler.send_header("X-Content-Type-Options", "nosniff")
    if result.content_type.startswith("text/html"):
        handler.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; img-src data:")
    handler.end_headers()
    with result.path.open("rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            handler.wfile.write(block)
