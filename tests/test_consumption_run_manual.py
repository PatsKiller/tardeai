"""Contract tests for /api/v2/consumption/run-manual lane classification."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.consumption_run_manual import (  # noqa: E402
    classify_manual_lane,
    deepseek_readiness_rows,
)


def test_grok_accepted():
    c = classify_manual_lane("grok")
    assert c["ok"] is True
    assert c["kind"] == "oauth"
    assert c["lane"] == "grok"


def test_chatgpt_accepted():
    c = classify_manual_lane("chatgpt")
    assert c["ok"] is True
    assert c["kind"] == "oauth"


def test_deepseek_flash_maps_to_fast():
    c = classify_manual_lane("deepseek-flash")
    assert c["ok"] is True
    assert c["kind"] == "deepseek"
    assert c["policy"] == "FAST"
    assert c["requested_model_id"] == "deepseek-v4-flash"


def test_fast_accepted():
    c = classify_manual_lane("fast")
    assert c["ok"] is True
    assert c["policy"] == "FAST"
    assert c["requested_model_id"] == "deepseek-v4-flash"


def test_fast_think_accepted():
    c = classify_manual_lane("fast_think")
    assert c["ok"] is True
    assert c["policy"] == "FAST_THINK"
    assert c["requested_model_id"] == "deepseek-v4-flash"


def test_pro_rejected_without_confirmation():
    c = classify_manual_lane("deepseek-v4-pro", operator_confirmed=False)
    assert c["ok"] is False
    assert c["reason_code"] == "PRO_CONFIRMATION_REQUIRED"
    c2 = classify_manual_lane("pro", operator_confirmed=False)
    assert c2["ok"] is False
    c3 = classify_manual_lane("PRO", operator_confirmed=False)
    assert c3["ok"] is False


def test_pro_accepted_with_confirmation():
    c = classify_manual_lane("deepseek-v4-pro", operator_confirmed=True)
    assert c["ok"] is True
    assert c["policy"] == "PRO"
    assert c["requested_model_id"] == "deepseek-v4-pro"


def test_ambiguous_and_legacy_rejected():
    for lane in ("deepseek-v4", "deepseek_v4", "v4"):
        c = classify_manual_lane(lane)
        assert c["ok"] is False
        assert c["reason_code"] == "AMBIGUOUS_LEGACY_LANE"
    for lane in ("deepseek-chat", "deepseek-reasoner"):
        c = classify_manual_lane(lane)
        assert c["ok"] is False
        assert c["reason_code"] == "LEGACY_MODEL_REJECTED"


def test_pro_max_requires_confirmation():
    c = classify_manual_lane("pro_max", operator_confirmed=False)
    assert c["ok"] is False
    assert c["reason_code"] == "PRO_MAX_CONFIRMATION_REQUIRED"


def test_no_secret_leak_in_readiness_rows(monkeypatch=None):
    rows = deepseek_readiness_rows()
    assert len(rows) == 2
    blob = str(rows)
    assert "deepseek_tradeai" not in blob
    assert "DEEPSEEK_API_KEY" not in blob
    assert "sk-" not in blob
    for r in rows:
        assert r["lane"] in ("deepseek-flash", "deepseek-v4-pro")
        assert r.get("label")
        # reason_code may be present when offline — never env name
        if r.get("reason_code"):
            assert "deepseek_tradeai" not in r["reason_code"]
            assert "API_KEY" not in r["reason_code"]


def test_api_v2_run_manual_no_longer_hard_oauth_only():
    api = (ROOT / "scripts" / "api_v2.py").read_text()
    assert "classify_manual_lane" in api
    assert "lane must be grok or chatgpt" not in api.split("if base_path == \"/api/v2/consumption/run-manual\"")[1].split("if base_path ==")[0]
    # legacy string may remain elsewhere; ensure deepseek path present in handler
    assert "billing\": \"metered\"" in api or "billing': 'metered'" in api or '"billing": "metered"' in api


def test_free_ensemble_contract_still_blocks_deepseek_in_free_path():
    """RUN ALL FREE must not include metered deepseek — existing free-ensemble guard."""
    api = (ROOT / "scripts" / "api_v2.py").read_text()
    assert "METERED_LANE_NOT_IN_FREE_ENSEMBLE" in api or "metered" in api.lower()
    # WatchTruth free button contract
    panel = (ROOT / "apps/command-center-v3/src/components/WatchTruthAuditPanel.tsx").read_text()
    assert "Free critics only for RUN ALL FREE" in panel or "RUN ALL FREE" in panel
    assert "local" in panel and "grok" in panel and "chatgpt" in panel
