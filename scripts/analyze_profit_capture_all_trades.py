#!/usr/bin/env python3
"""Phase 206 — Canonical all-trades profit-capture analyzer (ADVISORY / ANALYTICS ONLY).

Upgrades the paper-only, open-trade-only protection model to the canonical
`trade_instances` all-trades model. For every CLOSED trade instance (Alpaca paper +
imported Schwab/Fidelity), it computes max-favorable profit, captured profit, money
left on the table, give-back %, capture ratio, and classifies the protection failure.

Safety:
  * READ-ONLY on the broker. No order/stop/proposal/GO-WAIT/strategy mutation.
  * Writes ONLY `trade_profit_capture_analysis` (and only with --apply).
  * NEVER fabricates MFE — trades without bar-based MFE are flagged DATA_INCOMPLETE,
    measurable=false, give-back unknown. No hallucinated numbers.

Definitions (per spec):
  max_profit_usd       = max favorable open profit during the hold
  captured_profit_usd  = realized profit for winners
  money_left_usd       = max_profit_usd - captured_profit_usd
  giveback_pct_of_mfe  = money_left_usd / max_profit_usd
  capture_ratio        = captured_profit_usd / max_profit_usd
  protection_needed    = winner AND max_profit_usd > MIN AND giveback_pct_of_mfe > GIVEBACK
  protection_missed    = protection_needed AND no advisory existed before/near MFE

Usage:
  python3 scripts/analyze_profit_capture_all_trades.py --json out.json --markdown out.md     # dry-run
  python3 scripts/analyze_profit_capture_all_trades.py --apply --json a.json --markdown a.md  # write
"""
import os, sys, json, argparse
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Protection thresholds (documented in V3_PROTECTION_PROFIT_CAPTURE_ENHANCEMENT_20260606.md)
MIN_PROTECT_PROFIT_USD = 50.0   # max favorable profit below this is not worth protecting
GIVEBACK_PCT_THRESHOLD = 0.30   # gave back >30% of the favorable peak -> protectable miss


def load_env():
    for line in open(os.path.join(ROOT, ".env")):
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v.strip().strip('"').strip("'"))


def db():
    import psycopg2
    return psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ.get("DB_PORT", "5432"),
                            dbname=os.environ["DB_NAME"], user=os.environ["DB_USER"],
                            password=os.environ["DB_PASSWORD"])


def f(x):
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def r2(x):
    return round(x, 2) if x is not None else None


QUERY = """
SELECT ti.id ti_id, ti.source_system, ti.source_table, ti.source_trade_id, ti.symbol,
       ti.execution_account, ti.execution_broker, ti.execution_environment, ti.strategy_id,
       ti.side, ti.entry_time, ti.exit_time, ti.entry_price, ti.exit_price, ti.shares,
       ti.pnl, ti.pnl_pct, ti.r_multiple, ti.status,
       m.mfe_price, m.mfe_r, m.mae_r, m.money_left, m.mfe_time, m.capture_ratio mfe_capture_ratio,
       pt.planned_stop, pt.stop_loss, pt.take_profit_price, pt.exit_reason, pt.close_reason,
       a.tradeai_action adv_action, a.adv_created, a.operator_action_required,
       o.operator_decision, o.adjustment_applied
FROM trade_instances ti
LEFT JOIN trade_mfe_analysis m
       ON ti.source_table = 'paper_trades' AND ti.source_trade_id ~ '^[0-9]+$'
      AND m.trade_id = ti.source_trade_id::int
LEFT JOIN paper_trades pt
       ON ti.source_table = 'paper_trades' AND ti.source_trade_id ~ '^[0-9]+$'
      AND pt.id = ti.source_trade_id::int
LEFT JOIN LATERAL (
       SELECT tradeai_action, created_at AS adv_created, operator_action_required
       FROM atm_profit_protection_advisories ap
       WHERE ti.source_table = 'paper_trades' AND ti.source_trade_id ~ '^[0-9]+$'
         AND ap.paper_trade_id = ti.source_trade_id::int
       ORDER BY created_at DESC LIMIT 1
) a ON true
LEFT JOIN protection_advisory_outcomes o
       ON ti.source_table = 'paper_trades' AND ti.source_trade_id ~ '^[0-9]+$'
      AND o.trade_id = ti.source_trade_id::int
WHERE ti.exit_time IS NOT NULL
ORDER BY ti.id
"""


def analyze_row(d):
    entry = f(d["entry_price"]); exitp = f(d["exit_price"]); shares = f(d["shares"])
    realized_pnl = f(d["pnl"])
    pnl_pct = f(d["pnl_pct"])
    realized_r = f(d["r_multiple"])
    mfe_price = f(d["mfe_price"]); mfe_r = f(d["mfe_r"]); mae_r = f(d["mae_r"])
    money_left_src = f(d["money_left"])
    side = (d["side"] or "long").lower()
    winner = realized_pnl is not None and realized_pnl > 0

    has_bar = mfe_price is not None
    measurable = has_bar

    # max favorable open profit
    max_profit_usd = None
    if has_bar and entry and shares:
        if side == "short":
            max_profit_usd = (entry - mfe_price) * shares
        else:
            max_profit_usd = (mfe_price - entry) * shares
        max_profit_usd = max(0.0, max_profit_usd)

    captured_profit_usd = realized_pnl if winner else None

    # money_left: prefer bar-based authoritative $; else derive from max_profit - captured
    if money_left_src is not None:
        money_left_usd = max(0.0, money_left_src)
    elif max_profit_usd is not None and captured_profit_usd is not None:
        money_left_usd = max(0.0, max_profit_usd - captured_profit_usd)
    else:
        money_left_usd = None

    # if max_profit missing but we have money_left + captured, reconstruct
    if max_profit_usd is None and money_left_usd is not None and captured_profit_usd is not None:
        max_profit_usd = captured_profit_usd + money_left_usd

    giveback_usd = money_left_usd
    giveback_pct = None
    if max_profit_usd and max_profit_usd > 0 and money_left_usd is not None:
        giveback_pct = round(money_left_usd / max_profit_usd, 4)
    capture_ratio = None
    if max_profit_usd and max_profit_usd > 0 and captured_profit_usd is not None:
        capture_ratio = round(max(0.0, min(1.0, captured_profit_usd / max_profit_usd)), 4)
    elif f(d["mfe_capture_ratio"]) is not None:
        capture_ratio = f(d["mfe_capture_ratio"])

    mfe_pct = None
    if mfe_price and entry:
        mfe_pct = round((mfe_price - entry) / entry * 100.0, 4)

    advisory_existed = d["adv_action"] is not None
    adv_created = d["adv_created"]
    mfe_time = d["mfe_time"]
    advisory_too_late = bool(advisory_existed and adv_created and mfe_time and adv_created > mfe_time)
    operator_acted = bool(d["adjustment_applied"]) or (d["operator_decision"] == "accepted")
    operator_decision = d["operator_decision"] or ("accepted" if operator_acted else "none")

    protection_needed = bool(
        winner and measurable and max_profit_usd is not None
        and max_profit_usd > MIN_PROTECT_PROFIT_USD
        and giveback_pct is not None and giveback_pct > GIVEBACK_PCT_THRESHOLD
    )
    protection_missed = bool(protection_needed and (not advisory_existed or advisory_too_late))

    # failure classification
    take_profit = f(d["take_profit_price"])
    if not winner:
        fclass, freason = "NOT_PROTECTABLE", "Not a winning trade — no profit to give back."
    elif not measurable:
        fclass, freason = "DATA_INCOMPLETE", "No bar-based MFE/MAE — give-back not measurable (honest unknown)."
    elif max_profit_usd is None or max_profit_usd <= MIN_PROTECT_PROFIT_USD:
        fclass, freason = "NOT_PROTECTABLE", f"Max favorable profit <= ${MIN_PROTECT_PROFIT_USD:.0f} threshold."
    elif giveback_pct is None or giveback_pct <= GIVEBACK_PCT_THRESHOLD:
        fclass, freason = "NOT_PROTECTABLE", f"Give-back <= {GIVEBACK_PCT_THRESHOLD*100:.0f}% of peak — well captured."
    elif not advisory_existed:
        fclass, freason = "NO_ADVISORY_GENERATED", ("Protectable winner but no advisory was ever generated "
                                                    "(paper-only engine, open-trade-only scope, or closed before engine).")
    elif advisory_too_late:
        fclass, freason = "ADVISORY_TOO_LATE", "Advisory was generated after the favorable peak — most give-back already happened."
    elif not operator_acted:
        fclass, freason = "ADVISORY_IGNORED", "Advisory existed and urged protection but operator took no stop/TP action."
    elif take_profit is None:
        fclass, freason = "NO_TAKE_PROFIT", "Advisory acted on but no take-profit existed — gain still given back."
    else:
        fclass, freason = "STOP_NOT_MOVED", "Protection existed but stop/TP did not move enough to capture the peak."

    if has_bar:
        data_quality = "bar_mfe"
    elif winner:
        data_quality = "no_bars"
    else:
        data_quality = "ok"

    notes = {
        "money_left_source": "bar_analysis" if money_left_src is not None else
                             ("derived" if money_left_usd is not None else "none"),
        "has_paper_metadata": d["planned_stop"] is not None or d["stop_loss"] is not None,
        "has_strategy_id": bool(d["strategy_id"]),
        "side": side,
        "advisory_too_late": advisory_too_late,
        "exit_reason": d["exit_reason"] or d["close_reason"],
    }

    return {
        "trade_instance_id": d["ti_id"],
        "source_system": d["source_system"], "source_table": d["source_table"],
        "source_trade_id": str(d["source_trade_id"]), "symbol": d["symbol"],
        "execution_account": d["execution_account"], "execution_broker": d["execution_broker"],
        "execution_environment": d["execution_environment"], "strategy_id": d["strategy_id"],
        "entry_time": d["entry_time"], "exit_time": d["exit_time"],
        "entry_price": entry, "exit_price": exitp, "shares": shares,
        "realized_pnl": r2(realized_pnl), "realized_pnl_pct": pnl_pct, "realized_r": realized_r,
        "mfe_price": mfe_price, "mfe_pct": mfe_pct, "mfe_r": mfe_r, "mae_pct": mae_r,
        "max_profit_usd": r2(max_profit_usd), "captured_profit_usd": r2(captured_profit_usd),
        "money_left_usd": r2(money_left_usd), "giveback_usd": r2(giveback_usd),
        "giveback_pct_of_mfe": giveback_pct, "capture_ratio": capture_ratio,
        "winner": winner, "measurable": measurable,
        "protection_needed": protection_needed, "protection_missed": protection_missed,
        "advisory_existed": advisory_existed, "advisory_action": d["adv_action"],
        "advisory_created_at": adv_created, "operator_acted": operator_acted,
        "operator_decision": operator_decision,
        "failure_class": fclass, "failure_reason": freason,
        "data_quality": data_quality, "data_quality_notes": notes,
    }


def aggregate(rows):
    from collections import Counter, defaultdict
    winners = [r for r in rows if r["winner"]]
    meas_win = [r for r in winners if r["measurable"]]
    gb = [r for r in meas_win if (r["money_left_usd"] or 0) > 0]
    missed = [r for r in rows if r["protection_missed"]]
    adv = [r for r in winners if r["advisory_existed"]]
    acted = [r for r in winners if r["operator_acted"]]
    money_by_strat, money_by_src = defaultdict(float), defaultdict(float)
    for r in gb:
        money_by_strat[r["strategy_id"] or "unknown"] += (r["money_left_usd"] or 0)
        money_by_src[r["source_system"]] += (r["money_left_usd"] or 0)
    return {
        "total_closed_trades": len(rows),
        "measurable_closed_trades": sum(1 for r in rows if r["measurable"]),
        "winners": len(winners),
        "winners_with_mfe": len(meas_win),
        "winners_with_giveback": len(gb),
        "winners_protection_missed": len(missed),
        "winners_advisory_existed": len(adv),
        "winners_operator_acted": len(acted),
        "money_left_total": r2(sum(r["money_left_usd"] or 0 for r in gb)),
        "money_left_by_strategy": {k: r2(v) for k, v in sorted(money_by_strat.items(), key=lambda x: -x[1])},
        "money_left_by_source_system": {k: r2(v) for k, v in sorted(money_by_src.items(), key=lambda x: -x[1])},
        "failure_class_breakdown": dict(Counter(r["failure_class"] for r in rows)),
        "data_quality_breakdown": dict(Counter(r["data_quality"] for r in rows)),
        "by_source_system": dict(Counter(r["source_system"] for r in rows)),
    }


def to_markdown(agg, rows):
    L = ["# Profit-Capture All-Trades Analysis", "",
         f"Generated: {datetime.now(timezone.utc).isoformat()}", "",
         "**Advisory / analytics only. No broker, order, stop, proposal, GO/WAIT or strategy changes.**", "",
         "## Summary", ""]
    for k in ["total_closed_trades", "measurable_closed_trades", "winners", "winners_with_mfe",
              "winners_with_giveback", "winners_protection_missed", "winners_advisory_existed",
              "winners_operator_acted", "money_left_total"]:
        L.append(f"- **{k}**: {agg[k]}")
    L += ["", "## Money left by strategy", ""]
    for k, v in agg["money_left_by_strategy"].items():
        L.append(f"- {k}: ${v}")
    L += ["", "## Money left by source system", ""]
    for k, v in agg["money_left_by_source_system"].items():
        L.append(f"- {k}: ${v}")
    L += ["", "## Failure-class breakdown", ""]
    for k, v in sorted(agg["failure_class_breakdown"].items(), key=lambda x: -x[1]):
        L.append(f"- {k}: {v}")
    L += ["", "## Data-quality breakdown", ""]
    for k, v in agg["data_quality_breakdown"].items():
        L.append(f"- {k}: {v}")
    L += ["", "## Protectable winners that missed protection", "",
          "| sym | source | strat | realized | max$ | giveback$ | gb% | advisory | failure |",
          "|-----|--------|-------|----------|------|-----------|-----|----------|---------|"]
    for r in sorted([x for x in rows if x["protection_missed"]], key=lambda x: -(x["money_left_usd"] or 0)):
        L.append("| {symbol} | {source_system} | {strategy_id} | {realized_pnl} | {max_profit_usd} | "
                 "{money_left_usd} | {gp} | {advisory_existed} | {failure_class} |".format(
                     gp=round((r["giveback_pct_of_mfe"] or 0)*100, 1), **r))
    return "\n".join(L) + "\n"


def run(apply, json_path, md_path):
    load_env()
    import psycopg2.extras
    conn = db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(QUERY)
    raw = cur.fetchall()
    rows = [analyze_row(dict(d)) for d in raw]
    agg = aggregate(rows)

    written = 0
    if apply:
        wc = conn.cursor()
        cols = ["trade_instance_id", "source_system", "source_table", "source_trade_id", "symbol",
                "execution_account", "execution_broker", "execution_environment", "strategy_id",
                "entry_time", "exit_time", "entry_price", "exit_price", "shares",
                "realized_pnl", "realized_pnl_pct", "realized_r",
                "mfe_price", "mfe_pct", "mfe_r", "mae_pct", "max_profit_usd", "captured_profit_usd",
                "money_left_usd", "giveback_usd", "giveback_pct_of_mfe", "capture_ratio",
                "winner", "measurable", "protection_needed", "protection_missed", "advisory_existed",
                "advisory_action", "advisory_created_at", "operator_acted", "operator_decision",
                "failure_class", "failure_reason", "data_quality", "data_quality_notes"]
        for r in rows:
            vals = dict(r)
            vals["data_quality_notes"] = json.dumps(r["data_quality_notes"], default=str)
            wc.execute(f"""INSERT INTO trade_profit_capture_analysis ({','.join(cols)})
                VALUES ({','.join('%('+c+')s' for c in cols)})
                ON CONFLICT (trade_instance_id) DO UPDATE SET
                {','.join(f'{c}=excluded.{c}' for c in cols if c!='trade_instance_id')}, updated_at=now()""", vals)
            written += 1
        conn.commit()
    conn.close()

    report = {"run_at": datetime.now(timezone.utc).isoformat(), "applied": apply,
              "written": written, "thresholds": {"min_protect_profit_usd": MIN_PROTECT_PROFIT_USD,
              "giveback_pct_threshold": GIVEBACK_PCT_THRESHOLD}, "metrics": agg}
    if json_path:
        json.dump(report, open(json_path, "w"), indent=2, default=str)
    if md_path:
        open(md_path, "w").write(to_markdown(agg, rows))
    print(json.dumps(report, indent=2, default=str))
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write to trade_profit_capture_analysis")
    ap.add_argument("--json", default=None)
    ap.add_argument("--markdown", default=None)
    a = ap.parse_args()
    run(a.apply, a.json, a.markdown)
