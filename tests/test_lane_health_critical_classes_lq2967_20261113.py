"""LQ-20261107-2967 (REVIEW-2963 D2): ``business_critical_value_classes`` in config/lane_health.json.

Empty meant every LATE/STALE/FAILING lane counted toward the Home Schedulers WARN, so the tile read WARN forever
once rows existed. These tests read the REAL policy file and the REAL registry, not a literal list.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from scripts.lib import lane_health as LH  # noqa: E402
from test_lane_health_20261112 import (  # noqa: E402
    ALWAYS, NOW, ledger, n8n_lane, row, run, slots_utc,
)

POLICY = LH.load_config()  # the shipped config/lane_health.json merged over DEFAULTS


def snap(lanes, led, signals=None):
    return LH.build({"lanes": lanes}, ledger=led, now=NOW, trading_day=ALWAYS, signals=signals or {}, policy=POLICY)


def on_time(lane_id):
    return [run(lane_id, t, late_min=1) for t in slots_utc()]


def test_the_shipped_list_is_not_empty_and_names_real_registry_classes():
    classes = POLICY["business_critical_value_classes"]
    assert classes, "empty list = every lane counts = Schedulers WARN forever (REVIEW-2963 D2)"
    registry = json.loads((ROOT / "config/lane_registry.json").read_text(encoding="utf-8"))["lanes"]
    present = {str(r.get("value_class")) for r in registry}
    assert set(classes) <= present, sorted(set(classes) - present)
    assert "Business Critical" in classes
    assert POLICY.get("_config_gap") is None


def test_a_fresh_healthy_registry_reads_ok_even_with_a_late_non_critical_lane():
    crit = n8n_lane("syn-crit", value_class="Business Critical")
    ops_late = n8n_lane("syn-ops-late")  # Operationally Important, never ran
    ok_signal_free = snap([crit, ops_late], ledger(on_time("syn-crit")))
    assert row(ok_signal_free, "syn-crit")["state"] == "OK"
    assert row(ok_signal_free, "syn-ops-late")["state"] == "LATE"
    assert ok_signal_free["schedulers"]["status"] == "OK", ok_signal_free["schedulers"]
    assert ok_signal_free["schedulers"]["worst"] == []


def test_a_fresh_healthy_registry_of_only_critical_lanes_reads_ok():
    s = snap([n8n_lane("syn-a", value_class="Business Critical"),
              n8n_lane("syn-b", value_class="Business Critical")],
             ledger(on_time("syn-a") + on_time("syn-b")))
    assert s["schedulers"]["status"] == "OK" and s["schedulers"]["cause_code"] == "on_schedule"


def test_a_stale_business_critical_lane_reads_warn_with_the_producer_time_not_the_render_time():
    producer_at = NOW - timedelta(days=3)
    signal = {"readable": True, "kind": "file", "at": producer_at}
    crit = n8n_lane("syn-crit-stale", value_class="Business Critical")
    s = snap([crit], ledger(on_time("syn-crit-stale")), signals={"syn-crit-stale": signal})
    r = row(s, "syn-crit-stale")
    assert r["state"] == "STALE" and r["cause_code"] == "output_stale"
    assert s["schedulers"]["status"] == "WARN" and s["schedulers"]["cause_code"] == "lanes_off_schedule"
    # producer time: the signal's own timestamp and the lane's last expected slot, never the render clock
    assert r["output_signal_at"] == producer_at.isoformat()
    assert r["output_age_s"] == int((NOW - producer_at).total_seconds())
    assert r["last_expected_at"] == slots_utc()[-1].isoformat()
    assert r["output_signal_at"] != r["measured_at"] and r["last_expected_at"] != r["measured_at"]
    worst = s["schedulers"]["worst"][0]
    assert worst["lane_id"] == "syn-crit-stale" and worst["state"] == "STALE"
    assert worst["last_expected_at"] == slots_utc()[-1].isoformat()
    assert worst["last_expected_at"] != s["measured_at"]


def test_a_stale_non_critical_lane_does_not_turn_schedulers_warn_but_stays_visible_per_lane():
    signal = {"readable": True, "kind": "file", "at": NOW - timedelta(days=3)}
    s = snap([n8n_lane("syn-ops-stale")], ledger(on_time("syn-ops-stale")), signals={"syn-ops-stale": signal})
    assert row(s, "syn-ops-stale")["state"] == "STALE"  # the lane page still shows it
    assert s["schedulers"]["status"] == "OK" and s["schedulers"]["worst"] == []


def test_a_late_critical_lane_reads_warn_and_empty_list_would_have_counted_everything():
    late_crit = n8n_lane("syn-late-crit", value_class="Business Critical")
    ops_late = n8n_lane("syn-ops-late")
    s = snap([late_crit, ops_late], ledger([]))
    assert s["schedulers"]["status"] == "WARN"
    assert [w["lane_id"] for w in s["schedulers"]["worst"]] == ["syn-late-crit"]
    # the old config (empty list) would have listed both
    s_old = LH.build({"lanes": [late_crit, ops_late]}, ledger=ledger([]), now=NOW, trading_day=ALWAYS, signals={},
                     policy={**POLICY, "business_critical_value_classes": []})
    assert sorted(w["lane_id"] for w in s_old["schedulers"]["worst"]) == ["syn-late-crit", "syn-ops-late"]
