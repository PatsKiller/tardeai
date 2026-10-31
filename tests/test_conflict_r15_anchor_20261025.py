"""R15 hysteresis decision anchor (EXCEPTIONS_MATRIX.md R15, gap (d) 2026-10-25).

"A resolution holds until a side changes ACTION or conviction moves +/-5; a new flag needs 2 consecutive runs."
The anchor (each side's action as an ordinal, the chosen side, holding state, conviction) is recorded on the
ConflictDecision@v1 at decision time; later runs compare against it. Matrix test: conviction 70+/-1 over 3 runs ->
one flag.
"""
from datetime import datetime, timedelta, timezone

from scripts.lib.conflicts.adapters import evaluate_inputs, security_inputs
from scripts.lib.conflicts.engine import Input
from scripts.lib.conflicts.hysteresis import SCHEMA, anchor_holds, record_anchor
from scripts.lib.conflicts.ledger import KINDS, ConflictLedger, DECISION_SCHEMA, decision_inputs
from scripts.lib.conflicts.profiles.vocabulary import ordinal

NOW = datetime(2026, 10, 22, 17, tzinfo=timezone.utc)       # Thursday, session open


def bundle(*, conviction=70, cio="WATCH", desk="BUY", held=False, extra=(), now=NOW):
    b = security_inputs(security_guid="g1", symbol="SYM", held=held,
                        canonical={"source": "CIO record", "stance": cio, "as_of": (now - timedelta(hours=1)).isoformat()},
                        card={"decision": {"inputs": {"synthesis": desk,
                                                      "synthesis_at": (now - timedelta(hours=2)).isoformat()}}},
                        extras=list(extra))
    b.subject.context["conviction"] = conviction
    return b


class Runner:
    """The resolver loop (scripts/conflict_resolver.py): decisions in, observations kept, ledger reconciled."""

    def __init__(self, root):
        self.root, self.history = root, []
        self.ledger = ConflictLedger(root, memory_writer=lambda event: True)

    def run(self, b, now):
        b.inputs.extend(decision_inputs(self.root, b.subject, now=now))
        findings = evaluate_inputs(b, now=now, history=list(self.history))
        held = b.subject.context.get("held")
        observed = False
        for f in findings:
            if f.rule in {"R15", "U7", "R11"}:
                self.history.append({"key": f.key, "observed_at": now.isoformat(),
                                     "signature": sorted([s["source"], ordinal(s["value"], held)] for s in f.sides)})
                observed = True
        if not observed:
            self.history.append({"key": f"security:{b.subject.id}:reset", "signature": []})
        events = self.ledger.reconcile(b.subject, findings, at=now, observed_sources=[i.source for i in b.inputs],
                                       apply=True)
        return findings, events

    def decide(self, key, chosen, now, actor="cio"):
        return self.ledger.transition(key, "decided", at=now, apply=True, decision={
            "schema": DECISION_SCHEMA, "actor_kind": actor, "actor": actor, "chosen_side": chosen,
            "reason": "evidence reviewed", "evidence_refs": ["fixture:review"],
            "expires_at": (now + timedelta(days=30)).isoformat()})


def flags(findings):
    return [(f.kind, f.rule) for f in findings if f.kind in KINDS]


def confirmed_conflict(runner, make, start=NOW):
    first, _ = runner.run(make(), start)
    assert [(f.kind, f.rule) for f in first if f.rule == "R15"] == [("AGREEMENT", "R15")]
    second, _ = runner.run(make(), start + timedelta(minutes=15))
    conflict = [f for f in second if f.kind == "CONFLICT"]
    assert len(conflict) == 1, flags(second)
    return conflict[0]


def test_decision_records_each_side_action_and_conviction(tmp_path):
    runner = Runner(tmp_path)
    conflict = confirmed_conflict(runner, bundle)
    event = runner.decide(conflict.key, "WATCH", NOW + timedelta(minutes=20))
    anchor = event["decision"]["anchor"]
    assert anchor["schema"] == SCHEMA and anchor["held"] is False and anchor["conviction"] == 70
    assert anchor["sides"] == {"CIO record": 1, "watchlist_final_synthesis": 0}
    assert anchor["chosen"] == ["CIO decision", 1]
    # The durable record carries it, and the decision input hands it to the next run.
    assert runner.ledger.records()[conflict.key]["decision"]["anchor"] == anchor
    (item,) = decision_inputs(tmp_path, bundle().subject, now=NOW + timedelta(hours=1))
    assert item.metadata["anchor"] == anchor


def test_conviction_70_plus_minus_1_over_three_runs_is_one_flag(tmp_path):
    runner = Runner(tmp_path)
    conflict = confirmed_conflict(runner, bundle)
    runner.decide(conflict.key, "WATCH", NOW + timedelta(minutes=20))
    later = []
    for n, conviction in enumerate((71, 69, 70), start=1):
        findings, events = runner.run(bundle(conviction=conviction), NOW + timedelta(minutes=30 * n))
        later.append(findings)
        assert flags(findings) == [], (conviction, flags(findings))
        assert [f.summary for f in findings if f.rule == "R15"] == ["Recorded resolution still holds"]
        assert not [e for e in events if e["event"] in {"opened", "reopened"}]
    opened = [e for e in runner.ledger.events() if e["event"] in {"opened", "reopened"} and e["finding"]["kind"] in KINDS]
    assert len(opened) == 1                                          # the one flag the CIO decided
    assert runner.ledger.records()[conflict.key]["state"] == "DECIDED"


def test_conviction_move_of_five_ends_the_hold(tmp_path):
    runner = Runner(tmp_path)
    conflict = confirmed_conflict(runner, bundle)
    runner.decide(conflict.key, "WATCH", NOW + timedelta(minutes=20))
    moved, _ = runner.run(bundle(conviction=75), NOW + timedelta(minutes=30))
    # The decision is now one side of a three-way split that includes a recorded CIO side: never automatic
    # (matrix "Never auto-resolved": >=3-way splits including an operator/CIO side).
    assert flags(moved) == [("NEEDS_OPERATOR", "R11")]
    assert not [f for f in moved if f.summary == "Recorded resolution still holds"]
    # 4.9 points is noise.
    runner2 = Runner(tmp_path / "noise")
    conflict2 = confirmed_conflict(runner2, bundle)
    runner2.decide(conflict2.key, "WATCH", NOW + timedelta(minutes=20))
    noise, _ = runner2.run(bundle(conviction=74.9), NOW + timedelta(minutes=30))
    assert flags(noise) == [] and [f.summary for f in noise if f.rule == "R15"] == ["Recorded resolution still holds"]


def test_a_side_changing_action_ends_the_hold(tmp_path):
    runner = Runner(tmp_path)

    def held(cio="HOLD", conviction=70, extra=()):
        return bundle(cio=cio, desk="EXIT", held=True, conviction=conviction, extra=extra)
    conflict = confirmed_conflict(runner, held)
    assert conflict.rule == "U7"
    runner.decide(conflict.key, "HOLD", NOW + timedelta(minutes=20))
    kept, _ = runner.run(held(), NOW + timedelta(minutes=30))
    assert flags(kept) == []
    # The curator moves HOLD -> ADD: an anchored side changed ACTION, so the resolution no longer holds.
    moved, _ = runner.run(held(cio="ADD"), NOW + timedelta(minutes=45))
    assert [f.summary for f in moved if f.rule == "R15"] != ["Recorded resolution still holds"]
    # A new side that disagrees with the decision also ends the hold (it becomes an N-way split).
    runner3 = Runner(tmp_path / "new-side")
    conflict3 = confirmed_conflict(runner3, held)
    runner3.decide(conflict3.key, "HOLD", NOW + timedelta(minutes=20))
    desk = Input("advisory_desk", "SELL", NOW - timedelta(hours=1))
    split, _ = runner3.run(held(extra=[desk]), NOW + timedelta(minutes=30))
    assert [f.summary for f in split if f.rule == "R15"] != ["Recorded resolution still holds"]


def test_anchor_holds_rules():
    record = {"subject": {"context": {"held": True, "conviction": 60}},
              "sides": [{"source": "CIO record", "value": "HOLD"}, {"source": "desk", "value": "EXIT"}]}
    anchor = record_anchor(record, {"actor_kind": "operator", "chosen_side": "HOLD"})
    assert anchor["chosen"] == ["operator decision", 1] and anchor["conviction"] == 60
    assert anchor["conviction_source"] == "ledger subject context"
    assert record_anchor(record, {"actor_kind": "cio", "chosen_side": "HOLD"}, conviction=64)["conviction"] == 64
    same = [{"source": "operator decision", "value": "HOLD"}, {"source": "CIO record", "value": "HOLD"},
            {"source": "desk", "value": "EXIT"}]
    assert anchor_holds(anchor, same, True)
    assert not anchor_holds(anchor, same, False)                                  # position changed
    assert anchor_holds(anchor, same + [{"source": "review", "value": "KEEP"}], True)   # new side agrees
    assert not anchor_holds(anchor, same + [{"source": "review", "value": "SELL"}], True)
    assert not anchor_holds(anchor, [{"source": "desk", "value": "ADD"}], True)
    assert not anchor_holds({"sides": {}}, same, True)                          # not an anchor


def test_expired_decision_has_no_anchor(tmp_path):
    runner = Runner(tmp_path)
    conflict = confirmed_conflict(runner, bundle)
    runner.ledger.transition(conflict.key, "decided", at=NOW + timedelta(minutes=20), apply=True, decision={
        "schema": DECISION_SCHEMA, "actor_kind": "cio", "actor": "cio", "chosen_side": "WATCH",
        "reason": "evidence reviewed", "evidence_refs": ["fixture"],
        "expires_at": (NOW + timedelta(hours=1)).isoformat()})
    after, _ = runner.run(bundle(), NOW + timedelta(hours=2))
    assert [f.summary for f in after if f.rule == "R15"] != ["Recorded resolution still holds"]
