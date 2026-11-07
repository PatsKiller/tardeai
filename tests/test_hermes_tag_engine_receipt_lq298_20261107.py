"""LQ-20261107-298: hermes-learning-tag-engine proves what it produced, so the jobs page stops grading it UNPROVEN.

The lane's live runs left no LaneRunReceipt@v2. Its declared ``output_signal`` is ``db_max
hermes_tag_efficacy.updated_at`` — a signal no receipt carries — and its run reported no item count, so
``scripts/lib/run_quality.grade`` had nothing to check and returned ``UNPROVEN output_unverifiable``:

    "Ran live 6 h ago and exited ok, but nothing lets us check what it produced: its output is a database
     column (hermes_tag_efficacy.updated_at) this page does not query; and its receipt reports no item count"

The health contract says the same in its own words (failed check ``output_unverifiable``; expected_output
``min_produced`` 1 on ``produced_count``; evidence note "produced_count emission: NOT YET").

What is pinned here:

* a real ``--apply`` run writes LaneRunReceipt@v2 with ``produced_count`` = the ``hermes_tag_efficacy`` rows it
  upserted — the exact rows whose ``updated_at`` is the declared output signal;
* the executor's own verdict (``n8n_run_executor.apply_output_verdict``) reads that attempt receipt: ``produced``
  when rows were written, ``empty_violation`` when the run wrote none (so a zero can never look like success);
* the jobs page reads the receipt and its count (``run_quality.read_receipt`` + ``item_count``), which is what
  leaves the UNPROVEN branch;
* a dry run writes NO receipt (AGENTS.md §6) and prints ``receipt_preview`` instead;
* a raised apply run still leaves a failed receipt, and the kill switch leaves a ``disabled`` one.

Hermetic: the DB is a recording fake, the research writer is a stub, no network, no model, and
``TRADEAI_STATE_ROOT`` is a tmp dir so nothing touches the live state root.
"""

from __future__ import annotations

import copy
import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import hermes_tag_engine as TE  # noqa: E402
from scripts import n8n_run_executor as X  # noqa: E402
from scripts.lib import lane_last_receipt as LR  # noqa: E402
from scripts.lib import run_quality as RQ  # noqa: E402
from tests.test_hermes_learning_unblock_20261015 import (  # noqa: E402
    TAG_ANSWERS,
    TAG_CFG,
    FakeConn,
)

LANE = "hermes-learning-tag-engine"
ALLOW = {e["lane_id"]: e for e in json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text())["lanes"]}
CONTRACTS = X.parse_expected_outputs((ROOT / "config" / "n8n_health_contracts.json").read_bytes())
#: The allowlist entry AFTER the lead applies the opt-in patch this branch hands over. The code and its tests land
#: together; the shared n8n config is a single-lead write, so it arrives as a patch, not in this commit.
OPTED_IN = {**ALLOW[LANE], "output_receipt": "v2"}


@pytest.fixture
def env(monkeypatch, tmp_path):
    """The lane's real main() over a recording fake DB, inside a fake n8n attempt (tmp state root)."""
    log: list = []
    conns: list = []
    answers = [list(a) for a in TAG_ANSWERS]

    def _conn():
        c = FakeConn(answers, log)
        conns.append(c)
        return c

    gcg = types.ModuleType("lib.governed_cloud_generation")
    gcg.generate_cloud = lambda *a, **k: pytest.fail("model reached")
    monkeypatch.setitem(sys.modules, "lib.governed_cloud_generation", gcg)
    writer = types.ModuleType("lib.writers.hermes_research_writer")
    writer.set_fields_by_id = lambda cur, **k: None
    writer.blend_quality_score = lambda cur, **k: types.SimpleNamespace(rows_written=1)
    monkeypatch.setitem(sys.modules, "lib.writers.hermes_research_writer", writer)
    monkeypatch.setattr(TE, "_conn", _conn)
    monkeypatch.setattr(TE, "_cfg", lambda: copy.deepcopy(TAG_CFG))
    monkeypatch.setattr(TE, "KILL_SWITCH", tmp_path / "HERMES_DISABLED")
    monkeypatch.setattr(TE, "_llm_tags", lambda *a, **k: [])
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv(LR.RUN_ID_ENV, f"d:{LANE}:live:20261107T2155")
    monkeypatch.setenv(LR.RUN_ATTEMPT_ENV, "1")
    monkeypatch.setenv(LR.RUN_MODE_ENV, "live")
    monkeypatch.setenv(LR.CODE_SHA_ENV, "0" * 40)
    return types.SimpleNamespace(log=log, conns=conns, answers=answers, root=tmp_path,
                                 run_id=f"d:{LANE}:live:20261107T2155")


def _run_apply(monkeypatch, capsys, env):
    """Drive the real main() for a live --apply attempt between two executor-side clock reads."""
    lower = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(sys, "argv", ["hermes_tag_engine.py", "--apply"])
    TE.main()
    upper = datetime.now(timezone.utc).isoformat()
    return json.loads(capsys.readouterr().out), lower, upper


def _verdict(env, run_id, lower, upper, entry):
    receipt = {"run_id": run_id, "lane_id": LANE, "mode": "live", "state": "RUN_DONE", "exit": 0,
               "attempt": 1, "code_sha": "0" * 40, "started_at": lower, "finished_at": upper}
    return X.apply_output_verdict(receipt, CONTRACTS, lane_id=LANE, mode="live", state_root=env.root, entry=entry)


def test_apply_writes_the_attempt_receipt_the_executor_reads(env, monkeypatch, capsys):
    out, lower, upper = _run_apply(monkeypatch, capsys, env)
    path = LR.attempt_receipt_path(LANE, env.run_id, env.root)
    assert path.is_file(), "no immutable per-attempt receipt: the executor cannot bind a count to this run"
    doc = json.loads(path.read_text())
    assert doc["schema"] == "LaneRunReceipt@v2" and doc["run_id"] == env.run_id and doc["lane_id"] == LANE
    tags = out["efficacy"]["tags"]
    assert doc["produced_count"] == len(tags) == 1
    assert doc["attempted_count"] == 1 and doc["empty_reason"] is None
    assert doc["output_evidence"][0] == {"kind": "store_rows", "ref": "hermes_tag_efficacy", "upserted": 1}
    # the retag leg is reported beside the count, never folded into it (the contract's unit is efficacy rows)
    assert doc["output_evidence"][1]["ref"] == "hermes_research_intelligence.strategy_tags"
    assert doc["output_evidence"][1]["rows_tagged"] == out["retag"]["batch"] == 4

    verdict = _verdict(env, env.run_id, lower, upper, OPTED_IN)
    assert verdict["state"] == "RUN_DONE", verdict
    assert verdict["output_verdict"]["verdict"] == "produced", verdict
    assert verdict["output_verdict"]["produced_count"] == 1


def test_a_run_that_wrote_no_efficacy_row_is_an_empty_output(env, monkeypatch, capsys):
    """Zero is a verified empty, not a silent success: min_produced must turn it into RUN_FAILED."""
    env.answers[:] = [(needle, [] if "unnest(hri.strategy_tags) tag" in needle else value)
                      for needle, value in env.answers]
    out, lower, upper = _run_apply(monkeypatch, capsys, env)
    assert out["efficacy"]["tags"] == []
    doc = json.loads(LR.attempt_receipt_path(LANE, env.run_id, env.root).read_text())
    assert doc["produced_count"] == 0 and doc["empty_reason"] == "no_tags_to_score"
    verdict = _verdict(env, env.run_id, lower, upper, OPTED_IN)
    assert verdict["state"] == "RUN_FAILED" and verdict["reason"] == "empty_output", verdict
    assert verdict["output_verdict"]["verdict"] == "empty_violation"


def test_the_jobs_page_can_now_count_what_the_run_produced(env, monkeypatch, capsys):
    """The exact call run_quality makes: read the lane's last receipt, then count it. UNPROVEN came from
    (written is None and count is None) — the db_max signal is still unreadable, but the count is not."""
    _run_apply(monkeypatch, capsys, env)
    lane = {"lane_id": LANE, "output_signal": {"kind": "db_max", "table": "hermes_tag_efficacy",
                                               "column": "updated_at"}}
    receipt, rel = RQ.read_receipt(lane, env.root)
    assert rel == f"data/runtime/{LANE}_last.json" and receipt is not None
    count, key = RQ.item_count(receipt)
    assert (count, key) == (1, "produced_count")


def test_a_dry_run_writes_no_receipt_and_previews_the_count(env, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["hermes_tag_engine.py", "--dry-run", "--apply"])  # --dry-run wins
    TE.main()
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "dry_run" and out["apply"] is False
    assert not LR.receipt_path(LANE, env.root).exists()
    assert not (env.root / "data" / "runtime" / "lane_attempts" / LANE).exists()
    assert out["receipt_preview"]["would_write_produced_count"] == len(out["efficacy"]["tags"]) == 1
    assert "writes nothing" in out["receipt_preview"]["note"]


def test_a_raised_apply_run_leaves_a_failed_receipt(env, monkeypatch, capsys):
    def boom():
        raise RuntimeError("db went away")
    monkeypatch.setattr(TE, "_cfg", boom)
    monkeypatch.setattr(sys, "argv", ["hermes_tag_engine.py", "--apply"])
    with pytest.raises(RuntimeError, match="db went away"):
        TE.main()
    doc = json.loads(LR.attempt_receipt_path(LANE, env.run_id, env.root).read_text())
    assert doc["status"] == "failed" and doc["produced_count"] == 0
    assert doc["skipped_reasons"] == {"dependency_unavailable": 1}


def test_the_kill_switch_receipt_says_disabled(env, monkeypatch, capsys):
    TE.KILL_SWITCH.write_text("")
    monkeypatch.setattr(sys, "argv", ["hermes_tag_engine.py", "--apply"])
    TE.main()
    doc = json.loads(LR.attempt_receipt_path(LANE, env.run_id, env.root).read_text())
    assert doc["status"] == "failed" and doc["produced_count"] == 0
    assert doc["skipped_reasons"] == {"disabled": 1} and doc["error"] == "HERMES_DISABLED"


def test_the_count_is_efficacy_rows_not_the_retag_batch():
    """Pure: a run that retagged 400 rows but upserted no efficacy row has not advanced the declared signal."""
    out = TE.lane_output({"retag": {"batch": 400}, "quality": {"rows_updated": 7},
                          "efficacy": {"tags": [{"tag": "a"}, {"tag": "b"}]}})
    assert out["produced_count"] == 2 and out["attempted_count"] == 2
    assert [e["ref"] for e in out["output_evidence"]] == [
        "hermes_tag_efficacy", "hermes_research_intelligence.strategy_tags",
        "hermes_research_intelligence.quality_score"]
    empty = TE.lane_output({"retag": {"batch": 400}, "efficacy": {"tags": []}})
    assert empty["produced_count"] == 0 and empty["empty_reason"] == "no_tags_to_score"
