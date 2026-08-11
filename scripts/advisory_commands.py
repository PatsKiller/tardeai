#!/usr/bin/env python3
"""advisory_commands.py — Deterministic /advisory Telegram/CLI commands.

Zero model calls. Phase 3B feedback + history inspection.

Usage:
  python scripts/advisory_commands.py help
  python scripts/advisory_commands.py rate <row_id|SYMBOL> notuseful DISAGREE_THESIS [note...]
  python scripts/advisory_commands.py rate <row_id|SYMBOL> useful
  python scripts/advisory_commands.py ack <row_id|SYMBOL>
  python scripts/advisory_commands.py snooze <row_id|SYMBOL>
  python scripts/advisory_commands.py history <SYMBOL> [account]
  python scripts/advisory_commands.py calibration
  python scripts/advisory_commands.py score-outcomes [--max N]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.advisory.advisory_memory import (  # noqa: E402
    REASON_CODES,
    load_calibration,
    load_feedback_for_symbol,
    load_prior_for_row,
    record_feedback,
    score_pending_outcomes,
    _history_for_key,
    row_key,
)


def cmd_help(_: argparse.Namespace) -> str:
    codes = ", ".join(sorted(REASON_CODES - {"USEFUL"}))
    return f"""/advisory commands (READ_ONLY_ADVISORY):
  /advisory help
  /advisory rate <row_id|SYMBOL> useful
  /advisory rate <row_id|SYMBOL> notuseful <REASON_CODE> [note...]
      REASON_CODE: {codes}
  /advisory ack <row_id|SYMBOL>
  /advisory snooze <row_id|SYMBOL>
  /advisory history <SYMBOL> [account]
  /advisory calibration
  /advisory score-outcomes

Examples:
  /advisory rate SPCX:schwab_taxable|2026-08-11|abc123 notuseful DISAGREE_THESIS held through
  /advisory rate SCHD useful
"""


def _parse_target(target: str) -> tuple[str, str, str]:
    """Return (row_id, symbol, account)."""
    target = (target or "").strip()
    if "|" in target:
        head = target.split("|", 1)[0]
        if ":" in head:
            sym, acct = head.split(":", 1)
        else:
            sym, acct = head, ""
        return target, sym.upper(), acct
    if ":" in target and not target.replace(":", "").isalnum():
        # SYMBOL:account without date
        sym, acct = target.split(":", 1)
        return "", sym.upper(), acct
    return "", target.upper(), ""


def cmd_rate(args: argparse.Namespace) -> str:
    row_id, sym, acct = _parse_target(args.target)
    rating = (args.rating or "").lower()
    code = (args.reason_code or "").upper()
    note = " ".join(args.note or []).strip()
    try:
        entry = record_feedback(
            row_id=row_id,
            symbol=sym,
            account=acct,
            rating=rating,
            reason_code=code,
            note=note,
        )
    except ValueError as e:
        return f"❌ {e}"
    return (
        f"✅ Feedback stored: {entry['symbol']} {entry['rating']}"
        + (f"/{entry['reason_code']}" if entry.get("reason_code") else "")
        + (f" — {entry['note']}" if entry.get("note") else "")
    )


def cmd_ack(args: argparse.Namespace) -> str:
    row_id, sym, acct = _parse_target(args.target)
    entry = record_feedback(row_id=row_id, symbol=sym, account=acct, rating="ack")
    return f"✅ Ack {entry['symbol']}"


def cmd_snooze(args: argparse.Namespace) -> str:
    row_id, sym, acct = _parse_target(args.target)
    entry = record_feedback(row_id=row_id, symbol=sym, account=acct, rating="snooze")
    return f"✅ Snoozed {entry['symbol']}"


def cmd_history(args: argparse.Namespace) -> str:
    sym = (args.symbol or "").upper()
    acct = args.account or ""
    prior = load_prior_for_row(sym, acct)
    hist = _history_for_key(row_key(sym, acct))[-8:]
    fb = load_feedback_for_symbol(sym, acct, limit=5)
    lines = [
        f"History {row_key(sym, acct)}:",
        f"  prior={prior.get('prior_verdict')}@{prior.get('prior_conviction')} "
        f"on {prior.get('prior_date')} flips90d={prior.get('verdict_changes_90d')} "
        f"thrash_pen={prior.get('thrash_penalty')}",
    ]
    for e in hist:
        lines.append(
            f"  {(e.get('ts') or '')[:10]} {e.get('verdict')} "
            f"conv={e.get('conviction')} mv={e.get('market_value')}"
        )
    if fb:
        lines.append("Feedback:")
        for e in fb:
            lines.append(
                f"  {(e.get('ts') or '')[:10]} {e.get('rating')}/{e.get('reason_code')} "
                f"{(e.get('note') or '')[:60]}"
            )
    return "\n".join(lines)


def cmd_calibration(_: argparse.Namespace) -> str:
    cal = load_calibration()
    g = cal.get("global") or {}
    lines = [
        f"Calibration n={g.get('n')} hit_rate={g.get('hit_rate')}",
        f"rebuilt_at={cal.get('rebuilt_at')}",
    ]
    for v, st in sorted((cal.get("by_verdict") or {}).items()):
        lines.append(f"  {v}: n={st.get('n')} hit={st.get('hit_rate')}")
    return "\n".join(lines)


def cmd_score(args: argparse.Namespace) -> str:
    r = score_pending_outcomes(max_new=int(args.max or 200))
    return json.dumps(r, indent=2, default=str)


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        print(cmd_help(argparse.Namespace()))
        return 0

    p = argparse.ArgumentParser(prog="advisory_commands", add_help=False)
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("help")
    pr = sub.add_parser("rate")
    pr.add_argument("target")
    pr.add_argument("rating", choices=["useful", "notuseful"])
    pr.add_argument("reason_code", nargs="?", default="")
    pr.add_argument("note", nargs="*", default=[])

    for name in ("ack", "snooze"):
        px = sub.add_parser(name)
        px.add_argument("target")

    ph = sub.add_parser("history")
    ph.add_argument("symbol")
    ph.add_argument("account", nargs="?", default="")

    sub.add_parser("calibration")
    ps = sub.add_parser("score-outcomes")
    ps.add_argument("--max", type=int, default=200)

    # Allow telegram-style: rate SYM notuseful CODE note...
    args = p.parse_args(argv)
    if not args.cmd or args.cmd == "help":
        print(cmd_help(args))
        return 0
    handlers = {
        "rate": cmd_rate,
        "ack": cmd_ack,
        "snooze": cmd_snooze,
        "history": cmd_history,
        "calibration": cmd_calibration,
        "score-outcomes": cmd_score,
    }
    print(handlers[args.cmd](args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
