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
    """Return the missing field name, or None if the card is complete.
    v4: actionable groups additionally require levels with a real price —
    a card the operator can't act on from its face does not render."""
    for f in REQUIRED:
        v = card.get(f)
        if v is None or v == "" or v == [] or v == {}:
            return f
    if not all(("name" in x and "value" in x) for x in card["factors"]):
        return "factors"
    locked = any(i.get("symbol") == "—" for i in card.get("instruments", []))
    if card["group"] in ("get_into", "short_side", "income") and not locked:
        lv = card.get("levels") or {}
        if not lv.get("price"):
            return "levels.price"
        if not lv.get("entry_zone") or not lv.get("stop"):
            return "levels"
    # v5: a TRIM card without rendered arithmetic + a sell ticket does not render —
    # the static-band regression is now guard-impossible
    if card["id"].startswith("moveout-"):
        if not card.get("trim_rationale"):
            return "trim_rationale"
        tk = card.get("ticket") or {}
        if not tk.get("options"):
            return "ticket"
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


def account_equities(holdings) -> dict:
    eq = {}
    for h in holdings:
        eq[h["account"]] = eq.get(h["account"], 0) + h["value"]
    return {k: round(v) for k, v in eq.items()}


def dollars_band(pct_band, accounts, equities) -> dict:
    """WS-CARD: '2–4%' becomes real dollars per account the card is valid for."""
    out = {}
    for a in accounts:
        eq = equities.get(a)
        if eq:
            out[a] = [round(eq * pct_band[0] / 100), round(eq * pct_band[1] / 100)]
    return out


def _materiality_min(total_book: float) -> float:
    c = CFG["materiality"]
    return max(c["min_position_dollars"], total_book * c["min_position_pct_of_book"] / 100)


def core_set(cur) -> set:
    """v6 C1 — the operator-owned ★CORE registry. (symbol, None) = core in all accounts."""
    try:
        cur.execute("SELECT symbol, account FROM operator_core_registry")
        return {(r[0], r[1]) for r in cur.fetchall()}
    except Exception:
        cur.connection.rollback()
        return set()


def is_core(core: set, symbol: str, account: str) -> bool:
    return (symbol, None) in core or (symbol, account) in core


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


def rotate_in(sectors, cur, enrich, as_of, equities=None) -> list:
    c = CFG["rotate_in"]
    cards = []
    ranked = sorted([r for r in sectors if r.get("state") in ("LEADING", "IMPROVING")],
                    key=lambda r: -(r.get("rs20") or 0))
    # v8.10 — the defensive lean governs rotate-in IDEAS too (operator extension
    # 2026-07-18, after the Opus catch: pairs excluded cyclicals while Get-Into
    # still advised Energy): cyclical rotate-ins are excluded while lean is on
    lean = (CFG.get("rotation_pairs") or {}).get("defensive_lean") or {}
    if lean.get("enabled"):
        ranked = [r for r in ranked if r["sector"] in lean.get("defensive_sectors", [])]
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
        etf_px = _prices(cur, [r["etf"]]).get(r["etf"])
        etf_e = enrich.get(r["etf"]) or {}
        sma20_lvl = round(etf_px / (1 + (etf_e.get("sma20_pct") or 0) / 100), 2) if etf_px else None
        instruments = [{"symbol": r["etf"], "kind": "sector ETF", "note": "valid every account",
                        "price": etf_px}]
        instruments += [{"symbol": p["symbol"], "kind": "constituent",
                         "note": f"Hermes composite {p['hermes']}",
                         "price": px.get(p["symbol"])} for p in picks]
        if not picks:
            instruments[0]["note"] += " — no constituent passed the rails; ETF is the recommendation"
        band = dollars_band(c["size_band_pct"], sorted(CAPS.keys()), equities or {})
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
            "levels": {"price": etf_px, "entry_zone": f"pullback toward 20DMA ≈ ${sma20_lvl}" if sma20_lvl else "stagger on pullbacks",
                       "stop": f"thesis stop: {r['sector']} exits {r['state']} (2-close)"},
            "dollars_by_account": band,
            "impact_dollars": max((v[1] for v in band.values()), default=0),
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


def _sector_map(sectors):
    smap = {}
    for r in sectors:
        for name in [r["sector"]] + _sector_aliases(r["sector"]):
            smap[name] = r
    return smap


def _fired_factors(h, sec, e, hz) -> list:
    """The shared factor join (move-out + stances) — values always shown."""
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
    return factors


def move_out(sectors, holdings, cur, enrich, hermes, as_of, total_book=0, as_of_label="") -> list:
    import defense_trim_ladders as dtl
    from fund_lookthrough import _cfg as _lt_cfg
    c = CFG["move_out"]
    cc = CFG.get("core", {})
    smap = _sector_map(sectors)
    floor = _materiality_min(total_book)
    gg = dtl.gg_latest(cur)
    lt = _lt_cfg()
    core = core_set(cur)
    by_symbol = {}
    for h in holdings:
        by_symbol.setdefault(h["symbol"], []).append(h)
    cards, scraps, seen = [], [], set()
    for h in holdings:
        h_core = is_core(core, h["symbol"], h["account"])
        if h["value"] < floor and not h_core:  # cleanup NEVER touches core (C3)
            scraps.append(h)
            continue
        prof = _profiles_one(cur, h["symbol"])
        sec = smap.get((prof or {}).get("sector") or "")
        e = enrich.get(h["symbol"]) or {}
        hz = hermes.get(h["symbol"]) or {}
        factors = _fired_factors(h, sec, e, hz)
        if len(factors) < c["factor_threshold"]:
            continue
        # v8.7 — operator suppressions: dated, reasoned, revocable; the engine keeps
        # computing (honesty) but stops emitting the card until the entry is removed
        supp = next((x for x in CFG.get("operator_suppressions", [])
                     if x["symbol"] == h["symbol"] and x.get("scope") == "move_out"
                     and not x.get("until")), None)
        if supp:
            try:
                cur.execute("""INSERT INTO defense_execution_audit (intent_key, hop, detail, actor)
                               VALUES (%s,'advisory_suppressed',%s,'engine')""",
                            (f"mute-{h['symbol']}", f"{h['symbol']} move_out suppressed (operator mute {supp['set']})"))
            except Exception:
                cur.connection.rollback()
            continue
        # DT1 — the composite, arithmetic rendered; absent inputs listed
        urgent = any("urgent" in str(f.get("value", "")).lower() for f in factors)
        fund = lt.get(h["symbol"])
        if fund and fund.get("weights") and not sec:
            # fund positions: judge concentration via the DOMINANT lookthrough sleeve
            dom = max(fund["weights"], key=lambda s: fund["weights"][s])
            sec = smap.get(dom) or sec
        sector_name = (sec or {}).get("sector")
        eff_pct = (sec or {}).get("book_pct")
        lt_weight = (fund["weights"].get(sector_name, 0) if fund and fund.get("weights")
                     else 1.0)
        plan = dtl.compute_trim_plan(factors, urgent, gg.get((h["symbol"], h["account"])),
                                     eff_pct, dtl.stop_context(cur, h["symbol"], h["account"]))
        if h_core and plan["fraction_pct"] > cc.get("max_trim_pct", 60):
            plan["fraction_pct"] = cc["max_trim_pct"]
            plan["rationale"] += f" · ★CORE cap {cc['max_trim_pct']}%"
        # DT2 — the sell ticket across every account holding the symbol
        acct_rows = by_symbol[h["symbol"]]
        ticket = dtl.sell_ticket(h["symbol"], acct_rows, plan["fraction_pct"], as_of_label,
                                 sector_name, (sec or {}).get("book_dollars"),
                                 total_book, lookthrough_weight=lt_weight)
        if h["symbol"] in seen:
            continue  # one card per symbol — the ticket already covers all accounts
        seen.add(h["symbol"])
        tax = CFG["move_out"]["tax_gate_lt_gain_note"] if h["account"] == "schwab_taxable" else "IRA — no tax gate"
        # C3: full-exit language is BANNED on core cards — trim-ladder only, round-trip
        # by construction; the deepest core action is the config max-trim
        entry_logic = ("trim-ladder only (★CORE): reduce into strength, stage over 2–3 sessions; "
                       "every confirmed tranche opens a patient re-entry watch — this position comes back"
                       if h_core else
                       "reduce into strength, not into a flush; stage over 2–3 sessions; "
                       "full exit only on continued deterioration")
        card = {
            "id": f"moveout-{h['symbol']}-{h['account']}-{as_of}", "group": "protect",
            "title": f"{'★CORE TRIM' if h_core else 'MOVE-OUT'} · {h['symbol']} (${sum(a['value'] for a in acct_rows)/1000:.0f}K"
                     f"{' across ' + str(len(acct_rows)) + ' accounts' if len(acct_rows) > 1 else ' in ' + CFG['account_labels'].get(h['account'], h['account'])})",
            "instruments": [{"symbol": h["symbol"], "kind": "held position",
                             "note": f"{h['shares']:.0f} sh", "price": h["price"] or None}],
            "accounts": sorted({a["account"] for a in acct_rows}),
            "direction": "trim (core — never full exit)" if h_core else "reduce/exit",
            "is_core": h_core,
            "size_band": plan["rationale"],
            "trim_rationale": plan["rationale"],
            "trim_plan": plan,
            "ticket": ticket,
            "entry_logic": entry_logic,
            "invalidation": "sector recovers out of WEAKENING/LAGGING (2-close) AND price reclaims the 50DMA",
            "factors": factors + [{"name": "tax gate", "value": tax}],
            "as_of": as_of, "mode": "SHADOW",
            "levels": {"price": h["price"] or None, "position_value": round(sum(a["value"] for a in acct_rows)),
                       "basis_note": "unrealized P&L n/a — Cost Basis export pending"},
            "impact_dollars": round(sum(a["value"] for a in acct_rows)),
            "routes": {"shadow": f"10-trading-day shadow started {c['shadow_started']} — Telegram only after promote",
                       "round_trip": "registers in the round-trip ledger; ladder arms T2 at creation"},
        }
        cards.append(card)
        # EL1 — arm the ladder at creation (idempotent)
        try:
            dtl.ensure_ladder_tables(cur)
            dtl.arm_ladder(cur, card, plan, sector_name, (sec or {}).get("state"),
                           len(factors), urgent)
        except Exception as ex:
            cur.connection.rollback()
            print(f"[recs] ladder arm failed for {h['symbol']}: {ex}")
        if len(cards) >= c["max_cards"]:
            break
    # L2: residual scraps collapse to ONE janitorial card — never dressed as strategy
    if scraps:
        names = sorted(scraps, key=lambda x: -x["value"])
        cards.append({
            "id": f"cleanup-{as_of}", "group": "protect",
            "title": f"CLEANUP · {len(names)} residual scraps ≤${floor/1000:.1f}K — consolidate or close; not strategy",
            "instruments": [{"symbol": s["symbol"], "kind": "residual",
                             "note": f"${s['value']:.0f} in {CFG['account_labels'].get(s['account'], s['account'])}"}
                            for s in names[:10]],
            "accounts": sorted({s["account"] for s in names}),
            "direction": "janitorial", "size_band": f"total ${sum(s['value'] for s in names)/1000:.1f}K across {len(names)} lines",
            "entry_logic": "close or consolidate at convenience — market timing is irrelevant at this size",
            "invalidation": "n/a — housekeeping, not a thesis",
            "factors": [{"name": "materiality floor", "value": f"${floor:,.0f} ({CFG['materiality']['min_position_pct_of_book']}% of book)"}],
            "as_of": as_of, "mode": "SHADOW",
            "levels": {"price": None, "position_value": round(sum(s["value"] for s in names))},
            "impact_dollars": round(sum(s["value"] for s in names)),
            "routes": {"note": "scraps no longer generate individual MOVE-OUT cards"},
        })
    return cards


def stances(sectors, holdings, cur, enrich, hermes, as_of) -> list:
    """L3: every ≥$10K position gets an explicit stance — including HOLD.
    Funds judge by lookthrough-weighted sector states; silence about the core
    was the failure, assessed-and-holding is the fix."""
    from fund_lookthrough import _cfg as _lt_cfg
    lt = _lt_cfg()
    smap = _sector_map(sectors)
    state_by_sector = {r["sector"]: r for r in sectors}
    floor = CFG["materiality"]["stance_min_dollars"]
    # aggregate same symbol+account rows (holdings.json can split lots)
    agg = {}
    for h in holdings:
        k = (h["symbol"], h["account"])
        if k in agg:
            agg[k]["value"] += h["value"]
            agg[k]["shares"] += h["shares"]
        else:
            agg[k] = dict(h)
    out = []
    for h in sorted(agg.values(), key=lambda x: -x["value"]):
        if h["value"] < floor:
            continue
        sym = h["symbol"]
        fund = lt.get(sym)
        if fund and fund.get("weights"):
            weak = sum(w for s, w in fund["weights"].items()
                       if (state_by_sector.get(s) or {}).get("state") in ("WEAKENING", "LAGGING"))
            worst = max(fund["weights"], key=lambda s: fund["weights"][s])
            worst_state = (state_by_sector.get(worst) or {}).get("state") or "?"
            # v8.1 C2 — industry-level coherence for the ≥$50K funds (top-10 factsheet weights)
            ind_line = ""
            if fund.get("industries"):
                ind_states = {g["industry"]: g.get("state")
                              for g in _load("industry_momentum_latest.json").get("industries", [])}
                tot_w = sum(fund["industries"].values()) or 1
                lag = [(i, w) for i, w in fund["industries"].items()
                       if ind_states.get(i) in ("LAGGING", "WEAKENING")]
                if lag:
                    worst_inds = ", ".join(i.split(" - ")[0] for i, _ in
                                           sorted(lag, key=lambda x: -x[1])[:2])
                    ind_line = (f" · ~{sum(w for _, w in lag)/tot_w*100:.0f}% of top-10 industry "
                                f"weight in LAGGING/WEAKENING ({worst_inds})")
                else:
                    ind_line = " · top-10 industries LEADING/neutral"
            if weak >= 0.33:
                stance, reason = "TRIM-WATCH", (
                    f"{weak*100:.0f}% of fund weight sits in WEAKENING/LAGGING sectors "
                    f"(top: {worst} {fund['weights'][worst]*100:.0f}% → {worst_state}); no stop on funds" + ind_line)
            else:
                stance, reason = "HOLD", (
                    f"{(1-weak)*100:.0f}% of fund weight in LEADING/IMPROVING sectors; "
                    f"top sleeve {worst} {fund['weights'][worst]*100:.0f}% → {worst_state}" + ind_line)
            sec_label = "fund (lookthrough)"
        elif fund and fund.get("lookthrough") == "none":
            stance, reason, sec_label = "HOLD", f"not decomposed — {fund.get('why', 'no lookthrough map')}", "fund (not decomposed)"
        else:
            prof = _profiles_one(cur, sym)
            sec = smap.get((prof or {}).get("sector") or "")
            e = enrich.get(sym) or {}
            hz = hermes.get(sym) or {}
            factors = _fired_factors(h, sec, e, hz)
            sec_label = (sec or {}).get("sector") or "?"
            st = (sec or {}).get("state") or "?"
            if len(factors) >= CFG["move_out"]["factor_threshold"]:
                stance = "TRIM"
                reason = " · ".join(f"{f['name']} {f['value']}" for f in factors[:2]) + f" ({len(factors)} factors fired)"
            elif st == "LEADING" and (e.get("sma50_pct") or 0) > 0:
                stance = "HOLD" if (sec or {}).get("book_pct", 0) >= CFG["underweight_floor_pct"] else "ADD"
                reason = f"{sec_label} LEADING (RS20 {(sec or {}).get('rs20', 0):+.1f}), above 50DMA" + \
                         ("" if stance == "HOLD" else f" · sector only {(sec or {}).get('book_pct')}% of book")
            elif factors:
                stance = "HOLD"
                reason = f"{sec_label} {st} · watch: " + " · ".join(f"{f['name']} {f['value']}" for f in factors[:2])
            else:
                stance = "HOLD"
                reason = f"{sec_label} {st}, no factors fired"
        # v8.9 alignment (ARKX finding): a live trim advisory/escalated ladder must
        # AGREE with the stance — TRIM-WATCH cannot coexist with a FIRED tranche
        try:
            cur.execute("""SELECT t1_fraction, t1_status, tranches FROM rotation_ladders
                           WHERE symbol=%s AND account=%s AND status='open'""", (sym, h["account"]))
            lad_row = cur.fetchone()
        except Exception:
            cur.connection.rollback()
            lad_row = None
        if lad_row and stance in ("TRIM-WATCH", "HOLD"):
            trs = lad_row[2] if isinstance(lad_row[2], list) else json.loads(lad_row[2] or "[]")
            fired_tr = [t["tranche"] for t in trs if t.get("status") == "fired"]
            supp_chk = any(x["symbol"] == sym and not x.get("until")
                           for x in CFG.get("operator_suppressions", []))
            if not supp_chk:
                stance = "TRIM"
                reason = (f"upgraded from watch: live trim ladder T1 {lad_row[0]}% {lad_row[1]}"
                          + (f" · {'/'.join(fired_tr)} FIRED — escalation live" if fired_tr else "")
                          + " · " + reason)
        supp2 = next((x for x in CFG.get("operator_suppressions", [])
                      if x["symbol"] == sym and not x.get("until")), None)
        if supp2:
            reason += f" · TRIM ADVISORIES MUTED by operator {supp2['set']} (engine factors still shown — remove the config entry to unmute)"
        lean = (CFG.get("rotation_pairs") or {}).get("defensive_lean") or {}
        on_trigger = None
        if stance in ("TRIM", "TRIM-WATCH") and lean.get("enabled"):
            dests = "/".join(s0[:3] for s0 in []) or " · ".join(
                ["XLU/XLP/XLV (defensive sectors, if LEADING+underweight)",
                 "SCHD (income core, style-aligned)" if lean.get("allow_income_destination") else None,
                 "cash (money-market sweep) — the default when nothing qualifies"])
            on_trigger = (f"if the trim fires (defensive lean, operator directive 2026-07-18): "
                          f"proceeds → {dests}")
        out.append({"symbol": sym, "account": h["account"],
                    "account_label": CFG["account_labels"].get(h["account"], h["account"]),
                    "value": round(h["value"]), "stance": stance, "reason": reason,
                    "on_trigger": on_trigger,
                    "sector": sec_label, "as_of": as_of,
                    "is_core": is_core(_CORE_CACHE, sym, h["account"])})
    return out


_CORE_CACHE: set = set()


def inverse_etf(sectors, market, as_of, cur=None, equities=None) -> list:
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
        inst_px = _prices(cur, [inst]).get(inst) if cur else None
        accounts = sorted(k for k, v in CAPS.items() if v.get("inverse_etf_ok"))
        band = dollars_band(c["size_band_pct"], accounts, equities or {})
        # v6.1 operator ask: a CLEAR, ACTIONABLE playbook — when to get in after
        # highs (bounce days), when to take profits, when to stand down — with
        # matching alerts maintained nightly on the 20-min evaluator
        pb = CFG["hedge_playbook"]
        idx_sym = "QQQ" if tech_led else "SPY"
        idx_px = _prices(cur, [idx_sym]).get(idx_sym) if cur else None
        tp1 = round(inst_px * (1 + pb["take_profit_1_pct"] / 100), 2) if inst_px else None
        tp2 = round(inst_px * (1 + pb["take_profit_2_pct"] / 100), 2) if inst_px else None
        bounce_lvl = round(idx_px * (1 + pb["bounce_day_pct"] / 100), 2) if idx_px else None
        playbook = [
            f"1 · GET IN on BOUNCE days: {idx_sym} up ≥ +{pb['bounce_day_pct']}% (≥ ${bounce_lvl}) while the trigger state holds — "
            f"the hedge is at a discount when the index pops. Buy 1/{pb['tranches']} per bounce day, never after a big down day (you'd pay up). ALERT armed: '{idx_sym} bounce — hedge entry window'.",
            f"2 · TAKE PROFITS in halves: {inst} +{pb['take_profit_1_pct']}% (≈ ${tp1}) → sell half. ALERT armed. "
            f"{inst} +{pb['take_profit_2_pct']}% (≈ ${tp2}) or a capitulation gap-down in {idx_sym} → take the rest. ALERT armed.",
            "3 · STAND DOWN regardless of P&L when the trigger state exits (2-close confirmed) — the hedge's job ended; holding an inverse ETF past its reason bleeds daily-reset decay.",
            "4 · Levels recompute nightly until an entry is recorded (auto-detected from Schwab ingest or your tap on the paper twin).",
        ]
        if cur and inst_px and idx_px:
            for sym_a, cond, thr, note in [
                (idx_sym, "price_cross_above", bounce_lvl, f"defense hedge: {idx_sym} bounce day — hedge entry window ({inst})"),
                (inst, "price_cross_above", tp1, f"defense hedge: {inst} +{pb['take_profit_1_pct']}% — take profits on HALF"),
                (inst, "price_cross_above", tp2, f"defense hedge: {inst} +{pb['take_profit_2_pct']}% — take remaining profits"),
            ]:
                try:
                    cur.execute("""SELECT id FROM watch_alerts WHERE symbol=%s AND condition_type=%s
                                   AND created_by='defense_hedge' AND note=%s LIMIT 1""",
                                (sym_a, cond, note))
                    row = cur.fetchone()
                    if row:
                        cur.execute("UPDATE watch_alerts SET threshold=%s, active=true WHERE id=%s",
                                    (thr, row[0]))
                    else:
                        cur.execute("""INSERT INTO watch_alerts (symbol, condition_type, threshold,
                                       recurring, cooldown_days, active, created_by, note)
                                       VALUES (%s,%s,%s,true,1,true,'defense_hedge',%s)""",
                                    (sym_a, cond, thr, note))
                except Exception:
                    cur.connection.rollback()
        cards.append({
            "id": f"inverse-{inst}-{as_of}", "group": "short_side",
            "title": f"HEDGE · {inst} (1x inverse {'QQQ — deterioration is tech-led' if tech_led else 'S&P 500'})",
            "instruments": [{"symbol": inst, "kind": "inverse ETF", "note": c["decay_warning"],
                             "price": inst_px}],
            "accounts": accounts,
            "direction": "long (inverse exposure)",
            "size_band": f"{c['size_band_pct'][0]}–{c['size_band_pct'][1]}% of account equity"
                         + (f" (≈${at_risk/1000:.0f}K book in triggered sectors)" if at_risk else ""),
            "entry_logic": "scale in on bounce days, not after down days — hedges bought into weakness overpay",
            "invalidation": c["exit_rule"],
            "factors": factors, "as_of": as_of, "mode": "SHADOW",
            "playbook": playbook,
            "levels": {"price": inst_px,
                       "entry_zone": f"bounce days only — {idx_sym} ≥ ${bounce_lvl} (+{pb['bounce_day_pct']}%)" if bounce_lvl else "scale in on bounce days",
                       "stop": f"take-profit ${tp1} / ${tp2}; hard exit on trigger-state exit (2-close)" if tp1 else "exit when trigger state exits"},
            "dollars_by_account": band,
            "impact_dollars": round(at_risk) or max((v[1] for v in band.values()), default=0),
            "routes": {"paper_twin": "inverse-ETF paper track via approval queue"},
        })
    return cards


def taxable_short(industries, cur, enrich, as_of, held_symbols=frozenset(), equities=None) -> list:
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
            "levels": {"price": x["price"], "entry_zone": f"near ${x['price']:.2f}",
                       "stop": f"buy-stop ${stop:.2f} ({risk_per_sh / x['price'] * 100:+.1f}%)"},
            "impact_dollars": round((equities or {}).get("schwab_taxable", 0) * c["size_cap_pct_of_book"] / 100),
            "routes": {"paper_twin": "defensive_short paper strategy via approval queue"},
        })
    return cards


def covered_calls(sectors, holdings, cur, as_of, total_book=0) -> list:
    c = CFG["covered_call"]
    smap = _sector_map(sectors)
    radar = {r["symbol"]: r for r in (_load("hedging_radar_latest.json").get("radar") or [])}
    floor = max(c["min_position_dollars"], _materiality_min(total_book))
    cards = []
    for h in holdings:
        if h["value"] < floor or h["shares"] < 100:
            continue
        acct_caps = CAPS.get(h["account"]) or {}
        if not acct_caps.get("covered_calls_ok"):
            continue
        sec = smap.get((_profiles_one(cur, h["symbol"]) or {}).get("sector") or "")
        if not sec or sec.get("state") not in ("WEAKENING", "LAGGING"):
            continue
        n = int(h["shares"] // 100)
        cc = (radar.get(h["symbol"]) or {}).get("cc_call")
        px = (radar.get(h["symbol"]) or {}).get("underlying_price") or h["price"]
        if cc and px and cc.get("validated"):
            prem = round(cc["mid"] * 100 * n)
            prem_pct = round(prem / h["value"] * 100, 1) if h["value"] else 0
            cap_pct = round((cc["strike"] - px) / px * 100, 1)
            exp_short = cc["exp"][5:] if len(cc["exp"]) >= 10 else cc["exp"]
            struct_note = (f"sell {n}× {exp_short} ${cc['strike']}C (~{cc['delta']}Δ, {cc['dte']}d) · "
                           f"est ${prem} ({prem_pct}% of position) · caps upside at +{cap_pct}%")
            levels = {"price": px, "entry_zone": f"strike ${cc['strike']} ({cc['exp']})",
                      "stop": f"caps upside at +{cap_pct}%; premium ≈ ${prem}"}
        elif cc and px and not cc.get("validated"):
            cc_note = cc.get("validation", "failed liquidity rails")
            cc = None
            struct_note = (f"{c['tenor_dte'][0]}–{c['tenor_dte'][1]} DTE · {c['delta_band'][0]}–{c['delta_band'][1]}Δ "
                           f"(best chain candidate WITHHELD: {cc_note})")
            levels = {"price": px or None, "entry_zone": "per delta band", "stop": "upside capped at chosen strike"}
        else:
            struct_note = (f"{c['tenor_dte'][0]}–{c['tenor_dte'][1]} DTE · {c['delta_band'][0]}–{c['delta_band'][1]}Δ "
                           "(no chain pick in tonight's snapshot — strike from the chain at entry)")
            levels = {"price": px or None, "entry_zone": "per delta band", "stop": "upside capped at chosen strike"}
        cards.append({
            "id": f"cc-{h['symbol']}-{h['account']}-{as_of}", "group": "income",
            "title": f"COVERED CALL · {h['symbol']} ({n} contract{'s' if n != 1 else ''}, {CFG['account_labels'].get(h['account'], h['account'])})",
            "instruments": [{"symbol": h["symbol"], "kind": "covered call", "note": struct_note, "price": px}],
            "accounts": [h["account"]], "direction": "sell call vs held shares",
            "size_band": f"{n} contract{'s' if n != 1 else ''} against {h['shares']:.0f} sh (${h['value']/1000:.0f}K)",
            "entry_logic": "sell into up-days/IV pops; premium honesty: income caps upside — defensive yield, not a lottery hedge",
            "invalidation": f"{sec['sector']} recovers out of {sec['state']} — let calls expire/close, stop rolling",
            "factors": [
                {"name": "sector state", "value": f"{sec['sector']} {sec['state']} (RS20 {sec['rs20']:+.1f})"},
                {"name": "position", "value": f"${h['value']/1000:.0f}K · {h['shares']:.0f} sh"},
            ] + ([{"name": "greeks/liquidity VALIDATED", "value": cc["validation"]},
                  {"name": "order book", "value": f"${cc['bid']} × ${cc['ask']} (spread {cc['spread_pct']}%) · OI {cc['oi']}"}]
                 if cc else []),
            "as_of": as_of, "mode": "SHADOW",
            "levels": levels, "impact_dollars": round(h["value"]),
            "cc_struct": ({"symbol": h["symbol"], "account": h["account"], "contracts": n,
                           "strike": cc["strike"], "exp": cc["exp"], "delta": cc["delta"],
                           "mid": cc["mid"], "premium_est": round(cc["mid"] * 100 * n)}
                          if cc else None),
            "routes": {"options_desk": "queue → operator approval → per-order 2FA (the desk itself never places orders)"},
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
            try:
                cur.execute("""INSERT INTO paper_trade_proposals
                    (symbol, strategy_id, side, proposed_entry, proposed_stop, proposed_target1,
                     proposed_shares, proposed_dollar_size, status, proposed_by, origin,
                     setup_description, expires_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'PENDING','defense_recommendations','auto',%s,%s)""",
                    (inst["symbol"], strategy, "short" if short else "long", entry, stop, target,
                     shares, c["dollar_size"], card["title"][:180],
                     datetime.now(timezone.utc) + timedelta(hours=c["expires_hours"])))
            except Exception as ex:
                # DB-level guards (max-pending-per-symbol trigger etc.) are AUTHORITATIVE —
                # skip the twin, never kill the run
                cur.connection.rollback()
                print(f"[recs] twin skipped for {inst['symbol']}: {str(ex).splitlines()[0][:100]}")
                continue
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

    equities = account_equities(holdings)
    total_book = sum(equities.values())

    h_raw = json.loads((ROOT / "data" / "portfolios" / "state" / "holdings.json").read_text())
    as_of_label = f"prices as of {str(h_raw.get('as_of', ''))[:16]} (holdings snapshot)"

    cards = []
    cards += rotate_in(sectors, cur, enrich, as_of, equities=equities)
    cards += move_out(sectors, holdings, cur, enrich, hermes, as_of, total_book=total_book,
                      as_of_label=as_of_label)
    cards += inverse_etf(sectors, market, as_of, cur=cur, equities=equities)
    cards += taxable_short(industries, cur, enrich, as_of,
                           held_symbols=frozenset(h["symbol"] for h in holdings),
                           equities=equities)
    cards += covered_calls(sectors, holdings, cur, as_of, total_book=total_book)
    cards.append(options_locked_card(as_of))
    if not args.dry_run:
        # commit card-phase writes (ladder arms, hedge-alert registrations) NOW —
        # later per-row fail-soft rollbacks must never erase them (learned twice)
        conn.commit()

    ok, dropped = [], []
    for card in cards:
        missing = validate(card)
        if missing:
            dropped.append({"id": card.get("id", "?"), "missing": missing})
        else:
            ok.append(card)

    twins = paper_twins(ok, cur, args.dry_run)

    # WS-L3 stances + WS-RT round-trip ledger (core registry loaded first — chips + semantics)
    global _CORE_CACHE
    _CORE_CACHE = core_set(cur)
    stance_rows = stances(sectors, holdings, cur, enrich, hermes, as_of)
    import rotation_round_trips as rt
    rt.ensure_tables(cur)
    sector_states = {r["sector"]: r.get("state") for r in sectors}
    if not args.dry_run:
        rt.register_advisories(cur, ok, sector_states)
        rt.detect_fills(cur)
        import defense_trim_ladders as _dtl_af
        _dtl_af.ensure_ladder_tables(cur)
        auto_n = _dtl_af.detect_tranche_fills(cur)
        if auto_n:
            print(f"[recs] auto-detected {auto_n} tranche execution(s) from Schwab ingest")
    rt_prices = _prices(cur, list({x[0] for x in
                                   [(h["symbol"], 0) for h in holdings]}) or ["SPY"])
    round_trips = rt.evaluate(cur, sector_states, rt_prices, enrich)
    # C3: core rollback-open rows rank FIRST in every digest surface
    round_trips.sort(key=lambda t: (t["status"] != "rollback_open",
                                    not is_core(_CORE_CACHE, t["symbol"], t["account"])))
    for t in round_trips:
        t["is_core"] = is_core(_CORE_CACHE, t["symbol"], t["account"])

    # EL2/RP2 — nightly ladder evaluation (fire AND disarm) + the Rotation Plan rows
    import defense_trim_ladders as dtl
    dtl.ensure_ladder_tables(cur)
    factor_counts = {}
    smap_all = _sector_map(sectors)
    for h in holdings:
        prof = _profiles_one(cur, h["symbol"])
        sec_r = smap_all.get((prof or {}).get("sector") or "")
        factor_counts[(h["symbol"], h["account"])] = len(
            _fired_factors(h, sec_r, enrich.get(h["symbol"]) or {}, hermes.get(h["symbol"]) or {}))
    ladders = dtl.evaluate_ladders(cur, sector_states, factor_counts, dtl.gg_latest(cur))
    plan_rows = dtl.rotation_plan(cur, stance_rows, ladders, round_trips)
    if not args.dry_run:
        conn.commit()

    # v6 WS-PAIR — funded rotation pairs supersede their singles (never deleted)
    import defense_rotation_pairs as drp
    pair_prices = _prices(cur, [i["symbol"] for c in ok for i in c.get("instruments", [])
                                if i.get("symbol") and i["symbol"] != "—"] +
                          [drp.PC["income_destination"]])
    pairs, superseded_ids = drp.build_rotation_pairs(
        cur, [c for c in ok if c["id"].startswith("moveout-")],
        [c for c in ok if c["group"] == "get_into"],
        market, pair_prices, sectors, total_book, as_of, dry_run=args.dry_run)
    pairs = [p for p in pairs if drp.validate_pair(p) is None]
    for c in ok:
        if c["id"] in superseded_ids:
            c["superseded_by_pair"] = True
        elif c["id"].startswith("moveout-"):
            # v8.1 C1 — cash IS a recommendation, never a void
            c["destination"] = (
                "→ cash (money-market sweep) while the sector thesis stays broken · "
                f"redeploy when: {c['invalidation'][:90]} · "
                "no equity pair qualified (no same-account destination cleared the \$2K-leg rails)")

    # v8.1 C3 — coherence lint: the desk confesses its own contradictions
    tensions = []
    stance_by = {(x["symbol"], x["account"]): x for x in stance_rows}
    for lad in ladders:
        st = stance_by.get((lad["symbol"], lad["account"]))
        if st and st["stance"] in ("HOLD", "TRIM-WATCH") and lad.get("status") == "open" and any(
                t.get("status") == "fired" for t in lad.get("tranches", [])) or (
                st and st["stance"] == "HOLD" and lad.get("status") == "open"):
            t = (f"{lad['symbol']}: stance HOLD but a {lad['t1_fraction']}% trim ladder is open — "
                 "explanation: the ladder came from an earlier factor set; if HOLD is right, disarm it")
            tensions.append(t)
            st["tension"] = t
    for pcard in pairs:
        for leg in pcard.get("buy_legs", []):
            sec_leg = leg.get("sector")
            row = next((r for r in sectors if r["sector"] == sec_leg), None)
            if row and row.get("state") in ("LAGGING", "WEAKENING"):
                t = f"pair {pcard['id']}: buy leg {leg['symbol']} targets {sec_leg} which is {row['state']}"
                tensions.append(t)
                pcard["tension"] = t
    for c in ok:
        if c["id"].startswith("moveout-") and not c.get("superseded_by_pair") and not c.get("destination"):
            tensions.append(f"{c['id']}: trim without destination (guard breach)")
    # v8.5 — share-commitment collision (the Opus catch): the SAME held shares must
    # never be promised to a trim AND a covered call; at least one card cannot execute
    held_sh = {(h["symbol"], h["account"]): h["shares"] for h in holdings}
    commits = {}
    for c in ok:
        sym = c["instruments"][0]["symbol"]
        if c["id"].startswith("moveout-"):
            for o in (c.get("ticket") or {}).get("options", []):
                k = (sym, o["account"])
                commits.setdefault(k, []).append((c["id"], "trim", o["shares"]))
        elif c["id"].startswith("cc-"):
            k = (sym, c["accounts"][0])
            n = int(str(c.get("size_band", "0")).split(" contract")[0].split()[-1] or 0)
            commits.setdefault(k, []).append((c["id"], "covered_call", n * 100))
    for (sym, acct), lst in commits.items():
        total = sum(x[2] for x in lst)
        held = held_sh.get((sym, acct), 0)
        if len({x[1] for x in lst}) > 1 and total > held:
            t = (f"{sym} ({acct.replace('schwab_', '')}): {total:g} shares committed across "
                 f"{'+'.join(x[1] for x in lst)} but only {held:g} held — at least one card "
                 "cannot execute; pick ONE use for the shares")
            tensions.append(t)
            for cid, _, _ in lst:
                card = next((c for c in ok if c["id"] == cid), None)
                if card:
                    card["tension"] = t
    if not args.dry_run:
        conn.commit()

    groups = {g: sorted([c for c in ok if c["group"] == g],
                        key=lambda c: -(c.get("impact_dollars") or 0))
              for g in ("get_into", "protect", "short_side", "income")}
    empty_reasons = {
        "get_into": ("DEFENSIVE LEAN active: cyclical rotate-ins excluded — no defensive sector "
                     "(Utilities/Staples/Healthcare) is LEADING+underweight right now"
                     if (CFG.get("rotation_pairs") or {}).get("defensive_lean", {}).get("enabled")
                     else "no LEADING/IMPROVING sector is underweight vs your neutral map"),
        "protect": "no held position fired ≥%d factors" % CFG["move_out"]["factor_threshold"],
        "short_side": "no trigger: no >10%-book sector WEAKENING/LAGGING and short pool produced no clean candidate",
        "income": "no ≥100-share holding sits in a WEAKENING/LAGGING sector",
    }
    snap = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of": as_of, "mode": "SHADOW",
        "shadow_note": f"all groups SHADOW — 10-trading-day window from {CFG['move_out']['shadow_started']}; Telegram only after promote",
        "groups": groups,
        "pairs": pairs,
        "empty_reasons": {g: empty_reasons[g] for g in groups if not groups[g]},
        "dropped_by_field_guard": dropped,
        "paper_twins_created": twins,
        "accounts": {k: CFG["account_labels"].get(k, k) for k in sorted(CAPS.keys())},
        "account_equities": equities,
        "stances": stance_rows,
        "round_trips": round_trips,
        "ladders": ladders,
        "rotation_plan": plan_rows,
        "exposure_basis": sector_snap.get("exposure_basis"),
        "not_decomposed": sector_snap.get("not_decomposed"),
        "operator_items": CFG.get("operator_items", []),
        "tensions": tensions,
        "sources": {
            "sectors": sector_snap.get("generated_at"),
            "industries": industries.get("captured_at"),
            "hedging_radar": (_load("hedging_radar_latest.json") or {}).get("captured_at"),
        },
    }
    if not args.dry_run:
        SNAP.write_text(json.dumps(snap, default=str))
    if not args.dry_run:
        try:
            import defense_oversight as do
            ov = do.run_free_critiques(cur)
            conn.commit()
            print(f"[recs] oversight seats: {ov['seats']}")
        except Exception as e:
            conn.rollback()
            print(f"[recs] oversight skipped: {str(e).splitlines()[0][:90]}")
    print(f"[recs] {sum(len(v) for v in groups.values())} cards "
          f"({', '.join(f'{g}:{len(v)}' for g, v in groups.items())}) · "
          f"{len(dropped)} dropped by field guard · {len(twins)} paper twins")
    return 0


if __name__ == "__main__":
    sys.exit(main())
