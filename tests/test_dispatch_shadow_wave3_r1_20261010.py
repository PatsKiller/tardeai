"""Dispatcher shadow wave D3 (R1 classes ingest / learn), 2026-10-10 — staged inert until AGENTS.md 4.4.0 is ACTIVE.

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
#: The three lanes whose cron line gains `flock -n <lock>` (packet n8n-maturity/packets/wave23-flock).
FLOCK_ADDED = {"agent-outcome-linker", "agent-calibration-engine", "update-agent-performance"}


def _activate(row: dict) -> dict:
    """The post-ratification registry edit: apply r1_pending and drop it."""
    out = copy.deepcopy(row)
    pend = out.pop("r1_pending")
    out["scheduler"].update(pend["scheduler"])
    out["output_signal"] = pend["output_signal"]
    out["dispatch"] = pend["dispatch"]
    return out


def _admit(row: dict, shape: str) -> tuple[bool, str]:
    return LD.r1_class_admission(row, ALLOW[row["lane_id"]], shadow_shape_status=shape)


# ----------------------------------------------------------------------------------------- the staged rows


def test_wave3_is_19_lanes_and_only_r1_classes():
    assert len(WAVE3) == 19
    assert {k for _l, k in WAVE3.values()} == {"ingest", "learn"}
    staged = sorted(r["lane_id"] for r in REGISTRY["lanes"] if "r1_pending" in r)
    assert staged == sorted(WAVE3)


@pytest.mark.parametrize("lane", sorted(WAVE3))
def test_staged_row_is_inert_now(lane):
    row = ROWS[lane]
    assert "dispatch" not in row, lane
    assert LD.dispatch_mode(row) == "off"
    assert "stage" not in row["scheduler"] and row["scheduler"]["kind"] == "cron"
    assert row["state"] == "ACTIVE"
    assert LD.validate_dispatch_block(row) == []
    assert LD.r1_class_admission(row)[1] == "no_dispatch_block"


@pytest.mark.parametrize("lane", sorted(WAVE3))
def test_staged_block_shape(lane):
    lno, klass = WAVE3[lane]
    row = ROWS[lane]
    pend = row["r1_pending"]
    assert pend["inventory"] == f"cron:{lno}"
    assert "4.4.0" in pend["requires"] and "R1_SHADOW_SHAPE_STATUS" in pend["requires"]
    d = pend["dispatch"]
    assert d["mode"] == "dry_run" and d["class"] == klass and d["retry_policy"] == "none"
    assert d["cron"] == [row["scheduler"]["expression"]]
    assert pend["scheduler"]["stage"] == "shadow" and pend["scheduler"]["wave"] == "D3"
    sig = pend["output_signal"]
    assert sig["kind"] == "json_key" and sig["key"] == "ok_at"
    assert LD.receipt_signal_path({"output_signal": sig}) == sig["path"]


@pytest.mark.parametrize("lane", sorted(WAVE3))
def test_allowlist_entry_is_shadow_only_and_carries_no_broker_credential(lane):
    e = ALLOW[lane]
    assert e["live_arg"] is None
    assert e["dry_run_arg"] == ["--dry-run"]
    assert not any(t.startswith("--apply") for t in e["command"])
    assert e["output_signal"] == ROWS[lane]["r1_pending"]["output_signal"]["path"]
    for name in e["env_names"]:
        assert not any(f in name.upper() for f in LD.BROKER_CREDENTIAL_ENV_FRAGMENTS), (lane, name)
    assert LD.forbidden_text_hits(" ".join(e["command"] + e["dry_run_arg"])) == []


@pytest.mark.parametrize("lane", sorted(WAVE3))
def test_allowlist_lock_is_the_cron_line_lock(lane):
    """The staged command_text is the live cron command (plus the packet's flock for the three FLOCK_ADDED lanes);
    its flock lock is the allowlist lock, as the canary step will require (r1_canary_lock_matches)."""
    e = ALLOW[lane]
    text = ROWS[lane]["r1_pending"]["scheduler"]["command_text"]
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
    for lane in WAVE3:
        e = ALLOW[lane]
        script = (ROOT / e["command"][1]).read_text(encoding="utf-8")
        stem = Path(e["output_signal"]).name[: -len("_last.json")]
        assert f'"{stem}"' in script or BUILT_RECEIPT_NAMES.get(stem, "\0") in script, (lane, stem)


# ------------------------------------------------------------------------------ refused now, admitted later


@pytest.mark.parametrize("lane", sorted(WAVE3))
def test_activated_row_is_refused_while_4_4_0_is_proposed(lane):
    row = _activate(ROWS[lane])
    ok, why = _admit(row, "PROPOSED")
    assert not ok and why.startswith("shadow_on_cron_not_ratified"), (lane, why)
    if LD.R1_SHADOW_SHAPE_STATUS != "ACTIVE":  # the real constant on this branch
        ok, why = LD.r1_class_admission(row)
        assert not ok and "shadow_on_cron_not_ratified" in why, (lane, why)


@pytest.mark.parametrize("lane", sorted(WAVE3))
def test_activated_row_is_admitted_once_4_4_0_is_active(lane, monkeypatch):
    row = _activate(ROWS[lane])
    assert _admit(row, "ACTIVE") == (True, f"r1_admitted:{WAVE3[lane][1]}")
    assert LD.dispatch_eligible(row) == (True, "eligible")
    monkeypatch.setattr(LD, "R1_SHADOW_SHAPE_STATUS", "ACTIVE")
    assert LD.validate_dispatch_block(row, known_lane_ids=set(ROWS), retry_policy_names=set(POLICIES.policies)) == []


def test_activated_registry_has_no_dispatch_issue_once_active(monkeypatch):
    doc = dict(REGISTRY, lanes=[_activate(r) if "r1_pending" in r else r for r in REGISTRY["lanes"]])
    monkeypatch.setattr(LD, "R1_SHADOW_SHAPE_STATUS", "PROPOSED")
    errs = LD.registry_dispatch_errors(doc)
    assert len(errs) == 19 and all("shadow_on_cron_not_ratified" in x for x in errs), errs[:3]
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


def test_compute_due_week_sweep_staged_vs_activated(monkeypatch):
    staged = [ROWS[x] for x in WAVE3]
    emitted, errors = _sweep(staged, ALLOW, days=1)
    assert emitted == {} and errors == set()  # staged: nothing emitted, nothing refused

    activated = [_activate(r) for r in staged]
    monkeypatch.setattr(LD, "R1_SHADOW_SHAPE_STATUS", "PROPOSED")
    emitted, errors = _sweep(activated, ALLOW, days=1)
    assert emitted == {} and {c for _l, c in errors} == {"class_not_permitted"}

    monkeypatch.setattr(LD, "R1_SHADOW_SHAPE_STATUS", "ACTIVE")
    emitted, errors = _sweep(activated, ALLOW)
    assert errors == set(), sorted(errors)[:5]
    assert set(emitted) == set(WAVE3), sorted(set(WAVE3) - set(emitted))
    assert all(modes == {"dry_run"} for modes in emitted.values())
