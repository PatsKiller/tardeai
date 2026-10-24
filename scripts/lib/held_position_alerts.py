"""held_position_alerts — how a held position is named in an alert, and whether it may page.

P1 2026-10-23 (NVDA). The material-change notifier paged "🚨 STOP HIT — NVDA (held, 0.133 sh) …
stop $213.00 … review exit — price is through your plan stop" 31 times since 2026-09-28. The 0.133
share was a moomoo account-opening reward ($28, no cost basis); the operator did not recognise it
because the page never said which account held it. The "$213.00 plan stop" was not a stop anyone
set: it was the stop of a watchlist *entry* plan written by the LLM entry planner
(watchlist_entry_plans id 23236, grok-3-mini, entry_planner_v1, 2026-10-21) — a level below a
proposed buy zone, called "your plan stop" on a position the plan never covered.

This module is the one place that answers, for every held-position notice:

  * which account(s) hold it — by NAME only (scripts/lib/account_display.py; never digits);
  * whether it is a promo/reward or a tiny/untracked position (config/held_position_alerts.json);
  * whether it may receive stop / exit pages (excluded by default when tiny or promo, unless the
    operator opted in);
  * who owns a stop: "your stop" only for an operator-set stop, the broker's name for a
    broker-reported stop order, and an explicit "system … level (not a stop you set)" otherwise.

Pure apart from reading the policy file and (by default) the position store via portfolio_positions. No broker, no network,
no DB. AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "config" / "held_position_alerts.json"

TAG_PROMO = "promo/reward"
TAG_TINY = "tiny/untracked"

DEFAULTS: dict[str, Any] = {
    "de_minimis_usd": 100.0,
    "promo_max_usd": 100.0,
    "exclude_tiny_from_stop_exit_alerts": True,
    "exclude_promo_from_stop_exit_alerts": True,
    "comms_editor_account_tag": True,
    "opt_in": [],
    "promo_positions": [],
}

#: Where a plan level came from, in words the operator can act on. None of these is a stop the
#: operator set: they are levels the system derived for an entry or a strategy.
SYSTEM_LEVEL_NAMES = {
    "entry_plan": "system entry-plan level",
    "strategy_card": "system strategy-card level",
}


# ── policy ──────────────────────────────────────────────────────────────────


def load_policy(path: Optional[Path] = None) -> dict:
    """The policy with defaults filled in. An unreadable file falls back to the safe defaults."""
    p = Path(path) if path else Path(os.environ.get("TRADEAI_HELD_POSITION_ALERTS", "") or POLICY_PATH)
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = {}
    out = dict(DEFAULTS)
    for k in DEFAULTS:
        if k in doc:
            out[k] = doc[k]
    return out


# ── account names ───────────────────────────────────────────────────────────

_DIGITS = re.compile(r"\d{3,}")


def account_label(key: Any) -> str:
    """The account's short human name (account_display, PR #2020). Never an account number."""
    try:
        from scripts.lib.account_display import account_label as _label  # noqa: PLC0415
    except ImportError:  # pragma: no cover - scripts/ on path
        try:
            from lib.account_display import account_label as _label  # type: ignore  # noqa: PLC0415
        except ImportError:
            _label = None
    if _label is not None:
        return str(_label(key))
    s = str(key or "").strip()
    if not s or _DIGITS.search(s):
        return "Unlabelled account"
    return re.sub(r"\bIra\b", "IRA", s.replace("_live", "").replace("_", " ").title())


# ── holdings ────────────────────────────────────────────────────────────────

_HOLDINGS_CACHE: dict[str, Any] = {"mtime": None, "doc": None}


def _pp():
    try:
        from scripts.lib import portfolio_positions as pp  # noqa: PLC0415
    except ImportError:  # pragma: no cover - scripts/ on path
        from lib import portfolio_positions as pp  # type: ignore  # noqa: PLC0415
    return pp


def load_holdings(path: Optional[Path] = None) -> dict:
    """The position store through portfolio_positions (the one accessor), cached on mtime.
    Missing or unreadable → {} (no tag, never a guess)."""
    pp = _pp()
    if path is not None:
        return pp.load_store(Path(path))
    try:
        p = pp.store_path()
        mt = p.stat().st_mtime
    except Exception:  # noqa: BLE001
        return {}
    if _HOLDINGS_CACHE["mtime"] != mt:
        _HOLDINGS_CACHE.update(mtime=mt, doc=pp.load_store(p))
    return _HOLDINGS_CACHE["doc"] or {}


def _num(v: Any) -> Optional[float]:
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def _is_promo_listed(account: str, symbol: str, policy: Mapping[str, Any]) -> bool:
    for p in policy.get("promo_positions") or []:
        if not isinstance(p, Mapping):
            continue
        if str(p.get("symbol") or "").upper() == symbol and str(p.get("account") or "") in ("", account):
            return True
    return False


def position_tag(row: Mapping[str, Any], policy: Optional[Mapping[str, Any]] = None) -> Optional[str]:
    """promo/reward | tiny/untracked | None for one holdings row (one account).

    promo/reward: listed in promo_positions, or no cost basis and a market value above $0 and under
    promo_max_usd (a $0 row with no basis is a dead or delisted line, not a reward).
    tiny/untracked: any other position under de_minimis_usd.
    """
    pol = policy or load_policy()
    sym = str(row.get("symbol") or "").upper()
    acct = str(row.get("account") or row.get("account_id") or "")
    if _is_promo_listed(acct, sym, pol):
        return TAG_PROMO
    mv = _num(row.get("market_value"))
    cost = _num(row.get("cost_basis"))
    if (cost is None or cost <= 0) and mv is not None and 0 < mv < float(pol["promo_max_usd"]):
        return TAG_PROMO
    if mv is not None and mv < float(pol["de_minimis_usd"]):
        return TAG_TINY
    return None


def opted_in(symbol: str, account: str, policy: Mapping[str, Any]) -> bool:
    sym = str(symbol or "").upper()
    for o in policy.get("opt_in") or []:
        o = str(o or "").strip()
        if not o:
            continue
        if ":" in o:
            a, s = o.split(":", 1)
            if s.strip().upper() == sym and a.strip() == account:
                return True
        elif o.upper() == sym:
            return True
    return False


def positions_for(symbol: str, holdings: Optional[Mapping[str, Any]] = None,
                  policy: Optional[Mapping[str, Any]] = None) -> list[dict]:
    """One row per account holding `symbol` (shares > 0), with name, tag and alert eligibility."""
    pol = policy or load_policy()
    doc = holdings if holdings is not None else load_holdings()
    sym = str(symbol or "").upper()
    out: list[dict] = []
    for h in (doc.get("holdings") or []):
        if not isinstance(h, Mapping) or h.get("is_cash") or str(h.get("symbol") or "").upper() != sym:
            continue
        shares = _num(h.get("shares")) or 0.0
        if shares <= 0:
            continue
        acct = str(h.get("account") or h.get("account_id") or "")
        tag = position_tag(h, pol)
        excluded = (tag == TAG_PROMO and pol["exclude_promo_from_stop_exit_alerts"]) or (
            tag == TAG_TINY and pol["exclude_tiny_from_stop_exit_alerts"]
        )
        out.append({
            "account_id": acct,
            "account_label": account_label(acct),
            "shares": shares,
            "market_value": _num(h.get("market_value")),
            "cost_basis": _num(h.get("cost_basis")),
            "source": h.get("source"),
            "tag": tag,
            "stop_exit_alerts": (not excluded) or opted_in(sym, acct, pol),
        })
    return out


def shares_text(shares: float) -> str:
    s = float(shares)
    return f"{s:,.0f}" if s.is_integer() else f"{s:,.3f}".rstrip("0").rstrip(".")


def accounts_text(positions: Iterable[Mapping[str, Any]]) -> str:
    """'moomoo Taxable 0.133 sh (promo/reward)' — one entry per account, names only."""
    parts = []
    for p in positions:
        bit = f"{p.get('account_label') or 'Unlabelled account'} {shares_text(p.get('shares') or 0)} sh"
        if p.get("tag"):
            bit += f" ({p['tag']})"
        parts.append(bit)
    return ", ".join(parts)


def held_text(holding: Optional[Mapping[str, Any]]) -> Optional[str]:
    """'held · moomoo Taxable 0.133 sh (promo/reward)'. Falls back to the account names when the
    holding carries no per-account rows (older callers), and to the share count alone last."""
    if not holding:
        return None
    positions = holding.get("positions") or []
    if positions:
        return "held · " + accounts_text(positions)
    accounts = [str(a) for a in (holding.get("accounts") or []) if a]
    sh = shares_text(holding.get("shares") or 0)
    if len(accounts) == 1:
        return f"held · {accounts[0]} {sh} sh"
    if accounts:
        return f"held · {sh} sh in {', '.join(accounts)}"
    return f"held, {sh} sh"


def stop_exit_alerts_allowed(holding: Optional[Mapping[str, Any]]) -> bool:
    """A stop / exit page is allowed when at least one holding account is eligible."""
    if not holding:
        return False
    positions = holding.get("positions")
    if not positions:
        return True  # no per-account facts: keep the prior behaviour
    return any(p.get("stop_exit_alerts") for p in positions)


# ── stop provenance ─────────────────────────────────────────────────────────


def stop_owner(real_stop: Optional[Mapping[str, Any]]) -> Optional[str]:
    """'your stop' (operator-set) | '<Broker> stop order' (broker-reported) | None."""
    if not real_stop:
        return None
    if str(real_stop.get("source") or "") == "operator":
        return "your stop"
    broker = str(real_stop.get("broker") or "broker").strip()
    return f"{broker[:1].upper()}{broker[1:]} stop order" if broker else "broker stop order"


def system_level_name(plan_source: Optional[str]) -> str:
    return SYSTEM_LEVEL_NAMES.get(str(plan_source or ""), "system plan level")


# ── central account tag (comms editor) ──────────────────────────────────────

#: A notice about a position: it says held / position / stop / exit / trim / sell.
_HELD_NOTICE = re.compile(r"(?i)\b(held|holding|position|stop|exit|trim|sell)\b")


def held_account_line(symbols: Iterable[str], body: str, *, holdings: Optional[Mapping[str, Any]] = None,
                      policy: Optional[Mapping[str, Any]] = None) -> Optional[str]:
    """One plain-text line naming the account(s) of every held symbol a held-position notice names.

    None when the notice is not about a position, when no named symbol is held, or when the body
    already names every holding account (the material-change page tags inline).
    """
    pol = policy or load_policy()
    if not pol.get("comms_editor_account_tag", True):
        return None
    plain = re.sub(r"<[^>]+>", " ", body or "")
    if not _HELD_NOTICE.search(plain):
        return None
    bits: list[str] = []
    seen: set[str] = set()
    for sym in symbols or []:
        s = str(sym or "").upper()
        if not s or s in seen:
            continue
        seen.add(s)
        pos = positions_for(s, holdings, pol)
        if not pos:
            continue
        if all(p["account_label"] in plain for p in pos):
            continue
        bits.append(f"{s}: {accounts_text(pos)}")
    if not bits:
        return None
    return "📁 Held in " + " · ".join(bits)


# ── regression scan ─────────────────────────────────────────────────────────


def scan(holdings: Optional[Mapping[str, Any]] = None, policy: Optional[Mapping[str, Any]] = None) -> list[dict]:
    """Every held position tagged tiny or promo (what the new policy keeps out of stop/exit pages)."""
    pol = policy or load_policy()
    doc = holdings if holdings is not None else load_holdings()
    out = []
    for sym in sorted({str(h.get("symbol") or "").upper() for h in doc.get("holdings") or [] if not h.get("is_cash")}):
        for p in positions_for(sym, doc, pol):
            if p["tag"]:
                out.append({"symbol": sym, **p})
    return out


def main(argv: Optional[list[str]] = None) -> int:  # pragma: no cover - operator CLI
    import argparse

    ap = argparse.ArgumentParser(description="List held positions tagged tiny/untracked or promo/reward (read-only).")
    ap.add_argument("--holdings", type=Path, default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    rows = scan(load_holdings(a.holdings) if a.holdings else None)
    if a.json:
        print(json.dumps(rows, indent=2, default=str))
    else:
        for r in rows:
            print(f"{r['symbol']:<10} {r['account_label']:<24} {shares_text(r['shares']):>10} sh  "
                  f"${(r['market_value'] or 0):>9,.2f}  cost {r['cost_basis']}  {r['tag']}  "
                  f"stop/exit pages: {'yes' if r['stop_exit_alerts'] else 'no'}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
