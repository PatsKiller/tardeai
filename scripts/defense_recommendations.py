#!/usr/bin/env python3
"""defense_recommendations.py — Defense Desk v3 WS-R: the desk finally prescribes.

Nightly after the sector engine (17:25) + industry close capture (16:18). Reads the
state snapshots + capabilities matrix + enrichment rails and emits COMPLETE
recommendation cards in four groups:
  get_into   (R3) rotate-in: LEADING/IMPROVING sector underweight vs neutral map
  protect    (R2) move-out advisories (factor join, tax-gated, SHADOW 10d)
             (R1) put-structure placeholder until options_level filled
  short_side (R4a) inverse-ETF hedges · (R4b) taxable short advisories
  income     (R4d) covered-call defensive queue

Every card carries: instrument · accounts · direction · size band · entry logic ·
invalidation · factors (values shown) · as_of · SHADOW/LIVE chip. The field guard
DROPS any card missing a field (dropped list is in the payload — honest, visible).
Paper twins for short_side cards go through paper_trade_proposals (PENDING — the
normal approval queue; nothing self-executes). Advisory/paper only.

Usage: defense_recommendations.py [--dry-run]
"""
import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

CFG = json.loads((ROOT / "config" / "defense_recommendations.json").read_text())
CAPS = json.loads((ROOT / "config" / "account_capabilities.json").read_text())["accounts"]
SNAP = ROOT / "data" / "runtime" / "defense_recommendations_latest.json"

REQUIRED = ("id", "group", "title", "instruments", "accounts", "direction", "size_band",
            "entry_logic", "invalidation", "factors", "as_of", "mode")


def _load(name):
    p = ROOT / "data" / "runtime" / name
    return json.loads(p.read_text()) if p.exists() else {}


def _acct(name: str) -> str:
    return CFG["account_aliases"].get(name, name)


def validate(card: dict) -> str | None:
    """Return the missing field name, or None if the card is complete."""
    for f in REQUIRED:
        v = card.get(f)
        if v is None or v == "" or v == [] or v == {}:
            return f
    if not all(("name" in x and "value" in x) for x in card["factors"]):
        return "factors"
    return None


def _enrich() -> dict:
    try:
        c = json.loads((ROOT / "data" / "state" / "ticker_enrichment_cache.json").read_text())
        return {k: v for k, v in c.items() if not k.startswith("_")}
    except Exception:
        return {}


def _holdings() -> list:
    h = json.loads((ROOT / "data" / "portfolios" / "state" / "holdings.json").read_text())
    out = []
    for r in h.get("holdings", []):
        if r.get("is_cash") or not r.get("symbol"):
            continue
        out.append({"symbol": r["symbol"], "account": _acct(r["account"]),
                    "value": r.get("market_value") or 0, "shares": r.get("shares") or 0,
                    "price": r.get("price") or 0, "name": r.get("name") or ""})
    return out


def _profiles(cur, symbols):
    cur.execute("""SELECT symbol, sector, next_earnings_date, rsi14, sma50_pct
                   FROM symbol_profiles WHERE symbol = ANY(%s)""", (list(symbols),))
    return {r[0]: {"sector": r[1], "earnings": r[2], "rsi": r[3], "sma50_pct": r[4]}
            for r in cur.fetchall()}


def _hermes_latest(cur, symbols):
    cur.execute("""SELECT DISTINCT ON (symbol) symbol, composite_score, scored_at
                   FROM hermes_score_history WHERE symbol = ANY(%s)
                   ORDER BY symbol, scored_at DESC""", (list(symbols),))
    now5 = {r[0]: float(r[1]) for r in cur.fetchall() if r[1] is not None}
    cur.execute("""SELECT DISTINCT ON (symbol) symbol, composite_score
                   FROM hermes_score_history WHERE symbol = ANY(%s)
                     AND scored_at < now() - interval '5 days'
                   ORDER BY symbol, scored_at DESC""", (list(symbols),))
    ago = {r[0]: float(r[1]) for r in cur.fetchall() if r[1] is not None}
    return {s: {"score": now5[s], "delta5": round(now5[s] - ago[s], 1) if s in ago else None}
            for s in now5}


def _prices(cur, symbols) -> dict:
    """Latest close per symbol from ticker_prices (enrichment cache carries no price)."""
    if not symbols:
        return {}
    cur.execute("""SELECT DISTINCT ON (symbol) symbol, close_price FROM ticker_prices
                   WHERE symbol = ANY(%s) ORDER BY symbol, price_date DESC""", (list(symbols),))
    return {r[0]: float(r[1]) for r in cur.fetchall() if r[1]}


def _earnings_soon(prof, days):
    e = (prof or {}).get("earnings")
    if not e:
        return False
    try:
        d = e if hasattr(e, "toordinal") else datetime.strptime(str(e)[:10], "%Y-%m-%d").date()
        return 0 <= (d - datetime.now(timezone.utc).date()).days <= days
    except Exception:
        return False


def rotate_in(sectors, cur, enrich, as_of) -> list:
    c = CFG["rotate_in"]
    cards = []
    ranked = sorted([r for r in sectors if r.get("state") in ("LEADING", "IMPROVING")],
                    key=lambda r: -(r.get("rs20") or 0))
    for r in ranked:
        if (r.get("book_pct") or 0) >= CFG["underweight_floor_pct"]:
            continue
        # constituents: sector members by latest Hermes composite passing the rails
        cur.execute("""SELECT DISTINCT ON (h.symbol) h.symbol, h.composite_score
                       FROM hermes_score_history h JOIN trade_ai_scans t ON t.symbol = h.symbol
                       WHERE t.sector = ANY(%s) AND h.scored_at > now() - interval '3 days'
                       ORDER BY h.symbol, h.scored_at DESC""",
                    ([r["sector"]] + _sector_aliases(r["sector"]),))
        scored = sorted([(s, float(sc)) for s, sc in cur.fetchall() if sc is not None],
                        key=lambda x: -x[1])
        picks = []
        px = _prices(cur, [s for s, _ in scored[:40]])
        for sym, sc in scored[:40]:
            e = enrich.get(sym) or {}
            price = px.get(sym) or 0
            dollar_vol_m = (e.get("avg_vol_m") or 0) * 1000 * price / 1e6 if price else 0
            prof_e = _profiles_one(cur, sym)
            if dollar_vol_m < c["constituent_min_dollar_vol_m"]:
                continue
            if (e.get("sma50_pct") or 0) > c["constituent_max_ext_above_sma50_pct"]:
                continue  # EXTENDED — same discipline as Gain Guardian's parabolic read
            if _earnings_soon(prof_e, c["earnings_blackout_days"]):
                continue
            picks.append({"symbol": sym, "hermes": round(sc, 1)})
            if len(picks) >= c["top_constituents"]:
                break
        instruments = [{"symbol": r["etf"], "kind": "sector ETF", "note": "valid every account"}]
        instruments += [{"symbol": p["symbol"], "kind": "constituent",
                         "note": f"Hermes composite {p['hermes']}"} for p in picks]
        if not picks:
            instruments[0]["note"] += " — no constituent passed the rails; ETF is the recommendation"
        cards.append({
            "id": f"rotatein-{r['etf']}-{as_of}", "group": "get_into",
            "title": f"ROTATE-IN · {r['sector']} ({r['state']}, RS20 {r['rs20']:+.1f})",
            "instruments": instruments, "accounts": sorted(CAPS.keys()),
            "direction": "long", "size_band": f"{c['size_band_pct'][0]}–{c['size_band_pct'][1]}% of account equity",
            "entry_logic": "stagger in on pullbacks toward the 20DMA; do not chase extended prints",
            "invalidation": f"{r['sector']} drops out of {r['state']} (2-close confirmed) — exit the thesis",
            "factors": [
                {"name": "sector state", "value": r["state"]},
                {"name": "RS20 vs SPY", "value": f"{r['rs20']:+.2f}%"},
                {"name": "book weight", "value": f"{r.get('book_pct') or 0}% (floor {CFG['underweight_floor_pct']}%)"},
                {"name": "breadth", "value": f"{r.get('breadth_pct')}% above own 20DMA"},
            ],
            "as_of": as_of, "mode": "SHADOW",
            "routes": {"proposal": "watch-directive path — operator approves; nothing self-executes"},
        })
        if len(cards) >= c["max_cards"]:
            break
    return cards


_ALIAS_CACHE = None


def _sector_aliases(sector):
    global _ALIAS_CACHE
    if _ALIAS_CACHE is None:
        _ALIAS_CACHE = json.loads((ROOT / "config" / "sector_momentum.json").read_text()).get("sector_aliases", {})
    return _ALIAS_CACHE.get(sector, [])


_PROF_CACHE = {}


def _profiles_one(cur, sym):
    if sym not in _PROF_CACHE:
        cur.execute("SELECT sector, next_earnings_date FROM symbol_profiles WHERE symbol=%s", (sym,))
        row = cur.fetchone()
        _PROF_CACHE[sym] = {"sector": row[0], "earnings": row[1]} if row else {}
    return _PROF_CACHE[sym]


def move_out(sectors, holdings, cur, enrich, hermes, as_of) -> list:
    c = CFG["move_out"]
    smap = {}
    for r in sectors:
        for name in [r["sector"]] + _sector_aliases(r["sector"]):
            smap[name] = r
    cards = []
    for h in holdings:
        prof = _profiles_one(cur, h["symbol"])
        sec = smap.get((prof or {}).get("sector") or "")
        e = enrich.get(h["symbol"]) or {}
        hz = hermes.get(h["symbol"]) or {}
        factors = []
        if sec and sec.get("state") in ("WEAKENING", "LAGGING"):
            factors.append({"name": "sector state", "value": f"{sec['sector']} {sec['state']} (RS20 {sec['rs20']:+.1f})"})
        if (e.get("sma200_pct") or 0) < 0:
            factors.append({"name": "below 200DMA", "value": f"{e['sma200_pct']}%"})
        if (e.get("sma50_pct") or 0) < 0:
            factors.append({"name": "below 50DMA", "value": f"{e['sma50_pct']}%"})
        if (hz.get("delta5") or 0) < -3:
            factors.append({"name": "Hermes composite 5d", "value": f"{hz['delta5']:+.1f} → {hz['score']}"})
        if (e.get("rsi") or 50) < 40:
            factors.append({"name": "RSI14", "value": e["rsi"]})
        if sec and (sec.get("news_negatives") or 0) > 0:
            factors.append({"name": "sector negative catalysts 5d", "value": sec["news_negatives"]})
        if len(factors) < c["factor_threshold"]:
            continue
        tax = CFG["move_out"]["tax_gate_lt_gain_note"] if h["account"] == "schwab_taxable" else "IRA — no tax gate"
        cards.append({
            "id": f"moveout-{h['symbol']}-{h['account']}-{as_of}", "group": "protect",
            "title": f"MOVE-OUT · {h['symbol']} (${h['value']/1000:.0f}K in {CFG['account_labels'].get(h['account'], h['account'])})",
            "instruments": [{"symbol": h["symbol"], "kind": "held position", "note": f"{h['shares']} sh"}],
            "accounts": [h["account"]], "direction": "reduce/exit",
            "size_band": "trim 25–50% first; full exit only on continued deterioration",
            "entry_logic": "reduce into strength, not into a flush; stage over 2–3 sessions",
            "invalidation": "sector recovers out of WEAKENING/LAGGING (2-close) AND price reclaims the 50DMA",
            "factors": factors + [{"name": "tax gate", "value": tax}],
            "as_of": as_of, "mode": "SHADOW",
            "routes": {"shadow": f"10-trading-day shadow started {c['shadow_started']} — Telegram only after promote"},
        })
        if len(cards) >= c["max_cards"]:
            break
    return cards


def inverse_etf(sectors, market, as_of) -> list:
    c = CFG["inverse_etf"]
    cards = []
    triggered = [r for r in sectors if r.get("state") in ("WEAKENING", "LAGGING")
                 and (r.get("book_pct") or 0) >= c["trigger_book_pct"]]
    lagging_n = sum(1 for r in sectors if r.get("state") == "LAGGING")
    qqq = next((i for i in (market or {}).get("indices", []) if i["symbol"] == "QQQ"), {})
    if triggered or lagging_n >= c["index_trigger_lagging_sectors"]:
        # instrument: PSQ when the deterioration is tech-led (QQQ rs20 < -2), else SH
        tech_led = (qqq.get("rs_mid") or 0) < -2
        inst = c["map"]["QQQ"] if tech_led else c["map"]["SPY"]
        at_risk = sum(r.get("book_dollars") or 0 for r in triggered)
        factors = [{"name": "sectors LAGGING", "value": f"{lagging_n}/11"},
                   {"name": "QQQ RS20 vs SPY", "value": f"{qqq.get('rs_mid', 0):+.1f}%"}]
        for r in triggered:
            factors.append({"name": f"book in {r['sector']}", "value": f"{r['book_pct']}% ({r['state']})"})
        cards.append({
            "id": f"inverse-{inst}-{as_of}", "group": "short_side",
            "title": f"HEDGE · {inst} (1x inverse {'QQQ — deterioration is tech-led' if tech_led else 'S&P 500'})",
            "instruments": [{"symbol": inst, "kind": "inverse ETF", "note": c["decay_warning"]}],
            "accounts": sorted(k for k, v in CAPS.items() if v.get("inverse_etf_ok")),
            "direction": "long (inverse exposure)",
            "size_band": f"{c['size_band_pct'][0]}–{c['size_band_pct'][1]}% of account equity"
                         + (f" (≈${at_risk/1000:.0f}K book in triggered sectors)" if at_risk else ""),
            "entry_logic": "scale in on bounce days, not after down days — hedges bought into weakness overpay",
            "invalidation": c["exit_rule"],
            "factors": factors, "as_of": as_of, "mode": "SHADOW",
            "routes": {"paper_twin": "inverse-ETF paper track via approval queue"},
        })
    return cards


def taxable_short(industries, cur, enrich, as_of, held_symbols=frozenset()) -> list:
    c = CFG["taxable_short"]
    if not CAPS.get("schwab_taxable", {}).get("can_short_stock"):
        return []
    pool = (industries.get("candidates") or {}).get("defensive_short_pool") or []
    pool_names = [p["industry"] for p in pool]
    if not pool_names:
        return []
    cur.execute("""SELECT DISTINCT ON (symbol) symbol, industry FROM trade_ai_scans
                   WHERE industry = ANY(%s) ORDER BY symbol, scanned_at DESC""", (pool_names,))
    members = cur.fetchall()
    cands = []
    px = _prices(cur, [m[0] for m in members])
    for sym, industry in members:
        if sym in held_symbols:
            continue  # NEVER advise shorting a name the book holds
        e = enrich.get(sym) or {}
        price = px.get(sym) or 0
        if not price or price < c["min_price"]:
            continue
        dollar_vol_m = (e.get("avg_vol_m") or 0) * 1000 * price / 1e6
        if dollar_vol_m < c["min_dollar_vol_m"]:
            continue
        if (e.get("sma200_pct") or 0) >= 0 or (e.get("sma50_pct") or 0) >= 0:
            continue
        sf = e.get("short_float_pct")
        if sf is None or sf >= c["max_short_float_pct"]:
            continue  # anti-squeeze
        if _earnings_soon(_profiles_one(cur, sym), c["earnings_blackout_days"]):
            continue
        cands.append({"symbol": sym, "industry": industry, "price": price, "sf": sf,
                      "sma200": e["sma200_pct"], "sma20": e.get("sma20_pct") or 0,
                      "cached_at": e.get("cached_at")})
    cands.sort(key=lambda x: x["sma200"])
    cards = []
    picked = 0
    for x in cands:
        if picked >= c["max_cards"]:
            break
        sma20_level = x["price"] / (1 + x["sma20"] / 100) if x["sma20"] > -100 else x["price"] * 1.05
        stop = round(max(sma20_level, x["price"]) * (1 + c["buy_stop_above_sma20_pct"] / 100), 2)
        risk_per_sh = stop - x["price"]
        if risk_per_sh / x["price"] * 100 > c["max_stop_distance_pct"]:
            continue  # too far below its 20DMA — chasing an extended flush, stop unpayable
        picked += 1
        cards.append({
            "id": f"short-{x['symbol']}-{as_of}", "group": "short_side",
            "title": f"SHORT ADVISORY · {x['symbol']} ({x['industry']}) — Taxable only",
            "instruments": [{"symbol": x["symbol"], "kind": "short stock",
                             "note": f"short float {x['sf']}% as of {str(x['cached_at'])[:10]} (single capture — trend n/a)"}],
            "accounts": ["schwab_taxable"], "direction": "short",
            "size_band": f"≤{c['size_cap_pct_of_book']}% of taxable book (hard cap)",
            "entry_logic": f"entry near {x['price']:.2f}; MANDATORY buy-stop {stop:.2f} "
                           f"(≈{c['buy_stop_above_sma20_pct']}% above the 20DMA); max loss ≈ {risk_per_sh / x['price'] * 100:.1f}% of position",
            "invalidation": f"buy-stop {stop:.2f} hit, or {x['industry']} exits LAGGING (2-close)",
            "factors": [
                {"name": "industry state", "value": f"{x['industry']} LAGGING (confirmed pool)"},
                {"name": "vs 200DMA", "value": f"{x['sma200']}%"},
                {"name": "short float", "value": f"{x['sf']}% (<{c['max_short_float_pct']}% anti-squeeze)"},
            ],
            "as_of": as_of, "mode": "SHADOW",
            "routes": {"paper_twin": "defensive_short paper strategy via approval queue"},
        })
    return cards


def covered_calls(sectors, holdings, cur, as_of) -> list:
    c = CFG["covered_call"]
    smap = {}
    for r in sectors:
        for name in [r["sector"]] + _sector_aliases(r["sector"]):
            smap[name] = r
    cards = []
    for h in holdings:
        if h["value"] < c["min_position_dollars"] or h["shares"] < 100:
            continue
        acct_caps = CAPS.get(h["account"]) or {}
        if not acct_caps.get("covered_calls_ok"):
            continue
        sec = smap.get((_profiles_one(cur, h["symbol"]) or {}).get("sector") or "")
        if not sec or sec.get("state") not in ("WEAKENING", "LAGGING"):
            continue
        cards.append({
            "id": f"cc-{h['symbol']}-{h['account']}-{as_of}", "group": "income",
            "title": f"COVERED CALL · {h['symbol']} ({int(h['shares'] // 100)} contract{'s' if h['shares'] >= 200 else ''}, {CFG['account_labels'].get(h['account'], h['account'])})",
            "instruments": [{"symbol": h["symbol"], "kind": "covered call",
                             "note": f"{c['tenor_dte'][0]}–{c['tenor_dte'][1]} DTE · {c['delta_band'][0]}–{c['delta_band'][1]} delta"}],
            "accounts": [h["account"]], "direction": "sell call vs held shares",
            "size_band": f"{int(h['shares'] // 100)} contract(s) against {h['shares']:.0f} sh",
            "entry_logic": "sell into up-days/IV pops; premium honesty: income caps upside — this is a defensive yield, not a lottery hedge",
            "invalidation": f"{sec['sector']} recovers out of {sec['state']} — let calls expire/close, stop rolling",
            "factors": [
                {"name": "sector state", "value": f"{sec['sector']} {sec['state']} (RS20 {sec['rs20']:+.1f})"},
                {"name": "position", "value": f"${h['value']/1000:.0f}K · {h['shares']:.0f} sh"},
            ],
            "as_of": as_of, "mode": "SHADOW",
            "routes": {"options_desk": "route through the Options desk CC review flow"},
        })
        if len(cards) >= c["max_cards"]:
            break
    return cards


def options_locked_card(as_of) -> dict:
    return {
        "id": f"putlock-{as_of}", "group": "protect",
        "title": "PUT HEDGES · locked",
        "instruments": [{"symbol": "—", "kind": "long puts / put spreads",
                         "note": "unlocks when options level confirmed — fill options_level in config/account_capabilities.json"}],
        "accounts": sorted(CAPS.keys()), "direction": "n/a until unlocked",
        "size_band": "n/a", "entry_logic": "n/a — configuration gate, not a market call",
        "invalidation": "n/a",
        "factors": [{"name": "options_level", "value": "null in every account (operator fill)"}],
        "as_of": as_of, "mode": "SHADOW", "routes": {"config": "account_capabilities.json"},
    }


def paper_twins(cards, cur, dry: bool) -> list:
    """Short-side cards → PENDING paper proposals through the normal approval queue."""
    c = CFG["paper_twin"]
    created = []
    cur.execute("""SELECT count(*) FROM paper_trade_proposals
                   WHERE strategy_id IN ('defensive_short','inverse_etf_hedge')
                     AND status='PENDING'""")
    open_n = cur.fetchone()[0]
    for card in cards:
        if card["group"] != "short_side" or open_n >= c["max_concurrent_shorts"]:
            continue
        inst = card["instruments"][0]
        if inst["symbol"] == "—":
            continue
        short = card["direction"] == "short"
        strategy = "defensive_short" if short else "inverse_etf_hedge"
        cur.execute("""SELECT 1 FROM paper_trade_proposals WHERE symbol=%s AND strategy_id=%s
                       AND status='PENDING' LIMIT 1""", (inst["symbol"], strategy))
        if cur.fetchone():
            continue
        try:
            entry = float(card["entry_logic"].split("entry near ")[1].split(";")[0]) if short else None
        except (IndexError, ValueError):
            entry = None
        if entry is None:
            entry = _prices(cur, [inst["symbol"]]).get(inst["symbol"]) or 0
        if not entry:
            continue
        if short:
            stop = float(card["invalidation"].split("buy-stop ")[1].split(" ")[0])
            target = round(entry - 1.5 * (stop - entry), 2)
        else:
            stop = round(entry * 0.95, 2)
            target = round(entry * 1.08, 2)
        shares = max(1, int(c["dollar_size"] / entry))
        if not dry:
            cur.execute("""INSERT INTO paper_trade_proposals
                (symbol, strategy_id, side, proposed_entry, proposed_stop, proposed_target1,
                 proposed_shares, proposed_dollar_size, status, proposed_by, origin,
                 setup_description, expires_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'PENDING','defense_recommendations','auto',%s,%s)""",
                (inst["symbol"], strategy, "short" if short else "long", entry, stop, target,
                 shares, c["dollar_size"], card["title"][:180],
                 datetime.now(timezone.utc) + timedelta(hours=c["expires_hours"])))
        created.append({"symbol": inst["symbol"], "strategy": strategy, "entry": entry, "stop": stop})
        open_n += 1
    return created


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from db_adapter import _get_conn
    conn = _get_conn()
    cur = conn.cursor()
    as_of = datetime.now(timezone.utc).date().isoformat()

    sector_snap = _load("sector_momentum_latest.json")
    sectors = sector_snap.get("rows") or []
    market = sector_snap.get("market") or {}
    industries = _load("industry_momentum_latest.json")
    enrich = _enrich()
    holdings = _holdings()
    hermes = _hermes_latest(cur, [h["symbol"] for h in holdings])

    cards = []
    cards += rotate_in(sectors, cur, enrich, as_of)
    cards += move_out(sectors, holdings, cur, enrich, hermes, as_of)
    cards += inverse_etf(sectors, market, as_of)
    cards += taxable_short(industries, cur, enrich, as_of,
                           held_symbols=frozenset(h["symbol"] for h in holdings))
    cards += covered_calls(sectors, holdings, cur, as_of)
    cards.append(options_locked_card(as_of))

    ok, dropped = [], []
    for card in cards:
        missing = validate(card)
        if missing:
            dropped.append({"id": card.get("id", "?"), "missing": missing})
        else:
            ok.append(card)

    twins = paper_twins(ok, cur, args.dry_run)
    if not args.dry_run:
        conn.commit()

    groups = {g: [c for c in ok if c["group"] == g]
              for g in ("get_into", "protect", "short_side", "income")}
    empty_reasons = {
        "get_into": "no LEADING/IMPROVING sector is underweight vs your neutral map",
        "protect": "no held position fired ≥%d factors" % CFG["move_out"]["factor_threshold"],
        "short_side": "no trigger: no >10%-book sector WEAKENING/LAGGING and short pool produced no clean candidate",
        "income": "no ≥100-share holding sits in a WEAKENING/LAGGING sector",
    }
    snap = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of": as_of, "mode": "SHADOW",
        "shadow_note": f"all groups SHADOW — 10-trading-day window from {CFG['move_out']['shadow_started']}; Telegram only after promote",
        "groups": groups,
        "empty_reasons": {g: empty_reasons[g] for g in groups if not groups[g]},
        "dropped_by_field_guard": dropped,
        "paper_twins_created": twins,
        "accounts": {k: CFG["account_labels"].get(k, k) for k in sorted(CAPS.keys())},
    }
    if not args.dry_run:
        SNAP.write_text(json.dumps(snap, default=str))
    print(f"[recs] {sum(len(v) for v in groups.values())} cards "
          f"({', '.join(f'{g}:{len(v)}' for g, v in groups.items())}) · "
          f"{len(dropped)} dropped by field guard · {len(twins)} paper twins")
    return 0


if __name__ == "__main__":
    sys.exit(main())
