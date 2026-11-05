#!/usr/bin/env python3
"""List — and with --apply archive — delisted names in the operator's My Watchlist.

Operator 2026-10-26 (verbatim): "remove SRNE and any delisted". Dry run is the default: it reads My Watchlist
(data_broker.watch_domains.membership_operator), checks each name with lib/delisted_symbols (explicit list, house
delisted flag / identity listing status, no house close for N sessions, near-zero or terminal last close; thresholds
in config/delisted_symbols.json) and prints what it would archive. It writes nothing.

    python3 scripts/watch_archive_delisted.py                       # dry run (default): list, write nothing
    python3 scripts/watch_archive_delisted.py --apply               # archive every listed name
    python3 scripts/watch_archive_delisted.py --apply --symbols SRNE
    python3 scripts/watch_archive_delisted.py --undo <receipt.json> # restore exactly what a receipt archived

Archive = the existing My Watchlist "remove" command (api_v3_watch_commands.post_mine_decision, action remove,
star_write=False): one ``watch_mine_removed`` row in watchlist_events (which hides the name from My Watchlist) and
the operator's active ticker directives for the symbol set to status ``archived`` through the governed
watch_directives writer. The star row is KEPT and nothing is deleted. Each --apply writes a receipt
(data/runtime/watch_archive_delisted/<stamp>.json) naming every directive it archived; --undo replays it in
reverse (a ``watch_mine_added`` event, directives back to ``active``).

READ_ONLY_ADVISORY toward money: watching only, MBI_BEHAVIOR = 0 — no order, size, stop or broker call. Price rows
are never touched (the quarantine script owns bad bars).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import delisted_symbols as ds  # noqa: E402

ACTOR = "watch_archive_delisted"
SURFACE = "delisted_archive"
RECEIPT_SCHEMA = "WatchDelistedArchiveReceipt@v1"


def _state_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    from scripts.lib.persistent_state_root import good_persistent_root  # noqa: PLC0415
    return Path(good_persistent_root())


def _db() -> tuple[Callable, Callable]:
    """(db_query(sql, params=None, fetch='all'), db_execute(sql, params=None)) on the production DB."""
    from db_adapter import _execute, _get_conn  # type: ignore  # noqa: PLC0415

    def db_query(sql, params=None, fetch="all"):
        return _execute(sql, params, fetch=fetch)

    conn = _get_conn()

    def db_execute(sql, params=None):
        cur = conn.cursor()
        cur.execute(sql, params or ())
        conn.commit()

    return db_query, db_execute


def _wd():
    try:
        from scripts.lib.data_broker import watch_domains  # noqa: PLC0415
    except ImportError:  # pragma: no cover
        from lib.data_broker import watch_domains  # type: ignore  # noqa: PLC0415
    return watch_domains


def plan(*, db_query: Callable, state_root: Path, cfg: dict | None = None, symbols: list[str] | None = None,
         today=None, flags: dict | None = None) -> dict:
    """{watch: n, delisted: [{symbol, code, reason, starred, reasons}], errors}. Reads only."""
    cfg = cfg if cfg is not None else ds.load_config()
    mem = _wd().membership_operator(lambda sql, params=None: db_query(sql, params, fetch="all"))
    names = mem.get("names") or {}
    wanted = {ds.norm(s) for s in symbols or [] if ds.norm(s)}
    pool = sorted(s for s in names if not wanted or s in wanted)
    from scripts.lib.data_broker import daily_bars  # noqa: PLC0415
    lookback = int(cfg["no_price_sessions"]) * 2 + int((cfg.get("terminal_collapse") or {}).get("prior_sessions", 0)) + 30

    def bars_fn(sym: str) -> list:
        out = daily_bars.get_daily_bars(db_query, sym, days=lookback)
        if out.get("ok") is False and out.get("error"):
            raise RuntimeError(str(out.get("error"))[:120])
        return out.get("bars") or []

    flags = flags if flags is not None else ds.load_house_flags(state_root)
    res = ds.detect(pool, bars_fn=bars_fn, flags=flags, cfg=cfg, today=today)
    rows = []
    for sym, v in sorted(res["excluded"].items()):
        ent = names.get(sym) or {}
        rows.append({"symbol": sym, "code": v["code"], "reason": v["reason"], "starred": bool(ent.get("starred")),
                     "watch_reasons": [r.get("kind") for r in ent.get("reasons") or []]})
    return {"watch": len(names), "checked": res["checked"], "reference_date": res.get("reference_date"),
            "delisted": rows, "errors": res["errors"],
            "membership_sources": mem.get("sources")}


def archive(rows: list[dict], *, db_query: Callable, db_execute: Callable, command: Callable | None = None) -> list[dict]:
    if command is None:
        from scripts.api_v3_watch_commands import post_mine_decision as command  # noqa: PLC0415
    out = []
    for row in rows:
        note = f"{ds.LABEL}: {row['code']} — {row['reason']}"[:300]
        res = command({"symbol": row["symbol"], "action": "remove", "note": note, "surface": SURFACE},
                      db_execute=db_execute, db_query=db_query, by=ACTOR, star_write=False)
        out.append({"symbol": row["symbol"], "ok": bool(res.get("ok")), "event_type": res.get("event_type"),
                    "archived_directives": res.get("archived_directives") or [], "error": res.get("error"),
                    "code": row["code"], "reason": row["reason"]})
    return out


def undo(receipt: dict, *, db_query: Callable, db_execute: Callable, command: Callable | None = None,
         set_status: Callable | None = None) -> list[dict]:
    if receipt.get("schema") != RECEIPT_SCHEMA:
        raise ValueError(f"not a {RECEIPT_SCHEMA} receipt")
    if command is None:
        from scripts.api_v3_watch_commands import post_mine_decision as command  # noqa: PLC0415
    if set_status is None:
        from scripts.lib.writers.watch_directives_writer import set_watch_directive_status as set_status  # noqa: PLC0415
    out = []
    for row in receipt.get("archived") or []:
        if not row.get("ok"):
            continue
        restored = []
        for did in row.get("archived_directives") or []:
            set_status(db_query, did, "active", source=f"{ACTOR}_undo")
            restored.append(did)
        res = command({"symbol": row["symbol"], "action": "add", "note": "undo delisted archive", "surface": SURFACE},
                      db_execute=db_execute, db_query=db_query, by=ACTOR, star_write=False)
        out.append({"symbol": row["symbol"], "ok": bool(res.get("ok")), "restored_directives": restored,
                    "error": res.get("error")})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="List (dry run, default) or archive delisted names in My Watchlist.")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="default: list, write nothing")
    mode.add_argument("--apply", action="store_true", help="archive the listed names (reversible; nothing deleted)")
    mode.add_argument("--undo", metavar="RECEIPT", help="restore what an --apply receipt archived")
    ap.add_argument("--symbols", default="", help="comma-separated: only these Watch names")
    ap.add_argument("--state-root", default=None, help="persistent-state root (default: resolved production root)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    root = _state_root(args.state_root)
    db_query, db_execute = _db()
    if args.undo:
        receipt = json.loads(Path(args.undo).read_text(encoding="utf-8"))
        res = undo(receipt, db_query=db_query, db_execute=db_execute)
        print(json.dumps({"mode": "undo", "receipt": args.undo, "restored": res}, indent=2, default=str))
        return 0 if all(r["ok"] for r in res) else 1
    p = plan(db_query=db_query, state_root=root, symbols=[s for s in args.symbols.split(",") if s.strip()])
    if not args.apply:
        out = {"mode": "dry_run", "writes": "none", **p}
        if args.json:
            print(json.dumps(out, indent=2, default=str))
        else:
            print(f"My Watchlist: {p['watch']} names, checked {p['checked']}, delisted {len(p['delisted'])}")
            for r in p["delisted"]:
                print(f"  {r['symbol']:<8} {r['code']:<10} {r['reason']}")
            for s, e in sorted(p["errors"].items()):
                print(f"  {s:<8} READ ERROR {e} (not archived)")
            print("dry run: nothing written. Archive with --apply (reversible with --undo <receipt>).")
        return 0
    archived = archive(p["delisted"], db_query=db_query, db_execute=db_execute)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {"schema": RECEIPT_SCHEMA, "written_at": datetime.now(timezone.utc).isoformat(), "actor": ACTOR,
               "archived": archived, "undo": "python3 scripts/watch_archive_delisted.py --undo <this file>"}
    path = root / "data/runtime/watch_archive_delisted" / f"{stamp}.json"
    from scripts.lib.atomic_json_store import atomic_write_json  # noqa: PLC0415
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, receipt)
    print(json.dumps({"mode": "apply", "receipt": str(path), "archived": archived}, indent=2, default=str))
    return 0 if all(r["ok"] for r in archived) else 1


if __name__ == "__main__":
    raise SystemExit(main())
