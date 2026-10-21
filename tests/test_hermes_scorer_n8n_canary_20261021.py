"""hermes-watchlist-scorer n8n CANARY 2026-10-21 (operator waiver).

Operator 2026-10-21 ~13:05 ET, verbatim: "push live now" (shadow -> canary today, waiving the usual 3-market-day
shadow evidence wait), then "comment out whats working now this can be a fallback". The release ships the canary
shape (AGENTS.md §23.11 4.4.0, §23.12): a cron row at stage canary, dispatch.mode live, allowlist live_arg [] so the
live argv equals the cron argv, and the allowlist lock equal to cron L451's flock lock, so n8n and cron never
double-run. Canary, not cutover, because the cron line stays installed until the first live n8n RUN_DONE, and a
`kind: n8n` row with its cron line live fails CRON_PRESENT_WHILE_SCHEDULER_N8N (check_lane_registry --state-drift)
and CUTOVER_CRON_LINE_ACTIVE (check_registry_runtime_truth). The cron line is retired by
docs/ops/packets/hermes-scorer-canary-20261021/02_retire_cron_line.sh; the row moves to cutover in the next PR.
Hermetic: reads config only.
"""
from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

COVERS = ["config/lane_registry.json", "config/n8n_run_allowlist.json", "config/n8n_health_contracts.json"]

LANE = "hermes-watchlist-scorer"
LOCK = "/tmp/hermes_scorer.lock"
PACKET = ROOT / "docs" / "ops" / "packets" / "hermes-scorer-canary-20261021"


def _row():
    return next(r for r in json.loads((ROOT / "config/lane_registry.json").read_text())["lanes"]
                if r.get("lane_id") == LANE)


def _entry():
    return next(e for e in json.loads((ROOT / "config/n8n_run_allowlist.json").read_text())["lanes"]
                if e["lane_id"] == LANE)


def _contract():
    return next(c for c in json.loads((ROOT / "config/n8n_health_contracts.json").read_text())["contracts"]
                if c.get("id") == LANE)


def test_registry_row_is_a_cron_canary_in_live_mode():
    row = _row()
    sch = row["scheduler"]
    assert (sch["kind"], sch["stage"], row["dispatch"]["mode"]) == ("cron", "canary", "live")
    assert row["dispatch"]["cron"] == [sch["expression"]] == ["*/15 * * * *"]
    assert "push live now" in row["canary"]["operator_waiver"]
    assert "comment out whats working now this can be a fallback" in row["canary"]["operator_waiver"]


def test_live_argv_equals_the_cron_argv():
    e = _entry()
    assert e["live_arg"] == []
    live_argv = [*e["command"], *e["live_arg"]]
    cron = shlex.split(_row()["scheduler"]["command_text"].split(">>")[0])
    assert cron[cron.index("$PY"):] == live_argv == ["$PY", "scripts/hermes_watchlist_scorer.py", "--once"]


def test_allowlist_lock_is_the_cron_flock_lock():
    from scripts.lib import lane_dispatch as LD
    e = _entry()
    assert (e["lock"], e["lock_kind"]) == (LOCK, "flock")
    assert LD.cron_flock_locks(_row()["scheduler"]["command_text"]) == [LOCK]
    ok, why = LD.r1_canary_lock_matches(_row(), e)
    assert ok, why


def test_contract_is_operator_reviewed_at_canary_without_unknown():
    c = _contract()
    assert (c["stage"], c["status"], c["review"]["status"]) == ("canary", "REVIEWED", "REVIEWED")
    assert c["review"]["reviewed_by"].startswith("operator ")
    assert "push live now" in c["review"]["stage_rereview"]["operator_words"]
    assert "UNKNOWN" not in json.dumps(c)
    assert any(h["check"] == "canary_live_done" for h in c["healthy"])
    assert not any(h["check"] == "shadow_dry_run_done" for h in c["healthy"])


def test_effect_key_is_staged_and_arms_neither_side():
    """A shared flock stops overlap, not a second run in the same slot (canary double-effect audit 2026-10-15): the
    appending scorer carries a STAGED key; nothing claims until its cutover arms it."""
    from scripts.lib import effect_claim as E
    cfg = ROOT / "config" / "n8n_effect_keys.json"
    spec = json.loads(cfg.read_text())["lanes"][LANE]
    assert (spec["cron_claim"], spec["n8n_claim"], spec["effects"]) == (False, False, ["append"])
    assert spec["schedule"] == "*/15 * * * *" and spec["slot"] == "scheduled_minute"
    assert LANE not in E.load_effect_config(cfg)


def test_lane_is_not_cut_over_while_cron_l451_is_installed():
    assert _row()["scheduler"]["kind"] == "cron" and _row()["scheduler"].get("expression") != "dispatcher"


def test_operator_packet_is_dry_run_by_default():
    for name in ("01_live_list_add.sh", "02_retire_cron_line.sh", "03_fallback.sh"):
        text = (PACKET / name).read_text()
        assert 'APPLY=0' in text and "--apply" in text, name
        assert "place_order" not in text and "crontab -r" not in text, name
    assert "hermes-watchlist-scorer" in (PACKET / "01_live_list_add.sh").read_text()
