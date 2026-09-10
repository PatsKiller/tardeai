#!/usr/bin/env python3
"""Read-only Flash CIO soak observer.

Counts organic CIO dual_consensus rows where deepseek_status==VOTED and
participating_lanes contains deepseek-flash. Does not mutate brokers/orders.

Hermetic:  --json-in PATH
Live DB:   DB_* env (same pattern as other read-only scripts)

Authority: READ_ONLY_ADVISORY. MBI_BEHAVIOR=0.
On-demand Hermes challengers are never counted toward OBSERVED.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

SCHEMA = "FlashCioSoakObserve@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
MBI_BEHAVIOR = 0
NOT_COUNTED = ["on_demand_challengers"]
FLASH_LANE = "deepseek-flash"

NO_CONSUMER_REASON = (
    "FlashCioSoakObserve@v1 is a read-only CLI evidence emitter for campaign/operator "
    "soak adjudication; no runtime importer yet — campaign evidence/ files are the "
    "consumer surface (MBI_BEHAVIOR=0)."
)


def _parse_ts(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        dt = raw
    else:
        s = str(raw).strip()
        if not s:
            return None
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _as_dc(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            obj = json.loads(raw)
        except ValueError:
            return {}
        return obj if isinstance(obj, dict) else {}
    return {}


def _is_flash_voted(dc: dict[str, Any]) -> bool:
    if str(dc.get("deepseek_status") or "") != "VOTED":
        return False
    lanes = dc.get("participating_lanes") or []
    if not isinstance(lanes, (list, tuple)):
        return False
    return FLASH_LANE in {str(x) for x in lanes}


def _load_held_symbols(root: Path | None = None) -> set[str]:
    root = root or REPO
    try:
        from scripts.lib.symbol_universe import _held_symbols
    except Exception:
        return set()
    try:
        return set(_held_symbols(root).keys())
    except Exception:
        return set()


def _normalize_json_in(payload: Any) -> tuple[list[dict[str, Any]], set[str] | None]:
    held: set[str] | None = None
    rows: list[dict[str, Any]]
    if isinstance(payload, dict):
        raw_rows = payload.get("rows") or payload.get("items") or []
        hs = payload.get("held_symbols")
        if isinstance(hs, list):
            held = {str(s).upper() for s in hs if str(s).strip()}
        rows = list(raw_rows) if isinstance(raw_rows, list) else []
    elif isinstance(payload, list):
        rows = list(payload)
    else:
        rows = []
    out: list[dict[str, Any]] = []
    for r in rows:
        if isinstance(r, dict):
            out.append(r)
    return out, held


def _fetch_db_rows(*, window_days: int) -> list[dict[str, Any]]:
    import psycopg2
    import psycopg2.extras

    host = os.environ.get("DB_HOST")
    if not host:
        raise RuntimeError("DB_HOST unset (pass --json-in for hermetic mode)")
    conn = psycopg2.connect(
        host=host,
        port=os.environ.get("DB_PORT") or 5432,
        dbname=os.environ.get("DB_NAME"),
        user=os.environ.get("DB_USER"),
        password=os.environ.get("DB_PASSWORD"),
        connect_timeout=8,
    )
    conn.set_session(readonly=True, autocommit=True)
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT symbol, dual_consensus_json, updated_at
              FROM watchlist_final_synthesis
             WHERE dual_consensus_json IS NOT NULL
               AND updated_at >= (now() AT TIME ZONE 'utc') - (%s::text || ' days')::interval
            """,
            (int(window_days),),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def observe_flash_cio_soak(
    rows: Iterable[dict[str, Any]],
    *,
    window_days: int = 7,
    min_n: int = 5,
    held_only: bool = False,
    held_symbols: set[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Pure observer over dual_consensus rows. No I/O."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max(0, int(window_days)))
    held = {s.upper() for s in (held_symbols or set())}
    symbols: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or "").strip().upper()
        if not sym:
            continue
        ts = _parse_ts(row.get("updated_at") or row.get("produced_at") or row.get("as_of"))
        if ts is not None and ts < cutoff:
            continue
        if held_only:
            if "held" in row:
                if not bool(row.get("held")):
                    continue
            elif held_symbols is not None:
                if sym not in held:
                    continue
            else:
                # Cannot prove held without per-row flag or held_symbols set.
                continue
        dc = _as_dc(row.get("dual_consensus_json") or row.get("dual_consensus") or row)
        if not _is_flash_voted(dc):
            continue
        if sym not in symbols:
            symbols.append(sym)
    symbols.sort()
    n = len(symbols)
    claim = "OBSERVED" if n >= int(min_n) else "PENDING"
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "mbi_behavior": MBI_BEHAVIOR,
        "flash_voted_n": n,
        "symbols": symbols,
        "window": {
            "days": int(window_days),
            "cutoff_utc": cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "as_of_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "min_n": int(min_n),
        "held_only": bool(held_only),
        "claim": claim,
        "not_counted": list(NOT_COUNTED),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--window-days", type=int, default=7)
    ap.add_argument("--min-n", type=int, default=5)
    ap.add_argument("--held-only", action="store_true")
    ap.add_argument("--json-in", type=Path, default=None, help="Hermetic fixture JSON (no live DB)")
    ap.add_argument("--out", type=Path, default=None, help="Optional output path")
    ap.add_argument("--root", type=Path, default=REPO, help="Repo root for holdings.json (held-only)")
    args = ap.parse_args(argv)

    held_symbols: set[str] | None = None
    if args.json_in is not None:
        payload = json.loads(Path(args.json_in).read_text(encoding="utf-8"))
        rows, held_from_file = _normalize_json_in(payload)
        held_symbols = held_from_file
        if args.held_only and held_symbols is None:
            held_symbols = _load_held_symbols(Path(args.root))
    else:
        rows = _fetch_db_rows(window_days=int(args.window_days))
        if args.held_only:
            held_symbols = _load_held_symbols(Path(args.root))

    report = observe_flash_cio_soak(
        rows,
        window_days=int(args.window_days),
        min_n=int(args.min_n),
        held_only=bool(args.held_only),
        held_symbols=held_symbols,
    )
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
