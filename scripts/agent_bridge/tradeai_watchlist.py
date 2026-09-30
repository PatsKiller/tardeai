#!/usr/bin/env python3
"""Canonical tradeai-watchlist HTTP bridge for the agent skill surface.

Install/sync into the local skill scripts dir when an operator grants skill writes.
ZERO third-party deps (urllib + json only).

2026-09-29 NFLX: POST /watch/directives can exceed the skill HTTP timeout while the
directive IS saved. On timeout, verify provenance before reporting failure. Operator
chat adds use priority=high so Hermes research is prioritized.
"""
import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:7777/api/v2"


def _get(path, timeout=30):
    req = urllib.request.Request(BASE + path, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.load(r)
    return d.get("data", d) if isinstance(d, dict) else d


def _post(path, body, timeout=45):
    req = urllib.request.Request(
        BASE + path,
        method="POST",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _die(msg):
    print(f"❌ {msg}")
    sys.exit(1)


def _flag(args, name, default=None):
    if name in args:
        i = args.index(name)
        if i + 1 < len(args):
            return args[i + 1]
    return default


def _confirmed_on_watch(symbol: str) -> bool:
    """True when Trade AI already shows the ticker under a directive watch."""
    try:
        d = _get(f"/watch/provenance/{symbol}", timeout=8)
        if isinstance(d, dict) and d.get("in_directive_watch"):
            return True
    except Exception:
        pass
    return False


def cmd_add(args):
    label = _flag(args, "--label", "Watchlist")
    note = _flag(args, "--note", "added via agent watchlist skill")
    syms = [a.upper() for a in args if not a.startswith("--") and a not in (label, note)]
    if not syms:
        _die('no symbols given. Usage: add ANET TSM --label "Data Center"')
    ok, failed, deferred = [], [], []
    for s in syms:
        try:
            r = _post(
                "/watch/directives",
                {
                    "kind": "ticker",
                    "label": label,
                    "spec": {"symbol": s},
                    "rationale": f"{note} (operator via agent)",
                    "priority": "high",
                    "trade_ai_enabled": True,
                    "hermes_enabled": True,
                },
                timeout=20,
            )
            if r.get("directive_id") is not None:
                ok.append(s)
                serv = (r.get("serviced") or {}) if isinstance(r, dict) else {}
                if isinstance(serv, dict) and serv.get("status") == "QUEUED_ASYNC":
                    deferred.append(s)
            else:
                failed.append(f"{s}({r.get('error', 'no id')})")
        except Exception as e:
            err = str(e)[:80]
            if "timed out" in err.lower() or "timeout" in err.lower():
                time.sleep(1.5)
                if _confirmed_on_watch(s):
                    ok.append(s)
                    deferred.append(s)
                else:
                    failed.append(
                        f"{s}(timed out; provenance does not yet show directive watch — retry)"
                    )
            else:
                failed.append(f"{s}({err[:40]})")
    if ok:
        extra = ""
        if deferred:
            extra = (
                f" Promote/enrich still finishing for {', '.join(deferred)}; "
                "research is owed and should return within ~20 min when Hermes completes."
            )
        print(
            f"✅ Added to watchlist under \"{label}\": {', '.join(ok)} — "
            f"watched and monitored (priority=high).{extra}"
        )
    if failed:
        print(f"⚠️ Failed: {', '.join(failed)}")
    if not ok:
        sys.exit(1)


def cmd_watchlist(args):
    status = _flag(args, "--status")
    limit = int(_flag(args, "--limit", "25"))
    q = "/watchlist/items?sort=hermes" + (f"&status={status}" if status else "")
    d = _get(q)
    items = d.get("items", []) if isinstance(d, dict) else []

    def _itag(it):
        t = (it.get("instrument_type") or "").lower()
        return f" [{t.upper().replace('_', ' ')}]" if t and t != "stock" else ""

    etfs = sorted(
        {
            i.get("symbol")
            for i in items
            if (i.get("instrument_type") or "").lower() in ("etf", "fund", "inverse_etf")
        }
    )
    etf_line = (
        f"  ETFs/funds on watchlist ({len(etfs)}): {', '.join(etfs)}"
        if etfs
        else "  ETFs/funds on watchlist: none"
    )
    print(f"📋 Watchlist — {len(items)} shown (top by Hermes rank):")
    print(etf_line)
    for it in items[:limit]:
        cio = it.get("latest_recommendation") or "—"
        sec = it.get("profile_sector") or "—"
        ep = f" · entry ${it.get('entry_limit')}" if it.get("entry_limit") else ""
        print(f"  {it.get('symbol'):6} CIO:{cio:14} {sec}{_itag(it)}{ep}")


def cmd_prospects(args):
    limit = int(_flag(args, "--limit", "15"))
    d = _get("/watchlist/items?sort=hermes")
    items = d.get("items", []) if isinstance(d, dict) else []
    buy = [
        i
        for i in items
        if str(i.get("latest_recommendation") or "").upper()
        in ("BUY", "STRONG_BUY", "ADD", "ADD_ON_PULLBACK")
    ]
    print(f"🎯 Prospects — {len(buy)} buy-rated names (CIO BUY/ADD):")
    for it in buy[:limit]:
        up = it.get("entry_limit")
        print(
            f"  {it.get('symbol'):6} {str(it.get('latest_recommendation')):14} "
            f"{it.get('profile_sector') or '—'}" + (f" · entry ${up}" if up else "")
        )


def cmd_ticker(args):
    if not args:
        _die("Usage: ticker SYM")
    sym = args[0].upper()
    d = _get(f"/watch/provenance/{sym}")
    print(f"🔎 {sym}")
    print(json.dumps(d, indent=2)[:4000])


def main():
    if len(sys.argv) < 2:
        _die("Usage: tradeai_watchlist.py <add|watchlist|prospects|ticker> ...")
    cmd = sys.argv[1]
    args = sys.argv[2:]
    if cmd == "add":
        cmd_add(args)
    elif cmd == "watchlist":
        cmd_watchlist(args)
    elif cmd == "prospects":
        cmd_prospects(args)
    elif cmd == "ticker":
        cmd_ticker(args)
    else:
        _die(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
