#!/usr/bin/env python3
"""LQ-20261107-1253 — build the "Since last close" home-card snapshot (scheduled by n8n, never by crontab).

Dry-run by default: reads the quote snapshot and news (read-only SELECT), builds the card, prints a digest, writes
nothing and makes no LLM call.  ``--apply`` writes ``since_close_latest.json`` atomically; ``--llm`` additionally
permits ONE governed DeepSeek flash call for the summary (cached 15 min, daily cap), which needs ``--apply`` so a
spend always leaves a durable artifact.  Exit 0 means a snapshot was built (and written under --apply); a missing
quote snapshot exits 2 with nothing written.

n8n lane spec: see the LQ-1253 DONE note — hourly 17:00-04:00 ET plus 05:30 ET (must finish by 05:50), weekends
every 2 h:   python3 scripts/since_close_snapshot.py --apply --llm
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import since_close_card as card  # noqa: E402
from lib import since_close_stamp as stamp  # noqa: E402

ET = ZoneInfo("America/New_York")
STATE_DIR = Path(os.environ.get("TRADEAI_STATE_DIR") or Path(__file__).resolve().parent.parent / "data" / "portfolios" / "state")
OUT_NAME = "since_close_latest.json"
CIO_BRIEF_REL = Path("data") / "runtime" / "cio_overnight_brief" / "latest.json"  # LQ-1257 (cc-deepseek-3); pending until it exists
MARKET_RISK_REL = Path("data") / "runtime" / "market_risk" / "latest.json"
TICKER_NAME = "ticker_snapshot_latest.json"
FUTURES_REL = Path("data") / "market" / "futures_overseas_latest.json"  # cc-deepseek-9 LQ-1239 output, when it lands


def _flash(prompt: str) -> str:
    """One governed DeepSeek flash call; raises on failure so the card falls back to the deterministic list."""
    from lib.deepseek_client import chat
    from lib.provider_cost.context import cost_attribution

    attr = {"source_service": "since_close_card", "source_process": "since_close_card", "source_lane": "FAST"}
    with cost_attribution(**attr):
        resp = chat(policy="FAST", prompt=prompt, timeout=45.0, max_tokens=450, thinking="disabled", response_json=False, **attr)
    if not resp.ok or not resp.content:
        raise RuntimeError(resp.error_message or "no content")
    return resp.content


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="write the snapshot (default: dry run)")
    ap.add_argument("--llm", action="store_true", help="allow the flash summary call (needs --apply)")
    ap.add_argument("--state-dir", type=Path, default=STATE_DIR)
    ap.add_argument("--futures", type=Path, default=None, help="futures/overseas quotes JSON (default: the LQ-1239 path)")
    ap.add_argument("--if-changed", action="store_true", help="rebuild only on new held-name news, a held +/-3%% cross, or a new held/watch extended print; else exit 0 untouched")
    ap.add_argument("--cio-brief", type=Path, default=None, help="LQ-1257 CIO brief JSON (default: <state root>/data/runtime/cio_overnight_brief/latest.json)")
    ap.add_argument("--now", default=None, help="ISO instant, for replay (default: the clock)")
    ap.add_argument("--labels", type=Path, default=None,
                    help="futures/cash-index display names (default: config/market_risk_offhours_quotes.yaml schwab.labels)")
    a = ap.parse_args(argv)
    if a.llm and not a.apply:
        print("refused: --llm needs --apply (a spend must leave a durable artifact)", file=sys.stderr)
        return 2

    now = datetime.fromisoformat(a.now) if a.now else datetime.now(ET)
    if now.tzinfo is None:
        now = now.replace(tzinfo=ET)
    ticker = card.load_json(a.state_dir / TICKER_NAME)
    if not ticker or not ticker.get("tickers"):
        print(f"no quote snapshot at {a.state_dir / TICKER_NAME}; nothing built", file=sys.stderr)
        return 2
    out_path = a.state_dir / OUT_NAME
    prior = card.load_json(out_path)
    futures = card.load_json(a.futures or (a.state_dir.parents[2] / FUTURES_REL))

    from lib.cio_market_context_state import connect_trade_ai_readonly

    from lib.macro_calendar import default_path as _macro_path

    win = card.window(now)
    conn = connect_trade_ai_readonly()
    try:
        arts = card.fetch_articles(
            conn,
            since=datetime.fromisoformat(win["start"].replace("Z", "+00:00")),
            until=now,
            symbols=list(ticker["tickers"]),
        )
        clocks = stamp.fetch_clocks(conn)
        try:
            ex_divs = card.fetch_ex_divs(conn, today=now)
        except Exception:  # noqa: BLE001 -- a missing dividend table leaves the strip without ex-div rows, not the card
            ex_divs = []
        try:
            # LQ-20261107-1282: what printed after the close -- the weekend/overnight/pre-market answer. A store that
            # cannot be read leaves the chips on Friday's numbers with "no print since Fri", never a blank card.
            ext = card.fetch_extended(
                conn, symbols=list(ticker["tickers"]), since=datetime.fromisoformat(win["start"].replace("Z", "+00:00"))
            )
        except Exception:  # noqa: BLE001 -- the card degrades to the close, it does not fail to build
            ext = []
    finally:
        conn.close()

    clocks["market_risk"] = stamp.file_clock(a.state_dir.parents[2] / MARKET_RISK_REL)
    today = now.astimezone(ET).date().isoformat()
    calls = ((prior or {}).get("llm_calls") or {}).get(today, 0)
    snap = card.build_snapshot(
        now=now, ticker_snapshot=ticker, articles=arts, futures=futures,
        llm=_flash if (a.apply and a.llm) else None, prior=prior, calls_today=calls,
        macro_calendar=card.load_json(_macro_path()), earnings=card.load_json(a.state_dir / "earnings_dates.json"),
        ex_divs=ex_divs, if_changed=a.if_changed, source_clocks=clocks, cio_brief=card.load_json(a.cio_brief or (a.state_dir.parents[2] / CIO_BRIEF_REL)),
        extended_rows=ext, index_labels=card.load_labels(a.labels),
    )
    if snap is None:
        print(f"unchanged since the last build (window={win['label']!r}, articles={len(arts)}); no write, no LLM call")
        return 0
    if snap["summary"].get("llm_called"):
        calls += 1
    snap["llm_calls"] = {today: calls}

    s = snap["summary"]
    print(
        f"window={win['label']!r} moves={len(snap['moves'])} held={sum(m['held'] for m in snap['moves'])} "
        f"articles={len(arts)} macro={len(snap['macro']['headlines'])} futures={snap['macro']['futures']['status']} "
        f"feed={len(snap['feed'])} week_ahead={len(snap['week_ahead']['events'])} cio_brief={snap['cio_brief']['status']} "
        f"today={'yes' if snap['today'] else 'no'} updated={(snap['updated'] or {}).get('reason')!r} summary={s['source']}{'/' + s['reason'] if s.get('reason') else ''} llm_calls_today={calls}"
    )
    prints = [m["symbol"] for m in snap["moves"] if (m.get("extended") or {}).get("state") == "print"]
    print(
        f"prints_since_close={len(prints)}{' ' + ','.join(prints[:8]) if prints else ''} "
        f"market_now={(snap.get('macro') or {}).get('now', {}).get('status')} "
        f"futures={len((snap.get('macro') or {}).get('now', {}).get('futures') or [])} "
        f"indices={len((snap.get('macro') or {}).get('now', {}).get('indices') or [])} "
        f"feed_top={(snap['feed'][0]['holdings'][0]['symbol'] if snap['feed'] and snap['feed'][0].get('holdings') else '-')}"
        f"{(' ' + str(snap['feed'][0].get('score'))) if snap['feed'] else ''}"
    )
    if not a.apply:
        print("DRY RUN: nothing written, no LLM call. Re-run with --apply [--llm].")
        return 0
    fd, tmp = tempfile.mkstemp(dir=out_path.parent, prefix=".since_close.", suffix=".tmp")
    with os.fdopen(fd, "w") as fh:
        json.dump(snap, fh, indent=1, default=str)
    os.replace(tmp, out_path)
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
