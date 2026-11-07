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


def test_append_keeps_one_effective_outcome_per_commitment():
    from scripts.lib.governed_commitment import durable_outcome_ledger_append as app
    mk = lambda o, k: {"commitment_id": "syn-c1", "outcome": o, "idempotency_key": k}
    led = app([], mk("INSUFFICIENT_EVIDENCE", "k1"))
    assert app(led, mk("INSUFFICIENT_EVIDENCE", "k2")) == led          # same rank, new observation: no second row
    assert app(led, mk("INSUFFICIENT_EVIDENCE", "k1")) == led          # same key: no-op
    led2 = app(led, mk("REFUTED", "k3"))                                # more final: appended, links what it outranks
    assert len(led2) == 2 and led2[-1]["supersedes"] == "k1" and led2[0] == led[0]
    assert app(led2, mk("UNSCOREABLE", "k4")) == led2                   # a scored outcome is never displaced
    assert app(led2, mk("CONFIRMED", "k5")) == led2                     # nor rewritten by an equal-rank one
    assert len(app(led2, {"commitment_id": "syn-c2", "outcome": "EXPIRED", "idempotency_key": "k6"})) == 3


def test_a_stance_word_is_not_a_price_prediction():
    """LQ-20261107-272: the provider's module docstring promised stance-based scoring that
    ``direction_of`` never implemented. A commitment carrying ``author_stance`` and a BUY/SELL word
    but no ``observation_spec`` must not be scored even when both prices exist — the threshold would
    be invented."""
    from scripts.lib.commitment_price_observation import make_price_observation_provider
    c = {"commitment_id": "syn-c1", "author_stance": "BEARISH", "subject_guid": "g-syn",
         "claim": "SELL: synthetic instruments retrace",
         "created_at": "2026-10-01T00:00:00Z", "due_at": "2026-10-08T00:00:00Z"}
    prices = {"2026-10-01": (100.0, "2026-10-01"), "2026-10-08": (90.0, "2026-10-08")}
    prov = make_price_observation_provider(price_lookup=lambda s, d: prices.get(d),
                                           symbol_for_guid=lambda g: "ZZT", now=NOW)
    assert prov(c) == {}

    c["observation_spec"] = {"metric": "close_return_pct", "source": "ticker_prices",
                             "operator": "<", "threshold": -5.0}
    obs = prov(c)
    assert obs["observed"] is True and obs["change_pct"] == -10.0 and obs["confirmed"] is True
