#!/usr/bin/env python3
"""LQ-20261107-1590: a lane whose cron line was retired must be cut over, not left on `kind: cron`.

Evidence (2026-11-09 11:24 ET wave_watch): four lanes came back `RUN_SKIPPED_LOCK flock_held` at
their own slot — `generate-analyst-reports-autonomous-weekly` (Sun 21:15), `incubator-llm-screener`
(weekdays 08:10), `portfolio-lookthrough-themes` (weekdays 07:40) and `sec-filings-feed` (weekdays
08:20/12:20/17:20/21:20). For each, the flock holder was the lane's **own cron twin**, which had
fired ~20 s earlier: the crontab lines were retired under `# RETIRED 2026-11-09 n8n-cutover <lane>`
but the third step of the ladder — the registry row and the health contract — was never applied.
Both still said `scheduler.kind: cron`, `stage: canary`, so `run_quality` reported "both cron and
n8n fire this lane" on a lane whose cron line no longer exists, and the contract's healthy binding
still excused a lock skip as "the cron twin holds the shared flock".

The registry row now carries the §23.11 dispatcher row (`kind: n8n`, `expression: dispatcher`,
`stage: cutover`, `cadence` = the retired line's schedule, the old block kept as
`scheduler_before_cutover`), and the contract is at `stage: cutover` with the skip excuse removed.

The second test is the durable half: any lane carrying a retirement tag whose row is still
`kind: cron` is a lane that can be skipped by a twin that no longer exists, and it fails here. The
baseline below is the debt that predates this fix — mostly 2026-11-09's wave, which retired 21
lanes in one pass. It may only shrink: fixing a lane means deleting its line from the baseline.

The crontab text is a synthetic fixture (CI has no crontab); the tag format and the parser are the
repo's own (`scripts.lib.lane_registry.n8n_cutover_tag`, the parser behind
`lane_registry.N8N_CUTOVER_TAG`).
"""
import json
from pathlib import Path

import pytest

from scripts.lib.lane_registry import n8n_cutover_tag

ROOT = Path(__file__).resolve().parents[1]

# The four lanes wave_watch caught, with the schedule of the line the cutover retired.
CUT_OVER = {
    "generate-analyst-reports-autonomous-weekly": "15 21 * * 0",
    "incubator-llm-screener": "10 8 * * 1-5",
    "portfolio-lookthrough-themes": "40 7 * * 1-5",
    "sec-filings-feed": "20 8,12,17,21 * * 1-5",
}

# Retired under `# RETIRED <date> n8n-cutover <lane>` but still `scheduler.kind: cron` in the
# registry. Only documented retirement dates are listed here; a lane leaves this dict when its row
# is cut over, and nothing may be added to it.
KNOWN_STILL_CRON = {
    "aegis-evening-packet": "2026-11-09",
    "agent-calibration-engine": "2026-11-09",
    "agent-watchlist-engine": "2026-11-09",
    "ask-alerts": "2026-11-09",
    "drain-discovery-backlog": "2026-11-09",
    "event-detector": "2026-11-08",
    "fee-efficiency-analyzer": "2026-11-09",
    "finviz-enrichment-scalp-hot": "2026-11-09",
    "finviz-market-movers": "2026-11-09",
    "hermes-research-agenda-at-45-7": "2026-11-08",
    "news-ingestion-tail": "2026-11-07",
    "news-to-catalyst": "2026-11-09",
    "overnight-batch-tax": "2026-11-09",
    "proposal-llm-review-worker": "2026-11-09",
    "reclassify-momentum-proposals": "2026-11-08",
    "reconcile-exit-advisory-outcomes": "2026-11-08",
    "reconcile-pullback-outcomes": "2026-11-09",
    "reconcile-watch-outcomes": "2026-11-08",
    "research-intelligence-queue": "2026-11-09",
    "sec-fundamentals-ingest": "2026-11-07",
    "social-scalp-scanner": "2026-11-09",
    "tmp-scratch-cleanup": "2026-11-09",
    "trade-ai-scalp-live": "2026-11-09",
    "update-lockup-earnings-dates": "2026-11-09",
}


def _crontab() -> str:
    """The retirement tags as the live crontab carries them, plus one live line nobody retired."""
    lines = [f"# RETIRED 2026-11-09 n8n-cutover {lane} {sched} cd $PROJ && flock -n /tmp/{lane}.lock $PY lane.py"
             for lane, sched in CUT_OVER.items()]
    lines += [f"# RETIRED {date} n8n-cutover {lane} <schedule not reproduced in this fixture>"
              for lane, date in KNOWN_STILL_CRON.items()]
    lines.append("5 6 * * 1-5 cd $PROJ && flock -n /tmp/never-retired.lock $PY still_live.py")
    return "\n".join(lines) + "\n"


def _registry():
    doc = json.loads((ROOT / "config/lane_registry.json").read_text(encoding="utf-8"))
    return {r["lane_id"]: r for r in doc["lanes"] if isinstance(r, dict) and r.get("lane_id")}


def _contracts():
    doc = json.loads((ROOT / "config/n8n_health_contracts.json").read_text(encoding="utf-8"))
    return {c["id"]: c for c in doc["contracts"] if isinstance(c, dict) and c.get("kind") == "lane" and c.get("id")}


def test_the_four_skipped_lanes_carry_the_dispatcher_row():
    rows, contracts = _registry(), _contracts()
    for lane in CUT_OVER:
        sched = rows[lane]["scheduler"]
        assert sched["kind"] == "n8n", f"{lane} still fires from cron (kind={sched.get('kind')})"
        assert sched["expression"] == "dispatcher"
        assert sched["stage"] == "cutover"
        assert sched.get("cutover_wave"), "a cutover row records the wave that cut it over"
        before = rows[lane]["scheduler_before_cutover"]
        assert before["kind"] == "cron", "the pre-cutover block is what rollback restores"
        assert before["expression"] == CUT_OVER[lane]
        contract = contracts[lane]
        assert contract["stage"] == "cutover", f"{lane}'s contract still grades it as a canary"
        healthy = {h["check"]: h["text"] for h in contract["healthy"]}
        assert "or RUN_SKIPPED_LOCK while the cron twin" not in healthy["canary_live_done"], (
            f"{lane}'s contract still excuses a lock skip as 'the cron twin holds the shared flock' — "
            "the cron line is retired, so a skip is a stray trigger")


def test_no_retired_lane_is_left_on_cron():
    """Every lane the crontab says was retired must have been cut over, not left skipping behind a twin."""
    tags = {}
    for line in _crontab().splitlines():
        tag = n8n_cutover_tag(line)
        if tag is not None:
            tags.setdefault(tag["lane_id"], tag["date"])
    assert set(CUT_OVER) <= set(tags), "the fixture must exercise the four lanes this change fixes"

    rows = _registry()
    debt = {lane: date for lane, date in tags.items()
            if (rows.get(lane, {}).get("scheduler") or {}).get("kind") == "cron"}
    assert debt == KNOWN_STILL_CRON, (
        "a lane with a RETIRED n8n-cutover tag is still scheduler.kind cron:\n"
        f"  new debt: {sorted(set(debt) - set(KNOWN_STILL_CRON))}\n"
        f"  fixed (delete it from KNOWN_STILL_CRON): {sorted(set(KNOWN_STILL_CRON) - set(debt))}\n"
        "Apply the third cutover step: nightly_cutover.dispatcher_row(row, wave) on the registry row "
        "and cutover_contract(contract, wave) on its health contract.")


@pytest.mark.parametrize("lane", sorted(CUT_OVER))
def test_the_cadence_is_the_retired_cron_line(lane):
    """The dispatcher row must keep firing on the schedule the retired line carried."""
    line = next(ln for ln in _crontab().splitlines() if f"n8n-cutover {lane} " in ln)
    schedule = line.split(f"n8n-cutover {lane} ", 1)[1].split(" cd ", 1)[0].strip()
    sched = _registry()[lane]["scheduler"]
    assert sched["cadence"] == schedule
    fields = sched["cadence"].split()
    assert len(fields) == 5, f"{lane}: cadence is not a five-field cron expression: {sched['cadence']!r}"
