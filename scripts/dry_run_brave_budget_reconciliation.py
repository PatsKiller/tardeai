#!/usr/bin/env python3
"""Dry run for the single-ledger Brave budget. No network. No production writes.

Validates, against an ISOLATED ledger in a temp directory, every property the
reconciliation depends on:

  1. a reservation spends exactly one unit, before any request
  2. a refund returns exactly one, and never invents credit
  3. a failed request refunds, so the ledger never charges for work not done
  4. per-caller daily caps bind in the canonical ledger (they used to live only
     in the second one, which is why that one still counted)
  5. two concurrent processes cannot both spend the last unit
  6. the legacy ledger is no longer written by any path
  7. an exhausted or unreadable budget DENIES — never fails open

Run:  python scripts/dry_run_brave_budget_reconciliation.py
Exit 0 only if every property holds.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

NOW = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)

passed = 0
failed = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  [PASS] {label}")
    else:
        failed += 1
        print(f"  [FAIL] {label}" + (f" — {detail}" if detail else ""))


def used(sb, root: Path, provider: str = "brave") -> int:
    return int(sb.status(provider, now=NOW, root=root)["monthly_used"])


def main() -> int:
    from scripts.lib import search_budget as sb

    sandbox = Path(tempfile.mkdtemp(prefix="brave-dry-"))
    print(f"isolated ledger: {sb.budget_path(sandbox)}")
    print(f"production ledger (MUST NOT CHANGE): {sb.budget_path()}")

    prod = sb.budget_path()
    prod_before = prod.read_bytes() if prod.is_file() else None

    # ── 1. reserve spends exactly one ───────────────────────────────────────
    print("\n1. reservation")
    before = used(sb, sandbox)
    v = sb.try_consume("brave", caller="web_research", now=NOW, root=sandbox)
    check("a reservation is allowed on a fresh ledger", v["allowed"], v.get("reason", ""))
    check("it spends exactly one unit", used(sb, sandbox) == before + 1,
          f"{before} -> {used(sb, sandbox)}")

    # ── 2. refund returns exactly one, and never invents credit ─────────────
    print("\n2. refund")
    mid = used(sb, sandbox)
    check("a refund returns one unit",
          sb.refund("brave", caller="web_research", now=NOW, root=sandbox)
          and used(sb, sandbox) == mid - 1, f"now {used(sb, sandbox)}")
    # Drain to zero, then try to refund again.
    while used(sb, sandbox) > 0:
        sb.refund("brave", caller="web_research", now=NOW, root=sandbox)
    check("a refund against an empty day returns False, not credit",
          sb.refund("brave", caller="web_research", now=NOW, root=sandbox) is False)
    check("and the counter never goes below zero", used(sb, sandbox) == 0,
          str(used(sb, sandbox)))

    # ── 3. a failed request refunds ─────────────────────────────────────────
    # Drive the real brave_search paths with a key present and the network
    # guaranteed to fail, and assert the ledger is unchanged afterwards.
    print("\n3. a request that fails must not be charged")
    import brave_search as b

    monkey_root = sandbox
    orig_budget_path = sb.budget_path

    def _sandboxed(root=None):
        return orig_budget_path(monkey_root)

    sb.budget_path = _sandboxed                       # isolate every write below
    b._get_api_key = lambda project_root=".": "dry-run-not-a-real-key"
    b.BRAVE_API_URL = "http://127.0.0.1:1/never"      # connection refused
    b.BRAVE_NEWS_URL = "http://127.0.0.1:1/never"
    b._search_cache.clear()

    start = used(sb, sandbox)
    out = b.search("dry run query", caller="web_research")
    check("a failed web search returns []", out == [], repr(out)[:60])
    check("a failed web search leaves the counter unchanged (reserved then refunded)",
          used(sb, sandbox) == start, f"{start} -> {used(sb, sandbox)}")

    b._search_cache.clear()
    start = used(sb, sandbox)
    out = b.search_news("dry run query", caller="web_research")
    check("a failed news search returns []", out == [])
    check("a failed news search leaves the counter unchanged",
          used(sb, sandbox) == start, f"{start} -> {used(sb, sandbox)}")

    # A refund must be recorded as a refund, not as a denial: denial history is
    # read to answer "did the budget refuse us", and conflating them ruins it.
    doc = json.loads(sb.budget_path(sandbox).read_text())
    p = doc["providers"]["brave"]
    day = NOW.strftime("%Y-%m-%d")
    check("refunds are recorded separately from denials",
          int((p.get("refunds") or {}).get(day, 0)) >= 2
          and int((p.get("denied") or {}).get(day, 0)) == 0,
          f"refunds={p.get('refunds')} denied={p.get('denied')}")

    sb.budget_path = orig_budget_path

    # ── 4. per-caller daily caps bind in the canonical ledger ───────────────
    print("\n4. per-caller daily caps (moved from the retired ledger)")
    capbox = Path(tempfile.mkdtemp(prefix="brave-cap-"))
    os.environ["SEARCH_BUDGET_BRAVE_DAILY"] = "10000"
    os.environ["SEARCH_BUDGET_BRAVE_MONTHLY"] = "10000"
    cap = sb.caller_daily_cap("topic_ingestion")
    check("topic_ingestion has a tighter cap than default",
          cap < sb.caller_daily_cap("default"), f"{cap} vs {sb.caller_daily_cap('default')}")
    for i in range(cap):
        r = sb.try_consume("brave", caller="topic_ingestion", now=NOW, root=capbox)
        if not r["allowed"]:
            check(f"call {i + 1} of {cap} allowed", False, r["reason"])
            break
    blocked = sb.try_consume("brave", caller="topic_ingestion", now=NOW, root=capbox)
    check("the caller cap binds after its own allowance",
          not blocked["allowed"] and blocked["reason"] == "CALLER_DAILY_CAP",
          f"{blocked.get('reason')}")
    other = sb.try_consume("brave", caller="web_research", now=NOW, root=capbox)
    check("a different caller is unaffected by another's cap", other["allowed"],
          other.get("reason", ""))
    os.environ.pop("SEARCH_BUDGET_BRAVE_DAILY", None)
    os.environ.pop("SEARCH_BUDGET_BRAVE_MONTHLY", None)

    # ── 5. two processes cannot both spend the last unit ───────────────────
    print("\n5. concurrency on the last unit")
    racebox = Path(tempfile.mkdtemp(prefix="brave-race-"))
    code = (
        "from pathlib import Path\n"
        "from datetime import datetime, timezone\n"
        "from scripts.lib import search_budget as sb\n"
        f"root = Path({str(racebox)!r})\n"
        "now = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)\n"
        "v = sb.try_consume('brave', caller='race', now=now, root=root)\n"
        "print('ALLOW' if v['allowed'] else 'DENY')\n"
    )
    env = {**os.environ, "PYTHONPATH": str(ROOT),
           "SEARCH_BUDGET_BRAVE_DAILY": "1", "SEARCH_BUDGET_BRAVE_MONTHLY": "100"}
    procs = [subprocess.Popen([sys.executable, "-c", code], cwd=str(ROOT), env=env,
                              stdout=subprocess.PIPE, text=True) for _ in range(2)]
    outs = [p.communicate()[0].strip() for p in procs]
    check("exactly one of two racing processes spends the last unit",
          outs.count("ALLOW") == 1, str(outs))

    # ── 6. the legacy ledger is no longer written ──────────────────────────
    print("\n6. the retired ledger stays retired")
    check("_record_call writes nothing",
          b._record_call("web_research") is None)
    legacy = b._BUDGET_FILE
    legacy_before = legacy.read_bytes() if legacy.is_file() else None
    b._search_cache.clear()
    sb.budget_path = _sandboxed
    b.search("another dry query", caller="web_research")
    sb.budget_path = orig_budget_path
    legacy_after = legacy.read_bytes() if legacy.is_file() else None
    check("a search leaves the legacy ledger byte-identical",
          legacy_before == legacy_after,
          "the retired ledger was written")

    # ── 7. never fail open ─────────────────────────────────────────────────
    print("\n7. fail closed")
    corrupt = Path(tempfile.mkdtemp(prefix="brave-corrupt-"))
    cp = sb.budget_path(corrupt)
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text("{not json")
    v = sb.try_consume("brave", caller="web_research", now=NOW, root=corrupt)
    check("an unreadable ledger DENIES", not v["allowed"], v.get("reason", ""))
    check("and it is not rebuilt as a fresh zero counter",
          cp.read_text() == "{not json")

    exhausted = Path(tempfile.mkdtemp(prefix="brave-exh-"))
    os.environ["SEARCH_BUDGET_BRAVE_MONTHLY"] = "1"
    os.environ["SEARCH_BUDGET_BRAVE_DAILY"] = "1000"
    sb.try_consume("brave", caller="web_research", now=NOW, root=exhausted)
    v = sb.try_consume("brave", caller="web_research", now=NOW, root=exhausted)
    check("an exhausted month DENIES", not v["allowed"], v.get("reason", ""))
    os.environ.pop("SEARCH_BUDGET_BRAVE_MONTHLY", None)
    os.environ.pop("SEARCH_BUDGET_BRAVE_DAILY", None)

    # ── the whole point: production was never touched ──────────────────────
    print("\n8. blast radius")
    prod_after = prod.read_bytes() if prod.is_file() else None
    check("the PRODUCTION ledger is byte-identical after this dry run",
          prod_before == prod_after, "production ledger changed — dry run was not dry")

    print(f"\ndry run: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
