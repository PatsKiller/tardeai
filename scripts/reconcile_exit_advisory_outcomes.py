#!/usr/bin/env python3
"""Gain Guardian outcome reconciliation (F5, Phase-193 pattern).

For each PUBLISHED exit advisory, at +5 and +21 trading days record what the
market actually did and whether the operator acted — the evidence base that
will eventually justify (or kill) threshold changes. Without this, Gain
Guardian is another unfalsifiable advisor.

Verdicts (21d horizon):
  SIGNAL_CORRECT — post-advisory return underperforms SPY by >3% OR drawdown
                   from advisory price exceeds 1.5 ATR
  SIGNAL_EARLY   — 21d still outperforming, but a >1.5 ATR drawdown happened
                   along the way (the risk was real, the exit early)
  SIGNAL_WRONG   — outperformed SPY and never drew down 1.5 ATR
  NOT_EVALUABLE  — missing bars/ATR/benchmark

Usage:
  python scripts/reconcile_exit_advisory_outcomes.py            # reconcile due advisories
  python scripts/reconcile_exit_advisory_outcomes.py --self-test  # fixture verdict tests

2026-11-07 (LQ-20261107-104): every weekly run printed "no published exit advisories due — clean run on zero
rows" and exit_advisory_outcomes has held **0 rows ever**, because nothing produces its input: it reads
``hermes_research_intelligence.research_type='exit_intelligence'``, which only
``lib/gain_guardian_publish.publish_run`` writes, and that path is unreachable while
``config/gain_guardian_thresholds.json`` has ``published: false`` (Gain Guardian in shadow). The run now names
that dependency (``dependency_unavailable``, exit 1) instead of calling a permanently empty input clean, and
writes a LaneRunReceipt either way.

2026-11-08 (LQ-20261107-882): that receipt was itself wrong. ``exit_intelligence`` has 0 rows, but the types
Gain Guardian and its neighbours actually publish do not: read-only on 2026-11-08, ``protection_advisory``
(holding_protection_advisor) held 670 rows / 612 due and ``stop_health`` (stop_health_check) 972 / 936 — 1548
advisories awaiting an outcome while the lane said "nothing has ever been published to reconcile". The weekly
run failed (exit 1, ``dependency_unavailable``) instead of scoring them. This re-works LQ-87's selector onto
LQ-104's receipt contract: the selector and the producer counts both read EXIT_ADVISORY_TYPES (the union, so a
promoted Gain Guardian is reconciled too), "nothing to do" is measured as *pending* (advisories still owing an
outcome) rather than as "rows older than 5 days", and an empty or dead input is attributed to the producers by
name. The 200-advisory window is drained oldest-first, one bar fetch per symbol per run.
"""
from __future__ import annotations

import sys as _dr_sys

if __name__ == "__main__" and "--dry-run" in _dr_sys.argv[1:]:
    # n8n onboarding (lane disposition 2026-10-15, MIGRATE_N8N): --dry-run is an OFFLINE plan and wins over every
    # live flag (the bare scheduled run). It returns here, before the .env load, any DB/LLM/network/sender import and any file
    # write; it prints the plan and one LaneOutput@v1 line on stderr (produced 0, empty_reason dry_run).
    import os as _dr_os

    _dr_sys.path.insert(0, _dr_os.path.join(_dr_os.path.dirname(_dr_os.path.abspath(__file__))))
    from lib.lane_output import emit as _dr_emit, output_block as _dr_block

    _dr_lane = "reconcile-exit-advisory-outcomes"
    _dr_would = (
        "reconcile PUBLISHED exit advisories (research types protection_advisory/stop_health/exit_intelligence) "
        "due at +5/+21 trading days against bars and SPY and INSERT exit_advisory_outcomes rows "
        "(--self-test runs fixtures only)"
    )
    print(f"DRY-RUN {_dr_lane}: would {_dr_would}; argv={_dr_sys.argv[1:]!r}; dry-run wins over live flags; "
          "nothing read from env/DB/network, no model call, no send, no file write")
    _dr_emit(_dr_lane, "dry_run", _dr_block(produced=0, attempted=0, empty_reason="dry_run", unit="exit_advisory"))
    raise SystemExit(0)

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

DDL = """
CREATE TABLE IF NOT EXISTS exit_advisory_outcomes (
    id BIGSERIAL PRIMARY KEY,
    advisory_id BIGINT,
    symbol TEXT NOT NULL,
    advisory TEXT,
    advisory_at TIMESTAMPTZ,
    horizon_days INT NOT NULL,
    price_at_advisory NUMERIC,
    price_at_horizon NUMERIC,
    symbol_return_pct NUMERIC,
    spy_return_pct NUMERIC,
    max_drawdown_atr NUMERIC,
    giveback_frac_then NUMERIC,
    operator_acted BOOLEAN,
    verdict TEXT,
    evaluated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (advisory_id, horizon_days)
);
"""


LANE_ID = "reconcile-exit-advisory-outcomes"

# Every research type this lane reconciles = every type a producer actually writes (LQ-87, re-worked on the
# LQ-104 receipt contract). The lane used to read exit_intelligence only, which no run has ever written:
#   protection_advisory — holding_protection_advisor (stop-setting advice; evidence.inputs.{price,atr})
#   stop_health        — stop_health_check (health status; evidence.current_price, no ATR)
#   exit_intelligence  — lib/gain_guardian_publish.publish_run (an exit call; evidence.metrics_row), dark
#                        until the operator flips config/gain_guardian_thresholds.json published -> true
# stop_curation is deliberately absent: its evidence carries no price at all, so every row would be
# NOT_EVALUABLE noise.
EXIT_ADVISORY_TYPES = ("protection_advisory", "stop_health", "exit_intelligence")

# A producer silent this long is dead, not quiet (the same 45-day floor reconcile_watch_outcomes applies).
INPUT_DEAD_DAYS = 45
# Horizons measured after an advisory: (stored horizon_days, trading days to wait).
HORIZONS = ((5, 5), (21, 21))
# Calendar days of the longest horizon (trading days * 1.5, the same buffer the due check uses).
LONGEST_HORIZON_CAL_DAYS = int(max(t for _, t in HORIZONS) * 1.5)
# How far one bar fetch must reach: the advisory's own age, the longest horizon, and a bar-calendar slack.
# The drain is oldest-first, so the first advisory seen for a symbol needs the widest span and one fetch per
# symbol per run still holds (:func:`_closes_since`).
BAR_SPAN_SLACK_DAYS = 10
# A series whose first bar starts later than this after the advisory cannot measure that advisory's window.
BAR_COVER_SLACK_DAYS = 7

# Why a run produced nothing. ``up_to_date`` is the only one that is clean; the rest are failures naming
# a cause, never a green "0" (AGENTS.md rule 8: exit 0 is not evidence of work).
CLEAN_EMPTY_REASONS = frozenset({"up_to_date"})


def _num(v) -> float | None:
    """A positive number, or None. Never 0 for a missing/garbage value."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def advisory_fields(research_type, ev) -> tuple[dict, float | None, float | None]:
    """(fields for the row, price at advisory, ATR) from the real evidence shapes.

    A price the evidence does not carry stays None: the row is written NOT_EVALUABLE, never scored
    against 0. A legacy ``evidence_json.metrics_row`` wins when present (the exit_intelligence shape)."""
    ev = ev if isinstance(ev, dict) else {}
    mr = ev.get("metrics_row")
    if isinstance(mr, dict) and mr:
        return mr, _num(mr.get("price")), _num(mr.get("atr14"))
    if research_type == "protection_advisory":
        inp = ev.get("inputs") if isinstance(ev.get("inputs"), dict) else {}
        rec = ev.get("recommendation") if isinstance(ev.get("recommendation"), dict) else {}
        pct = rec.get("stop_pct_below")
        label = f"stop_{pct}pct" if pct is not None else "protection_advisory"
        return {"advisory": label}, _num(inp.get("price")), _num(inp.get("atr"))
    if research_type == "stop_health":
        return {"advisory": f"stop_health:{ev.get('health')}"}, _num(ev.get("current_price")), None
    return {}, None, None


def _age_days(ts) -> int | None:
    """Whole days since ``ts`` (a datetime or an ISO string); None when it cannot be read.

    Unknown stays None: a timestamp that did not parse must not become "0 days old"."""
    if ts is None:
        return None
    try:
        when = dt.datetime.fromisoformat(str(ts)) if isinstance(ts, str) else ts
        if when.tzinfo is None:
            when = when.replace(tzinfo=dt.timezone.utc)
        return max(0, (dt.datetime.now(dt.timezone.utc) - when).days)
    except (TypeError, ValueError):
        return None


def producer_state(ex) -> dict:
    """How much input exists: ``ever`` rows of the reconciled types, ``due`` ones past the 5-day floor,
    ``pending`` the ones still owing an outcome, and the age of the newest row.

    A count that did not come back stays unknown (None), never 0: ``ever == 0`` is the evidence that every
    producer is switched off, so a failed read must not be able to masquerade as that evidence (LQ-104)."""
    row = ex(
        """SELECT count(*) AS ever,
                  count(*) FILTER (WHERE h.created_at < now() - interval '5 days') AS due,
                  count(*) FILTER (
                      WHERE h.created_at < now() - interval '5 days'
                        AND (SELECT count(*) FROM exit_advisory_outcomes o
                              WHERE o.advisory_id = h.id) < 2) AS pending,
                  max(h.created_at) AS newest
           FROM hermes_research_intelligence h
           WHERE h.research_type = ANY(%s) AND h.symbol IS NOT NULL""",
        (list(EXIT_ADVISORY_TYPES),),
        fetch="one",
    ) or {}
    ever, due, pending = row.get("ever"), row.get("due"), row.get("pending")
    if ever is None or due is None or pending is None:
        return {"ever": None, "due": None, "pending": None, "newest_age_days": None}
    return {"ever": int(ever), "due": int(due), "pending": int(pending),
            "newest_age_days": _age_days(row.get("newest"))}


def gain_guardian_published() -> bool | None:
    """The switch that decides whether exit_intelligence is ever published (None when the config is unreadable)."""
    path = ROOT / "config" / "gain_guardian_thresholds.json"
    try:
        return bool(json.loads(path.read_text()).get("published"))
    except (OSError, ValueError, AttributeError):
        return None


def empty_input_reason(state: dict, published: bool | None) -> tuple[str, str]:
    """Why the selector returned nothing: producers off, a dead feed, up to date, or unattributable.

    The order matters, and only ``up_to_date`` is clean.

    * a count that did not come back attributes nothing — ``input_unreadable``;
    * 0 rows ever means no producer of any reconciled type has ever written — ``dependency_unavailable``,
      naming all three writers and, when it was readable, Gain Guardian's ``published`` switch;
    * rows present but none newer than INPUT_DEAD_DAYS means the producers died — ``dependency_unavailable``,
      naming the newest date, never "a quiet week";
    * no advisory still owing an outcome is ``up_to_date``;
    * rows still owing an outcome that the selector did not return is an internal contradiction —
      ``input_inconsistent``, never clean.
    """
    if state.get("ever") is None or state.get("pending") is None:
        return ("input_unreadable",
                "the advisory row counts did not come back, so an empty result cannot be attributed"
                " to a quiet week")
    if state["ever"] == 0:
        if published is None:
            return ("input_unreadable",
                    f"no {'/'.join(EXIT_ADVISORY_TYPES)} rows exist and config/gain_guardian_thresholds.json"
                    " could not be read, so the producers' switch state is unknown")
        gg = "unpublished (published=false — promote it to reconcile its exit_intelligence rows)" if published is False \
            else "published (published=true), so its writer is failing"
        return ("dependency_unavailable",
                f"no {'/'.join(EXIT_ADVISORY_TYPES)} rows exist: holding_protection_advisor, stop_health_check and"
                f" gain_guardian_publish have never published an advisory to reconcile; Gain Guardian is {gg}")
    age = state.get("newest_age_days")
    if age is not None and age > INPUT_DEAD_DAYS:
        return ("dependency_unavailable",
                f"the newest reconciled advisory is {age} days old (> {INPUT_DEAD_DAYS}): the producers are"
                " silent, which is not a quiet week")
    if state["pending"] == 0:
        return ("up_to_date", f"all {state['ever']} reconciled advisories already carry their outcome rows")
    return ("input_inconsistent",
            f"{state['pending']} advisories are pending but the selector returned none")


def _receipt(*, ok: bool, produced: int, attempted: int | None = None, empty_reason=None, skipped=None,
             error=None) -> None:
    """LaneRunReceipt (data/runtime/reconcile-exit-advisory-outcomes_last.json). Never raises."""
    try:
        from lib.lane_last_receipt import now_iso, write_lane_receipt
        write_lane_receipt(LANE_ID, ok=ok, started_at=now_iso(), script="reconcile_exit_advisory_outcomes.py",
                           produced_count=max(0, int(produced)), attempted_count=attempted,
                           skipped_reasons=skipped or {}, empty_reason=empty_reason, error=error)
    except Exception as exc:  # noqa: BLE001 -- a receipt problem must not change the run's verdict
        print(f"[exit-outcomes] receipt not written: {exc}", file=sys.stderr)


def verdict_for(*, symbol_return_pct: float | None, spy_return_pct: float | None,
                max_drawdown_atr: float | None) -> str:
    """Pure verdict logic — unit-tested with fixtures below."""
    if symbol_return_pct is None or spy_return_pct is None:
        return "NOT_EVALUABLE"
    rel = symbol_return_pct - spy_return_pct
    deep_dd = max_drawdown_atr is not None and max_drawdown_atr > 1.5
    if rel < -3.0 or deep_dd and rel < 0:
        return "SIGNAL_CORRECT"
    if deep_dd:
        return "SIGNAL_EARLY"
    return "SIGNAL_WRONG"


def _closes_since(symbol: str, since_iso: str, needed_days: int, cache: dict | None = None) -> list[float]:
    """Closes for ``symbol`` on/after ``since_iso``, oldest first.

    ``needed_days`` is how far back this advisory's window can reach (its age plus the longest horizon), so a
    backlogged advisory cannot be measured against a series that starts after it. ``cache`` maps symbol ->
    (days fetched, bars) and is reused only when it already reaches far enough; because the drain is
    oldest-first, that stays one network call per symbol per run. A series that still does not begin near the
    advisory returns ``[]``, so the caller writes NOT_EVALUABLE instead of a verdict on a shifted window.
    """
    from holdings_gain_guardian import _bars_with_volume
    days = max(int(needed_days), LONGEST_HORIZON_CAL_DAYS + BAR_SPAN_SLACK_DAYS)
    bars = None
    if cache is not None:
        hit = cache.get(symbol)
        if hit and hit[0] >= days:
            bars = hit[1]
    if bars is None:
        bars = _bars_with_volume(symbol, days=days) or []
        if cache is not None:
            cache[symbol] = (days, bars)
    since = dt.date.fromisoformat(since_iso[:10])
    cover_by = since + dt.timedelta(days=BAR_COVER_SLACK_DAYS)
    out: list[float] = []
    first = None
    for b in bars:
        ts = b.get("datetime") or b.get("t") or b.get("date") or ""
        try:
            when = (dt.datetime.fromtimestamp(ts / 1000, dt.timezone.utc)
                    if isinstance(ts, (int, float)) else dt.datetime.fromisoformat(str(ts)[:19]).replace(tzinfo=dt.timezone.utc))
        except Exception:
            continue
        if str(when.date()) >= since_iso[:10]:
            c = float(b.get("close") or 0)
            if c > 0:
                if first is None:
                    first = when.date()
                out.append(c)
    if first is None or first > cover_by:
        return []            # the fetch did not reach the advisory date: no honest outcome for this window
    return out


def _horizon_end(created_at, trading_days: int):
    """Calendar end of a horizon window (trading days * 1.5, the buffer the due check uses); None if unreadable."""
    try:
        return created_at + dt.timedelta(days=int(trading_days * 1.5))
    except TypeError:
        return None


def reconcile() -> int:
    from db_adapter import _execute as ex, USE_DB
    if not USE_DB:
        print("DB unavailable", file=sys.stderr)
        return 2
    for stmt in DDL.strip().split(";"):
        if stmt.strip():
            ex(stmt, fetch="none")

    state = producer_state(ex)
    advisories = ex(
        """SELECT h.id, h.symbol, h.topic, h.created_at, h.research_type, h.evidence_json
           FROM hermes_research_intelligence h
           WHERE h.research_type = ANY(%s)
             AND h.symbol IS NOT NULL
             AND h.created_at < now() - interval '5 days'
             AND (SELECT count(*) FROM exit_advisory_outcomes o WHERE o.advisory_id = h.id) < 2
           ORDER BY h.created_at ASC LIMIT 200""",
        (list(EXIT_ADVISORY_TYPES),),
        fetch="all",
    ) or []
    if not advisories:
        reason, why = empty_input_reason(state, gain_guardian_published())
        if reason in CLEAN_EMPTY_REASONS:
            print(f"[exit-outcomes] {reason} — {why}")
            _receipt(ok=True, produced=0, attempted=0, empty_reason=reason)
            return 0
        print(f"[exit-outcomes] {reason} — {why}", file=sys.stderr)
        pending = state.get("pending")
        _receipt(ok=False, produced=0, attempted=None if pending is None else int(pending),
                 empty_reason=reason, skipped={reason: 1}, error=why)
        return 1

    done = 0
    attempted = 0
    skipped: dict[str, int] = {}
    bars_cache: dict[str, tuple[int, list]] = {}
    for a in advisories:
        ev = a.get("evidence_json")
        if isinstance(ev, str):
            try:
                ev = json.loads(ev)
            except Exception:
                ev = {}
        m, p0, atr = advisory_fields(a.get("research_type"), ev)
        age_days = _age_days(a.get("created_at"))
        if age_days is None:
            skipped["advisory_at_unreadable"] = skipped.get("advisory_at_unreadable", 0) + 1  # nosemgrep: tq-py-missing-as-zero -- a skip counter starts at 0; it is not a data value
            continue
        for horizon, trading_days in ((5, 5), (21, 21)):
            if age_days < int(trading_days * 1.5):  # calendar buffer around trading days
                skipped["not_due"] = skipped.get("not_due", 0) + 1  # nosemgrep: tq-py-missing-as-zero -- a skip counter starts at 0; it is not a data value
                continue
            dup = ex("SELECT 1 FROM exit_advisory_outcomes WHERE advisory_id=%s AND horizon_days=%s",
                     (a["id"], horizon), fetch="one")
            if dup:
                skipped["already_reconciled"] = skipped.get("already_reconciled", 0) + 1  # nosemgrep: tq-py-missing-as-zero -- a skip counter starts at 0; it is not a data value
                continue
            attempted += 1
            # the advisory's own age + the longest horizon: a backlogged row needs a longer series, not a
            # window silently shifted forward to the oldest bar the fetch happened to return
            span = age_days + LONGEST_HORIZON_CAL_DAYS + BAR_SPAN_SLACK_DAYS
            closes = _closes_since(a["symbol"], str(a["created_at"]), span, bars_cache)
            spy = _closes_since("SPY", str(a["created_at"]), span, bars_cache)
            if len(closes) <= trading_days or len(spy) <= trading_days or not p0:
                ret = spy_ret = dd_atr = None
                v = "NOT_EVALUABLE"
            else:
                p_h = closes[trading_days]
                ret = round(100.0 * (p_h / p0 - 1), 2)
                spy_ret = round(100.0 * (spy[trading_days] / spy[0] - 1), 2)
                dd = p0 - min(closes[: trading_days + 1])
                dd_atr = round(dd / atr, 2) if atr else None
                v = verdict_for(symbol_return_pct=ret, spy_return_pct=spy_ret, max_drawdown_atr=dd_atr)
            acted = None
            window_end = _horizon_end(a["created_at"], trading_days)
            if window_end is not None:
                try:
                    # The window runs advisory -> horizon end. It used to be created_at -> created_at, an
                    # always-empty range that recorded operator_acted=False on every row (LQ-882).
                    acted_row = ex(
                        """SELECT 1 FROM alert_events
                           WHERE symbol=%s AND created_at BETWEEN %s AND %s
                             AND alert_type IN ('stop_replaced','order_filled','position_trimmed') LIMIT 1""",
                        (a["symbol"], a["created_at"], window_end), fetch="one",
                    )
                    acted = bool(acted_row)
                except Exception:
                    acted = None
            ex(
                """INSERT INTO exit_advisory_outcomes
                   (advisory_id, symbol, advisory, advisory_at, horizon_days, price_at_advisory,
                    price_at_horizon, symbol_return_pct, spy_return_pct, max_drawdown_atr,
                    giveback_frac_then, operator_acted, verdict)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (advisory_id, horizon_days) DO NOTHING""",
                (a["id"], a["symbol"], m.get("advisory"), a["created_at"], horizon, p0,
                 (closes[trading_days] if ret is not None else None), ret, spy_ret, dd_atr,
                 m.get("giveback_frac"), acted, v),
                fetch="none",
            )
            done += 1
    if done == 0:
        # The selector found work and none of it could be written: name it instead of reporting a green 0.
        why = f"{attempted} advisory-horizon pairs attempted, none written: {skipped or 'no reason recorded'}"
        print(f"[exit-outcomes] all_skipped — {why}", file=sys.stderr)
        _receipt(ok=True, produced=0, attempted=attempted, empty_reason="all_skipped", skipped=skipped)
        return 0
    print(f"[exit-outcomes] evaluated {done} advisory-horizon pairs (of {attempted} attempted)")
    _receipt(ok=True, produced=done, attempted=attempted, skipped=skipped)
    return 0


def self_test() -> int:
    fixtures = [
        # (sym_ret, spy_ret, dd_atr, expected)
        (-8.0, 1.0, 0.8, "SIGNAL_CORRECT"),   # big relative underperformance
        (4.0, 2.0, 2.1, "SIGNAL_EARLY"),      # still outperforming but deep drawdown happened
        (6.0, 2.0, 0.4, "SIGNAL_WRONG"),      # clean outperformance, shallow dd
        (None, 2.0, None, "NOT_EVALUABLE"),
        (-1.0, 1.0, 1.8, "SIGNAL_CORRECT"),   # deep dd while lagging
    ]
    fails = 0
    for sr, br, dd, want in fixtures:
        got = verdict_for(symbol_return_pct=sr, spy_return_pct=br, max_drawdown_atr=dd)
        status = "ok" if got == want else "FAIL"
        if got != want:
            fails += 1
        print(f"  [{status}] ret={sr} spy={br} dd_atr={dd} → {got} (want {want})")
    print("self-test:", "PASS" if fails == 0 else f"{fails} FAILURES")
    return 0 if fails == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    return self_test() if args.self_test else reconcile()


if __name__ == "__main__":
    raise SystemExit(main())
