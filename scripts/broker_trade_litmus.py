#!/usr/bin/env python3
"""broker_trade_litmus.py — operator facts check before live route.

Refreshes live quote, thesis band, live R:R, sizing gates, and cloud snapshot.
Advisory only — does not submit orders.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _q(sql, params=None, one=False):
    from db_adapter import _get_conn
    try:
        cur = _get_conn().cursor()
        cur.execute(sql, params or ())
        if one:
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception:
        return None if one else []


def _fetch_live_quote(symbol: str) -> dict:
    sym = str(symbol or "").upper()
    quote: dict = {}
    try:
        import schwab_transport as _st
        sq = _st.get_quotes([sym]) if sym else {}
        if sq.get("status") == "ok":
            q = (sq.get("quotes") or {}).get(sym) or {}
            bid, ask, last = q.get("bid"), q.get("ask"), q.get("last")
            spread_pct = None
            if bid is not None and ask is not None and float(bid) > 0:
                spread_pct = round((float(ask) - float(bid)) / float(bid) * 100, 3)
            quote = {"last": last, "bid": bid, "ask": ask, "spread_pct": spread_pct, "provider": "schwab"}
    except Exception:
        pass
    if not quote.get("last"):
        try:
            from market_quote_provider import get_best_quote
            q = get_best_quote(sym) or {}
            quote = {
                "last": q.get("last_price"), "bid": q.get("bid"), "ask": q.get("ask"),
                "spread_pct": q.get("spread_pct"), "provider": q.get("provider"),
            }
        except Exception:
            pass
    return quote


def _now_et() -> str:
    try:
        return datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M %Z")
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _cloud_lane_conflict(cloud: dict) -> dict | None:
    lanes = cloud.get("lanes") or {}
    verdicts = {}
    for lane, lr in lanes.items():
        if not isinstance(lr, dict) or not lr.get("ok"):
            continue
        v = str(lr.get("verdict") or "").upper()
        if v:
            verdicts[lane] = v
    if len(verdicts) < 2:
        return None
    vals = set(verdicts.values())
    if len(vals) <= 1:
        return None
    return {"lanes": verdicts, "note": "Grok and ChatGPT disagree — cloud reviewed static thesis, not live band"}


def run_litmus(proposal_id: int, *, account: str | None = None, refresh: bool = True) -> dict:
    """Full pre-route validation packet for operator."""
    row = _q(
        """SELECT id, symbol, strategy_id, origin, discovery_source, cio_view, sizing_basis,
                  COALESCE(target_account, proposed_account) AS account, intended_broker,
                  proposed_entry, proposed_stop, proposed_target1, proposed_shares, proposed_rr,
                  current_price, catalyst, catalyst_verified, status
           FROM paper_trade_proposals WHERE id=%s""",
        (proposal_id,), one=True,
    )
    if not row:
        return {"ok": False, "error": f"proposal #{proposal_id} not found"}

    sym = str(row.get("symbol") or "").upper()
    acct = (account or row.get("account") or "").strip()
    quote: dict = {}
    if refresh:
        quote = _fetch_live_quote(sym) or {}
        last = quote.get("last")
        drift_pct = None
        if last is not None and row.get("proposed_entry"):
            try:
                drift_pct = round((float(last) - float(row["proposed_entry"])) / float(row["proposed_entry"]) * 100, 2)
            except Exception:
                pass
        if last is not None:
            try:
                _q(
                    """UPDATE paper_trade_proposals
                       SET current_price=%s, price_drift_pct=%s, updated_at=NOW()
                       WHERE id=%s""",
                    [last, drift_pct, proposal_id],
                )
            except Exception:
                pass
            row["current_price"] = last
            row["price_drift_pct"] = drift_pct
            row["refreshed_at"] = datetime.now(timezone.utc).isoformat()[:19]
            row["quote_provider"] = quote.get("provider") or row.get("intended_broker") or ""

    entry = float(row.get("proposed_entry") or 0)
    stop = float(row.get("proposed_stop") or 0)
    target = float(row.get("proposed_target1") or 0)
    shares = int(row.get("proposed_shares") or 0)
    strat = str(row.get("strategy_id") or "momentum_scalp")
    live = float(row.get("current_price") or quote.get("last") or 0) or None

    from broker_thesis_validity import attach_thesis_validity, assess_price_freshness
    work = dict(row)
    if live:
        work["current_price"] = live
    if quote.get("provider"):
        work["quote_provider"] = quote.get("provider")
        work["refreshed_at"] = work.get("refreshed_at") or datetime.now(timezone.utc).isoformat()[:19]
    attach_thesis_validity(work)
    tv = work.get("thesis_validity") or {}
    fresh = assess_price_freshness(work, live_quote=bool(quote.get("last")))

    evaluation = {}
    sizing = {}
    try:
        import broker_promote_sizing as bps
        qd = {}
        if live:
            qd = {"last_price": live, "bid": quote.get("bid"), "ask": quote.get("ask")}
        if acct and entry and stop:
            sizing = bps.compute_broker_sizing(acct, strat, entry, stop) or {}
            evaluation = bps.evaluate_broker_promote(
                acct, strat, entry, stop, target, int(shares or 0), quote=qd,
                operator_route=True,
            ) or {}
    except Exception:
        pass

    oversight = {}
    try:
        import broker_promote_oversight as bpo
        oversight = bpo.evaluate_oversight(proposal_id) or {}
        if evaluation:
            evaluation = bpo.merge_evaluation_with_oversight(evaluation, oversight)
    except Exception:
        pass

    cloud = oversight.get("cloud_review") or {}
    cloud_conflict = _cloud_lane_conflict(cloud)
    zone = str(tv.get("zone_status") or "unknown")
    live_rr = tv.get("current_rr")
    planned_rr = tv.get("planned_rr") or row.get("proposed_rr")
    min_rr = float(tv.get("min_rr") or 2.0)
    gate = evaluation.get("status") or oversight.get("status")
    actionable = bool(tv.get("actionable"))
    price_stale = bool(fresh.get("price_stale"))

    facts: list[str] = []
    ts = _now_et()
    if live:
        facts.append(
            f"Live ${live:.2f} · {ts}"
            + (f" · {work.get('quote_provider')}" if work.get("quote_provider") else "")
        )
    else:
        facts.append(f"No live quote at {ts} — refresh failed or market closed")

    if not price_stale and live:
        facts.append("Quote fresh for live R:R math")
    elif price_stale:
        facts.append(f"Price stale ({fresh.get('price_age_min', '?')}m old) — live R:R unreliable")

    if zone == "comfortable":
        facts.append(f"Thesis band comfortable · live R:R {live_rr or '—'}:1 (min {min_rr:.1f})")
    elif zone == "approaching":
        facts.append(f"Thesis approaching edge · live R:R {live_rr or '—'}:1 — {(tv.get('reasons') or ['check band'])[0]}")
    elif zone in ("at_risk", "invalid"):
        facts.append(f"Thesis {zone} · {(tv.get('reasons') or ['outside valid band'])[0]}")
    else:
        facts.append("Thesis band unknown — refresh prices")

    if planned_rr is not None:
        facts.append(f"Planned R:R {planned_rr}:1 · drift {row.get('price_drift_pct', tv.get('drift_pct', '—'))}% from entry")

    max_sh = evaluation.get("max_shares") or sizing.get("shares")
    if shares and max_sh is not None:
        facts.append(f"Queued {shares} sh · cap {int(max_sh)} sh · risk ${evaluation.get('dollar_risk', '—')}")
    for v in (evaluation.get("violations") or [])[:4]:
        facts.append(f"Gate block: {v}")
    for w in (evaluation.get("warnings") or [])[:2]:
        if "cloud" in str(w).lower():
            facts.append(f"Gate warn: {w}")

    cloud_st = str(cloud.get("status") or "not_run").lower()
    ran = cloud.get("ran_at") or ""
    if cloud_st == "not_run":
        facts.append("Cloud Grok+ChatGPT: not run — validates static thesis only when you run it")
    elif cloud_st == "running":
        facts.append("Cloud Grok+ChatGPT: running…")
    else:
        lane_txt = ""
        if cloud.get("lanes"):
            parts = []
            for lane, lr in (cloud.get("lanes") or {}).items():
                if isinstance(lr, dict) and lr.get("ok"):
                    parts.append(f"{lane} {lr.get('verdict', '?')}")
            if parts:
                lane_txt = f" ({', '.join(parts)})"
        facts.append(f"Cloud consensus {cloud_st.upper()}{lane_txt}" + (f" · ran {ran}" if ran else ""))
        if cloud_conflict:
            facts.append(
                "Cloud lane conflict: "
                + ", ".join(f"{k}={v}" for k, v in cloud_conflict["lanes"].items())
                + " — re-run after Validate so models see live price"
            )
        elif cloud_st in ("caution", "disagree") and zone in ("comfortable", "approaching"):
            facts.append(
                "Cloud vs live band mismatch likely — cloud reviewed thesis without current live price/date context"
            )

    still_good = True
    blockers: list[str] = []
    if price_stale or not live:
        still_good = False
        blockers.append("stale or missing live price")
    if zone in ("at_risk", "invalid"):
        still_good = False
        blockers.append(f"thesis zone {zone}")
    if live_rr is not None and float(live_rr) < min_rr:
        still_good = False
        blockers.append(f"live R:R {live_rr:.1f} below {min_rr:.1f}")
    if gate == "BLOCK":
        still_good = False
        blockers.append("risk/oversight gate BLOCK")
    if row.get("status") not in ("PENDING", "APPROVED_FOR_PAPER_TEST"):
        still_good = False
        blockers.append(f"status {row.get('status')}")

    verdict = "GO" if still_good and actionable else ("CAUTION" if still_good else "NO-GO")

    return {
        "ok": True,
        "proposal_id": proposal_id,
        "symbol": sym,
        "validated_at": ts,
        "validated_at_utc": datetime.now(timezone.utc).isoformat()[:19],
        "verdict": verdict,
        "trade_still_good": still_good,
        "blockers": blockers,
        "facts": facts,
        "live_price": live,
        "live_rr": live_rr,
        "planned_rr": planned_rr,
        "drift_pct": row.get("price_drift_pct") or tv.get("drift_pct"),
        "thesis_validity": tv,
        "price_freshness": fresh,
        "gate_status": gate,
        "actionable": actionable,
        "cloud_review": cloud,
        "cloud_conflict": cloud_conflict,
        "oversight": oversight,
        "evaluation": {
            "status": evaluation.get("status"),
            "max_shares": evaluation.get("max_shares"),
            "recommended_shares": evaluation.get("recommended_shares"),
            "violations": evaluation.get("violations") or [],
            "warnings": evaluation.get("warnings") or [],
            "oversight": oversight,
        },
        "oversight_status": oversight.get("status"),
        "quote": quote,
    }


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("proposal_id", type=int)
    p.add_argument("--account", default="")
    p.add_argument("--no-refresh", action="store_true")
    args = p.parse_args()
    print(json.dumps(
        run_litmus(args.proposal_id, account=args.account or None, refresh=not args.no_refresh),
        indent=2,
        default=str,
    ))