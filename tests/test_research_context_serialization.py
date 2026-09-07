"""A research packet is JSON by contract, and two things were breaking that.

Both surfaced 2026-09-07 when the material-change loop tried to route its first
questions. Both had been there long enough to matter, and neither was visible unless a
symbol's sector resolved into sector_momentum_state — which is exactly the tracked
universe the new layer routes for.

1. DECIMAL
    Postgres NUMERIC arrives as decimal.Decimal and json.dumps refuses it:

        TypeError: Object of type Decimal is not JSON serializable
        when serializing dict item 'rs5'

    That killed the ENTIRE research request, on every lane.

    The tempting fix is json.dumps(default=str). It stops the crash and turns 1.23
    into "1.23" — changing the type for every downstream reader and trading a loud
    failure for a quiet one. Converted at the producer instead, to float.

2. REDACTING THE SERIALIZED FORM
    The packet was built as json.loads(redact(json.dumps(context))) — a line-oriented
    text redactor run over a JSON document. redact() DROPS WHOLE LINES containing a
    forbidden marker, and serialized JSON is one line, so a single match destroys the
    document:

        json.decoder.JSONDecodeError: Expecting ',' delimiter: line 1 column 2475

    Redaction is a property of the VALUES, not of the punctuation between them.

No database, no network.
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

RESEARCHER = ROOT / "scripts" / "hermes_external_researcher.py"
CONTEXT = ROOT / "scripts" / "lib" / "research_prompt_context.py"


@pytest.fixture(scope="module")
def ctxmod():
    return pytest.importorskip("scripts.lib.research_prompt_context")


# ── 1. Decimal ──────────────────────────────────────────────────────────────

def test_a_decimal_becomes_a_number_not_a_string(ctxmod):
    """default=str would have "fixed" this by corrupting the type."""
    out = ctxmod._jsonable({"rs5": Decimal("1.23")})
    assert out["rs5"] == 1.23
    assert isinstance(out["rs5"], float)
    assert not isinstance(out["rs5"], str)


def test_it_reaches_decimals_nested_anywhere(ctxmod):
    out = ctxmod._jsonable(
        {"sector_industry_state": {"rows": [{"rs5": Decimal("2.5")}]}})
    assert out["sector_industry_state"]["rows"][0]["rs5"] == 2.5
    json.dumps(out)   # the whole point: it must now serialize


def test_dates_survive_as_iso_strings(ctxmod):
    out = ctxmod._jsonable({"as_of": date(2026, 9, 7),
                            "at": datetime(2026, 9, 7, 10, 30)})
    assert out["as_of"] == "2026-09-07"
    assert out["at"].startswith("2026-09-07T10:30")
    json.dumps(out)


def test_ordinary_values_are_untouched(ctxmod):
    src = {"a": 1, "b": "two", "c": None, "d": True, "e": [1, "x"]}
    assert ctxmod._jsonable(src) == src


def test_the_sector_query_result_is_converted_at_the_producer(ctxmod):
    """Converting here keeps every caller safe, not just the one that crashed."""
    src = CONTEXT.read_text(encoding="utf-8")
    for name in ("_sector_state", "_market_regime"):
        fn = src.split(f"def {name}(", 1)[1].split("\ndef ", 1)[0]
        assert "_jsonable(row)" in fn, f"{name} still returns raw DB rows"


def test_default_str_is_not_used_as_the_escape_hatch():
    src = RESEARCHER.read_text(encoding="utf-8")
    packet = src.split("def canonical_prompt_context", 1)[1].split("\ndef ", 1)[0]
    assert "default=str" not in packet, (
        "a str() coercion silently changes numeric types downstream")


# ── 2. redaction must not touch JSON syntax ────────────────────────────────

def test_the_packet_is_never_built_by_redacting_serialized_json():
    """Checked against CODE only — the comment above the fix deliberately quotes the
    old form to explain why it was wrong, and a file-wide search calls that a defect."""
    src = "\n".join(
        ln for ln in RESEARCHER.read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#"))
    assert "json.loads(redact(json.dumps(" not in src, (
        "redacting the serialized form is back — one forbidden marker deletes the "
        "whole document, because serialized JSON is a single line")


def test_redaction_walks_values_and_leaves_structure_intact():
    import hermes_external_researcher as H

    out = H._redact_values({"keep_key": ["text", 1, None],
                            "nested": {"k": "value"}})
    assert set(out) == {"keep_key", "nested"}
    assert out["keep_key"][1] == 1 and out["keep_key"][2] is None
    assert isinstance(out["nested"], dict)


def test_a_forbidden_marker_removes_only_its_own_value():
    """The failure being prevented: one match wiping the entire packet."""
    import hermes_external_researcher as H

    packet = {"safe": "ordinary text", "risky": "line one\nsecret-ish\nline three"}
    out = H._redact_values(packet)
    assert out["safe"] == "ordinary text", "an unrelated value was damaged"
    assert set(out) == {"safe", "risky"}


def test_the_redacted_packet_still_serializes():
    import hermes_external_researcher as H

    out = H._redact_values(H._jsonable_packet({"rs5": Decimal("1.5"),
                                               "note": "text"}))
    json.dumps(out)
    assert out["rs5"] == 1.5
