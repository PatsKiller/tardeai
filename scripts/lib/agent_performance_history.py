"""agent_performance_history — the table's one safe write path and its display rules.

LQ-20261107-264. Two writers inserted one row per agent per period with a plain INSERT and the table
had no key over ``(agent, period_start, period_end)``:

* ``scripts/update_agent_performance.py`` — the daily 20:00 ET lane, 30-day rolling window;
* ``scripts/overnight_batch.py::record_agent_performance`` — the Sunday weekly aggregate.

So whenever the same period was scored twice, both writers added another row. Six such rows remain for
2026-05-24..2026-05-31, written 15 minutes apart on 2026-05-31 (ids 11..22). ``upsert_period_rows`` is now
the only write path: it serialises runs on the period with a transaction-scoped advisory lock and updates
the existing row instead of inserting a second one. The unique index that makes a duplicate impossible
even for a hand-written INSERT is proposed in
``migrations/2026_11_07_agent_performance_history_unique.sql``; this module does not depend on it.

``annotate_sample`` / ``accuracy_label`` give every consumer the same minimum-sample rule, so an agent
scored on one recommendation cannot be displayed as "100% accurate". The threshold is the repository's
own agent-calibration insight bar (``learning_governance.AGENT_SAMPLE_INSIGHT``, 25), not a new number.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from learning_governance import AGENT_SAMPLE_INSIGHT

#: Below this many scored recommendations an accuracy is noise, not a measurement.
MIN_SAMPLES = AGENT_SAMPLE_INSIGHT

#: What a surface shows instead of an accuracy it cannot stand behind.
NOT_ENOUGH_DATA = "not enough data"

_TABLE = "agent_performance_history"


def _int_or_zero(value: Any) -> int:
    try:
        return int(value) if value is not None else 0
    except (TypeError, ValueError):
        return 0


def annotate_sample(row: Mapping[str, Any], *, min_samples: int = MIN_SAMPLES) -> dict:
    """Copy ``row`` with ``sample_size_ok`` and ``min_samples`` added (never mutates the input)."""
    out = dict(row)
    out["min_samples"] = min_samples
    out["sample_size_ok"] = _int_or_zero(out.get("total_recommendations")) >= min_samples
    return out


def accuracy_label(row: Mapping[str, Any], *, min_samples: int = MIN_SAMPLES) -> str:
    """The text a surface should show for this row's accuracy: a number, an em dash, or the honest refusal."""
    r = annotate_sample(row, min_samples=min_samples)
    if not r["sample_size_ok"]:
        return NOT_ENOUGH_DATA
    acc = r.get("accuracy_pct")
    return "—" if acc is None else f"{acc}%"


def _returned_id(row: Any) -> Any:
    """``RETURNING id`` under a plain cursor (tuple) or psycopg2.extras.RealDictCursor (dict)."""
    if row is None:
        return None
    if isinstance(row, Mapping):
        return row.get("id")
    return row[0]


def upsert_period_rows(cur, period_start, period_end, rows: Sequence[Mapping[str, Any]]) -> list[dict]:
    """Insert-or-update one row per agent for ``(period_start, period_end)``.

    Returns one dict per input row, in the same order: ``{"id": <perf id>, "outcome": "inserted"|"updated"}``.

    The advisory lock is transaction-scoped: it is released by the caller's commit/rollback, so both
    writers keep their existing "score, write, commit" transaction shape. Concurrent runs for the same
    period queue on it instead of racing to insert. Callers must not use autocommit.
    """
    key = f"{_TABLE}:{period_start}:{period_end}"
    cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s)::bigint)", (key,))

    out: list[dict] = []
    for r in rows:
        params = (
            r.get("total_recommendations"), r.get("accuracy_pct"), r.get("avg_confidence"),
            # A caller that did not measure these leaves them None: the columns are nullable and 0 would read
            # as "none observed" (taxonomy #2 — a missing value must not become a zero).
            r.get("rule_violations"), r.get("human_overrides"),
            r.get("agent"), period_start, period_end,
        )
        # created_at is the row's snapshot time, not its first appearance: consumers order by it, and the
        # table has no updated_at column, so a refreshed snapshot has to carry its own timestamp.
        cur.execute(
            """
            UPDATE agent_performance_history
               SET total_recommendations = %s, accuracy_pct = %s, avg_confidence = %s,
                   rule_violations = %s, human_overrides = %s, created_at = now()
             WHERE agent = %s AND period_start = %s AND period_end = %s
            RETURNING id
            """,
            params,
        )
        hit = _returned_id(cur.fetchone())
        if hit is not None:
            out.append({"id": hit, "outcome": "updated"})
            continue
        cur.execute(
            """
            INSERT INTO agent_performance_history
                (agent, period_start, period_end, total_recommendations,
                 accuracy_pct, avg_confidence, rule_violations, human_overrides)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                r.get("agent"), period_start, period_end, r.get("total_recommendations"),
                r.get("accuracy_pct"), r.get("avg_confidence"), r.get("rule_violations"),
                r.get("human_overrides"),
            ),
        )
        out.append({"id": _returned_id(cur.fetchone()), "outcome": "inserted"})
    return out
