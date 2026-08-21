#!/usr/bin/env python3
"""Retarget remaining DeepSeek-peak crontab lines (A.1). Read + optional apply.

Does not touch hermes-autonomous-loop.timer (already official off-peak).
Does not wrap ATP2 premarket_4am (latency-sensitive; price at peak).

Default: print the patch. --apply writes crontab after a timestamped backup.
READ_ONLY_ADVISORY for trading. Crontab mutation is ops-only.
"""
from __future__ import annotations

import argparse
import subprocess
from datetime import datetime, timezone
from pathlib import Path

AUTHORITY = "READ_ONLY_ADVISORY"
WRAP = 'bash "$HOME/.config/tradeai/bin/run_with_deepseek_offpeak.sh" --'

# old exact line -> new exact line (crontab uses $PROJ / $PY)
REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (
        "0 2 * * * cd $PROJ && flock -n /tmp/research_sched.lock $PY scripts/research_scheduler.py --mode cold-floor --apply --budget 20 >> logs/research_scheduler.log 2>&1",
        '0 10 * * * cd $PROJ && ' + WRAP + ' flock -n /tmp/research_sched.lock $PY scripts/research_scheduler.py --mode cold-floor --apply --budget 20 >> logs/research_scheduler.log 2>&1  # RETARGETED_OFFPEAK 2026-08-21 was 02:00 ET Peak B',
    ),
    (
        "50 2 * * * cd $PROJ && bash $PROJ/scripts/safe_flock.sh /tmp/hermes_outcome_grader.lock $PY scripts/hermes_outcome_grader.py --apply --max-rows 10000 >> logs/hermes_outcome_grader.log 2>&1",
        '50 10 * * * cd $PROJ && ' + WRAP + ' bash $PROJ/scripts/safe_flock.sh /tmp/hermes_outcome_grader.lock $PY scripts/hermes_outcome_grader.py --apply --max-rows 10000 >> logs/hermes_outcome_grader.log 2>&1  # RETARGETED_OFFPEAK 2026-08-21 was 02:50 ET Peak B',
    ),
    (
        "5 3 * * * cd $PROJ && bash $PROJ/scripts/safe_flock.sh /tmp/hermes_tag_engine.lock $PY scripts/hermes_tag_engine.py --apply >> logs/hermes_tag_engine.log 2>&1",
        '5 11 * * * cd $PROJ && ' + WRAP + ' bash $PROJ/scripts/safe_flock.sh /tmp/hermes_tag_engine.lock $PY scripts/hermes_tag_engine.py --apply >> logs/hermes_tag_engine.log 2>&1  # RETARGETED_OFFPEAK 2026-08-21 was 03:05 ET Peak B',
    ),
    (
        "25 3 * * * cd $PROJ && bash $PROJ/scripts/safe_flock.sh /tmp/hermes_outcome_feedback.lock $PY scripts/hermes_outcome_feedback_agent.py --apply >> logs/hermes_outcome_feedback.log 2>&1",
        '25 11 * * * cd $PROJ && ' + WRAP + ' bash $PROJ/scripts/safe_flock.sh /tmp/hermes_outcome_feedback.lock $PY scripts/hermes_outcome_feedback_agent.py --apply >> logs/hermes_outcome_feedback.log 2>&1  # RETARGETED_OFFPEAK 2026-08-21 was 03:25 ET Peak B',
    ),
    (
        "35 3 * * * cd $PROJ && bash $PROJ/scripts/safe_flock.sh /tmp/hermes_outcome_learning.lock $PY scripts/hermes_outcome_learning.py --apply >> logs/hermes_outcome_learning.log 2>&1",
        '35 11 * * * cd $PROJ && ' + WRAP + ' bash $PROJ/scripts/safe_flock.sh /tmp/hermes_outcome_learning.lock $PY scripts/hermes_outcome_learning.py --apply >> logs/hermes_outcome_learning.log 2>&1  # RETARGETED_OFFPEAK 2026-08-21 was 03:35 ET Peak B',
    ),
    (
        "35 3 * * * cd $PROJ && flock -n /tmp/hermes_score_retention.lock $PY scripts/hermes_score_history_retention.py --apply --days 21 >> logs/hermes_score_retention.log 2>&1",
        '40 11 * * * cd $PROJ && ' + WRAP + ' flock -n /tmp/hermes_score_retention.lock $PY scripts/hermes_score_history_retention.py --apply --days 21 >> logs/hermes_score_retention.log 2>&1  # RETARGETED_OFFPEAK 2026-08-21 was 03:35 ET Peak B',
    ),
    (
        "40 3 * * * cd $PROJ && flock -n /tmp/hermes_config_governor.lock $PY scripts/hermes_config_governor.py --apply >> logs/hermes_config_governor.log 2>&1",
        '45 11 * * * cd $PROJ && ' + WRAP + ' flock -n /tmp/hermes_config_governor.lock $PY scripts/hermes_config_governor.py --apply >> logs/hermes_config_governor.log 2>&1  # RETARGETED_OFFPEAK 2026-08-21 was 03:40 ET Peak B',
    ),
    (
        "0 21 * * 1-5 cd $PROJ && $PY scripts/auto_research.py --check --telegram >> logs/auto_research.log 2>&1",
        '0 20 * * 1-5 cd $PROJ && ' + WRAP + ' $PY scripts/auto_research.py --check --telegram >> logs/auto_research.log 2>&1  # RETARGETED_OFFPEAK 2026-08-21 was 21:00 ET Peak A',
    ),
    (
        "0 21 * * * cd $PROJ && $PY scripts/aegis_synthesis.py >> logs/aegis_synthesis.log 2>&1",
        '0 20 * * * cd $PROJ && ' + WRAP + ' $PY scripts/aegis_synthesis.py >> logs/aegis_synthesis.log 2>&1  # RETARGETED_OFFPEAK 2026-08-21 was 21:00 ET Peak A',
    ),
    (
        "0 21 * * 1-5 cd $PROJ && ALPACA_MODE=paper bash $PROJ/scripts/safe_flock.sh /tmp/structured_eval.lock $PY scripts/trade_close_llm_analyzer.py --structured --apply --confirm-llm-review-write --allow-local-llm --limit 12 >> logs/structured_eval.log 2>&1",
        '0 20 * * 1-5 cd $PROJ && ' + WRAP + ' env ALPACA_MODE=paper bash $PROJ/scripts/safe_flock.sh /tmp/structured_eval.lock $PY scripts/trade_close_llm_analyzer.py --structured --apply --confirm-llm-review-write --allow-local-llm --limit 12 >> logs/structured_eval.log 2>&1  # RETARGETED_OFFPEAK 2026-08-21 was 21:00 ET Peak A',
    ),
)


def load_crontab() -> str:
    proc = subprocess.run(["crontab", "-l"], check=True, capture_output=True, text=True)
    return proc.stdout


def patch(text: str) -> tuple[str, list[str], list[str]]:
    found: list[str] = []
    missing: list[str] = []
    out = text
    for old, new in REPLACEMENTS:
        if old in out:
            out = out.replace(old, new, 1)
            found.append(old[:80])
        else:
            missing.append(old[:80])
    return out, found, missing


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true")
    p.add_argument("--backup-dir", type=Path, default=Path.home() / "trade-ai-v12-rebuild" / "trade-ai-v12-rebuild")
    args = p.parse_args(argv)
    original = load_crontab()
    updated, found, missing = patch(original)
    print(f"authority={AUTHORITY}")
    print(f"matched={len(found)} missing={len(missing)}")
    for m in missing:
        print(f"MISSING {m}")
    for f in found:
        print(f"MATCH   {f}")
    if original == updated:
        print("no changes")
        return 0 if not missing else 2
    if not args.apply:
        print("dry-run (pass --apply to install)")
        return 0 if not missing else 2
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup = args.backup_dir / f"crontab_backup_pre_offpeak_retarget_{ts}.txt"
    backup.write_text(original, encoding="utf-8")
    tmp = Path("/tmp/tradeai_crontab_offpeak.txt")
    tmp.write_text(updated, encoding="utf-8")
    subprocess.run(["crontab", str(tmp)], check=True)
    print(f"applied backup={backup}")
    return 0 if not missing else 2


if __name__ == "__main__":
    raise SystemExit(main())
