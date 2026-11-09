#!/usr/bin/env python3
"""agent_calibration_engine.py — Score agent recommendations against outcomes.

Generates calibration events, windows, learning evidence and recommendations.
No active config changes. Dry-run safe.

LQ-20261107-1032 (2026-11-08). The read used to be
``... LIMIT 2000`` with ``ROW_CAP = 2000`` in the source: the first live run (12:03 ET)
scored 2,000 of 73,525 eligible joined rows (2.7%) and said so, and because the event id was
random every weekly run inserted the same recommendations again — 6,411 duplicated
``(recommendation_id, scoring_window)`` groups. Two defects, two fixes:

* the read is a keyset page walk over every eligible recommendation, with the page size and
  an optional cap read from ``config/agent_calibration_engine.json`` (no constant);
* a recommendation is selected once — ``agent_recommendation_outcome_links`` fans out (one
  recommendation carries up to 169 paper trades and 85 proposals in the 90-day set), and the
  old join turned that fan-out into one event per link, so ``recommendations`` counted the
  same call again for every trade it touched. The page query takes the best link per
  recommendation (a realised paper-trade outcome before a proposal status), so one
  recommendation yields one event;
* the event id and the window id are derived from the natural key
  (``scripts/lib/calibration_keys.py``), so the existing ``ON CONFLICT (calibration_event_id)``
  and ``ON CONFLICT (window_id)`` actually fire and a re-run updates the row it wrote last week.

Rows the old code wrote are archived by ``scripts/archive_duplicate_calibration_events.py``
(operator applies). This script never deletes.

Usage:
    .venv/bin/python scripts/agent_calibration_engine.py --dry-run --json
    .venv/bin/python scripts/agent_calibration_engine.py --apply --json
    .venv/bin/python scripts/agent_calibration_engine.py --agent Maria --dry-run --json
"""
import argparse, json, sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
# No import-time load_dotenv(PROJECT_ROOT/".env"). session13_db.get_conn() calls env_bootstrap
# .load_env(), which reads the tmpfs render first and treats a disk .env as the fallback -- but it
# never overrides a name already in the environment, so loading the checkout .env first pinned
# whatever that file said. On 2026-11-08 a worktree .env naming a scratch pgemul socket made a
# "live" dry run read an empty database and report 0 events, with no error.
from lib import calibration_keys  # noqa: E402

CONFIG_REL = Path("config") / "agent_calibration_engine.json"
CONFIG_SCHEMA = "AgentCalibrationEngineConfig@v1"

AGENT_SAMPLE_INSIGHT = 25
AGENT_SAMPLE_SHADOW = 100


def _f(v): return float(v) if isinstance(v, Decimal) else v


def load_config(path=None):
    """The lane's tunables. A missing or malformed file is a failure, not a silent default.

    ``page_rows`` is how many recommendations one round trip returns; coverage never depends
    on it. ``max_rows_per_run`` is 0 (no cap) unless an operator reviewed a number here.
    """
    p = Path(path) if path else PROJECT_ROOT / CONFIG_REL
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise RuntimeError(f"calibration config missing: {p}")
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"calibration config unreadable: {p}: {exc}")
    if doc.get("schema") != CONFIG_SCHEMA:
        raise RuntimeError(f"calibration config {p} has schema {doc.get('schema')!r}, expected {CONFIG_SCHEMA}")
    page_rows = int(doc.get("page_rows") or 0)
    if page_rows <= 0:
        raise RuntimeError(f"calibration config {p}: page_rows must be positive")
    max_rows = int(doc.get("max_rows_per_run") or 0)
    if max_rows < 0:
        raise RuntimeError(f"calibration config {p}: max_rows_per_run must be >= 0 (0 = no cap)")
    return {"page_rows": page_rows, "max_rows_per_run": max_rows,
            "window_days": int(doc.get("window_days") or 90), "path": str(p)}


def _get_conn():
    from session13_db import get_conn
    return get_conn()


# ── Read: every eligible recommendation, one row each, in pages ──────────────────────────────
# `tq-py-sql-fstring`: the two braces hold code-built fragments only (an ILIKE clause whose value
# travels in params, and the keyset clause); every value is a parameter.
PAGE_SQL = """
    SELECT r.recommendation_id, r.agent_name, r.symbol, r.strategy_id,
           r.recommendation_type, r.confidence, r.recommendation_time,
           b.outcome_type, b.paper_trade_id, b.proposal_id, b.link_confidence
    FROM agent_recommendation_registry r
    JOIN LATERAL (
        SELECT l.outcome_type, l.paper_trade_id, l.proposal_id, l.link_confidence
        FROM agent_recommendation_outcome_links l
        WHERE l.recommendation_id = r.recommendation_id
        ORDER BY (l.paper_trade_id IS NOT NULL) DESC, l.link_confidence DESC NULLS LAST, l.id ASC
        LIMIT 1
    ) b ON TRUE
    WHERE r.recommendation_time > now() - make_interval(days => %s)
      {agent_clause}
      {keyset_clause}
    ORDER BY r.recommendation_time DESC, r.recommendation_id DESC
    LIMIT %s
"""


COUNT_SQL = """
    SELECT count(*) FROM agent_recommendation_registry r
    WHERE r.recommendation_time > now() - make_interval(days => %s)
      {agent_clause}
      AND EXISTS (
          SELECT 1 FROM agent_recommendation_outcome_links l
          WHERE l.recommendation_id = r.recommendation_id
      )
"""


def count_eligible(cur, *, window_days, agent_filter=None):
    """How many recommendations the walk would score with no cap. None when the count cannot be read."""
    params = [int(window_days)]
    agent_clause = ""
    if agent_filter:
        agent_clause = "AND r.agent_name ILIKE %s"
        params.append(f"%{agent_filter}%")
    # nosemgrep: tq-py-sql-fstring -- agent_clause is one of two literals; every value is a parameter
    cur.execute(COUNT_SQL.format(agent_clause=agent_clause), params)
    row = cur.fetchone()
    if not row or row[0] is None:
        return None
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return None


def fetch_page(cur, *, window_days, limit, after=None, agent_filter=None):
    """One page of (recommendation, its best outcome link), newest first, keyset-bounded."""
    params = [int(window_days)]
    agent_clause = ""
    if agent_filter:
        agent_clause = "AND r.agent_name ILIKE %s"
        params.append(f"%{agent_filter}%")
    keyset_clause = ""
    if after is not None:
        keyset_clause = "AND (r.recommendation_time, r.recommendation_id) < (%s, %s)"
        params.extend([after[0], after[1]])
    params.append(int(limit))
    # nosemgrep: tq-py-sql-fstring -- fragments are code-built; every value is a parameter
    cur.execute(PAGE_SQL.format(agent_clause=agent_clause, keyset_clause=keyset_clause), params)
    return cur.fetchall()


def iter_eligible_pages(conn, *, window_days=90, page_rows=500, max_rows=0, agent_filter=None):
    """Yield pages until the eligible set is exhausted.

    ``after`` is the last (recommendation_time, recommendation_id) read, so each page is a
    bounded index range and no page can repeat another (the old OFFSET-less LIMIT could not
    reach past its cap at all).
    """
    cur = conn.cursor()
    after = None
    read = 0
    try:
        while True:
            want = int(page_rows)
            if max_rows:
                remaining = int(max_rows) - read
                if remaining <= 0:
                    break
                want = min(want, remaining)
            rows = fetch_page(cur, window_days=window_days, limit=want,
                              after=after, agent_filter=agent_filter)
            if not rows:
                break
            read += len(rows)
            yield rows
            if len(rows) < want:
                break
            after = (rows[-1][6], rows[-1][0])
    finally:
        cur.close()


# ── Score one page (three batched lookups, not three per row) ────────────────────────────────
def _relist_symbols(cur, symbols):
    """Symbols whose stop-out was a relist/market-reconnection, i.e. a loss that is not a miss.

    A failed statement poisons the rest of the transaction, so the optional table/columns are
    read inside a savepoint: the fallback is an empty set, not a dead session.
    """
    if not symbols:
        return set()
    cur.execute("SAVEPOINT relist_probe")
    try:
        cur.execute("""
            SELECT DISTINCT symbol FROM stopped_out_watch
            WHERE symbol = ANY(%s) AND is_active = true
              AND explicit_stop_out = false
              AND (relisted_without_stop_out = true OR market_reconnection_event = true)
        """, (symbols,))
        found = {r[0] for r in cur.fetchall()}
        cur.execute("RELEASE SAVEPOINT relist_probe")
        return found
    except Exception:
        cur.execute("ROLLBACK TO SAVEPOINT relist_probe")
        return set()


def _paper_trades(cur, ids):
    if not ids:
        return {}
    cur.execute("SELECT id, status, pnl, r_multiple FROM paper_trades WHERE id = ANY(%s)", (list(ids),))
    return {r[0]: (r[1], r[2], r[3]) for r in cur.fetchall()}


def _proposals(cur, ids):
    if not ids:
        return {}
    cur.execute("SELECT id, status FROM paper_trade_proposals WHERE id = ANY(%s)", (list(ids),))
    return {r[0]: r[1] for r in cur.fetchall()}


def score_page(conn, rows, window_days=90):
    """Score one page. ``rows`` are fetch_page tuples (one per recommendation)."""
    cur = conn.cursor()
    try:
        symbols = sorted({r[2] for r in rows if r[2]})
        trade_ids = sorted({r[8] for r in rows if r[8] is not None})
        proposal_ids = sorted({r[9] for r in rows if r[8] is None and r[9] is not None})
        relists = _relist_symbols(cur, symbols)
        trades = _paper_trades(cur, trade_ids)
        proposals = _proposals(cur, proposal_ids)
    finally:
        cur.close()
    return [score_row(r, window_days=window_days, relists=relists, trades=trades, proposals=proposals)
            for r in rows]


def score_row(row, window_days=90, relists=frozenset(), trades=None, proposals=None):
    """One recommendation + its chosen outcome link -> one calibration event."""
    trades = trades or {}
    proposals = proposals or {}
    rec_id, agent, symbol, strat, rec_type, conf, _rec_time = row[:7]
    outcome_type, trade_id, proposal_id, _link_conf = row[7:11]

    actual = "unresolved"
    outcome_score = 0
    pnl = None
    r_mult = None
    explanation = "no_outcome_data"
    is_relist = symbol in relists

    if trade_id is not None:
        trade = trades.get(trade_id)
        if trade:
            status, t_pnl, t_r = trade
            pnl = _f(t_pnl)
            r_mult = _f(t_r)
            if status == "closed":
                if rec_type in ("buy", "add", "approve_trade"):
                    if (pnl or 0) > 0:
                        actual = "correct"
                        outcome_score = 1
                    elif is_relist:
                        # Relist: loss is market noise, not recommendation failure
                        actual = "relist_neutral"
                        outcome_score = 0
                    else:
                        actual = "incorrect"
                        outcome_score = -1
                    explanation = f"trade closed pnl={pnl}" + (" [relist]" if is_relist else "")
                elif rec_type in ("sell", "trim", "avoid", "reject_trade"):
                    if (pnl or 0) <= 0:
                        actual = "correct"
                        outcome_score = 1
                    elif is_relist:
                        actual = "relist_neutral"
                        outcome_score = 0
                    else:
                        actual = "incorrect"
                        outcome_score = -1
                    explanation = f"contrarian trade closed pnl={pnl}" + (" [relist]" if is_relist else "")
                else:
                    actual = "neutral"
                    explanation = f"non-directional rec, trade closed pnl={pnl}"
            else:
                actual = "unresolved"
                explanation = f"trade still {status}"
        else:
            explanation = f"trade {trade_id} not found"

    elif proposal_id is not None:
        status = proposals.get(proposal_id)
        if status == "REJECTED":
            if rec_type in ("avoid", "wait", "reject_trade"):
                actual = "correct"
                outcome_score = 0.5
                explanation = "proposal rejected, rec was cautious"
            else:
                actual = "neutral"
                explanation = "proposal rejected"
        elif status in ("APPROVED", "APPROVED_FOR_PAPER_TEST"):
            if rec_type in ("buy", "add", "approve_trade"):
                actual = "partially_correct"
                outcome_score = 0.3
                explanation = "proposal approved, awaiting trade outcome"
            else:
                actual = "neutral"
                explanation = "proposal approved"
        elif status is None:
            explanation = f"proposal {proposal_id} not found"
        else:
            actual = "unresolved"
            explanation = f"proposal status={status}"

    # Calibration error — skip relist_neutral (market event, not cal signal)
    cal_error = None
    overconf = None
    underconf = None
    if conf is not None and actual in ("correct", "incorrect"):
        c = float(conf)
        expected = c
        realized = 1.0 if actual == "correct" else 0.0
        cal_error = abs(expected - realized)
        overconf = max(0, expected - realized)
        underconf = max(0, realized - expected)

    return {
        "calibration_event_id": calibration_keys.event_key(rec_id, f"{int(window_days)}d"),
        "recommendation_id": rec_id,
        "agent_name": agent,
        "symbol": symbol,
        "strategy_id": strat,
        "outcome_type": outcome_type,
        "scoring_window": f"{int(window_days)}d",
        "predicted_action": rec_type,
        "predicted_confidence": _f(conf),
        "actual_outcome": actual,
        "outcome_score": outcome_score,
        "pnl": pnl,
        "r_multiple": r_mult,
        "calibration_error": cal_error,
        "overconfidence": overconf,
        "underconfidence": underconf,
        "explanation": explanation,
    }


def score_recommendations(conn, agent_filter=None, window_days=90, *, page_rows=None,
                          max_rows=None, config=None):
    """Score every eligible recommendation. Returns (events, stats).

    ``stats`` is the run's evidence: how many pages were read, how many recommendations were
    eligible, and whether a configured cap stopped the walk. It exists so a capped run can
    never read like a complete one (the old script printed a NOTE only when
    ``len(events) >= ROW_CAP``).
    """
    cfg = config or load_config()
    page_rows = int(page_rows if page_rows is not None else cfg["page_rows"])
    max_rows = int(cfg["max_rows_per_run"] if max_rows is None else max_rows)
    if page_rows <= 0:
        raise ValueError("page_rows must be positive")

    events = []
    count_cur = conn.cursor()
    try:
        eligible_total = count_eligible(count_cur, window_days=window_days, agent_filter=agent_filter)
    finally:
        count_cur.close()
    stats = {"page_rows": page_rows, "max_rows_per_run": max_rows, "pages_read": 0,
             "eligible_recommendations": 0, "eligible_total": eligible_total,
             "events_scored": 0, "rows_truncated": None, "capped": False,
             "config_path": cfg.get("path")}
    for page in iter_eligible_pages(conn, window_days=window_days, page_rows=page_rows,
                                    max_rows=max_rows, agent_filter=agent_filter):
        stats["pages_read"] += 1
        stats["eligible_recommendations"] += len(page)
        events.extend(score_page(conn, page, window_days=window_days))
    stats["events_scored"] = len(events)
    if eligible_total is None:
        # The population could not be counted. A cap that stopped the walk is still not a complete run.
        stats["capped"] = bool(max_rows) and stats["eligible_recommendations"] >= max_rows
    else:
        stats["rows_truncated"] = max(0, int(eligible_total) - stats["events_scored"])
        stats["capped"] = stats["rows_truncated"] > 0
    return events, stats


def aggregate_windows(events, window_days=90):
    """Aggregate calibration events into per-agent windows (one row per agent per run day)."""
    now = datetime.now(timezone.utc)
    window_start, window_end = calibration_keys.day_bounds(now, window_days)
    windows = {}

    for ev in events:
        agent = ev["agent_name"]
        if agent not in windows:
            windows[agent] = {
                "window_id": calibration_keys.window_key(agent, window_start, window_end, "general", None),
                "agent_name": agent,
                "window_start": window_start,
                "window_end": window_end,
                "domain": "general",
                "recommendations": 0, "resolved": 0,
                "correct": 0, "incorrect": 0, "neutral": 0,
                "partially_correct": 0, "unresolved": 0,
                "relist_neutral": 0,
                "confidences": [], "outcome_scores": [], "cal_errors": [],
                "overconfs": [], "underconfs": [], "r_multiples": [],
            }

        w = windows[agent]
        w["recommendations"] += 1
        w[ev["actual_outcome"]] = w.get(ev["actual_outcome"], 0) + 1
        if ev["actual_outcome"] not in ("unresolved", "relist_neutral"):
            # relist_neutral is excluded from resolved count — it's a market event
            w["resolved"] += 1
        if ev["predicted_confidence"] is not None:
            w["confidences"].append(ev["predicted_confidence"])
        if ev["outcome_score"]:
            w["outcome_scores"].append(ev["outcome_score"])
        if ev["calibration_error"] is not None:
            w["cal_errors"].append(ev["calibration_error"])
        if ev["overconfidence"] is not None:
            w["overconfs"].append(ev["overconfidence"])
        if ev["underconfidence"] is not None:
            w["underconfs"].append(ev["underconfidence"])
        if ev["r_multiple"] is not None:
            w["r_multiples"].append(ev["r_multiple"])

    results = []
    for agent, w in windows.items():
        resolved = w["resolved"]
        # A tier is earned on outcomes that can be right or wrong. `resolved` also counts
        # `neutral` (a hold, or a rejected proposal: no directional claim), so an agent
        # that only ever emitted `hold` reached 506 "resolved" with 0 correct and 0
        # incorrect and was promoted to proposal_allowed on 2026-11-01 — maria's window.
        graded = w["correct"] + w["incorrect"] + w.get("partially_correct", 0)
        w["graded"] = graded
        w["accuracy"] = round(w["correct"] / graded, 4) if graded > 0 else None
        w["avg_confidence"] = round(sum(w["confidences"]) / len(w["confidences"]), 4) if w["confidences"] else None
        w["calibration_error"] = round(sum(w["cal_errors"]) / len(w["cal_errors"]), 4) if w["cal_errors"] else None
        w["overconfidence_score"] = round(sum(w["overconfs"]) / len(w["overconfs"]), 4) if w["overconfs"] else None
        w["underconfidence_score"] = round(sum(w["underconfs"]) / len(w["underconfs"]), 4) if w["underconfs"] else None
        w["avg_outcome_score"] = round(sum(w["outcome_scores"]) / len(w["outcome_scores"]), 4) if w["outcome_scores"] else None
        w["avg_r_multiple"] = round(sum(w["r_multiples"]) / len(w["r_multiples"]), 4) if w["r_multiples"] else None
        w["low_sample_size"] = graded < AGENT_SAMPLE_INSIGHT
        if graded < AGENT_SAMPLE_INSIGHT:
            w["sample_size_status"] = "insight_only"
        elif graded < AGENT_SAMPLE_SHADOW:
            w["sample_size_status"] = "shadow_only"
        else:
            w["sample_size_status"] = "proposal_allowed"

        relist_note = f", {w.get('relist_neutral', 0)} relist-excluded" if w.get("relist_neutral", 0) > 0 else ""
        w["learning_summary"] = (f"{agent}: {resolved} resolved, {graded} graded{relist_note}, "
                                 f"acc={w['accuracy']}, cal_err={w['calibration_error']}")
        w["recommendation"] = "insufficient_data" if resolved < 10 else (
            "review_overconfidence" if (w["overconfidence_score"] or 0) > 0.3 else "maintain_current")

        # Remove temp lists
        for k in ("confidences", "outcome_scores", "cal_errors", "overconfs", "underconfs", "r_multiples"):
            del w[k]
        results.append(w)

    return results


def save_events(conn, events, dry_run=True):
    """Upsert on the natural-key id: a recommendation scored again updates its row.

    The DO UPDATE set is exactly the fields that can change between runs (an outcome resolves,
    a trade closes). ``created_at`` keeps the first time this pair was scored, and the key
    columns never move.
    """
    if dry_run:
        return
    cur = conn.cursor()
    for ev in events:
        cur.execute("""
            INSERT INTO agent_calibration_events
                (calibration_event_id, recommendation_id, agent_name, symbol, strategy_id,
                 outcome_type, scoring_window, predicted_action, predicted_confidence,
                 actual_outcome, outcome_score, pnl, r_multiple, calibration_error,
                 overconfidence, underconfidence, explanation)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (calibration_event_id) DO UPDATE SET
                agent_name=EXCLUDED.agent_name,
                symbol=EXCLUDED.symbol,
                strategy_id=EXCLUDED.strategy_id,
                outcome_type=EXCLUDED.outcome_type,
                predicted_action=EXCLUDED.predicted_action,
                predicted_confidence=EXCLUDED.predicted_confidence,
                actual_outcome=EXCLUDED.actual_outcome,
                outcome_score=EXCLUDED.outcome_score,
                pnl=EXCLUDED.pnl,
                r_multiple=EXCLUDED.r_multiple,
                calibration_error=EXCLUDED.calibration_error,
                overconfidence=EXCLUDED.overconfidence,
                underconfidence=EXCLUDED.underconfidence,
                explanation=EXCLUDED.explanation
        """, [ev["calibration_event_id"], ev["recommendation_id"], ev["agent_name"],
              ev["symbol"], ev.get("strategy_id"), ev.get("outcome_type"),
              ev["scoring_window"], ev["predicted_action"], ev.get("predicted_confidence"),
              ev["actual_outcome"], ev["outcome_score"], ev.get("pnl"), ev.get("r_multiple"),
              ev.get("calibration_error"), ev.get("overconfidence"), ev.get("underconfidence"),
              ev["explanation"]])
    conn.commit()


def save_windows(conn, windows, dry_run=True):
    """Upsert on the window's natural-key id.

    The old statement conflicted on ``(agent_name, window_start, window_end, domain,
    strategy_id)`` — a key that could never match: the bounds were rebuilt from ``now()`` on
    every run, and ``strategy_id`` was not in the column list at all, so it was NULL and a NULL
    is distinct from itself in a unique index. Every run therefore inserted a fresh copy of the
    window (25 per agent by 2026-11-08). The bounds are now day-aligned
    (``calibration_keys.day_bounds``) and the id is derived from them, so a second run on the
    same day updates the row instead of adding one; and the DO UPDATE set now covers every
    count it writes (``recommendations``/``incorrect``/``neutral`` used to keep week one's
    numbers forever).
    """
    if dry_run:
        return
    cur = conn.cursor()
    for w in windows:
        cur.execute("""
            INSERT INTO agent_calibration_windows
                (window_id, agent_name, window_start, window_end, domain, strategy_id,
                 recommendations, resolved, correct, incorrect, neutral,
                 partially_correct, unresolved, accuracy, avg_confidence,
                 calibration_error, overconfidence_score, underconfidence_score,
                 avg_outcome_score, avg_r_multiple, low_sample_size,
                 sample_size_status, learning_summary, recommendation)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (window_id) DO UPDATE SET
                agent_name=EXCLUDED.agent_name,
                window_start=EXCLUDED.window_start,
                window_end=EXCLUDED.window_end,
                domain=EXCLUDED.domain,
                strategy_id=EXCLUDED.strategy_id,
                recommendations=EXCLUDED.recommendations,
                resolved=EXCLUDED.resolved,
                correct=EXCLUDED.correct,
                incorrect=EXCLUDED.incorrect,
                neutral=EXCLUDED.neutral,
                partially_correct=EXCLUDED.partially_correct,
                unresolved=EXCLUDED.unresolved,
                accuracy=EXCLUDED.accuracy,
                avg_confidence=EXCLUDED.avg_confidence,
                calibration_error=EXCLUDED.calibration_error,
                overconfidence_score=EXCLUDED.overconfidence_score,
                underconfidence_score=EXCLUDED.underconfidence_score,
                avg_outcome_score=EXCLUDED.avg_outcome_score,
                avg_r_multiple=EXCLUDED.avg_r_multiple,
                low_sample_size=EXCLUDED.low_sample_size,
                sample_size_status=EXCLUDED.sample_size_status,
                learning_summary=EXCLUDED.learning_summary,
                recommendation=EXCLUDED.recommendation
        """, [w["window_id"], w["agent_name"], w["window_start"], w["window_end"],
              w.get("domain"), w.get("strategy_id"), w["recommendations"], w["resolved"],
              w["correct"], w["incorrect"], w["neutral"], w["partially_correct"],
              w["unresolved"], w.get("accuracy"), w.get("avg_confidence"),
              w.get("calibration_error"), w.get("overconfidence_score"),
              w.get("underconfidence_score"), w.get("avg_outcome_score"),
              w.get("avg_r_multiple"), w["low_sample_size"], w.get("sample_size_status"),
              w.get("learning_summary"), w.get("recommendation")])
    conn.commit()


def _receipt(**kw):
    """Real-run receipt (data/runtime/agent-calibration-engine_last.json, ok_at on success only)."""
    from lib.lane_last_receipt import write_lane_receipt

    kw.setdefault("exit_code", 0 if kw.get("ok") else 1)
    write_lane_receipt("agent-calibration-engine", script="agent_calibration_engine.py", **kw)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Agent Calibration Engine")
    parser.add_argument("--dry-run", action="store_true",
                        help="score and report; never write (wins over --apply)")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--agent", help="Filter by agent")
    parser.add_argument("--window", default=None,
                        help="Window (e.g. 30d, 90d); default from config")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    # --dry-run wins: a dispatcher passing both must never write (AGENTS.md §6).
    dry_run = args.dry_run or not args.apply
    config = load_config()
    window_days = int(args.window.replace("d", "")) if args.window else int(config["window_days"])
    started_at = _now_iso()
    conn = _get_conn()
    if dry_run:
        from lib.lane_last_receipt import enforce_readonly
        enforce_readonly(conn)  # dry run: the server refuses any write (AGENTS.md §6)
    try:
        events, stats = score_recommendations(conn, agent_filter=args.agent,
                                              window_days=window_days, config=config)
        windows = aggregate_windows(events, window_days=window_days)

        out = {
            "mode": "dry_run" if dry_run else "applied",
            "calibration_events": len(events),
            "events_capped": stats["capped"],
            "agent_windows": len(windows),
            "window_days": window_days,
            "read": {
                "eligible_recommendations": stats["eligible_recommendations"],
                "eligible_total": stats["eligible_total"],
                "rows_truncated": stats["rows_truncated"],
                "pages_read": stats["pages_read"],
                "page_rows": stats["page_rows"],
                "max_rows_per_run": stats["max_rows_per_run"],
                "config": stats.get("config_path"),
            },
            "agents": [{k: v for k, v in w.items() if k != "payload"} for w in windows],
            "low_sample_warning": all(w.get("low_sample_size", True) for w in windows),
        }
        if dry_run:
            out["would_write"] = {"agent_calibration_events": len(events),
                                  "agent_calibration_windows": len(windows)}
        else:
            save_events(conn, events, dry_run=False)
            save_windows(conn, windows, dry_run=False)
            _receipt(ok=True, started_at=started_at,
                     summary={"calibration_events": len(events), "agent_windows": len(windows),
                              "events_capped": out["events_capped"],
                              "eligible_recommendations": stats["eligible_recommendations"],
                              "eligible_total": stats["eligible_total"],
                              "rows_truncated": stats["rows_truncated"],
                              "pages_read": stats["pages_read"]})
        if args.json:
            print(json.dumps(out, indent=2, default=str))
        else:
            print(f"Calibration: {out['calibration_events']} events, {out['agent_windows']} windows "
                  f"({out['mode']}; {stats['eligible_recommendations']} eligible recommendations in "
                  f"{stats['pages_read']} page(s) of {stats['page_rows']})")
            if out["events_capped"]:
                print(f"  NOTE: stopped at max_rows_per_run={stats['max_rows_per_run']} "
                      f"rows_truncated={stats['rows_truncated']} of eligible_total={stats['eligible_total']} "
                      f"(config/agent_calibration_engine.json) — this run did NOT cover the eligible set")
            if out["low_sample_warning"]:
                print("  WARNING: All agents have low sample size")
        return 0
    except Exception as exc:
        if not dry_run:  # a failed real run leaves a failed receipt (ok_at kept), then exits non-zero
            _receipt(ok=False, started_at=started_at, error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        conn.close()


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    sys.exit(main())
