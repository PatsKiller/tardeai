#!/usr/bin/env python3
"""CIO entry state runner — evaluate tracked names, record the CIO's call, alert the operator and the CIO.

Operator decisions 2026-09-15: the CIO owns the entry / BUY state; the operator is alerted and the CIO
is alerted; small caps are in scope and labeled. Deterministic, no model calls, advisory only — it
never sizes, orders, sets stops or touches a broker.

Tracked names = active watchlist items ∪ re-entry desk rows ∪ pending proposals. For each name the
freshest plan wins: re-entry desk row (live price, zone, stop, target, wash window) → latest
watchlist_entry_plans row within 7 days → strategy card levels.

Default is a dry run (prints the would-be states and messages). --apply:
  * appends a cio_entry_states row whenever a symbol's state changes;
  * writes a cio_decisions row (action BUY_READY / ENTRY_NEAR, action_class 'entry') on entry into
    an actionable state, at most once per symbol, state and day;
  * sends the operator alert (routes IMMEDIATE as cio_entry_state) and the CIO desk message, and
    emits watch.new_signal on the CIO event bus so the CIO wakes on it;
  * writes data/runtime/cio_entry_state_last_run.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT))

from lib import cio_entry_state as ces  # noqa: E402
from lib.market_cap_label import cap_label  # noqa: E402

STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
DESK_PATH = PROJECT_ROOT / "data" / "runtime" / "reentry_decision_desk_latest.json"
RECEIPT = PROJECT_ROOT / "data" / "runtime" / "cio_entry_state_last_run.json"
MAX_ALERTS_PER_RUN = 8

DDL = """CREATE TABLE IF NOT EXISTS cio_entry_states (
    id bigserial PRIMARY KEY,
    symbol text NOT NULL,
    state text NOT NULL,
    prior_state text,
    evaluated_at timestamptz NOT NULL DEFAULT now(),
    alerted boolean NOT NULL DEFAULT false,
    details jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_cio_entry_states_symbol_time ON cio_entry_states (symbol, evaluated_at DESC);"""


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def gather(cur) -> dict[str, dict]:
    """symbol → evidence dict for cio_entry_state.evaluate."""
    ev: dict[str, dict] = {}
    desk = _load_json(DESK_PATH, {})
    for r in desk.get("rows") or []:
        sym = str(r.get("symbol") or "").upper()
        if not sym:
            continue
        ev[sym] = {"symbol": sym, "price": r.get("price"), "quote_age_h": r.get("price_age_h"),
                   "entry_low": r.get("entry_low"), "entry_high": r.get("entry_high"), "stop": r.get("stop"),
                   "target": r.get("target"), "atr": r.get("atr"), "wash_blocked": r.get("wash_blocked"),
                   "held": r.get("held"), "earnings_date": r.get("earnings_date"), "rsi": r.get("rsi"),
                   "catalyst": (r.get("catalyst") or {}).get("headline") if isinstance(r.get("catalyst"), dict) else None,
                   "plan_source": "reentry_desk"}
    cur.execute("""SELECT upper(symbol) s FROM watchlist_items WHERE status='active'
                   UNION SELECT upper(symbol) FROM paper_trade_proposals WHERE status='PENDING'""")
    tracked = {row[0] for row in cur.fetchall()} | set(ev)
    syms = sorted(tracked)
    cur.execute("""SELECT DISTINCT ON (upper(symbol)) upper(symbol), entry_zone_low, entry_zone_high, stop_price,
                          target_price, created_at
                     FROM watchlist_entry_plans
                    WHERE upper(symbol) = ANY(%s) AND created_at > now() - interval '7 days'
                    ORDER BY upper(symbol), created_at DESC""", (syms,))
    plans = {row[0]: row[1:] for row in cur.fetchall()}
    cur.execute("""SELECT DISTINCT ON (upper(symbol)) upper(symbol), price,
                          EXTRACT(EPOCH FROM (now() - last_enriched_at)) / 3600.0
                     FROM watchlist_items WHERE upper(symbol) = ANY(%s) AND price IS NOT NULL
                    ORDER BY upper(symbol), last_enriched_at DESC NULLS LAST""", (syms,))
    quotes = {row[0]: row[1:] for row in cur.fetchall()}
    cur.execute("""SELECT DISTINCT ON (upper(symbol)) upper(symbol), ideal_entry, add_zone_low, add_zone_high,
                          stop_loss, target_price, catalyst_summary
                     FROM watchlist_strategy_cards WHERE upper(symbol) = ANY(%s)
                    ORDER BY upper(symbol), updated_at DESC NULLS LAST""", (syms,))
    cards = {row[0]: row[1:] for row in cur.fetchall()}
    cur.execute("""SELECT DISTINCT ON (upper(symbol)) upper(symbol), action FROM cio_decisions
                    WHERE upper(symbol) = ANY(%s) AND action_class <> 'entry'
                    ORDER BY upper(symbol), created_at DESC""", (syms,))
    cio = {row[0]: row[1] for row in cur.fetchall()}
    # Identity. The alert used to name a bare ticker and a market-cap pill, so the
    # operator was asked to act on "ESE" with no idea it is Esco Technologies, a
    # Technology / Scientific & Technical Instruments name. symbol_profiles already
    # carries all three and was simply never read here.
    cur.execute("""SELECT DISTINCT ON (upper(symbol)) upper(symbol), description_1s, sector, industry
                     FROM symbol_profiles WHERE upper(symbol) = ANY(%s)
                    ORDER BY upper(symbol), updated_at DESC NULLS LAST""", (syms,))
    profiles = {row[0]: row[1:] for row in cur.fetchall()}
    cur.execute("""SELECT upper(symbol), packet FROM decision_packets
                    WHERE superseded_by IS NULL AND upper(symbol) = ANY(%s)""", (syms,))
    packets = {row[0]: row[1] or {} for row in cur.fetchall()}
    enrichment = _load_json(STATE_DIR / "ticker_enrichment_cache.json", {})
    holdings = _load_json(STATE_DIR / "holdings.json", {})
    held = {str(h.get("symbol") or "").upper() for h in holdings.get("holdings") or [] if not h.get("is_cash")}
    try:
        import watch_packet_quality as pq
    except Exception:
        pq = None
    from lib.finviz_csv import enrichment_market_cap_billions

    for sym in syms:
        e = ev.setdefault(sym, {"symbol": sym, "plan_source": None})
        if e.get("plan_source") is None:
            if sym in plans and (plans[sym][0] is not None or plans[sym][1] is not None):
                lo, hi, st, tg, _ = plans[sym]
                e.update(entry_low=lo, entry_high=hi, stop=st, target=tg, plan_source="entry_plan")
            elif sym in cards and cards[sym][0] is not None:
                ideal, zl, zh, st, tg, _ = cards[sym]
                e.update(entry_low=zl or ideal, entry_high=zh or ideal, stop=st, target=tg, plan_source="strategy_card")
        if e.get("price") is None and sym in quotes:
            e["price"], e["quote_age_h"] = quotes[sym]
        if not e.get("catalyst") and sym in cards:
            e["catalyst"] = cards[sym][5]
        e["cio_action"] = cio.get(sym)
        e["held"] = bool(e.get("held")) or sym in held
        if sym in profiles:
            # Conditional on purpose: symbol_profiles covers ~3,136 symbols, fewer than
            # the tracked set, and a blank identity line under a BUY READY call is worse
            # than no line at all.
            desc, sector, industry = profiles[sym]
            e["company"], e["sector"], e["industry"] = desc, sector, industry
        pk = packets.get(sym)
        if pk is not None and pq is not None:
            e["quality_state"] = pq.packet_gate(pk).get("quality")
            e.setdefault("earnings_date", ((pk.get("event_state") or {}).get("earnings") or {}).get("date"))
        e["market_cap_label"] = cap_label(
            None if (b := enrichment_market_cap_billions(enrichment.get(sym) or {})) is None else b * 1000.0)
        # P8 thesis/structure inputs from house enrichment (never invent).
        enr = enrichment.get(sym) or {}
        if isinstance(enr, dict):
            if e.get("pe") is None and enr.get("pe") is not None:
                e["pe"] = enr.get("pe")
            if e.get("forward_pe") is None and enr.get("forward_pe") is not None:
                e["forward_pe"] = enr.get("forward_pe")
            if e.get("peg") is None and enr.get("peg") is not None:
                e["peg"] = enr.get("peg")
            if e.get("atr") is None and enr.get("atr") is not None:
                e["atr"] = enr.get("atr")
            if not e.get("sector") and enr.get("sector"):
                e["sector"] = enr.get("sector")
            if not e.get("industry") and enr.get("industry"):
                e["industry"] = enr.get("industry")
    return ev


def last_states(cur) -> dict[str, str]:
    cur.execute("""SELECT DISTINCT ON (symbol) symbol, state FROM cio_entry_states ORDER BY symbol, evaluated_at DESC""")
    return {row[0]: row[1] for row in cur.fetchall()}


def alerted_today(cur, keys: list[str]) -> set[str]:
    cur.execute("""SELECT details->>'transition_key' FROM cio_entry_states
                    WHERE alerted AND evaluated_at::date = CURRENT_DATE AND details->>'transition_key' = ANY(%s)""", (keys,))
    return {row[0] for row in cur.fetchall()}


def operator_send(text: str, *, primary_symbols: list[str] | None = None) -> dict:
    """The one operator send path (alert and digest). Routes IMMEDIATE as cio_entry_state.

    ``primary_symbols`` scopes Communications Editor footer chrome to the active
    symbol(s) so residual tickers (e.g. MAA GUID bleed on an AXTI alert) never
    appear in Finviz/Yahoo/CC links.
    """
    token = None
    reset_primary_symbols = None
    try:
        if primary_symbols:
            try:
                from scripts.lib.comms_editor import set_primary_symbols, reset_primary_symbols as _reset
            except ImportError:
                from lib.comms_editor import set_primary_symbols, reset_primary_symbols as _reset  # type: ignore
            reset_primary_symbols = _reset
            token = set_primary_symbols(primary_symbols)
        from telegram_alert import send_telegram
        return {"operator": bool(send_telegram(text, message_class="operator_alert"))}
    except Exception as exc:
        return {"operator": False, "operator_error": f"{type(exc).__name__}: {str(exc)[:120]}"}
    finally:
        if token is not None and reset_primary_symbols is not None:
            try:
                reset_primary_symbols(token)
            except Exception:
                pass


def starred_symbols(cur) -> set[str]:
    """Symbols the operator starred on the watchlist. Same idiom as
    watch_decision_scheduler.py:67 rather than a ninth bespoke variant.

    Fails CLOSED to the empty set: if the store cannot be read we page on
    BUY_READY only, which is quieter, never noisier.
    """
    try:
        cur.execute("SELECT upper(symbol) FROM operator_starred_symbols")
        return {row[0] for row in cur.fetchall() if row and row[0]}
    except Exception:
        return set()


def alert_worthy(actionable: list[dict], prior: dict, done: set,
                 starred: set[str] | None = None) -> list[dict]:
    """Page only on a move TOWARD a buy, once per symbol, state and day.

    On 2026-09-15 at 12:40, RTX and BZFD fell from BUY_READY back to ENTRY_NEAR, a price step out of
    the zone, and the operator got a second "getting close" for names already paged BUY READY at
    12:30. A downgrade is not news, and ENTRY_NEAR after a same-day BUY_READY alert is not either.

    Operator decision 2026-09-21: "Only alert when time to purchase unless starred on watchlist."
    ENTRY_NEAR is not a time to purchase -- it is a heads-up -- so it pages ONLY for a starred
    symbol. On 2026-09-21 at 15:10 the operator was paged "getting close" for GNL (+1.1%) and LOMA
    (+2.9%), neither starred and neither actionable. BUY_READY is unaffected and always pages.
    The suppression is of PAGING only: the cio_decisions row is still written for every state
    change, so the CIO keeps tracking names it no longer wakes the operator for.
    """
    starred = starred or set()
    out = []
    for r in actionable:
        if ces.transition_key(r) in done:
            continue
        if r["state"] == "ENTRY_NEAR" and (prior.get(r["symbol"]) == "BUY_READY"
                                           or ces.transition_key({**r, "state": "BUY_READY"}) in done):
            continue
        if r["state"] == "ENTRY_NEAR" and str(r.get("symbol") or "").upper() not in starred:
            continue
        out.append(r)
    return out


def stamp_cio_stance(text: str, symbols: list[str], only_conflicts: bool = False) -> str:
    """CIO stance footer, never a hold (M5 audit 2026-09-23, Module 4d).

    This page IS a CIO decision: the runner writes its own ``cio-entry-*`` row to
    cio_decisions just before paging, so gating it on the latest cio_decisions
    row would read that row back and always allow -- circular. Instead the
    footer shows the CIO's independent stance (the daily decision, excluding
    ``cio-entry-*`` rows) and flags an AVOID/SELL conflict.
    """
    try:
        from lib.publisher_stance_gate import stamp_symbols
    except ImportError:
        from scripts.lib.publisher_stance_gate import stamp_symbols  # type: ignore
    try:
        return stamp_symbols(text, symbols, exclude_decision_prefix="cio-entry-",
                             note="entry page is CIO-authored, not gated", only_conflicts=only_conflicts)
    except Exception:  # noqa: BLE001 -- a footer must never cost the page
        return text


def send_alerts(result: dict, evidence: dict) -> dict:
    out = {"cio_desk": False, "cio_bus": False}
    sym = str(result.get("symbol") or "").upper()
    out.update(operator_send(
        stamp_cio_stance(ces.render_operator(result, evidence), [result["symbol"]]),
        primary_symbols=[sym] if sym else None,
    ))
    try:
        from scripts.lib.cio_telegram_transport import send_cio_message
        r = send_cio_message(ces.render_cio(result, evidence), subject=f"Entry state {result['symbol']}",
                             kind="cio_advisory", dedupe_key=ces.transition_key(result))
        # send_cio_message returns {"delivered": bool, "reason": str, "deduped": bool, ...}. Reading
        # "sent"/"ok" recorded every desk message as failed on the first live run (2026-09-15 12:30).
        r = r or {}
        out["cio_desk"] = bool(r.get("delivered"))
        if not out["cio_desk"]:
            out["cio_desk_reason"] = "deduped" if r.get("deduped") else (r.get("reason") or "not delivered")
    except Exception as exc:
        out["cio_desk_error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
    try:
        from scripts.lib.cio_event_bus import CIOEventBus
        CIOEventBus().emit("watch.new_signal", {"symbol": result["symbol"], "signal": "cio_entry_state",
                                                "state": result["state"], "entry_low": result["entry_low"],
                                                "entry_high": result["entry_high"], "price": result["price"],
                                                "rr": result["rr"], "market_cap_label": result["market_cap_label"]},
                           source="cio_entry_state_runner", semantic_event_key=ces.transition_key(result))
        out["cio_bus"] = True
    except Exception as exc:
        out["cio_bus_error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="record states, write CIO decisions and send alerts")
    ap.add_argument("--max-alerts", type=int, default=MAX_ALERTS_PER_RUN)
    a = ap.parse_args()
    conn = _conn()
    cur = conn.cursor()
    if a.apply:
        cur.execute(DDL)
        conn.commit()
    evidence = gather(cur)
    results = {sym: ces.evaluate(e) for sym, e in evidence.items()}
    try:
        prior = last_states(cur)
    except Exception:
        conn.rollback()
        prior = {}
    counts: dict[str, int] = {}
    for r in results.values():
        counts[r["state"]] = counts.get(r["state"], 0) + 1
    actionable = sorted((r for r in results.values() if r["state"] in ces.ACTIONABLE),
                        key=lambda r: (0 if r["state"] == "BUY_READY" else 1, abs(r["distance_pct"] or 0)))
    keys = [ces.transition_key(r) for r in actionable]
    buy_keys = [ces.transition_key({**r, "state": "BUY_READY"}) for r in actionable if r["state"] == "ENTRY_NEAR"]
    done = alerted_today(cur, keys + buy_keys) if (a.apply and keys) else set()
    starred = starred_symbols(cur)
    pending = alert_worthy(actionable, prior, done, starred)
    to_alert = pending[: max(0, a.max_alerts)]
    digest = pending[max(0, a.max_alerts):]
    sent = []
    if a.apply:
        for sym, r in results.items():
            if prior.get(sym) != r["state"]:
                alert = r in to_alert
                cur.execute("""INSERT INTO cio_entry_states (symbol, state, prior_state, alerted, details)
                               VALUES (%s,%s,%s,%s,%s::jsonb)""",
                            (sym, r["state"], prior.get(sym), alert,
                             json.dumps({**r, "transition_key": ces.transition_key(r)}, default=str)))
        for r in to_alert:
            if prior.get(r["symbol"]) == r["state"]:
                cur.execute("""INSERT INTO cio_entry_states (symbol, state, prior_state, alerted, details)
                               VALUES (%s,%s,%s,true,%s::jsonb)""",
                            (r["symbol"], r["state"], r["state"],
                             json.dumps({**r, "transition_key": ces.transition_key(r)}, default=str)))
            did = f"cio-entry-{r['symbol'].lower()}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
            cur.execute("""INSERT INTO cio_decisions (decision_id, symbol, strategy_type, action, action_class, priority,
                                                      confidence_raw, decision_safety, human_review_required, rationale,
                                                      status, agent_votes)
                           VALUES (%s,%s,%s,%s,'entry',%s,%s,'safe',true,%s,'proposed','{}')""",
                        (did, r["symbol"], r.get("plan_source"), r["state"], "high" if r["state"] == "BUY_READY" else "medium",
                         None, ces.render_cio(r, evidence[r["symbol"]])[:500]))
        conn.commit()
        for r in digest:
            # recorded as alerted so the digest names do not come back one by one later today
            cur.execute("""INSERT INTO cio_entry_states (symbol, state, prior_state, alerted, details)
                           VALUES (%s,%s,%s,true,%s::jsonb)""",
                        (r["symbol"], r["state"], r["state"],
                         json.dumps({**r, "transition_key": ces.transition_key(r), "via": "digest"}, default=str)))
        conn.commit()
        for r in to_alert:
            sent.append({"symbol": r["symbol"], "state": r["state"], **send_alerts(r, evidence[r["symbol"]])})
        if digest:
            digest_syms = [str(r["symbol"]).upper() for r in digest if r.get("symbol")]
            sent.append({
                "digest": digest_syms,
                **operator_send(
                    stamp_cio_stance(
                        ces.render_digest(digest),
                        [r["symbol"] for r in digest],
                        only_conflicts=True,
                    ),
                    primary_symbols=digest_syms,
                ),
            })
        RECEIPT.parent.mkdir(parents=True, exist_ok=True)
        RECEIPT.write_text(json.dumps({"as_of": datetime.now(timezone.utc).isoformat(), "counts": counts,
                                       "alerts": sent}, indent=2, default=str))
    else:
        conn.rollback()
    report = {"mode": "apply" if a.apply else "dry_run", "tracked": len(results), "states": counts,
              "actionable": len(actionable), "would_alert": [f"{r['symbol']} {r['state']}" for r in to_alert],
              "would_digest": [f"{r['symbol']} {r['state']}" for r in digest],
              "sent": sent,
              "blocked_reasons": _top_reasons(results.values())}
    if not a.apply and to_alert:
        report["sample_operator_message"] = stamp_cio_stance(
            ces.render_operator(to_alert[0], evidence[to_alert[0]["symbol"]]), [to_alert[0]["symbol"]])
    print(json.dumps(report, indent=2, default=str))
    return 0


def _top_reasons(results) -> dict:
    c: dict[str, int] = {}
    for r in results:
        for reason in r["reasons"]:
            import re as _re
            key = _re.sub(r"[0-9]+(\.[0-9]+)?", "N", reason)
            c[key] = c.get(key, 0) + 1
    return dict(sorted(c.items(), key=lambda kv: -kv[1])[:8])


if __name__ == "__main__":
    raise SystemExit(main())
