#!/usr/bin/env python3
"""snaptrade_sync.py — read-only holdings sync from SnapTrade into holdings.json.

ADDITIVE + SAFE BY DEFAULT:
  • Dry run unless --apply (prints what WOULD change; writes nothing).
  • Only the accounts mapped in config/snaptrade_accounts.json are touched; every other account in
    holdings.json is preserved verbatim.
  • The write goes through schwab_position_sync.protected_holdings_write() — same sanity / no-wipe /
    catastrophic-drop guard as the Schwab sync.
  • No trading. Read only.

Setup: save client keys (UI modal) → `snaptrade_connect.py register/login` → map accounts in
config/snaptrade_accounts.json → run this (dry) → `--apply` once it looks right.

  python3 scripts/snaptrade_sync.py            # dry run
  python3 scripts/snaptrade_sync.py --apply    # merge mapped accounts into holdings.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "brokers"))

HOLDINGS_PATH = PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"
ACCOUNTS_MAP_PATH = PROJECT_ROOT / "config" / "snaptrade_accounts.json"
STATE_PATH = PROJECT_ROOT / "data" / "runtime" / "snaptrade_sync_state.json"
# A mapped account that SnapTrade stops returning is only ZEROED after this many consecutive --apply syncs
# confirm it's gone — so a transient API miss never wipes a live account (e.g. the 401k mid-rollover).
VANISH_CONFIRM_SYNCS = 2

# SnapTrade returns a freshly-linked account with NO holdings for hours after the first link (its data
# pull from the brokerage is pending). Never overwrite a currently-FUNDED account (in holdings.json)
# with that empty response — skip it until real data arrives. Below this $ value an "empty" sync is fine.
EMPTY_SYNC_SKIP_THRESHOLD = 100.0
FINVIZ_CACHE_PATH = PROJECT_ROOT / "data" / "portfolios" / "state" / "finviz_quote_cache.json"


def _overlay_live_prices(positions: list[dict]) -> list[dict]:
    """SnapTrade position prices lag hours — overlay Finviz Elite / market_quotes for MV and P/L."""
    if not positions:
        return positions
    fv: dict = {}
    try:
        if FINVIZ_CACHE_PATH.exists():
            fv = json.loads(FINVIZ_CACHE_PATH.read_text())
    except Exception:
        pass
    mq: dict[str, float] = {}
    try:
        from db_adapter import _get_conn
        conn = _get_conn(); cur = conn.cursor()
        syms = [(p.get("symbol") or "").upper() for p in positions if not p.get("is_cash")]
        if syms:
            cur.execute("""SELECT DISTINCT ON (symbol) symbol, price
                           FROM market_quotes WHERE symbol = ANY(%s)
                           ORDER BY symbol, fetched_at DESC""", (syms,))
            for sym, px in cur.fetchall():
                try:
                    mq[str(sym).upper()] = float(px)
                except (TypeError, ValueError):
                    pass
        conn.close()
    except Exception:
        pass
    for p in positions:
        if p.get("is_cash"):
            continue
        sym = (p.get("symbol") or "").upper()
        fvrow = fv.get(sym) if isinstance(fv.get(sym), dict) else {}
        px = mq.get(sym) or fvrow.get("price")
        try:
            px = float(px) if px is not None else None
        except (TypeError, ValueError):
            px = None
        if not px or px <= 0:
            continue
        shares = float(p.get("shares") or 0)
        if shares <= 0:
            continue
        p["current_price"] = round(px, 4)
        p["price"] = round(px, 4)
        p["market_value"] = round(px * shares, 2)
        p["price_source"] = "market_quotes" if sym in mq else "finviz"
        cb = p.get("cost_basis")
        if cb is None and p.get("avg_cost"):
            cb = float(p["avg_cost"]) * shares
            p["cost_basis"] = round(cb, 2)
        if cb:
            p["gain_loss"] = round(p["market_value"] - float(cb), 2)
            p["gain_loss_pct"] = round(p["gain_loss"] / float(cb) * 100, 4) if float(cb) else None
        chg = fvrow.get("change_pct")
        if chg is not None:
            try:
                p["day_change_pct"] = float(chg)
                prev = px / (1 + float(chg) / 100) if float(chg) != -100 else px
                p["day_change"] = round((px - prev) * shares, 2)
            except (TypeError, ValueError, ZeroDivisionError):
                pass
    return positions


def _current_account_value(account_key: str) -> float:
    """Sum of market_value for an account_key in the live holdings.json (0 if absent/unreadable)."""
    try:
        cur = json.loads(HOLDINGS_PATH.read_text())
        return round(sum((h.get("market_value") or 0) for h in cur.get("holdings", [])
                         if h.get("account") == account_key), 2)
    except Exception:
        return 0.0


def _load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(state, indent=2))
    except Exception:
        pass


def _load_account_map() -> dict:
    """{ snaptrade_account_id: internal_account_key }."""
    if not ACCOUNTS_MAP_PATH.exists():
        return {}
    try:
        cfg = json.loads(ACCOUNTS_MAP_PATH.read_text())
        return cfg.get("accounts", cfg) if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def _merge(current: dict, synced_by_account: dict[str, list[dict]]) -> dict:
    """Replace ONLY the synced accounts' positions; keep everything else untouched. Pure function."""
    owned = set(synced_by_account.keys())
    kept = [h for h in current.get("holdings", []) if h.get("account") not in owned]
    fresh = [pos for positions in synced_by_account.values() for pos in positions]
    out = dict(current)
    out["holdings"] = kept + fresh
    return out


def _summary(positions: list[dict]) -> str:
    n = len(positions)
    val = sum(float(p.get("market_value") or 0) for p in positions)
    return f"{n} positions, ${val:,.0f}"


def run(apply: bool = False) -> dict:
    from brokers import snaptrade_read as sr
    from brokers import snaptrade_credentials as creds

    if not creds.status().get("ready"):
        return {"ok": False, "error": "client keys not set (UI modal)"}
    if not creds.user_status().get("ready"):
        return {"ok": False, "error": "no connected user — run snaptrade_connect.py register/login"}

    acct_map = _load_account_map()
    if not acct_map:
        return {"ok": False, "error": f"no account mapping — fill {ACCOUNTS_MAP_PATH}"}

    try:
        user = sr.SnapTradeUser.from_env()
        accounts = sr.list_accounts(user)
    except Exception as e:
        return {"ok": False, "error": f"snaptrade read failed: {e}"}

    synced: dict[str, list[dict]] = {}
    report = []
    for a in accounts:
        aid = str(a.get("id") or a.get("account_id") or "")
        key = acct_map.get(aid)
        if not key:
            continue  # account not opted into the sync
        try:
            raw = sr.holdings(user, aid)
            bal = sr.balances(user, aid)
            positions = sr.reconcile_cash_positions(sr.normalize_positions(raw, key), bal, key)
            positions = _overlay_live_prices(positions)
        except Exception as e:
            report.append(f"  {key} ({aid}): read error — {e}")
            continue
        # data-pull-pending guard: don't wipe a funded account with an empty post-link response
        synced_val = round(sum((p.get("market_value") or 0) for p in positions), 2)
        if synced_val <= EMPTY_SYNC_SKIP_THRESHOLD:
            cur_val = _current_account_value(key)
            if cur_val > EMPTY_SYNC_SKIP_THRESHOLD:
                report.append(f"  {key} ({aid}): SnapTrade returned EMPTY (${synced_val:,.0f}) but account "
                              f"is funded (${cur_val:,.0f}) — SKIP (data pull pending, keeping prior)")
                continue
        synced[key] = positions
        report.append(f"  {key} ({aid}): {_summary(positions)}")

    # ── vanished-account detection (e.g. the 401k closing after a rollover) ──────────────────────────
    # A mapped account that SnapTrade no longer returns is ZEROED — but only after VANISH_CONFIRM_SYNCS
    # consecutive --apply runs confirm it, so a transient API miss never wipes a live account. Guarded by
    # a non-empty listing (if SnapTrade returns NO accounts at all, treat as an anomaly and touch nothing).
    listed_ids = {str(a.get("id") or a.get("account_id") or "") for a in accounts}
    state = _load_state()
    miss = dict(state.get("missing", {}))
    zeroed: list[str] = []
    if accounts:  # only run the check when the listing itself is healthy
        for aid, key in acct_map.items():
            if aid in listed_ids:
                miss.pop(key, None)  # present → reset the counter
            else:
                n = miss.get(key, 0) + 1
                miss[key] = n
                if n >= VANISH_CONFIRM_SYNCS:
                    synced[key] = []  # confirmed gone → zero its holdings in the merge
                    zeroed.append(key)
                    report.append(f"  {key} ({aid}): VANISHED {n}x — zeroing holdings")
                else:
                    report.append(f"  {key} ({aid}): not returned by SnapTrade "
                                  f"({n}/{VANISH_CONFIRM_SYNCS} confirmations before zeroing)")

    print("SnapTrade read-only sync — mapped accounts:")
    print("\n".join(report) if report else "  (no mapped accounts matched the connected brokerages)")

    if not synced:
        return {"ok": True, "applied": False, "accounts": 0, "note": "nothing to sync"}

    if not apply:
        print("DRY RUN — nothing written. Re-run with --apply to merge into holdings.json.")
        return {"ok": True, "applied": False, "accounts": len(synced),
                "would_write": {k: len(v) for k, v in synced.items()},
                "would_zero": zeroed}

    # persist the confirmation counters (only on a real apply, so dry runs don't advance them)
    state["missing"] = miss
    _save_state(state)

    if zeroed:
        try:
            from alert_event_writer import save_alert_event
            save_alert_event(alert_type="system_health", severity="warning",
                             source_script="snaptrade_sync.py",
                             raw_text=f"[snaptrade] zeroed vanished account(s): {', '.join(zeroed)} "
                                      f"(no longer returned by SnapTrade after {VANISH_CONFIRM_SYNCS} syncs)",
                             parsed_payload={"kind": "snaptrade_account_vanished", "accounts": zeroed})
        except Exception:
            pass

    # apply: merge only the synced accounts, write through the sanity gate
    import schwab_position_sync as sps
    current = json.loads(HOLDINGS_PATH.read_text()) if HOLDINGS_PATH.exists() else {"holdings": []}
    merged = _merge(current, synced)
    result = sps.protected_holdings_write(merged, source="snaptrade",
                                          account_key=",".join(sorted(synced.keys())), protect_basis=False)
    print(f"holdings write: {result.get('status')} (wrote={result.get('wrote')})")
    if result.get("wrote"):
        try:
            import portfolio_repricer as _pr
            _hp = json.loads(HOLDINGS_PATH.read_text())
            _repriced = _pr.reprice_portfolio(_hp, PROJECT_ROOT / "data" / "portfolios" / "state")
            HOLDINGS_PATH.write_text(json.dumps(_repriced, indent=2, default=str))
            print("holdings repriced after SnapTrade merge (totals + Finviz overlay)")
        except Exception as _e:
            print(f"WARNING: post-sync repricer failed ({_e}) — run portfolio_repricer.py manually")
    return {"ok": bool(result.get("wrote")), "applied": True, "accounts": len(synced),
            "zeroed": zeroed, "write": result}


def main():
    ap = argparse.ArgumentParser(description="SnapTrade read-only holdings sync.")
    ap.add_argument("--apply", action="store_true", help="merge mapped accounts into holdings.json (default: dry run)")
    a = ap.parse_args()
    out = run(apply=a.apply)
    print(json.dumps(out, indent=2, default=str))
    sys.exit(0 if out.get("ok") else 1)


if __name__ == "__main__":
    main()
