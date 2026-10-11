#!/usr/bin/env python3
"""Executor CLI for lane analyst-prospectus-generate (Wave C).

Ad-hoc prospectus generation (single / batch_holdings / batch_watchlist).
Does NOT overload generate-analyst-daily-digest.

Request payload (written by the API before host_run_request):
  data/runtime/n8n_cc_wave_c/requests/analyst-prospectus-generate.json

Usage:
  $PY scripts/analyst_prospectus_generate.py --dry-run
  $PY scripts/analyst_prospectus_generate.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _run_generate(q: dict) -> dict:
    import reporting_engine as _re

    mode = (q.get("mode") or "single").lower()
    if mode == "batch_holdings":
        stale_raw = q.get("stale_days")
        stale_days = int(stale_raw) if stale_raw not in (None, "", 0, "0") else None
        return _re.generate_holding_prospectus_batch(
            force=bool(q.get("force")),
            grok_edit=bool(q.get("grok_edit", True)),
            limit=int(q.get("limit", 40) or 40),
            stale_days=stale_days,
            generation_mode=str(q.get("generation_mode") or "batch"),
            oversight=bool(q.get("oversight", True)),
        )
    if mode == "batch_watchlist":
        return _re.generate_watchlist_prospectus_batch(
            force=bool(q.get("force")),
            grok_edit=bool(q.get("grok_edit", True)),
            limit=int(q.get("limit", 200) or 200),
            generation_mode=str(q.get("generation_mode") or "batch_watchlist"),
            oversight=bool(q.get("oversight", True)),
        )
    out = _re.generate_report(
        report_type=q.get("type") or q.get("report_type") or "symbol_holding",
        symbol=(q.get("symbol") or "").strip().upper() or None,
        sector=(q.get("sector") or "").strip() or None,
        topic=(q.get("topic") or "").strip() or None,
        grok_edit=bool(q.get("grok_edit", True)),
        oversight=bool(q.get("oversight", True)),
        formats=["docx", "pdf"]
        if str(q.get("format", "all")).lower() == "all"
        else [str(q.get("format", "docx")).lower()],
        generation_mode=str(q.get("generation_mode") or "api_generate"),
    )
    if out.get("blocked"):
        return {
            "ok": False,
            "blocked": True,
            "block_reason": out.get("block_reason"),
            "error": "; ".join(out.get("exports", {}).get("blocked_detail") or [])
            or "Publication blocked by catalyst gate",
            "report": out.get("report"),
            "exports": out.get("exports"),
        }
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Ad-hoc analyst prospectus generate (Wave C)")
    ap.add_argument("--dry-run", action="store_true", help="validate request payload; do not call reporting_engine")
    args = ap.parse_args(argv)

    from lib.n8n_cc_wave_c import LANE_ANALYST, read_request_payload, write_lane_receipt

    q = read_request_payload(LANE_ANALYST)
    mode = "dry_run" if args.dry_run else "live"
    if args.dry_run:
        detail = {
            "would": {
                "mode": (q.get("mode") or "single"),
                "symbol": q.get("symbol"),
                "keys": sorted(q.keys()),
            }
        }
        write_lane_receipt(LANE_ANALYST, ok=True, mode=mode, detail=detail)
        print(json.dumps({"ok": True, "mode": mode, "lane_id": LANE_ANALYST, **detail}, default=str))
        return 0
    try:
        out = _run_generate(q)
    except Exception as exc:  # noqa: BLE001
        write_lane_receipt(
            LANE_ANALYST,
            ok=False,
            mode=mode,
            detail={"error": f"{type(exc).__name__}: {exc}"[:400]},
        )
        print(json.dumps({"ok": False, "error": str(exc)[:300]}, default=str))
        return 1
    ok = bool(out.get("ok", True)) and not out.get("error") and not out.get("blocked")
    write_lane_receipt(LANE_ANALYST, ok=ok, mode=mode, detail={"result_keys": sorted(out.keys())})
    print(json.dumps({"ok": ok, "mode": mode, "lane_id": LANE_ANALYST, "result": out}, default=str)[:4000])
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
