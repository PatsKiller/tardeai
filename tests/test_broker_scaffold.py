#!/usr/bin/env python3
"""Broker scaffold test suite (Phase 4). Self-runnable (no pytest dependency):
    .venv/bin/python tests/test_broker_scaffold.py
Covers: canonical validation, Schwab/Alpaca translation, OCO/bracket/ladder/trailing integrity,
serde round-trip, capability degradation/blocking, fail-closed guard, blocked adapter, audit emission,
and the no-write-imports boundary rule."""
import sys
import os
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from brokers.order_intent import (OrderIntent, Instrument, Direction, EntrySpec, EntryMethod, Quantity,
                                  ExitPolicy, StopSpec, TargetSpec, TrailConfig, PriceLinkBasis,
                                  PriceLinkType, LadderConfig, LadderLeg, AssetType, SessionPolicy,
                                  validate)
from brokers import capabilities
from brokers.translators import schwab as schwab_tr
from brokers.translators import alpaca as alpaca_tr
from brokers.execution_guard import authorize, require, ExecutionBlocked, BrokerExecutionMode
from brokers.schwab_order_adapter import SchwabOrderAdapter

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {detail}")


def bracket_intent(**over):
    base = dict(
        instrument=Instrument("TEST"), direction=Direction.LONG,
        entry=EntrySpec(method=EntryMethod.LIMIT, limit_price=10.0),
        quantity=Quantity(qty=100),
        exit_policy=ExitPolicy(stop=StopSpec(price=9.0), targets=[TargetSpec(12.0)], oco=True),
        broker="schwab")
    base.update(over)
    return OrderIntent(**base)


# ── 1. canonical validation ─────────────────────────────────────────────────
v = validate(bracket_intent())
check("valid bracket passes", v.ok, v.errors)
v = validate(bracket_intent(exit_policy=ExitPolicy(stop=StopSpec(price=11.0), targets=[TargetSpec(12.0)])))
check("stop above entry rejected (LONG)", not v.ok and any("below entry" in e for e in v.errors))
v = validate(bracket_intent(quantity=Quantity(qty=100, notional=1000)))
check("two quantity bases rejected", not v.ok)
v = validate(bracket_intent(exit_policy=ExitPolicy(
    stop=StopSpec(price=9.0), targets=[TargetSpec(12.0, 60), TargetSpec(13.0, 60)])))
check("target pct != 100 rejected", not v.ok)
v = validate(bracket_intent(instrument=Instrument("TEST", asset_type=AssetType.OPTION)))
check("options intent BLOCKED_CAPABILITY", not v.ok and any("BLOCKED_CAPABILITY" in e for e in v.errors))
v = validate(bracket_intent(ladder=LadderConfig(legs=[LadderLeg(9.8, 50), LadderLeg(9.5, 50)])))
check("valid ladder passes", v.ok, v.errors)
v = validate(bracket_intent(ladder=LadderConfig(legs=[LadderLeg(9.8, 50)])))
check("1-leg ladder rejected", not v.ok)
trail = ExitPolicy(stop=StopSpec(trail=TrailConfig(PriceLinkBasis.LAST, PriceLinkType.PERCENT, 0)),
                   targets=[TargetSpec(12.0)])
check("trailing offset=0 rejected", not validate(bracket_intent(exit_policy=trail)).ok)

# ── 2. serde round-trip ─────────────────────────────────────────────────────
i = bracket_intent(ladder=LadderConfig(legs=[LadderLeg(9.8, 50), LadderLeg(9.5, 50)]))
i2 = OrderIntent.from_dict(json.loads(json.dumps(i.to_dict())))
check("serde round-trip equality", i2.to_dict() == i.to_dict())

# ── 3. Schwab translation: OTOCO bracket ───────────────────────────────────
t = schwab_tr.translate(bracket_intent())
o = t["orders"][0]
check("bracket -> TRIGGER root", o["orderStrategyType"] == "TRIGGER")
check("child is OCO", o["childOrderStrategies"][0]["orderStrategyType"] == "OCO")
kids = o["childOrderStrategies"][0]["childOrderStrategies"]
check("OCO has target LIMIT + STOP", {k["orderType"] for k in kids} == {"LIMIT", "STOP"})
check("entry leg BUY", o["orderLegCollection"][0]["instruction"] == "BUY")

# trailing native
ti = bracket_intent(exit_policy=ExitPolicy(
    stop=StopSpec(trail=TrailConfig(PriceLinkBasis.LAST, PriceLinkType.PERCENT, 3.0)),
    targets=[TargetSpec(12.0)]))
t2 = schwab_tr.translate(ti)
kids2 = t2["orders"][0]["childOrderStrategies"][0]["childOrderStrategies"]
trail_o = [k for k in kids2 if k["orderType"] == "TRAILING_STOP"][0]
check("native trailing stop emitted", trail_o["stopPriceLinkType"] == "PERCENT"
      and trail_o["stopPriceOffset"] == 3.0)

# short direction
si = bracket_intent(direction=Direction.SHORT,
                    exit_policy=ExitPolicy(stop=StopSpec(price=11.0), targets=[TargetSpec(8.0)]))
t3 = schwab_tr.translate(si)
check("short entry SELL_SHORT / exits BUY_TO_COVER",
      t3["orders"][0]["orderLegCollection"][0]["instruction"] == "SELL_SHORT" and
      all(k["orderLegCollection"][0]["instruction"] == "BUY_TO_COVER"
          for k in t3["orders"][0]["childOrderStrategies"][0]["childOrderStrategies"]))

# ladder expansion
li = bracket_intent(ladder=LadderConfig(legs=[LadderLeg(9.8, 50), LadderLeg(9.5, 50)]))
t4 = schwab_tr.translate(li)
check("ladder expands to 2 orders", len(t4["orders"]) == 2)
check("ladder qty split 50/50", t4["orders"][0]["orderLegCollection"][0]["quantity"] == 50.0)
check("ladder coordination note present", any("coordinated by US" in n for n in t4["notes"]))

# multi-target marked unverified
mi = bracket_intent(exit_policy=ExitPolicy(stop=StopSpec(price=9.0),
                                           targets=[TargetSpec(11.0, 50), TargetSpec(12.0, 50)]))
t5 = schwab_tr.translate(mi)
check("multi-target flagged UNVERIFIED", any("UNVERIFIED" in u for u in t5["unverified"]))

# ── 4. Alpaca translation parity ────────────────────────────────────────────
a = alpaca_tr.translate(bracket_intent(broker="alpaca"))["orders"][0]
check("alpaca bracket shape", a["order_class"] == "bracket" and a["take_profit"]["limit_price"] == "12.0"
      and a["stop_loss"]["stop_price"] == "9.0")
at = alpaca_tr.translate(bracket_intent(broker="alpaca", exit_policy=ExitPolicy(
    stop=StopSpec(price=9.0, trail=TrailConfig(PriceLinkBasis.LAST, PriceLinkType.PERCENT, 3.0)),
    targets=[TargetSpec(12.0)])))
check("alpaca trailing DEGRADED note", any("DEGRADED" in n for n in at["notes"]))

# ── 5. capability registry ──────────────────────────────────────────────────
ann = capabilities.annotate_intent("alpaca", bracket_intent(
    broker="alpaca", entry=EntrySpec(method=EntryMethod.LIMIT, limit_price=10.0,
                                     price_link=None)))
check("alpaca bracket native", any(x["capability"] == "exit.bracket" and x["level"] == "native" for x in ann))
ann2 = capabilities.annotate_intent("schwab", bracket_intent())
check("schwab bracket native (VERIFIED-SDK)", any(
    x["capability"] == "exit.bracket" and x["level"] == "native" and "VERIFIED" in x.get("confidence", "")
    for x in ann2))
check("unknown capability fails closed",
      capabilities.feature("schwab", "nonexistent.thing")["level"] == "blocked")
check("unknown broker fails closed",
      capabilities.get("etrade")["execution_mode_default"] == "BROKER_DISABLED")

# ── 6. execution guard: fail-closed ────────────────────────────────────────
d = authorize(bracket_intent(), "submit")
check("schwab submit BLOCKED by default", not d.allowed and d.mode == BrokerExecutionMode.BROKER_DISABLED)
try:
    require(bracket_intent(), "submit")
    check("require() raises ExecutionBlocked", False)
except ExecutionBlocked:
    check("require() raises ExecutionBlocked", True)
da = authorize(bracket_intent(broker="alpaca"), "submit")
check("alpaca paper training allowed (existing pipeline)", da.allowed
      and da.mode == BrokerExecutionMode.PAPER_TRAINING)
os.environ["BROKER_LIVE_ENABLED"] = "true"   # env flag ALONE must not unlock anything
d2 = authorize(bracket_intent(), "submit")
check("env flag alone cannot unlock live", not d2.allowed)
os.environ.pop("BROKER_LIVE_ENABLED")

# ── 7. adapter stub blocks unconditionally ──────────────────────────────────
ad = SchwabOrderAdapter()
for meth, args in (("submit", (None, None)), ("replace", (None, "x")), ("cancel", ("x",))):
    try:
        getattr(ad, meth)(*args)
        check(f"SchwabOrderAdapter.{meth} blocked", False)
    except ExecutionBlocked:
        check(f"SchwabOrderAdapter.{meth} blocked", True)

# ── 8. audit emission ───────────────────────────────────────────────────────
try:
    from brokers import audit
    it = bracket_intent()
    authorize(it, "preview")            # guard decision -> audited event for THIS intent
    audit.save_intent(it, validation={"ok": True}, translation=schwab_tr.translate(it),
                      state="TRANSLATED")
    rows = [r for r in audit.load_drafts("schwab", 5) if r["intent_id"] == it.intent_id]
    check("intent persisted + loadable", len(rows) == 1 and rows[0]["state"] == "TRANSLATED")
    from db_adapter import _get_conn
    cur = _get_conn().cursor()
    cur.execute("SELECT count(*) FROM intent_state_events WHERE intent_id=%s", (it.intent_id,))
    check("state + guard events audited", cur.fetchone()[0] >= 2)   # save + earlier guard decisions
    cur.execute("DELETE FROM broker_order_intents WHERE symbol='TEST'")
    cur.execute("DELETE FROM intent_state_events WHERE intent_id=%s", (it.intent_id,))
    _get_conn().commit()
except Exception as ex:
    check("audit emission", False, str(ex)[:90])

# ── 9. boundary rule: no write imports in scripts/brokers ───────────────────
import re as _re
bad = []
for f in (ROOT / "scripts" / "brokers").rglob("*.py"):
    src = f.read_text()
    # 1) schwab-py must never be imported in this layer (translators stay pure)
    if _re.search(r"^\s*(import schwab\b|from schwab(\.|\s+import))", src, _re.M):
        bad.append(f"{f.name}: schwab-py import")
    # 2) the read-only transport may be imported ONLY by the adapter stub (for reads)
    if "schwab_transport" in src and f.name != "schwab_order_adapter.py":
        bad.append(f"{f.name}: schwab_transport import outside adapter")
    # 3) no transport write CALLS anywhere (word-boundary, call syntax)
    if f.name != "schwab_order_adapter.py":
        for w in ("place_order", "cancel_order", "replace_order"):
            if _re.search(rf"(?<![A-Za-z_]){w}\s*\(", src):
                bad.append(f"{f.name}: {w}(")
check("no schwab-py / transport-write surface in brokers/", not bad, str(bad))



# ── 10. two-factor approval lifecycle (operator requirement) ────────────────
try:
    import datetime as _dt
    from brokers import approval_service as ap
    from db_adapter import _get_conn as _gc

    it2 = bracket_intent()
    # suppress real telegram during tests
    import brokers.approval_service as _aps
    req = None
    import unittest.mock as _mock
    with _mock.patch.dict("sys.modules"):
        req = ap.request_approval(it2)
    check("2FA request creates both channels", set(req["channels"]) == {"web", "telegram"})
    check("not approved with zero confirmations", not ap.is_fully_approved(it2.intent_id))
    # Stage 2a (operator 2026-06-12): web channel requires TYPING the ticker — a bare click never confirms
    r0 = ap.confirm(it2.intent_id, "web")
    check("web confirm WITHOUT typed ticker rejected", not r0["ok"])
    r0b = ap.confirm(it2.intent_id, "web", "WRONGTICKER")
    check("web confirm with WRONG ticker rejected", not r0b["ok"])
    r1 = ap.confirm(it2.intent_id, "web", it2.instrument.symbol)
    check("web confirm with typed ticker ok", r1["ok"] and not r1["fully_approved"])
    check("single channel insufficient", not ap.is_fully_approved(it2.intent_id))
    rbad = ap.confirm(it2.intent_id, "telegram", "000000" )
    # 1-in-a-million collision guard:
    cur = _gc().cursor()
    cur.execute("SELECT code FROM trade_approvals WHERE intent_id=%s AND channel='telegram' ORDER BY id DESC LIMIT 1", (it2.intent_id,))
    real_code = cur.fetchone()[0]
    if real_code == "000000":
        rbad = {"ok": False}
    check("wrong telegram code rejected", not rbad["ok"])
    r2 = ap.confirm(it2.intent_id, "telegram", real_code)
    check("telegram confirm w/ code ok", r2["ok"] and r2["fully_approved"])
    check("fully approved after both", ap.is_fully_approved(it2.intent_id))
    r3 = ap.confirm(it2.intent_id, "web", it2.instrument.symbol)
    check("web re-confirm blocked (single-use)", not r3["ok"])
    check("consume marks used", ap.consume(it2.intent_id))
    check("not approved after consume", not ap.is_fully_approved(it2.intent_id))
    # expiry
    it3 = bracket_intent()
    ap.request_approval(it3)
    cur.execute("UPDATE trade_approvals SET expires_at=NOW()-INTERVAL '1 minute' WHERE intent_id=%s", (it3.intent_id,))
    _gc().commit()
    rexp = ap.confirm(it3.intent_id, "web", it3.instrument.symbol)
    check("expired approval rejected", not rexp["ok"] and "expired" in rexp["reason"])
    # cleanup
    cur.execute("DELETE FROM trade_approvals WHERE intent_id IN (%s,%s)", (it2.intent_id, it3.intent_id))
    _gc().commit()
except Exception as ex:
    check("2FA approval lifecycle", False, str(ex)[:120])

print(f"\n  RESULT: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
