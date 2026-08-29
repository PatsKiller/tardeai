#!/usr/bin/env python3
"""CIO Wave 2 census — one read-only NOW block from the live surfaces.

Every number the scoreboard claims, recomputed from CURRENT in one pass, so the
scoreboard can be checked rather than trusted.

  python scripts/cio_wave2_census.py --json
  python scripts/cio_wave2_census.py                  # human table
  python scripts/cio_wave2_census.py --out census.json

READ_ONLY_ADVISORY. MBI=0. Reads only; writes nothing but --out.
"""
from __future__ import annotations

NO_CONSUMER_REASON = (
    "operator-invoked audit CLI: CIOWave2Census@v1 exists so the Wave 2 "
    "scoreboard can be checked against the live surfaces, and its consumer is a "
    "person running --json, not a code path. Wiring it into the product would "
    "make the scoreboard verify itself, which defeats the point."
)

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LIVE = Path("/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT")
HOME_URL = "http://127.0.0.1:7777/api/v3/cio/home"
HEALTH_URL = "http://127.0.0.1:7777/api/v2/health"
CIO_URL = "http://127.0.0.1:7777/v3/cio"

SCHEMA = "CIOWave2Census@v1"
AUTHORITY = "READ_ONLY_ADVISORY"


def _http_status(url: str, timeout: float = 10.0) -> int:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return int(resp.status)
    except Exception:
        return 0


def _http_json(url: str, timeout: float = 30.0) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return {}


def census(root: Path) -> dict[str, Any]:
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "scripts"))
    os.environ.setdefault("TRADEAI_ROOT", str(root))

    from scripts.lib import holdings_universe as hu
    from scripts.lib.cio_plans import CIOPlanStore
    from scripts.lib.cio_research_fail_policy import load_fail_histogram, load_verdict_counts

    out: dict[str, Any] = {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "memory_behavior_influence": 0,
        "financial_action": False,
        "root": str(root),
    }

    # ── pin + endpoints ──
    try:
        out["current_pin"] = (root / "BUILD_SHA").read_text(encoding="utf-8").strip()
    except OSError:
        out["current_pin"] = None
    out["endpoints"] = {
        "health": _http_status(HEALTH_URL),
        "v3_cio": _http_status(CIO_URL),
        "home": _http_status(HOME_URL),
    }

    # ── holdings truth (slices 12 / 12a / 39 / 40) ──
    snap = hu.snapshot(root=root)
    dq = hu.holdings_data_quality(root=root)
    out["holdings"] = {
        "position_rows": snap["position_rows"],
        "held_equity_ticker_n": snap["held_equity_ticker_n"],
        "held_equity_ticker_nondust_n": snap["held_equity_ticker_nondust_n"],
        "dust_n": snap["dust_n"],
        "dust_tickers": snap["dust_tickers"],
        "instrument_id_n": snap["instrument_id_n"],
        "instrument_ids": [r["instrument_id"] for r in snap["instrument_ids"]],
        "dust_threshold_usd": snap["dust_policy"]["threshold_usd"],
        "data_quality_state": dq["state"],
        "data_quality_labels": dq["labels"],
        "cash_row_sum": dq["cash_totals"]["cash_row_sum"],
        "cash_portfolio_totals": dq["cash_totals"]["portfolio_totals_total_cash"],
        "cash_delta": dq["cash_totals"]["delta_rows_minus_declared"],
        "cash_sources_agree": dq["cash_totals"]["sources_agree"],
    }

    # ── plans (slices 12b / 16 / orphan S6) ──
    store = CIOPlanStore(
        event_path=root / "data/cio/cio_plans.jsonl",
        projection_path=root / "data/cio/cio_plans_projection.json",
    )
    open_plans = store.list_open_plans(limit=1000000)
    by_situation: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for p in open_plans:
        st = str(p.get("situation_type") or "UNKNOWN")
        by_situation[st] = by_situation.get(st, 0) + 1
        stt = str(p.get("status") or "UNKNOWN")
        by_status[stt] = by_status.get(stt, 0) + 1
    out["plans"] = {
        "open_total": len(open_plans),
        "by_situation": dict(sorted(by_situation.items(), key=lambda kv: -kv[1])),
        "by_status": by_status,
    }

    # ── research (slices 19 / 25) ──
    hist = load_fail_histogram(root=root, window_days=7)
    verdicts = load_verdict_counts(root=root)
    out["research"] = {
        "fail_window_days": hist["window_days"],
        "fails_in_window": hist["failures_in_window"],
        "fails_all_time": hist["failures_total_all_time"],
        "fails_by_class": hist["by_class"],
        "fails_retryable": hist["retryable_n"],
        "fails_worker_bug": hist["worker_bug_n"],
        "completed_n": verdicts["completed_n"],
        "by_verdict": verdicts["by_verdict"],
        "attachable_n": verdicts["attachable_n"],
        "attach_rule": verdicts["attach_rule"],
    }

    # ── memory (slices 30 / 31) ──
    try:
        from scripts.lib.agent_durable_memory import get_durable_provider
        rows = list(get_durable_provider(root)._store.values())
        by_type: dict[str, int] = {}
        for r in rows:
            key = f"{r.get('memory_type')}:{r.get('status')}"
            by_type[key] = by_type.get(key, 0) + 1
        out["memory"] = {
            "records": len(rows),
            "by_type_status": dict(sorted(by_type.items())),
            "research_reference_active": sum(
                1 for r in rows
                if r.get("memory_type") == "RESEARCH_REFERENCE"
                and str(r.get("status")).upper() in {"ACTIVE", "ADMITTED"}
            ),
        }
    except Exception as exc:
        out["memory"] = {"available": False, "reason": type(exc).__name__}

    # ── live home surface ──
    home = _http_json(HOME_URL)
    cov = home.get("coverage") or {}
    graph = home.get("graph_impact") or {}
    wbs = home.get("watch_block_summary") or {}
    out["home"] = {
        "coverage": {
            k: cov.get(k) for k in (
                "held_n", "thesis_count", "with_plan", "with_plan_source",
                "with_research", "with_case_summary", "watch_ready",
                "watch_block", "reentry_near",
            )
        },
        "graph_impact": {
            "s6_symbols": graph.get("s6_symbols"),
            "attached_n": graph.get("attached_n"),
            "skipped": [s.get("symbol") for s in (graph.get("skipped") or [])],
        },
        "watch": {
            "block_count": wbs.get("count"),
            "ready_count": wbs.get("ready_count"),
            "fires_s7": wbs.get("fires_s7"),
        },
        "earnings_n": len(home.get("earnings") or []),
        "new_position_if": [
            x.get("symbol") for x in (home.get("new_position_if") or []) if isinstance(x, dict)
        ],
        "telegram_sent": home.get("telegram_sent"),
        "authority": home.get("authority"),
    }

    # ── rails ──
    out["rails"] = {
        "authority": home.get("authority") or AUTHORITY,
        "memory_behavior_influence": 0,
        "telegram_sent": home.get("telegram_sent"),
        "fires_s7": wbs.get("fires_s7"),
        "interdict": os.environ.get("CIO_TELEGRAM_INTERDICT", "0"),
    }
    return out


def render(c: dict[str, Any]) -> str:
    h, p, r, m, home = c["holdings"], c["plans"], c["research"], c.get("memory", {}), c["home"]
    cov = home["coverage"]
    lines = [
        "CIO Wave 2 census — read-only",
        f"  pin              {c['current_pin']}",
        f"  endpoints        health {c['endpoints']['health']} · /v3/cio "
        f"{c['endpoints']['v3_cio']} · home {c['endpoints']['home']}",
        "",
        f"  held (non-dust)  {h['held_equity_ticker_nondust_n']} "
        f"(incl dust {h['held_equity_ticker_n']}, dust {h['dust_n']} {h['dust_tickers']})",
        f"  instrument_ids   {h['instrument_id_n']} {h['instrument_ids']}",
        f"  data quality     {h['data_quality_state']} {h['data_quality_labels']}",
        f"  cash rows        ${h['cash_row_sum']:,.2f} vs portfolio_totals "
        f"${(h['cash_portfolio_totals'] or 0):,.2f} (Δ ${(h['cash_delta'] or 0):,.2f}, "
        f"agree={h['cash_sources_agree']})",
        "",
        f"  open plans       {p['open_total']}  {p['by_status']}",
        f"  by situation     {p['by_situation']}",
        "",
        f"  research fails   {r['fails_in_window']} in {r['fail_window_days']}d "
        f"of {r['fails_all_time']} all time · {r['fails_by_class']}",
        f"    retryable {r['fails_retryable']} · worker_bug {r['fails_worker_bug']}",
        f"  research verdicts {r['completed_n']} completed · {r['by_verdict']} · "
        f"attachable {r['attachable_n']} (rule {r['attach_rule']})",
        "",
        f"  memory           {m.get('records')} records · RESEARCH_REFERENCE ACTIVE "
        f"{m.get('research_reference_active')}",
        "",
        f"  home coverage    held {cov.get('held_n')} · thesis {cov.get('thesis_count')} · "
        f"with_plan {cov.get('with_plan')} ({cov.get('with_plan_source')}) · "
        f"with_research {cov.get('with_research')}",
        f"  home watch       BLOCK {home['watch']['block_count']} · READY "
        f"{home['watch']['ready_count']} · fires_s7 {home['watch']['fires_s7']}",
        f"  home graph S6    {home['graph_impact']['attached_n']} attached · "
        f"skipped {home['graph_impact']['skipped']}",
        f"  home earnings    {home['earnings_n']} · NEW_POSITION_IF {home['new_position_if']}",
        "",
        f"  rails            authority {c['rails']['authority']} · MBI "
        f"{c['rails']['memory_behavior_influence']} · telegram_sent "
        f"{c['rails']['telegram_sent']} · fires_s7 {c['rails']['fires_s7']} · "
        f"INTERDICT {c['rails']['interdict']}",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="CIO Wave 2 census (read-only)")
    ap.add_argument("--root", default=str(LIVE))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    data = census(Path(a.root))
    text = json.dumps(data, indent=2, default=str)
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
    print(text if a.json else render(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
