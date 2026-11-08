"""ANCHOR: NEWS_TO_CATALYST_SUMMARY_ONLY_20261108 — a body mention is not an event.

LQ-20261107-1131. The 2026-11-08 14:02–14:07 ET catalyst_events batch (46 rows, written by the
``news-ingestion-tail`` lane through ``scripts/news_ingestion.py`` -> ``news_to_catalyst._classify``)
carried types the headline never stated: an analyst upgrade from a costs-and-rankings piece, a
geopolitical tag from an earnings-growth valuation, a buyback from an earnings-call transcript, a
merger from earnings-call highlights. Replaying the module's own ``_classify`` over those 46 rows,
26 matched **only** in the article summary — an incidental body word ("outperform", "tariff",
"acquisition", "buyback", "new agreement") typed the article even though the event reported for the
ticker was different.

The repair is scoped: for the five types whose vocabulary appears routinely in article *bodies*
without describing an event of the issuer (analyst_upgrade, geopolitical, merger_acquisition,
buyback, contract_win), the keyword must appear in the HEADLINE. Earnings / guidance / dividend
keep the summary in evidence, because a results story routinely states the beat or the guidance
change in the body and the headline is a generic "reports results".

Synthetic text only (the repository is public); no DB, no network, no live lane.
"""
from __future__ import annotations

import importlib

import pytest


def _n2c():
    """The lane script (conftest puts ``scripts/`` on the path)."""
    return importlib.import_module("news_to_catalyst")


def _classify(title: str, summary: str) -> str:
    return _n2c()._classify(title, summary)


# ── a summary-only mention of the five body-prone families types nothing ───────────────────────────────────────

@pytest.mark.parametrize("summary, forbidden", [
    ("Analysts argue the shares could outperform peers from here.", "analyst_upgrade"),
    ("Management fielded questions about a proposed tariff on imported components.", "geopolitical"),
    ("The quarter included the acquisition of a small supplier.", "merger_acquisition"),
    ("Management also discussed a share repurchase authorization from 2024.", "buyback"),
    ("The company renewed a new agreement with an existing distributor.", "contract_win"),
])
def test_summary_only_mention_does_not_type_the_article(summary, forbidden):
    title = "Example Brands reports third-quarter results and discusses costs"
    assert _classify(title, summary) != forbidden
    assert _classify(title, summary) == "other"


def test_earnings_call_transcript_is_not_a_buyback_from_its_body():
    title = "Example Holdings third-quarter earnings call transcript"
    summary = "The operator read prepared remarks; a director asked about buyback timing."
    assert _classify(title, summary) == "other"


# ── the same words in the HEADLINE are evidence, so recall is kept ─────────────────────────────────────────────

@pytest.mark.parametrize("title, expected", [
    ("Example Holdings upgraded to Buy at Example Securities", "analyst_upgrade"),
    ("Example Steel wins exemption from new tariffs", "geopolitical"),
    ("Example Corp agrees to acquire Rival Co", "merger_acquisition"),
    ("Example Corp announces a share repurchase program", "buyback"),
    ("Example Defense wins contract with the Navy", "contract_win"),
])
def test_headline_mention_still_types(title, expected):
    assert _classify(title, "No further detail was provided.") == expected


# ── the repair is scoped, not a blanket headline-only classifier ───────────────────────────────────────────────

def test_results_stated_in_the_body_still_type():
    title = "Example Corp reports third-quarter results"
    summary = "The company posted a revenue beat and raised guidance for the year."
    assert _classify(title, summary) in {"earnings_beat", "guidance_raise"}
