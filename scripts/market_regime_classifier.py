#!/usr/bin/env python3
"""market_regime_classifier.py — Classify current market regime from indicators.

Usage:
    .venv/bin/python scripts/market_regime_classifier.py --dry-run --json
    .venv/bin/python scripts/market_regime_classifier.py --apply --json
    .venv/bin/python scripts/market_regime_classifier.py --latest --json

Dry run is the default (no --apply). Refactor wave 1 (2026-10-10): an explicit --dry-run now WINS over
--apply (previously `--dry-run --apply` applied). An --apply run exits 1 when the snapshot write failed
and writes data/runtime/market-regime-classifier_last.json (LaneRunReceipt@v1; ok_at only when the
snapshot row was written) under the persistent-state root.
"""

import argparse, json, os, sys, uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")


def _f(v):
    return float(v) if isinstance(v, Decimal) else v


LANE_ID = "market-regime-classifier"
# confidence_floor, the Market Risk Engine inputs and their weights: config/market_regime_classifier.yaml
VIX_TO_VOL_STATE = {"extreme": "high_vol", "high": "high_vol", "normal": "neutral", "low": "low_vol"}


def _uid(p="RS_"):
    return f"{p}{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"


def _get_conn():
    from session13_db import get_conn

    return get_conn()


def classify(conn, snapshot_id=None, cfg=None):
    """Classify market regime from available indicators."""
    from lib.market_regime import mre_inputs

    cfg = cfg or mre_inputs.load_config()
    from market_session import current_market_session

    session = current_market_session()

    # Collect the indicators of ONE collector run. Until 2026-10-31 this read
    # `ORDER BY created_at DESC LIMIT 20` across runs and overwrote the dict key by key,
    # so the OLDEST of ~3 runs won every key: the 2026-10-30 16:05 snapshot recorded
    # `vix_close: normal` while the same-minute collector row said 21.3 `high`
    # (RCA docs/audits/MARKET_SELLOFF_ALERT_RCA_2026-10-30.md, DSN-20261031-market-risk-engine-P0-T1).
    cur = conn.cursor()
    if not snapshot_id:
        cur.execute("SELECT snapshot_id FROM market_regime_indicators ORDER BY created_at DESC LIMIT 1")
        row = cur.fetchone()
        snapshot_id = row[0] if row else None

    indicators = {}
    if snapshot_id:
        cur.execute(
            "SELECT indicator_key, signal, value, value_text FROM market_regime_indicators WHERE snapshot_id=%s",
            [snapshot_id],
        )
        for row in cur.fetchall():
            indicators[row[0]] = {"signal": row[1], "value": _f(row[2]), "text": row[3]}

    # Scoring model
    scores = {
        "risk_on_trend": 0,
        "risk_off": 0,
        "choppy_range": 0,
        "high_volatility": 0,
        "low_volatility_grind": 0,
        "broad_momentum": 0,
        "unknown": 0,
    }
    missing = []

    # "Breadth": scan_breadth_24h counts how many symbols the scanner touched in 24h. That is scan
    # activity, not market breadth (advancers, new highs/lows, % above a moving average), so it no
    # longer scores (P0-T1). Market breadth now comes from the Market Risk Engine (mre_breadth, below).
    breadth = indicators.get("scan_breadth_24h", {})

    # Scanner-population proxies are CONTEXT, not score (LQ-20261107-1613). `scan_score_avg` and
    # `gap_volatility_proxy` average `trade_ai_scans`: the symbols the scanner selected (gappers), not the
    # market. Once the broad scan runs stopped (after 2026-10-29) avg |gap| sat above 3.0 and avg score below 40
    # on every run by construction, adding +3 high_volatility and +2 risk_off every time, so the regime became a
    # two-state function of the VIX bucket. They stay in `inputs` for the record and no longer score.

    # VIX level: the canonical market volatility gauge.
    vix = indicators.get("vix_close", {})
    if vix.get("signal") == "extreme":
        scores["high_volatility"] += 4
        scores["risk_off"] += 2
    elif vix.get("signal") == "high":
        scores["high_volatility"] += 2
        scores["risk_off"] += 1
    elif vix.get("signal") == "low":
        scores["low_volatility_grind"] += 2
        scores["risk_on_trend"] += 1
    elif vix.get("signal") == "normal":
        scores["risk_on_trend"] += 1
    elif not vix:
        missing.append("no_vix_data")

    # VIX term structure (collected since LQ-969, unscored until LQ-1613). Contango is the resting state and
    # does not score; an inversion is stress: VIX/VIX3M > 1 (backwardation) is risk-off, VIX9D/VIX > 1 is a
    # short-dated volatility spike.
    vix3m_ratio = indicators.get("vix_vix3m_ratio", {})
    vix9d_ratio = indicators.get("vix9d_vix_ratio", {})
    if vix3m_ratio.get("signal") == "inverted":
        scores["risk_off"] += 2
        scores["high_volatility"] += 1
    if vix9d_ratio.get("signal") == "inverted":
        scores["high_volatility"] += 2
    partial = []
    if not vix3m_ratio and not vix9d_ratio:
        partial.append("no_term_structure")

    # VIX coherence guard: don't declare "high_volatility" off a term-structure kink alone while the fear gauge
    # itself is calm (low/normal) — that reads as a contradiction to the operator.
    if vix.get("signal") in ("low", "normal") and scores["high_volatility"] > 0:
        scores["high_volatility"] = max(0, scores["high_volatility"] - 3)
        if vix.get("signal") == "low":
            scores["low_volatility_grind"] += 1

    # Source health
    finviz = indicators.get("finviz_health", {})
    if finviz.get("signal") == "risk_off":
        scores["risk_off"] += 1
        missing.append("finviz_degraded")

    # Market-wide trend and breadth from the Market Risk Engine (LQ-1613 re-open): the collector records the
    # engine's technical and breadth observations; their states and points come from config. A stale, absent or
    # UNKNOWN observation scores nothing and is named in missing_data.
    mre_states, mre_gaps = mre_inputs.apply(indicators, scores, cfg)
    partial.extend(mre_gaps)

    # Session
    if session in ("weekend", "holiday", "closed"):
        scores["unknown"] += 2
        missing.append(f"market_{session}")

    # If too little data
    if len(indicators) < 3:
        scores["unknown"] += 5
        missing.append("insufficient_indicators")

    # Pick regime
    regime = max(scores, key=scores.get)
    ranked = sorted(scores.values(), reverse=True)
    # Confidence is the margin over the runner-up, over at least confidence_floor points of evidence: a near-tie
    # between two regimes is low confidence, and a single small score is not certainty (top/total read 0.62 for
    # a 5-vs-3 split and 1.0 for one point).
    confidence = round((ranked[0] - ranked[1]) / max(sum(ranked), cfg["confidence_floor"]), 2)
    stale = len(missing) > 2 or "insufficient_indicators" in missing
    missing.extend(partial)  # named, but a missing context leg does not make the snapshot stale

    # States. Volatility follows the VIX bucket; trend and breadth follow the engine's observations through the
    # config maps, and stay `not_measured` (never the scanner's own population) when there is none (LQ-1613).
    vol_state = VIX_TO_VOL_STATE.get(vix.get("signal"), "unknown")
    trend_state = mre_states.get("trend_state", "not_measured")
    breadth_state = mre_states.get("breadth_state", "not_measured")

    summary = f"Regime: {regime} (conf={confidence:.0%})"
    if missing:
        summary += f", missing: {', '.join(missing[:3])}"

    snapshot = {
        "snapshot_id": _uid(),
        "market_session": session,
        "regime_label": regime,
        "regime_score": scores[regime],
        "confidence": confidence,
        "volatility_state": vol_state,
        "trend_state": trend_state,
        "breadth_state": breadth_state,
        "liquidity_state": "unknown",
        "leadership_state": "unknown",
        "risk_appetite_state": trend_state,
        "macro_state": "unknown",
        "data_freshness_state": "stale" if stale else "fresh",
        "stale_data": stale,
        "missing_data": missing,
        "inputs": {**{k: v.get("signal") for k, v in indicators.items()}, "_indicator_snapshot_id": snapshot_id},
        "summary": summary,
    }
    return snapshot


def save_snapshot(conn, snapshot, dry_run=True):
    if dry_run:
        return False
    cur = conn.cursor()
    # Transaction health check (AGENT-WORKER-1 lesson)
    try:
        cur.execute("SELECT 1")
    except Exception:
        conn.rollback()
    try:
        cur.execute(
            """
            INSERT INTO market_regime_snapshots
                (snapshot_id, generated_at, market_session, regime_label, regime_score, confidence,
                 volatility_state, trend_state, breadth_state, liquidity_state,
                 leadership_state, risk_appetite_state, macro_state, data_freshness_state,
                 stale_data, missing_data, inputs, summary)
            VALUES (%s, NOW(), %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (snapshot_id) DO NOTHING
        """,
            [
                snapshot["snapshot_id"],
                snapshot["market_session"],
                snapshot["regime_label"],
                snapshot["regime_score"],
                snapshot["confidence"],
                snapshot["volatility_state"],
                snapshot["trend_state"],
                snapshot["breadth_state"],
                snapshot["liquidity_state"],
                snapshot["leadership_state"],
                snapshot["risk_appetite_state"],
                snapshot["macro_state"],
                snapshot["data_freshness_state"],
                snapshot["stale_data"],
                json.dumps(snapshot["missing_data"]),
                json.dumps(snapshot["inputs"]),
                snapshot["summary"],
            ],
        )
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(f"ERROR: snapshot write failed: {e}")
        return False


def _record_run_log(conn, run_id, mode, started_at, status, snapshot_id=None, indicators_read=0, error_msg=None):
    """Write to risk_regime_run_log."""
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1")  # transaction health check
    except Exception:
        conn.rollback()
        cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO risk_regime_run_log
                (run_id, mode, started_at, finished_at, status,
                 indicators_read, snapshots_created, rotation_signals_created,
                 alignments_created, errors, summary)
            VALUES (%s, %s, %s, NOW(), %s, %s, %s, 0, 0, %s, %s)
            ON CONFLICT (run_id) DO UPDATE SET
                finished_at=NOW(), status=EXCLUDED.status,
                indicators_read=EXCLUDED.indicators_read,
                snapshots_created=EXCLUDED.snapshots_created,
                errors=EXCLUDED.errors, summary=EXCLUDED.summary
        """,
            [
                run_id,
                mode,
                started_at,
                status,
                indicators_read,
                1 if status == "success" else 0,
                json.dumps([error_msg] if error_msg else []),
                json.dumps({"snapshot_id": snapshot_id, "status": status}),
            ],
        )
        conn.commit()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        print(f"WARNING: run_log write failed: {e}")


def _get_previous_regime(conn):
    """Get the most recent regime label before the current run."""
    cur = conn.cursor()
    cur.execute("SELECT regime_label FROM market_regime_snapshots ORDER BY created_at DESC LIMIT 1")
    row = cur.fetchone()
    return row[0] if row else None


RISK_OFF_LABELS = frozenset({"risk_off", "high_volatility"})  # the labels stop_policy.yaml treats as risk-off


def _alert_regime_change(old_regime, snapshot):
    """Notify the operator that the regime label changed.

    A change INTO a risk-off label is something the operator must act on (review stops and exposure),
    so it goes out as a P1 operator-action intent — delivered now, never quiet-held, dedupe window 0
    (AGENTS.md §9.1). Before 2026-10-31 every change was a P2 `dispatch_alert`, which the 22:00–07:00
    quiet window archived for a digest that showed it only as a count (P0-T2). Any other change keeps
    the P2 dispatcher path. Errors are returned, never swallowed; the caller records them in the run log.
    Returns {"path", "accepted", "error"}.
    """
    new = snapshot["regime_label"]
    try:
        vol = snapshot.get("volatility_state", "?")
        trend = snapshot.get("trend_state", "?")
        breadth = snapshot.get("breadth_state", "?")
        conf = snapshot.get("confidence", 0)
        vix_input = snapshot.get("inputs", {}).get("vix_close", "--")

        message = (
            f"*Market Regime Changed*\n\n"
            f"{old_regime} → *{new}* (conf={conf:.0%})\n\n"
            f"Volatility: {vol}\n"
            f"Trend: {trend}\n"
            f"Breadth: {breadth}\n"
            f"VIX signal: {vix_input}\n\n"
            f"Review open positions for regime alignment."
        )
        if new in RISK_OFF_LABELS:
            from telegram_alert import send_telegram

            accepted = send_telegram(
                message,
                priority="P1",
                dedupe_minutes=0,
                producer="market_regime_classifier",
                message_class="market_regime",
            )
            return {"path": "p1_intent", "accepted": bool(accepted), "error": None}
        from alert_dispatcher import dispatch_alert

        res = dispatch_alert(
            "regime_change",
            f"Regime: {old_regime} → {new}",
            message,
            tier="ALERT",
            source="market_regime_classifier",
            dedupe_scope="global",
        )
        return {"path": "dispatch_alert", "accepted": bool((res or {}).get("sent")), "error": None}
    except Exception as e:  # noqa: BLE001 — surfaced to the run log, never silent
        return {
            "path": "p1_intent" if new in RISK_OFF_LABELS else "dispatch_alert",
            "accepted": False,
            "error": f"{type(e).__name__}: {e}",
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Market Regime Classifier")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--latest", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output-json", type=str)
    parser.add_argument("--output-md", type=str)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    # An explicit --dry-run always wins: a preview must not be able to reach the write (AGENTS.md §6).
    dry_run = args.dry_run or not args.apply
    conn = _get_conn()
    try:
        if args.latest:
            cur = conn.cursor()
            cur.execute(
                "SELECT snapshot_id, regime_label, confidence, stale_data, summary FROM market_regime_snapshots ORDER BY created_at DESC LIMIT 1"
            )
            row = cur.fetchone()
            if row:
                out = {
                    "snapshot_id": row[0],
                    "regime": row[1],
                    "confidence": _f(row[2]),
                    "stale": row[3],
                    "summary": row[4],
                }
            else:
                out = {"message": "No regime snapshots yet"}
            print(json.dumps(out, indent=2, default=str) if args.json else str(out))
            return 0

        started_at = datetime.now(timezone.utc)
        run_id = _uid("RUN_")
        snapshot = classify(conn)

        write_ok = False
        alert_out = None
        if not dry_run:
            prev = _get_previous_regime(conn)
            write_ok = save_snapshot(conn, snapshot, dry_run=False)
            if write_ok and prev and prev != snapshot["regime_label"]:
                alert_out = _alert_regime_change(prev, snapshot) or None
                if alert_out and alert_out.get("error"):
                    print(
                        f"WARNING: regime change alert failed ({alert_out['path']}): {alert_out['error']}",
                        file=sys.stderr,
                    )
            err = None if write_ok else "snapshot write failed"
            if alert_out and alert_out.get("error"):
                err = (err + "; " if err else "") + f"regime_change alert: {alert_out['error']}"
            _record_run_log(
                conn,
                run_id,
                "apply",
                started_at,
                "success" if write_ok else "failed",
                snapshot_id=snapshot["snapshot_id"] if write_ok else None,
                indicators_read=len([k for k in snapshot.get("inputs", {}) if not k.startswith("_")]),
                error_msg=err,
            )

        out = {
            "mode": "dry_run" if dry_run else "applied",
            "write_ok": write_ok if not dry_run else None,
            "run_id": run_id,
            "regime_change_alert": alert_out,
            **snapshot,
        }

        if args.json or args.verbose:
            print(
                json.dumps(out, indent=2, default=str)
                if args.json
                else f"Regime: {snapshot['regime_label']} (conf={snapshot['confidence']:.0%}, stale={snapshot['stale_data']}, write={'OK' if write_ok else 'FAIL' if not dry_run else 'DRY'})"
            )
        else:
            print(
                f"Regime: {snapshot['regime_label']} (conf={snapshot['confidence']:.0%}, stale={snapshot['stale_data']})"
            )

        if args.output_json:
            Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output_json).write_text(json.dumps(out, indent=2, default=str))
        if args.output_md:
            Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
            md = [
                f"# Market Regime Classifier ({'DRY RUN' if dry_run else 'APPLY'})\n",
                f"- Regime: {snapshot['regime_label']}",
                f"- Confidence: {snapshot['confidence']:.0%}",
                f"- Stale: {snapshot['stale_data']}",
                f"- Snapshot ID: {snapshot['snapshot_id']}",
                f"- Write: {'OK' if write_ok else 'FAIL' if not dry_run else 'DRY RUN'}",
            ]
            if snapshot.get("missing_data"):
                md.append(f"- Missing: {', '.join(snapshot['missing_data'])}")
            Path(args.output_md).write_text("\n".join(md))
        if dry_run:
            print(
                f"DRY RUN: would insert market_regime_snapshots snapshot_id={snapshot['snapshot_id']} "
                f"regime={snapshot['regime_label']} + one risk_regime_run_log row; nothing written",
                file=sys.stderr if args.json else sys.stdout,
            )
            return 0
        rc = 0 if write_ok else 1
        from lib.lane_last_receipt import write_lane_receipt

        write_lane_receipt(
            LANE_ID,
            ok=write_ok,
            exit_code=rc,
            started_at=started_at,
            summary={
                "run_id": run_id,
                "snapshot_id": snapshot["snapshot_id"] if write_ok else None,
                "regime_label": snapshot["regime_label"],
                "confidence": snapshot["confidence"],
                "stale_data": snapshot["stale_data"],
            },
        )
        return rc
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
