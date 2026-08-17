"""Provider-spend attribution tests. Fixtures only — no paid calls."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.provider_cost.export import KEY_ATTRIBUTION_UNAVAILABLE, export_by_key
from scripts.lib.provider_cost.identity import fingerprint_key, redact_mapping, redacted_key_id
from scripts.lib.provider_cost.parse import parse_consumption_rows, parse_reservation_rows
from scripts.lib.provider_cost.pricing import calculate_usd
from scripts.lib.provider_cost.reconcile import reconcile
from scripts.lib.provider_cost.schema import is_test_process
from scripts.provider_cost_reconcile import SUPPLIED_BASELINE, _load_json
from scripts.lib.provider_cost.parse import (
    parse_bypass_rows,
    parse_claude_code_jsonl,
    parse_console_totals,
    parse_openclaw_jsonl,
)
import tempfile


def _events_from_fixture():
    data = _load_json(ROOT / "tests/fixtures/provider_cost/period_ab.json")
    events = []
    events += parse_console_totals(data["console"])
    events += parse_reservation_rows(data["reservations"])
    events += parse_bypass_rows(data["bypass"])
    oc = Path(tempfile.mkdtemp()) / "oc.jsonl"
    oc.write_text("".join(json.dumps(x) + "\n" for x in data["openclaw_inline"]))
    events += parse_openclaw_jsonl([oc])
    cl = Path(tempfile.mkdtemp()) / "cl.jsonl"
    cl.write_text("".join(json.dumps(x) + "\n" for x in data["claude_inline"]))
    events += parse_claude_code_jsonl([cl])
    return events


def test_export_by_key_unavailable_without_operator_file():
    r = export_by_key(start="2026-08-01", end="2026-08-16")
    assert r["status"] == KEY_ATTRIBUTION_UNAVAILABLE
    assert r["key_attribution"] is False
    assert r["rows"] == []
    assert any("chat/completions" in x or "no documented" in x for x in r["provider_exposes"])


def test_export_by_key_from_operator_csv(tmp_path):
    p = tmp_path / "keys.csv"
    p.write_text(
        "api_key_id,model,billed_cost_usd,input_tokens,output_tokens\n"
        "ds_prod_slot,deepseek-v4-flash,1.25,1000,50\n"
    )
    r = export_by_key(start="2026-08-01", end="2026-08-02", operator_export=p)
    assert r["ok"] is True
    assert r["rows"][0]["key_id_redacted"] == "ds_prod_slot"
    assert r["rows"][0]["provider_cost_usd"] == 1.25
    assert "sk-" not in json.dumps(r)


def test_effective_dated_period_a_not_new_table():
    # 2M miss + 906429 out at historical flash = $0.5338
    old = calculate_usd(
        provider="deepseek",
        model="deepseek-v4-flash",
        at="2026-08-08T16:00:00+00:00",
        cache_miss_input=2_000_000,
        output=906429,
    )
    new = calculate_usd(
        provider="deepseek",
        model="deepseek-v4-flash",
        at="2026-08-17T12:00:00+00:00",
        cache_miss_input=2_000_000,
        output=906429,
    )
    assert abs(old["calculated_cost_usd"] - 0.5338) < 0.0001
    assert old["price_schedule_id"] == "deepseek-v4-flat-2026-08-03"
    assert new["price_schedule_id"] == "deepseek-v4-flash-peakoff-2026-08-16"
    assert abs(new["calculated_cost_usd"] - 0.5338) > 0.4
    assert new["calculated_cost_usd"] != 1.17  # not the hardcoded wrong number; just different schedule


def test_unknown_model_price_unknown():
    r = calculate_usd(provider="deepseek", model="no-such-model", at="2026-08-08T00:00:00+00:00")
    assert r["calculated_cost_usd"] is None
    assert r["cost_source"] == "PRICE_UNKNOWN"


def test_test_reservations_classified_not_production():
    rows = [
        {"id": 1, "process_id": "test_foo", "created_at": "2026-08-08T00:00:00+00:00", "actual_usd": 4.85},
        {"id": 2, "process_id": "advisory_desk_opinion", "created_at": "2026-08-08T00:00:00+00:00", "actual_usd": 0.22},
    ]
    ev = parse_reservation_rows(rows)
    assert ev[0].is_test is True
    assert ev[0].classification == "TRADE_AI_TEST"
    assert ev[1].is_test is False
    assert ev[1].classification == "TRADE_AI_PRODUCTION"
    assert is_test_process("test_smoke_bridge")


def test_kchar_not_treated_as_usd():
    rows = [{
        "id": 1,
        "created_at": "2026-08-08T00:00:00+00:00",
        "model": "deepseek-v4-flash",
        "estimated_cost_usd": 8065.40,
        "cost_basis": "oauth_free_or_unset",
        "prompt_chars": 8065000,
        "tokens_in": 10,
        "tokens_out": 2,
    }]
    ev = parse_consumption_rows(rows, at_default="2026-08-08T00:00:00+00:00")[0]
    assert ev.characters == 8065000
    assert ev.provider_reported_cost_usd is None
    assert ev.attributed_usd() != 8065.40


def test_period_ab_reconciliation_matches_forensic_arithmetic():
    report = reconcile(_events_from_fixture(), supplied_baseline=SUPPLIED_BASELINE)
    assert abs(report["CONSOLE_TOTAL"] - 60.94) < 0.001
    assert abs(report["LEDGER_ATTRIBUTED"] - 0.867) < 0.002
    assert abs(report["LEDGER_GAP"] - 60.07) < 0.01
    assert abs(report["CLAUDE_CODE"] - 10.30) < 0.01
    assert abs(report["HOST_ATTRIBUTED"] - 11.167) < 0.02
    assert abs(report["HOST_GAP"] - 49.77) < 0.03
    assert abs(report["TEST_ONLY_COST"] - 4.85) < 0.001
    assert abs(report["OPENCLAW"] - 0.2475) < 0.001
    assert report["residual_disposition"] == "UNATTRIBUTABLE_WITH_CURRENT_PROVIDER_DATA"
    assert report["supplied_baseline"]["LEDGER_GAP"] == 60.07
    # test spend is NOT in production ledger
    assert report["TEST_ONLY_COST"] not in (report["LEDGER_ATTRIBUTED"],)
    assert report["LEDGER_ATTRIBUTED"] < 1.0


def test_dedupe_same_event_id():
    evs = _events_from_fixture()
    doubled = evs + evs
    report = reconcile(doubled)
    assert report["double_count_prevented"] == len(evs)
    assert abs(report["CONSOLE_TOTAL"] - 60.94) < 0.001


def test_fingerprint_stable_and_distinct():
    a = fingerprint_key("sk-aaaa-secret-one", provider="deepseek")
    b = fingerprint_key("sk-aaaa-secret-one", provider="deepseek")
    c = fingerprint_key("sk-bbbb-secret-two", provider="deepseek")
    assert a == b and a != c
    label = redacted_key_id("sk-aaaa-secret-one")
    assert "secret-one" not in label
    assert "sk-aaaa" not in label


def test_redaction_never_emits_raw_key():
    dirty = {"DEEPSEEK_API_KEY": "sk-super-secret-value-12345", "ok": 1}
    clean = redact_mapping(dirty)
    assert clean["DEEPSEEK_API_KEY"] == "[REDACTED]"
    assert "sk-super" not in json.dumps(clean)


def test_replay_deterministic():
    a = reconcile(_events_from_fixture())
    b = reconcile(_events_from_fixture())
    c = reconcile(_events_from_fixture())
    assert a["report_hash"] == b["report_hash"] == c["report_hash"]
