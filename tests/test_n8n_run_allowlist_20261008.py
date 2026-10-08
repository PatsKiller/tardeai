"""config/n8n_run_allowlist.json safety (n8n scheduler-of-record tranche N1, 2026-10-08).

The allowlist is the only thing the run route can start, so it is tested as data: every command token
passes pipeline_manifest.FORBIDDEN_COMMAND_TOKENS and the gateway's FORBIDDEN_ROUTE_TOKENS substring test;
no command names a broker, order, send, secret-render, guard or deploy script; every entry carries a lock,
a timeout and at least one mode argument; the seven N1 lanes are present with their registry output_signal."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import n8n_coordination_gateway as G  # noqa: E402
from scripts import n8n_run_executor as X  # noqa: E402
from scripts.pipelines import pipeline_manifest as PM  # noqa: E402

DOC = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text(encoding="utf-8"))
LANES = {e["lane_id"]: e for e in DOC["lanes"]}
N1 = {
    "n8n-pilot-dispatch": "data/runtime/n8n_pilot_dispatch_last.json",
    "n8n-incident-fanin": "data/runtime/n8n_incident_fanin_last.json",
    "n8n-research-intake-consumer": "data/runtime/n8n_research_intake_last.json",
    "crontab-snapshot-for-health-agent": "data/runtime/crontab_snapshot.txt",
    "n8n-lab-watchdog": "data/runtime/n8n_lab_watchdog_last.json",
    "lane-governance-packet-weekly": "data/runtime/lane_governance_packet_last.json",
    "maturity-remeasure": "data/governance/maturity_latest.json",
}
NEVER = (
    "place_order",
    "alpaca",
    "schwab",
    "moomoo",
    "snaptrade",
    "render_env",
    "sm-render",
    "sm_render",
    "guard",
    "cio_phase2_exact_main_deploy",
    "telegram_alert",
    "send_telegram",
    "telegram_send",
    "cio_telegram",
    "notify",
    "deploy",
    "promote",
    "rotation_daemon",
    "secrets/",
)


def _tokens(entry: dict) -> list[str]:
    return [
        *entry["command"],
        *(entry.get("dry_run_arg") or []),
        *(entry.get("live_arg") or []),
        entry["lock"],
        entry.get("output_signal") or "",
    ]


def _route_forbidden(token: str) -> str | None:
    """The gateway's substring test, applied to a command token instead of a route."""
    text = token.strip().lower()
    for tok in (t for t in re.split(r"[^a-z0-9]+", text) if t):
        if tok in G.FORBIDDEN_ROUTE_TOKENS:
            return tok
    collapsed = text.replace("-", "").replace("/", "")
    for tok in G.FORBIDDEN_ROUTE_TOKENS:
        if tok in collapsed and tok != "title":
            return tok
    return None


def test_schema_and_every_entry_is_runnable_by_the_executor():
    assert DOC["schema"] == "N8nRunAllowlist@v1"
    assert LANES, "empty allowlist"
    for lane_id, entry in LANES.items():
        assert X.validate_entry(entry) is None, (lane_id, X.validate_entry(entry))
        assert entry["lock"].startswith("/tmp/"), lane_id
        assert entry["timeout_s"] > 0, lane_id
        assert entry.get("dry_run_arg") is not None or entry.get("live_arg") is not None, lane_id
    assert set(X.load_allowlist(ROOT / "config" / "n8n_run_allowlist.json")) == set(LANES)


def test_the_seven_n1_lanes_are_seeded_with_their_registry_output_signals():
    assert set(N1) <= set(LANES)
    for lane_id, signal in N1.items():
        assert LANES[lane_id]["output_signal"] == signal, lane_id
    registry = json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))
    rows = {r["lane_id"]: r for r in registry["lanes"]}
    for lane_id in N1:
        assert lane_id in rows, f"{lane_id} has no registry row"
        sig = rows[lane_id].get("output_signal", {}).get("path", "")
        assert sig.endswith(LANES[lane_id]["output_signal"]), (lane_id, sig)


def test_every_command_token_passes_both_forbidden_lists_and_names_no_authority_script():
    for lane_id, entry in LANES.items():
        for token in _tokens(entry):
            low = token.lower()
            for forbidden in PM.FORBIDDEN_COMMAND_TOKENS:
                assert forbidden not in token, (lane_id, token, forbidden)
            hit = _route_forbidden(token)
            assert hit is None, (lane_id, token, hit)
            for never in NEVER:
                assert never not in low, (lane_id, token, never)
        assert "market_day_gate" not in json.dumps(entry["command"])  # the executor prepends the gate from the flag


def test_commands_run_repo_scripts_or_crontab_only_and_mode_args_differ():
    for lane_id, entry in LANES.items():
        cmd = entry["command"]
        if cmd[0] == "$PY":
            assert cmd[1].startswith("scripts/") and (ROOT / cmd[1]).is_file(), (lane_id, cmd[1])
        else:
            assert cmd[:2] == ["bash", "-c"] and cmd[2].startswith("crontab -l"), (lane_id, cmd)
        if entry.get("dry_run_arg") is not None and entry.get("live_arg") is not None:
            assert entry["dry_run_arg"] != entry["live_arg"], lane_id


def test_dry_run_arguments_match_each_scripts_argparse():
    """--dry-run/--apply/--write exist on the script they are passed to (no invented flags)."""
    for lane_id, entry in LANES.items():
        if entry["command"][0] != "$PY":
            continue
        src = (ROOT / entry["command"][1]).read_text(encoding="utf-8")
        for arg in [*(entry.get("dry_run_arg") or []), *(entry.get("live_arg") or [])]:
            if arg.startswith("--"):
                assert f'"{arg}"' in src, (lane_id, arg)


def test_pending_tranches_list_lane_ids_without_commands_and_the_never_list_is_stated():
    pending = DOC["pending_tranches"]
    for tranche in ("N2", "N3", "N4", "N5", "N6"):
        assert isinstance(pending[tranche], list) and pending[tranche], tranche
        assert not set(pending[tranche]) & set(LANES), tranche  # pending means not runnable
    assert len(pending["N2"]) == 17 and len(pending["N3"]) == 12 and len(pending["N4"]) == 20
    assert "broker" in DOC["never"] and "sm-render" in DOC["never"]


def test_json_is_the_only_source_of_commands_in_the_executor():
    src = (ROOT / "scripts" / "n8n_run_executor.py").read_text(encoding="utf-8")
    assert "scripts/safe_flock.sh" in src and "scripts/market_day_gate.sh" in src
    for never in ("place_order", "alpaca", "schwab", "moomoo", "snaptrade", "telegram"):
        assert never not in src.lower(), never
    assert "import socket" not in src and "bind(" not in src and "http.server" not in src
