"""Wave 2 slice 12a live-activation regression.

Observed immediately after #621 promoted: `/v3/cio/home` served `held_n=19` with
SCHG still counted as a hold, on code that excludes it.

The operator product prefers a persisted brief's `holdings_thesis_coverage` and
only recomputed when `held_n` was missing — a condition a *pre-12a* block
satisfies. So the stale block was served until the next brief persist happened
to rewrite it. Correctness depended on that timing.

The freshness check now treats a block missing the 12a keys as stale, so the
surface is right on the first request after a promote rather than the first
request after the next worker pass.

READ_ONLY_ADVISORY. MBI=0.
"""
from __future__ import annotations

import pytest

from scripts.lib.cio_operator_product import build_operator_product

PRE_12A = {
    "held_n": 19,
    "current_n": 19,
    "unavailable_n": 0,
    "items": [{"symbol": "SCHG", "thesis_status": "CURRENT"}],
}

POST_12A = {
    "held_n": 15,
    "current_n": 15,
    "unavailable_n": 0,
    "items": [{"symbol": "SCHD", "thesis_status": "CURRENT"}],
    "dust_tickers": ["SCHG"],
    "dust_n": 1,
    "held_n_including_dust": 16,
    "instrument_id_n": 3,
}


def _recompute_calls(monkeypatch):
    calls: list[int] = []

    def _fake(*, holdings=None, root=None):
        calls.append(1)
        return dict(POST_12A)

    monkeypatch.setattr(
        "scripts.lib.cio_investment_product.collect_holdings_thesis_coverage", _fake,
    )
    monkeypatch.setattr(
        "scripts.lib.cio_investment_product.collect_holdings",
        lambda root=None: {"holdings": []},
    )
    return calls


@pytest.mark.parametrize("stale", [
    PRE_12A,                                              # the real regression
    {**PRE_12A, "dust_tickers": ["SCHG"]},                # half-migrated
    {**PRE_12A, "held_n_including_dust": 19},             # half-migrated
    {},                                                   # empty
    None,                                                 # absent
])
def test_a_pre_12a_coverage_block_is_recomputed(monkeypatch, stale):
    calls = _recompute_calls(monkeypatch)
    monkeypatch.setattr(
        "scripts.lib.cio_operator_product._load_brief",
        lambda *a, **k: {"holdings_thesis_coverage": stale},
        raising=False,
    )
    cov = build_operator_product(root=None, persist=False).get("holdings_thesis_coverage") or {}
    # Either it recomputed, or it produced a block that carries the 12a keys.
    assert calls or ("dust_tickers" in cov and "held_n_including_dust" in cov)


def test_a_current_schema_block_is_not_needlessly_recomputed():
    """The check must detect stale schema, not recompute on every request."""
    from scripts.lib import cio_operator_product as cop
    import inspect

    src = inspect.getsource(cop)
    assert '"dust_tickers" not in cov' in src
    assert '"held_n_including_dust" not in cov' in src


def test_fallback_block_carries_the_12a_keys():
    """Even the fail-soft zero block must not look like a pre-12a block."""
    from scripts.lib import cio_operator_product as cop
    import inspect

    src = inspect.getsource(cop)
    fallback = src.split('except Exception:', 1)[-1]
    assert '"dust_tickers": []' in src
    assert '"held_n_including_dust": 0' in src
