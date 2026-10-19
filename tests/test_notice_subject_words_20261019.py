"""Operational words must not become security subjects; no external effects."""

from datetime import datetime, timezone

import pytest

from scripts.lib import comms_editor as ce


@pytest.mark.parametrize(
    "word,message,subject",
    [
        ("LAST", "STOP HEALTH — LAST-KNOWN STOPS: XLI", "XLI"),
        ("DOWN", "STAND DOWN · NCPL · the setup broke down", "NCPL"),
        ("CC", "CC header will show STALE until cache is healed", None),
        ("DATA", "TRADE AI DATA QUALITY ALERT", None),
    ],
)
def test_operational_words_do_not_acquire_financial_links(tmp_path, word, message, subject):
    candidates = [{"symbol": word, "guid": f"fixture-{word}"}]
    if subject:
        candidates.append({"symbol": subject, "guid": f"fixture-{subject}"})
    result = ce.edit(
        message,
        chat_id="fixture",
        now=datetime(2026, 10, 19, 14, tzinfo=timezone.utc),
        ledger=ce.DuplicateLedger(tmp_path / "ledger.json"),
        resolve=lambda text: candidates,
        db_query=lambda *args, **kwargs: [],
        editor_mode="live",
    )
    assert word not in [row["symbol"] for row in result.subjects]
    assert f"/intelligence/{word}" not in result.text
    assert f"quote.ashx?t={word}" not in result.text
    if subject:
        assert subject in [row["symbol"] for row in result.subjects]
        assert f"/intelligence/{subject}" in result.text
    assert message in result.text


@pytest.mark.parametrize("word", ["LAST", "DOWN", "CC", "DATA"])
@pytest.mark.parametrize("mark", ["${word}", "ticker: {word}", "symbol {word}", "fixture-guid"])
def test_explicit_security_subjects_are_preserved(word, mark):
    row = {"symbol": word, "guid": "fixture-guid"}
    assert ce.unambiguous_subjects(mark.format(word=word), [row]) == [row]


@pytest.mark.parametrize("word", ["LAST", "DOWN", "CC", "DATA"])
def test_explicit_producer_subject_scope_is_preserved(tmp_path, word):
    result = ce.edit(
        f"Research update for {word}",
        chat_id="fixture",
        now=datetime(2026, 10, 19, 14, tzinfo=timezone.utc),
        ledger=ce.DuplicateLedger(tmp_path / "ledger.json"),
        resolve=lambda text: [{"symbol": word, "guid": "fixture-guid"}],
        db_query=lambda *args, **kwargs: [],
        editor_mode="live",
        primary_symbols=[word],
    )
    assert [row["symbol"] for row in result.subjects] == [word]
    assert f"/intelligence/{word}" in result.text
