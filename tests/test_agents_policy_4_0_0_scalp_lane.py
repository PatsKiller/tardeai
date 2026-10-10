"""AGENTS.md 4.0.0 — the one n8n live-lane exception, `trade-ai-scalp-live` (§23.3), ratified 2026-10-09.

Operator 2026-10-09 15:25 ET in session: "APPROVE_AGENTS_POLICY_4_0_0 and build the finviz API fix", after
"n8n drives a governed lane (Recommended)". The failure this guards against: a named exception that quietly
becomes a class — a second ingest writer or sender entering the allowlist "by analogy", or the scalp lane's
live argv drifting from the cron line so n8n runs something cron never did. Also pins the ratification record
and that the stale "awaiting APPROVE_AGENTS_POLICY_3_0_0 … 2.0.1 governs" sentence left by #1552 is gone.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts import check_agents_policy_state as C  # noqa: E402

AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
ALLOW = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text(encoding="utf-8"))
REG = {r["lane_id"]: r for r in json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))["lanes"]}
ADR = (ROOT / "docs/architecture/n8n/ADR_COORDINATION_SECRETS.md").read_text(encoding="utf-8")
LANE = "trade-ai-scalp-live"
TOKEN = "APPROVE_AGENTS_POLICY_4_0_0"
OPERATOR_WORDS = "APPROVE_AGENTS_POLICY_4_0_0 and build the finviz API fix"


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _control(key: str) -> str:
    m = re.search(rf"^{re.escape(key)}:\s+(\S+)", AGENTS, re.M)
    assert m, key
    return m.group(1)


def _section_23() -> str:
    m = re.search(r"^# 23 · .*?(?=^# Version history)", AGENTS, re.M | re.S)
    assert m
    return m.group(0)


def test_header_is_4_0_0_active_and_the_state_checker_passes():
    v = tuple(int(x) for x in _control("Policy-Version").split("."))
    assert v >= (4, 0, 0)
    if v == (4, 0, 0):
        assert _control("Status") == "ACTIVE" and _control("Effective-Date") == "2026-10-09"
        assert _control("Supersedes") == "3.0.0"
    assert C.check(AGENTS, on_main=True) == []
    assert C.check(AGENTS, on_main=False) == []


def test_version_row_records_token_and_operator_words():
    m = re.search(r"^\| 4\.0\.0 \| 2026-10-09 \| ACTIVE \| MAJOR \|(.*)$", AGENTS, re.M)
    assert m, "no 4.0.0 ACTIVE MAJOR row"
    assert TOKEN in m.group(1) and OPERATOR_WORDS in m.group(1)
    assert "trade-ai-scalp-live" in m.group(1)
    assert _flat(OPERATOR_WORDS) in _flat(AGENTS.split("```", 2)[2][:3000])      # top-of-file record


def test_section_23_status_line_is_current():
    s = _flat(_section_23())
    assert re.search(r"^# 23 · .*— ACTIVE 4\.(?:0\.0|1\.0|3\.0|4\.0)$", _section_23(), re.M)  # 4.1.0 ratified 2026-10-09; 4.3.0, 4.4.0 2026-10-10
    assert "awaiting `APPROVE_AGENTS_POLICY_3_0_0 <pr> <sha>`" not in s
    assert "Until then the 2.0.1 text of those subsections governs" not in s
    assert "APPROVE_AGENTS_POLICY_3_0_0 1547 a0984546181d316f92931c7b87218b55b3b836d9" in s


def test_exception_bullet_names_exactly_one_lane_and_its_conditions():
    m = re.search(r"^## 23\.3 .*?(?=^## )", _section_23(), re.M | re.S)
    assert m
    s = _flat(m.group(0))
    assert "**Exception (4.0.0) — `trade-ai-scalp-live` only.**" in s
    for frag in ("/tmp/tradeai_scalp_live.lock", "`timeout_s` 295", "market_day_gate.sh", "n8n holds no provider key",
                 "send_telegram", "TRADEAI_N8N_RELAY_LIVE_LANES", "3 market days",
                 "No other ingest writer or sender enters the allowlist by analogy"):
        assert frag in s, frag
    assert s.count("**Exception (") == 1


def test_allowlist_matches_the_exception_and_the_cron_line():
    entry = next(e for e in ALLOW["lanes"] if e["lane_id"] == LANE)
    assert entry["live_arg"] == [] and entry["dry_run_arg"] == ["--dry-run"]
    assert entry["command"] == ["$PY", "scripts/run_trade_ai_scalp_live.py"]
    assert entry["lock"] == "/tmp/tradeai_scalp_live.lock" and entry["lock_kind"] == "flock"
    assert entry["timeout_s"] == 295 and entry["market_gate"] is True
    cron = REG[LANE]["scheduler"]
    assert cron["kind"] == "cron"                                       # cron stays the fallback scheduler
    for frag in ("flock -n /tmp/tradeai_scalp_live.lock", "timeout 295", "market_day_gate.sh",
                 "scripts/run_trade_ai_scalp_live.py >>"):
        assert frag in cron["expression"] + " " + cron.get("command_text", ""), frag  # registry-ops-crons 2026-10-09: bare schedule + command_text
    assert "Sole exception: trade-ai-scalp-live" in ALLOW["never"]
    assert "LIVE CANDIDATE" in REG[LANE]["note"]


def test_no_other_allowlisted_lane_is_a_sender_or_ingest_writer():
    """The exception is a name, not a class: no other entry may point at the scan cycle or a sender."""
    for e in ALLOW["lanes"]:
        if e["lane_id"] == LANE:
            continue
        toks = " ".join([*e["command"], *(e.get("live_arg") or []), *(e.get("dry_run_arg") or [])])
        for bad in ("run_trade_ai_scalp_live", "continuous_runner", "finviz_ingestion", "send_telegram"):
            assert bad not in toks, (e["lane_id"], bad)


def test_adr_records_no_new_credential():
    assert "amended by 3.0.0 PROPOSED" not in ADR
    assert "## Addendum — AGENTS.md 4.0.0" in ADR
    add = ADR.split("## Addendum — AGENTS.md 4.0.0", 1)[1]
    assert "No credential is added or changed" in add and "never enters n8n" in add
