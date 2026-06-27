#!/usr/bin/env python3
"""replay_chart_audit.py — Batch validate + backfill replay chart metadata for every closed trade.

For each trade in trade_closed (deduped by trade_key), calls ohlc_charts.trade_chart() and writes a
compact replay snapshot into journal_trade_reviews.payload.replay_chart. Also emits a machine + human
audit under docs/audits/.

Usage:
    python scripts/replay_chart_audit.py                  # all trades, write DB + docs
    python scripts/replay_chart_audit.py --dry-run        # audit only, no DB writes
    python scripts/replay_chart_audit.py --limit 25       # sample
    python scripts/replay_chart_audit.py --json           # stdout summary only
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import journal_trade_in_view as tiv
import ohlc_charts


def _dedupe_trades(rows: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for r in rows:
        key = r.get("trade_key") or f"{r.get('symbol')}:{r.get('account')}:{r.get('close_date')}"
        if key in seen:
            continue
        seen.add(key)
        out.append({**r, "trade_key": key})
    return out


def _replay_snapshot(chart: dict) -> dict:
    """Compact metadata stored on journal_trade_reviews — not full OHLC (too large)."""
    pb = chart.get("price_bounds") or {}
    integrity = chart.get("integrity") or {}
    return {
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "ui_version": "3.4",
        "timeframe": chart.get("timeframe"),
        "source": chart.get("source"),
        "bar_count": chart.get("bar_count", 0),
        "fallback": chart.get("fallback"),
        "price_bounds": pb,
        "integrity": {
            "marker_in_range": integrity.get("marker_in_range"),
            "marker_warnings": integrity.get("marker_warnings") or [],
        },
        "entry_et": chart.get("entry_et"),
        "exit_et": chart.get("exit_et"),
        "scale_fix": "volume_isolated_overlay_v3.4",
    }


def _upsert_replay_payload(trade_key: str, snap: dict, dry_run: bool) -> None:
    if dry_run:
        return
    existing = tiv._q("SELECT id, payload FROM journal_trade_reviews WHERE trade_key = %s",
                      [trade_key], fetch="one")
    payload = tiv._review_payload(existing) if existing else {}
    payload["replay_chart"] = snap
    if existing:
        tiv._q("UPDATE journal_trade_reviews SET payload = %s::jsonb, updated_at = NOW() WHERE trade_key = %s",
               [json.dumps(payload), trade_key], fetch="none")
    else:
        parts = trade_key.split(":")
        sym = parts[0]
        acct = parts[1] if len(parts) > 2 else ""
        cd = parts[-1]
        tiv._q("""
            INSERT INTO journal_trade_reviews (trade_key, symbol, account, closed_date, payload)
            VALUES (%s, %s, %s, %s::date, %s::jsonb)
            ON CONFLICT (trade_key) DO UPDATE SET payload = EXCLUDED.payload, updated_at = NOW()
        """, [trade_key, sym, acct, cd, json.dumps(payload)], fetch="none")


def run_audit(*, limit: int | None = None, dry_run: bool = False, throttle: float = 0.12) -> dict:
    rows = _dedupe_trades(tiv.fetch_closed_trades(limit=limit or 5000))
    results: list[dict] = []
    ok = warn = fail = 0

    for i, row in enumerate(rows):
        sym = row["symbol"]
        ed = str(row.get("open_date") or "")[:10]
        xd = str(row.get("close_date") or ed)[:10]
        ep = row.get("buy_price")
        xp = row.get("sell_price")
        tk = row["trade_key"]

        chart = ohlc_charts.trade_chart(sym, ed, xd, entry_price=ep, exit_price=xp)
        snap = _replay_snapshot(chart)

        status = "ok"
        reason = ""
        if chart.get("error"):
            status, fail = "fail", fail + 1
            reason = chart["error"]
        elif chart.get("fallback") == "finviz" or not chart.get("bars"):
            status, warn = "fallback", warn + 1
            reason = chart.get("reason") or "finviz fallback"
        elif chart.get("integrity", {}).get("marker_in_range") is False:
            status, warn = "marker_warn", warn + 1
            reason = "; ".join(chart["integrity"].get("marker_warnings") or [])
        else:
            ok += 1

        entry = {
            "trade_key": tk,
            "symbol": sym,
            "open_date": ed,
            "close_date": xd,
            "status": status,
            "reason": reason,
            "replay_chart": snap,
        }
        results.append(entry)
        _upsert_replay_payload(tk, snap, dry_run)

        if (i + 1) % 10 == 0:
            print(f"  [{i + 1}/{len(rows)}] {sym} {status}", flush=True)
        if throttle > 0:
            time.sleep(throttle)

    summary = {
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "total": len(results),
        "ok": ok,
        "warn": warn,
        "fail": fail,
        "dry_run": dry_run,
        "scale_fix": "volume_isolated_overlay_v3.4",
        "results": results,
    }
    return summary


def _write_docs(summary: dict, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    jpath = out_dir / f"REPLAY_INTEGRITY_{stamp}.json"
    mpath = out_dir / f"REPLAY_INTEGRITY_{stamp}.md"
    latest_j = out_dir / "REPLAY_INTEGRITY_LATEST.json"
    latest_m = out_dir / "REPLAY_INTEGRITY_LATEST.md"

    jpath.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    latest_j.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    lines = [
        f"# Replay chart integrity audit — {stamp}",
        "",
        f"**Audited:** {summary['audited_at']}  ",
        f"**Trades:** {summary['total']} · OK {summary['ok']} · WARN {summary['warn']} · FAIL {summary['fail']}  ",
        f"**Scale fix:** `{summary['scale_fix']}` (volume on isolated overlay scale; candle autoscale from OHLC only)",
        "",
        "## Summary",
        "",
        "| Status | Count | Meaning |",
        "|--------|------:|---------|",
        f"| ok | {summary['ok']} | Bars loaded; markers in range |",
        f"| warn | {summary['warn']} | Finviz fallback or marker outside bar range |",
        f"| fail | {summary['fail']} | No chart data / API error |",
        "",
        "## Per-trade",
        "",
        "| Symbol | Close | Bars | Source | Range | Status |",
        "|--------|-------|-----:|--------|-------|--------|",
    ]
    for r in summary["results"]:
        snap = r["replay_chart"]
        pb = snap.get("price_bounds") or {}
        rng = f"${pb.get('min_low', '—')}–${pb.get('max_high', '—')}" if pb else "—"
        lines.append(
            f"| {r['symbol']} | {r['close_date']} | {snap.get('bar_count', 0)} "
            f"| {snap.get('source') or snap.get('fallback') or '—'} | {rng} | {r['status']} |"
        )
    if summary["warn"] or summary["fail"]:
        lines += ["", "## Issues", ""]
        for r in summary["results"]:
            if r["status"] != "ok" and r.get("reason"):
                lines.append(f"- **{r['symbol']}** ({r['close_date']}): {r['reason']}")

    text = "\n".join(lines) + "\n"
    mpath.write_text(text, encoding="utf-8")
    latest_m.write_text(text, encoding="utf-8")
    return jpath, mpath


def main():
    ap = argparse.ArgumentParser(description="Replay chart integrity audit for all closed trades")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true", help="Print summary JSON to stdout only")
    ap.add_argument("--no-docs", action="store_true")
    ap.add_argument("--throttle", type=float, default=0.12)
    args = ap.parse_args()

    print(f"Replay chart audit starting (dry_run={args.dry_run})…", flush=True)
    summary = run_audit(limit=args.limit, dry_run=args.dry_run, throttle=args.throttle)

    if not args.no_docs and not args.dry_run:
        jpath, mpath = _write_docs(summary, PROJECT_ROOT / "docs" / "audits")
        print(f"Wrote {jpath.name} + {mpath.name}", flush=True)

    print(f"Done: {summary['ok']} ok, {summary['warn']} warn, {summary['fail']} fail / {summary['total']} trades",
          flush=True)

    if args.json:
        # strip full results for brevity unless needed
        out = {k: v for k, v in summary.items() if k != "results"}
        out["sample_issues"] = [r for r in summary["results"] if r["status"] != "ok"][:20]
        print(json.dumps(out, indent=2))
    return 0 if summary["fail"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())