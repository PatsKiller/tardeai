#!/usr/bin/env python3
"""validate_schwab_no_writes.py — regression guard (Phase 1, proof artifact #4 + Rule 9).

Proves, mechanically:
  1. No reachable Schwab WRITE/order path (adapter write methods return NOT_PROVEN; broker_confirm_schwab.py absent).
  2. Schwab accounts keep api_write_enabled=false.
  3. live_trading_interlock refuses Schwab live accounts.
  4. LEVEL II ISOLATION (Rule 9): no path lets Level-II/volume-sweep advisory data touch the screeners
     (prime_setups / watchlist_setups), strategy match-minimums, GO/WAIT, or ATM routing.

Exit 0 = all green. Non-zero = a guard tripped (a regression).
"""
from __future__ import annotations
import os, re, subprocess, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PROJECT_ROOT / "scripts"
checks = []


def ok(name, passed, detail=""):
    checks.append((name, passed, detail))
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}{' — ' + detail if detail else ''}")


def _raises_notproven(mod, name):
    """True iff calling mod.name() raises NotProvenWrite (the write fence held)."""
    try:
        getattr(mod, name)()
        return False
    except mod.NotProvenWrite:
        return True
    except Exception:
        return False


# 1. broker_confirm_schwab.py must NOT exist (the write blocker stays unbuilt)
ok("broker_confirm_schwab.py absent (no write path)", not (SCRIPTS / "broker_confirm_schwab.py").exists())

# 2. schwab_adapter write methods unreachable / NOT_PROVEN
adapter = (SCRIPTS / "schwab_adapter.py").read_text() if (SCRIPTS / "schwab_adapter.py").exists() else ""
write_methods = re.findall(r"def (place_order|submit_order|submit_entry|cancel_order|replace_order|modify_stop|_api_post|confirm[_a-z]*)\b", adapter)
if write_methods:
    # each must raise/return NOT_PROVEN
    bad = []
    for m in set(write_methods):
        body = re.search(rf"def {m}\b.*?(?=\n    def |\nclass |\Z)", adapter, re.S)
        if body and "NOT_PROVEN" not in body.group(0):
            bad.append(m)
    ok("schwab_adapter write methods all NOT_PROVEN", not bad, f"unguarded: {bad}" if bad else f"{len(set(write_methods))} guarded")
else:
    ok("schwab_adapter exposes no order-write methods", True)

# 3. position-sync never reaches a live write without the guard
psync = (SCRIPTS / "schwab_position_sync.py").read_text() if (SCRIPTS / "schwab_position_sync.py").exists() else ""
ok("position sync routes writes through protected_holdings_write", "protected_holdings_write" in psync and "os.replace" in psync)
ok("position sync live fetch is NOT_PROVEN (fail closed)", "NOT_PROVEN" in psync)

# 4. Schwab accounts conservative (api_write_enabled=false) + interlock refuses them
try:
    sys.path.insert(0, str(SCRIPTS))
    from db_adapter import _get_conn
    conn = _get_conn(); cur = conn.cursor()
    cur.execute("SELECT account_key, api_write_enabled FROM broker_accounts WHERE broker ILIKE '%schwab%'")
    rows = cur.fetchall()
    ok("all Schwab accounts api_write_enabled=false", all(not r[1] for r in rows), f"{len(rows)} schwab accounts" if rows else "none seeded yet")
    # interlock refuses a Schwab live account. Use the fast account_mode + master-flag path (gate_status
    # scans all paper_trades and can block on an unrelated lock — not needed to prove refusal).
    try:
        import live_trading_interlock as lti
        cur.execute("SELECT live_trading_allowed FROM paper_validation_policy WHERE active=true ORDER BY id DESC LIMIT 1")
        fr = cur.fetchone(); live_allowed = bool(fr[0]) if fr else False
        modes = {ak: lti.account_mode(conn, ak) for ak, _ in (rows or [])}
        # refusal holds iff no Schwab account is classified 'paper' (they're 'live'/unknown) AND the
        # master live-trading flag is OFF (live + not-allowed => assert_writable raises InterlockRefused)
        none_paper = all(m != "paper" for m in modes.values()) if modes else True
        ok("live_trading_interlock refuses Schwab (live + master flag OFF)", none_paper and not live_allowed,
           f"modes={modes} live_allowed={live_allowed}")
    except Exception as e:
        ok("interlock importable", False, str(e)[:60])
except Exception as e:
    ok("DB checks", False, str(e)[:60])

# 5. LEVEL II ISOLATION (Rule 9): no Schwab/Level-II/volume artifact feeds the screeners or routing.
#    Guard: the screeners and routing must not import or read any schwab/level2/volume_sweep symbol.
SCREENER_FILES = ["prime_setups", "watchlist_setups", "trade_ai_orchestrator", "atm_auto_approver"]
leak = []
for stem in SCREENER_FILES:
    for f in SCRIPTS.glob(f"*{stem}*.py"):
        txt = f.read_text()
        if re.search(r"level\s*2|level_ii|levelii|volume_sweep|depth_of_book|nasdaq_book|nyse_book|schwab_position_sync|schwab_adapter", txt, re.I):
            leak.append(f.name)
ok("Level II / volume / Schwab data isolated from screeners+routing (Rule 9)", not leak, f"leak: {leak}" if leak else "no references")

# 6. schwab-py WRAPPER write surface is fenced at the transport boundary (static)
trans = (SCRIPTS / "schwab_transport.py").read_text() if (SCRIPTS / "schwab_transport.py").exists() else ""
fenced = all(re.search(rf"def {m}\b[^\n]*\n\s+raise NotProvenWrite", trans) for m in ("place_order", "cancel_order", "replace_order"))
ok("schwab_transport order surface raises NotProvenWrite (fenced)", bool(trans) and fenced)
ok("schwab_transport never calls a wrapper client write", bool(trans) and not re.search(r"\.(place_order|cancel_order|replace_order)\s*\(", trans))

# 7. schwab-py library imported ONLY at the transport boundary (not app/endpoint/agent code)
schwab_importers = []
for f in SCRIPTS.glob("*.py"):
    if f.name in ("schwab_transport.py", "validate_schwab_no_writes.py"):
        continue
    if re.search(r"\bfrom\s+schwab\.\w|\bimport\s+schwab\b", f.read_text()):
        schwab_importers.append(f.name)
ok("schwab-py imported only at transport boundary", not schwab_importers, f"leak: {schwab_importers}" if schwab_importers else "boundary-only")

# 8. RUNTIME: the fenced writes actually raise (the safety-critical invariant — must ALWAYS hold, whether
#    creds are present or not). build_client may legitimately succeed now that reads are live (cred-in done);
#    what must never change is that the order surface is unreachable.
try:
    import schwab_transport as _st
    raised = sum(1 for m in ("place_order", "cancel_order", "replace_order")
                 if _raises_notproven(_st, m))
    client, err = _st.build_client("schwab_taxable")
    # acceptable: a live client (reads proven) OR a fail-closed status; NEVER a reachable write.
    build_ok = (client is not None) or (err or {}).get("status") in ("NOT_PROVEN", "degraded")
    ok("runtime: transport write surface raises NotProvenWrite (fence holds live)",
       raised == 3 and build_ok, f"{raised}/3 raised, build={'live-client' if client else (err or {}).get('status')}")
except Exception as e:
    ok("runtime transport check", False, str(e)[:60])

# 9. Rule-9 isolation extends to the transport (screeners/routing must not import schwab_transport)
leak2 = []
for stem in SCREENER_FILES:
    for f in SCRIPTS.glob(f"*{stem}*.py"):
        if "schwab_transport" in f.read_text():
            leak2.append(f.name)
ok("schwab_transport isolated from screeners+routing (Rule 9)", not leak2, f"leak: {leak2}" if leak2 else "no references")

# ── Stage 2a additions (2026-06-12): harness/capture read-only, hardcoded gate, dormant UI ──────
# 10. Shadow-recon harness + activity capture call NO write symbol and never import schwab-py
WRITE_RE = re.compile(r"place_order|cancel_order|replace_order|requests\.(post|put|delete|patch)")
for fname in ("schwab_shadow_recon.py", "schwab_activity_capture.py"):
    src = (SCRIPTS / fname).read_text() if (SCRIPTS / fname).exists() else ""
    clean = bool(src) and not WRITE_RE.search(src) \
        and not re.search(r"\bfrom\s+schwab\.\w|\bimport\s+schwab\b(?!_)", src)
    ok(f"{fname} is read-only (no write symbols, no schwab-py import)", clean)

# 11. Hardcoded canary gate: pure (commit-only) AND fail-closed at runtime, IN FRONT of the guard
try:
    gate_src = (SCRIPTS / "brokers" / "canary_gate.py").read_text()
    pure = not re.search(r"^\s*(import os\b|from os\b)", gate_src, re.M) \
        and not re.search(r"db_adapter|_get_conn|json\.load|yaml|configparser|open\(", gate_src)
    from brokers.order_intent import OrderIntent, Instrument, Direction, EntrySpec, EntryMethod, Quantity
    from brokers.execution_guard import authorize as _auth
    _big = OrderIntent(instrument=Instrument("AAPL"), direction=Direction.LONG,
                       entry=EntrySpec(method=EntryMethod.LIMIT, limit_price=180.0),
                       quantity=Quantity(qty=100), broker="schwab")
    d = _auth(_big, "submit")
    ok("hardcoded canary gate: pure module + out-of-envelope submit denied in front of guard",
       pure and (not d.allowed) and d.reason.startswith("CANARY_GATE BLOCK"),
       f"pure={pure} reason={d.reason[:60]}")
except Exception as e:
    ok("hardcoded canary gate check", False, str(e)[:60])

# 12. Dormant UI surface: no submit/execute route exists, and the UI files call no such endpoint
api_src = (SCRIPTS / "api_v2.py").read_text()
bad_routes = re.findall(r"broker-orders/(submit|execute|send|place|cancel-live|replace)", api_src)
ui_dir = PROJECT_ROOT / "apps" / "command-center-v3" / "src"
ui_bad = []
for uf in ("components/BrokerOrders.tsx", "components/SchwabAccountsMonitor.tsx"):
    txt = (ui_dir / uf).read_text() if (ui_dir / uf).exists() else ""
    for m in re.findall(r"fetch\('([^']+)'", txt):
        if re.search(r"submit|execute|/send|place|/live", m):
            ui_bad.append(f"{uf}:{m}")
ok("Broker Orders UI has no execution path (no submit route in API; UI calls none)",
   not bad_routes and not ui_bad, f"routes={bad_routes} ui={ui_bad}" if (bad_routes or ui_bad) else "draft/preview/approve only")

# 13. Canary analytics exclusion present in every schwab_round_trips consumer
CANARY_CONSUMERS = ["api_v2.py", "schwab_journal_builder.py", "schwab_journal_classifier.py",
                    "backtest_fill_reconciliation.py", "build_trade_execution_quality.py",
                    "ingest_schwab_gainloss.py"]
missing = [f for f in CANARY_CONSUMERS
           if "canary" not in (SCRIPTS / f).read_text()]
ok("canary exclusion wired into all round-trip consumers", not missing,
   f"missing: {missing}" if missing else f"{len(CANARY_CONSUMERS)} consumers filtered")

passed = sum(1 for _, p, _ in checks if p)
print(f"\n  {passed}/{len(checks)} guards green")
sys.exit(0 if passed == len(checks) else 1)
