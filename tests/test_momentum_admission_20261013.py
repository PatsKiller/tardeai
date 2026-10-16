"""Offline stage-shaped admission; no financial runner, credential or host operation."""

import copy
import json
from datetime import date, datetime
from pathlib import Path

import pytest

from scripts.lib import lane_dispatch as D
from scripts.lib import lane_registry as L
from scripts.lib import n8n_health_contracts as H
from scripts.lib import n8n_momentum_lifecycle as M
from scripts.lib.n8n_due import compute_due
from scripts.lib.n8n_retry_policy import load_policies
from scripts.lib.lane_stage_clamp import clamp_mode
from scripts import n8n_run_executor as E

ROOT = Path(__file__).resolve().parents[1]
IDS = ("momentum-lifecycle-monitor", "momentum-cache-reconcile", "trade-ai-scalp-live")


def source():
    registry = json.loads((ROOT / "config/lane_registry.json").read_text())
    allow = json.loads((ROOT / "config/n8n_run_allowlist.json").read_text())
    contracts = json.loads((ROOT / "config/n8n_health_contracts.json").read_text())
    return (
        {r["lane_id"]: r for r in registry["lanes"]},
        {a["lane_id"]: a for a in allow["lanes"]},
        {c["id"]: c for c in contracts["contracts"]},
    )


def reviewed(contract):
    contract = copy.deepcopy(contract)
    contract.update(status="REVIEWED", ownership_confirmation="OWNER_ACCEPTED")
    contract["review"] = {"reviewed_by": "TEST_ONLY_OWNER", "decision_ref": "fixture://body-review"}
    contract["review"]["contract_body_sha256"] = M.contract_body_digest(contract)
    return contract


def test_current_admission_is_structurally_valid_and_unreviewed_work_stays_off(monkeypatch):
    rows, allow, contracts = source()
    monkeypatch.setenv(
        "TRADEAI_N8N_RELAY_LIVE_LANES",
        " ".join(lane for lane in IDS if rows[lane]["dispatch"]["mode"] == "live"),
    )
    for lane in IDS:
        assert L.validate_row(rows[lane]) == []
        assert D.validate_dispatch_block(rows[lane]) == []
        assert E.validate_entry(allow[lane]) is None
        assert H.validate_contract(contracts[lane]) == []
        if contracts[lane]["status"] == "DRAFT":
            assert rows[lane]["dispatch"]["mode"] == "off"
            assert not M.contract_review_proven(contracts[lane])
            assert contracts[lane]["review"]["reviewed_by"] is None
        else:
            assert M.contract_review_proven(contracts[lane])
    response = compute_due(
        [rows[lane] for lane in IDS], allow, load_policies(), None, datetime.fromisoformat("2026-10-13T09:30:00-04:00")
    )
    assert response["errors"] == []
    assert all(item["mode"] == rows[item["lane_id"]]["dispatch"]["mode"] for item in response["items"])
    assert not any(
        item["lane_id"] == lane for lane in IDS if rows[lane]["dispatch"]["mode"] == "off" for item in response["items"]
    )


@pytest.mark.parametrize("lane", IDS)
def test_shadow_and_canary_keep_natural_slot_identity_and_original_lock(lane, tmp_path, monkeypatch):
    rows, allow, _ = source()
    row, entry = copy.deepcopy(rows[lane]), copy.deepcopy(allow[lane])
    row["state"] = "ACTIVE"
    row["dispatch"]["mode"] = "dry_run"
    row["scheduler"]["stage"] = "shadow"
    if lane != "trade-ai-scalp-live":
        entry["live_arg"] = None
    assert clamp_mode(lane, "live", [row])["effective_mode"] == "dry_run"
    now = datetime.fromisoformat("2026-10-13T09:30:00-04:00")
    response = compute_due([row], {lane: entry}, load_policies(), None, now)
    assert response["errors"] == []
    assert response["items"][0]["idempotency_key"] == f"d:{lane}:dry_run:20261013T0930"
    dry = E.build_argv(
        entry, "dry_run", env={"TRADEAI_VENV_PYTHON": "fixture-python"}, state_root=tmp_path, code_root=tmp_path
    )
    assert entry["lock"] + ".dryrun" in dry and "--dry-run" in dry
    row["scheduler"]["stage"] = "canary"
    row["dispatch"]["mode"] = "live"
    monkeypatch.setenv("TRADEAI_N8N_RELAY_LIVE_LANES", lane)
    entry["live_arg"] = (
        []
        if lane == "trade-ai-scalp-live"
        else ["--write-monitor" if lane == "momentum-lifecycle-monitor" else "--apply"]
    )
    response = compute_due([row], {lane: entry}, load_policies(), None, now)
    assert response["errors"] == []
    assert response["items"][0]["idempotency_key"] == f"d:{lane}:live:20261013T0930"
    live = E.build_argv(
        entry, "live", env={"TRADEAI_VENV_PYTHON": "fixture-python"}, state_root=tmp_path, code_root=tmp_path
    )
    assert entry["lock"] in live and entry["lock"] + ".dryrun" not in live


def test_helper_canary_does_not_arm_autonomous_recovery():
    rows, allow, contracts = source()
    lane = "momentum-cache-reconcile"
    rows[lane]["state"] = "ACTIVE"
    rows[lane]["scheduler"]["stage"] = "canary"
    allow[lane]["live_arg"] = ["--apply"]
    contracts[lane] = reviewed(contracts[lane])
    admission = M.Admission(rows, contracts, allow, load_policies(), "a" * 40, {})
    assert M.cache_helper_admitted(admission, lane)
    assert not M.recovery_admitted(admission, lane)
    policy = json.loads((ROOT / "config/n8n_momentum_lifecycle_candidate.json").read_text())
    # Candidate recovery.armed gates explicit --apply; autonomous recovery_admitted stays cutover-only.
    assert policy["recovery"]["armed"] is True
    assert policy["credential_recovery"]["automatic"] is False
    assert policy["enabled"] is True


def test_actual_helper_apply_refuses_while_recovery_remains_disarmed(tmp_path):
    from scripts import momentum_cache_reconcile as helper

    rows, allow, contracts = source()
    lane = "momentum-cache-reconcile"
    rows[lane]["state"] = "ACTIVE"
    rows[lane]["scheduler"]["stage"] = "canary"
    allow[lane]["live_arg"] = ["--apply"]
    contracts[lane] = reviewed(contracts[lane])
    code, state = tmp_path / "code", tmp_path / "state"
    (code / "config").mkdir(parents=True)
    state.mkdir()
    (code / "SOURCE_COMMIT").write_text("a" * 40)
    docs = {
        "lane_registry": {"lanes": [rows[lane]]},
        "n8n_run_allowlist": {"lanes": [allow[lane]]},
        "n8n_health_contracts": {"contracts": [contracts[lane]]},
        "n8n_momentum_lifecycle_candidate": {"enabled": True, "recovery": {"armed": False}},
    }
    for name, document in docs.items():
        (code / f"config/{name}.json").write_text(json.dumps(document))
    (code / "config/n8n_retry_policies.json").write_bytes((ROOT / "config/n8n_retry_policies.json").read_bytes())
    result = helper.reconcile(
        code_root=code, state_root=state, now=datetime.fromisoformat("2026-10-13T06:00:00-04:00"), apply=True
    )
    assert result["status"] == "REFUSED" and result["reason"] == "operative_recovery_admission_unproven"
    assert list(state.iterdir()) == []
    assert result["canonical_business_writes"] == 0 and result["provider_calls"] == 0


def test_real_owner_body_review_is_required_for_monitor_publication():
    rows, allow, contracts = source()
    lane = "momentum-lifecycle-monitor"
    rows[lane]["state"] = "ACTIVE"
    rows[lane]["scheduler"]["stage"] = "canary"
    allow[lane]["live_arg"] = ["--write-monitor"]
    contracts[lane]["status"] = "DRAFT"
    admission = M.Admission(rows, contracts, allow, load_policies(), "a" * 40, {})
    assert not M.monitor_admitted(admission)
    contracts[lane] = reviewed(contracts[lane])
    assert M.monitor_admitted(admission)
    contracts[lane]["owner"] = "changed-after-review"
    assert not M.monitor_admitted(admission)


def test_named_scalp_exception_preserves_every_admitted_argument_and_gate():
    rows, allow, _ = source()
    lane = "trade-ai-scalp-live"
    entry = allow[lane]
    assert entry["command"] == ["$PY", "scripts/run_trade_ai_scalp_live.py"]
    assert entry["live_arg"] == [] and entry["dry_run_arg"] == ["--dry-run"]
    assert entry["lock"] == "/tmp/tradeai_scalp_live.lock" and entry["lock_kind"] == "flock"
    assert entry["timeout_s"] == 295 and entry["market_gate"] is True
    assert D.dispatch_eligible(rows[lane], allowlist_argv={lane: " ".join(entry["command"])})[0]
    assert rows[lane]["scheduler"]["kind"] == "cron"
    assert rows[lane]["scheduler"]["expression"] == "*/5 9-15 * * 1-5"


def test_other_business_and_credential_lanes_are_not_promoted():
    rows, allow, _ = source()
    for lane in ("finviz-market-movers", "finviz-screener-runner", "daily-incubator-refresh"):
        if lane in _CW_PROMOTED:
            # 2026-10-15 operator directive ("N8N Cutover Decision"): promoted to canary by an n8n cutover wave; its
            # canary shape is pinned by tests/test_n8n_cutover_wave_20261015.py, not by this momentum review.
            continue
        assert rows[lane]["dispatch"]["mode"] == "dry_run"
        assert allow[lane]["live_arg"] is None
        assert allow[lane]["env_allowlist_mode"] == "report"
    for lane in (
        "finviz-momentum-scalp-early-lane",
        "auto-proposal-general",
        "momentum-scalp-advisory-alerts",
        "warm-caches",
        "orchestrator-slot",
        "youtube-cookie-health-check",
        "youtube-transcript-ingest",
        "incubator-proposal-promoter",
    ):
        assert lane not in allow
        assert D.dispatch_mode(rows[lane]) == "off"


def test_new_drafts_are_not_grandfathered_or_claimed_accepted():
    rows, _, contracts = source()
    selected = [contracts[c] for c in (*IDS, "tradeai-momentum-lifecycle-candidate")]
    result = H.check({"contracts": selected}, {"lanes": [rows[c] for c in IDS]}, {"workflows": []}, date(2026, 10, 13))
    for contract in selected:
        if contract["status"] == "DRAFT":
            assert any(f"DRAFT_NOT_GRANDFATHERED {contract['id']}" in error for error in result["errors"])
        else:
            assert M.contract_review_proven(contract)


def test_tomorrow_packet_preserves_lines_and_labels_unmeasured_receipts():
    packet = json.loads(
        (
            ROOT
            / "docs/implementation/n8n-maturity/reconciliation-20261012/MOMENTUM_TOMORROW_CHANGE_PACKET_20261013.json"
        ).read_text()
    )
    line = packet["scalp_legacy_change"]
    assert packet["test_date"] == "2026-10-13" and packet["timezone"] == "America/New_York"
    assert (
        line["comment_preview"]
        == "# RETIRED 2026-10-13 n8n-cutover trade-ai-scalp-live " + line["source_declared_full_line"]
    )
    assert line["installed_archived_full_line"] is None and line["ready_to_apply"] is False
    assert packet["receipt_identity"]["actual_run_ids"].startswith("NOT_MEASURED")
    assert packet["request_authority"]["sole_requester"] == "tradeai-dispatcher"
    assert packet["request_authority"]["scalp_generated_workflows_keep_inactive"] == [
        "537142069dd5b352",
        "15b22c523f844467",
    ]


from tests.support.n8n_cutover_waves import PROMOTED as _CW_PROMOTED  # noqa: E402  2026-10-15 cutover waves
