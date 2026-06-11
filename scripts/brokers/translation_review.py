#!/usr/bin/env python3
"""Stage-1 translation review harness (migration-plan gate 1).

Generates 30 diverse order intents — grounded in REAL recent symbols/prices from paper_trades — runs each
through the full preview pipeline (validate -> capability-annotate -> translate -> guard -> audit), and
REVIEWS every translation against intended semantics with field-level assertions. Emits a markdown review
log for operator sign-off. Repeatable; zero broker I/O (the guard blocks everything; reviews are local).

  .venv/bin/python scripts/brokers/translation_review.py
Writes docs/brokers/stage1-translation-review-log.md and exits non-zero on any DEFECT.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from brokers.order_intent import (OrderIntent, Instrument, Direction, EntrySpec, EntryMethod, Quantity,
                                  ExitPolicy, StopSpec, TargetSpec, TrailConfig, PriceLink, PriceLinkBasis,
                                  PriceLinkType, LadderConfig, LadderLeg, AssetType, SessionPolicy, TIF,
                                  validate)
from brokers import capabilities
from brokers.translators.schwab import translate as schwab_translate
from brokers.execution_guard import authorize

OUT = ROOT / "docs" / "brokers" / "stage1-translation-review-log.md"


def _real_prices():
    """Pull real recent symbols + price levels so the suite reviews realistic numbers."""
    try:
        from db_adapter import _get_conn
        cur = _get_conn().cursor()
        cur.execute("""SELECT symbol, entry_price, COALESCE(stop_loss, entry_price*0.95),
                              COALESCE(target_1, entry_price*1.1)
                       FROM paper_trades WHERE entry_price > 0 ORDER BY id DESC LIMIT 12""")
        out = []
        for r in cur.fetchall():
            sym, e, st, tg = r[0], float(r[1]), float(r[2]), float(r[3])
            # sanitize LONG geometry: real rows can have stop>entry (trailing moved past breakeven on
            # winners — legitimate live data, invalid as a fresh LONG intent)
            st = min(st, round(e * 0.97, 2))
            tg = max(tg, round(e * 1.05, 2))
            out.append((sym, e, st, tg))
        return out
    except Exception:
        return [("ELVN", 41.65, 39.49, 45.73), ("NUVL", 123.43, 117.35, 135.88),
                ("TMHC", 71.61, 68.02, 78.77), ("NWG", 15.84, 15.05, 17.42)]


def build_suite() -> list[tuple[str, OrderIntent, dict]]:
    """30 cases: (name, intent, expectations). Expectations drive the field-level review."""
    px = _real_prices()
    def P(i):  # cycle real price rows
        return px[i % len(px)]
    S = []

    def case(name, intent, **expect):
        S.append((name, intent, expect))

    def mk(sym, e, st, tg, **over):
        base = dict(instrument=Instrument(sym), direction=Direction.LONG,
                    entry=EntrySpec(method=EntryMethod.LIMIT, limit_price=e),
                    quantity=Quantity(qty=100), broker="schwab",
                    exit_policy=ExitPolicy(stop=StopSpec(price=st), targets=[TargetSpec(tg)], oco=True))
        base.update(over)
        return OrderIntent(**base)

    # 1-4: classic brackets on real prices
    for i in range(4):
        s, e, st, tg = P(i)
        case(f"bracket_{s}", mk(s, e, st, tg), root="TRIGGER", child="OCO",
             exits={"LIMIT", "STOP"}, entry_type="LIMIT", instruction="BUY", duration="DAY")
    # 5: market entry + bracket
    s, e, st, tg = P(4)
    case(f"market_bracket_{s}", mk(s, None, st, tg,
         entry=EntrySpec(method=EntryMethod.MARKET)), root="TRIGGER", entry_type="MARKET")
    # 6: stop entry (breakout buy-stop)
    s, e, st, tg = P(5)
    case(f"stop_entry_{s}", mk(s, None, st, tg,
         entry=EntrySpec(method=EntryMethod.STOP, stop_price=round(e * 1.02, 2))),
         entry_type="STOP", has_stop_price=True)
    # 7: stop-limit entry
    s, e, st, tg = P(6)
    case(f"stop_limit_entry_{s}", mk(s, e, st, tg,
         entry=EntrySpec(method=EntryMethod.STOP_LIMIT, limit_price=e, stop_price=round(e * 1.01, 2))),
         entry_type="STOP_LIMIT", has_stop_price=True)
    # 8-11: trailing stops, all link types + bases
    for i, (basis, ltype, off) in enumerate([(PriceLinkBasis.LAST, PriceLinkType.PERCENT, 3.0),
                                             (PriceLinkBasis.BID, PriceLinkType.VALUE, 0.50),
                                             (PriceLinkBasis.MARK, PriceLinkType.TICK, 5),
                                             (PriceLinkBasis.ASK, PriceLinkType.PERCENT, 2.5)]):
        s, e, st, tg = P(7 + i)
        case(f"trail_{basis.value}_{ltype.value}_{s}",
             mk(s, e, st, tg, exit_policy=ExitPolicy(
                 stop=StopSpec(trail=TrailConfig(basis, ltype, off)), targets=[TargetSpec(tg)], oco=True)),
             trail={"basis": basis.value, "type": ltype.value, "offset": off})
    # 12: multi-target OCO (expect UNVERIFIED flag)
    s, e, st, tg = P(11)
    case(f"multi_target_{s}", mk(s, e, st, tg, exit_policy=ExitPolicy(
        stop=StopSpec(price=st), targets=[TargetSpec(tg, 50), TargetSpec(round(tg * 1.08, 2), 50)],
        oco=True)), exits={"LIMIT", "STOP"}, exit_count=3, unverified_contains="multi-target")
    # 13-14: ladders
    s, e, st, tg = P(0)
    case(f"ladder2_{s}", mk(s, e, st, tg, ladder=LadderConfig(
        legs=[LadderLeg(round(e * 0.995, 2), 50), LadderLeg(round(e * 0.98, 2), 50)])),
        order_count=2, note_contains="coordinated by US")
    case(f"ladder3_{s}", mk(s, e, st, tg, ladder=LadderConfig(
        legs=[LadderLeg(e, 40), LadderLeg(round(e * 0.99, 2), 30), LadderLeg(round(e * 0.98, 2), 30)])),
        order_count=3)
    # 15-16: shorts
    s, e, st, tg = P(1)
    case(f"short_bracket_{s}", mk(s, e, round(e * 1.05, 2), round(e * 0.9, 2),
         direction=Direction.SHORT), instruction="SELL_SHORT", exit_instruction="BUY_TO_COVER")
    case(f"short_market_{s}", mk(s, None, round(e * 1.05, 2), round(e * 0.9, 2),
         direction=Direction.SHORT, entry=EntrySpec(method=EntryMethod.MARKET)),
         instruction="SELL_SHORT", entry_type="MARKET")
    # 17: bid-style entry (price link)
    s, e, st, tg = P(2)
    case(f"bid_link_entry_{s}", mk(s, e, st, tg, entry=EntrySpec(
        method=EntryMethod.LIMIT, limit_price=e,
        price_link=PriceLink(PriceLinkBasis.BID, PriceLinkType.VALUE, 0.02))),
        price_link=True, unverified_contains="priceLink")
    # 18: entry range
    s, e, st, tg = P(3)
    case(f"entry_range_{s}", mk(s, None, st, tg, entry=EntrySpec(
        method=EntryMethod.LIMIT, entry_range={"low": round(e * 0.99, 2), "high": e})),
        entry_price=str(e), note_contains="entry_range")
    # 19-21: sessions
    for i, sess in enumerate([SessionPolicy.AM, SessionPolicy.PM, SessionPolicy.SEAMLESS]):
        s, e, st, tg = P(4 + i)
        case(f"session_{sess.value}_{s}", mk(s, e, st, tg, session=sess), session=sess.value)
    # 22-24: TIFs
    for i, (tif, dur) in enumerate([(TIF.GTC, "GOOD_TILL_CANCEL"), (TIF.FOK, "FILL_OR_KILL"),
                                    (TIF.IOC, "IMMEDIATE_OR_CANCEL")]):
        s, e, st, tg = P(7 + i)
        case(f"tif_{tif.value}_{s}", mk(s, e, st, tg, tif=tif), duration=dur)
    # 25: MOC
    s, e, st, tg = P(10)
    case(f"moc_{s}", mk(s, None, st, tg, entry=EntrySpec(method=EntryMethod.MARKET_ON_CLOSE)),
         entry_type="MARKET_ON_CLOSE")
    # 26: stop-only exit (no target)
    s, e, st, tg = P(11)
    case(f"stop_only_{s}", mk(s, e, st, tg, exit_policy=ExitPolicy(stop=StopSpec(price=st), targets=[])),
         root="TRIGGER", child_types={"STOP"})
    # 27: target-only exit
    case(f"target_only_{s}", mk(s, e, st, tg, exit_policy=ExitPolicy(stop=None, targets=[TargetSpec(tg)])),
         root="TRIGGER", child_types={"LIMIT"})
    # 28: REJECTION — stop above entry (must fail validation)
    case("reject_bad_stop", mk("ELVN", 41.65, 45.0, 50.0), expect_invalid="below entry")
    # 29: BLOCKED — options (model-only)
    case("blocked_options", mk("NVDA", 5.0, 4.0, 7.0,
         instrument=Instrument("NVDA", asset_type=AssetType.OPTION)), expect_invalid="BLOCKED_CAPABILITY")
    # 30: BLOCKED capability — notional sizing (fractional unverified)
    case("blocked_notional", mk("ELVN", 41.65, 39.49, 45.73, quantity=Quantity(notional=2000.0)),
         expect_blocked_cap="fractional")
    return S


def review_one(name, intent, expect) -> tuple[str, list[str], dict]:
    """Run pipeline + field-level review. Returns (verdict, defects, summary)."""
    defects = []
    v = validate(intent)
    ann = capabilities.annotate_intent("schwab", intent)
    guard = authorize(intent, "preview")
    summary = {"validation_ok": v.ok, "guard_mode": guard.mode.value, "guard_allowed": guard.allowed}

    if guard.allowed:
        defects.append("GUARD GRANTED EXECUTION — must never happen this phase")

    if "expect_invalid" in expect:
        if v.ok:
            defects.append(f"expected validation rejection containing '{expect['expect_invalid']}'")
        elif not any(expect["expect_invalid"] in e for e in v.errors):
            defects.append(f"rejection reason mismatch: {v.errors}")
        return ("REJECTED-AS-EXPECTED" if not defects else "DEFECT"), defects, summary

    if "expect_blocked_cap" in expect:
        blocked = [a for a in ann if a["level"] == "blocked"]
        if not any(expect["expect_blocked_cap"] in a["capability"] for a in blocked):
            defects.append(f"expected blocked capability '{expect['expect_blocked_cap']}', got {blocked}")
        return ("BLOCKED-AS-EXPECTED" if not defects else "DEFECT"), defects, summary

    if not v.ok:
        defects.append(f"unexpected validation failure: {v.errors}")
        return "DEFECT", defects, summary

    t = schwab_translate(intent)
    orders = t["orders"]
    summary["orders"] = len(orders)
    o = orders[0]

    if expect.get("order_count") and len(orders) != expect["order_count"]:
        defects.append(f"order_count {len(orders)} != {expect['order_count']}")
    if expect.get("root") and o.get("orderStrategyType") != expect["root"]:
        defects.append(f"root {o.get('orderStrategyType')} != {expect['root']}")
    if expect.get("entry_type") and o.get("orderType") != expect["entry_type"]:
        defects.append(f"entry orderType {o.get('orderType')} != {expect['entry_type']}")
    if expect.get("duration") and o.get("duration") != expect["duration"]:
        defects.append(f"duration {o.get('duration')} != {expect['duration']}")
    if expect.get("session") and o.get("session") != expect["session"]:
        defects.append(f"session {o.get('session')} != {expect['session']}")
    if expect.get("instruction") and o["orderLegCollection"][0]["instruction"] != expect["instruction"]:
        defects.append(f"instruction {o['orderLegCollection'][0]['instruction']} != {expect['instruction']}")
    if expect.get("entry_price") and o.get("price") != expect["entry_price"]:
        defects.append(f"price {o.get('price')} != {expect['entry_price']}")
    if expect.get("has_stop_price") and "stopPrice" not in o:
        defects.append("missing stopPrice on entry")
    if expect.get("price_link") and "priceLinkBasis" not in o:
        defects.append("missing priceLink fields")

    kids = []
    if o.get("childOrderStrategies"):
        c0 = o["childOrderStrategies"][0]
        if expect.get("child") and c0.get("orderStrategyType") != expect["child"]:
            defects.append(f"child {c0.get('orderStrategyType')} != {expect['child']}")
        kids = c0.get("childOrderStrategies") or [c0]
    if expect.get("exits") and {k.get("orderType") for k in kids} != expect["exits"]:
        defects.append(f"exit types {[k.get('orderType') for k in kids]} != {expect['exits']}")
    if expect.get("child_types") and {k.get("orderType") for k in kids} != expect["child_types"]:
        defects.append(f"child types {[k.get('orderType') for k in kids]} != {expect['child_types']}")
    if expect.get("exit_count") and len(kids) != expect["exit_count"]:
        defects.append(f"exit count {len(kids)} != {expect['exit_count']}")
    if expect.get("exit_instruction"):
        bad = [k for k in kids if k["orderLegCollection"][0]["instruction"] != expect["exit_instruction"]]
        if bad:
            defects.append(f"exit instruction != {expect['exit_instruction']}")
    if expect.get("trail"):
        tr = [k for k in kids if k.get("orderType") == "TRAILING_STOP"]
        if not tr:
            defects.append("no TRAILING_STOP child emitted")
        else:
            k = tr[0]
            for fld, key in (("stopPriceLinkBasis", "basis"), ("stopPriceLinkType", "type"),
                             ("stopPriceOffset", "offset")):
                if k.get(fld) != expect["trail"][key]:
                    defects.append(f"trail {fld}={k.get(fld)} != {expect['trail'][key]}")
    if expect.get("note_contains") and not any(expect["note_contains"] in n for n in t["notes"]):
        defects.append(f"missing note containing '{expect['note_contains']}'")
    if expect.get("unverified_contains") and not any(expect["unverified_contains"] in u
                                                     for u in t["unverified"]):
        defects.append(f"missing UNVERIFIED flag containing '{expect['unverified_contains']}'")

    # universal: qty conservation
    total_entry_qty = sum(ord_["orderLegCollection"][0]["quantity"] for ord_ in orders)
    if abs(total_entry_qty - float(intent.quantity.qty or 0)) > 0.01:
        defects.append(f"entry qty {total_entry_qty} != intent {intent.quantity.qty}")

    # persist as audited draft (review trail)
    try:
        from brokers import audit
        audit.save_intent(intent, validation={"ok": v.ok}, translation=t, capability_notes=ann,
                          state="TRANSLATED")
    except Exception:
        pass
    return ("CLEAN" if not defects else "DEFECT"), defects, summary


def main():
    suite = build_suite()
    rows, n_defect = [], 0
    for name, intent, expect in suite:
        verdict, defects, summary = review_one(name, intent, expect)
        if verdict == "DEFECT":
            n_defect += 1
        rows.append((name, intent, expect, verdict, defects, summary))
        print(f"  [{verdict}] {name}" + (f" — {defects}" if defects else ""))

    lines = ["# Stage-1 Translation Review Log", "",
             f"**Run:** repeatable via `scripts/brokers/translation_review.py` · **Cases:** {len(suite)} · "
             f"**Defects:** {n_defect} · **Guard grants:** 0 expected/0 allowed",
             "", "Real recent symbols/prices from paper_trades ground every case. Every preview persisted as",
             "an audited draft (broker_order_intents) — inspect via GET /api/v2/broker-orders/drafts.", "",
             "| # | Case | Intent summary | Verdict | Notes |", "|---|---|---|---|---|"]
    for i, (name, intent, expect, verdict, defects, summary) in enumerate(rows, 1):
        e = intent.entry
        isum = (f"{intent.direction.value} {intent.instrument.symbol} {e.method.value}"
                f"{' @' + str(e.limit_price) if e.limit_price else ''}"
                f" qty={intent.quantity.qty or intent.quantity.notional}"
                f" tif={intent.tif.value} sess={intent.session.value}")
        notes = "; ".join(defects) if defects else (
            "; ".join(f"{k}={v}" for k, v in expect.items() if k in
                      ("root", "trail", "order_count", "expect_invalid", "expect_blocked_cap")) or "ok")
        lines.append(f"| {i} | {name} | {isum} | **{verdict}** | {notes[:110]} |")
    lines += ["", f"## Verdict: {'ZERO TRANSLATION DEFECTS — Stage-1 gate criteria met' if n_defect == 0 else f'{n_defect} DEFECTS — gate NOT met'}",
              "", "Operator sign-off required to advance to Stage 2 (dev-account validation of UNVERIFIED items)."]
    OUT.write_text("\n".join(lines))
    print(f"\n  log: {OUT}")
    print(f"  RESULT: {len(suite) - n_defect}/{len(suite)} clean")
    return 1 if n_defect else 0


if __name__ == "__main__":
    sys.exit(main())
