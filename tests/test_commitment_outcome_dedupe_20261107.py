"""ANCHOR: COMMITMENT_OUTCOME_DEDUPE_20261107 — LQ-20261107-54: one effective outcome per commitment."""
import json
from datetime import datetime, timezone

from scripts import commitment_outcome_ledger_plan as cli
from scripts.lib.commitment_outcome_sweep import effective_outcomes, outcome_summary, plan_ledger_cleanup

NOW = datetime(2026, 11, 7, tzinfo=timezone.utc)


def _o(cid, outcome, key):
    return {"commitment_id": cid, "outcome": outcome, "idempotency_key": key}


LEDGER = [_o("a", "INSUFFICIENT_EVIDENCE", "a1"), _o("a", "UNSCOREABLE", "a2"),
          _o("b", "EXPIRED", "b1"), _o("c", "UNSCOREABLE", "c1"), _o("c", "CONFIRMED", "c2")]
COMMITS = [{"commitment_id": k, "due_at": "2026-10-01T00:00:00Z"} for k in "abcd"]


def test_one_effective_outcome_with_precedence():
    eff = effective_outcomes(LEDGER)
    assert {k: v["outcome"] for k, v in eff.items()} == {"a": "UNSCOREABLE", "b": "EXPIRED", "c": "CONFIRMED"}


def test_summary_counts_rows_effective_and_scored():
    s = outcome_summary(COMMITS, LEDGER, now=NOW)
    assert (s["ledger_rows"], s["effective_outcomes"], s["commitments_with_duplicate_outcomes"]) == (5, 3, 2)
    assert s["scored"] == 1 and s["due_without_outcome"] == 1  # d has none


def test_cleanup_is_a_plan_only_and_names_superseded_rows():
    before = json.dumps(LEDGER)
    plan = plan_ledger_cleanup(LEDGER)
    assert json.dumps(LEDGER) == before and plan["dry_run"] and plan["writes"] == 0
    assert plan["superseded"] == 2 and plan["superseded_by_pair"] == {"INSUFFICIENT_EVIDENCE->UNSCOREABLE": 1, "UNSCOREABLE->CONFIRMED": 1}


def test_cli_never_writes(tmp_path, capsys):
    (tmp_path / "commitments.jsonl").write_text("\n".join(json.dumps(c) for c in COMMITS) + "\n")
    p = tmp_path / "commitment_outcomes.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in LEDGER) + "\n")
    before = p.read_bytes()
    assert cli.main(["--state-root", str(tmp_path)]) == 0
    assert p.read_bytes() == before and json.loads(capsys.readouterr().out)["cleanup_plan"]["superseded"] == 2
    assert sorted(x.name for x in tmp_path.iterdir()) == ["commitment_outcomes.jsonl", "commitments.jsonl"]
