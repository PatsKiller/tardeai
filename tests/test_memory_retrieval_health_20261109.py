"""LQ-20261107-1614 — the memory SHADOW contracts: ladder step 7 can hit, the adjudicator can confirm a
contradiction, and the retrieval counterfactual is measured, never enforced.

ANCHOR: MEMORY_RETRIEVAL_HEALTH_20261109

Synthetic rows only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import memory_retrieval_health as mrh  # noqa: E402


def _rcpt(i, cause="flag_off", hit=False, note=None, **kw):
    step7 = {"step": 7, "store": "intelligence.embedding", "hit": hit, "refs": ["e1"] if hit else [],
             "note": note or ("hit" if hit else "not_installed")}
    if cause is not None:
        step7["cause"] = cause
    return {"receipt_id": f"rc{i}", "decision": kw.get("decision", "HIT_PARTIAL"),
            "ladder": kw.get("ladder", []) + [step7], "reused_refs": kw.get("reused", [])}


def test_embedding_never_ran_is_broken_and_legacy_rows_count_as_not_run():
    assert mrh.embedding_contract([_rcpt(i) for i in range(60)])["verdict"] == "BROKEN"
    # receipts written before the cause field existed: note only
    legacy = mrh.embedding_contract([_rcpt(i, cause=None) for i in range(60)])
    assert (legacy["verdict"], legacy["reason"]) == ("BROKEN", "step7_never_ran")
    err = mrh.embedding_contract([_rcpt(i, cause="error:OperationalError") for i in range(60)])
    assert err["reason"] == "step7_errors"


def test_embedding_ran_without_hits_is_degraded_and_one_hit_is_ok():
    miss = [_rcpt(i, cause="miss", note="miss") for i in range(60)]
    assert mrh.embedding_contract(miss)["verdict"] == "DEGRADED"
    assert mrh.embedding_contract(miss + [_rcpt(99, cause="hit", hit=True)])["verdict"] == "OK"
    assert mrh.embedding_contract(miss[:10])["verdict"] == "UNVERIFIABLE"


def _res(rid, ts, cls, stance="WATCH", receipt=None, sym="ZZA"):
    return {"result_id": rid, "completed_ts": ts, "classification": cls, "thesis_stance": stance, "symbol": sym,
            "retrieval_receipt_id": receipt}


def test_counterfactual_compares_against_the_newest_earlier_artifact_the_ladder_reached():
    results = [_res("h0", "2026-01-01", "CONFIRMS"), _res("h1", "2026-01-02", "WEAKENS"),
               _res("n1", "2026-01-03", "WEAKENS", receipt="r1"),       # same as newest prior h1
               _res("n2", "2026-01-04", "STRENGTHENS", receipt="r2"),   # changed vs h1, directional
               _res("n3", "2026-01-05", "NO_NEW_INFO", receipt="r3"),   # no prior reached
               _res("n4", "2026-01-06", "CONFIRMS", receipt="missing")]
    receipts = {"r1": {"decision": "HIT_FRESH", "reused_refs": ["h0", "h1"], "ladder": []},
                "r2": {"decision": "HIT_PARTIAL", "ladder": [{"step": 3, "refs": ["h1", "n9"]}]},
                "r3": {"decision": "MISS", "ladder": []}}
    cf = mrh.counterfactual(results, receipts)
    assert (cf["same_conclusion"], cf["changed_conclusion"], cf["no_prior_artifact"]) == (1, 1, 1)
    assert cf["same_share"] == 0.5 and cf["directional_changes"] == 1
    assert cf["by_decision"] == {"HIT_FRESH": {"same_conclusion": 1}, "HIT_PARTIAL": {"changed_conclusion": 1}}
    case = cf["_cases"][0]
    assert (case["memory_dir"], case["new_dir"], case["date"]) == (-1, 1, "2026-01-04")


def test_a_later_artifact_is_never_the_memory_answer():
    results = [_res("n1", "2026-01-01", "WEAKENS", receipt="r1"), _res("h9", "2026-02-01", "CONFIRMS")]
    cf = mrh.counterfactual(results, {"r1": {"decision": "HIT_FRESH", "reused_refs": ["h9"], "ladder": []}})
    assert cf["no_prior_artifact"] == 1 and cf["compared"] == 0 and cf["same_share"] is None


def test_score_cases_uses_the_forward_return_and_a_dead_band():
    cases = [{"symbol": s, "date": "d", "memory_dir": m, "new_dir": n} for s, m, n in
             (("UP", -1, 1), ("DOWN", -1, 1), ("FLAT", -1, 1), ("NONE", -1, 1), ("SIDE", 0, 1))]
    series = {"UP": [100, 1, 1, 1, 1, 105], "DOWN": [100, 1, 1, 1, 1, 95], "FLAT": [100, 1, 1, 1, 1, 100.5],
              "NONE": [100, 101], "SIDE": [100, 1, 1, 1, 1, 90]}
    out = mrh.score_cases(cases, lambda sym, d, n: series[sym][:n])
    assert out == {"new_right": 1, "memory_right": 1, "flat": 1, "no_forward_bars": 1, "neither": 1}


def _state(tmp_path, receipts):
    cio = tmp_path / "data" / "cio"
    cio.mkdir(parents=True)
    (cio / "retrieval_receipts.jsonl").write_text("".join(json.dumps(r) + "\n" for r in receipts))
    return tmp_path


def test_dry_run_reads_only_and_never_escalates(tmp_path, monkeypatch):
    root = _state(tmp_path, [_rcpt(i) for i in range(60)])
    monkeypatch.setattr(mrh, "_connect", lambda read_only: pytest.fail("dry run without --prices opens no DB"))
    out = mrh.run(root=root, apply=False, escalate=lambda *a: pytest.fail("dry run escalated"))
    assert out["verdict"] == "BROKEN" and out["contracts"]["embedding_step"]["verdict"] == "BROKEN"
    assert out["contracts"]["adjudicator"]["verdict"] == "UNVERIFIABLE"
    assert out["escalated"] == [] and out["sends"] == 0 and out["memory_behavior_influence"] == 0
    assert sorted(p.name for p in (root / "data" / "cio").iterdir()) == ["retrieval_receipts.jsonl"]


class _Cur:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=()):
        self.conn.queries.append(params)

    def fetchone(self):
        return (1,) if self.conn.recent else None


class _Conn:
    def __init__(self, recent=False):
        self.recent, self.queries, self.commits = recent, [], 0

    def cursor(self):
        return _Cur(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def test_apply_escalates_a_broken_contract_once_per_cooldown(tmp_path):
    root = _state(tmp_path, [_rcpt(i) for i in range(60)])
    sent = []
    out = mrh.run(root=root, apply=True, conn=_Conn(), escalate=lambda name, res: sent.append(name) or True)
    assert out["escalated"] == ["embedding_step"] and sent == ["embedding_step"] and out["sends"] == 0
    again = mrh.run(root=root, apply=True, conn=_Conn(recent=True), escalate=lambda *a: pytest.fail("cooldown"))
    assert again["escalated"] == [] and again["escalation_suppressed_cooldown"] == ["embedding_step"]
