"""A commitment's window closes at created_at + horizon, never earlier.

Measured on the live store 2026-10-09:

    governed commitments                                         884
    template rows (claim_not_falsifiable), re-evaluated nightly  883
    judged rows                                                    1  (XLB, 14d)
    rows whose due_at - created_at == 7d                         884  (incl. the 14d XLB)
    rows carrying an observation_spec                              0

`cortex_shadow_pipeline` set due_at = now + 7d whatever the horizon, so the 14d
XLB claim (gcmt_c300f64e4756a9b68285d474) was due on 2026-10-10 and the 18:20
sweep would have settled it EXPIRED -- terminal -- at half-time with no
evidence. And the 883 template rows were re-scored INSUFFICIENT_EVIDENCE (not
terminal) every night forever, with `unfalsifiable` counted before dedupe.

Hermetic: every store is tmp_path; prices are injected lambdas.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from scripts.lib.commitment_outcome_sweep import sweep_due_commitments
from scripts.lib.commitment_price_observation import make_price_observation_provider
from scripts.lib.cortex_shadow_pipeline import CORTEX_SHADOW_FLAG, run_cortex_shadow
from scripts.lib.governed_commitment import (
    FEATURE_FLAG as COMMITMENT_FLAG,
    CommitmentError,
    build_governed_commitment,
    horizon_delta,
)

CREATED = datetime(2026, 10, 3, 15, 1, 39, tzinfo=timezone.utc)
XLB_ID = "gcmt_c300f64e4756a9b68285d474"
FALSIFIER = (
    "A confirmed close back above the 53.36 basis with the moving-average stack "
    "flattening or turning positive and RSI recovering above 50 would falsify the impairment claim."
)
TEMPLATE_CLAIM = (
    "Scheduled persistent wake reviewed subject 4b54769d-c407-5732-81c3-cf67575dd759; "
    "advisory observation only."
)
SPEC = {"metric": "close_return_pct", "source": "ticker_prices", "operator": "<", "threshold": 0.0}


def _xlb(**patch):
    """Shaped like the live row: horizon 14d, due_at minted at created + 7d."""
    row = {
        "schema_version": "GovernedCommitment@v1",
        "commitment_id": XLB_ID,
        "subject_guid": "ae38aa9e-5cee-5fbe-8117-83121c3bb8ee",
        "claim": "The standing XLB thesis is technically impaired rather than merely lagging.",
        "confidence": 0.62,
        "horizon": "14d",
        "due_at": (CREATED + timedelta(days=7)).isoformat().replace("+00:00", "Z"),
        "falsifier": FALSIFIER,
        "evidence_refs": ["wake:8a9450d1-82f4-5305-b8a6-9ac169eae130"],
        "source_identity": "cortex_shadow_pipeline",
        "source_sha": "8eb65152d",
        "served_sha": "8eb65152d",
        "trigger_provenance": {"producer": "cortex_shadow_pipeline", "trigger": "agent_view_v1"},
        "created_at": CREATED.isoformat().replace("+00:00", "Z"),
        "frozen_at": CREATED.isoformat().replace("+00:00", "Z"),
        "lifecycle_state": "FROZEN",
        "author_stance": "DISPUTE",
    }
    row.update(patch)
    return row


def _template(cid="gcmt_template01"):
    return _xlb(commitment_id=cid, horizon="7d", claim=TEMPLATE_CLAIM,
                falsifier="observation contradicts claim within horizon")


# --------------------------------------------------------------------------
# horizon grammar
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("14d", timedelta(days=14)), ("7d", timedelta(days=7)), ("2 weeks", timedelta(days=14)),
    ("36h", timedelta(hours=36)), ("P3D", timedelta(days=3)), ("PT12H", timedelta(hours=12)),
])
def test_horizon_delta_parses_explicit_durations(text, expected):
    assert horizon_delta(text) == expected


@pytest.mark.parametrize("text", ["", None, "0d", "5_sessions", "event-relative", "soon"])
def test_horizon_delta_refuses_ambiguous_horizons(text):
    assert horizon_delta(text) is None


# --------------------------------------------------------------------------
# sweep: the horizon guard (what saves XLB)
# --------------------------------------------------------------------------

def test_xlb_shaped_commitment_does_not_expire_at_day_seven():
    c = _xlb()
    before = dict(c)
    for day in (7, 8, 13):
        res = sweep_due_commitments([c], now=CREATED + timedelta(days=day, hours=7))
        assert res.due == 0, day
        assert res.horizon_guarded == 1, day
        assert res.outcomes == [], day
    assert c == before  # the frozen row is never rewritten


def test_xlb_shaped_commitment_settles_only_after_its_full_horizon():
    c = _xlb()
    res = sweep_due_commitments([c], now=CREATED + timedelta(days=14, hours=7))
    assert res.due == 1 and res.horizon_guarded == 0
    assert res.by_outcome == {"EXPIRED": 1}  # no observation provider: closed unobserved
    assert c["due_at"] == (CREATED + timedelta(days=7)).isoformat().replace("+00:00", "Z")


def test_provider_observes_at_the_horizon_close_not_the_minted_due_date():
    c = _xlb(observation_spec=SPEC)
    asked: list[str] = []

    def lookup(symbol, on_or_before):
        asked.append(on_or_before)
        return (50.0, on_or_before) if on_or_before > "2026-10-03" else (53.22, on_or_before)

    now = CREATED + timedelta(days=14, hours=7)
    provider = make_price_observation_provider(price_lookup=lookup, symbol_for_guid=lambda _g: "XLB", now=now)
    res = sweep_due_commitments([c], observation_provider=provider, now=now)
    assert asked == ["2026-10-03", "2026-10-17"]  # not 2026-10-10
    assert res.by_outcome == {"CONFIRMED": 1}


def test_a_commitment_whose_due_at_already_covers_the_horizon_is_unchanged():
    c = _xlb(horizon="7d")
    res = sweep_due_commitments([c], now=CREATED + timedelta(days=7, hours=1))
    assert res.due == 1 and res.horizon_guarded == 0
    assert res.by_outcome == {"EXPIRED": 1}


def test_an_unparseable_horizon_falls_back_to_the_minted_due_date():
    c = _xlb(horizon="5_sessions")
    res = sweep_due_commitments([c], now=CREATED + timedelta(days=7, hours=1))
    assert res.due == 1


# --------------------------------------------------------------------------
# sweep: terminal UNSCOREABLE, counter after dedupe
# --------------------------------------------------------------------------

def test_unfalsifiable_template_settles_unscoreable_once_then_is_never_revisited():
    now = CREATED + timedelta(days=8)
    first = sweep_due_commitments([_template()], now=now)
    assert first.by_outcome == {"UNSCOREABLE": 1}
    assert first.unfalsifiable == 1 and first.unscoreable == 1 and first.scored == 0
    assert first.lessons == []
    assert first.outcomes[0]["errors"] == ["claim_not_falsifiable:claim_asserts_only_that_a_review_occurred"]

    second = sweep_due_commitments([_template()], ledger=first.ledger, now=now + timedelta(days=1))
    assert second.outcomes == []
    assert second.already_settled == 1
    assert second.unfalsifiable == 0  # counted after dedupe, not every night


def test_legacy_insufficient_evidence_rows_are_preserved_and_closed_once():
    legacy = {
        "schema_version": "GovernedCommitmentOutcome@v1",
        "commitment_id": "gcmt_template01",
        "outcome": "INSUFFICIENT_EVIDENCE",
        "errors": ["claim_not_falsifiable:claim_asserts_only_that_a_review_occurred"],
        "idempotency_key": "cec2646c75d2077eb69c404f7f9c20c9",
    }
    ledger = [dict(legacy)]
    res = sweep_due_commitments([_template()], ledger=ledger, now=CREATED + timedelta(days=8))
    assert res.by_outcome == {"UNSCOREABLE": 1}
    assert res.ledger[0] == legacy  # append-only: the old row is untouched
    assert len(res.ledger) == 2
    again = sweep_due_commitments([_template()], ledger=res.ledger, now=CREATED + timedelta(days=9))
    assert again.outcomes == [] and again.already_settled == 1


def test_mint_marked_unscoreable_settles_unscoreable_at_its_horizon_not_expired():
    c = _xlb(scoreability={"state": "UNSCOREABLE", "reason": "no_observation_spec"})
    early = sweep_due_commitments([c], now=CREATED + timedelta(days=8))
    assert early.outcomes == [] and early.horizon_guarded == 1
    res = sweep_due_commitments([c], now=CREATED + timedelta(days=14, hours=1))
    assert res.by_outcome == {"UNSCOREABLE": 1}
    assert res.outcomes[0]["errors"] == ["unscoreable_at_mint:no_observation_spec"]
    assert res.unfalsifiable == 0 and res.scored == 0 and res.lessons == []


# --------------------------------------------------------------------------
# producer
# --------------------------------------------------------------------------

def _shadow(tmp_path, monkeypatch, **kw):
    monkeypatch.setenv(CORTEX_SHADOW_FLAG, "1")
    monkeypatch.setenv(COMMITMENT_FLAG, "1")
    args = dict(subject="ae38aa9e-5cee-5fbe-8117-83121c3bb8ee",
                summary="The XLB thesis is technically impaired rather than merely lagging.",
                citations=["wake:abc"], confidence=0.62, state_root=tmp_path,
                source_sha_value="sha-test", falsifier=FALSIFIER, dry_run=False)
    args.update(kw)
    return run_cortex_shadow(**args)


def _rows(tmp_path):
    p = tmp_path / "commitments.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def _span(row):
    parse = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))  # noqa: E731
    return parse(row["due_at"]) - parse(row["created_at"])


def test_producer_derives_due_from_a_14d_horizon(tmp_path, monkeypatch):
    r = _shadow(tmp_path, monkeypatch, horizon="14d")
    assert r.ok and r.commitment is not None
    (row,) = _rows(tmp_path)
    assert _span(row) == timedelta(days=14)


def test_producer_refuses_to_mint_without_an_explicit_horizon(tmp_path, monkeypatch):
    for horizon in ("", "5_sessions"):
        r = _shadow(tmp_path, monkeypatch, horizon=horizon)
        assert r.ok and r.outcome == "observation_only"
        assert r.reason == "horizon_not_an_explicit_duration"
        assert r.commitment is None
    assert _rows(tmp_path) == []


def test_producer_refuses_an_explicit_due_before_the_horizon_closes(tmp_path, monkeypatch):
    early = datetime.now(timezone.utc) + timedelta(days=7)
    r = _shadow(tmp_path, monkeypatch, horizon="14d", due_at=early)
    assert not r.ok and r.outcome == "commitment_refused"
    assert "due_before_horizon_close" in (r.reason or "")
    assert _rows(tmp_path) == []


def test_producer_without_observation_spec_marks_unscoreable_at_mint(tmp_path, monkeypatch):
    _shadow(tmp_path, monkeypatch, horizon="14d")
    (row,) = _rows(tmp_path)
    assert row["scoreability"] == {"state": "UNSCOREABLE", "reason": "no_observation_spec"}
    assert "observation_spec" not in row


def test_producer_with_a_scoreable_spec_persists_it(tmp_path, monkeypatch):
    _shadow(tmp_path, monkeypatch, horizon="14d", observation_spec=SPEC)
    (row,) = _rows(tmp_path)
    assert row["observation_spec"] == SPEC
    assert "scoreability" not in row


def test_producer_with_an_unscoreable_spec_marks_it(tmp_path, monkeypatch):
    _shadow(tmp_path, monkeypatch, horizon="14d", observation_spec={"metric": "vibes"})
    (row,) = _rows(tmp_path)
    assert row["scoreability"] == {"state": "UNSCOREABLE", "reason": "observation_spec_not_scoreable"}
    assert "observation_spec" not in row


# --------------------------------------------------------------------------
# contract + CLI
# --------------------------------------------------------------------------

def _build(**kw):
    args = dict(claim="XLB closes below its basis at the horizon.", confidence=0.6, horizon="14d",
                due_at=CREATED + timedelta(days=14), falsifier="XLB closes above 53.36 at the horizon.",
                evidence_refs=["wake:abc"], source_identity="t", source_sha="a", served_sha="a",
                subject_guid="g", trigger_provenance={"producer": "cortex_shadow_pipeline"},
                created_at=CREATED, frozen_at=CREATED)
    args.update(kw)
    return build_governed_commitment(**args)


def test_contract_refuses_a_due_date_inside_the_horizon():
    assert _build()["horizon"] == "14d"
    with pytest.raises(CommitmentError, match="due_before_horizon_close"):
        _build(due_at=CREATED + timedelta(days=7))
    with pytest.raises(CommitmentError, match="horizon_not_an_explicit_duration"):
        _build(horizon="5_sessions")


def test_cli_as_of_is_report_only(tmp_path, monkeypatch, capsys):
    from scripts import resolve_due_checkpoints, sweep_commitment_outcomes as cli

    monkeypatch.setattr(resolve_due_checkpoints, "_price_lookup_factory", lambda: (lambda _s, _d: None))
    (tmp_path / "commitments.jsonl").write_text(json.dumps(_xlb()) + "\n" + json.dumps(_template()) + "\n",
                                                encoding="utf-8")
    assert cli.main(["--state-root", str(tmp_path), "--as-of", "2026-10-10T22:20:00Z", "--apply"]) == 2
    assert json.loads(capsys.readouterr().out)["outcome"] == "AS_OF_REFUSED_WITH_APPLY"
    assert not (tmp_path / "commitment_outcomes.jsonl").exists()


def test_cli_as_of_reports_xlb_guarded_tomorrow(tmp_path, monkeypatch, capsys):
    from scripts import resolve_due_checkpoints, sweep_commitment_outcomes as cli

    monkeypatch.setattr(resolve_due_checkpoints, "_price_lookup_factory", lambda: (lambda _s, _d: None))
    (tmp_path / "commitments.jsonl").write_text(json.dumps(_xlb()) + "\n" + json.dumps(_template()) + "\n",
                                                encoding="utf-8")
    assert cli.main(["--state-root", str(tmp_path), "--as-of", "2026-10-10T22:20:00Z"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["applied"] is False
    assert report["horizon_guarded"] == 1
    assert report["by_outcome"] == {"UNSCOREABLE": 1}
    assert not (tmp_path / "commitment_outcomes.jsonl").exists()
