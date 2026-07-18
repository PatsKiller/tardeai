#!/usr/bin/env python3
"""defense_rotation_pairs.py — Defense v6 WS-PAIR: out of X, into Y, one card.

build_rotation_pairs(): for each trim card's sell ticket, match rotate-in
destinations IN THE SAME ACCOUNT ONLY (cross-account funding is a contribution/
rollover event, not a rotation — if a better home exists elsewhere it renders as
a NOTE, never a funded leg), allocate estimated proceeds across the top
destinations (rank × underweight gap; style-aligned income boost when the market
layer shows growth lagging equal-weight/value), and emit a PAIR card that
SUPERSEDES the two singles in the rail — singles stay reachable, never deleted.

Both legs ticketed or the card does not render (field-guard extension).
Buy legs stage through paper_trade_proposals PENDING (family-gated operator
approval). Pair outcomes score as a UNIT (source_type=rotation_pair) when the
sell slice's round trip closes. Advisory-only; estimates, never orders.
"""
import json
import math
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "config" / "defense_recommendations.json").read_text())
PC = CFG["rotation_pairs"]


def ensure_pair_tables(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS defense_rotation_pairs (
        id serial PRIMARY KEY, pair_id text UNIQUE NOT NULL, as_of date NOT NULL,
        source_symbol text, source_account text, ladder_advisory_id text,
        destinations jsonb, style_rationale text, status text DEFAULT 'open',
        created_at timestamptz DEFAULT now(), closed_at timestamptz, outcome jsonb)""")


def _style_read(market: dict) -> dict:
    """The existing style spreads → is the tape rotating away from growth?"""
    styles = {s["key"]: s for s in (market or {}).get("styles", [])}
    eq = styles.get("equal_vs_cap") or {}
    gv = styles.get("growth_vs_value") or {}
    away_from_growth = (eq.get("state") == "LEADING" and (eq.get("s20") or 0) > 1)
    bits = []
    if eq.get("state"):
        bits.append(f"equal-weight {eq['s20']:+.1f}% over cap-weight 20d ({eq['state']})")
    if gv.get("state"):
        bits.append(f"VUG−VTV {gv.get('s20', 0):+.1f} ({gv['state']})")
    return {"away_from_growth": away_from_growth,
            "rationale": ("style rotation: " + " · ".join(bits) +
                          (" — broadening away from megacap growth" if away_from_growth else ""))
                         if bits else "style layer neutral"}


def _destinations_for(account: str, rotate_cards: list, style: dict, source_symbol: str,
                      holdings_by_sym_acct: dict, prices: dict, sectors_by_name: dict) -> list:
    """Ranked destination candidates valid in this account. Never forced."""
    from fund_lookthrough import _cfg as _lt_cfg
    lean = PC.get("defensive_lean") or {}
    dests = []
    for rank, rc in enumerate(rotate_cards):
        if account not in rc.get("accounts", []):
            continue
        if lean.get("enabled"):
            sec_name = rc["title"].split("· ")[1].split(" (")[0] if "· " in rc["title"] else ""
            if sec_name not in lean.get("defensive_sectors", []):
                continue  # DEFENSIVE LEAN (operator directive): cyclical destinations excluded
        etf = rc["instruments"][0]
        sector = rc["title"].split("· ")[1].split(" (")[0] if "· " in rc["title"] else None
        row = sectors_by_name.get(sector) or {}
        gap = max(0.0, CFG["underweight_floor_pct"] - (row.get("book_pct") or 0))
        score = (len(rotate_cards) - rank) * (1 + gap * PC["underweight_gap_weight"])
        dests.append({"symbol": etf["symbol"], "kind": f"sector ETF ({sector})",
                      "why": f"{sector} {row.get('state', '')} RS20 {row.get('rs20', 0):+.1f} · book {row.get('book_pct', 0)}%",
                      "price": etf.get("price") or prices.get(etf["symbol"]),
                      "sector": sector, "score": round(score, 2)})
    # style-aligned income destination (the operator's SCHG→SCHD question)
    lt = _lt_cfg()
    src_fund = lt.get(source_symbol) or {}
    growth_heavy = source_symbol in PC["growth_heavy_symbols"] or (
        src_fund.get("weights") and sum(src_fund["weights"].get(s, 0) for s in
        ("Technology", "Consumer Discretionary", "Communications")) > 0.5)
    if style["away_from_growth"] and growth_heavy:
        inc = PC["income_destination"]
        base = max((d["score"] for d in dests), default=1.0)
        dests.append({"symbol": inc, "kind": "income core (style-aligned)",
                      "why": "dividend sleeve — " + style["rationale"],
                      "price": prices.get(inc), "sector": "income sleeve",
                      "score": round(base * PC["style_boost"], 2)})
    return sorted([d for d in dests if d.get("price")], key=lambda d: -d["score"])


def build_rotation_pairs(cur, trim_cards: list, rotate_cards: list, market: dict,
                         prices: dict, sectors: list, total_book: float, as_of: str,
                         dry_run: bool = False) -> tuple:
    """→ (pair_cards, superseded_ids). Same-account only; both legs ticketed or no card."""
    ensure_pair_tables(cur)
    cur.connection.commit()  # DDL must survive later fail-soft rollbacks
    style = _style_read(market)
    sectors_by_name = {r["sector"]: r for r in sectors}
    pairs, superseded = [], set()
    for tc in trim_cards:
        if not tc["id"].startswith("moveout-") or not (tc.get("ticket") or {}).get("options"):
            continue
        src = tc["instruments"][0]["symbol"]
        for opt in tc["ticket"]["options"]:
            acct = opt["account"]
            dests = _destinations_for(acct, rotate_cards, style, src, {}, prices, sectors_by_name)
            # allocate proceeds: score-weighted across top N, min per leg, whole shares
            picks = dests[:PC["max_destinations"]]
            tot_score = sum(d["score"] for d in picks) or 1.0
            legs = []
            lean_cap = ((PC.get("defensive_lean") or {}).get("max_single_destination_pct")
                        if (PC.get("defensive_lean") or {}).get("enabled") else None)
            for d in picks:
                alloc = opt["proceeds_est"] * d["score"] / tot_score
                if lean_cap:
                    alloc = min(alloc, opt["proceeds_est"] * lean_cap / 100)  # never pile one sector
                if alloc < PC["min_leg_dollars"]:
                    continue
                sh = math.floor(alloc / d["price"])
                if sh < 1:
                    continue
                legs.append({**d, "alloc_est": round(sh * d["price"]), "shares": sh,
                             "line": f"buy ≈ {sh} sh {d['symbol']} @ ~${d['price']:.2f} ≈ ${sh*d['price']/1000:.1f}K ({d['kind']})"})
            lean_cfg = PC.get("defensive_lean") or {}
            allocated = sum(l["alloc_est"] for l in legs)
            if lean_cfg.get("enabled") and lean_cfg.get("cash_remainder") and \
                    opt["proceeds_est"] - allocated > PC["min_leg_dollars"]:
                rem = round(opt["proceeds_est"] - allocated)
                legs.append({"symbol": "CASH", "kind": "money-market sweep", "price": 1.0,
                             "sector": "cash", "score": 0, "alloc_est": rem, "shares": rem,
                             "why": "defensive lean: no further defensive destination qualified — cash IS the position",
                             "line": f"hold ≈ ${rem/1000:.1f}K in cash (money-market sweep) — defensive lean; redeploy when the tape confirms risk-on"})
            if not legs:
                continue
            # cross-account note (never a funded leg): a destination that ranked but
            # isn't valid here — same-account rule renders it as information only
            note = None
            all_dest = _destinations_for(acct, rotate_cards, style, src, {}, prices, sectors_by_name)
            invalid = [rc["instruments"][0]["symbol"] for rc in rotate_cards
                       if acct not in rc.get("accounts", [])]
            if invalid:
                note = (f"note: {'/'.join(invalid[:2])} ranks as a destination but only in another "
                        "account — cross-account funding is a contribution/rollover event, not a rotation")
            sector_after = opt.get("sector_after") or {}
            income_pp = round(sum(l["alloc_est"] for l in legs if l["sector"] == "income sleeve")
                              / total_book * 100, 1) if total_book else 0
            pair_id = f"pair-{src}-{acct}-{as_of}"
            tax = "IRA — no tax event" if acct != "schwab_taxable" else \
                "TAXABLE — wash-sale window applies on the sell leg; verify with tax context (Alex)"
            card = {
                "id": pair_id, "group": "pair",
                "title": f"ROTATE · {src} → {' + '.join(l['symbol'] for l in legs)} ({CFG['account_labels'].get(acct, acct)})",
                "instruments": [{"symbol": src, "kind": "sell leg", "price": opt["price"],
                                 "note": opt["line"]}] +
                               [{"symbol": l["symbol"], "kind": "buy leg", "price": l["price"],
                                 "note": l["line"]} for l in legs],
                "accounts": [acct], "direction": "rotate (sell → fund buys, same account)",
                "size_band": f"${opt['proceeds_est']/1000:.1f}K rotates across {len(legs)} destination(s)",
                "sell_ticket": opt, "buy_legs": legs,
                "style_rationale": style["rationale"] + (" · DEFENSIVE LEAN active (operator directive per the 5-seat panel 2026-07-18): cyclical destinations excluded" if (PC.get("defensive_lean") or {}).get("enabled") else ""),
                "entry_logic": "execute the sell leg first (ladder T1); stage buys on pullbacks — "
                               "legs are independent tickets, not one order",
                "invalidation": tc["invalidation"] + " — pair dissolves if the sell thesis dies",
                "factors": [{"name": "style", "value": style["rationale"]},
                            {"name": "trim basis", "value": tc["trim_rationale"]}] +
                           [{"name": f"→ {l['symbol']}", "value": l["why"]} for l in legs],
                "as_of": as_of, "mode": "SHADOW",
                "levels": {"price": opt["price"], "entry_zone": "sell leg per ladder T1",
                           "stop": tc["invalidation"][:80]},
                "exposure_after": {**sector_after,
                                   **({"income_sleeve_pp": f"+{income_pp}pp"} if income_pp else {})},
                "tax_note": tax,
                "is_core": tc.get("is_core", False),
                "supersedes": [tc["id"]] + [rc["id"] for rc in rotate_cards
                                            if any(l["symbol"] == rc["instruments"][0]["symbol"] for l in legs)],
                "impact_dollars": opt["proceeds_est"],
                "routes": {"sell": "confirm via the ladder (tranche flow + re-entry watch; core rules apply)",
                           "buys": "staged ideas via the family-gated approval queue" if PC["stage_buy_legs"] else "manual"},
            }
            if note:
                card["cross_account_note"] = note
            pairs.append(card)
            superseded.update(card["supersedes"])
            if not dry_run:
                cur.execute("""INSERT INTO defense_rotation_pairs (pair_id, as_of, source_symbol,
                               source_account, ladder_advisory_id, destinations, style_rationale)
                               VALUES (%s,%s,%s,%s,%s,%s,%s)
                               ON CONFLICT (pair_id) DO UPDATE SET destinations=EXCLUDED.destinations,
                                 style_rationale=EXCLUDED.style_rationale""",
                            (pair_id, as_of, src, acct, tc["id"], json.dumps(legs),
                             style["rationale"]))
                if PC["stage_buy_legs"]:
                    _stage_buy_legs(cur, pair_id, legs)
    return pairs, sorted(superseded)


def _stage_buy_legs(cur, pair_id: str, legs: list):
    """Buy legs → PENDING proposals through the family-gated queue (operator approves)."""
    for l in legs:
        cur.execute("""SELECT 1 FROM paper_trade_proposals WHERE symbol=%s
                       AND strategy_id='rotation_pair_buy' AND status='PENDING' LIMIT 1""",
                    (l["symbol"],))
        if cur.fetchone():
            continue
        entry = l["price"]
        try:
            cur.execute("""INSERT INTO paper_trade_proposals
                (symbol, strategy_id, side, proposed_entry, proposed_stop, proposed_target1,
                 proposed_shares, proposed_dollar_size, status, proposed_by, origin,
                 setup_description, expires_at)
                VALUES (%s,'rotation_pair_buy','long',%s,%s,%s,%s,%s,'PENDING',
                        'defense_rotation_pairs','auto',%s, now() + interval '96 hours')""",
                (l["symbol"], entry, round(entry * 0.93, 2), round(entry * 1.10, 2),
                 l["shares"], l["alloc_est"], f"{pair_id} buy leg — {l['kind']}"[:180]))
        except Exception as ex:
            cur.connection.rollback()  # DB guards authoritative; never kill the run
            print(f"[pairs] stage skipped for {l['symbol']}: {str(ex).splitlines()[0][:100]}")


def validate_pair(card: dict) -> str | None:
    """Field-guard extension: a pair card missing EITHER leg's ticket does not render."""
    if not (card.get("sell_ticket") or {}).get("proceeds_est"):
        return "sell_ticket"
    legs = card.get("buy_legs") or []
    if not legs or any(not l.get("shares") or not l.get("price") for l in legs):
        return "buy_legs"
    if not card.get("style_rationale"):
        return "style_rationale"
    return None
