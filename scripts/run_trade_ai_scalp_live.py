#!/usr/bin/env python3
"""run_trade_ai_scalp_live.py — Trade-AI scalp scan every 5 minutes in RTH (operator 2026-10-09).

"these are scalps should be every 5 minutes at least … same should be feeding both tradeai and also active trader".

One deterministic live cycle (continuous_runner.run_live_cycle; no paid LLM — catalysts come from the 20-minute
catalyst cache / local enrichment) over the scalp screeners only (assets/screeners.yaml run window `scalp`),
written to trade_ai_scans under its own run_label `scalp` so it never merges with the slot runs. Scoring is the
same score_all as every other run, so GO rules (incl. the 40+-with-catalyst runner GO) are identical.

The cycle's "already GO / already alerted" memory is saved between runs (persistent state, reset each day), so a
GO alerts once, not every 5 minutes. Market-day gated by the cron wrapper; outside 09:30-16:00 ET it exits.

    python3 scripts/run_trade_ai_scalp_live.py            # one cycle (cron: */5 9-15 * * 1-5)
    python3 scripts/run_trade_ai_scalp_live.py --force    # ignore the RTH window (testing)
    python3 scripts/run_trade_ai_scalp_live.py --dry-run  # plan only: no scan, no write, no send (n8n shadow)

Every completed run (a cycle, or an outside-RTH exit) writes the receipt
$TRADEAI_STATE_ROOT/data/runtime/trade_ai_scalp_live_last.json (TradeAIScalpLiveReceipt@v1): the n8n run
executor's output_signal and the incident fan-in's stall source (last_ok_at older than 12 min in RTH).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

ET = ZoneInfo("America/New_York")
RUN_LABEL = "scalp"
RTH = ((9, 30), (16, 0))


def projection_path() -> Path:
    """The shared scalp universe both engines read (one Finviz pull, one writer: this lane)."""
    base = os.getenv("TRADEAI_STATE_ROOT") or str(Path.home() / "trade-ai-releases" / "persistent-state")
    return Path(base) / "data" / "trade_ai" / "scalp_universe_latest.json"


def write_projection(scored, now: datetime) -> int:
    rows = [{"symbol": str(t.get("symbol") or "").upper(), "decision": t.get("decision"), "score": t.get("score"),
             "float_m": t.get("float_m"), "price": t.get("price"), "setup_class": t.get("setup_class")}
            for t in (scored or []) if t.get("symbol")]
    p = projection_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"schema": "TradeAIScalpUniverse@v1", "as_of": now.isoformat(), "run_label": RUN_LABEL,
                               "writer": "run_trade_ai_scalp_live", "rows": rows}), encoding="utf-8")
    tmp.replace(p)
    return len(rows)


def state_path() -> Path:
    base = os.getenv("TRADEAI_STATE_ROOT") or str(Path.home() / "trade-ai-releases" / "persistent-state")
    return Path(base) / "state" / "trade_ai_scalp_live_state.json"


def receipt_path() -> Path:
    base = os.getenv("TRADEAI_STATE_ROOT") or str(Path.home() / "trade-ai-releases" / "persistent-state")
    return Path(base) / "data" / "runtime" / "trade_ai_scalp_live_last.json"


def write_receipt(status: str, now: datetime, *, universe: int | None = None, go: int | None = None,
                  seconds: float | None = None) -> dict:
    """Atomic receipt. last_ok_at carries over from the previous receipt until a cycle completes again."""
    p = receipt_path()
    try:
        prev = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — first run or a torn file: no previous ok
        prev = {}
    doc = {"schema": "TradeAIScalpLiveReceipt@v1", "lane_id": "trade-ai-scalp-live", "as_of": now.isoformat(),
           "status": status, "run_label": RUN_LABEL, "universe": universe, "go": go,
           "seconds": None if seconds is None else round(seconds, 1),
           "last_ok_at": now.isoformat() if status == "ok" else prev.get("last_ok_at")}
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, sort_keys=True), encoding="utf-8")
    tmp.replace(p)
    return doc


def dry_run_plan(now: datetime) -> dict:
    """What a live run would do, read-only: no scan, no state/projection/receipt write, no send."""
    def _age_min(path: Path, key: str):
        try:
            then = datetime.fromisoformat(json.loads(path.read_text(encoding="utf-8"))[key])
            return round((now - then).total_seconds() / 60, 1)
        except Exception:  # noqa: BLE001 — missing/torn file reads as unknown
            return None
    rth = in_rth(now)
    return {"mode": "dry_run", "now": now.isoformat(), "in_rth": rth, "run_label": RUN_LABEL,
            "would": ("run_live_cycle(publish_dashboard=False) + state + projection + receipt" if rth
                      else "exit outside RTH (receipt status outside_rth)"),
            "projection_age_min": _age_min(projection_path(), "as_of"),
            "last_ok_age_min": _age_min(receipt_path(), "last_ok_at")}


def in_rth(now: datetime) -> bool:
    m = now.hour * 60 + now.minute
    return RTH[0][0] * 60 + RTH[0][1] <= m < RTH[1][0] * 60 + RTH[1][1]


def load_state(day: str):
    from continuous_runner import CycleState

    try:
        d = json.loads(state_path().read_text(encoding="utf-8"))
        if d.get("date") == day:
            return CycleState.from_dict(d.get("state") or {})
    except Exception:  # noqa: BLE001 — a missing/old state is a fresh day
        pass
    return CycleState()


def save_state(day: str, st) -> None:
    p = state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"date": day, "saved_at": datetime.now(ET).isoformat(), "state": st.to_dict()}),
                   encoding="utf-8")
    tmp.replace(p)


def enrich_budget() -> Optional[float]:
    """Seconds of catalyst lookups per cycle (config/trade_ai_scalp_lane.yaml); None = unbounded."""
    try:
        import yaml

        v = (yaml.safe_load((ROOT / "config" / "trade_ai_scalp_lane.yaml").read_text(encoding="utf-8")) or {}).get(
            "enrich_budget_s")
        return float(v) if v else None
    except Exception:
        return None


def bulk_catalysts() -> Optional[dict]:
    """`catalysts` block of config/trade_ai_scalp_lane.yaml (bulk catalyst read); None when absent."""
    from scalp_catalyst_bulk import load_config

    return load_config(ROOT) or None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--force", action="store_true", help="run outside 09:30-16:00 ET")
    ap.add_argument("--dry-run", action="store_true", help="print the plan; no scan, write or send")
    a = ap.parse_args(argv)
    now = datetime.now(ET)
    if a.dry_run:
        print(f"[scalp-live] dry-run {json.dumps(dry_run_plan(now), sort_keys=True)}")
        return 0
    if not a.force and not in_rth(now):
        print(f"[scalp-live] {now:%H:%M} ET outside RTH — nothing to do")
        write_receipt("outside_rth", now)
        return 0
    from continuous_runner import run_live_cycle

    day = now.date().isoformat()
    st = load_state(day)
    t0 = datetime.now(ET)
    scored = run_live_cycle(ROOT, RUN_LABEL, day, st, now.strftime("%H:%M"), publish_dashboard=False,
                            enrich_budget_s=enrich_budget(), bulk_catalysts=bulk_catalysts())
    save_state(day, st)
    n = write_projection(scored, datetime.now(ET)) if scored else 0
    write_receipt("ok", datetime.now(ET), universe=n, go=len(st.prev_go),
                  seconds=(datetime.now(ET) - t0).total_seconds())
    print(f"[scalp-live] heartbeat ok label={RUN_LABEL} go={len(st.prev_go)} universe={n} "
          f"seconds={(datetime.now(ET) - t0).total_seconds():.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
