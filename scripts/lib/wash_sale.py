"""Wash-sale windows — the ONE implementation (EXCEPTIONS_MATRIX R9, conflict-resolution-20261024).

Before 2026-10-25 four places disagreed: the re-entry desk (30 d after ANY taxable sell), decision_integrity
(30 d, loss-only, env-tunable), the CIO prospect lifecycle (30 d from the exit timestamp, any account, strict
``<``) and the rotation round-trip ledger (31 d from the ingest DETECTION time, gains included). Every caller
now takes its constants and date arithmetic from here.

The rule (IRC §1091; Rev. Rul. 2008-5 for IRAs):
  * Only a sale at a LOSS in a TAXABLE account opens a wash window. An IRA/Roth sale has no deductible loss.
  * The window is calendar days: an acquisition of the same security from ``sale - 30`` through ``sale + 30``
    (both inclusive, the 61-day window) washes the loss — purchases in the 30 days BEFORE the sale count too
    (``replacement_purchases``; the lots the sale itself disposed of do not). Going forward a sale on day S gates
    buys through S+30 inclusive; the first clear day is S+31.
  * The gate applies to buys in ALL accounts, IRAs included (an IRA repurchase disallows the loss permanently).
  * Stances are per symbol; the gate is per account and every account is gated.
  * A taxable sale whose gain cannot be computed is UNVERIFIED — treated as an unknown gate, never as clear.
  * A taxable sale at a GAIN opens no wash window. The re-entry desk's own 30-day "house hold" after any taxable
    sell is a separate house policy (``house_hold_until``), never labelled a wash sale.

Pure: no I/O except the optional account registry read (config/account_display_names.json). Stdlib-only imports
(a dispatched lane importing this must not reach the quote provider or broker transport, AGENTS §23.14).
MBI_BEHAVIOR = 0 — nothing here orders, sizes, stops or calls a broker.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Optional
from zoneinfo import ZoneInfo

SCHEMA = "WashWindow@v1"
#: IRC §1091: 30 calendar days before or after the loss sale. Statutory, not a tunable.
WASH_DAYS = 30
NY = ZoneInfo("America/New_York")

KIND_NONE = "NONE"
KIND_HOUSE_HOLD_GAIN = "HOUSE_HOLD_NO_LOSS"      # taxable sell at a GAIN: house hold only
KIND_WASH_RISK = "WASH_SALE_RISK_LOSS"           # taxable sell at a LOSS inside the window
KIND_UNVERIFIED = "UNVERIFIED"                   # a taxable sell exists, gain unknown

#: Transaction actions that dispose of shares (the re-entry desk's set, now shared).
SALE_ACTIONS = frozenset({"sell", "sold", "assigned", "assignment", "expired", "exercise", "exercised", "close",
                          "closed"})
_NON_TAXABLE_TYPES = frozenset({"rollover_ira", "roth_ira", "ira", "traditional_ira", "sep_ira", "hsa", "paper"})


def _f(value: Any) -> Optional[float]:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def as_date(value: Any) -> Optional[date]:
    """A trade date. Datetimes are read in America/New_York (the trade date); naive datetimes are UTC."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        at = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return at.astimezone(NY).date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


#: Opening a short / writing an option is not a disposal of owned shares; closing one is not an acquisition.
_SHORT_OPEN = ("sell short", "short sale", "sell to open", "sold short")
_SHORT_CLOSE = ("buy to cover", "buy to close")


def is_sale(action: Any) -> bool:
    act = str(action or "").strip().lower()
    if any(act.startswith(k) for k in _SHORT_OPEN):
        return False
    return act in SALE_ACTIONS or act.startswith("sell")


def is_acquisition(action: Any) -> bool:
    """A purchase of shares: buys and dividend reinvestments (a DRIP purchase is an acquisition for §1091)."""
    act = str(action or "").strip().lower()
    if any(act.startswith(k) for k in _SHORT_CLOSE):
        return False
    return act.startswith("buy") or "reinvest" in act


def today_ny(now: Any = None) -> date:
    """The New York calendar date (never the UTC date: evenings ET are already 'tomorrow' in UTC)."""
    return as_date(now or datetime.now(timezone.utc))


FIFO_NOTE = "FIFO_FROM_TRADE_TRANSACTIONS — verify with your tax context"
SCOPE_NOTE = "same symbol only; substantially identical securities (other share classes, options) are not checked"


def account_taxable(account: Any) -> bool:
    """True when a sale in ``account`` can realize a deductible loss.

    The account registry type (config/account_display_names.json) decides; an account the registry does not type
    falls back to the name test the re-entry desk used (not paper / roth / ira), so an unknown account is treated as
    taxable — the conservative side for a gate.
    """
    raw = str(account or "")
    try:
        try:
            from scripts.lib.account_display import location_facts
        except ImportError:  # scripts/ (not the repo root) on sys.path
            from lib.account_display import location_facts  # type: ignore
        kind = str(location_facts({"account": raw}).get("account_type") or "unknown").lower()
    except Exception:  # noqa: BLE001 -- registry unreadable: fall back to the name test
        kind = "unknown"
    if kind == "taxable":
        return True
    if kind in _NON_TAXABLE_TYPES:
        return False
    low = raw.lower()
    return not any(k in low for k in ("paper", "roth", "ira"))


def window_until(sale: Any, *, days: int = WASH_DAYS) -> Optional[date]:
    """Last calendar day inside the window that a sale on ``sale`` opens (inclusive)."""
    d = as_date(sale)
    return d + timedelta(days=days) if d else None


def window_open(sale: Any, today: Any, *, days: int = WASH_DAYS) -> bool:
    """A buy on ``today`` falls inside the forward window of a sale on ``sale`` (sale ≤ today ≤ sale + days)."""
    d, t = as_date(sale), as_date(today)
    return bool(d and t and d <= t <= d + timedelta(days=days))


def days_left(sale: Any, today: Any, *, days: int = WASH_DAYS) -> int:
    """Calendar days still gated, today included (0 when clear)."""
    until, t = window_until(sale, days=days), as_date(today)
    if not until or not t or not window_open(sale, today, days=days):
        return 0
    return (until - t).days + 1


def classify(*, last_taxable_sell_date: Any, realized_gain: Optional[float], evidence: str = "",
             acquisitions_within_30d: Iterable[Mapping[str, Any]] = (), today: Optional[date] = None,
             hold_days: int = WASH_DAYS, sold_quantity: Optional[float] = None,
             replacements: Optional[Iterable[Mapping[str, Any]]] = None) -> dict[str, Any]:
    """Label one taxable sell honestly (the former decision_integrity.classify_wash body).

    * no sell, or the sell is outside its window → NONE
    * GAIN → HOUSE_HOLD_NO_LOSS: the house re-entry hold (``hold_days``) applies; the wash-sale rule does not
    * LOSS → WASH_SALE_RISK_LOSS through sale + WASH_DAYS (statutory, independent of the house hold)
    * gain unknown → UNVERIFIED through sale + WASH_DAYS (conservative; no legal conclusion)

    When ``replacements`` (from ``replacement_purchases``) and ``sold_quantity`` are given for a LOSS, the shares
    already bought back are matched oldest first: ``wash_status`` LIKELY_WASHED (matched quantity), IRA_PERMANENT
    when part of the match is in a non-taxable account (that part of the loss is lost for good), else OPEN_RISK.
    The forward gate (kind WASH_SALE_RISK_LOSS through sale + 30) is kept either way.
    """
    today = as_date(today) or today_ny()
    sell = as_date(last_taxable_sell_date)
    if sell is None:
        return {"kind": KIND_NONE, "hold_until": None, "realized_gain": None,
                "label": "no taxable sell in window", "legal_conclusion": None}
    days = hold_days if (realized_gain is not None and realized_gain >= 0) else WASH_DAYS
    hold_until = (sell + timedelta(days=days)).isoformat()
    if sell + timedelta(days=days) < today:
        return {"kind": KIND_NONE, "hold_until": hold_until, "realized_gain": realized_gain,
                "label": "taxable sell outside the hold window", "legal_conclusion": None}
    acq = [dict(a) for a in acquisitions_within_30d if a]
    base = {"hold_until": hold_until, "sell_date": sell.isoformat(), "realized_gain": realized_gain,
            "evidence": evidence or None, "acquisitions_within_30d": acq,
            "evidence_note": FIFO_NOTE if evidence == "FIFO_FROM_TRADE_TRANSACTIONS" else None,
            "scope": SCOPE_NOTE}
    basis_note = f" Basis: {FIFO_NOTE}." if evidence == "FIFO_FROM_TRADE_TRANSACTIONS" else ""
    if realized_gain is None:
        return {**base, "kind": KIND_UNVERIFIED,
                "label": f"taxable sell {sell.isoformat()}; lot basis not on file — "
                         f"house hold to {hold_until}; wash-sale status UNVERIFIED ({SCOPE_NOTE}). "
                         "Verify with your tax advisor.",
                "legal_conclusion": None}
    if realized_gain >= 0:
        return {**base, "kind": KIND_HOUSE_HOLD_GAIN,
                "label": f"house {days}-day re-entry hold to {hold_until} after a taxable sell at a "
                         f"GAIN (+${realized_gain:,.2f}); no wash-sale rule applies to a gain.{basis_note}",
                "legal_conclusion": "NOT_A_WASH_SALE"}
    match = match_replacements(sold_quantity, replacements) if replacements is not None else None
    if match and match["matched_quantity"] > 0:
        ira = match["ira_permanent_quantity"]
        label = (f"Taxable loss sale on {sell.isoformat()} (a loss of ${-realized_gain:,.2f}): "
                 f"{match['matched_quantity']:g} of the "
                 f"{sold_quantity:g} shares sold were already bought back within 30 days before or after the sale, so "
                 f"that part of the loss is likely disallowed (added to the new shares' cost basis)"
                 + (f"; {ira:g} of them were bought in an IRA, where the disallowed loss is lost permanently" if ira else "")
                 + f". Buying more in any account (IRA included) through {hold_until} would wash more of it "
                 f"({SCOPE_NOTE}).{basis_note} Verify with your tax advisor.")
        return {**base, **match, "kind": KIND_WASH_RISK, "wash_status": "IRA_PERMANENT" if ira else "LIKELY_WASHED",
                "label": label, "legal_conclusion": "WASH_SALE_RISK"}
    return {**base, **(match or {}), "kind": KIND_WASH_RISK, "wash_status": "OPEN_RISK",
            "label": f"taxable LOSS sale {sell.isoformat()} (${realized_gain:,.2f}); a repurchase "
                     f"through {hold_until} in any account (IRA included) risks permanent disallowance"
                     + (f"; {len(acq)} acquisition(s) already inside the window" if acq else "")
                     + f" ({SCOPE_NOTE}).{basis_note} Verify with your tax advisor.",
            "legal_conclusion": "WASH_SALE_RISK"}


def match_replacements(sold_quantity: Optional[float], replacements: Optional[Iterable[Mapping[str, Any]]]) -> dict:
    """Match replacement purchases to the shares sold, oldest first, capped at the sold quantity."""
    remaining = float(sold_quantity or 0.0)
    matched = ira = 0.0
    used = []
    for r in sorted((dict(x) for x in replacements or []), key=lambda r: str(r.get("trade_date") or "")):
        if remaining <= 1e-9:
            break
        take = min(remaining, float(r.get("quantity") or 0.0))
        if take <= 0:
            continue
        remaining -= take
        matched += take
        taxable = account_taxable(r.get("account"))
        if not taxable:
            ira += take
        used.append({**r, "matched_quantity": round(take, 6), "permanent": not taxable})
    return {"matched_quantity": round(matched, 6), "ira_permanent_quantity": round(ira, 6),
            "matched_replacements": used}


def fifo_realized_gain(transactions: Iterable[Mapping[str, Any]], *, sell_date: Any = None) -> dict[str, Any]:
    """FIFO realized gain for the LAST sell (or the sell on ``sell_date``) in one
    account/symbol series of trade_transactions rows.

    Rows: trade_date, action (Buy/Sell…), quantity, price, amount (signed),
    fees. Deterministic; abstains (``evidence="INSUFFICIENT_LOTS"``) when the
    sold quantity exceeds the lots the rows can account for.
    """
    rows = sorted(
        (dict(r) for r in transactions if r),
        key=lambda r: (str(r.get("trade_date") or ""), str(r.get("trade_time") or "")),
    )
    lots: list[list[float]] = []          # [qty, price]
    last: Optional[dict[str, Any]] = None
    for r in rows:
        act = str(r.get("action") or "").lower()
        qty = _f(r.get("quantity")) or 0.0
        px = _f(r.get("price"))
        if is_acquisition(act) and qty > 0 and px is not None:
            lots.append([qty, px])
            continue
        if not ((act.startswith("sell") and is_sale(act)) or act in ("sold",)) or qty <= 0 or px is None:
            continue
        if sell_date is not None and str(r.get("trade_date") or "")[:10] != str(sell_date)[:10]:
            # consume lots for earlier sells so later ones see the right basis
            remaining = qty
            while remaining > 1e-9 and lots:
                take = min(remaining, lots[0][0])
                lots[0][0] -= take
                remaining -= take
                if lots[0][0] <= 1e-9:
                    lots.pop(0)
            continue
        remaining = qty
        basis = 0.0
        matched = 0.0
        while remaining > 1e-9 and lots:
            take = min(remaining, lots[0][0])
            basis += take * lots[0][1]
            lots[0][0] -= take
            remaining -= take
            matched += take
            if lots[0][0] <= 1e-9:
                lots.pop(0)
        proceeds = qty * px - (_f(r.get("fees")) or 0.0)
        last = {
            "trade_date": str(r.get("trade_date") or "")[:10],
            "quantity": qty,
            "price": px,
            "proceeds": round(proceeds, 2),
            "matched_quantity": round(matched, 4),
            "basis": round(basis, 2),
            "realized_gain": round(proceeds - basis, 2) if remaining <= 1e-9 else None,
            "evidence": "FIFO_FROM_TRADE_TRANSACTIONS" if remaining <= 1e-9 else "INSUFFICIENT_LOTS",
            "unmatched_quantity": round(remaining, 4),
        }
        if sell_date is not None:
            break
    return last or {"evidence": "NO_SELL", "realized_gain": None}


def _row_date(row: Mapping[str, Any]) -> Optional[date]:
    return as_date(row.get("trade_date"))


def replacement_purchases(rows: list[Mapping[str, Any]], sale_row: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Purchases that wash a loss sale: the full 61-day window, ``sale - 30`` through ``sale + 30`` (IRC §1091).

    ``rows`` are every account's rows for the security, sorted by (trade_date, trade_time); ``sale_row`` is one of
    them. In the sale's own account, shares bought before the sale count only while they are still held after it
    (FIFO): the lots the sale itself disposed of are not replacements. Buys after the sale (same account, same day
    included when later in the sort) and buys in any OTHER account (IRAs included) inside the window count in full.
    """
    sale_d = _row_date(sale_row)
    if sale_d is None:
        return []
    lo, hi = sale_d - timedelta(days=WASH_DAYS), sale_d + timedelta(days=WASH_DAYS)
    account = str(sale_row.get("account") or "")
    out: list[dict[str, Any]] = []
    lots: list[list[Any]] = []            # [qty, date] in the sale account, FIFO
    after = False
    for r in rows:
        d = _row_date(r)
        same = str(r.get("account") or "") == account
        if r is sale_row:
            qty = _f(r.get("quantity")) or 0.0
            while qty > 1e-9 and lots:
                take = min(qty, lots[0][0])
                lots[0][0] -= take
                qty -= take
                if lots[0][0] <= 1e-9:
                    lots.pop(0)
            for q, ld in lots:
                if ld and lo <= ld <= sale_d and q > 1e-9:
                    out.append({"account": account, "trade_date": ld.isoformat(), "quantity": round(q, 6),
                                "when": "before_sale"})
            after = True
            continue
        if same and not after:
            qty = _f(r.get("quantity")) or 0.0
            if is_acquisition(r.get("action")) and qty > 0:
                lots.append([qty, d])
            elif is_sale(r.get("action")) and qty > 0:
                while qty > 1e-9 and lots:
                    take = min(qty, lots[0][0])
                    lots[0][0] -= take
                    qty -= take
                    if lots[0][0] <= 1e-9:
                        lots.pop(0)
            continue
        if not is_acquisition(r.get("action")) or d is None or not lo <= d <= hi:
            continue
        # Same account after the sale, or any other account inside the window.
        when = "after_sale" if same or d > sale_d else "before_sale" if d < sale_d else "same_day"
        out.append({"account": str(r.get("account") or ""), "trade_date": d.isoformat(),
                    "quantity": _f(r.get("quantity")), "when": when})
    return out


def symbol_window(transactions: Iterable[Mapping[str, Any]], *, today: Any) -> dict[str, Any]:
    """The canonical wash window for ONE security from its trade_transactions rows (every account).

    Every taxable sale inside the window is classified with FIFO basis computed per account (lots never pool
    across accounts). Precedence: any LOSS → WASH_SALE_RISK_LOSS (until = latest loss sale + 30); else any unknown
    gain → UNVERIFIED; else GAIN → HOUSE_HOLD_NO_LOSS; no taxable sale inside the window → NONE.
    ``house_hold_until`` is the desk's house hold (latest taxable sell + 30, gain or loss) for callers that keep it.
    """
    today_d = as_date(today) or today_ny()
    rows = sorted((dict(r) for r in transactions if r), key=lambda r: (str(r.get("trade_date") or ""),
                                                                       str(r.get("trade_time") or "")))
    by_account: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_account.setdefault(str(r.get("account") or ""), []).append(r)
    sales = []
    for account, txs in by_account.items():
        if not account_taxable(account):
            continue
        for r in txs:
            d = _row_date(r)
            if d is None or not is_sale(r.get("action")) or not window_open(d, today_d):
                continue
            gain = fifo_realized_gain(txs, sell_date=d.isoformat())
            sales.append({"account": account, "sale_date": d, "realized_gain": gain.get("realized_gain"),
                          "evidence": gain.get("evidence"), "quantity": _f(r.get("quantity")),
                          "price": _f(r.get("price")), "_row": r})
    if not sales:
        return {"schema": SCHEMA, "kind": KIND_NONE, "gated": False, "until": None, "house_hold_until": None,
                "sales": [], "acquisitions_within_30d": [], "label": "no taxable sell in window"}
    losses = [s for s in sales if s["realized_gain"] is not None and s["realized_gain"] < 0]
    unknown = [s for s in sales if s["realized_gain"] is None]
    pick = max(losses or unknown or sales, key=lambda s: s["sale_date"])
    lo, hi = pick["sale_date"] - timedelta(days=WASH_DAYS), pick["sale_date"] + timedelta(days=WASH_DAYS)
    acq = [{"trade_date": d.isoformat(), "account": r.get("account"), "quantity": _f(r.get("quantity")),
            "price": _f(r.get("price"))}
           for r in rows if is_acquisition(r.get("action")) and (d := _row_date(r)) and lo <= d <= hi]
    # The 61-day rule: purchases in the 30 days BEFORE the loss sale wash it as well as purchases after it.
    replacements = replacement_purchases(rows, pick["_row"]) if pick in losses or pick in unknown else []
    out = classify(last_taxable_sell_date=pick["sale_date"], realized_gain=pick["realized_gain"],
                   evidence=str(pick["evidence"] or ""), acquisitions_within_30d=acq, today=today_d,
                   sold_quantity=pick["quantity"], replacements=replacements if pick in losses else None)
    latest = max(s["sale_date"] for s in sales)
    washed = out["kind"] == KIND_WASH_RISK and out.get("wash_status") in ("LIKELY_WASHED", "IRA_PERMANENT")
    # The forward gate lasts until the LAST loss or unknown-basis taxable sale's window closes.
    gate_until = max((window_until(s["sale_date"]) for s in losses + unknown), default=None)
    gated = out["kind"] in (KIND_WASH_RISK, KIND_UNVERIFIED)
    if gated and gate_until and gate_until.isoformat() > str(out.get("hold_until")):
        out["label"] += f" Another taxable sale keeps the buy window open through {gate_until.isoformat()}."
    return {"schema": SCHEMA, **out, "gated": gated,
            "until": gate_until.isoformat() if gated and gate_until else None,
            "house_hold_until": window_until(latest).isoformat(), "account": pick["account"],
            "replacements": replacements, "loss_washed": washed,
            "sales": [{k: v for k, v in {**s, "sale_date": s["sale_date"].isoformat()}.items() if k != "_row"}
                      for s in sales]}


def windows_from_transactions(transactions: Iterable[Mapping[str, Any]], *, today: Any) -> dict[str, dict[str, Any]]:
    """{SYMBOL: symbol_window} for every symbol with a taxable sale inside its window."""
    by_symbol: dict[str, list[Mapping[str, Any]]] = {}
    for r in transactions:
        sym = str((r or {}).get("symbol") or "").strip().upper()
        if sym:
            by_symbol.setdefault(sym, []).append(r)
    out = {}
    for sym, rows in by_symbol.items():
        window = symbol_window(rows, today=today)
        if window["kind"] != KIND_NONE:
            out[sym] = window
    return out


#: The resolver's R9 input values (config/conflict_rulebook.json gate_known vocabulary).
RESOLVER_VALUE = {KIND_WASH_RISK: "BLOCKED", KIND_UNVERIFIED: "UNKNOWN", KIND_HOUSE_HOLD_GAIN: "CLEAR",
                  KIND_NONE: "CLEAR"}
