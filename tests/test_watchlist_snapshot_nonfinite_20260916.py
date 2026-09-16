"""2026-09-16: a non-finite close price must never destroy a watchlist agent write.

Measured the same day in ``logs/watchlist_agent_jobs_offpeak.log``::

    DETAIL:  Token "NaN" is invalid.
    CONTEXT:  JSON data, line 1: ..."recent_prices": [{"price": NaN...

``float()`` on a Postgres NUMERIC ``NaN`` yields Python ``nan``; ``json.dumps`` emits a
bare ``NaN`` token, which is not JSON; Postgres rejects the whole INSERT; the agent's
answer is discarded and ``watchlist_items`` still looks clean. Nothing alarmed — exactly
one monitor in the repo mentions NaN at all.

These tests pin both halves of the fix:
  1. the source never builds a non-finite price point, and says how many it dropped;
  2. the writer serialises with ``allow_nan=False``, so a future non-finite value fails
     at the writer (named, logged, recoverable) instead of at the database (opaque,
     row-destroying).

Source-level: the module imports psycopg2/telegram at import time, so the pure helpers
are extracted with ast, the same way ``test_watchlist_agent_job_llm_retries_20260915``
does it.
"""
from __future__ import annotations

import ast
import json
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "scripts" / "process_watchlist_agent_jobs.py").read_text(encoding="utf-8")

WANT = {"_json_finite", "_pg_json", "_finite_price_points"}


def _ns() -> dict:
    tree = ast.parse(SRC)
    keep = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in WANT]
    assert {n.name for n in keep} == WANT, "the non-finite guards are gone from the writer"
    ns: dict = {"json": json}
    exec(compile(ast.Module(body=keep, type_ignores=[]), "nonfinite_guards", "exec"), ns)
    return ns


def _strict(s: str):
    """Parse as real JSON: bare NaN/Infinity raise instead of being silently accepted."""
    def _boom(tok):
        raise ValueError(f"bare {tok} is not JSON")
    return json.loads(s, parse_constant=_boom)


# ------------------------------------------------- the defect, reproduced verbatim

def test_the_original_expression_really_does_emit_bare_nan():
    """The before-state, so the fix is measured against the actual failure."""
    prices = [{"close_price": float("nan"), "price_date": "2026-09-16"}]
    old = json.dumps({"recent_prices": [{"price": float(p["close_price"]),
                                         "date": str(p["price_date"])} for p in prices]})
    assert "NaN" in old                      # this is the string Postgres rejected
    with pytest.raises(ValueError):
        _strict(old)


# ------------------------------------------------------------------- source guard

def test_a_non_finite_close_is_dropped_not_rendered():
    f = _ns()["_finite_price_points"]
    rows = [
        {"close_price": 10.5, "price_date": "2026-09-16"},
        {"close_price": float("nan"), "price_date": "2026-09-15"},
        {"close_price": float("inf"), "price_date": "2026-09-14"},
        {"close_price": 9.25, "price_date": "2026-09-13"},
    ]
    points, dropped = f(rows)
    assert dropped == 2
    assert [p["price"] for p in points] == [10.5, 9.25]
    assert all(math.isfinite(p["price"]) for p in points)
    # And the whole snapshot now survives a strict encode.
    assert _strict(json.dumps({"recent_prices": points}, allow_nan=False))


def test_a_null_or_junk_close_is_a_missing_price_not_a_crash():
    f = _ns()["_finite_price_points"]
    points, dropped = f([{"close_price": None, "price_date": "d"},
                         {"close_price": "n/a", "price_date": "d"},
                         {"price_date": "d"}])
    assert points == [] and dropped == 3
    assert f(None) == ([], 0) and f([]) == ([], 0)


def test_the_drop_is_counted_so_the_loss_is_never_silent():
    """A shorter list alone is indistinguishable from a symbol with fewer quotes."""
    assert '"recent_prices_dropped_nonfinite": dropped_prices' in SRC
    assert "clean_prices, dropped_prices = _finite_price_points(prices)" in SRC


def test_the_prompt_text_can_no_longer_print_a_nan_price():
    """The agent was one format-string away from reading 'Recent prices: $nan'."""
    assert "float(p['close_price'])" not in SRC, "the prompt builder still floats the raw column"
    assert "price_strs = [f\"${p['price']:.2f}\" for p in clean_prices[:5]]" in SRC


# ------------------------------------------------------------------- writer guard

def test_the_writer_cannot_emit_bare_nan_even_if_a_new_field_carries_one():
    pg = _ns()["_pg_json"]
    out = pg({"cost": float("nan"), "conf": float("-inf"), "ok": 1.5}, "full_result")
    assert "NaN" not in out and "Infinity" not in out
    doc = _strict(out)                      # valid JSON — Postgres would accept it
    assert doc == {"cost": None, "conf": None, "ok": 1.5}


def test_a_clean_payload_takes_the_strict_fast_path_untouched():
    pg = _ns()["_pg_json"]
    assert _strict(pg({"recent_prices": [{"price": 10.5, "date": "2026-09-16"}]})) == {
        "recent_prices": [{"price": 10.5, "date": "2026-09-16"}]}


def test_a_non_finite_value_is_announced_at_the_writer(capsys):
    """Fails loudly HERE instead of silently at the database."""
    _ns()["_pg_json"]({"price": float("nan")}, "input_data_snapshot")
    out = capsys.readouterr().out
    assert "[json-nonfinite]" in out and "input_data_snapshot" in out


def test_non_serialisable_objects_still_fall_back_to_str():
    """allow_nan=False must not cost the existing default=str behaviour."""
    class Weird:
        def __str__(self): return "weird"
    assert _strict(_ns()["_pg_json"]({"x": Weird()})) == {"x": "weird"}


# ------------------------------------------------- the insert actually uses it

def test_every_json_column_write_in_the_agent_insert_is_strict():
    assert 'json.dumps(context["snapshot"]' not in SRC
    assert '_pg_json(context["snapshot"], "input_data_snapshot")' in SRC
    assert "_pg_json(dual_meta, \"dual_consensus_json\")" in SRC
    assert "json.dumps(dual_meta)" not in SRC
    assert '}, "full_result"),' in SRC


def test_both_serialisation_paths_in_the_writer_are_strict():
    body = SRC[SRC.index("def _pg_json("):SRC.index("def _finite_price_points(")]
    assert "return json.dumps(obj, default=str, allow_nan=False)" in body
    assert "return json.dumps(_json_finite(obj), default=str, allow_nan=False)" in body
