"""LQ-20261107-1856 — vix-index-quotes-schwab goes live (operator APPROVED 2026-11-10 18:17 ET).

ANCHOR: VIX_INDEX_QUOTES_LIVE_20261110

Three things are pinned here, all synthetic or read from the committed config:

  1. the header/VIX monitor admits the continuous lane's print (``market_quotes:schwab:$VIX``) and still refuses any
     other source, so a fresh continuous print reads OK and an unrelated one still reads BROKEN;
  2. the registry row is ``canary`` + ``dispatch.mode live`` on the *unchanged* window -- Sun 18:00 through Fri 20:00
     ET, every 15 min, all week (no Sunday-only start) -- and the rails that gate a live fire admit exactly that row;
  3. the lane's health contract is at the registry's stage (STAGE_DRIFT) and no longer carries the shadow-only check.

The window assertion is a coverage check, not a comment: every 15-minute slot of the span must fire and every slot
outside it must not, so narrowing the cron or adding a Sunday gate turns it red.
"""
from __future__ import annotations

import copy
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import header_market_freshness_health as hm  # noqa: E402
from scripts.lib import lane_dispatch as LD  # noqa: E402
from scripts.lib import lane_stage_clamp as LSC  # noqa: E402
from scripts import n8n_run_executor as X  # noqa: E402
from scripts.lib import lane_last_receipt as LR  # noqa: E402
from scripts.lib import n8n_health_contracts as HC  # noqa: E402

LANE = "vix-index-quotes-schwab"
CONTINUOUS = "market_quotes:schwab:$VIX"
EXTENDED = "market_quotes_extended:schwab:$VIX"
FRED = "fred_economic_series:VIXCLS"
# A zoned pre-market observation, the shape the continuous lane writes.
OBS = "2026-01-12T03:45:00-05:00"

# The live window, as three cron lines (registry dispatch.cron). dow: 0 = Sunday.
WINDOW_CRON = ("*/15 18-23 * * 0", "*/15 * * * 1-4", "*/15 0-19 * * 5")


def _headline(vix=21.5, state="FRESH", as_of=OBS, source=CONTINUOUS, reason=None):
    return {"vix": vix, "vix_source": source if vix is not None else None,
            "vix_observation_time": as_of if vix is not None else None, "vix_state": state,
            "vix_age_hours": 0.25, "vix_stale_after_hours": 26.0, "vix_reason": reason}


def _header(vix=21.5, source=CONTINUOUS, as_of=OBS):
    return {"vix": vix, "vix_source": source, "vix_observation_time": as_of}


def _card(vix=21.5, source=CONTINUOUS, as_of=OBS):
    return {"vix": vix, "vix_source": source, "vix_as_of": as_of}


# ── the monitor admits the continuous print ────────────────────────────────────────────────────────────────────

def test_a_fresh_continuous_print_is_ok_not_inadmissible():
    out = hm.vix_contract(headline=_headline(), header=_header(), card=_card())
    assert (out["verdict"], out["reason"]) == ("OK", None)
    assert out["headline"]["source"] == CONTINUOUS


def test_before_the_source_was_admitted_the_same_print_was_broken(monkeypatch):
    """BEFORE: the pre-LQ-1856 admissible set, holding only the extended store and FRED."""
    monkeypatch.setattr(hm, "ADMISSIBLE_VIX_SOURCES", (EXTENDED, FRED))
    out = hm.vix_contract(headline=_headline(), header=_header(), card=_card())
    assert out["verdict"] == "BROKEN"
    assert out["reason"] == f"header_source_inadmissible:{CONTINUOUS}"


def test_a_stale_continuous_print_is_degraded_not_broken():
    out = hm.vix_contract(headline=_headline(state="STALE", reason="last print 16:45 ET, 11 h ago"),
                          header=_header(), card=_card())
    assert out["verdict"] == "DEGRADED"
    assert out["reason"].startswith("vix_stale:") and "16:45" in out["reason"]


@pytest.mark.parametrize("source", [
    "market_quotes:schwab:$VIX9D",          # a sibling symbol is not the headline
    "market_quotes:schwab:$VIX3M",
    "market_quotes_extended:schwab:$VIX9D",
    "market_quotes:yahoo_finance:$VIX",    # banned feed
    "yahoo_finance",
    "market_quotes:schwab:$VIX ",          # exact string, not a prefix: a trailing space is another source
])
def test_an_unknown_source_is_still_broken(source):
    out = hm.vix_contract(headline=_headline(source=source), header=_header(source=source), card=_card(source=source))
    assert out["verdict"] == "BROKEN"
    assert out["reason"] == f"header_source_inadmissible:{source}"


def test_the_admissible_set_is_closed_and_matches_the_producer_key():
    """The literal must be the key the producer writes: ``<store>:<feed>:<symbol>`` from the two configs."""
    lane_cfg = yaml.safe_load((ROOT / "config" / "vix_index_quotes.yaml").read_text(encoding="utf-8"))
    complex_cfg = yaml.safe_load((ROOT / "config" / "market_regime_vix_complex.yaml").read_text(encoding="utf-8"))
    assert f"{lane_cfg['store']}:{lane_cfg['source']}:$VIX" == CONTINUOUS
    assert (complex_cfg["continuous_store"], complex_cfg["continuous_source"]) == (lane_cfg["store"], lane_cfg["source"])
    assert set(hm.ADMISSIBLE_VIX_SOURCES) == {EXTENDED, CONTINUOUS, FRED}
    assert len(hm.ADMISSIBLE_VIX_SOURCES) == 3


# ── the config: canary + live, on the unchanged window ─────────────────────────────────────────────────────────

def _registry():
    return json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))


def _row():
    rows = [r for r in _registry()["lanes"] if r.get("lane_id") == LANE]
    assert len(rows) == 1, f"expected exactly one registry row for {LANE}"
    return rows[0]


def _allow_entry():
    doc = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text(encoding="utf-8"))
    entries = [e for e in doc["lanes"] if e.get("lane_id") == LANE]
    assert len(entries) == 1, f"expected exactly one allowlist entry for {LANE}"
    return entries[0]


def _contract():
    doc = json.loads((ROOT / "config" / "n8n_health_contracts.json").read_text(encoding="utf-8"))
    rows = [c for c in doc["contracts"] if c.get("id") == LANE]
    assert len(rows) == 1
    return rows[0]


def _field_match(field, value):
    """A cron field: ``*``, ``N``, ``A-B``, any of them with ``/step``, comma-lists."""
    for part in field.split(","):
        span, _, step = part.partition("/")
        lo, _, hi = span.partition("-")
        if span == "*":
            lo, hi = "0", "999"
        hi = hi or lo
        step = int(step or 1)
        if int(lo) <= value <= int(hi) and (value - int(lo)) % step == 0:
            return True
    return False


def _fires(minute, hour, dow):
    return any(_field_match(m, minute) and _field_match(h, hour) and _field_match(d, dow)
               for m, h, _dom, _mon, d in (line.split() for line in WINDOW_CRON))


def test_the_window_runs_all_week_every_fifteen_minutes():
    """Sun 18:00 -> Fri 20:00 ET in one continuous span: no Sunday-only start, no narrowed weekday, no gap."""
    assert tuple(_row()["dispatch"]["cron"]) == WINDOW_CRON
    missing, extra = [], []
    for dow in range(7):
        for hour in range(24):
            for minute in (0, 15, 30, 45):
                inside = (dow == 0 and hour >= 18) or (1 <= dow <= 4) or (dow == 5 and hour < 20)
                if inside and not _fires(minute, hour, dow):
                    missing.append((dow, hour, minute))
                if not inside and _fires(minute, hour, dow):
                    extra.append((dow, hour, minute))
    assert missing == [], f"the window does not fire at {missing[:5]}"
    assert extra == [], f"the cron fires outside the window at {extra[:5]}"


def test_the_registry_row_is_canary_live_and_the_allowlist_admits_the_pinned_shape():
    row, entry = _row(), _allow_entry()
    assert row["scheduler"]["stage"] == "canary"
    assert row["dispatch"]["mode"] == "live"
    assert row["dispatch"]["class"] == "ingest"
    assert entry["live_arg"] == ["--apply"]
    assert tuple(entry["command"]) == LD.SCHWAB_QUOTE_READ_COMMAND
    assert LD.schwab_quote_read_shape_problem(row, entry) is None
    eligible, why = LD.dispatch_eligible(row)
    assert eligible, why


def test_the_stage_clamp_keeps_this_row_live_and_clamped_a_shadow_one(monkeypatch):
    rows = _registry()["lanes"]
    live = LSC.clamp_mode(LANE, "live", rows)
    assert (live["effective_mode"], live["clamped"], live["stage"]) == ("live", False, "canary")
    assert live["reason"] == "stage_canary"
    # BEFORE: the shadow row the 2026-11-10 flip replaced -- a live request became a dry run.
    row = next(r for r in rows if r.get("lane_id") == LANE)
    monkeypatch.setitem(row["scheduler"], "stage", "shadow")
    shadow = LSC.clamp_mode(LANE, "live", rows)
    assert (shadow["effective_mode"], shadow["clamped"], shadow["reason"]) == ("dry_run", True, "stage_shadow")


def test_the_health_contract_is_at_the_registry_stage_and_not_shadow_only():
    contract, row = _contract(), _row()
    assert contract["stage"] == row["scheduler"]["stage"] == "canary"
    assert contract["target_reason"] == "stage:canary"
    assert contract["status"] == "REVIEWED"
    checks = [h["check"] for h in contract["healthy"]]
    assert "shadow_dry_run_done" not in checks
    assert "canary_live_done" in checks
    assert "no finished live runs yet (stage shadow)" not in contract["baseline"]["source"]
    assert contract["baseline"]["basis"] == "CLASS_DEFAULT_PROVISIONAL"  # activation is not validation


def test_the_health_contract_gate_is_clean_for_this_lane():
    res = HC.check(HC.load_json(HC.CONTRACTS_PATH), HC.load_json(HC.REGISTRY_PATH), HC.load_json(HC.GENERIC_INDEX_PATH))
    assert [e for e in res["errors"] if LANE in e] == []
    assert [w for w in res["warnings"] if LANE in w] == []
    assert res["errors"] == []


# ── the executor grades a live fire the contract allows to be empty ─────────────────────────────────────────
#
# Measured on this host, 2026-11-10 (data/runtime/n8n_runs/d:vix-index-quotes-schwab:dry_run:20261110T*): $VIX prints
# every 15 min from 03:15 to 16:15 ET, stops at 16:15 ET, and every fire from 16:45 ET on reads the same print with
# age > max_trade_age_minutes and status stale_print. A live fire in those hours produces 0 rows with a typed reason,
# and that must be RUN_DONE, not RUN_FAILED -- the operator approved the lane, not a permanent red.

LIVE_RUN = f"d:{LANE}:live:20261110T2100"
START = datetime(2026, 11, 10, 21, 0, tzinfo=timezone.utc)
END = START + timedelta(seconds=30)
CODE = "c" * 40


def _live_receipt(**change):
    doc = {"schema": "LaneRunReceipt@v2", "run_id": LIVE_RUN, "lane_id": LANE, "attempt": 1, "mode": "live",
           "run_mode": "live", "code_sha": CODE, "status": "ok", "produced_count": 3, "attempted_count": 3,
           "skipped_reasons": {}, "started_at": (START + timedelta(seconds=1)).isoformat(),
           "finished_at": (END - timedelta(seconds=1)).isoformat(),
           "ok_at": (END - timedelta(seconds=1)).isoformat(),
           "summary": {"symbols": {"written": 3}, "inserted": 3}}
    doc.update(change)
    return doc


def _grade(tmp_path, **change):
    doc = copy.deepcopy(_live_receipt(**change))
    path = LR.attempt_receipt_path(LANE, LIVE_RUN, tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc))
    receipt = {"run_id": LIVE_RUN, "lane_id": LANE, "mode": "live", "state": "RUN_DONE", "reason": None,
               "attempt": 1, "code_sha": CODE, "started_at": START.isoformat(), "finished_at": END.isoformat()}
    return X.apply_output_verdict(receipt, {LANE: _contract()["expected_output"]}, lane_id=LANE, mode="live",
                                  state_root=tmp_path, entry={"output_receipt": "v2"})


def _empty_reasons():
    return set(_contract()["expected_output"]["empty_allowed_reasons"])


def test_a_live_fire_that_writes_rows_is_produced(tmp_path):
    out = _grade(tmp_path)
    assert out["state"] == "RUN_DONE" and out["reason"] is None
    assert out["output_verdict"]["verdict"] == "produced"


@pytest.mark.parametrize("reason", ["cboe_not_calculating", "unchanged", "outside_window"])
def test_a_typed_empty_in_the_contract_is_not_a_failure(tmp_path, reason):
    assert reason in _empty_reasons(), "the case must be one the contract actually allows"
    out = _grade(tmp_path, produced_count=0, empty_reason=reason)
    assert out["state"] == "RUN_DONE", out
    assert out["output_verdict"]["verdict"] == "empty_allowed", out


def test_an_empty_reason_outside_the_contract_still_fails(tmp_path):
    out = _grade(tmp_path, produced_count=0, empty_reason="nothing_today")
    assert out["state"] == "RUN_FAILED"
    assert out["output_verdict"]["verdict"] == "empty_violation"
