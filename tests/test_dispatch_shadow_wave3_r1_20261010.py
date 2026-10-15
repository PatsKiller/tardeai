"""Dispatcher shadow wave D3 (R1 classes ingest / learn), 2026-10-10 — staged inert, activated 2026-10-10 once
AGENTS.md 4.4.0 was ACTIVE (APPROVE_AGENTS_POLICY_4_4_0 1660 463535dfe; flock packet installed, cron grant 08c0bb77ec898136).

COVERS = ["config/lane_registry.json", "config/n8n_run_allowlist.json"]

Operator rulings 2026-10-10 ~14:00 ET ("All yes"): 4.4.0 approved in principle (still needs
APPROVE_AGENTS_POLICY_4_4_0 on its PR); flock added to the cron lines L318 / L314 / L427 so they join the wave;
waves 2 + 3 in ONE registry PR.

Why the rows are staged and not live: while `lane_dispatch.R1_SHADOW_SHAPE_STATUS` is PROPOSED, an ingest / learn
cron row with a dispatch block is refused by `r1_class_admission`, so `validate_dispatch_block`, the registry gate
(check_lane_registry rule 5) and compute_due's errors[] would all go red, every minute, on 19 rows. So each D3 row
carries an `r1_pending` block (scheduler patch, the LaneRunReceipt@v1 output_signal, the dispatch block) and no
`dispatch` key: the dispatcher never emits it and the cron line keeps doing the work. Its allowlist entry lands now
with live_arg null. Activation after ratification is one mechanical registry-train commit (`_activate` below).

The failures this guards against:
* an R1 row reaching the dispatcher before 4.4.0 is ratified (refused while PROPOSED, here and on the real code);
* a staged row that would NOT pass the gate once ratified (admitted when the status is flipped in-test);
* any broker / order / stop / secret / daemon token, broker credential env, a live argv, a non-`none` retry policy
  for ingest / learn, a lock that is not the cron line's, or a receipt the script does not write.
Hermetic: repo config read only; the status constant is never flipped on disk.
"""

from __future__ import annotations

import copy
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import lane_dispatch as LD  # noqa: E402
from scripts.lib import lane_stage_clamp as SC  # noqa: E402
from scripts.lib import n8n_due as D  # noqa: E402
from scripts.lib import n8n_retry_policy as RP  # noqa: E402

REGISTRY = json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))
ROWS = {r["lane_id"]: r for r in REGISTRY["lanes"]}
ALLOW = {e["lane_id"]: e for e in json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text())["lanes"]}
POLICIES = RP.load_policies(ROOT / "config" / "n8n_retry_policies.json")

#: lane_id -> (crontab line, class). L199 market-regime-collector is NOT here: its row spans L199 and the compound
#: L213 line, whose `&&` chain also runs the L205 classifier (a Telegram sender); a live dispatcher fire holding the
#: collector lock would make the cron chain skip the classifier.
WAVE3 = {
    "catalyst-momentum-engine-overnight": ("L381", "ingest"),
    "news-to-catalyst": ("L406", "ingest"),
    "hermes-topic-monitor-bridge": ("L420", "ingest"),
    "watchlist-enrichment-sweep": ("L447", "ingest"),
    "sector-rs-daily": ("L750", "ingest"),
    "hermes-news-bridge": ("L413", "ingest"),
    "classify-instruments": ("L504", "ingest"),
    "research-insight-extractor": ("L418", "ingest"),
    "distributions-enrich": ("L553", "ingest"),
    "build-symbol-profiles-watchlist": ("L508", "ingest"),
    "fund-technicals-enrich": ("L552", "ingest"),
    "mint-identity-registry": ("L877", "ingest"),
    "signal-fusion-full": ("L409", "ingest"),
    "signal-fusion-active": ("L411", "ingest"),
    "earnings-enrich": ("L551", "ingest"),
    "catalyst-calibration": ("L408", "learn"),
    "agent-outcome-linker": ("L318", "learn"),
    "agent-calibration-engine": ("L314", "learn"),
    "update-agent-performance": ("L427", "learn"),
}
#: C1 premarket flip (2026-10-11): these six D3 lanes' cron lines became steps of premarket-data-pipeline. Their rows
#: are RETIRED (superseded_by the stage lane) and left the wave (dispatch_retired keeps stage/wave/dispatch); their
#: allowlist entries are removed. A stage step cannot also be a dispatcher row.
C1_PREMARKET_ABSORBED = frozenset({"catalyst-calibration", "mint-identity-registry", "earnings-enrich",
                                   "fund-technicals-enrich", "distributions-enrich", "build-symbol-profiles-watchlist"})
#: The D3 lanes still in the wave.
WAVE3_LIVE = {k: v for k, v in WAVE3.items() if k not in C1_PREMARKET_ABSORBED}
#: The three lanes whose cron line gains `flock -n <lock>` (packet n8n-maturity/packets/wave23-flock).
FLOCK_ADDED = {"agent-outcome-linker", "agent-calibration-engine", "update-agent-performance"}
#: Wave-3 lanes moved on to canary (live fire under the cron line's flock lock; tests/test_canary_wave1_20261011.py).
#: research-insight-extractor climbed canary -> cutover 2026-10-13 17:56 ET (operator ran _cutover.py --apply; receipt
#: n8n_cutover/research-insight-extractor-20261013T215647Z-cutover.json): its cron line is `# RETIRED`, its row is an
#: n8n dispatcher row, so it leaves the cron-row checks below and is pinned by test_cutover_row_is_the_dispatcher_row.
CANARY: set[str] = {"hermes-news-bridge"}  # canary-wave-20261014 (news-to-catalyst held at shadow)
CUTOVER = frozenset({"research-insight-extractor"})
#: The wave-3 rows still scheduled by cron (shadow or canary).
WAVE3_ON_CRON = {k: v for k, v in WAVE3_LIVE.items() if k not in CUTOVER}
#: lane -> the stage / dispatch.mode its row carries now.
STAGE = {
    lane: ("cutover", "live") if lane in CUTOVER else ("canary", "live") if lane in CANARY else ("shadow", "dry_run")
    for lane in WAVE3
}


#: Staged r1_pending rows that are NOT activated by the wave-3 simulation (held for a named prerequisite).
HELD_PENDING = frozenset({"run-research-intelligence-overnight"})  # bridge route (lane repair 2026-10-15)


def _activate(row: dict) -> dict:
    """The post-ratification registry edit: apply r1_pending and drop it (identity on an activated row)."""
    out = copy.deepcopy(row)
    if "r1_pending" not in out:
        return out
    pend = out.pop("r1_pending")
    out["scheduler"].update(pend["scheduler"])
    out["output_signal"] = pend["output_signal"]
    out["dispatch"] = pend["dispatch"]
    return out


def _admit(row: dict, shape: str) -> tuple[bool, str]:
    return LD.r1_class_admission(row, ALLOW[row["lane_id"]], shadow_shape_status=shape)


# ------------------------------------------------- the activated rows (AGENTS 4.4.0 ACTIVE, activate_wave3.py)


def test_wave3_is_19_lanes_and_only_r1_classes():
    assert len(WAVE3) == 19
    assert {k for _l, k in WAVE3.values()} == {"ingest", "learn"}
    # activated 2026-10-10; the one staged row since is the lane repair 2026-10-15 llm row, held until its bridge
    # route exists (tests/test_lane_repair_ri_hermes_litmus_20261015.py)
    assert [r["lane_id"] for r in REGISTRY["lanes"] if "r1_pending" in r] == ["run-research-intelligence-overnight"]
    d3 = sorted(r["lane_id"] for r in REGISTRY["lanes"] if (r.get("scheduler") or {}).get("wave") == "D3")
    assert d3 == sorted(WAVE3_LIVE) and len(WAVE3_LIVE) == 13


@pytest.mark.parametrize("lane", sorted(C1_PREMARKET_ABSORBED))
def test_c1_absorbed_lane_left_the_wave(lane):
    row = ROWS[lane]
    assert row["state"] == "RETIRED" and row["superseded_by"] == "premarket-data-pipeline"
    assert "dispatch" not in row and "stage" not in row["scheduler"] and "wave" not in row["scheduler"]
    assert row["dispatch_retired"]["wave"] == "D3" and row["dispatch_retired"]["dispatch"]["class"] == WAVE3[lane][1]
    assert lane not in ALLOW


@pytest.mark.parametrize("lane", sorted(WAVE3_ON_CRON))
def test_row_is_a_shadow_cron_row_admitted_by_the_r1_gate(lane):
    row = ROWS[lane]
    assert LD.R1_SHADOW_SHAPE_STATUS == "ACTIVE"
    assert row["scheduler"]["kind"] == "cron" and row["scheduler"]["stage"] == STAGE[lane][0]
    assert row["state"] == "ACTIVE"
    assert LD.dispatch_mode(row) == STAGE[lane][1]
    assert LD.validate_dispatch_block(row) == []
    assert LD.r1_class_admission(row) == (True, f"r1_admitted:{WAVE3[lane][1]}")


@pytest.mark.parametrize("lane", sorted(WAVE3_ON_CRON))
def test_dispatch_block_shape(lane):
    lno, klass = WAVE3[lane]
    row = ROWS[lane]
    pend = row
    assert lno.startswith("L")
    d = pend["dispatch"]
    assert d["mode"] == STAGE[lane][1] and d["class"] == klass and d["retry_policy"] == "none"
    assert d["cron"] == [row["scheduler"]["expression"]]
    assert pend["scheduler"]["stage"] == STAGE[lane][0] and pend["scheduler"]["wave"] == "D3"
    sig = pend["output_signal"]
    assert sig["kind"] == "json_key" and sig["key"] == "ok_at"
    assert LD.receipt_signal_path({"output_signal": sig}) == sig["path"]


@pytest.mark.parametrize("lane", sorted(WAVE3_LIVE))
def test_allowlist_entry_is_shadow_only_and_carries_no_broker_credential(lane):
    e = ALLOW[lane]
    assert e["live_arg"] is None if lane not in CANARY | CUTOVER else e["live_arg"] == []
    assert e["dry_run_arg"] == ["--dry-run"]
    assert not any(t.startswith("--apply") for t in e["command"])
    assert e["output_signal"] == ROWS[lane]["output_signal"]["path"]
    for name in e["env_names"]:
        assert not any(f in name.upper() for f in LD.BROKER_CREDENTIAL_ENV_FRAGMENTS), (lane, name)
    assert LD.forbidden_text_hits(" ".join(e["command"] + e["dry_run_arg"])) == []


@pytest.mark.parametrize("lane", sorted(WAVE3_ON_CRON))
def test_allowlist_lock_is_the_cron_line_lock(lane):
    """The staged command_text is the live cron command (plus the packet's flock for the three FLOCK_ADDED lanes);
    its flock lock is the allowlist lock, as the canary step will require (r1_canary_lock_matches)."""
    e = ALLOW[lane]
    text = ROWS[lane]["scheduler"]["command_text"]
    if e["lock_kind"] == "flock":
        assert LD.cron_flock_locks(text) == [e["lock"]], (lane, text)
    else:  # catalyst-momentum-engine-overnight: scripts/safe_flock.sh <lock> (needs lock_kind flock before canary)
        assert lane == "catalyst-momentum-engine-overnight" and f"safe_flock.sh {e['lock']} " in text
    if lane in FLOCK_ADDED:
        assert f"flock -n {e['lock']} $PY" in text


#: Receipt names a script builds rather than spells: signal_fusion.py `f"signal_fusion_{mode}"` (--full / --active);
#: catalyst_momentum_engine.py BAND_LANE_IDS["overnight"].
BUILT_RECEIPT_NAMES = {
    "signal_fusion_full": 'f"signal_fusion_{mode}"',
    "signal_fusion_active": 'f"signal_fusion_{mode}"',
}


def test_the_script_writes_the_receipt_the_row_names():
    for lane in WAVE3_LIVE:
        e = ALLOW[lane]
        script = (ROOT / e["command"][1]).read_text(encoding="utf-8")
        stem = Path(e["output_signal"]).name[: -len("_last.json")]
        assert f'"{stem}"' in script or BUILT_RECEIPT_NAMES.get(stem, "\0") in script, (lane, stem)


# ------------------------------------------------------------------------------ refused now, admitted later


@pytest.mark.parametrize("lane", sorted(WAVE3_ON_CRON))
def test_activated_row_is_refused_while_4_4_0_is_proposed(lane):
    row = _activate(ROWS[lane])
    ok, why = _admit(row, "PROPOSED")
    assert not ok and why.startswith("shadow_on_cron_not_ratified"), (lane, why)
    if LD.R1_SHADOW_SHAPE_STATUS != "ACTIVE":  # the real constant on this branch
        ok, why = LD.r1_class_admission(row)
        assert not ok and "shadow_on_cron_not_ratified" in why, (lane, why)


@pytest.mark.parametrize("lane", sorted(WAVE3_ON_CRON))
def test_activated_row_is_admitted_once_4_4_0_is_active(lane, monkeypatch):
    row = _activate(ROWS[lane])
    assert _admit(row, "ACTIVE") == (True, f"r1_admitted:{WAVE3[lane][1]}")
    assert LD.dispatch_eligible(row) == (True, "eligible")
    monkeypatch.setattr(LD, "R1_SHADOW_SHAPE_STATUS", "ACTIVE")
    assert LD.validate_dispatch_block(row, known_lane_ids=set(ROWS), retry_policy_names=set(POLICIES.policies)) == []


def test_activated_registry_has_no_dispatch_issue_once_active(monkeypatch):
    # The lane repair llm row stays staged (not allowlisted until its bridge route exists): not activated here.
    doc = dict(REGISTRY, lanes=[_activate(r) if "r1_pending" in r and r["lane_id"] not in HELD_PENDING else r
                                for r in REGISTRY["lanes"]])
    monkeypatch.setattr(LD, "R1_SHADOW_SHAPE_STATUS", "PROPOSED")
    errs = LD.registry_dispatch_errors(doc)
    # 19 wave-3 rows + the 3 W4 provider-owner rows (tests/test_w4_provider_owners_shadow_20261011.py) - the 6 D3 rows
    # the C1 premarket flip (2026-10-11) absorbed: every R1 cron-shadow row on the registry is refused while 4.4.0 is
    # PROPOSED.
    r1_cron_shadow = [r for r in doc["lanes"] if (r.get("dispatch") or {}).get("class") in LD.R1_ADMITTED_CLASSES
                      and (r.get("scheduler") or {}).get("kind") == "cron"]
    # + 15 SW4 rows (shadow wave 4, 2026-10-11; tests/test_sw4_shadow_wave4_20261011.py).
    # + 10 refactor train 3 rows (shards 01-04, 2026-10-11; tests/test_refactor_shard_0[1-4]_20261011.py): 13 proposed,
    # 3 (register-analyst-sources, source-outcome-attribution, research-intelligence-materialize) stay RETIRED into the
    # premarket C1 stage (train 2), so they are not shadow rows.
    # + 11 train 4 rows (shards 05-08, 2026-10-11; tests/test_refactor_shard_0[5-8]_20261011.py): 22 proposed, 5 stay
    # RETIRED into the premarket C1 stage (train 2), 5 are SW4 EXCLUDED (tests/test_sw4_shadow_wave4_20261011.py) and
    # sec-filings-feed is W4 provider-owner EXCLUDED (tests/test_w4_provider_owners_shadow_20261011.py).
    # - 1: C1 hermes_overnight registry edit (train 6, 2026-10-12) absorbs SW4 hermes-tag-lift-discovery (dispatch_retired).
    # (WAVE3_ON_CRON: research-insight-extractor left cron at cutover, 2026-10-13.)
    # + 2 scalp hot-tier ingest rows (2026-10-14; tests/test_scalp_premarket_onboard_20261014.py).
    assert len(r1_cron_shadow) == len(WAVE3_ON_CRON) + 3 + 15 + 10 + 11 - 1 + 2
    assert len(errs) == len(r1_cron_shadow) and all("shadow_on_cron_not_ratified" in x for x in errs), errs[:3]
    monkeypatch.setattr(LD, "R1_SHADOW_SHAPE_STATUS", "ACTIVE")
    assert LD.registry_dispatch_errors(doc) == []


# ---------------------------------------------------------------------------------- compute_due week sweep


START = datetime(2026, 10, 12, 4, 0, tzinfo=timezone.utc)  # Monday 00:00 America/New_York


def _sweep(rows, allow, days=7):
    """Every 30 minutes (the 'none' policy's catch-up window is 30 min, so no slot is skipped)."""
    emitted, errors = {}, set()
    t = START
    while t < START + timedelta(days=days):
        resp = D.compute_due(rows, allow, POLICIES, None, t)
        for it in resp["items"]:
            emitted.setdefault(it["lane_id"], set()).add(it["mode"])
        errors |= {(e["lane_id"], e["code"]) for e in resp["errors"]}
        t += timedelta(minutes=30)
    return emitted, errors


def test_compute_due_week_sweep_proposed_vs_active(monkeypatch):
    activated = [_activate(ROWS[x]) for x in WAVE3_ON_CRON]
    monkeypatch.setattr(LD, "R1_SHADOW_SHAPE_STATUS", "PROPOSED")
    emitted, errors = _sweep(activated, ALLOW, days=1)
    assert emitted == {} and {c for _l, c in errors} == {"class_not_permitted"}

    monkeypatch.setattr(LD, "R1_SHADOW_SHAPE_STATUS", "ACTIVE")
    live = " ".join(lane for lane, (_stage, mode) in STAGE.items() if mode == "live")
    monkeypatch.setenv(D.LIVE_LANES_ENV, live)
    emitted, errors = _sweep(activated, ALLOW)
    assert errors == set(), sorted(errors)[:5]
    assert set(emitted) == set(WAVE3_ON_CRON), sorted(set(WAVE3_ON_CRON) - set(emitted))
    assert all(modes == {STAGE[lane][1]} for lane, modes in emitted.items())


@pytest.mark.parametrize("lane", sorted(CUTOVER))
def test_cutover_row_is_the_dispatcher_row(lane):
    """§23.11 cutover: the row is scheduled by the n8n dispatcher at the retired cron line's cadence, live, admitted,
    and the stage clamp keeps it live; the allowlist still carries the cron line's flock lock and its live argv."""
    row, e = ROWS[lane], ALLOW[lane]
    s = row["scheduler"]
    assert s["kind"] == "n8n" and s["expression"] == "dispatcher" and s["stage"] == "cutover" and s["wave"] == "D3"
    assert "command_text" not in s and row["dispatch"]["cron"] == [s["cadence"]]
    assert row["state"] == "ACTIVE" and LD.dispatch_mode(row) == "live"
    assert LD.validate_dispatch_block(row) == []
    assert LD.r1_class_admission(row, e) == (True, f"r1_admitted:{WAVE3[lane][1]}")
    assert SC.clamp_mode(lane, "live", REGISTRY["lanes"])["reason"] == "stage_cutover"
    assert e["lock_kind"] == "flock" and e["live_arg"] == []
