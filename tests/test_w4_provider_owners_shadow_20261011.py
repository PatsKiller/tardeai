"""Consolidation W4 provider owners on the dispatcher in SHADOW (R1 class ingest), 2026-10-11.

COVERS = ["config/lane_registry.json", "config/n8n_run_allowlist.json", "config/n8n_health_contracts.json"]

CONSOLIDATION_PLAN §B.3 W4 ("provider owners without broker credentials", AGENTS §23.18): three owner lanes get the
AGENTS 4.4.0 cron-row shadow shape — scheduler.stage shadow, dispatch.mode dry_run, allowlist live_arg null — so the
dispatcher fires their write-free dry run on the natural schedule while the cron line keeps doing the real work:

* finviz-enrichment  cron L142  owner of the finviz_enrichment domain;
* sec-data-ingest    cron L150  SEC Form 4 owner (sec_form4);
* social-ingest-all  cron L243  social owner (social_posts writer_target).

Excluded, and pinned so a later PR cannot slip them in unreviewed:
* news-ingestion / news-ingestion-tail (L193, L649, L650): scripts/news_ingestion.py has no --dry-run (an unknown
  flag falls through to the live --priority branch) and writes no LaneRunReceipt; the rows are KEEP_ON_CRON.
* sec-filings-feed (L1002): no LaneRunReceipt, its dry run is the argv default (no dry_run_arg), and its cron line
  sources the whole tmpfs secret render (which carries ALPACA_* per config/secret_registry.yaml).

The failures this guards against: an owner row that the R1 gate would refuse; a live argv at shadow; a broker
credential env name; a lock claimed to be the cron line's when the line has no flock (canary must stay blocked until a
cron packet adds it); a scheduler.match that hits more than its own cron line (the dispatch.cron mismatch and a
cutover that would retire two lines); a contract that is not REVIEWED. Hermetic: repo config read only.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tests") not in sys.path:
    sys.path.append(str(ROOT / "tests"))
from support import n8n_cutover_waves as CW  # noqa: E402
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import lane_dispatch as LD  # noqa: E402
from scripts.lib import n8n_due as D  # noqa: E402
from scripts.lib import n8n_health_contracts as H  # noqa: E402
from scripts.lib import n8n_retry_policy as RP  # noqa: E402

REGISTRY = json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))
ROWS = {r["lane_id"]: r for r in REGISTRY["lanes"]}
ALLOW = {e["lane_id"]: e for e in json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text())["lanes"]}
CONTRACTS = {c["id"]: c for c in json.loads((ROOT / "config" / "n8n_health_contracts.json").read_text())["contracts"]}
POLICIES = RP.load_policies(ROOT / "config" / "n8n_retry_policies.json")

#: lane_id -> (crontab line on 2026-10-11, live schedule, the script's LANE_ID literal, dispatcher argv after $PY)
W4 = {
    "finviz-enrichment": ("L142", "0 13 * * 1-5", "finviz_enrichment.py", ["scripts/finviz_enrichment.py"]),
    "sec-data-ingest": ("L150", "0 20 * * 1-5", "sec_data_ingest.py", ["scripts/sec_data_ingest.py", "--all"]),
    "social-ingest-all": ("L243", "0 6 * * 1-5", "social_ingest.py",
                          ["scripts/social_ingest.py", "--source", "all"]),
}
EXCLUDED = ("news-ingestion", "news-ingestion-tail", "sec-filings-feed")
#: 2026-10-15: lanes a cutover wave promoted to canary leave the shadow pins below; tests/test_n8n_cutover_wave_20261015.py
#: pins their canary shape (tests/support/n8n_cutover_waves.py).
W4_SHADOW = {k: v for k, v in W4.items() if k not in CW.PROMOTED}

#: The crontab lines (2026-10-11, crontab -l) that share a script with a W4 row; each W4 match must hit exactly one.
SIBLING_LINES = [
    "cd $PROJ && flock -n /tmp/finviz_enrichment.lock $PY scripts/finviz_enrichment.py >> logs/finviz_enrichment.log 2>&1",
    "cd $PROJ && SCALP_HOT_TIER=1 flock -n /tmp/finviz_enrichment_scalp_hot.lock timeout 240 bash "
    "scripts/market_day_gate.sh $PY scripts/finviz_enrichment.py --scalp-hot >> logs/finviz_enrichment_scalp_hot.log 2>&1",
    "cd $PROJ && flock -n /tmp/sec_data_ingest.lock $PY scripts/sec_data_ingest.py --all >> logs/sec_ingest.log 2>&1",
    "cd $PROJ && flock -n /tmp/social_ingest_all.lock $PY scripts/social_ingest.py --source all >> logs/social_ingest.log 2>&1",
    "cd $PROJ && $PY scripts/social_ingest.py --source stocktwits --discover >> logs/social_ingest.log 2>&1",
]


@pytest.mark.parametrize("lane", sorted(W4_SHADOW))
def test_row_is_a_w4_shadow_cron_row_admitted_by_the_r1_gate(lane):
    _line, cron, _script, _argv = W4[lane]
    row = ROWS[lane]
    s = row["scheduler"]
    assert s["kind"] == "cron" and s["stage"] == "shadow" and s["wave"] == "W4" and s["expression"] == cron
    assert row["state"] == "ACTIVE"
    assert "generated_by" not in row and row["adopted_from_generator"] == "reconcile_lane_registry@v1"
    d = row["dispatch"]
    assert d == {"mode": "dry_run", "cron": [cron], "tz": "America/New_York", "wave": "W4", "class": "ingest",
                 "priority": 5, "retry_policy": "none"}
    assert LD.dispatch_mode(row) == "dry_run"
    assert LD.validate_dispatch_block(row) == []
    assert LD.dispatch_eligible(row) == (True, "eligible")
    assert LD.r1_class_admission(row) == (True, "r1_admitted:ingest")


@pytest.mark.parametrize("lane", sorted(W4_SHADOW))
def test_row_is_refused_while_4_4_0_is_proposed(lane):
    ok, why = LD.r1_class_admission(ROWS[lane], ALLOW[lane], shadow_shape_status="PROPOSED")
    assert not ok and why.startswith("shadow_on_cron_not_ratified"), why


@pytest.mark.parametrize("lane", sorted(W4_SHADOW))
def test_allowlist_entry_is_shadow_only_and_carries_no_broker_credential(lane):
    _line, _cron, _script, argv = W4[lane]
    e = ALLOW[lane]
    assert e["command"] == ["$PY", *argv]
    assert e["live_arg"] is None and e["dry_run_arg"] == ["--dry-run"]
    assert not any(t.startswith("--apply") for t in e["command"])
    assert e["output_signal"] == ROWS[lane]["output_signal"]["path"] == f"data/runtime/{lane}_last.json"
    assert LD.receipt_signal_path(ROWS[lane]) == e["output_signal"]
    assert e["env_allowlist_mode"] == "report" and e["env_report_reason"]
    for name in e["env_names"]:
        assert not any(f in name.upper() for f in LD.BROKER_CREDENTIAL_ENV_FRAGMENTS), (lane, name)
    assert LD.forbidden_text_hits(" ".join(e["command"] + e["dry_run_arg"])) == []
    assert e["timeout_s"] <= 900 and e["market_gate"] is False


@pytest.mark.parametrize("lane", sorted(W4_SHADOW))
def test_cron_lock_is_installed_and_matches_but_the_row_stays_shadow(lane):
    """The w4-flock packet is installed (crontab -l 2026-10-11 ~10:10 ET: each line carries `flock -n <lock>`), and
    canary wave 1 synced scheduler.command_text to the flocked line: the canary lock gate now passes on a simulated
    canary, but the row stays shadow (live_arg null) until it has a RUN_DONE dry_run (§23.12 / canary-wave1)."""
    e = ALLOW[lane]
    text = ROWS[lane]["scheduler"]["command_text"]
    assert e["lock_kind"] == "flock" and e["lock"].startswith("/tmp/")
    assert LD.cron_flock_locks(text) == [e["lock"]]
    assert e["lock"] in e["source"]
    assert ROWS[lane]["scheduler"]["stage"] == "shadow" and e["live_arg"] is None
    canary = json.loads(json.dumps(ROWS[lane]))
    canary["scheduler"]["stage"] = "canary"
    canary["dispatch"]["mode"] = "live"
    assert LD.r1_canary_lock_matches(canary, dict(e, live_arg=[])) == (True, "canary_on_cron")
    assert LD.r1_canary_lock_matches(canary, e)[0] is False  # live_arg null: no live fire from a shadow row


def test_each_match_hits_exactly_its_own_cron_line():
    for lane, (_line, _cron, _script, _argv) in W4.items():
        row = ROWS[lane]
        marker = row["scheduler"]["match"]
        hits = [ln for ln in SIBLING_LINES if marker in ln]
        assert hits == [row["scheduler"]["command_text"]], (lane, marker, hits)
    hot = ROWS["finviz-enrichment-scalp-hot"]
    # 2026-10-14 scalp-premarket-onboard: the hot tier is now its own W5 shadow cron row (dry_run) matching only its line
    # (tests/test_scalp_premarket_onboard_20261014.py).
    assert hot["dispatch"]["mode"] == "dry_run" and hot["scheduler"]["kind"] == "cron"
    assert hot["scheduler"]["stage"] == "shadow" and hot["scheduler"]["wave"] == "W5"
    assert [ln for ln in SIBLING_LINES if hot["scheduler"]["match"] in ln] == [SIBLING_LINES[1]]


def test_the_script_writes_the_receipt_the_row_names():
    for lane, (_line, _cron, script, _argv) in W4.items():
        src = (ROOT / "scripts" / script).read_text(encoding="utf-8")
        assert f'"{lane}"' in src, (lane, script)
        assert "write_lane_receipt" in src and "dry_run_report" in src and '"--dry-run"' in src


@pytest.mark.parametrize("lane", sorted(W4_SHADOW))
def test_health_contract_is_reviewed_and_complete(lane):
    c = CONTRACTS[lane]
    assert c["status"] == "REVIEWED" and c["stage"] == "shadow"
    assert H.validate_contract(c) == []
    assert H.unknown_fields(c) == []
    assert not [e for e in c["connects_to"] if e["kind"] == "inventory_text"]
    assert {e["direction"] for e in c["connects_to"]} >= {"read", "write", "calls"}
    assert c["baseline"]["freshness_degraded_after_h"] == 26.0 and c["baseline"]["freshness_failed_after_h"] == 50.0
    assert c["evidence"]["receipt"] == ALLOW[lane]["output_signal"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", c["review_by"])
    assert c["owner"] == ROWS[lane]["owner"]


def test_contract_gate_is_clean():
    doc = json.loads((ROOT / "config" / "n8n_health_contracts.json").read_text())
    idx = json.loads((ROOT / "docs" / "implementation" / "n8n-maturity" / "workflows" / "INDEX.json").read_text())
    res = H.check(doc, REGISTRY, idx)
    assert res["errors"] == []
    assert set(W4) - set(doc["grandfathered_draft"]) == set(W4)  # REVIEWED, not grandfathered


def test_excluded_lanes_stay_off_the_dispatcher():
    for lane in EXCLUDED:
        row = ROWS[lane]
        assert "dispatch" not in row and "r1_pending" not in row, lane
        assert (row.get("scheduler") or {}).get("stage") is None, lane
        assert lane not in ALLOW, lane
    src = (ROOT / "scripts" / "news_ingestion.py").read_text(encoding="utf-8")
    # onboarding B3 (2026-10-15) added the offline --dry-run guard (tests/test_onboard_dryrun_b3_20261015.py); the lane
    # still writes no LaneRunReceipt, so it stays off the dispatcher until its onboarding row adds one.
    assert "write_lane_receipt" not in src  # refactor first, then a W4 row
    assert '"--dry-run" in _dr_sys.argv[1:]' in src


START = datetime(2026, 10, 12, 4, 0, tzinfo=timezone.utc)  # Monday 00:00 America/New_York


def test_compute_due_week_sweep_emits_dry_run_on_the_weekday_slots_only():
    rows = [ROWS[x] for x in W4_SHADOW]
    slots: dict[str, set] = {}
    errors = set()
    t = START
    while t < START + timedelta(days=7):
        resp = D.compute_due(rows, ALLOW, POLICIES, None, t)
        for it in resp["items"]:
            assert it["mode"] == "dry_run", it
            slots.setdefault(it["lane_id"], set()).add(it["slot_local"][-4:])
        errors |= {(e["lane_id"], e["code"]) for e in resp["errors"]}
        t += timedelta(minutes=30)
    assert errors == set(), sorted(errors)
    want = {"finviz-enrichment": {"1300"}, "sec-data-ingest": {"2000"}, "social-ingest-all": {"0600"}}
    assert slots == {k: v for k, v in want.items() if k not in CW.PROMOTED}
