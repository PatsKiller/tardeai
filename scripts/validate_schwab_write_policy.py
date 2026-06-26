#!/usr/bin/env python3
"""validate_schwab_write_policy.py — Stage 2b successor to validate_schwab_no_writes.py.

The old validator proved "no Schwab write path exists." SB-1 (operator-approved 2026-06-12)
deliberately created ONE — so this validator proves the new committed policy instead:

  WRITES EXIST ONLY BEHIND THE FULL STACK, AND THE STACK CANNOT BE WIDENED WITHOUT A COMMIT.

Checks are STATE-INDEPENDENT where possible: green when the pilot is disarmed (resting state) AND
when legitimately armed (system_controls + standing approval + api_write_enabled all set by
schwab_pilot_arm.py). Post operator-unlock 2026-06-22 all three Schwab accounts may be in
PILOT_ACCOUNT_ALLOWLIST with api_write_enabled=true when armed; per-order 2FA + readiness still
gate every submit. What can never be green: a gate module edited outside git, a write call that
skips the guard, or a reachable replace path.

Exit 0 = all green. Non-zero = a policy regression.
"""
from __future__ import annotations
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PROJECT_ROOT / "scripts"
checks = []


def ok(name, passed, detail=""):
    checks.append((name, passed, detail))
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}{' — ' + detail if detail else ''}")


# 1. legacy write blocker stays unbuilt; legacy adapter stays fenced
ok("broker_confirm_schwab.py absent (legacy write path stays unbuilt)",
   not (SCRIPTS / "broker_confirm_schwab.py").exists())

adapter = (SCRIPTS / "schwab_adapter.py").read_text() if (SCRIPTS / "schwab_adapter.py").exists() else ""
write_methods = re.findall(r"def (place_order|submit_order|submit_entry|cancel_order|replace_order|modify_stop|_api_post|confirm[_a-z]*)\b", adapter)
if write_methods:
    bad = []
    for m in set(write_methods):
        body = re.search(rf"def {m}\b.*?(?=\n    def |\nclass |\Z)", adapter, re.S)
        if body and "NOT_PROVEN" not in body.group(0):
            bad.append(m)
    ok("legacy schwab_adapter write methods all NOT_PROVEN", not bad,
       f"unguarded: {bad}" if bad else f"{len(set(write_methods))} guarded")
else:
    ok("legacy schwab_adapter exposes no order-write methods", True)

# 2. position sync unchanged (protected writes; fail-closed live fetch)
psync = (SCRIPTS / "schwab_position_sync.py").read_text() if (SCRIPTS / "schwab_position_sync.py").exists() else ""
ok("position sync routes writes through protected_holdings_write", "protected_holdings_write" in psync and "os.replace" in psync)
ok("position sync live fetch is fail-closed (non-list → degraded_noop)",
   "degraded_noop" in psync and "get_positions" in psync and "not isinstance(live, list)" in psync)

# 3. api_write_enabled POLICY: pilot allowlist accounts true ONLY when legitimately armed
#    (broker_live_enabled + standing approval); disarmed resting state = all false.
try:
    sys.path.insert(0, str(SCRIPTS))
    from db_adapter import _get_conn
    from brokers.pilot_caps import PILOT_ACCOUNT_ALLOWLIST
    conn = _get_conn(); cur = conn.cursor()
    cur.execute("SELECT account_key, api_write_enabled FROM broker_accounts WHERE broker ILIKE '%schwab%'")
    flags = dict(cur.fetchall())
    cur.execute("SELECT value FROM system_controls WHERE key='broker_live_enabled'")
    r = cur.fetchone()
    cur.execute("SELECT count(*) FROM broker_live_approvals WHERE revoked_at IS NULL")
    standing = int(cur.fetchone()[0] or 0)
    pilot_armed = bool(r and str(r[0]).lower() == "true") and standing > 0
    enabled = {k for k, v in flags.items() if v}
    expected = set(PILOT_ACCOUNT_ALLOWLIST)
    if pilot_armed:
        policy_ok = expected.issubset(enabled)
        policy_detail = f"armed pilot enabled={sorted(enabled)} expected={sorted(expected)}"
    else:
        policy_ok = not enabled
        policy_detail = f"disarmed flags={flags}"
    ok("api_write_enabled policy: pilot allowlist only-when-armed, all false when disarmed",
       policy_ok, policy_detail)
    # interlock posture unchanged (paper master flag refuses Schwab live accounts)
    try:
        import live_trading_interlock as lti
        cur.execute("SELECT live_trading_allowed FROM paper_validation_policy WHERE active=true ORDER BY id DESC LIMIT 1")
        fr = cur.fetchone(); live_allowed = bool(fr[0]) if fr else False
        modes = {ak: lti.account_mode(conn, ak) for ak in flags}
        ok("live_trading_interlock refuses Schwab (live + master flag OFF)",
           all(m != "paper" for m in modes.values()) and not live_allowed,
           f"modes={modes} live_allowed={live_allowed}")
    except Exception as e:
        ok("interlock importable", False, str(e)[:60])
except Exception as e:
    ok("DB checks", False, str(e)[:60])

# 4. Rule 9 isolation (screeners/routing see no Schwab/Level-II artifacts, no transport import)
SCREENER_FILES = ["prime_setups", "watchlist_setups", "trade_ai_orchestrator", "atm_auto_approver"]
leak, leak2 = [], []
for stem in SCREENER_FILES:
    for f in SCRIPTS.glob(f"*{stem}*.py"):
        txt = f.read_text()
        if re.search(r"level\s*2|level_ii|levelii|volume_sweep|depth_of_book|nasdaq_book|nyse_book|schwab_position_sync|schwab_adapter", txt, re.I):
            leak.append(f.name)
        if "schwab_transport" in txt:
            leak2.append(f.name)
ok("Level II / volume / Schwab data isolated from screeners+routing (Rule 9)", not leak,
   f"leak: {leak}" if leak else "no references")
ok("schwab_transport isolated from screeners+routing (Rule 9)", not leak2,
   f"leak: {leak2}" if leak2 else "no references")

# 5. THE WRITE SURFACE: transport-only, guard-stacked, persist-before-POST, replace fenced
trans = (SCRIPTS / "schwab_transport.py").read_text()
place_body = re.search(r"def place_order\(.*?(?=\ndef )", trans, re.S)
cancel_body = re.search(r"def cancel_order\(.*?(?=\ndef )", trans, re.S)
pb = place_body.group(0) if place_body else ""
cb = cancel_body.group(0) if cancel_body else ""
stack_ok = ("_pilot_preconditions" in pb and 'require(intent, "submit")' in pb
            and "_pilot_preconditions" in cb and 'require(intent, "cancel")' in cb)
ok("transport writes pass the full stack (preconditions + execution_guard.require)", stack_ok)
persist_first = ("INSERT INTO schwab_pilot_orders" in pb
                 and pb.index("INSERT INTO schwab_pilot_orders") < pb.index("client.place_order"))
ok("transport persists the pilot row BEFORE any POST (Schwab does not dedupe)", persist_first)
ok("replace_order remains FENCED (NotProvenWrite; no replace in the pilot)",
   bool(re.search(r"def replace_order\([^\n]*\n\s+raise NotProvenWrite", trans)))
ok("consume(): 2FA approval burned single-use at submit", "approval_service.consume" in pb)

# 6. schwab-py imported ONLY at the transport boundary
schwab_importers = []
for f in SCRIPTS.glob("*.py"):
    if f.name in ("schwab_transport.py", "validate_schwab_no_writes.py", "validate_schwab_write_policy.py"):
        continue
    if re.search(r"\bfrom\s+schwab\.\w|\bimport\s+schwab\b(?!_)", f.read_text()):
        schwab_importers.append(f.name)
ok("schwab-py imported only at transport boundary", not schwab_importers,
   f"leak: {schwab_importers}" if schwab_importers else "boundary-only")

# 7. raw Schwab order-endpoint HTTP absent outside the transport (no requests.post side-channel)
raw = []
for f in SCRIPTS.rglob("*.py"):
    if f.name in ("schwab_transport.py", "validate_schwab_write_policy.py"):
        continue
    txt = f.read_text()
    # Schwab-specific: a mutating HTTP call whose line references BOTH the Schwab API host/path AND
    # an order endpoint. (Alpaca paper-pipeline order HTTP and the Schwab OAuth token POST are fine.)
    if re.search(r"requests\.(post|put|delete)\([^\n]*(schwabapi|trader/v1)[^\n]*order", txt, re.I):
        raw.append(str(f.relative_to(SCRIPTS)))
ok("no raw Schwab order-endpoint HTTP outside the transport", not raw, f"leak: {raw}" if raw else "clean")

# 8. RUNTIME fail-closed: IRA write raises; replace raises; cancel of a non-pilot order raises
try:
    import schwab_transport as _st
    from brokers.order_intent import OrderIntent, Instrument, Direction, EntrySpec, EntryMethod, Quantity
    _probe = OrderIntent(instrument=Instrument("ZGATE"), direction=Direction.LONG,
                         entry=EntrySpec(method=EntryMethod.LIMIT, limit_price=3.0),
                         quantity=Quantity(qty=2), broker="schwab", account_key="schwab_roth_ira")
    try:
        from brokers.execution_guard import ExecutionBlocked as _ExecBlocked
        _fail_closed = (_st.NotProvenWrite, _ExecBlocked)
    except Exception:
        _fail_closed = (_st.NotProvenWrite,)
    ira_raised = False
    try:
        _st.place_order("schwab_roth_ira", {}, _probe)
    except _fail_closed:
        ira_raised = True
    except Exception:
        ira_raised = False
    rep_raised = False
    try:
        _st.replace_order()
    except _st.NotProvenWrite:
        rep_raised = True
    except Exception:
        rep_raised = False
    ok("runtime: IRA write + replace both raise NotProvenWrite", ira_raised and rep_raised)
except Exception as e:
    ok("runtime transport check", False, str(e)[:60])

# 9. canary gate: pure commit-only module; envelope enforced here OR via execution_guard when removed
try:
    from unittest import mock as _mock
    import brokers.canary_gate as _cg
    from brokers.execution_guard import authorize as _auth
    from brokers.order_intent import OrderIntent as _OI, Instrument as _In, Direction as _Dir, \
        EntrySpec as _ES, EntryMethod as _EM, Quantity as _Q
    gate_src = (SCRIPTS / "brokers" / "canary_gate.py").read_text()
    pure = not re.search(r"^\s*(import os\b|from os\b)", gate_src, re.M) \
        and not re.search(r"db_adapter|_get_conn|json\.load|yaml|configparser|open\(", gate_src)
    _big = _OI(instrument=_In("AAPL"), direction=_Dir.LONG,
               entry=_ES(method=_EM.LIMIT, limit_price=180.0), quantity=_Q(qty=100), broker="schwab")
    if getattr(_cg, "GATES_REMOVED", False):
        d = _auth(_big, "submit")
        ok("canary gate: GATES_REMOVED pass-through; execution_guard still denies unapproved submit",
           pure and (not d.allowed),
           f"pure={pure} GATES_REMOVED=True reason={d.reason[:60]}")
    else:
        d = _auth(_big, "submit")
        ok("canary gate: pure module + out-of-envelope submit denied in front of guard",
           pure and (not d.allowed) and d.reason.startswith("CANARY_GATE BLOCK"),
           f"pure={pure} reason={d.reason[:60]}")
except Exception as e:
    ok("canary gate check", False, str(e)[:60])

# 10. canary auto-expiry behavior (skipped while GATES_REMOVED=True — operator 2026-06-21)
try:
    import brokers.canary_gate as _cg
    _zp = _OI(instrument=_In("ZGATE"), direction=_Dir.LONG,
              entry=_ES(method=_EM.LIMIT, limit_price=3.0), quantity=_Q(qty=2), broker="schwab")
    if getattr(_cg, "GATES_REMOVED", False):
        ok("canary gate auto-expiry: bypassed while GATES_REMOVED=True (2FA locks apply)", True)
    else:
        with _mock.patch.object(_cg, "CANARY_SYMBOL_ALLOWLIST", ("ZGATE",)), \
             _mock.patch.object(_cg, "CANARY_SESSION_DATE", "2099-01-01"):
            with _mock.patch.object(_cg, "_today", return_value="2099-01-01"):
                on_ok = _cg.evaluate(_zp).allowed
            with _mock.patch.object(_cg, "_today", return_value="2099-01-02"):
                off_blocked = not _cg.evaluate(_zp).allowed
        ok("canary gate auto-expiry: on-date passes, off-date fails closed", on_ok and off_blocked)
except Exception as e:
    ok("canary auto-expiry check", False, str(e)[:60])

# 10b. BATTERY SHAPES envelope-bounded (skipped while GATES_REMOVED=True)
try:
    import schwab_stage2b_canary_preflight as _pf
    from decimal import Decimal as _Dec
    if getattr(_cg, "GATES_REMOVED", False):
        ok("battery shapes envelope-bounded: bypassed while GATES_REMOVED=True (2FA locks apply)", True)
    else:
        with _mock.patch.object(_cg, "_today", return_value=_cg.CANARY_SESSION_DATE):
            in_env = [
                _pf.make_battery_intent("schwab_taxable", "GRAB", 10, "buy_cancel", price=_Dec("1.70")),
                _pf.make_battery_intent("schwab_taxable", "GRAB", 10, "protective", stop_price=_Dec("3.00")),
                _pf.make_battery_intent("schwab_taxable", "GRAB", 10, "trailing", trail_pct=_Dec("3"), reference_price=_Dec("3.30")),
                _pf.make_battery_intent("schwab_taxable", "GRAB", 10, "close", price=_Dec("3.30")),
            ]
            all_allow = all(_cg.evaluate(i).allowed for i in in_env)
            over_buy = not _cg.evaluate(_pf.make_battery_intent("schwab_taxable", "GRAB", 10, "buy_cancel", price=_Dec("5.00"))).allowed
            over_stop = not _cg.evaluate(_pf.make_battery_intent("schwab_taxable", "GRAB", 10, "protective", stop_price=_Dec("4.50"))).allowed
            over_qty = not _cg.evaluate(_pf.make_battery_intent("schwab_taxable", "GRAB", 11, "buy_cancel", price=_Dec("3.00"))).allowed
        ok("battery shapes envelope-bounded (in-env allow; >$4 buy/stop + >10sh block)",
           all_allow and over_buy and over_stop and over_qty,
           f"allow={all_allow} overbuy={over_buy} overstop={over_stop} overqty={over_qty}")
except Exception as e:
    ok("battery envelope check", False, str(e)[:80])

# 11. pilot caps: pure commit-only literals + behavioral cap/allowlist denial
try:
    caps_src = (SCRIPTS / "brokers" / "pilot_caps.py").read_text()
    caps_pure = not re.search(r"os\.getenv\(|configparser|yaml\.", caps_src)
    import brokers.pilot_caps as _pc
    _want = ("schwab_taxable", "schwab_roth_ira", "schwab_rollover_ira")
    lits = _pc.PILOT_ACCOUNT_ALLOWLIST == _want and _pc.MAX_PILOT_ORDERS_TOTAL >= 9999
    with _mock.patch.object(_pc, "orders_used", return_value=99999):
        cap_block = not _pc.evaluate("schwab_taxable")[0]
    with _mock.patch.object(_pc, "orders_used", return_value=0):
        ira_pass = _pc.evaluate("schwab_roth_ira")[0]
        tax_pass = _pc.evaluate("schwab_taxable")[0]
        rogue_block = not _pc.evaluate("alpaca_paper")[0]
    ok("pilot caps: all 3 Schwab accounts + high cap + allowlist deny",
       caps_pure and lits and cap_block and ira_pass and tax_pass and rogue_block)
except Exception as e:
    ok("pilot caps check", False, str(e)[:60])

# 12. 2FA REQUIRED: with every standing lock mocked open and caps green, an unapproved intent is
#     DENIED; a fully-approved one is GRANTED (proves the stack can both deny and grant correctly).
try:
    import brokers.execution_guard as _eg
    import brokers.approval_service as _aps
    _gp = _OI(instrument=_In("ZGATE"), direction=_Dir.LONG,
              entry=_ES(method=_EM.LIMIT, limit_price=3.0), quantity=_Q(qty=2),
              broker="schwab", account_key="schwab_taxable")
    with _mock.patch.object(_cg, "CANARY_SYMBOL_ALLOWLIST", ("ZGATE",)), \
         _mock.patch.object(_cg, "CANARY_SESSION_DATE", "2099-01-01"), \
         _mock.patch.object(_cg, "_today", return_value="2099-01-01"), \
         _mock.patch.object(_eg, "_live_future_unlocked", return_value=True), \
         _mock.patch.object(_pc, "orders_used", return_value=0):
        with _mock.patch.object(_aps, "is_fully_approved", return_value=False):
            denied = not _eg.authorize(_gp, "submit").allowed
        with _mock.patch.object(_aps, "is_fully_approved", return_value=True):
            granted = _eg.authorize(_gp, "submit").allowed
        cancel_ok = _eg.authorize(_gp, "cancel").allowed
    with _mock.patch.object(_eg, "_live_future_unlocked", return_value=False):
        locked_deny = not _eg.authorize(_gp, "cancel").allowed
    ok("guard: 2FA-less submit DENIED / fully-approved GRANTED / cancel safe-direction / locks-closed deny",
       denied and granted and cancel_ok and locked_deny,
       f"denied={denied} granted={granted} cancel={cancel_ok} locked_deny={locked_deny}")
except Exception as e:
    ok("guard 2FA behavior check", False, str(e)[:80])

# 13. TAMPER EVIDENCE: the gate modules on disk must match git HEAD — an uncommitted edit to the
#     envelope/caps is a policy violation even if syntactically valid (commit-only means commit-only).
try:
    gate_files = ["scripts/brokers/canary_gate.py", "scripts/brokers/pilot_caps.py",
                  "scripts/brokers/execution_guard.py", "scripts/brokers/protective_stop_policy.py"]
    r = subprocess.run(["git", "diff", "--name-only", "HEAD", "--"] + gate_files,
                       cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=20)
    dirty = [l for l in r.stdout.splitlines() if l.strip()]
    ok("tamper evidence: gate modules match git HEAD (no uncommitted envelope edits)",
       r.returncode == 0 and not dirty, f"dirty: {dirty}" if dirty else "clean vs HEAD")
except Exception as e:
    ok("tamper evidence check", False, str(e)[:60])

# 14. shadow recon + activity capture stay read-only
WRITE_RE = re.compile(r"\bplace_order|\bcancel_order|\breplace_order|requests\.(post|put|delete|patch)")
for fname in ("schwab_shadow_recon.py", "schwab_activity_capture.py"):
    src = (SCRIPTS / fname).read_text() if (SCRIPTS / fname).exists() else ""
    clean = bool(src) and not WRITE_RE.search(src) \
        and not re.search(r"\bfrom\s+schwab\.\w|\bimport\s+schwab\b(?!_)", src)
    ok(f"{fname} is read-only (no write symbols, no schwab-py import)", clean)

# 15. UI/API execution surface: the ONLY submit-capable routes are the two pilot routes, and they
#     call the transport (never a client/raw HTTP directly).
api_src = (SCRIPTS / "api_v2.py").read_text()
sub_routes = set(re.findall(r"broker-orders/((?:pilot/)?(?:submit|execute|send|place|cancel-live|replace|cancel))", api_src))
ok("API execution routes are exactly pilot/execute + pilot/cancel",
   sub_routes == {"pilot/execute", "pilot/cancel"}, f"routes={sorted(sub_routes)}")
pilot_fns = re.search(r"def _pilot_execute.*?(?=\ndef _pilot_cancel)", api_src, re.S)
ok("pilot routes delegate to the transport (no direct client/raw HTTP)",
   bool(pilot_fns) and "st.place_order" in pilot_fns.group(0)
   and "requests.post" not in pilot_fns.group(0))

# 16. canary analytics exclusion in every round-trip consumer (unchanged)
CANARY_CONSUMERS = ["api_v2.py", "schwab_journal_builder.py", "schwab_journal_classifier.py",
                    "backtest_fill_reconciliation.py", "build_trade_execution_quality.py",
                    "ingest_schwab_gainloss.py"]
missing = [f for f in CANARY_CONSUMERS if "canary" not in (SCRIPTS / f).read_text()]
ok("canary exclusion wired into all round-trip consumers", not missing,
   f"missing: {missing}" if missing else f"{len(CANARY_CONSUMERS)} consumers filtered")

passed = sum(1 for _, p, _ in checks if p)
print(f"\n  {passed}/{len(checks)} guards green")
sys.exit(0 if passed == len(checks) else 1)
