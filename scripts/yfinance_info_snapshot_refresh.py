#!/usr/bin/env python3
"""yfinance-info-snapshot — the owner lane for ``yfinance_info_snapshot`` (one raw yfinance ``.info`` per symbol).

Operator decision 2026-10-26 (verbatim: "Yahoo Finance feed … switched on: yes"); store approved 2026-10-10
(CONSOLIDATION_PLAN.md §D.13, registry domain ``yfinance_info_snapshot``). This is the producer the registry row
said was missing (§D.12). It fetches once per symbol per window so consumers (the prospectus fund block, through
``lib.data_broker.yfinance_info``) read the store instead of calling Yahoo themselves.

Universe — only what the operator owns or looks at, never the 3,700-row scanner list:

* every non-cash holding with shares > 0 in any account (``lib.portfolio_positions.load_store``);
* the operator's My Watchlist (``lib.data_broker.watch_domains.membership_operator``);
* the prospectus universe (``<state>/data/prospectus/universe.json`` via ``lib.prospectus.store.read_universe``).

Each symbol passes ``lib.provider_ticker_guard`` (profile ``quote``) before it reaches the provider.

Governed and rate limited:

* a symbol is fetched only when its stored snapshot is older than its window (``ok``: ``--ok-hours`` 20 h;
  ``no_profile`` / ``error``: ``--negative-hours`` 168 h — the negative cache the table was designed for);
* at most ``--max-symbols`` fetches per run (default 300), one at a time, ``--sleep`` seconds apart (default 1.0);
* a provider throttle (HTTP 429 / "Too Many Requests" / rate limit) stops the run at once; the remaining symbols
  are skipped with reason ``rate_limited`` and wait for the next run.

For a fund (``quoteType`` ETF / MUTUALFUND) the payload also carries ``_house_fund`` — the yfinance
``funds_data`` top holdings (symbol, name, weight %), description and overview — so the prospectus fund block can
show top holdings, issuer and index without its own provider call. Every other key is the raw ``.info``.

Writes go through the single declared writer ``lib.writers.yfinance_info_snapshot_writer.write_info_snapshots``
(rails: aware ``fetched_at``, non-empty ``ok`` payload, upsert never regresses ``fetched_at``).

Modes: ``--dry-run`` (the default, and what the n8n stage clamp passes at SHADOW) reads the universe and the store
on a READ ONLY session, fetches at most ``--probe`` symbols (default 3) to prove the provider answers, prints, and
writes nothing — no row, no receipt. ``--apply`` fetches what is due and writes rows plus the LaneRunReceipt
(v2 output fields) ``data/runtime/yfinance-info-snapshot_last.json``.

Exit 0 = run completed (rows written, or nothing due); 1 = the store is missing (migration not applied), the
database or the provider is unavailable, or the universe is empty; 2 = bad arguments.

No broker, no order, no sender, no model. AUTHORITY: READ_ONLY_ADVISORY (market reference data only).
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

LANE_ID = "yfinance-info-snapshot"
SCRIPT = "yfinance_info_snapshot_refresh.py"
FUND_TYPES = frozenset({"ETF", "MUTUALFUND"})
THROTTLE_MARKERS = ("too many requests", "rate limit", "ratelimit", "429")
DEFAULTS = {"ok_hours": 20.0, "negative_hours": 168.0, "max_symbols": 300, "sleep": 1.0, "probe": 3}


class RateLimited(RuntimeError):
    pass


# ── universe ──────────────────────────────────────────────────────────────────────────────────────────────────────
def _f(v: Any) -> Optional[float]:
    try:
        out = float(v)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def held_symbols(store_doc: dict) -> list[str]:
    from lib import portfolio_positions as pp

    out = set()
    for r in (store_doc or {}).get("holdings") or []:
        if not isinstance(r, dict) or pp.is_cash(r):
            continue
        if (_f(r.get("shares", r.get("quantity"))) or 0) > 0:
            sym = str(r.get("symbol") or "").strip().upper()
            if sym:
                out.add(sym)
    return sorted(out)


def build_universe(
    state_root: Path,
    *,
    db_query: Optional[Callable[..., Any]],
    store_doc: Optional[dict] = None,
) -> tuple[dict[str, list[str]], dict[str, str]]:
    """({SYM: [membership, ...]}, {source: status}). A source that cannot be read is reported, never fatal alone."""
    from lib import portfolio_positions as pp
    from lib.provider_ticker_guard import partition

    members: dict[str, list[str]] = {}
    status: dict[str, str] = {}

    def add(syms: Iterable[Any], kind: str) -> None:
        n = 0
        for s in syms:
            sym = str(s or "").strip().upper()
            if sym:
                members.setdefault(sym, [])
                if kind not in members[sym]:
                    members[sym].append(kind)
                n += 1
        status[kind] = f"ok ({n})"

    try:
        doc = store_doc if store_doc is not None else pp.load_store(pp.store_path(state_root))
        add(held_symbols(doc), "held")
    except Exception as exc:  # noqa: BLE001
        status["held"] = f"unreadable: {type(exc).__name__}"
    if db_query is not None:
        try:
            from lib.data_broker.watch_domains import membership_operator

            add((membership_operator(db_query).get("names") or {}).keys(), "watch")
        except Exception as exc:  # noqa: BLE001
            status["watch"] = f"unreadable: {type(exc).__name__}"
    else:
        status["watch"] = "unreadable: no database"
    try:
        from lib.prospectus import load_config
        from lib.prospectus import store as pstore

        base = pstore.base_dir(state_root, load_config())
        add((r.get("symbol") for r in pstore.read_universe(base)), "prospectus")
    except Exception as exc:  # noqa: BLE001
        status["prospectus"] = f"unreadable: {type(exc).__name__}"
    ok, refused = partition(sorted(members), profile="quote")
    for r in refused:
        members.pop(str(r.get("symbol") or "").upper(), None)
    if refused:
        status["ticker_guard_refused"] = str(len(refused))
    return {s: members[s] for s in ok if s in members}, status


# ── due selection ────────────────────────────────────────────────────────────────────────────────────────────────
def due_symbols(universe: Iterable[str], stored: dict[str, dict], *, now: datetime, ok_hours: float,
                negative_hours: float) -> tuple[list[str], int]:
    """Symbols whose stored snapshot is missing or older than its window; held names first. (due, fresh_count)."""
    due: list[str] = []
    fresh = 0
    for sym in universe:
        rec = stored.get(sym) or {}
        age = rec.get("age_hours")
        window = ok_hours if rec.get("status") == "ok" else negative_hours
        if rec and age is not None and age < window:
            fresh += 1
        else:
            due.append(sym)
    return due, fresh


# ── provider ─────────────────────────────────────────────────────────────────────────────────────────────────────
def _is_throttle(exc: BaseException) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return any(m in text for m in THROTTLE_MARKERS)


def _fund_extras(ticker: Any) -> dict:
    out: dict[str, Any] = {}
    try:
        fd = ticker.funds_data
    except Exception:  # noqa: BLE001
        return out
    try:
        th = fd.top_holdings
        rows = []
        if th is not None and not getattr(th, "empty", True):
            for sym, rec in th.iterrows():
                w = _f(rec.get("Holding Percent"))
                rows.append({"symbol": str(sym), "name": str(rec.get("Name") or sym),
                             "weight_pct": round(w * 100, 4) if w is not None else None})
        out["top_holdings"] = rows
    except Exception as exc:  # noqa: BLE001
        if _is_throttle(exc):
            raise
    for attr in ("description", "fund_overview"):
        try:
            val = getattr(fd, attr)
            if isinstance(val, (str, dict)) and val:
                out[attr] = val
        except Exception as exc:  # noqa: BLE001
            if _is_throttle(exc):
                raise
    if out:
        out["fetched_via"] = "yfinance Ticker.funds_data"
    return out


def yfinance_fetch(sym: str) -> dict:
    """{status, payload, quote_type, error}. Raises RateLimited on a provider throttle."""
    import yfinance as yf  # the declared provider (config/data_source_authority.json providers.yfinance)

    try:
        t = yf.Ticker(sym)
        info = t.info or {}
    except Exception as exc:  # noqa: BLE001
        if _is_throttle(exc):
            raise RateLimited(str(exc)[:200]) from exc
        return {"status": "error", "payload": {}, "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
    if not isinstance(info, dict) or not info.get("quoteType"):
        return {"status": "no_profile", "payload": {}, "error": None}
    payload = {k: v for k, v in info.items() if _jsonable(v)}
    if str(info.get("quoteType")).upper() in FUND_TYPES:
        try:
            extra = _fund_extras(t)
        except Exception as exc:  # noqa: BLE001
            raise RateLimited(str(exc)[:200]) from exc
        if extra:
            payload["_house_fund"] = extra
    return {"status": "ok", "payload": payload, "quote_type": info.get("quoteType"), "error": None}


def _jsonable(v: Any) -> bool:
    if isinstance(v, float):
        return math.isfinite(v)
    return isinstance(v, (str, int, bool, list, dict)) or v is None


def fetch_many(symbols: Sequence[str], fetch: Callable[[str], dict], *, sleep_s: float, now_fn: Callable[[], datetime],
               sleep_fn: Callable[[float], None] = time.sleep) -> tuple[list[dict], dict[str, int]]:
    """Sequential fetches; stops at the first throttle. Returns (rows for the writer, skipped_reasons)."""
    rows: list[dict] = []
    skipped: dict[str, int] = {}
    for i, sym in enumerate(symbols):
        if i and sleep_s > 0:
            sleep_fn(sleep_s)
        try:
            res = fetch(sym)
        except RateLimited:
            skipped["rate_limited"] = len(symbols) - i
            break
        rows.append({"symbol": sym, "fetched_at": now_fn(), "status": res.get("status"),
                     "quote_type": res.get("quote_type"), "payload": res.get("payload") or {}, "error": res.get("error")})
        if res.get("status") != "ok":
            skipped[str(res.get("status"))] = skipped.get(str(res.get("status")), 0) + 1
    return rows, skipped


# ── database ─────────────────────────────────────────────────────────────────────────────────────────────────────
def pg_connect(readonly: bool):  # pragma: no cover - exercised on the host only
    import psycopg2

    conn = psycopg2.connect(host=os.getenv("DB_HOST", "localhost"), port=int(os.getenv("DB_PORT", "5432")),
                            dbname=os.getenv("DB_NAME", "trade_ai"), user=os.getenv("DB_USER", "trade_ai"),
                            password=os.getenv("DB_PASSWORD", ""), connect_timeout=10)
    conn.set_session(readonly=readonly, autocommit=readonly)
    return conn


def query_fn(conn: Any) -> Callable[..., list[dict]]:
    def q(sql: str, params: Any = None, **_: Any) -> list[dict]:
        cur = conn.cursor()
        cur.execute(sql, params)
        if cur.description is None:
            return []
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    return q


def table_present(q: Callable[..., list[dict]]) -> bool:
    rows = q("SELECT to_regclass('public.yfinance_info_snapshot') IS NOT NULL AS present", None)
    return bool(rows and rows[0].get("present"))


# ── run ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def state_root() -> Path:
    for name in ("TRADEAI_PERSISTENT_STATE_ROOT", "TRADEAI_STATE_ROOT"):
        v = os.environ.get(name)
        if v:
            return Path(v)
    return ROOT


def run(
    *,
    apply: bool,
    state: Path,
    connect: Callable[[bool], Any],
    fetch: Callable[[str], dict],
    args: argparse.Namespace,
    now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    sleep_fn: Callable[[float], None] = time.sleep,
    store_doc: Optional[dict] = None,
) -> int:
    from lib.lane_last_receipt import dry_run_report, now_iso, receipt_path, write_lane_receipt

    started = now_iso()

    def fail(kind: str, detail: str) -> int:
        print(f"[{LANE_ID}] FAILED ({kind}): {detail}", file=sys.stderr)
        if apply:
            write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started, script=SCRIPT,
                               error=f"{kind}: {detail[:200]}", summary={"failure_kind": kind, "detail": detail[:300]},
                               output={"produced_count": 0, "attempted_count": 0, "skipped_reasons": {kind: 1}})
        return 1

    try:
        conn = connect(not apply)
    except Exception as exc:  # noqa: BLE001
        return fail("dependency_unavailable", f"database: {type(exc).__name__}")
    q = query_fn(conn)
    try:
        if not table_present(q):
            return fail("unconfigured", "table yfinance_info_snapshot does not exist (migration "
                        "migrations/2026_10_10_yfinance_info_snapshot.sql not applied)")
    except Exception as exc:  # noqa: BLE001
        return fail("dependency_unavailable", f"database: {type(exc).__name__}")
    universe, sources = build_universe(state, db_query=q, store_doc=store_doc)
    print(f"[{LANE_ID}] universe {len(universe)} symbols; sources {sources}")
    if not universe:
        return fail("universe_empty_unexpected", f"no held, watch or prospectus symbol readable ({sources})")
    from lib.data_broker.yfinance_info import get_info_batch

    now = now_fn()
    stored = get_info_batch(q, list(universe), now=now)
    if not stored.get("ok", True):
        return fail("dependency_unavailable", f"store read: {stored.get('error')}")
    order = sorted(universe, key=lambda s: (0 if "held" in universe[s] else 1, s))
    due, fresh = due_symbols(order, stored.get("symbols") or {}, now=now, ok_hours=args.ok_hours,
                             negative_hours=args.negative_hours)
    capped = due[: args.max_symbols]
    over_cap = len(due) - len(capped)
    print(f"[{LANE_ID}] due {len(due)} (fresh {fresh}; run cap {args.max_symbols}; over cap {over_cap})")
    if not apply:
        probe = capped[: max(0, args.probe)]
        rows, skipped = fetch_many(probe, fetch, sleep_s=args.sleep, now_fn=now_fn, sleep_fn=sleep_fn)
        for r in rows:
            print(f"[{LANE_ID}] probe {r['symbol']}: {r['status']} quoteType={r.get('quote_type')} "
                  f"keys={len(r['payload'])} fund_extras={'_house_fund' in r['payload']}")
        dry_run_report(LANE_ID, {"universe": len(universe), "sources": sources, "due": len(due), "fresh": fresh,
                                 "would_fetch": len(capped), "over_cap": over_cap,
                                 "probe": {r["symbol"]: r["status"] for r in rows}, "probe_skipped": skipped},
                       would_write=["table yfinance_info_snapshot", f"data/runtime/{LANE_ID}_last.json"])
        return 0
    rows, skipped = fetch_many(capped, fetch, sleep_s=args.sleep, now_fn=now_fn, sleep_fn=sleep_fn)
    if over_cap:
        skipped["over_run_cap"] = over_cap
    if fresh:
        skipped["fresh"] = fresh
    if capped and not rows:
        return fail("dependency_unavailable", f"provider: every fetch throttled or failed ({skipped})")
    from lib.writers.yfinance_info_snapshot_writer import write_info_snapshots

    try:
        rec = write_info_snapshots(conn, rows, run_id=os.environ.get("TRADEAI_RUN_ID"))
        conn.commit()
    except Exception as exc:  # noqa: BLE001
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass
        return fail("dependency_unavailable", f"write: {type(exc).__name__}")
    ok_rows = sum(1 for r in rows if r["status"] == "ok")
    rejected = len(rows) - int(getattr(rec, "rows_accepted", len(rows)))
    if rejected:
        skipped["rejected"] = rejected
    produced = int(getattr(rec, "rows_accepted", len(rows)))
    target = receipt_path(LANE_ID)
    write_lane_receipt(
        LANE_ID, ok=True, exit_code=0, started_at=started, script=SCRIPT,
        summary={"universe": len(universe), "sources": sources, "due": len(due), "fetched": len(rows),
                 "ok_rows": ok_rows, "fresh": fresh},
        output={"produced_count": produced, "attempted_count": len(capped), "skipped_reasons": skipped,
                "empty_reason": None if produced else "nothing_due",
                "output_evidence": [{"kind": "store_rows", "ref": "yfinance_info_snapshot",
                                     "fetched_at": now.isoformat()}]},
    )
    print(f"[{LANE_ID}] wrote {produced} snapshot rows ({ok_rows} ok); receipt {target}")
    return 0


def parse(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], allow_abbrev=False)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="default: read, probe a few symbols, write nothing")
    mode.add_argument("--apply", action="store_true", help="fetch what is due and write rows + receipt")
    ap.add_argument("--ok-hours", type=float, default=DEFAULTS["ok_hours"])
    ap.add_argument("--negative-hours", type=float, default=DEFAULTS["negative_hours"])
    ap.add_argument("--max-symbols", type=int, default=DEFAULTS["max_symbols"])
    ap.add_argument("--sleep", type=float, default=DEFAULTS["sleep"])
    ap.add_argument("--probe", type=int, default=DEFAULTS["probe"])
    a = ap.parse_args(argv)
    if not (1 <= a.max_symbols <= 2000 and 0.25 <= a.sleep <= 30 and 0 <= a.probe <= 10
            and 1 <= a.ok_hours <= 24 * 30 and 1 <= a.negative_hours <= 24 * 90):
        ap.error("out of range: --max-symbols 1..2000, --sleep 0.25..30, --probe 0..10, --ok-hours 1..720, "
                 "--negative-hours 1..2160")
    return a


def main(argv: Optional[Sequence[str]] = None) -> int:
    a = parse(argv)  # argparse exits 2 on a bad argument
    return run(apply=bool(a.apply), state=state_root(), connect=pg_connect, fetch=yfinance_fetch, args=a)


if __name__ == "__main__":
    raise SystemExit(main())
