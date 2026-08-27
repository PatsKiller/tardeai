"""SchwabInstrumentEvidence@v1 — the broker-reference sweep store.

The behaviour under test is not "can we parse a payload" but "does the store
refuse to manufacture evidence", which is what makes a CONFIRMED identity built
on it trustworthy.
"""
from __future__ import annotations

import json

from scripts.lib.identity_registry import empty_registry, lookup_symbol, register
from scripts.lib.schwab_instrument_evidence import (
    empty_evidence,
    identifier_rows,
    load,
    record_instrument,
    record_miss,
    save,
)


def test_payload_without_a_durable_id_is_a_miss_not_an_instrument():
    """A description-only row must never look like identifier evidence.

    Schwab returns a name for symbols it cannot give a CUSIP for. Filing that
    under `instruments` would let the mint confirm an entity on a company name
    the holdings source already supplied — a CONFIRMED status backed by nothing.
    """
    doc = record_instrument(empty_evidence(), "ACLX", {"description": "ARCELLX INC"})

    assert "ACLX" not in doc["instruments"]
    assert doc["misses"]["ACLX"]["reason"] == "no_durable_identifier_in_payload"
    assert identifier_rows(doc) == []


def test_identifiers_are_normalized_and_blanks_are_not_evidence():
    doc = record_instrument(empty_evidence(), "adtn", {"cusip": " 00486h105 "})
    assert doc["instruments"]["ADTN"]["identifiers"] == {"cusip": "00486H105"}

    blank = record_instrument(empty_evidence(), "AAA", {"cusip": "   "})
    assert "AAA" not in blank["instruments"]


def test_a_later_hit_clears_an_earlier_miss():
    """A symbol that resolves on a retry must stop being reported as a miss."""
    doc = record_miss(empty_evidence(), "ADTN", "fetch_failed:Timeout")
    record_instrument(doc, "ADTN", {"cusip": "00486H105"})

    assert "ADTN" not in doc["misses"]
    assert doc["instruments"]["ADTN"]["identifiers"]["cusip"] == "00486H105"


def test_rows_feed_the_registry_and_confirm_an_unheld_symbol():
    """The point of the sweep: a name we have never traded becomes CONFIRMED."""
    doc = record_instrument(empty_evidence(), "ABCL", {
        "cusip": "00288U106", "description": "ABCELLERA BIOLOGICS", "exchange": "NASDAQ",
    })
    rows = identifier_rows(doc)
    assert rows == [{
        "symbol": "ABCL",
        "identifiers": {"cusip": "00288U106"},
        "source": "schwab_instruments",
        "company": "ABCELLERA BIOLOGICS",
        "exchange": "NASDAQ",
    }]

    registry = register(empty_registry(), rows[0])
    entity = lookup_symbol(registry, "ABCL")
    assert entity["identity_status"] == "CONFIRMED"
    assert entity["identifiers"] == {"cusip": "00288U106"}
    assert entity["identity_basis"] == "cusip"


def test_a_corrupt_store_reads_as_empty_rather_than_poisoning_identity(tmp_path):
    """Garbage on disk must not become identity input."""
    path = tmp_path / "evidence.json"
    path.write_text("{ not json", encoding="utf-8")
    assert load(path)["instruments"] == {}
    assert load(path)["misses"] == {}

    path.write_text(json.dumps({"schema": "SomethingElse@v9",
                                "instruments": {"X": {"identifiers": {"cusip": "1"}}}}),
                    encoding="utf-8")
    assert load(path)["instruments"] == {}, "a foreign schema must not be trusted"


def test_save_round_trips(tmp_path):
    path = tmp_path / "evidence.json"
    doc = record_instrument(empty_evidence(), "ABCL", {"cusip": "00288U106"})
    save(doc, path)
    assert load(path)["instruments"]["ABCL"]["identifiers"] == {"cusip": "00288U106"}
