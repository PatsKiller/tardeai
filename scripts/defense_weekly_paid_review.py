#!/usr/bin/env python3
"""Friday week-final oversight.

Auto (crontab, no flags): ChatGPT OAuth via llm_lane — $0, never Anthropic.
Paid Claude (or other metered seat): operator-only, requires --apply-paid.

The filename is historical (crontab pins it). Cron must never pass --apply-paid.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Friday oversight: ChatGPT OAuth auto; paid Claude only with --apply-paid.")
    ap.add_argument(
        "--apply-paid", action="store_true",
        help="Spend a metered paid seat (default seat=paid / Claude). Operator approval. Cron must NOT pass this.")
    ap.add_argument(
        "--seat", default="paid",
        help="Paid seat name when --apply-paid (paid / paid_gpt / paid_xai / paid_ds). Ignored on auto.")
    ap.add_argument(
        "--force", action="store_true",
        help="Accepted for compatibility. Friday auto always bypasses the free-seat build_hash cache.")
    ap.add_argument(
        "--dry-run", action="store_true",
        help="Print the intended path and exit 0. No DB, no LLM, no Telegram.")
    return ap.parse_args(argv)


def _cfg() -> dict:
    return json.loads((ROOT / "config" / "defense_recommendations.json").read_text())


def intended_mode(args, cfg=None) -> str:
    """paid | auto_chatgpt | skip. Paid is ONLY --apply-paid — config cannot auto-spend."""
    cfg = cfg or _cfg()
    if args.apply_paid:
        return "paid"
    free = cfg.get("oversight_free") or {}
    if free.get("weekly_auto_review", True) is False:
        return "skip"
    return "auto_chatgpt"


def auto_seat(cfg=None) -> str:
    free = (cfg or _cfg()).get("oversight_free") or {}
    seat = str(free.get("weekly_auto_seat") or "chatgpt").strip().lower()
    return seat or "chatgpt"


def _telegram(send_telegram, text: str) -> None:
    try:
        send_telegram(text, bypass_router=True)
    except TypeError:
        send_telegram(text)
    except Exception as e:
        print(f"[weekly-oversight] telegram failed: {e}")


def main(argv=None, *, do=None, get_conn=None, send_telegram=None) -> int:
    args = parse_args(argv)
    cfg = _cfg()
    mode = intended_mode(args, cfg)
    seat_auto = auto_seat(cfg)

    if args.dry_run:
        print(f"[weekly-oversight] dry-run mode={mode} apply_paid={bool(args.apply_paid)} "
              f"auto_seat={seat_auto} paid_seat={args.seat}")
        return 0

    if mode == "skip":
        print("[weekly-oversight] weekly_auto_review OFF — skipping")
        return 0

    if do is None:
        import defense_oversight as do  # type: ignore
    if get_conn is None:
        from db_adapter import _get_conn as get_conn  # type: ignore
    if send_telegram is None:
        try:
            from telegram_alert import send_telegram as send_telegram  # type: ignore
        except Exception:
            send_telegram = None

    conn = get_conn()
    try:
        if mode == "paid":
            # Explicit operator flag. Config weekly_paid_review is NOT a cron auto-gate
            # (old script treated it as one — that spent $0.396 Claude 2026-08-21).
            res = do.run_paid_review(conn.cursor(), seats=[args.seat])
            if hasattr(conn, "commit"):
                conn.commit()
            print(f"[weekly-paid] {res}")
            if send_telegram:
                r = (res.get("results") or {}).get(args.seat, {})
                _telegram(
                    send_telegram,
                    f"[OPERATIONAL] Weekly paid oversight ({r.get('model')}): {r.get('status')} "
                    f"· ${res.get('spent_usd', 0)} — memo on the Defense page "
                    f"(manual --apply-paid)",
                )
            return 0 if res.get("ok") else 1

        # Week-final snapshot: bypass mid-week build_hash cache. Quota still applies.
        res = do.run_free_critiques(conn.cursor(), force=True, seats=[seat_auto])
        if hasattr(conn, "commit"):
            conn.commit()
        print(f"[weekly-oversight] auto oauth {seat_auto}: {res}")
        if send_telegram:
            st = (res.get("seats") or {}).get(seat_auto, "unknown")
            _telegram(
                send_telegram,
                f"[OPERATIONAL] Weekly oversight ({seat_auto} oauth): {st} "
                f"· $0 — memo on the Defense page",
            )
        return 0
    finally:
        close = getattr(conn, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
