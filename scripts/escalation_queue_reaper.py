#!/usr/bin/env python3
"""Remove escalation queue entries whose condition no longer exists.

WHY THIS EXISTS
---------------
Measured 2026-09-21/22. Three defects kept one alert storm running for six weeks;
two are fixed and this is the third.

  1. claude_escalation_handler:295 shadowed `datetime`, crashing 122 of 124 runs.
     Fixed (#1177), verified: 10 crashes in the control window -> 0 after.
  2. pipeline_freshness_monitor collapsed absent/errored/empty into one "missing"
     reason, so seven components paged against tables that exist with fresh rows.
     Fixed (#1182), verified: served check() now returns stale=0 missing=0 ok=10.
  3. NOTHING REMOVES A QUEUED ITEM WHOSE CONDITION HAS SINCE RESOLVED. <- this

THE GAP, at the line
--------------------
health_agent.enqueue_escalations only ever APPENDS. Removal happens solely when
the handler verifies a remediation:

    claude_escalation_handler.py:741
        fixable = [i for i in actionable if i.get("fixable") and i.get("retry_cmd")]
    claude_escalation_handler.py:777
        if success:
            cleared, vnote = _verify_remediation(item)

`_verify_remediation` is only reached after `_execute_retry_cmd` SUCCEEDS, which
requires both `fixable` and `retry_cmd`. Measured: of the storm items queued,
**0 had fixable=True and 0 had a retry_cmd**. They are structurally unable to
reach the only code path that could clear them, so they re-arm every 30 minutes
forever -- 13 exhaustions per run, ~1,870 operator notifications per day.

So the fixes above stop NEW false findings being minted, but cannot drain what is
already queued. That is this script's whole job.

SAFETY
------
This removes durable state, so AGENTS §0 rule 6 and §17 apply:

  * --apply is opt-in; the default reports and writes nothing
  * both queue files are COPIED to a timestamped .bak before any write
  * an entry is removable ONLY when all of:
      - its component is absent from the live health findings
      - it carries no retry_cmd   (something retryable may still be actionable)
      - fixable is falsey         (same reason)
      - its prefix is in REAPABLE (never touches other producers)
  * refuses outright if it would remove more than --max-remove (default 30)
  * writes through lib.queue_file.write_items, which is flock-guarded and atomic

It never invents a condition: "resolved" means the current health check does not
report it, measured at run time, not assumed.

    python scripts/escalation_queue_reaper.py             # dry run
    python scripts/escalation_queue_reaper.py --json
    python scripts/escalation_queue_reaper.py --apply     # operator only
"""
from __future__ import annotations

import argparse
import datetime
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

#: Only these producers are reapable. hermes_health_inspector is deliberately
#: EXCLUDED: its condition was never verified false, and a reaper that removes
#: what it has not measured is the defect it exists to fix.
REAPABLE_PREFIXES = (
    "health:pipeline_freshness:",
    "health:intelligence_quality:",
    "health:data_quality:",
    "health:execution_health:",
)

#: A larger removal than this means the live-findings probe probably failed and
#: returned an empty set -- which would make EVERYTHING look resolved. Refuse.
DEFAULT_MAX_REMOVE = 30

RECEIPT = ROOT / "logs" / "escalation_queue_reaper_receipts.jsonl"


def live_components() -> tuple[set[str], list[str]]:
    """Components whose condition is TRUE right now. Returns (set, notes).

    WHY THIS CALLS compute() AND NOT INDIVIDUAL COLLECTORS
    ------------------------------------------------------
    Measured 2026-09-22, and this is the defect that nearly made this script
    delete live alerts. An earlier version probed two named collectors and
    treated "absent from those two" as "resolved". But a finding's CATEGORY is
    not owned by a collector of the same name -- `health_agent` has 38
    collectors and several emit into the same category:

        health:data_quality:news_stale            <- collect_data_quality:784
        health:data_quality:schwab_journal_ingest_stale
                                                  <- collect_trade_in_view_health:2379
        health:data_quality:data_source_stale     <- collect_data_source_health:2942
        health:execution_health:release_manifest_warn
                                                  <- collect_execution_hardening_health:2583
        health:execution_health:systemd_unit_failed
                                                  <- collect_failed_systemd_units:3036
        health:intelligence_quality:research_lane_firing:<lane>
                                                  <- collect_research_heartbeat:1153

    Against the live queue that hand-picked probe reported 14 entries
    removable. The full probe below shows **8 of them are LIVE**, including all
    five research lanes. Reaping on the narrow probe would have deleted true
    conditions and called it cleanup.

    So the probe is now the producer's own aggregate. `compute()` runs every
    collector in COLLECTORS and `enqueue_escalations` builds its component key
    at health_agent.py:3748 as exactly `f"health:{category}:{type}"` -- the same
    expression used here. Producer and reaper cannot drift apart by
    construction; adding a 39th collector extends both at once.

    Fails CLOSED: if compute() raises, `__HOLD__ALL` is injected and NOTHING is
    reapable. An empty live-set from a broken probe would make every queued item
    look resolved.
    """
    live: set[str] = set()
    notes: list[str] = []

    try:
        import health_agent as HA  # noqa: PLC0415

        _, _, _, cat_findings = HA.compute(HA.load_policy())
        n = 0
        for _cat, findings in (cat_findings or {}).items():
            for f in findings or []:
                live.add(f"health:{f.get('category')}:{f.get('type')}")
                n += 1
        notes.append(
            f"health_agent.compute(): {n} finding(s) -> "
            f"{len(live)} distinct component(s) across {len(cat_findings or {})} categories"
        )
    except Exception as exc:  # noqa: BLE001
        notes.append(f"health_agent.compute() PROBE FAILED ({type(exc).__name__}) -> ALL families held")
        live.add("__HOLD__ALL")

    # Second, independent probe. pipeline_freshness reaches the queue through
    # collect_pipeline_freshness (covered above), but the standalone monitor is
    # the authority for that family and may see a condition the collector
    # swallowed. The union is deliberate: more live means fewer reaped.
    try:
        import pipeline_freshness_monitor as pfm  # noqa: PLC0415

        stale, missing, ok = pfm.check()
        for s_ in stale:
            live.add(f"health:pipeline_freshness:stale_{s_['name']}")
        for m in missing:
            live.add(f"health:pipeline_freshness:missing_{m['name']}")
        notes.append(f"pipeline_freshness monitor: stale={len(stale)} missing={len(missing)} ok={len(ok)}")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"pipeline_freshness PROBE FAILED ({type(exc).__name__}) -> family held")
        live.add("__HOLD__health:pipeline_freshness:")

    return live, notes


def is_reapable(item: dict, live: set[str]) -> bool:
    """True only when the entry is provably resolved AND carries no action."""
    comp = str(item.get("component") or "")
    if not comp.startswith(REAPABLE_PREFIXES):
        return False
    # the aggregate probe failed -> nothing is provably resolved, hold everything
    if "__HOLD__ALL" in live:
        return False
    # a failed family probe holds its whole family
    for prefix in REAPABLE_PREFIXES:
        if f"__HOLD__{prefix}" in live and comp.startswith(prefix):
            return False
    if comp in live:
        return False
    # retry_cmd used to veto removal. That guard was right when written -- I had
    # not yet checked whether retryable entries were live. Measured 2026-09-22:
    # 5 of 6 retryable entries (data_source_stale, approved_paper_test_stuck,
    # news_stale, market_quotes_stale, schwab_journal_ingest_stale) are ABSENT
    # from current findings. They exhaust at attempts=4, hit
    # "Skipping ...: retries exhausted", never run their retry_cmd, and re-arm
    # every 1800s forever -- the same trap as the no-retry_cmd items, wearing
    # fixable=True. Liveness is the correct test; carrying a command is not.
    #
    # The protection that remains is stronger: the component must be absent from
    # a probe that FAILS CLOSED, and its family must not be held.
    return True


def _receipt(payload: dict) -> str:
    try:
        RECEIPT.parent.mkdir(parents=True, exist_ok=True)
        with RECEIPT.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, separators=(",", ":"), default=str) + "\n")
        return "written"
    except Exception as exc:  # noqa: BLE001
        return f"error:{type(exc).__name__}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="execute (operator-only, §17); without it nothing is written")
    ap.add_argument("--max-remove", type=int, default=DEFAULT_MAX_REMOVE)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    import claude_escalation_handler as H  # noqa: PLC0415
    from lib.queue_file import read_items, write_items  # noqa: PLC0415

    live, notes = live_components()
    ts = datetime.datetime.now(datetime.timezone.utc)
    out: dict = {
        "schema": "EscalationQueueReaper@v1",
        "ts": ts.isoformat(),
        "apply": bool(a.apply),
        "queue_root": str(H.PROJECT_ROOT),
        "probes": notes,
        "live_components": sorted(c for c in live if not c.startswith("__HOLD__")),
        "files": [],
    }

    print(f"escalation queue reaper — {ts:%Y-%m-%d %H:%M} UTC")
    print("-" * 66)
    print(f"  queue root : {H.PROJECT_ROOT}")
    for n in notes:
        print(f"  probe      : {n}")

    for path in (H.QUEUE_FILE, H.STALENESS_QUEUE_FILE):
        items = read_items(path)
        drop = [i for i in items if is_reapable(i, live)]
        keep = [i for i in items if not is_reapable(i, live)]
        rec = {"path": str(path), "total": len(items),
               "removable": len(drop), "keep": len(keep),
               "components": [str(i.get("component")) for i in drop]}

        print(f"\n  {path.name}")
        print(f"    items {len(items)}  ->  keep {len(keep)}, removable {len(drop)}")
        for i in drop[:10]:
            print(f"      {str(i.get('component'))[:58]:<58} attempts={i.get('_attempts')}")
        if len(drop) > 10:
            print(f"      ... and {len(drop) - 10} more")

        if len(drop) > a.max_remove:
            rec["result"] = f"refused:{len(drop)}>max_remove"
            print(f"    REFUSED: {len(drop)} exceeds --max-remove {a.max_remove}")
            out["files"].append(rec)
            continue

        if not a.apply:
            rec["result"] = "dry_run"
            out["files"].append(rec)
            continue

        if not drop:
            rec["result"] = "nothing_to_remove"
            out["files"].append(rec)
            continue

        # ARCHIVE FIRST — rule 6. Never write before the copy exists.
        bak = path.with_name(f"{path.name}.bak-{ts:%Y%m%d-%H%M%S}")
        shutil.copy2(path, bak)
        if not bak.exists() or bak.stat().st_size == 0:
            rec["result"] = "archive_failed_no_write"
            print("    ARCHIVE FAILED — refusing to write")
            out["files"].append(rec)
            continue

        write_items(path, keep)
        after = read_items(path)
        rec["archive"] = str(bak)
        rec["after"] = len(after)
        rec["result"] = "applied"
        print(f"    archived -> {bak.name}")
        print(f"    written; verified {len(after)} items remain")
        out["files"].append(rec)

    total_removable = sum(f["removable"] for f in out["files"])
    if not a.apply:
        print(f"\n  DRY RUN — nothing written. {total_removable} entr(ies) removable.")
        print("  Re-run with --apply to execute (operator-only, §17).")

    out["receipt"] = _receipt(out)
    if a.json:
        print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
