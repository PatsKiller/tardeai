"""Canary-wave effect keys, the cron-side claim wrapper, and the two audit packets (2026-10-15).

Source: ~/n8n-maturity-verification/arch-review-20261014/CANARY_DOUBLE_EFFECT_AUDIT.md. A shared ``flock -n`` stops
a cron run and an n8n run of one lane from overlapping, not from running one after the other in the same slot. So
every live, canary or canary-wave lane whose effect appends rows, sends or calls an LLM gets a semantic effect key
in config/n8n_effect_keys.json, STAGED (cron_claim false, n8n_claim false): nothing changes until each lane's
cutover arms it. Lanes without a manifest runner claim through scripts/effect_claim_cron.sh, off unless the cron
line sets TRADEAI_EFFECT_CLAIM=<lane>.

Hermetic: tmp_path ledgers and configs, fake commands, a disposable PostgreSQL cluster (tests/support/isolated_pg)
for the migration. Never the live ledger, crontab, live-lane file, units or production database.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if str(ROOT / "tests") not in sys.path:
    sys.path.append(str(ROOT / "tests"))
from support import n8n_cutover_waves as CW  # noqa: E402
from tests.support import hermes_learning_cutover as HL  # noqa: E402
from tests.support import comms_intent_consumer_live as CIL  # noqa: E402
from tests.support import disk_hygiene_n8n as DHN  # noqa: E402

from scripts import n8n_run_executor as X  # noqa: E402
from scripts.lib import effect_claim as E  # noqa: E402
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerRunStore  # noqa: E402

CONFIG = ROOT / "config" / "n8n_effect_keys.json"
WRAPPER = ROOT / "scripts" / "effect_claim_cron.sh"
MIG = ROOT / "sql" / "migrations"
MIG_PLAIN = MIG / "20261015_research_insights_source_reference_unique.sql"
MIG_CONC = MIG / "20261015_research_insights_source_reference_unique_concurrently.sql"
MIG_ROLLBACK = MIG / "20261015_research_insights_source_reference_unique_rollback.sql"
PKT_MR = ROOT / "docs" / "ops" / "packets" / "maturity-remeasure-relay-live-removal-20261015"
PKT_RI = ROOT / "docs" / "ops" / "packets" / "research-insights-unique-index-20261015"
INDEX = "uq_research_insights_source_reference"

# ── the lanes in scope (audit 2026-10-14 + MIGRATION_STATUS 2026-10-14 11:30) ──────────────────────────────────────
#: TRADEAI_N8N_RELAY_LIVE_LANES as read (read-only) 2026-10-15.
RELAY_LIVE = (
    "n8n-pilot-dispatch n8n-incident-fanin n8n-research-intake-consumer crontab-snapshot-for-health-agent "
    "maturity-remeasure research-insight-extractor heartbeat-watch"
).split()
TIER_A = (
    "job-coverage-monitor hermes-pipeline-health identity-sweep-stage0 material-change-detector-stage1 "
    "document-mentions-backfill resolve-due-checkpoints agent-number-grounding-slo trade-ai-scalp-live "
    "hermes-entity-spike-discovery data-gap-resolver-at-0-10-16 hermes-analyst-signal-discovery news-to-catalyst "
    "hermes-news-bridge aegis-social-sentiment finviz-proactive-research hermes-research-worker-pool "
    "finviz-sector-research proposal-backtest-engine hermes-scope-governor hermes-score-event-feeder "
    "momentum-cache-reconcile"
).split()
TIER_B = (
    "source-attribution-monitor catalyst-symbol-impact watch-goods-consistency catalyst-graph commitment-outcome-sweep "
    "instrument-belief-writer hermes-research-agenda-at-45-7 write-state-freshness-history classifier-health-check "
    "enterprise-backtester setup-quality-prior data-gap-resolver-pre data-gap-resolver-weekly agent-calibration-engine "
    "agent-outcome-linker signal-fusion-full hermes-topic-monitor-bridge update-agent-performance classify-instruments "
    "sector-rs-daily finviz-enrichment sec-data-ingest social-ingest-all feedback-loop-processor record-decision-outcome "
    "aegis-transcript-discovery aegis-nightly-ingestion trade-backtest-engine update-lockup-earnings-dates "
    "sync-social-to-intelligence hermes-social-sentiment finviz-screener-runner daily-incubator-refresh "
    "weekly-incubator-builder investment-costs trade-thesis-review-engine advisory-desk-run-now "
    "analyst-prospectus-generate aegis-brief-regenerate momentum-lifecycle-monitor"
).split()
#: In scope but NOT keyed: the live effect only overwrites (or only reads). Read-only code trace 2026-10-15.
NOT_KEYED_OVERWRITE_ONLY = {
    "crontab-snapshot-for-health-agent": "tmp + mv of the crontab snapshot",
    "job-coverage-monitor": "read-only check; receipt only",
    "identity-sweep-stage0": "UPDATE ... WHERE subject_guid IS NULL",
    "agent-number-grounding-slo": "SELECT-only report; --out JSON receipt",
    "finviz-sector-research": "ON CONFLICT (snapshot_date, group_type, name) DO UPDATE",
    "momentum-cache-reconcile": "atomic projection rewrite",
    "watch-goods-consistency": "UPDATE ... COALESCE fills empty fields",
    "catalyst-graph": "atomic projection rewrite",
    "classifier-health-check": "read-only session; atomic JSON",
    "enterprise-backtester": "no --apply on the line: OHLC cache overwrite only",
    "setup-quality-prior": "TRUNCATE + rebuild",
    "classify-instruments": "symbol_profiles ON CONFLICT (symbol) DO UPDATE",
    "sector-rs-daily": "ON CONFLICT (rs_date, symbol) DO UPDATE",
    "finviz-enrichment": "atomic cache replace + entity upsert",
    "trade-backtest-engine": "ON CONFLICT (trade_key) DO UPDATE",
    "sync-social-to-intelligence": "entity UPDATE (signal_count counter, no new row)",
    "aegis-brief-regenerate": "rewrites the day's brief export; no send",
    "momentum-lifecycle-monitor": "read-only evaluate (no --write-monitor)",
}
SENDS = {"trade-ai-scalp-live", "hermes-pipeline-health", "update-lockup-earnings-dates"}
LLM = {
    "data-gap-resolver-at-0-10-16",
    "data-gap-resolver-pre",
    "data-gap-resolver-weekly",
    "news-to-catalyst",
    "advisory-desk-run-now",
    "analyst-prospectus-generate",
}
ON_DEMAND = {"advisory-desk-run-now", "analyst-prospectus-generate"}


def _raw() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def _registry() -> dict:
    return {r["lane_id"]: r for r in json.loads((ROOT / "config" / "lane_registry.json").read_text())["lanes"]}


def _scope() -> set[str]:
    reg = _registry()
    canary = {k for k, v in reg.items() if (v.get("scheduler") or {}).get("stage") in ("canary", "cutover")}
    # 2026-10-15 cutover waves (scripts/n8n_cutover_wave.py) promote lanes outside this audit's scope; their keys are
    # that wave's review (tests/support/n8n_cutover_waves.py ARMED), not this audit's.
    canary -= set(CW.PROMOTED) - set(RELAY_LIVE) - set(TIER_A) - set(TIER_B)
    # hermes-learning cutover PR-2: its process step lanes are reviewed by that cutover's pins
    # (tests/support/hermes_learning_cutover.py, tests/test_n8n_fabric_hermes_learning_20261015.py), not this audit.
    canary -= set(HL.LIVE)
    # comms-intent consumer live 2026-10-17 (tests/support/comms_intent_consumer_live.py): n8n-native, no cron side,
    # idempotent per intent; reviewed by tests/test_comms_intent_consumer_live_20261017.py, not keyed.
    canary -= set(CIL.LIVE)
    # disk hygiene + disk-usage monitor 2026-10-18 (tests/support/disk_hygiene_n8n.py; operator approval 2026-10-18:
    # "a script with rules that's repeatable, n8n should run this weekly; and also monitor when a threshold is over
    # 80%"): n8n-native, no cron side to fence; the monitor's intent is deduped by the store, the plan writes only a
    # manifest. Reviewed by tests/test_disk_hygiene_20261018.py, not keyed.
    canary -= set(DHN.LIVE)
    return set(RELAY_LIVE) | set(TIER_A) | set(TIER_B) | canary


STAGED = sorted(_scope() - set(NOT_KEYED_OVERWRITE_ONLY))


# ── 1. every in-scope append/send/LLM lane has a key; keys are unique ──────────────────────────────────────────────


def test_scope_is_the_68_lanes_and_partition_is_complete():
    scope = _scope()
    assert len(set(TIER_A)) == 21 and len(set(TIER_B)) == 40
    assert set(NOT_KEYED_OVERWRITE_ONLY) <= scope
    assert len(scope) == 68 and len(STAGED) == 50


@pytest.mark.parametrize("lane", STAGED)
def test_every_append_send_llm_lane_has_a_staged_key(lane):
    spec = _raw()["lanes"].get(lane)
    assert spec is not None, f"{lane} appends/sends/calls an LLM but has no effect key"
    assert spec["process"] == lane and spec["input_version"] == "v1"
    if lane in CW.ARMED:  # armed by a 2026-10-15 cutover wave for its canary (owner row -> n8n in the wave packet)
        assert spec["cron_claim"] is True and spec["n8n_claim"] is True
    else:
        assert spec["cron_claim"] is False and spec["n8n_claim"] is False
    assert set(spec["effects"]) <= {"append", "send", "llm"} and spec["effects"]
    assert ("send" in spec["effects"]) == (lane in SENDS)
    assert ("llm" in spec["effects"]) == (lane in LLM)
    assert spec["slot_tz"] == "America/New_York"
    if lane in ON_DEMAND:
        assert spec["slot"] == "request_minute" and spec["schedule"] is None
    else:
        assert spec["slot"] == "scheduled_minute" and len(spec["schedule"].split()) == 5
    assert re.match(r"^(guarded|no):", spec["idempotent_today"])
    assert lane in _registry()


def test_overwrite_only_lanes_are_not_keyed():
    assert not set(NOT_KEYED_OVERWRITE_ONLY) & set(_raw()["lanes"])


def test_no_key_outside_scope_except_reviewed_process_steps():
    # The hermes-learning process step lanes (PRs #1746 and #1749) may also be present; anything else is a new review.
    extra = set(_raw()["lanes"]) - set(STAGED) - set(CW.ARMED)
    assert extra <= {
        "hermes-learning-outcome-grader",
        "hermes-learning-outcome-learning",
        "hermes-learning-config-governor",
        "hermes-learning-tag-engine",
        "hermes-learning-outcome-feedback-agent",
        "hermes-learning-autonomous-self-tune",
        # Lane repair 2026-10-15 (tests/test_lane_repair_20261015.py): the entry planner rows are staged r1_pending;
        # each live run appends plans after an LLM call, so the key is staged with them (cron_claim/n8n_claim false).
        "watchlist-entry-planner-limit",
        "watchlist-entry-planner-scope",
        # lane repair 2026-10-15 (tests/test_lane_repair_ri_hermes_litmus_20261015.py): staged, no claim.
        "run-research-intelligence-overnight",
        # shadow wave LD-W1 (2026-10-15): the wave's appending lane, keyed and staged before any canary.
        "incubator-rolloff-engine",
    }


def test_keys_are_unique():
    lanes = E.load_effect_lanes(CONFIG)
    processes = [s["process"] for s in lanes.values()]
    assert len(processes) == len(set(processes))
    keys = [E.effect_key(s["process"], "20261015T0650", s["input_version"]) for s in lanes.values()]
    assert len(keys) == len(set(keys))
    for k in keys:
        assert E.parse_effect_key(k) is not None


def test_committed_staged_keys_arm_neither_side():
    lanes = E.load_effect_lanes(CONFIG)
    executor_view = E.load_effect_config(CONFIG)
    for lane in sorted(set(STAGED) - set(CW.ARMED)):
        assert lane not in executor_view
        assert lanes[lane]["cron_claim"] is False
    for lane in CW.ARMED:
        assert lane in executor_view and lanes[lane]["cron_claim"] is True


# ── 1b. the loader: n8n_claim / cron_claim semantics ───────────────────────────────────────────────────────────────


def _cfg(tmp_path: Path, lanes: dict) -> Path:
    p = tmp_path / "keys.json"
    p.write_text(json.dumps({"schema": E.EFFECT_CONFIG_SCHEMA, "lanes": lanes}))
    return p


def test_n8n_claim_defaults_true_so_older_entries_keep_their_meaning(tmp_path):
    p = _cfg(
        tmp_path,
        {
            "old": {"process": "old", "input_version": "v1"},
            "staged": {"process": "staged", "input_version": "v1", "n8n_claim": False, "cron_claim": False},
            "armed": {"process": "armed", "input_version": "v1", "n8n_claim": True, "cron_claim": True},
        },
    )
    assert set(E.load_effect_config(p)) == {"old", "armed"}
    lanes = E.load_effect_lanes(p)
    assert lanes["old"]["cron_claim"] is False and lanes["old"]["n8n_claim"] is True
    assert lanes["armed"]["cron_claim"] is True


@pytest.mark.parametrize("field,value", [("cron_claim", "false"), ("n8n_claim", 0), ("cron_claim", None)])
def test_non_boolean_claim_flags_fail_closed(tmp_path, field, value):
    p = _cfg(tmp_path, {"x-lane": {"process": "x-lane", "input_version": "v1", field: value}})
    with pytest.raises(E.EffectKeyError):
        E.load_effect_lanes(p)
    with pytest.raises(E.EffectKeyError):
        E.load_effect_config(p)


def test_staged_lane_live_run_through_the_executor_is_unchanged(tmp_path):
    """A live n8n run of a staged lane (research-insight-extractor: live today) with the COMMITTED config: the gate is
    inert, the command runs once, no effect block, no claim row, even with no owner row."""
    ledger = CoordinationLedger(tmp_path / "ledger.sqlite")
    try:
        gate = X.EffectGate.from_ledger(ledger, ROOT)
        assert gate.config_error is None
        runs = LedgerRunStore(ledger)
        lane = "research-insight-extractor"
        run_id = f"d:{lane}:live:20261015T0650"
        runs.request(run_id=run_id, lane_id=lane, mode="live", requested_by="t", caller_id="n8n-relay", now=1.0)
        calls = []

        def runner(argv, *, timeout, env, cwd):
            calls.append(argv)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        entry = {
            "lane_id": lane,
            "command": ["$PY", "scripts/fake.py"],
            "lock": str(tmp_path / "fake.lock"),
            "timeout_s": 60,
            "dry_run_arg": ["--dry-run"],
            "live_arg": [],
        }
        out = X.drain(
            runs, {lane: entry}, env={}, state_root=tmp_path / "s", code_root=tmp_path, runner=runner, effects=gate
        )
        assert out[-1]["state"] == "RUN_DONE" and "effect" not in out[-1] and len(calls) == 1
        assert E.EffectClaimStore(ledger).get(E.effect_key(lane, "20261015T0650", "v1")) is None
    finally:
        ledger.close()


def test_lane_spec_cli(tmp_path, capsys):
    p = _cfg(tmp_path, {"x-lane": {"process": "x-proc", "input_version": "v2", "cron_claim": True}})
    assert E.main(["lane-spec", "--lane", "x-lane", "--config", str(p)]) == 0
    assert capsys.readouterr().out.strip().split("\t") == ["x-proc", "v2", "1"]
    assert E.main(["lane-spec", "--lane", "absent", "--config", str(p)]) == E.LANE_NOT_KEYED_EXIT
    (tmp_path / "bad.json").write_text("{nope")
    assert E.main(["lane-spec", "--lane", "x-lane", "--config", str(tmp_path / "bad.json")]) == 2


# ── 2. the cron-side wrapper: off / on / refusal ───────────────────────────────────────────────────────────────────

SLOT = "20261015T0650"


@pytest.fixture
def wrap(tmp_path):
    ledger_path = tmp_path / "ledger.sqlite"
    marker = tmp_path / "ran.txt"
    logs = tmp_path / "logs"

    def run(lane="x-lane", *, on=None, config=None, code=0, slot=SLOT, extra_env=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith("TRADEAI_EFFECT")}
        env.update(
            {
                "EFFECT_CLAIM_PY": sys.executable,
                "TRADEAI_N8N_COORDINATION_LEDGER": str(ledger_path),
                "EFFECT_CLAIM_LOG_DIR": str(logs),
                "TRADEAI_EFFECT_SLOT": slot,
            }
        )
        if on is not None:
            env["TRADEAI_EFFECT_CLAIM"] = on
        if config is not None:
            env["TRADEAI_EFFECT_CLAIM_CONFIG"] = str(config)
        env.update(extra_env or {})
        cmd = ["bash", str(WRAPPER), lane, "bash", "-c", f'echo run >> "{marker}"; exit {code}']
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=60)
        return r

    def runs() -> int:
        return len(marker.read_text().splitlines()) if marker.exists() else 0

    def events() -> list[dict]:
        f = logs / "effect_claim_events.jsonl"
        return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []

    def store():
        return E.EffectClaimStore(CoordinationLedger(ledger_path))

    return SimpleNamespace(run=run, runs=runs, events=events, store=store, ledger=ledger_path, tmp=tmp_path)


def _armed(tmp_path, cron_claim=True):
    return _cfg(tmp_path, {"x-lane": {"process": "x-lane", "input_version": "v1", "cron_claim": cron_claim}})


def test_wrapper_off_by_default_is_a_plain_exec(wrap, tmp_path):
    r = wrap.run(config=_armed(tmp_path), code=7)
    assert r.returncode == 7 and wrap.runs() == 1
    assert not wrap.ledger.exists() and wrap.events() == []  # no python, no ledger, no event


def test_wrapper_switch_is_per_line_not_global(wrap, tmp_path):
    for value in ("1", "true", "other-lane", ""):
        r = wrap.run(on=value, config=_armed(tmp_path))
        assert r.returncode == 0
    assert wrap.runs() == 4 and not wrap.ledger.exists() and wrap.events() == []


def test_wrapper_on_but_cron_claim_false_runs_unclaimed(wrap, tmp_path):
    wrap.store()  # a reachable ledger (no owner row); an unreachable one fails closed for an armed key (finding 2)
    r = wrap.run(on="x-lane", config=_armed(tmp_path, cron_claim=False), code=3)
    assert r.returncode == 3 and wrap.runs() == 1
    assert [e["event"] for e in wrap.events()] == ["run_unclaimed_cron_claim_false", "completed_unclaimed"]
    assert wrap.events()[-1]["exit_code"] == 3


def test_committed_config_keeps_every_staged_lane_unclaimed_even_when_switched_on(wrap):
    r = wrap.run("research-insight-extractor", on="research-insight-extractor")
    assert r.returncode == 0 and wrap.runs() == 1 and not wrap.ledger.exists()
    assert wrap.events()[0]["event"] == "run_unclaimed_cron_claim_false"


def test_wrapper_on_refuses_an_unkeyed_lane(wrap, tmp_path):
    r = wrap.run("not-keyed", on="not-keyed", config=_armed(tmp_path))
    assert r.returncode == 65 and wrap.runs() == 0
    assert wrap.events()[0]["event"] == "refused_not_keyed"


def test_wrapper_on_refuses_an_unreadable_config(wrap, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{nope")
    r = wrap.run(on="x-lane", config=bad)
    assert r.returncode == 65 and wrap.runs() == 0
    assert wrap.events()[0]["event"] == "refused_config_unreadable"


def test_wrapper_armed_without_owner_row_refuses(wrap, tmp_path):
    wrap.store()  # reachable ledger, tables, no owner row
    r = wrap.run(on="x-lane", config=_armed(tmp_path))
    assert r.returncode == E.REFUSED_EXIT and wrap.runs() == 0
    assert "effect_no_owner" in r.stderr and wrap.events()[0]["event"] == "refused_claim"


def test_wrapper_armed_claims_once_per_slot(wrap, tmp_path):
    cfg = _armed(tmp_path)
    wrap.store().set_owner("x-lane", "cron", expect_epoch=None, by="t", now=1.0)
    first = wrap.run(on="x-lane", config=cfg)
    second = wrap.run(on="x-lane", config=cfg)
    assert first.returncode == 0 and second.returncode == E.REFUSED_EXIT
    assert wrap.runs() == 1 and "effect_already_claimed" in second.stderr
    row = wrap.store().get(f"fx:x-lane:{SLOT}:v1")
    assert row["state"] == "DONE" and row["scheduler"] == "cron"
    assert [e["event"] for e in wrap.events()] == ["completed_claimed", "refused_claim"]
    nxt = wrap.run(on="x-lane", config=cfg, slot="20261015T1250")  # the next slot runs
    assert nxt.returncode == 0 and wrap.runs() == 2


def test_wrapper_refuses_when_n8n_owns_the_process(wrap, tmp_path):
    # 2026-10-16 (architect review): the production owner switch (effect_claim.py set-owner) also writes the
    # handover manifest; with both stores saying n8n the wrapper skips before it ever claims.
    E.set_owner_with_manifest(wrap.store(), tmp_path / E.HANDOVER_NAME, "x-lane", "n8n", expect_epoch=None, by="t",
                              now=1.0)
    r = wrap.run(on="x-lane", config=_armed(tmp_path))
    # 2026-10-16 (cron effect-claim wrap): owner n8n is a clean skip, exit 0 + skipped_effect (was 75).
    assert r.returncode == 0 and wrap.runs() == 0 and "owned by n8n" in r.stderr
    assert wrap.events()[-1]["event"] == "skipped_effect"


def test_wrapper_failed_run_may_be_retried_in_the_same_slot(wrap, tmp_path):
    cfg = _armed(tmp_path)
    wrap.store().set_owner("x-lane", "cron", expect_epoch=None, by="t", now=1.0)
    assert wrap.run(on="x-lane", config=cfg, code=4).returncode == 4
    key = f"fx:x-lane:{SLOT}:v1"
    assert wrap.store().get(key)["state"] == "FAILED"
    # 2026-10-15 (audit DD05): the failed run may have written before exiting non-zero, so the slot is held until an
    # operator release (after checking the target); then the retry runs.
    assert wrap.run(on="x-lane", config=cfg).returncode == 75 and wrap.runs() == 1
    wrap.store().release(key, by="t", now=2.0, note="target checked: no row for the slot")
    assert wrap.run(on="x-lane", config=cfg).returncode == 0 and wrap.runs() == 2


def test_wrapper_n8n_first_then_cron_same_slot_is_refused(wrap, tmp_path):
    cfg = _armed(tmp_path)
    st = wrap.store()
    st.set_owner("x-lane", "n8n", expect_epoch=None, by="t", now=1.0)
    assert st.claim(f"fx:x-lane:{SLOT}:v1", scheduler="n8n", now=2.0).ok
    st.set_owner("x-lane", "cron", expect_epoch=1, by="t", now=3.0)  # ownership moves back mid-slot
    r = wrap.run(on="x-lane", config=cfg)
    assert r.returncode == E.REFUSED_EXIT and wrap.runs() == 0 and "effect_already_claimed" in r.stderr


def test_wrapper_usage_error():
    r = subprocess.run(["bash", str(WRAPPER), "only-lane"], capture_output=True, text=True)
    assert r.returncode == 2 and "Usage" in r.stderr


def test_wrapper_slot_now_is_the_new_york_minute():
    assert E.slot_now(datetime(2026, 10, 15, 10, 50, 30, tzinfo=timezone.utc).timestamp()) == "20261015T0650"


# ── 3. the maturity-remeasure live-list packet ─────────────────────────────────────────────────────────────────────


def _edit_mod():
    spec = importlib.util.spec_from_file_location("edit_live_lanes", PKT_MR / "edit_live_lanes.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


LIVE_FILE = "# lanes\nTRADEAI_N8N_RELAY_LIVE_LANES=" + " ".join(RELAY_LIVE) + "\n"


def test_packet_removes_only_maturity_remeasure():
    m = _edit_mod()
    new = m.remove_lane(LIVE_FILE, "maturity-remeasure")
    assert m.lanes_of(new) == [x for x in RELAY_LIVE if x != "maturity-remeasure"]
    assert new.startswith("# lanes\n") and new.endswith("\n")
    assert m.add_lane(new, "maturity-remeasure").count("maturity-remeasure") == 1


@pytest.mark.parametrize(
    "text,lane",
    [
        ("TRADEAI_N8N_RELAY_LIVE_LANES=a-lane b-lane\n", "maturity-remeasure"),  # absent
        ("TRADEAI_N8N_RELAY_LIVE_LANES=maturity-remeasure maturity-remeasure\n", "maturity-remeasure"),
        (
            "TRADEAI_N8N_RELAY_LIVE_LANES=x-lane\nTRADEAI_N8N_RELAY_LIVE_LANES=maturity-remeasure\n",
            "maturity-remeasure",
        ),
        ("OTHER=1\n", "maturity-remeasure"),
        (LIVE_FILE, "Bad Lane"),
    ],
)
def test_packet_refuses_ambiguous_files(text, lane):
    m = _edit_mod()
    with pytest.raises(m.EditRefused):
        m.remove_lane(text, lane)


def test_packet_cli_dry_run_writes_nothing_and_apply_is_atomic(tmp_path):
    f = tmp_path / "n8n-live-lanes.env"
    f.write_text(LIVE_FILE)
    f.chmod(0o600)
    m = _edit_mod()
    assert m.main(["--file", str(f), "--remove", "maturity-remeasure"]) == 0
    assert f.read_text() == LIVE_FILE
    assert m.main(["--file", str(f), "--remove", "maturity-remeasure", "--apply"]) == 0
    assert "maturity-remeasure" not in f.read_text() and (f.stat().st_mode & 0o777) == 0o600
    assert m.main(["--file", str(f), "--remove", "maturity-remeasure", "--apply"]) == 3  # already gone


def test_packet_apply_script_backs_up_and_dry_runs_by_default(tmp_path):
    f = tmp_path / "n8n-live-lanes.env"
    f.write_text(LIVE_FILE)
    env = {**os.environ, "LIVE_LANES_FILE": str(f)}
    env.pop("APPLY", None)
    r = subprocess.run(["bash", str(PKT_MR / "01_apply.sh")], env=env, capture_output=True, text=True)
    assert r.returncode == 0 and f.read_text() == LIVE_FILE and "set APPLY=1" in r.stdout
    r = subprocess.run(["bash", str(PKT_MR / "01_apply.sh")], env={**env, "APPLY": "1"}, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "maturity-remeasure" not in f.read_text()
    backups = list(tmp_path.glob("n8n-live-lanes.env.pre-maturity-remeasure-removal-*"))
    assert len(backups) == 1 and backups[0].read_text() == LIVE_FILE
    r = subprocess.run(["bash", str(PKT_MR / "02_restart.sh")], env=env, capture_output=True, text=True)
    assert r.returncode == 0 and "would restart" in r.stdout  # no APPLY: restarts nothing


def test_packet_scripts_parse():
    for f in sorted(PKT_MR.glob("*.sh")) + sorted(PKT_RI.glob("*.sh")) + [WRAPPER]:
        r = subprocess.run(["bash", "-n", str(f)], capture_output=True, text=True)
        assert r.returncode == 0, (f, r.stderr)


# ── 4. the research_insights migration: SQL parse + idempotency on a disposable cluster ────────────────────────────


def split_sql(text: str) -> list[str]:
    """Statements of a migration file: comments stripped, ';' splits outside quotes and $$ bodies."""
    out, buf, i, n = [], [], 0, len(text)
    in_dollar = in_quote = False
    while i < n:
        if not in_dollar and not in_quote and text.startswith("--", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if not in_quote and text.startswith("$$", i):
            in_dollar = not in_dollar
            buf.append("$$")
            i += 2
            continue
        c = text[i]
        if not in_dollar and c == "'":
            in_quote = not in_quote
        if c == ";" and not in_dollar and not in_quote:
            stmt = "".join(buf).strip()
            if stmt:
                out.append(stmt)
            buf = []
        else:
            buf.append(c)
        i += 1
    assert not in_dollar and not in_quote, "unterminated $$ body or quote"
    assert not "".join(buf).strip(), "trailing statement without ';'"
    return out


def _kind(stmt: str) -> str:
    return " ".join(stmt.split()[:2]).upper()


def _code(sql: str) -> str:
    """SQL with string literals blanked (a RAISE message may name DROP INDEX as advice)."""
    return re.sub(r"'[^']*'", "''", sql)


def _balanced(stmt: str) -> bool:
    depth = 0
    for c in re.sub(r"'[^']*'", "", stmt):
        depth += c == "("
        depth -= c == ")"
        if depth < 0:
            return False
    return depth == 0


def test_plain_migration_parses_and_is_one_transaction():
    stmts = split_sql(MIG_PLAIN.read_text())
    kinds = [_kind(s) for s in stmts]
    assert kinds[0] == "BEGIN" and kinds[-1] == "COMMIT"
    assert kinds.count("CREATE UNIQUE") == 1 and kinds.count("DO $$") == 1
    create = next(s for s in stmts if _kind(s) == "CREATE UNIQUE")
    assert re.fullmatch(
        rf"CREATE UNIQUE INDEX IF NOT EXISTS {INDEX}\s+ON research_insights \(source_reference\)", create
    )
    assert all(_balanced(s) for s in stmts)
    assert not re.search(r"\b(DELETE|TRUNCATE|DROP|UPDATE|INSERT)\b", _code("\n".join(stmts)))


def test_concurrent_migration_parses_and_has_no_transaction():
    stmts = split_sql(MIG_CONC.read_text())
    kinds = [_kind(s) for s in stmts]
    assert "BEGIN" not in kinds and "COMMIT" not in kinds
    create = [s for s in stmts if _kind(s) == "CREATE UNIQUE"]
    assert len(create) == 1 and re.fullmatch(
        rf"CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {INDEX}\s+ON research_insights \(source_reference\)",
        create[0],
    )
    assert kinds.count("DO $$") == 2  # preflight + postcheck
    assert all(_balanced(s) for s in stmts)
    assert not re.search(r"\b(DELETE|TRUNCATE|DROP|UPDATE|INSERT)\b", _code("\n".join(stmts)))


def test_rollback_only_drops_the_index():
    stmts = split_sql(MIG_ROLLBACK.read_text())
    assert stmts[-1] == f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX}"
    assert [_kind(s) for s in stmts] == ["SET LOCK_TIMEOUT", "DROP INDEX"]


try:
    from support.isolated_pg import IsolatedPostgres, pg_bin_dir

    pg_bin_dir()
    HAVE_PG = True
except Exception:  # noqa: BLE001
    HAVE_PG = False


@pytest.fixture(scope="module")
def pg():
    if not HAVE_PG:
        pytest.skip("no PostgreSQL server binaries on this host")
    cluster = IsolatedPostgres()
    try:
        cluster.start()
        cluster.verify_isolated()
        yield cluster
    finally:
        cluster.stop()


def _psql_file(pg, path: Path):
    return pg._run(
        str(pg_bin_dir() / "psql"),
        "-X",
        "-h",
        pg.host,
        "-p",
        str(pg.port),
        "-U",
        pg.user,
        "-d",
        pg.dbname,
        "-v",
        "ON_ERROR_STOP=1",
        "-f",
        str(path),
        env={**os.environ, "PGPASSWORD": pg.password},
    )


def _q(pg, sql: str) -> str:
    r = pg._run(
        str(pg_bin_dir() / "psql"),
        "-X",
        "-At",
        "-h",
        pg.host,
        "-p",
        str(pg.port),
        "-U",
        pg.user,
        "-d",
        pg.dbname,
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
        sql,
        env={**os.environ, "PGPASSWORD": pg.password},
    )
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _reset(pg, rows=("news:1", "catalyst:1", None, None)):
    _q(pg, "DROP TABLE IF EXISTS research_insights")
    _q(
        pg,
        "CREATE TABLE research_insights (id BIGSERIAL PRIMARY KEY, source_reference TEXT, "
        "thesis_type TEXT NOT NULL DEFAULT 'neutral', created_at TIMESTAMPTZ DEFAULT NOW())",
    )
    for ref in rows:
        _q(
            pg,
            "INSERT INTO research_insights (source_reference) VALUES (" + ("NULL" if ref is None else f"'{ref}'") + ")",
        )


def _index_state(pg) -> str:
    return _q(
        pg,
        f"SELECT coalesce((SELECT indisvalid::text || ',' || indisunique::text FROM pg_index "
        f"WHERE indexrelid = to_regclass('public.{INDEX}')), 'absent')",
    )


@pytest.mark.parametrize("path", [MIG_PLAIN, MIG_CONC], ids=["plain", "concurrently"])
def test_migration_is_idempotent_and_enforces_uniqueness(pg, path):
    _reset(pg)
    for _ in range(2):  # second application is a no-op
        r = _psql_file(pg, path)
        assert r.returncode == 0, r.stderr
        assert _index_state(pg) == "true,true"
    assert _q(pg, "SELECT count(*) FROM research_insights") == "4"  # no row touched; NULLs stay allowed
    dup = pg._run(
        str(pg_bin_dir() / "psql"),
        "-X",
        "-h",
        pg.host,
        "-p",
        str(pg.port),
        "-U",
        pg.user,
        "-d",
        pg.dbname,
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
        "INSERT INTO research_insights (source_reference) VALUES ('news:1')",
        env={**os.environ, "PGPASSWORD": pg.password},
    )
    assert dup.returncode != 0 and "duplicate key" in dup.stderr
    _q(pg, "INSERT INTO research_insights (source_reference) VALUES (NULL)")
    r = _psql_file(pg, MIG_ROLLBACK)
    assert r.returncode == 0 and _index_state(pg) == "absent"
    assert _psql_file(pg, MIG_ROLLBACK).returncode == 0  # rollback idempotent too


@pytest.mark.parametrize("path", [MIG_PLAIN, MIG_CONC], ids=["plain", "concurrently"])
def test_migration_refuses_existing_duplicates_and_changes_nothing(pg, path):
    _reset(pg, rows=("news:1", "news:1", "catalyst:2"))
    r = _psql_file(pg, path)
    assert r.returncode != 0 and "duplicate source_reference groups" in r.stderr
    assert _index_state(pg) == "absent" and _q(pg, "SELECT count(*) FROM research_insights") == "3"


@pytest.mark.parametrize("path", [MIG_PLAIN, MIG_CONC], ids=["plain", "concurrently"])
def test_migration_refuses_an_invalid_leftover_index(pg, path):
    _reset(pg)
    _q(pg, f"CREATE UNIQUE INDEX {INDEX} ON research_insights (source_reference)")
    _q(pg, f"UPDATE pg_index SET indisvalid = false WHERE indexrelid = to_regclass('public.{INDEX}')")
    r = _psql_file(pg, path)
    assert r.returncode != 0 and "INVALID" in r.stderr
    assert _psql_file(pg, MIG_ROLLBACK).returncode == 0 and _index_state(pg) == "absent"
    assert _psql_file(pg, path).returncode == 0 and _index_state(pg) == "true,true"
