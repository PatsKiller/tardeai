"""
continuous_runner_patch.py v3 — Applies remaining fixes to continuous_runner.py

Fix 2: Startup FULL run at launch (exact string match confirmed)
Fix 4: Banner update showing 4AM schedule

Already applied (skip if present):
Fix 1: SCHEDULE starts at 04:00
Fix 3: HOURLY_FULL_ANCHORS includes 04:00 + 05:00

Run from project root:
    python scripts\\continuous_runner_patch.py
"""
import sys
from pathlib import Path

root = Path(__file__).parent.parent
target = root / "scripts" / "continuous_runner.py"
if not target.exists():
    print(f"ERROR: {target} not found"); sys.exit(1)

src = target.read_text(encoding="utf-8")
original = src

# ── Fix 1: SCHEDULE (re-check) ────────────────────────────────────────────────
if '"04:00", "06:00"' not in src:
    OLD_SCHED = '''SCHEDULE = [
    # (start_hhmm, end_hhmm, interval_minutes, is_full_at_start)
    ("06:00", "09:00", 15, True),   # pre-market: 15-min cycles, full at :00
    ("09:00", "10:00", 10, True),   # market open: 10-min cycles
    ("10:00", "11:00", 15, True),   # first-hour wind-down
]'''
    NEW_SCHED = '''SCHEDULE = [
    # (start_hhmm, end_hhmm, interval_minutes, is_full_at_start)
    ("04:00", "06:00", 30, True),   # early pre-market: 30-min LIVE cycles
    ("06:00", "09:00", 15, True),   # pre-market: 15-min cycles, full at :00
    ("09:00", "10:00", 10, True),   # market open: 10-min cycles
    ("10:00", "11:00", 15, True),   # first-hour wind-down
]'''
    if OLD_SCHED in src:
        src = src.replace(OLD_SCHED, NEW_SCHED, 1)
        print("✅ Fix 1: SCHEDULE extended to 04:00")
    else:
        print("⚠️  Fix 1: not applied and target not found")
else:
    print("ℹ️  Fix 1: already applied")

# ── Fix 2: Startup FULL run — exact double-newline match ─────────────────────
if '[STARTUP]' not in src:
    # Exact string as confirmed from live file inspection
    OLD_CYCLE = "\n\n    cycle = 0\n    while True:\n        now      = datetime.now()\n"
    NEW_CYCLE = """

    # ── Startup: run FULL pipeline immediately on launch ───────────────────
    # Ensures 4AM run fires even if Task Scheduler was late or machine slept.
    _startup_now   = datetime.now()
    _startup_label = _best_run_label(_startup_now)
    _startup_date  = _startup_now.strftime("%Y-%m-%d")
    print(f"\\n[STARTUP] {_startup_now.strftime('%H:%M:%S')} — immediate FULL run (label={_startup_label})")
    try:
        run_full_cycle(root, _startup_label, _startup_date)
        print(f"[STARTUP] Complete")
    except Exception as _e:
        import traceback as _tb
        print(f"[STARTUP] ERROR: {_e}")
        _tb.print_exc()

    cycle = 0
    while True:
        now      = datetime.now()
"""
    if OLD_CYCLE in src:
        src = src.replace(OLD_CYCLE, NEW_CYCLE, 1)
        print("✅ Fix 2: Startup FULL run injected")
    else:
        # Show what we find around cycle = 0 for manual diagnosis
        idx = src.find('cycle = 0')
        if idx >= 0:
            snippet = repr(src[max(0,idx-80):idx+60])
            print(f"⚠️  Fix 2: exact match failed. Context around 'cycle = 0': {snippet}")
        else:
            print("⚠️  Fix 2: 'cycle = 0' not found at all")
else:
    print("ℹ️  Fix 2: already applied")

# ── Fix 3: HOURLY_FULL_ANCHORS (re-check) ────────────────────────────────────
if '"04:00"' not in src or 'HOURLY_FULL_ANCHORS' not in src:
    OLD_A = 'HOURLY_FULL_ANCHORS = {"06:00", "07:00", "08:00", "09:00", "10:00"}'
    NEW_A = 'HOURLY_FULL_ANCHORS = {"04:00", "05:00", "06:00", "07:00", "08:00", "09:00", "10:00"}'
    if OLD_A in src:
        src = src.replace(OLD_A, NEW_A, 1)
        print("✅ Fix 3: HOURLY_FULL_ANCHORS updated")
    else:
        print("⚠️  Fix 3: not applied and target not found")
else:
    print("ℹ️  Fix 3: already applied")

# ── Fix 4: Banner print ───────────────────────────────────────────────────────
if '4\u20136 AM' not in src:
    OLD_B = '    print(f"  Schedule: 6\u20139 AM (15min) \u00b7 9\u201310 AM (10min) \u00b7 10\u201311 AM (15min)")'
    NEW_B = ('    print(f"  Schedule: 4\u20136 AM (30min) \u00b7 6\u20139 AM (15min) '
             '\u00b7 9\u201310 AM (10min) \u00b7 10\u201311 AM (15min)")\n'
             '    print(f"  Startup FULL run: fires immediately on launch")')
    if OLD_B in src:
        src = src.replace(OLD_B, NEW_B, 1)
        print("✅ Fix 4: Banner updated")
    else:
        print("ℹ️  Fix 4: banner string not matched (non-critical)")
else:
    print("ℹ️  Fix 4: already applied")

# ── Save ──────────────────────────────────────────────────────────────────────
if src != original:
    bak = target.with_suffix(".py.bak3")
    bak.write_text(original, encoding="utf-8")
    target.write_text(src, encoding="utf-8")
    print(f"\n✅ Saved → {target.name}  (backup → {bak.name})")
else:
    print("\nℹ️  No changes made")

# Verify
print("\n── Verification ──────────────────────────────────────")
final = target.read_text(encoding="utf-8")
print(f"  Fix 1 (04:00 schedule):      {'✅' if '\"04:00\", \"06:00\"' in final else '❌'}")
print(f"  Fix 2 (startup FULL run):    {'✅' if '[STARTUP]' in final else '❌'}")
print(f"  Fix 3 (anchors 04:00+05:00): {'✅' if '\"04:00\"' in final and 'HOURLY_FULL_ANCHORS' in final else '❌'}")
print(f"  Fix 4 (banner 4-6AM):        {'✅' if '4\u20136 AM' in final else '❌'}")
