"""Ticker Prospectus — portfolio-server API (contract: coordination/handoffs/prospectus-20261026/CONTRACT.md).

    GET  /api/v2/prospectus/index                         {items, totals, budget}
    GET  /api/v2/prospectus/<SYMBOL>                      latest prospectus.json + {versions, since_report}
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
import json
from pathlib import Path
import re
import sys as _sys
from typing import Any, Callable, Optional

_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)

from scripts.lib.prospectus import load_config, store  # noqa: E402
from scripts.lib.prospectus import presentation  # noqa: E402

try:
    from scripts.lib.security_identity import is_dead_cusip_holding  # noqa: E402
except ImportError:  # scripts/ on sys.path
    from lib.security_identity import is_dead_cusip_holding  # type: ignore  # noqa: E402

PREFIX = "/api/v2/prospectus"
SERVE_PROXY = "serve_proxy"
CONTENT_TYPES = {"html": "text/html; charset=utf-8", "pdf": "application/pdf",
                 "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
_PATH_RE = re.compile(r"^/api/v2/prospectus/([A-Za-z0-9.\-]{1,12})(?:/(refresh|file/(html|pdf|docx)))?$")

# --- Stored-unit normalization (OP-064 legacy market cap) ---------------------------------------------------------
# The peer block's ``market_cap_b`` is Finviz "Market Cap" in MILLIONS of dollars despite the name, and the column
# label says "$B". Prospectus builds that predate the producer conversion wrote the raw cache value under that label;
# every stored doc written before this cutover therefore renders "$218731.9B" for ANET's $218.7B. Source of the
# cutover: ``scripts/lib/prospectus/blocks.py`` ``market_cap_billions`` (commit e416d7c55, 2026-10-26 19:29:07 -0400),
# which converts at the source so nothing is normalised twice.
#
# The doc's own ``version`` stamp names the code version that wrote it, so the stamp — never the magnitude — decides:
#   * before the cutover  -> divide the peer market caps by 1000 exactly once, at read;
#   * at/after the cutover -> values are already $B, left untouched;
#   * no readable stamp   -> the unit is unverified: the values are withdrawn (the UI renders "—"), never guessed.
# A magnitude rule is wrong here: a $0.7B name stored in millions is 696.65, under any threshold that catches the
# large caps, and a small cap would be shown 1000x too big.
PEER_MARKET_CAP_CUTOVER_VERSION = "20261026T232907Z"  # blocks.py e416d7c55, 2026-10-26T19:29:07-04:00
UNIT_RULE = "prospectus_peer_market_cap_b@v1"
_MILLIONS_TO_BILLIONS = 1000.0
_CAP_FACT_LABEL_RE = re.compile(r"^(?:.+ )?Mkt cap \(\$B\)$|^Market cap \(\$B\)$")


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


def _num(v: Any) -> Optional[float]:
    """A finite number, or None. Booleans are not figures."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def normalize_stored_units(doc: dict) -> dict:
    """Convert a unit a pre-cutover prospectus build stored wrongly; returns ``doc``.

    Only the peer block carries a field whose unit changed under a fixed name (``market_cap_b``: MILLIONS before the
    producer cutover, billions after — see the block comment above). The decision and its effect are recorded on the
    payload as ``unit_normalization``, so the conversion is auditable and cannot be applied twice by a later reader.
    The stored file is never written: this is a read.
    """
    blocks = doc.get("blocks") if isinstance(doc.get("blocks"), dict) else {}
    pc = blocks.get("peer_comparison") if isinstance(blocks.get("peer_comparison"), dict) else None
    rows = [r for r in ((pc or {}).get("rows") or []) if isinstance(r, dict)]
    median = (pc or {}).get("median") if isinstance((pc or {}).get("median"), dict) else None
    has_cap = (any(_num(r.get("market_cap_b")) is not None for r in rows)
               or (median is not None and _num(median.get("market_cap_b")) is not None))
    if not pc or not has_cap:
        return doc
    prior = doc.get("unit_normalization") if isinstance(doc.get("unit_normalization"), dict) else {}
    if prior.get("rule") == UNIT_RULE:  # already decided for this payload: never divide twice
        return doc
    version = str(doc.get("version") or "").strip()
    record: dict[str, Any] = {"rule": UNIT_RULE, "cutover_version": PEER_MARKET_CAP_CUTOVER_VERSION}
    if not store.STAMP_RE.match(version):
        # Unknown beats wrong: withdraw a figure whose unit cannot be established rather than print a guess. The
        # cap-labelled FACTS carry the same stored values under the same "$B" label, so they are withdrawn by the
        # SAME exact value-identity set the legacy arm converts below (cc-deepseek-9 VERDICT 2026-11-14T21:23Z, F1:
        # nulling the rows alone left a footnote printing the 1000x figure while the record said "withdrawn").
        # A cap-labelled fact citing a value this table does not hold — or a dollar-valued fact such as the
        # subject's own `MarketCap (latest)` — is not guessed at and is left exactly as stored.
        stored_caps: set[float] = set()
        withdrawn_rows = 0
        for r in rows:
            v = _num(r.get("market_cap_b"))
            if v is not None:
                stored_caps.add(v)
                r["market_cap_b"] = None
                withdrawn_rows += 1
        median_withdrawn = False
        if median is not None:
            v = _num(median.get("market_cap_b"))
            if v is not None:
                stored_caps.add(v)
                median["market_cap_b"] = None
                median_withdrawn = True
        facts_withdrawn = 0
        for f in doc.get("facts") or []:
            if not isinstance(f, dict) or not _CAP_FACT_LABEL_RE.match(str(f.get("label") or "")):
                continue
            v = _num(f.get("value"))
            if v is not None and v in stored_caps:
                f["value"] = None
                # The writer's own convention for an unprintable value; the client renders `text` in place of the
                # number (prospectusModel.ts footnotes), so the footnote reads as a muted note, not as a figure.
                f["text"] = "not reliable (stored unit unverified)"
                facts_withdrawn += 1
        record.update({"applied": False, "action": "withdrawn", "version": version,
                       "rows": withdrawn_rows, "median": median_withdrawn, "facts": facts_withdrawn,
                       "reason": "no readable version stamp — stored unit unverified, market cap withdrawn"})
        doc["unit_normalization"] = record
        return doc
    if version >= PEER_MARKET_CAP_CUTOVER_VERSION:
        record.update({"applied": False, "action": "none", "version": version,
                       "reason": "written after the producer conversion; peer market caps already in $B"})
        doc["unit_normalization"] = record
        return doc
    # Legacy: $M -> $B, exactly once. Facts that cite a peer cap carry the same stored value under a "$B" label, so
    # they are converted by exact value identity — the payload never disagrees with itself, and a dollar-valued fact
    # (the subject's own market cap in dollars, e.g. 217396490000.0) matches no peer value and is left alone.
    stored_caps: set[float] = set()
    row_fields = 0
    for r in rows:
        v = _num(r.get("market_cap_b"))
        if v is None:
            continue
        stored_caps.add(v)
        r["market_cap_b"] = round(v / _MILLIONS_TO_BILLIONS, 2)
        row_fields += 1
    median_converted = False
    if median is not None:
        v = _num(median.get("market_cap_b"))
        if v is not None:
            stored_caps.add(v)
            median["market_cap_b"] = round(v / _MILLIONS_TO_BILLIONS, 2)
            median_converted = True
    fact_fields = 0
    for f in doc.get("facts") or []:
        if not isinstance(f, dict) or not _CAP_FACT_LABEL_RE.match(str(f.get("label") or "")):
            continue
        v = _num(f.get("value"))
        if v is not None and v in stored_caps:
            f["value"] = round(v / _MILLIONS_TO_BILLIONS, 2)
            fact_fields += 1
    record.update({"applied": bool(row_fields or median_converted), "action": "divided_1000", "version": version,
                   "rows": row_fields, "median": median_converted, "facts": fact_fields,
                   "reason": "written before the producer conversion; peer market caps are MILLIONS, converted once"})
    doc["unit_normalization"] = record
    return doc


def budget(root: Path) -> dict:
    try:
        from scripts.lib.anthropic_credit import CreditBook
        from scripts.lib.anthropic_transport import load_policy
        snap = CreditBook(root, load_policy()).snapshot(now=datetime.now(timezone.utc))
        return {"credit_remaining_usd": snap.get("estimated_credit_remaining_usd"),
                "today_used_usd": snap.get("today_used_usd"), "daily_cap_usd": snap.get("daily_cap_usd"),
                "status": snap.get("status")}
    except Exception as exc:  # noqa: BLE001 - the budget panel degrades; the list still renders
        # CreditDenied carries WHY the book refused (CREDIT_UNAVAILABLE, CREDIT_CONFIGURATION_INVALID,
        # CREDIT_CLOCK_INVALID …). The class name alone told the operator "the credit check was refused"
        # and no more; LQ-20261107-178 showed the real cause was an unreadable journal.
        reason = getattr(exc, "reason", None)
        out = {"credit_remaining_usd": None, "today_used_usd": None, "daily_cap_usd": None,
               "status": "UNAVAILABLE", "error": type(exc).__name__}
        if isinstance(reason, str) and reason.strip():
            out["reason"] = reason.strip()[:64]
        return out


QUEUE_STATUS = {"running": "running", "failed": "failed", "blocked_data": "blocked_data"}


def holdings_rows_for_dead_filter(root: Path) -> list[dict[str, Any]]:
    """Raw holdings rows under ``root`` for the dead-CUSIP ignore rule.

    Missing or unreadable store → empty list (no symbols dropped). The broker
    file is not written. LQ-20261107-1448.
    """
    path = Path(root) / "data" / "portfolios" / "state" / "holdings.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    rows = doc.get("holdings") if isinstance(doc, dict) else None
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def dead_cusip_symbols(holdings_rows: list[Any] | None) -> set[str]:
    """Symbols whose *every* holdings row is a dead CUSIP (LQ-20261107-1458).

    ``is_dead_cusip_holding`` is applied per row. A symbol stays when any row for
    it fails that predicate (e.g. account A unpriced, account B still priced).
    A symbol whose rows are all dead is dropped. Symbols with no holdings rows
    are not returned here.
    """
    by_sym: dict[str, list[Any]] = {}
    for row in holdings_rows or []:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or "").strip().upper()
        if not sym:
            continue
        by_sym.setdefault(sym, []).append(row)
    return {
        sym
        for sym, rows in by_sym.items()
        if rows and all(is_dead_cusip_holding(r) for r in rows)
    }


def without_dead_cusip_index_items(
    items: list[Any] | None,
    holdings_rows: list[Any] | None,
) -> list[dict[str, Any]]:
    """Drop prospectus index items whose holdings rows are all dead CUSIPs.

    Per-row predicate (LQ-1458): one zero row must not hide a priced row of the
    same symbol. A priced CUSIP stays. Non-CUSIP tickers stay. The store is not
    written.
    """
    dead = dead_cusip_symbols(holdings_rows)
    if not dead:
        return [i for i in (items or []) if isinstance(i, dict)]
    return [
        i for i in (items or [])
        if isinstance(i, dict) and str(i.get("symbol") or "").strip().upper() not in dead
    ]


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
        items.append({"symbol": sym, "name": presentation.index_name(sym, e.get("name")),
                      "scope": "holding" if (scopes.get(sym) or e.get("scope")) == "holding" else "watch",
                      "version": e.get("version"), "generated_at": e.get("generated_at"), "model": e.get("model"),
                      "cost_usd": e.get("cost_usd"), "status": status, "stale": stale, "next_due": due,
                      "verdict_line": e.get("verdict_line"),
                      "failure_reason": ((q or {}).get("last_error") or e.get("failure_reason")) if status == "failed" else None,
                      "partial_gaps": (e.get("partial_gaps") or []) if status == "partial" else [],
                      # data-quality gate (scripts/lib/prospectus/quality_gate.py): pass / soft_fail / hard_fail + why
                      "gate_status": e.get("gate_status"), "gate_reasons": e.get("gate_reasons") or [],
                      "gate_checked_at": e.get("gate_checked_at")})
    # LQ-20261107-1448: ignore dead CUSIP holdings (same predicate as LQ-1417/1418).
    # Stale universe/index entries for those symbols must not reach /api/v2/prospectus/index.
    items = without_dead_cusip_index_items(items, holdings_rows_for_dead_filter(root))
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
    # Stored-unit normalization (a legacy doc's peer market caps are MILLIONS under a "$B" label); recorded on the
    # payload as `unit_normalization`. The stored JSON, the pre-rendered html/pdf/docx files and the delta prompt are
    # untouched — this changes what the JSON reader is served, nothing else.
    doc = normalize_stored_units(doc)
    doc["viewer"] = {"operator": bool(_safe_operator(ctx))}
    entry = store.read_index(base)["items"].get(sym) or {}
    doc.setdefault("failure_reason", entry.get("failure_reason") if entry.get("status") == "failed" else None)
    doc["gate_status"] = (doc.get("gate") or {}).get("status") or entry.get("gate_status")
    doc["gate_reasons"] = (doc.get("gate") or {}).get("reasons") or entry.get("gate_reasons") or []
    if entry.get("status") == "blocked_data":  # a newer attempt was blocked on data; the stored version predates it
        doc["latest_attempt"] = {"status": "blocked_data", "gate_reasons": entry.get("gate_reasons") or []}
    # Read-time presentation (footnote numbers, display name, fund layout, relevant coverage); never stored.
    doc["presentation"] = presentation.present(doc)
    if version is None or version == (doc.get("versions") or [{}])[0].get("version"):
        doc["since_report"] = since_report(base, sym, doc)
    return 200, doc


def since_report(base: Path, sym: str, doc: dict, *, now: datetime | None = None) -> dict | None:
    """"Since this report" (operator 2026-10-27): relevant headlines / filings with a material badge, the price move
    since the report, stop events and status, read from the news log the window lane keeps. No model, no DB.
    Never fails the page: an unreadable log returns None."""
    try:
        from scripts.lib.prospectus import news_note, schedule
        cfg = load_config()
        now = now or datetime.now(timezone.utc)
        q = next((r for r in store.read_queue(base)["items"] if r.get("symbol") == sym
                  and r.get("state") in ("queued", None, schedule.HELD)), None)
        scope = "holding" if doc.get("scope") == "holding" else "watch"
        wins = {w.get("id"): w for w in schedule.window_cfg(cfg).get("windows") or []}
        win = None
        for nxt in schedule.next_windows(cfg, now, 6):  # the next window that covers this report's scope
            w = wins.get(nxt["id"]) or {}
            if scope in (w.get("scopes") or ["holding", "watch"]):
                win = {"id": nxt["id"], "start": nxt["start"], "time": w.get("time"), "label": w.get("label")}
                break
        return news_note.since_report(base, sym, doc, cfg=cfg, queue_row=q, next_window=win)
    except Exception:  # noqa: BLE001 - the strip degrades; the report still renders
        return None


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
