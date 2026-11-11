"""LQ-20261107-1884 — the promotion chain's missing writer and the outcome link.

Fail-before: at base 179b081505eb this module set has no ``lesson_queue_cycle`` and no
``lesson_outcome_linkage``, and ``lesson_promotion.gather`` returns CASE_SUMMARY_CONTEXT
procedures with no link to the plan's settled outcome. The same tests fail at import /
assertion there and pass here.

Synthetic fixture only (PUBLIC repo). No production store, DB or journal is touched.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import lesson_outcome_linkage as lol  # noqa: E402
import lesson_promotion as lp  # noqa: E402
import lesson_queue_cycle as lane  # noqa: E402
import approval_package as ap  # noqa: E402


def _write(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


@pytest.fixture()
def store(tmp_path):
    root = tmp_path / "state"
    cio = root / "data" / "cio"
    (root / "data" / "runtime").mkdir(parents=True)
    _write(cio / "outcome_checkpoints.jsonl", [
        {"checkpoint_id": "c-mrvl", "status": "SCHEDULED", "plan_id": "plan_mrvl",
         "decision_id": "plan_mrvl", "due_at": "2026-11-11T14:16:21+00:00"},
        {"checkpoint_id": "c-mrvl", "status": "RESOLVED", "plan_id": "plan_mrvl",
         "decision_id": "plan_mrvl", "outcome_id": "4a8607cf"},
        {"checkpoint_id": "c-other", "status": "RESOLVED", "plan_id": "plan_other",
         "outcome_id": "out_other"},
    ])
    _write(cio / "lesson_candidates.jsonl", [
        {"schema": "LessonCandidate@v2", "lesson_id": "les_mrvl", "scope": "MRVL",
         "task_class": "CASE_SUMMARY_CONTEXT", "plan_id": "plan_mrvl",
         "statement": "MRVL watch: narrative evidence did not change the standing thesis",
         "supporting_outcome_ids": [], "supporting_case_summary_ids": ["mem_1"],
         "status": "PROVISIONAL", "promotion_stage": "REVIEW_READY", "symbols": []},
        {"schema": "LessonCandidate@v2", "lesson_id": "les_schd_a", "scope": "SCHD",
         "task_class": "TRIM", "statement": "TRIM on SCHD held: the subsequent move averaged -10.0% across 3 observations",
         "supporting_outcome_ids": ["o1", "o2", "o3"], "status": "PROVISIONAL", "symbols": ["SCHD"]},
        {"schema": "LessonCandidate@v2", "lesson_id": "les_schd_b", "scope": "SCHD",
         "task_class": "TRIM", "statement": "TRIM on SCHD held: the subsequent move averaged -10.1% across 3 observations",
         "supporting_outcome_ids": ["o1", "o2", "o3"], "status": "PROVISIONAL", "symbols": ["SCHD"]},
    ])
    obs = []
    for i, day in enumerate(("2026-10-01", "2026-10-05", "2026-10-09"), start=1):
        obs.append({"outcome_id": f"o{i}", "realized_state": {
            "symbol": "SCHD", "recommendation": "TRIM", "decision_price_date": day,
            "horizon_price_date": "2026-10-20", "price_at_decision": 34.0,
            "price_at_horizon": 30.6, "change_pct": -10.0}})
    _write(cio / "outcome_observations.jsonl", obs)
    _write(cio / "lesson_promotions.jsonl", [])
    env = {"TRADEAI_CIO_DIR": str(cio), "TRADEAI_STATE_ROOT": str(root),
           "TRADEAI_GOVERNANCE_DIR": str(root / "data" / "governance")}
    price_on = lambda sym, day: 34.0 if day == "2026-10-01" else (30.6 if day == "2026-10-20" else 34.0)  # noqa: E731
    # every observation carries its own decision date; the same recorded prices stay within tolerance
    price_on = lambda sym, day: 34.0 if day in ("2026-10-01", "2026-10-05", "2026-10-09") else 30.6  # noqa: E731
    daily_vol = lambda sym: 0.02  # noqa: E731
    return {"root": root, "cio": cio, "env": env, "price_on": price_on, "daily_vol": daily_vol}


class FakeCursor:
    def __init__(self, store):
        self.store = store
        self._row = None

    def execute(self, sql, params=None):
        params = params or []
        self._row = None
        s = " ".join(str(sql).split()).upper()
        if s.startswith("SELECT 1 FROM LEARNING_PROMOTION_DECISIONS"):
            self._row = (1,) if any(r[1] == params[1] for r in self.store) else None
        elif s.startswith("INSERT INTO LEARNING_PROMOTION_DECISIONS"):
            self.store.append(list(params))

    def fetchone(self):
        return self._row


class FakeConn:
    def __init__(self):
        self.store = []

    def cursor(self):
        return FakeCursor(self.store)

    def commit(self):
        pass

    def close(self):
        pass


def test_linkage_binds_plan_outcome_as_provenance(store):
    res = lol.apply(store["root"], store["env"], apply=True)
    assert res["links_new"] == 1 and res["written"] == 1, res   # only the MRVL lesson carries plan_id
    assert lol.plan_outcome_index(store["cio"])["plan_mrvl"] == ["4a8607cf"]
    rows = lol.state(store["root"], store["env"])
    assert ("les_mrvl", "4a8607cf") in rows
    # provenance, never evidence: the lesson itself still carries no supporting outcomes
    gathered = {p["source_id"]: p for p in lp.gather(store["root"], store["env"])}
    ev = gathered["les_mrvl"]["evidence"]
    assert ev["linked_outcome_ids"] == ["4a8607cf"]
    assert ev["supporting_outcome_ids"] == []
    assert lp.queue_verdict(gathered["les_mrvl"], lp.outcome_index(store["root"], store["env"]),
                            price_on=store["price_on"], daily_vol=store["daily_vol"])["eligible"] is False


def test_enqueue_coalesces_statement_hashes_and_is_idempotent(store):
    dry = lp.enqueue(store["root"], store["env"], apply=False,
                     price_on=store["price_on"], daily_vol=store["daily_vol"])
    assert dry["new"] == 1, dry                  # les_schd_a/b collapsed to one semantic key
    assert dry["coalesced"] == 1
    assert dry["written"] == 0
    first = lp.enqueue(store["root"], store["env"], apply=True,
                       price_on=store["price_on"], daily_vol=store["daily_vol"])
    assert first["written"] == 1, first
    second = lp.enqueue(store["root"], store["env"], apply=True,
                        price_on=store["price_on"], daily_vol=store["daily_vol"])
    assert second["written"] == 0 and second["skipped_already_queued"] == 1, second
    assert sum(1 for r in lp.state(store["root"], store["env"]).values() if r["status"] == "QUEUED") == 1


def test_cycle_writes_receipt_and_operator_package(store):
    out = lane.run_cycle(store["root"], apply=True, price_on=store["price_on"], daily_vol=store["daily_vol"])
    assert out["ok"] is True, out
    assert out["state"]["queued"] == 1 and out["state"]["promoted"] == 0, out["state"]
    assert out["package"]["created"] is True and out["package"]["items"] == 1
    receipt = json.loads((store["root"] / "data" / "runtime" / "lesson-queue-cycle_last.json").read_text())
    assert receipt["ok"] is True and receipt["ok_at"]
    led = ap.Ledger(ap.ledger_path(store["root"], store["env"]))
    pkg = led.package(out["package"]["package_id"])
    assert pkg["campaign"] == "lesson-promotion"
    assert pkg["items"][0]["state"] == "PENDING"       # the lane never approves its own item


def test_operator_approval_promotes_and_records_db_decision(store):
    out = lane.run_cycle(store["root"], apply=True, price_on=store["price_on"], daily_vol=store["daily_vol"])
    pkg_id = out["package"]["package_id"]
    led = ap.Ledger(ap.ledger_path(store["root"], store["env"]))
    ap.apply_reply(led, ap.parse_reply(f"APPROVE {pkg_id} all"),
                   decided_by={"who": "operator", "from_id": "test", "via": "typed", "text": "APPROVE"})
    conn = FakeConn()
    res = lane.consume_approved(store["root"], store["env"], apply=True, conn_factory=lambda: conn)
    assert res["promoted"] == 1, res
    assert conn.store and conn.store[0][4] == "promote_lesson", conn.store
    assert conn.store[0][5].startswith("operator:operator"), conn.store[0][5]
    st = lp.state(store["root"], store["env"])
    promoted = [r for r in st.values() if r["status"] == "PROMOTED"]
    assert len(promoted) == 1 and promoted[0]["decided_by"].startswith("operator:")
    # idempotent: a second pass promotes nothing and inserts no second decision row
    res2 = lane.consume_approved(store["root"], store["env"], apply=True, conn_factory=lambda: conn)
    assert res2["promoted"] == 0
    assert len(conn.store) == 1


def test_promote_one_requires_the_operator_and_promotes_top(store):
    lp.enqueue(store["root"], store["env"], apply=True,
               price_on=store["price_on"], daily_vol=store["daily_vol"])
    with pytest.raises(PermissionError):
        lane.promote_one(store["root"], store["env"], procedure_id="top", by="agent:cc-deepseek-9",
                         reason="test", authorization="none", apply=True,
                         price_on=store["price_on"], daily_vol=store["daily_vol"], conn_factory=None)
    conn = FakeConn()
    res = lane.promote_one(store["root"], store["env"], procedure_id="top", by="operator:test:typed",
                           reason="single test lesson", authorization="operator 2026-11-11 09:45 ET",
                           apply=True, price_on=store["price_on"], daily_vol=store["daily_vol"],
                           conn_factory=lambda: conn)
    assert res["result"] == "promoted" and res["decision_id"], res
    assert conn.store and conn.store[0][1] is None and conn.store[0][4] == "promote_lesson"
    assert any(r["status"] == "PROMOTED" for r in lp.state(store["root"], store["env"]).values())
    # the reader the façades call now returns the promoted procedure
    assert lp.promoted(store["root"], store["env"], symbol="SCHD")
