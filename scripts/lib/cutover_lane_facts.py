"""cutover_lane_facts.py — the pure lane facts of the n8n cutover factory, shared by scripts/n8n_cutover_wave.py and
the nightly cutover controller (scripts/lib/nightly_cutover.py), 2026-10-16.

Moved verbatim out of scripts/n8n_cutover_wave.py (which re-exports every name, so its API is unchanged) so the
controller's import closure does not reach the wave tool's executor validation import (lane transitive-capability
scan, tests/test_lane_transitive_capabilities_20261015.py). Disposition scope, cron-line matching, the effect tiers,
the sender test and the retire tag. Pure apart from load_disposition (one CSV read).

AUTHORITY: READ_ONLY_ADVISORY.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from scripts.lib import lane_dispatch as LD

NO_CONSUMER_REASON = "Library of scripts/n8n_cutover_wave.py and scripts/lib/nightly_cutover.py."

DISPOSITION_CSV = Path("docs/implementation/n8n-maturity/LANE_DISPOSITION_20261015.csv")
REGISTRY = Path("config/lane_registry.json")
ALLOWLIST = Path("config/n8n_run_allowlist.json")
CONTRACTS = Path("config/n8n_health_contracts.json")
EFFECT_KEYS = Path("config/n8n_effect_keys.json")
RETRY_POLICIES = Path("config/n8n_retry_policies.json")

#: Families the 2026-10-15 directive approved (F07 and registry_systemd are deferred; CONSOLIDATE rows are elsewhere).
DEFERRED_FAMILIES = frozenset({"F07"})
DEFERRED_SOURCES = frozenset({"registry_systemd"})
SCOPE_DISPOSITIONS = ("MIGRATE_N8N", "STAY_HOST")

TIER_READ = 1
TIER_APPEND = 2
TIER_SEND = 3
TIER_LLM = 4
TIER_WATCHDOG = 5
TIER_BROKER = 6
TIER_NAMES = {1: "read/overwrite", 2: "append", 3: "send", 4: "llm", 5: "watchdog", 6: "broker"}
SEND_FAMILIES = frozenset({"F10", "F37", "F22"})
LLM_FAMILIES = frozenset({"F40"})
WATCHDOG_FAMILIES = frozenset({"F07w"})
BROKER_FAMILIES = frozenset({"F09"})
#: Classes whose live run writes rows (append) unless the lane is known overwrite-only. Conservative: pipeline/heavy
#: are treated as appenders; monitor/report/hygiene as overwrite-only.
APPEND_CLASSES = frozenset({"ingest", "learn", "pipeline", "heavy"})

#: Shell operators that end the lane's argv on a cron line.
_ARGV_STOP = frozenset({">>", ">", "2>&1", "2>>", "2>", "|", "||", "&&", ";", "&", "1>", "1>>", "<"})
#: Tokens allowed BEFORE the lane command on a cron line (the executor reproduces each one or it is inert).
_PREFIX_OK = re.compile(
    r"^(cd|&&|\$PROJ|\$PY|python3?|/usr/bin/python3|bash|/usr/bin/bash|/bin/bash|sh|exec|nice|-n|\d+|"
    r"CUR=.*|\"\$CUR\"|\$CUR|/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT|"
    r"/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/\.venv/bin/python|"
    r"/usr/bin/flock|flock|-[nxwE]|--nonblock|timeout|-k|\d+[smh]?)$"
)
_MARKET_GATE = "scripts/market_day_gate.sh"
_OFFPEAK_WRAPPER = "scripts/run_with_deepseek_offpeak.sh"
_OFFPEAK_FLAGS = {"--gate": "bulk", "--official": "official", "--scheduled": "scheduled"}
#: Lanes whose LIVE effect only overwrites or reads (no effect key). Source: the read-only code trace of
#: CANARY_DOUBLE_EFFECT_AUDIT.md (2026-10-15; tests/test_canary_effect_keys_20261015.py NOT_KEYED_OVERWRITE_ONLY),
#: plus this factory's own trace (marked CW).
OVERWRITE_ONLY = {
    "crontab-snapshot-for-health-agent": "tmp + mv of the crontab snapshot",
    "job-coverage-monitor": "read-only check; receipt only",
    "identity-sweep-stage0": "UPDATE ... WHERE subject_guid IS NULL",
    "agent-number-grounding-slo": "SELECT-only report; --out JSON receipt",
    "finviz-sector-research": "ON CONFLICT (snapshot_date, group_type, name) DO UPDATE",
    "momentum-cache-reconcile": "atomic projection rewrite",
    "watch-goods-consistency": "UPDATE ... COALESCE fills empty fields",
    "catalyst-graph": "atomic projection rewrite",
    "classifier-health-check": "read-only session; atomic JSON",
    "enterprise-backtester": "no --apply on the line: OHLC cache overwrite only",
    "setup-quality-prior": "TRUNCATE + rebuild",
    "classify-instruments": "symbol_profiles ON CONFLICT (symbol) DO UPDATE",
    "sector-rs-daily": "ON CONFLICT (rs_date, symbol) DO UPDATE",
    "finviz-enrichment": "atomic cache replace + entity upsert",
    "trade-backtest-engine": "ON CONFLICT (trade_key) DO UPDATE",
    "sync-social-to-intelligence": "entity UPDATE (signal_count counter, no new row)",
    "aegis-brief-regenerate": "rewrites the day's brief export; no send",
    "momentum-lifecycle-monitor": "read-only evaluate (no --write-monitor)",
    "hermes-governance-api": "CW: os.replace of the governance panel cache (scripts/hermes_governance_api.py:86)",
    "materialize-watchlist-strategy-cards": "CW: INSERT ... ON CONFLICT (symbol) DO UPDATE (:60-65)",
}
#: Lanes held off canary on purpose (verdict SKIP with this reason).
HELD = {
    "aegis-nightly-ingestion": "held: the n8n reference workflow's inert lane (scripts/build_n8n_reference_workflow.py "
                               "LANE; its allowlist live_arg must stay null and its effect key unarmed)",
}
#: Lanes whose class reads as overwrite-only but whose live effect appends (keyed).
APPEND_OVERRIDE = {
    "journal-tilt-morning-hook": "CW: INSERT INTO operator_review_queue (scripts/journal_tilt_morning_hook.py:44)",
}
_SENDER = re.compile(r"(?<![a-z0-9])--(alert|send|telegram|notify|email)(?![a-z0-9])")
#: The cron-side effect-claim wrapper (scripts/effect_claim_cron.sh, #1767 canary effect keys).
EFFECT_CLAIM_WRAPPER = "effect_claim_cron.sh"


def is_sender_lane(disp: Mapping[str, str], row: Mapping[str, Any], effect_keys: Mapping[str, Any],
                   line_text: str) -> bool:
    """A lane whose run can message the operator: a send family, a sender flag on the cron line, a `send` effect
    key, or a lifted sender token (§23.25 send/telegram/sender). Pure."""
    effects = set((effect_keys.get(row.get("lane_id")) or {}).get("effects") or [])
    if (disp.get("family_id") or "") in SEND_FAMILIES or _SENDER.search(line_text or "") or "send" in effects:
        return True
    return bool({t for t, _ in LD.forbidden_hits(row)} & LD.CUTOVER_SENDER_TOKENS)

def load_disposition(code_root: Path) -> list[dict[str, str]]:
    with open(code_root / DISPOSITION_CSV, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def scope_rows(rows: Iterable[Mapping[str, str]]) -> list[Mapping[str, str]]:
    """The directive's scope: MIGRATE_N8N + STAY_HOST, minus F07 and registry_systemd. One row per lane id (the first
    crontab row wins; a lane with several lines is one lane)."""
    seen: dict[str, Mapping[str, str]] = {}
    for r in rows:
        if r.get("disposition") not in SCOPE_DISPOSITIONS:
            continue
        if r.get("family_id") in DEFERRED_FAMILIES or r.get("source") in DEFERRED_SOURCES:
            continue
        lid = r.get("lane_id") or ""
        if lid and lid not in seen:
            seen[lid] = r
    return list(seen.values())

def matches_of(sched: Mapping[str, Any]) -> list[str]:
    raw = sched.get("match") or ""
    if isinstance(raw, list):
        return [str(x) for x in raw if str(x)]
    return [str(raw)] if str(raw) else []


def live_lines(crontab: str, sched: Mapping[str, Any]) -> tuple[list[tuple[int, str]], list[str]]:
    """((index, line) of every uncommented crontab line the row's match names, problems)."""
    lines = crontab.splitlines()
    out: list[tuple[int, str]] = []
    problems: list[str] = []
    ms = matches_of(sched)
    if not ms:
        return [], ["registry_row_has_no_scheduler_match"]
    for m in ms:
        hit = [(i, ln) for i, ln in enumerate(lines) if m in ln and not ln.lstrip().startswith("#")
               and not re.match(r"^\s*[A-Za-z_][A-Za-z0-9_]*=", ln)]
        if not hit:
            problems.append(f"no_live_cron_line_for_match:{m!r}")
        out.extend(h for h in hit if h not in out)
    if len(ms) == 1 and len(out) > 1:
        problems.append(f"match_hits_{len(out)}_lines:{ms[0]!r} (needs a list match, one item per line)")
    return out, problems

def tier_of(disp: Mapping[str, str], row: Mapping[str, Any], entry: Optional[Mapping[str, Any]],
            effect_keys: Mapping[str, Any], line_text: str) -> int:
    fam = disp.get("family_id") or ""
    if fam in BROKER_FAMILIES:
        return TIER_BROKER
    if fam in WATCHDOG_FAMILIES:
        return TIER_WATCHDOG
    klass = (row.get("dispatch") or {}).get("class") if isinstance(row.get("dispatch"), dict) else None
    if fam in LLM_FAMILIES or klass == "llm" or (entry or {}).get("llm_route"):
        return TIER_LLM
    effects = set((effect_keys.get(row.get("lane_id")) or {}).get("effects") or [])
    if "llm" in effects:
        return TIER_LLM
    if fam in SEND_FAMILIES or _SENDER.search(line_text or "") or "send" in effects:
        return TIER_SEND
    if row.get("lane_id") in APPEND_OVERRIDE:
        return TIER_APPEND
    if row.get("lane_id") in OVERWRITE_ONLY:
        return TIER_READ
    if row.get("lane_id") in effect_keys or klass in APPEND_CLASSES:
        return TIER_APPEND
    return TIER_READ


TAG = "# RETIRED {date} n8n-cutover {lane} "
