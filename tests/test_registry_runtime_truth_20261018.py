"""Registry / runtime truth (2026-10-18 external review; packet docs/ops/packets/registry-runtime-truth-20261018/).

Five Hermes fabric step lanes were declared NEVER_SCHEDULED (contracts at shadow) while n8n owned their effect keys
and ran them live; every gate was green. This file pins:

* the reconciliation: the five steps ACTIVE at canary with run-id evidence, REVIEWED contracts at canary, the held
  feedback agent unchanged, the parent cron rows' effect_ownership blocks;
* scripts/check_registry_runtime_truth.py: every contradiction rule on hermetic fixtures (the pre-fix Hermes shape
  fires DECLARED_OFF_BUT_RUNS_LIVE / EFFECT_OWNER_N8N_NOT_LIVE / LIVE_LIST_REGISTRY_NOT_LIVE /
  PROCESS_LIVE_STEP_NOT_ACTIVE; the declared dual state of a cron row at canary with dispatch live does not), the
  NOT_MEASURED rule for unreadable sources, a dry run that writes nothing and leaves the ledger byte-identical, an
  apply run that writes a LaneRunReceipt@v2 the executor's output verdict accepts and queues exactly ONE deduped
  host comms intent, and an import closure that never reaches the coordination gateway;
* the lane registry-runtime-truth (registry row, allowlist entry, REVIEWED contract, host route) and the explicit
  output-signal exemptions of docs/ops/OUTPUT_SIGNAL_COVERAGE_20261018.md.

Hermetic: tmp ledgers, tmp state roots, fixture repo roots; no crontab, no docker, no live ledger, no send.

COVERS = ["scripts/check_registry_runtime_truth.py", "config/lane_registry.json", "config/n8n_run_allowlist.json",
          "config/n8n_health_contracts.json", "config/host_comms_intent_routes.json", "scripts/lib/lane_registry.py"]
"""

from __future__ import annotations

import ast
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import check_registry_runtime_truth as RT  # noqa: E402
from scripts.lib import lane_last_receipt as R  # noqa: E402
from scripts.lib import lane_registry as LR  # noqa: E402
from scripts.lib import n8n_output_verdict as OV  # noqa: E402
from tests.support import hermes_learning_cutover as HL  # noqa: E402
from tests.support import registry_runtime_truth_lane as RRT  # noqa: E402

LANE = "registry-runtime-truth"
CONFIG = ROOT / "config"
NOW = datetime(2026, 10, 19, 11, 20, tzinfo=timezone.utc)
WID = "tradeai-fabric-hermes-learning"


def _load(name: str) -> dict:
    return json.loads((CONFIG / name).read_text(encoding="utf-8"))


REG = {r["lane_id"]: r for r in _load("lane_registry.json")["lanes"]}
CONTRACTS = {c["id"]: c for c in _load("n8n_health_contracts.json")["contracts"]}
ALLOW = {e["lane_id"]: e for e in _load("n8n_run_allowlist.json")["lanes"]}


# ── fixtures ─────────────────────────────────────────────────────────────────────────────────────────────────────


def _row(lane, *, state="ACTIVE", kind="n8n", expression=WID, stage="canary", dispatch=None, **extra):
    sched = {"kind": kind, "expression": expression, "match": f"{expression}:x"}
    if stage is not None:
        sched["stage"] = stage
    row = {"lane_id": lane, "owner": "t", "state": state, "scheduler": sched, "expected_cadence_hours": 24,
           "output_signal": {"kind": "none"}}
    if dispatch:
        row["dispatch"] = {"mode": dispatch}
    row.update(extra)
    return row


def _decl(rows, contracts=(), allow=(), processes=None, grandfathered=()):
    return {"rows": {r["lane_id"]: r for r in rows}, "contracts": {c["id"]: c for c in contracts},
            "allow": {e["lane_id"]: e for e in allow}, "processes": processes or {},
            "grandfathered_draft": list(grandfathered)}


def _contract(lane, stage="canary", status="REVIEWED"):
    return {"id": lane, "kind": "lane", "status": status, "stage": stage}


def _allow(lane, live=("--apply",)):
    return {"lane_id": lane, "live_arg": list(live) if live is not None else None}


def _ledger(path: Path, *, runs=(), owners=()):
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE runs (run_id TEXT PRIMARY KEY, lane_id TEXT, mode TEXT, state TEXT, requested_at TEXT);"
        "CREATE TABLE effect_owners (process TEXT PRIMARY KEY, owner TEXT, epoch INTEGER, switched_at TEXT,"
        " switched_by TEXT, note TEXT);"
    )
    for i, (lane, mode, state, at) in enumerate(runs):
        conn.execute("INSERT INTO runs VALUES (?, ?, ?, ?, ?)", (f"r{i}", lane, mode, state, at))
    for process, owner in owners:
        conn.execute("INSERT INTO effect_owners VALUES (?, ?, 2, '2026-10-16T17:20:08Z', 'op', 'n')", (process, owner))
    conn.commit()
    conn.close()
    return path


def _codes(found):
    return sorted({(c["code"], c["lane_id"]) for c in found})


PRE_FIX = "hermes-learning-tag-engine"


def _pre_fix_shape():
    """The 2026-10-18 shape: NEVER_SCHEDULED at canary, contract shadow, live_arg set, process mode live."""
    rows = [_row(PRE_FIX, state="NEVER_SCHEDULED")]
    processes = {"hermes-learning": {"mode": "live", "steps": {"tag_engine": {"lane_id": PRE_FIX, "blocked": None}}}}
    return _decl(rows, [_contract(PRE_FIX, stage="shadow")], [_allow(PRE_FIX)], processes)


# ── 1. the reconciliation itself ─────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("lane", HL.LIVE)
def test_the_five_proven_steps_are_active_at_canary_with_run_evidence(lane):
    row = REG[lane]
    assert row["state"] == "ACTIVE" and row["state_since"] == "2026-10-17"
    assert row["scheduler"]["kind"] == "n8n" and row["scheduler"]["expression"] == WID
    assert row["scheduler"]["stage"] == "canary"  # not cutover: the parent cron line still fires (fenced)
    assert row["reason_confidence"] == "ESTABLISHED"
    assert f"p:{lane}:live:" in row["reason_evidence"] and "RUN_DONE" in row["reason_evidence"]
    assert row["canary"]["since"] == "2026-10-17" and row["canary"]["rollback"]
    assert CONTRACTS[lane]["status"] == "REVIEWED" and CONTRACTS[lane]["stage"] == "canary"


def test_learn_steps_record_their_output_proof_gap_honestly():
    for lane in HL.LEARN_LIVE:
        assert "declared_not_enforced" in REG[lane]["reason_evidence"], lane
        assert ALLOW[lane].get("output_receipt") != "v2", lane  # if this flips, rewrite the gap note


def test_feedback_agent_stays_held():
    (lane,) = HL.HELD
    assert REG[lane]["state"] == "NEVER_SCHEDULED" and REG[lane]["scheduler"]["stage"] == "shadow"
    assert ALLOW[lane]["live_arg"] is None and CONTRACTS[lane]["stage"] == "shadow"


def test_parent_cron_rows_declare_partial_ownership():
    learn, tune = REG["hermes-learning-pipeline-learn"], REG["hermes-learning-pipeline-tune"]
    assert learn["scheduler"]["kind"] == "cron" and learn["state"] == "ACTIVE"
    assert set(learn["effect_ownership"]["n8n_owned_steps"].values()) == set(HL.LEARN_LIVE)
    assert "outcome_feedback_agent" in learn["effect_ownership"]["cron_owned_steps"]
    assert "score_history_retention" in learn["effect_ownership"]["cron_owned_steps"]
    assert set(tune["effect_ownership"]["n8n_owned_steps"].values()) == set(HL.TUNE_LIVE)
    assert tune["effect_ownership"]["cron_owned_steps"] == {}
    for row in (learn, tune):
        assert "Pending: the first natural --apply run" not in row["reason_evidence"].split("Was:")[0]


def test_fabric_index_workflows_are_known_so_the_active_fabric_is_not_undeclared():
    known = LR.n8n_known_workflow_ids()
    for wid in ("tradeai-fabric-run-lane", "tradeai-fabric-error", WID):
        assert wid in known
    found = {"n8n": [{"kind": "n8n", "expression": "tradeai-fabric-run-lane", "name": "x"}], "cron": [], "systemd": []}
    assert LR.find_undeclared({"lanes": []}, found, n8n_known_ids=known) == []
    snap = json.loads((ROOT / "docs/implementation/n8n-parallel/workflows/active_workflows_snapshot.json").read_text())
    active = {w["id"] for w in snap["workflows"]}
    assert WID in active
    assert LR.find_inactive_n8n_rows({"lanes": list(REG.values())}, {"n8n": [{"expression": w} for w in active]}) == []


def test_fabric_index_fails_closed(tmp_path):
    with pytest.raises(OSError):
        LR.n8n_fabric_workflow_ids(tmp_path / "missing.json")
    bad = tmp_path / "INDEX.json"
    bad.write_text(json.dumps({"schema": "Other@v1", "workflows": [{"id": "x"}]}), encoding="utf-8")
    with pytest.raises(ValueError):
        LR.n8n_fabric_workflow_ids(bad)


# ── 2. rules (pure) ──────────────────────────────────────────────────────────────────────────────────────────────


def test_pre_fix_hermes_shape_is_caught_by_four_rules():
    ledger = {"live_runs": {PRE_FIX: {"count": 3, "last": "2026-10-18T14:50:15Z"}},
              "owners": {PRE_FIX: {"owner": "n8n", "epoch": 2, "switched_at": "x"}}}
    found, nm, _ = RT.evaluate(_pre_fix_shape(), ledger=ledger, live_lanes=[PRE_FIX], cron_lines=[], n8n_active=[WID])
    assert _codes(found) == [
        ("DECLARED_OFF_BUT_RUNS_LIVE", PRE_FIX),
        ("EFFECT_OWNER_N8N_NOT_LIVE", PRE_FIX),
        ("LIVE_LIST_REGISTRY_NOT_LIVE", PRE_FIX),
        ("PROCESS_LIVE_STEP_NOT_ACTIVE", PRE_FIX),
    ]
    assert nm == []
    assert all(c["evidence"] for c in found)


def test_reconciled_shape_is_clean():
    decl = _decl([_row(PRE_FIX)], [_contract(PRE_FIX)], [_allow(PRE_FIX)],
                 {"p": {"mode": "live", "steps": {"s": {"lane_id": PRE_FIX}}}})
    ledger = {"live_runs": {PRE_FIX: {"count": 3, "last": "x"}}, "owners": {PRE_FIX: {"owner": "n8n"}}}
    found, nm, acc = RT.evaluate(decl, ledger=ledger, live_lanes=[PRE_FIX], cron_lines=[], n8n_active=[WID])
    assert found == [] and nm == [] and acc == []


def test_cron_row_with_dispatch_live_at_canary_is_the_declared_dual_state_not_a_contradiction():
    lane = "aegis-social-sentiment"
    decl = _decl([_row(lane, kind="cron", expression="0 7 * * *", dispatch="live")], [_contract(lane)], [_allow(lane)])
    ledger = {"live_runs": {lane: {"count": 1, "last": "x"}}, "owners": {lane: {"owner": "n8n"}}}
    found, _, _ = RT.evaluate(decl, ledger=ledger, live_lanes=[lane], cron_lines=[], n8n_active=[])
    assert found == []
    decl = _decl([_row(lane, kind="cron", expression="0 7 * * *", stage=None)])
    found, _, _ = RT.evaluate(decl, ledger=ledger, live_lanes=None, cron_lines=None, n8n_active=None)
    assert _codes(found) == [("EFFECT_OWNER_N8N_KIND_NOT_N8N", lane)]


def test_live_list_rules_registry_contract_and_live_arg():
    a, b, c = "lane-a", "lane-b", "lane-c"
    decl = _decl(
        [_row(a, stage="shadow"), _row(b), _row(c)],
        [_contract(b, status="DRAFT"), _contract(c)],
        [_allow(a), _allow(b, live=None)],
    )
    found, _, _ = RT.evaluate(decl, ledger={"live_runs": {}, "owners": {}}, live_lanes=[a, b, c, "ghost"],
                              cron_lines=[], n8n_active=[WID])
    # a: shadow row, no contract; b: DRAFT contract (not grandfathered), live_arg null; c: no allowlist entry;
    # ghost: on the live list with nothing declared at all.
    assert _codes(found) == [
        ("LIVE_LIST_CONTRACT_NOT_LIVE", "ghost"),
        ("LIVE_LIST_CONTRACT_NOT_LIVE", a),
        ("LIVE_LIST_CONTRACT_NOT_LIVE", b),
        ("LIVE_LIST_NO_LIVE_ARG", "ghost"),
        ("LIVE_LIST_NO_LIVE_ARG", b),
        ("LIVE_LIST_NO_LIVE_ARG", c),
        ("LIVE_LIST_REGISTRY_NOT_LIVE", "ghost"),
        ("LIVE_LIST_REGISTRY_NOT_LIVE", a),
    ]


def test_grandfathered_draft_is_accepted_debt_and_pilot_rows_without_stage_are_live():
    lane = "n8n-pilot-dispatch"
    decl = _decl([_row(lane, expression="078e8fcbea0c5020", stage=None)], [_contract(lane, stage=None, status="DRAFT")],
                 [_allow(lane)], grandfathered=[lane])
    found, _, acc = RT.evaluate(decl, ledger=None, live_lanes=[lane], cron_lines=None, n8n_active=["078e8fcbea0c5020"])
    assert found == [] and acc == [{"code": "LIVE_LIST_CONTRACT_GRANDFATHERED_DRAFT", "lane_id": lane}]


def test_stage_mismatch_both_directions_and_only_for_active_rows():
    decl = _decl([_row("up"), _row("down", stage="shadow"), _row("off", state="PAUSED")],
                 [_contract("up", stage="shadow"), _contract("down", stage="canary"), _contract("off", stage="shadow")])
    found, _, _ = RT.evaluate(decl, ledger=None, live_lanes=None, cron_lines=None, n8n_active=None)
    assert _codes(found) == [("CONTRACT_STAGE_MISMATCH", "down"), ("CONTRACT_STAGE_MISMATCH", "up")]


def test_workflow_inactive_and_cutover_cron_line_rules():
    decl = _decl([
        _row("disp", expression="dispatcher", stage="canary"),
        _row("own", expression="wf-own"),
        _row("cut", expression="dispatcher", stage="cutover"),
    ])
    decl["rows"]["cut"]["scheduler"]["match"] = "scripts/cut.py"
    lines = ["0 6 * * * cd $PROJ && $PY scripts/cut.py >> log", "5 6 * * * bash scripts/effect_claim_cron.sh scripts/cut.py"]
    found, _, _ = RT.evaluate(decl, ledger=None, live_lanes=None, cron_lines=lines, n8n_active=["tradeai-dispatcher"])
    assert _codes(found) == [("ACTIVE_N8N_WORKFLOW_INACTIVE", "own"), ("CUTOVER_CRON_LINE_ACTIVE", "cut")]
    cut = next(c for c in found if c["code"] == "CUTOVER_CRON_LINE_ACTIVE")
    assert cut["evidence"]["lines"] == 1 and "scripts/cut.py >>" not in json.dumps(cut)  # line text never reported


def test_effect_ownership_drift():
    parent = _row("parent", kind="cron", expression="20 11 * * *", stage=None,
                  effect_ownership={"n8n_owned_steps": {"a": "lane-a", "b": "lane-b"},
                                    "cron_owned_steps": {"c": "lane-c (held)"}})
    ledger = {"live_runs": {}, "owners": {"lane-a": {"owner": "n8n"}, "lane-c": {"owner": "n8n"}}}
    found, _, _ = RT.evaluate(_decl([parent]), ledger=ledger, live_lanes=None, cron_lines=None, n8n_active=None)
    assert _codes(found) == [("EFFECT_OWNERSHIP_DRIFT", "parent")]
    assert sorted(c["evidence"]["step_lane"] for c in found) == ["lane-b", "lane-c"]


def test_unreadable_sources_are_not_measured_never_clean():
    found, nm, _ = RT.evaluate(_pre_fix_shape(), ledger=None, live_lanes=None, cron_lines=None, n8n_active=None)
    assert {"DECLARED_OFF_BUT_RUNS_LIVE", "LIVE_LIST_REGISTRY_NOT_LIVE", "ACTIVE_N8N_WORKFLOW_INACTIVE",
            "CUTOVER_CRON_LINE_ACTIVE", "EFFECT_OWNERSHIP_DRIFT"} <= set(nm)
    assert "registry/runtime truth: clean" not in RT.render({"sources": {}, "not_measured": nm, "contradiction_count": 0})


def test_parse_live_lanes_reads_only_its_key():
    text = "\n".join(["SECRET_TOKEN=abc", "# TRADEAI_N8N_RELAY_LIVE_LANES=old", "export TRADEAI_N8N_RELAY_LIVE_LANES='a,b  c'",
                      "TRADEAI_N8N_RELAY_LIVE_LANES_X=z"])
    assert RT.parse_live_lanes(text) == ["a", "b", "c"]


def test_read_live_lanes_never_holds_other_lines(tmp_path):
    p = tmp_path / "live.env"
    p.write_text("OTHER=secretvalue\nTRADEAI_N8N_RELAY_LIVE_LANES=x,y\n", encoding="utf-8")
    st, names, note = RT.read_live_lanes(p)
    assert (st, names) == ("ok", ["x", "y"]) and "secretvalue" not in note
    assert RT.read_live_lanes(tmp_path / "absent.env")[0] == "unavailable"


def test_active_cron_lines_drop_comments_and_assignments():
    text = "PROJ=/x\nSHELL=/bin/bash\n# RETIRED 0 1 * * * a\n\n0 1 * * * run a\n@reboot b\n"
    assert RT.active_cron_lines(text) == ["0 1 * * * run a", "@reboot b"]
    assert RT.read_crontab(lambda: (1, ""))[0] == "unavailable"
    assert RT.read_crontab(lambda: (0, text))[1] == ["0 1 * * * run a", "@reboot b"]


def test_read_ledger_is_read_only_and_windowed(tmp_path):
    db = _ledger(tmp_path / "l.sqlite", runs=[("x", "live", "RUN_DONE", "2026-10-18T10:00:00+00:00"),
                                             ("x", "dry_run", "RUN_DONE", "2026-10-18T10:00:00+00:00"),
                                             ("x", "live", "RUN_FAILED", "2026-10-18T10:00:00+00:00"),
                                             ("old", "live", "RUN_DONE", "2026-09-01T10:00:00+00:00")],
                 owners=[("x", "n8n")])
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    st, ev, _ = RT.read_ledger(db, datetime(2026, 10, 12, tzinfo=timezone.utc))
    assert st == "ok" and ev["live_runs"] == {"x": {"count": 1, "last": "2026-10-18T10:00:00+00:00"}}
    assert ev["owners"]["x"]["owner"] == "n8n"
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before
    assert RT.read_ledger(tmp_path / "absent.sqlite", NOW)[0] == "unavailable"


# ── 3. CLI: dry run, apply, receipt v2, one intent ───────────────────────────────────────────────────────────────


@pytest.fixture()
def env(tmp_path):
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    rows = [_row(PRE_FIX, state="NEVER_SCHEDULED")]
    (root / "config" / "lane_registry.json").write_text(json.dumps({"lanes": rows}), encoding="utf-8")
    (root / "config" / "n8n_health_contracts.json").write_text(
        json.dumps({"contracts": [_contract(PRE_FIX, stage="shadow")]}), encoding="utf-8")
    (root / "config" / "n8n_run_allowlist.json").write_text(json.dumps({"lanes": [_allow(PRE_FIX)]}), encoding="utf-8")
    state = tmp_path / "state"
    ledger = _ledger(tmp_path / "ledger.sqlite", runs=[(PRE_FIX, "live", "RUN_DONE", "2026-10-18T14:50:15+00:00")],
                     owners=[(PRE_FIX, "n8n")])
    live = tmp_path / "live.env"
    live.write_text(f"TRADEAI_N8N_RELAY_LIVE_LANES={PRE_FIX}\n", encoding="utf-8")
    base = ["--root", str(root), "--state-root", str(state), "--ledger", str(ledger), "--live-lanes-env", str(live),
            "--no-crontab", "--no-n8n", "--now", NOW.isoformat()]
    return type("Env", (), {"root": root, "state": state, "ledger": ledger, "base": base})


def _intents(ledger):
    conn = sqlite3.connect(ledger)
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'comms_intents'").fetchone():
            return []
        return conn.execute("SELECT domain, kind, tier, workflow_id, caller_id, count, state FROM comms_intents").fetchall()
    finally:
        conn.close()


def test_dry_run_writes_nothing(env, capsys):
    before = hashlib.sha256(env.ledger.read_bytes()).hexdigest()
    assert RT.main(env.base) == 0
    out = capsys.readouterr().out
    assert "DECLARED_OFF_BUT_RUNS_LIVE" in out and "DRY-RUN " in out
    assert "NOT_MEASURED" in out  # crontab and n8n skipped: named, never clean
    assert not env.state.exists()
    assert hashlib.sha256(env.ledger.read_bytes()).hexdigest() == before
    assert RT.main(env.base + ["--fail-on-contradiction"]) == 1


def test_apply_writes_v2_receipt_the_executor_accepts_and_queues_one_intent(env, monkeypatch, capsys):
    run_id = f"d:{LANE}:live:20261019T0720"
    monkeypatch.setenv("TRADEAI_RUN_ID", run_id)
    monkeypatch.setenv("TRADEAI_RUN_ATTEMPT", "1")
    monkeypatch.setenv("TRADEAI_RUN_MODE", "live")
    assert RT.main(env.base + ["--apply"]) == 0
    last = json.loads(R.receipt_path(LANE, env.state).read_text())
    # no fabric spec in the fixture repo: DECLARED_OFF, EFFECT_OWNER_N8N_NOT_LIVE, LIVE_LIST_REGISTRY_NOT_LIVE
    assert last["ok_at"] and last["summary"]["contradiction_count"] == 3
    assert last["summary"]["alert"]["queued"] is True
    attempt = json.loads(R.attempt_receipt_path(LANE, run_id, env.state).read_text())
    assert attempt["schema"] == "LaneRunReceipt@v2" and attempt["produced_count"] == 1
    assert attempt["skipped_reasons"] == {"not_measured_crontab": 1, "not_measured_n8n_workflows": 1}
    verdict = OV.evaluate(CONTRACTS[LANE]["expected_output"], attempt, run_id=run_id, lane_id=LANE, mode="live")
    assert verdict["verdict"] == "produced", verdict
    rows = _intents(env.ledger)
    assert rows == [("fabric", "registry_runtime_contradiction", "DIGEST", "host.registry_runtime_truth",
                     "host:registry_runtime_truth", 1, "QUEUED")]
    # a rerun within the dedupe window folds into the same intent (one row, count 2), never a second message
    monkeypatch.setenv("TRADEAI_RUN_ID", run_id + "b")
    assert RT.main(env.base + ["--apply"]) == 0
    assert [(r[0], r[5]) for r in _intents(env.ledger)] == [("fabric", 2)]


def test_apply_without_contradictions_queues_nothing(env, monkeypatch):
    reg = env.root / "config" / "lane_registry.json"
    reg.write_text(json.dumps({"lanes": [_row(PRE_FIX)]}), encoding="utf-8")
    (env.root / "config" / "n8n_health_contracts.json").write_text(
        json.dumps({"contracts": [_contract(PRE_FIX)]}), encoding="utf-8")
    monkeypatch.delenv("TRADEAI_RUN_ID", raising=False)
    assert RT.main(env.base + ["--apply"]) == 0
    last = json.loads(R.receipt_path(LANE, env.state).read_text())
    assert last["summary"]["contradiction_count"] == 0 and last["summary"]["alert"]["queued"] is False
    assert _intents(env.ledger) == []


def test_unreadable_ledger_is_fatal_dependency_unavailable(env, monkeypatch, tmp_path):
    base = list(env.base)
    base[base.index("--ledger") + 1] = str(tmp_path / "absent.sqlite")
    assert RT.main(base) == 1
    run_id = f"d:{LANE}:live:x"
    monkeypatch.setenv("TRADEAI_RUN_ID", run_id)
    assert RT.main(base + ["--apply"]) == 1
    attempt = json.loads(R.attempt_receipt_path(LANE, run_id, env.state).read_text())
    assert attempt["produced_count"] == 0 and attempt["skipped_reasons"] == {"dependency_unavailable": 1}
    assert not (tmp_path / "absent.sqlite").exists()  # never creates the ledger


def test_intent_refused_when_ledger_absent_or_route_foreign(tmp_path):
    with pytest.raises(RT.IntentRefused) as e:
        RT.queue_host_intent(producer=RT.PRODUCER, domain="fabric", kind=RT.INTENT_KIND, subject="s", summary="m",
                             execution_id="x", node="", ledger_path=tmp_path / "none.sqlite")
    assert e.value.reason == "ledger_absent"
    with pytest.raises(RT.IntentRefused) as e:
        RT.queue_host_intent(producer="hermes_outcome_feedback_agent", domain="fabric", kind=RT.INTENT_KIND,
                             subject="s", summary="m", execution_id="x", node="", ledger_path=tmp_path / "none.sqlite")
    assert e.value.reason == "producer_refused"


def test_import_closure_never_reaches_the_gateway_or_a_sender():
    tree = ast.parse((ROOT / "scripts" / "check_registry_runtime_truth.py").read_text(encoding="utf-8"))
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
        elif isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
    assert not {m for m in mods if "gateway" in m or "host_comms_intents" in m or "telegram" in m.lower()
                or "notifier" in m or "broker" in m}, mods


# ── 4. the lane ──────────────────────────────────────────────────────────────────────────────────────────────────


def test_lane_row_allowlist_contract_and_route():
    assert RRT.LIVE == (LANE,)
    row, entry, c = REG[LANE], ALLOW[LANE], CONTRACTS[LANE]
    assert row["state"] == "ACTIVE" and row["scheduler"]["kind"] == "n8n"
    assert (row["scheduler"]["expression"], row["scheduler"]["stage"]) == ("dispatcher", "canary")
    assert row["dispatch"]["mode"] == "live" and row["dispatch"]["class"] == "monitor"
    assert row["dispatch"]["cron"] == [row["scheduler"]["cadence"]] and row["expected_cadence_hours"] == 24.0
    assert row["output_signal"] == {"kind": "json_key", "path": f"data/runtime/{LANE}_last.json", "key": "ok_at"}
    assert entry["command"] == ["$PY", "scripts/check_registry_runtime_truth.py"]
    assert entry["dry_run_arg"] == ["--dry-run"] and entry["live_arg"] == ["--apply"]
    assert entry["output_receipt"] == "v2" and entry["env_allowlist_mode"] == "enforce"
    assert entry["lock_kind"] == "flock" and entry["market_gate"] is False
    assert c["status"] == "REVIEWED" and c["stage"] == "canary" and c["workflow_id"] == "dispatcher"
    assert OV.validate_expected_output(c["expected_output"]) == []
    assert (c["alerting"]["failed"]["notifier_priority"], c["alerting"]["degraded"]["notifier_priority"]) == ("P2", "P3")
    assert c["expected_output"]["on_violation"]["notifier_priority"] == "P2"  # never PAGE
    routes = _load("host_comms_intent_routes.json")["routes"]
    mine = [r for r in routes if (r["domain"], r["kind"]) == ("fabric", "registry_runtime_contradiction")]
    assert mine == [{"domain": "fabric", "kind": "registry_runtime_contradiction", "tier": "DIGEST",
                     "runbook_id": "registry-runtime-truth", "producer": "registry_runtime_truth"}]
    n8n_pairs = {(r["domain"], r["kind"]) for r in _load("n8n_comms_intent_routes.json")["routes"]}
    assert ("fabric", "registry_runtime_contradiction") not in n8n_pairs  # n8n can never post it


def test_registry_and_contract_gates_stay_clean():
    assert LR.validate_registry(_load("lane_registry.json")) == []


# ── 5. output-signal exemptions (docs/ops/OUTPUT_SIGNAL_COVERAGE_20261018.md) ────────────────────────────────────

EXEMPT = {
    "openclaw-reminder-claude-plan-1", "openclaw-reminder-claude-plan-2", "openclaw-reminder-supergrok-expiry",
    "openclaw-reminder-sentinelone-earnings", "launchpadlib-cache-clean", "snap-firmware-updater-firmware-notifier",
    "systemd-tmpfiles-clean", "ubuntu-insights-collect", "ubuntu-insights-upload",
}


def test_exemptions_are_explicit_reasoned_and_only_the_reviewed_set():
    exempt = {lid for lid, r in REG.items()
              if (r.get("output_signal") or {}).get("reason") == LR.OUTPUT_SIGNAL_EXEMPT_REASON}
    assert exempt == EXEMPT
    for lid in EXEMPT:
        sig = REG[lid]["output_signal"]
        assert sig["kind"] == "none" and len(sig["detail"]) > 40 and sig["exempt_since"] == "2026-10-19", lid


def test_exemption_without_detail_is_a_registry_error():
    row = {"lane_id": "x", "owner": "o", "state": "ACTIVE", "expected_cadence_hours": 1,
           "scheduler": {"kind": "cron", "expression": "* * * * *"},
           "output_signal": {"kind": "none", "reason": LR.OUTPUT_SIGNAL_EXEMPT_REASON}}
    assert any("exempt" in e for e in LR.validate_row(row))
    row["output_signal"] = {"kind": "file_mtime", "path": "p", "reason": LR.OUTPUT_SIGNAL_EXEMPT_REASON, "detail": "d" * 50}
    assert any("exempt" in e for e in LR.validate_row(row))


def test_coverage_report_lists_every_active_signal_free_lane():
    text = (ROOT / "docs" / "ops" / "OUTPUT_SIGNAL_COVERAGE_20261018.md").read_text(encoding="utf-8")
    none_active = [lid for lid, r in REG.items()
                   if r.get("state") == "ACTIVE" and (r.get("output_signal") or {}).get("kind") == "none"]
    missing = [lid for lid in none_active if f"`{lid}`" not in text]
    assert not missing, missing
