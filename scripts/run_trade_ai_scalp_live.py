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
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--force", action="store_true", help="run outside 09:30-16:00 ET")
    a = ap.parse_args(argv)
    now = datetime.now(ET)
    if not a.force and not in_rth(now):
        print(f"[scalp-live] {now:%H:%M} ET outside RTH — nothing to do")
        return 0
    from continuous_runner import run_live_cycle

    day = now.date().isoformat()
    st = load_state(day)
    t0 = datetime.now(ET)
    scored = run_live_cycle(ROOT, RUN_LABEL, day, st, now.strftime("%H:%M"), publish_dashboard=False)
    if not isinstance(scored, list) or any(not isinstance(row, dict) for row in scored):
        print(f"[scalp-live] cycle failed label={RUN_LABEL}: no valid scored result", file=sys.stderr)
        return 1
    save_state(day, st)
    n = write_projection(scored, datetime.now(ET))
    print(f"[scalp-live] heartbeat ok label={RUN_LABEL} go={len(st.prev_go)} universe={n} "
          f"seconds={(datetime.now(ET) - t0).total_seconds():.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
