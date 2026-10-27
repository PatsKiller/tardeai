"""My history — the operator's own position history in one ticker, for the prospectus (block ``my_history``).

Operator 2026-10-26: "It's showing that I hold this. What is my average cost? Have I won or lost, P&L? What were the
catalysts that hit? ... If I owned it multiple round trips, should that be analyzed? This is a customized prospectus
for me, not for the public."

Built for holdings AND for anything ever traded, from house stores only (read-only, no broker call):

* **Open lots by account NAME** — shares, average cost, unrealized $/% from the position store
  (``lib.portfolio_positions``, the one accessor; marked at the same quote as the Position tile). Lot dates, holding
  period and short/long term come from a FIFO over ``trade_transactions`` buys and sells (``wash_sale``'s action
  vocabulary); when that FIFO does not reconcile with the position store's shares (transfers, pre-journal lots) the
  dating says so instead of guessing.
* **Round trips** — exactly the Rec Intelligence "Purchased → Sold Lifecycle" rows
  (``recommendation_intelligence_engine.lifecycle_performance``: ``trade_closed`` + discovery origin from
  ``rec_ticker_attribution`` + the matched ``journal_trade_reviews`` review), filtered to this symbol. Totals: lifetime
  realized P/L, wins / losses, average win and loss, best and worst trip.
* **Why you got in** — the Rec Intelligence origin plus every discovery source recorded before the entry date, and
  the earliest recorded rationale as the thesis at entry.
* **What happened while held** — typed ``catalyst_events`` (earnings flagged), days with |move| ≥ the cadence
  trigger (8%), and filled stops (``stop_last_known``) inside each holding window, each with the next-session and
  5-session price reaction from house closes.
* **Lessons** — deterministic statistics across trips (win rate, payoff, entry position in the 52-week range vs
  outcome, hold length vs outcome, stop-out frequency, re-entries after a loss) plus the journal's lessons. The writer
  may interpret them; every number is a cited fact.
* **Tax flags** — taxable vs tax-advantaged by account (``wash_sale.account_taxable``) and, for a loss sale in a taxable
  account, the canonical 61-day wash-sale test (``wash_sale.replacement_purchases``), plus the open window today
  (``wash_sale.symbol_window``). Verify with your tax context.

Every number is added to the bundle as a fact (``kind="my_history"``) and the block rows carry their fact ids.
Account numbers never appear: accounts are shown through ``account_display.account_label``.
READ_ONLY_ADVISORY (MBI_BEHAVIOR=0): nothing here sizes, orders, stops or weights.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import statistics
from typing import Any, Callable, Iterable, Optional

SCHEMA = "MyHistory@v1"
LONG_TERM_DAYS = 365          # IRS: held more than one year → long-term
BIG_MOVE_PCT = 8.0            # same threshold as the holdings cadence trigger (config cadence.triggers.day_move_abs_pct)
STOP_EXITS = {"hard_stop", "trailing_stop", "stop", "stop_loss", "stopped_out"}
MAX_EVENTS_PER_WINDOW = 4
MAX_FACTS = 140
_LOSS_REENTRY_DAYS = 30
TRANSFER_ACTIONS = ("transfer", "journal")  # direction is not recorded on these rows; never used for lot dating


def _f(v: Any) -> Optional[float]:
    try:
        out = float(v)
    except (TypeError, ValueError):
        return None
    return out if out == out and abs(out) != float("inf") else None


def _d(v: Any) -> Optional[date]:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _plib(name: str):
    import importlib
    try:
        return importlib.import_module(f"lib.{name}")
    except ImportError:
        return importlib.import_module(f"scripts.lib.{name}")


def _wash():
    return _plib("wash_sale")


def account_name(raw: Any) -> str:
    try:
        return _plib("account_display").account_label(raw)
    except Exception:  # noqa: BLE001 - never fall back to the raw key (it may be a number)
        return "Account"


def taxable(raw: Any) -> bool:
    return bool(_wash().account_taxable(raw))


# ── readers ───────────────────────────────────────────────────────────────────────────────────────────────────────
class _Cursor:
    """psycopg-style cursor over the house ``db_query`` callable, so the Rec Intelligence functions run unchanged."""

    def __init__(self, query: Callable):
        self._q, self._rows = query, []

    def execute(self, sql: str, params: Any = None) -> None:
        rows = self._q(sql, params, fetch="all") or []
        self._rows = [tuple(r.values()) if isinstance(r, dict) or hasattr(r, "values") else tuple(r) for r in rows]

    def fetchall(self) -> list[tuple]:
        return list(self._rows)


class HouseHistoryReader:
    """Production reads for one symbol. Every method returns plain rows; the caller records failures as gaps."""

    def __init__(self, sources: Any):
        self.sources = sources
        self.q = sources.db()

    def position_rows(self, sym: str, holding: dict | None) -> list[dict]:
        pp = _plib("portfolio_positions")
        doc = pp.load_store()
        mark_quote = (holding or {}).get("mark") if isinstance((holding or {}).get("mark"), dict) else None
        out = []
        for r in doc.get("holdings") or []:
            if str(r.get("symbol") or "").upper() != sym or pp.is_cash(r):
                continue
            qty = _f(r.get("shares", r.get("quantity")))
            if not qty or qty <= 0:
                continue
            mark = pp.resolve_mark(r, quote=mark_quote if mark_quote and mark_quote.get("price") else None)
            vp = pp.value_and_pl(r, mark)
            out.append({"account": r.get("account") or r.get("account_id"), "shares": qty,
                        "avg_cost": pp.per_share_cost(r), "cost_basis": vp.get("cost_basis"),
                        "market_value": vp.get("market_value"),
                        # value_and_pl names it gain_loss (reading "unrealized_pl" left every open lot without P/L)
                        "unrealized_pl": vp.get("gain_loss", vp.get("unrealized_pl")),
                        "as_of": doc.get("as_of") or doc.get("data_as_of"), "mark": mark.get("price")})
        return out

    def transactions(self, sym: str) -> list[dict]:
        rows = self.q("SELECT trade_date, trade_time, action, quantity, price, amount, fees, account FROM trade_transactions "
                      "WHERE upper(symbol) = %s ORDER BY trade_date, trade_time NULLS FIRST, id", (sym,), fetch="all") or []
        return [dict(r) for r in rows]

    def trips(self, sym: str) -> list[dict]:
        try:
            import recommendation_intelligence_engine as rie  # type: ignore
        except ImportError:
            from scripts import recommendation_intelligence_engine as rie  # type: ignore
        return rie.lifecycle_performance(_Cursor(self.q), limit=500, symbol=sym)

    def attributions(self, sym: str) -> list[dict]:
        rows = self.q("SELECT source_type, first_seen_at, rationale FROM rec_ticker_attribution WHERE upper(symbol) = %s "
                      "AND source_type NOT IN ('execution', 'holding', 'rotation') ORDER BY first_seen_at LIMIT 200",
                      (sym,), fetch="all") or []
        return [dict(r) for r in rows]

    def events(self, sym: str, start: date, end: date) -> list[dict]:
        rows = self.q("SELECT catalyst_type, headline, severity, impact_score, source, COALESCE(published_at, created_at) AS at "
                      "FROM catalyst_events WHERE upper(symbol) = %s AND catalyst_type <> 'other' "
                      "AND COALESCE(published_at, created_at) >= %s AND COALESCE(published_at, created_at) < %s "
                      "ORDER BY impact_score DESC NULLS LAST, COALESCE(published_at, created_at) LIMIT 40",
                      (sym, start, end + timedelta(days=1)), fetch="all") or []
        return [dict(r) for r in rows]

    def stop_fills(self, sym: str) -> list[dict]:
        rows = self.q("SELECT account, stop_price, status, captured_at, order_type FROM stop_last_known "
                      "WHERE upper(symbol) = %s AND lower(status) = 'filled' ORDER BY captured_at", (sym,), fetch="all") or []
        return [dict(r) for r in rows]

    def bars(self, sym: str, days: int = 1100) -> list[dict]:
        return self.sources.bars(sym, days=days) or []


def reader_for(sources: Any) -> Any:
    """The production reader only for the production sources; tests pass their own via ``history_reader()``."""
    custom = getattr(sources, "history_reader", None)
    if callable(custom):
        return custom()
    try:
        from .inputs import HouseSources
    except ImportError:  # pragma: no cover
        return None
    return HouseHistoryReader(sources) if isinstance(sources, HouseSources) else None


# ── pure computation ──────────────────────────────────────────────────────────────────────────────────────────────
def fifo_open_lots(transactions: Iterable[dict]) -> dict[str, dict]:
    """{raw account: {lots: [[qty, date, price]], transfers: n}} after FIFO over buys/sells (per account)."""
    ws = _wash()
    out: dict[str, dict] = {}
    rows = sorted((dict(r) for r in transactions if r), key=lambda r: (str(r.get("trade_date") or ""), str(r.get("trade_time") or "")))
    for r in rows:
        acct = str(r.get("account") or "")
        st = out.setdefault(acct, {"lots": [], "transfers": 0, "oversold": 0.0})
        act = str(r.get("action") or "").strip().lower()
        qty = _f(r.get("quantity")) or 0.0
        if qty <= 0:
            continue
        if ws.is_acquisition(act):
            st["lots"].append([qty, _d(r.get("trade_date")), _f(r.get("price"))])
        elif ws.is_sale(act):
            remaining = qty
            while remaining > 1e-9 and st["lots"]:
                take = min(remaining, st["lots"][0][0])
                st["lots"][0][0] -= take
                remaining -= take
                if st["lots"][0][0] <= 1e-9:
                    st["lots"].pop(0)
            st["oversold"] += remaining
        elif any(k in act for k in TRANSFER_ACTIONS):
            st["transfers"] += 1
    return out


def _money(v: Any) -> str:
    return "n/a" if _f(v) is None else f"${_f(v):,.2f}"


def _n(v: Any) -> str:
    x = _f(v)
    if x is None:
        return "n/a"
    return f"{int(x):,}" if x.is_integer() else f"{x:,.4g}"


def _term(days: Optional[int]) -> Optional[str]:
    if days is None:
        return None
    return "long" if days > LONG_TERM_DAYS else "short"


def _closes(bars: Iterable[Any]) -> list[tuple[date, float]]:
    out = []
    for b in bars or []:
        d = _d(b.get("price_date") if isinstance(b, dict) else b[0])
        c = _f(b.get("close") if isinstance(b, dict) else b[1])
        if d and c and c > 0 and _is_session(d):
            out.append((d, c))
    out.sort()
    return out


def _is_session(d: date) -> bool:
    try:
        from .blocks import is_session
    except ImportError:  # loaded outside the package (tests import the module directly)
        return d.weekday() < 5
    return is_session(d)


def _idx_on_or_after(s: list[tuple[date, float]], d: date) -> Optional[int]:
    for i, (day, _) in enumerate(s):
        if day >= d:
            return i
    return None


def reaction(s: list[tuple[date, float]], d: date) -> dict:
    """Event on day d: day-of = first session on/after d vs the close before; 5-session = 5 sessions on vs that base."""
    i = _idx_on_or_after(s, d)
    if i is None or i == 0:
        return {"next_day_pct": None, "five_day_pct": None}
    base = s[i - 1][1]
    nd = round((s[i][1] / base - 1) * 100, 2)
    fd = round((s[i + 4][1] / base - 1) * 100, 2) if i + 4 < len(s) else None
    return {"next_day_pct": nd, "five_day_pct": fd}


def big_moves(s: list[tuple[date, float]], start: date, end: date, threshold: float) -> list[dict]:
    out = []
    for i in range(1, len(s)):
        d, c = s[i]
        if d < start or d > end:
            continue
        move = (c / s[i - 1][1] - 1) * 100
        if abs(move) >= threshold:
            nxt = round((s[i + 1][1] / c - 1) * 100, 2) if i + 1 < len(s) else None
            five = round((s[i + 5][1] / c - 1) * 100, 2) if i + 5 < len(s) else None
            out.append({"date": d.isoformat(), "kind": "big_move", "move_pct": round(move, 2), "next_day_pct": nxt,
                        "five_day_pct": five})
    out.sort(key=lambda r: -abs(r["move_pct"]))
    return out


def range_position(s: list[tuple[date, float]], d: date, price: Optional[float]) -> Optional[float]:
    """Entry price as % of the trailing 52-week (252-session) low→high range, from house closes before the entry."""
    if price is None:
        return None
    prior = [c for day, c in s if day < d][-252:]
    if len(prior) < 120:
        return None
    lo, hi = min(prior), max(prior)
    if hi <= lo:
        return None
    return round((price - lo) / (hi - lo) * 100, 1)


def _mean(vals: list[float]) -> Optional[float]:
    vals = [v for v in vals if v is not None]
    return round(statistics.fmean(vals), 2) if vals else None


# ── the block ─────────────────────────────────────────────────────────────────────────────────────────────────────
class _Facts:
    """Adds facts to the bundle up to a cap; returns the id (or None when capped / empty)."""

    def __init__(self, bundle: Any, cap: int):
        self.b, self.cap, self.n, self.capped = bundle, cap, 0, False

    def add(self, label: str, *, value: Any = None, text: str | None = None, unit: str = "", source: str,
            as_of: Any = None) -> Optional[str]:
        if self.n >= self.cap:
            self.capped = True
            return None
        fid = self.b.add("my_history", label, value=value, text=text, unit=unit, source=source, as_of=as_of)
        if fid:
            self.n += 1
        return fid


SRC_POS = "position store (lib.portfolio_positions)"
SRC_TRIP = "Rec Intelligence lifecycle (trade_closed + rec_ticker_attribution + journal_trade_reviews)"
SRC_TX = "trade_transactions (journal ledger), FIFO"
SRC_PX = "ticker_prices (house closes)"
SRC_CAT = "catalyst_events"
SRC_WASH = "wash_sale (IRC §1091, 61-day window) over trade_transactions"


def build(reader: Any, bundle: Any, *, holding: dict | None, now: datetime, last_close: Optional[float] = None,
          cfg: dict | None = None) -> dict:
    """Assemble the my_history block for ``bundle.symbol`` and add its facts. Never raises on a missing store."""
    cfg = cfg or {}
    sym = bundle.symbol
    today = now.date() if isinstance(now, datetime) else now
    threshold = float(cfg.get("big_move_pct", BIG_MOVE_PCT))
    facts = _Facts(bundle, int(cfg.get("max_facts", MAX_FACTS)))
    gaps: list[str] = []
    block: dict[str, Any] = {"schema": SCHEMA, "symbol": sym, "as_of": now.isoformat(), "open_lots": [], "trips": [],
                             "current_hold": None, "totals": None, "lessons": {"stats": [], "journal_notes": []},
                             "tax": {"flags": [], "accounts": [], "open_window": None, "note": None},
                             "origin": None, "gaps": gaps,
                             "method": {"trips": "Rec Intelligence Purchased → Sold Lifecycle (reused, symbol-filtered)",
                                        "lots": "position store for shares / cost / P&L; FIFO over trade_transactions for lot dates",
                                        "reactions": "day-of = first session on/after the event vs the prior close; "
                                                     "5-session = fifth session on/after vs the same base (house closes)",
                                        "term": f"long-term when held more than {LONG_TERM_DAYS} days"}}

    def read(name: str, fn: Callable, default: Any):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - recorded, never fatal
            gaps.append(f"{name}: {type(exc).__name__}: {str(exc)[:100]}")
            return default

    positions = read("position store", lambda: reader.position_rows(sym, holding), []) if holding else []
    txs = read("trade_transactions", lambda: reader.transactions(sym), [])
    trips_raw = read("Rec Intelligence lifecycle", lambda: reader.trips(sym), [])
    attrs = read("rec_ticker_attribution", lambda: reader.attributions(sym), [])
    fills = read("stop_last_known", lambda: reader.stop_fills(sym), [])
    txs_for_fills = txs
    first_needed = min([d for d in (_d(t.get("open_date")) for t in trips_raw) if d] + [today])
    days_needed = (today - first_needed).days + 400
    bars = read("price history", lambda: reader.bars(sym, days=max(1100, days_needed)), [])
    s = _closes(bars)
    if s and s[0][0] > first_needed:
        gaps.append(f"house price history starts {s[0][0].isoformat()}; events and reactions before it are not available")
    fills = date_stop_fills(fills, txs_for_fills)
    if not positions and not trips_raw and not txs:
        block["scope"] = "never_traded"
        return block
    block["scope"] = "held" if positions else "previously_traded"
    tax_accounts: dict[str, bool] = {}

    # ── open lots ──
    fifo = fifo_open_lots(txs)
    hold_start: Optional[date] = None
    for p in positions:
        raw = str(p.get("account") or "")
        name = account_name(raw)
        tx_lots = [lot for lot in (fifo.get(raw) or {}).get("lots") or [] if lot[0] > 1e-9]
        fifo_qty = sum(lot[0] for lot in tx_lots)
        reconciled = bool(tx_lots) and abs(fifo_qty - (p.get("shares") or 0)) <= max(0.01, 0.001 * (p.get("shares") or 0))
        is_tax = taxable(raw)
        tax_accounts[name] = is_tax
        lots = []
        for qty, d, px in tx_lots:
            days = (today - d).days if d else None
            lots.append({"acquired": d.isoformat() if d else None, "shares": round(qty, 4), "price": px,
                         "days": days, "term": _term(days)})
        first = min((lot[1] for lot in tx_lots if lot[1]), default=None)
        if first and (hold_start is None or first < hold_start):
            hold_start = first
        days = (today - first).days if first else None
        terms = {lot["term"] for lot in lots if lot["term"]}
        cost = _f(p.get("cost_basis"))
        upl = _f(p.get("unrealized_pl"))
        row = {"account": name, "shares": p.get("shares"), "avg_cost": _f(p.get("avg_cost")),
               "market_value": _f(p.get("market_value")), "unrealized_usd": upl,
               "unrealized_pct": round(upl / cost * 100, 2) if upl is not None and cost else None,
               "acquired_first": first.isoformat() if first else None, "holding_days": days,
               "term": (terms.pop() if len(terms) == 1 else "mixed" if terms else None),
               "tax_character": "taxable" if is_tax else "tax-advantaged",
               "lot_dating": "fifo_reconciled" if reconciled else "unreconciled",
               "lots": lots[:12], "fact_ids": []}
        if not reconciled:
            why = (f"journal FIFO holds {fifo_qty:g} shares vs {p.get('shares'):g} in the position store"
                   + ("; transfers on record (direction not recorded)" if (fifo.get(raw) or {}).get("transfers") else ""))
            row["lot_dating_note"] = why
            gaps.append(f"lot dates for {name}: {why}")
        at = p.get("as_of")
        for key, label, unit, src in (("shares", "shares held", "", SRC_POS), ("avg_cost", "average cost $", "$", SRC_POS),
                                      ("unrealized_usd", "unrealized P/L $", "$", SRC_POS),
                                      ("unrealized_pct", "unrealized P/L %", "%", f"derived: {SRC_POS}"),
                                      ("holding_days", "days held since the first open lot", "", SRC_TX)):
            fid = facts.add(f"My open position ({name}): {label}", value=row[key], unit=unit, source=src, as_of=at)
            if fid:
                row["fact_ids"].append(fid)
        if row["term"]:
            fid = facts.add(f"My open position ({name}): holding term", text=f"{row['term']}-term ({row['tax_character']} account)",
                            source=SRC_TX, as_of=at)
            if fid:
                row["fact_ids"].append(fid)
        block["open_lots"].append(row)

    # ── round trips (Rec Intelligence rows) ──
    trips_sorted = sorted(trips_raw, key=lambda t: (str(t.get("open_date") or ""), str(t.get("close_date") or "")))
    discovery = [(_d(a.get("first_seen_at")), a) for a in attrs if _d(a.get("first_seen_at"))]
    discovery.sort(key=lambda x: x[0])
    origin_first = trips_sorted[0].get("origin") if trips_sorted else None
    tx_sorted = sorted((dict(r) for r in txs), key=lambda r: (str(r.get("trade_date") or ""), str(r.get("trade_time") or "")))
    ws = _wash()
    for n, t in enumerate(trips_sorted, start=1):
        raw = str(t.get("account") or "")
        name = account_name(raw)
        is_tax = taxable(raw)
        tax_accounts.setdefault(name, is_tax)
        od, cd = _d(t.get("open_date")), _d(t.get("close_date"))
        pnl, pct = _f(t.get("pnl")), _f(t.get("pnl_pct"))
        hold = t.get("hold_days") if t.get("hold_days") is not None else ((cd - od).days if od and cd else None)
        before = [a for d, a in discovery if od and d <= od]
        src_types = list(dict.fromkeys(str(a.get("source_type")) for a in before))
        thesis = next((str(a.get("rationale"))[:240] for a in before if a.get("rationale")), None)
        jr = t.get("journal") or {}
        exit_type = jr.get("exit_type")
        trip = {"trip": n, "account": name, "entry_date": od.isoformat() if od else None,
                "entry_price": _f(t.get("buy_price")), "exit_date": cd.isoformat() if cd else None,
                "exit_price": _f(t.get("sell_price")), "shares": _f(t.get("shares")), "hold_days": hold,
                "realized_usd": pnl, "realized_pct": pct, "r_multiple": _f(t.get("r_multiple")),
                "origin": t.get("origin"), "sources_before_entry": src_types, "thesis_at_entry": thesis,
                "setup": t.get("setup"), "journaled": bool(t.get("journaled")),
                "journal": {k: jr.get(k) for k in ("realized_r", "lesson", "setup_family", "exit_type") if jr.get(k) is not None} or None,
                "stopped_out": bool(exit_type and str(exit_type).lower() in STOP_EXITS),
                "term": _term(hold), "tax_character": "taxable" if is_tax else "tax-advantaged",
                "entry_vs_52w_range_pct": range_position(s, od, _f(t.get("buy_price"))) if od else None,
                "wash_sale": None, "while_held": [], "fact_ids": []}
        # wash sale: only a LOSS in a TAXABLE account opens a window (wash_sale rule); 61-day replacement test
        if is_tax and pnl is not None and pnl < 0 and cd:
            sale_row = next((r for r in tx_sorted if str(r.get("account") or "") == raw and ws.is_sale(r.get("action"))
                             and _d(r.get("trade_date")) == cd), None)
            if sale_row is not None:
                reps = ws.replacement_purchases(tx_sorted, sale_row)
                evidence = "trade_transactions sale row"
            else:  # the journal does not cover this sale: test the other trips' entries (any account)
                reps = [{"account": o.get("account"), "trade_date": str(o.get("open_date"))[:10],
                         "quantity": _f(o.get("shares")), "when": "after_sale" if _d(o.get("open_date")) > cd else "before_sale"}
                        for o in trips_sorted if o is not t and _d(o.get("open_date"))
                        and abs((_d(o.get("open_date")) - cd).days) <= ws.WASH_DAYS]
                evidence = "trip entry dates (sale not in trade_transactions)"
            if reps:
                trip["wash_sale"] = {"flag": True, "window": [(cd - timedelta(days=ws.WASH_DAYS)).isoformat(),
                                                            (cd + timedelta(days=ws.WASH_DAYS)).isoformat()],
                                     "replacements": [{"account": account_name(r.get("account")),
                                                       "date": r.get("trade_date"), "shares": r.get("quantity"),
                                                       "when": r.get("when")} for r in reps[:6]],
                                     "evidence": evidence, "note": ws.FIFO_NOTE}
                fid = facts.add(f"Trip {n} tax flag: loss sale {cd.isoformat()} with a repurchase inside the 61-day "
                                f"wash-sale window", text=f"replacement buys on "
                                f"{', '.join(str(r.get('trade_date')) for r in reps[:4])} ({evidence})",
                                source=SRC_WASH, as_of=cd)
                if fid:
                    trip["fact_ids"].append(fid)
                block["tax"]["flags"].append({"trip": n, "kind": "wash_sale", "sale_date": cd.isoformat(),
                                              "replacement_dates": [r.get("trade_date") for r in reps[:6]], "fact": fid})
        # one text fact carries the trip's prices, size and hold (its numbers are citable); P/L are value facts
        parts = [f"bought {trip['entry_date']} at {_money(trip['entry_price'])}", f"sold {trip['exit_date']} at "
                 f"{_money(trip['exit_price'])}", f"{_n(trip['shares'])} shares", f"held {_n(hold)} days"]
        if trip["r_multiple"] is not None:
            parts.append(f"R {_n(trip['r_multiple'])}")
        fid = facts.add(f"Trip {n} ({name}): entry, exit, size and hold", text=", ".join(parts), source=SRC_TRIP, as_of=cd)
        if fid:
            trip["fact_ids"].append(fid)
        for key, label, unit in (("realized_usd", "realized P/L $", "$"), ("realized_pct", "realized P/L %", "%")):
            fid = facts.add(f"Trip {n} ({name}, {trip['entry_date']} → {trip['exit_date']}): {label}", value=trip[key],
                            unit=unit, source=SRC_TRIP, as_of=cd)
            if fid:
                trip["fact_ids"].append(fid)
        why = ", ".join(src_types) or (t.get("origin") or "direct / manual")
        fid = facts.add(f"Trip {n}: why you got in (recorded origin before entry)",
                        text=f"{why}" + (f"; thesis at entry: {thesis}" if thesis else ""), source="rec_ticker_attribution",
                        as_of=od)
        if fid:
            trip["fact_ids"].append(fid)
        if jr.get("lesson"):
            block["lessons"]["journal_notes"].append({"trip": n, "lesson": str(jr["lesson"])[:300]})
            facts.add(f"Trip {n}: journal lesson", text=str(jr["lesson"])[:300], source="journal_trade_reviews", as_of=cd)
        if od and cd:
            trip["while_held"] = _window_events(reader, sym, s, od, cd, threshold, fills, facts, f"Trip {n}", gaps, raw)
        block["trips"].append(trip)

    # ── current holding window ──
    if positions:
        start = hold_start or min((_d(r.get("trade_date")) for r in tx_sorted if ws.is_acquisition(r.get("action"))
                                   and _d(r.get("trade_date"))), default=None)
        if start:
            block["current_hold"] = {"since": start.isoformat(), "days": (today - start).days,
                                     "while_held": _window_events(reader, sym, s, start, today, threshold, fills, facts,
                                                                  "Current holding", gaps, None)}
        else:
            gaps.append("current holding window: no acquisition date in trade_transactions")

    # ── totals ──
    closed = [t for t in block["trips"] if t["realized_usd"] is not None]
    if closed:
        wins = [t for t in closed if t["realized_usd"] > 0]
        losses = [t for t in closed if t["realized_usd"] < 0]
        best = max(closed, key=lambda t: t["realized_usd"])
        worst = min(closed, key=lambda t: t["realized_usd"])
        tot = {"trips": len(block["trips"]), "closed_with_pl": len(closed), "wins": len(wins), "losses": len(losses),
               "win_rate_pct": round(len(wins) / len(closed) * 100, 1),
               "realized_usd": round(sum(t["realized_usd"] for t in closed), 2),
               "avg_win_usd": _mean([t["realized_usd"] for t in wins]), "avg_loss_usd": _mean([t["realized_usd"] for t in losses]),
               "avg_win_pct": _mean([t["realized_pct"] for t in wins]), "avg_loss_pct": _mean([t["realized_pct"] for t in losses]),
               "avg_hold_days": _mean([t["hold_days"] for t in closed if t["hold_days"] is not None]),
               "best": {"trip": best["trip"], "realized_usd": best["realized_usd"], "realized_pct": best["realized_pct"]},
               "worst": {"trip": worst["trip"], "realized_usd": worst["realized_usd"], "realized_pct": worst["realized_pct"]},
               "fact_ids": []}
        for key, label, unit in (("realized_usd", f"Lifetime realized P/L on {sym} $", "$"),
                                 ("trips", "Round trips (count)", ""), ("wins", "Winning round trips (count)", ""),
                                 ("losses", "Losing round trips (count)", ""), ("win_rate_pct", "Round-trip win rate %", "%"),
                                 ("avg_win_usd", "Average winning trip $", "$"), ("avg_loss_usd", "Average losing trip $", "$"),
                                 ("avg_win_pct", "Average winning trip %", "%"), ("avg_loss_pct", "Average losing trip %", "%"),
                                 ("avg_hold_days", "Average days held per round trip", "")):
            fid = facts.add(f"My history: {label}", value=tot[key], unit=unit, source=f"derived: {SRC_TRIP}")
            if fid:
                tot["fact_ids"].append(fid)
        for key in ("best", "worst"):
            r = tot[key]
            fid = facts.add(f"My history: {key} round trip", text=f"trip {r['trip']}: {r['realized_usd']:+,.2f} $"
                            + (f" ({r['realized_pct']:+.2f}%)" if r["realized_pct"] is not None else ""),
                            source=f"derived: {SRC_TRIP}")
            if fid:
                tot["fact_ids"].append(fid)
        block["totals"] = tot
    elif block["trips"]:
        gaps.append("round trips on record carry no P/L (trade_closed pnl empty)")

    # ── sells the round trips do not cover (lots that arrived by transfer / ACATS carry no basis in trade_closed) ──
    sold = round(sum(abs(_f(r.get("quantity")) or 0) for r in txs if str(r.get("action") or "").strip().lower().startswith("sell")), 4)
    tripped = round(sum(t.get("shares") or 0 for t in block["trips"]), 4)
    if sold > 0 and sold - tripped > max(0.01, 0.001 * sold):
        missing = round(sold - tripped, 4)
        block["unmatched_sells"] = {"shares_sold": sold, "shares_in_round_trips": tripped, "shares_without_basis": missing}
        facts.add("My history: shares sold that are NOT in the round trips (no recorded basis)", value=missing,
                  source=f"derived: trade_transactions sells ({sold:g}) − round-trip shares ({tripped:g})")
        gaps.append(f"realized P/L covers {tripped:g} of {sold:g} shares sold; {missing:g} sold shares are not in the round "
                    "trips (no recorded basis, e.g. lots that arrived by transfer) and are not in the totals")

    # ── lessons (deterministic) ──
    block["lessons"]["stats"] = _lessons(block["trips"], facts, sym)

    # ── origin + tax ──
    block["origin"] = {"first_origin": origin_first or (str(discovery[0][1].get("source_type")) if discovery else None),
                       "sources": list(dict.fromkeys(str(a.get("source_type")) for _, a in discovery))[:8]}
    block["tax"]["accounts"] = [{"account": k, "character": "taxable" if v else "tax-advantaged"} for k, v in tax_accounts.items()]
    try:
        win = ws.symbol_window(tx_sorted, today=today)
        if win.get("kind") != ws.KIND_NONE:
            block["tax"]["open_window"] = {"kind": win.get("kind"), "gated": win.get("gated"), "until": win.get("until"),
                                           "label": win.get("label"), "loss_washed": win.get("loss_washed")}
            facts.add("Wash-sale window today", text=f"{win.get('kind')}: {win.get('label')}"
                      + (f" (through {win.get('until')})" if win.get("until") else ""), source=SRC_WASH, as_of=today)
    except Exception as exc:  # noqa: BLE001
        gaps.append(f"wash-sale window: {type(exc).__name__}")
    block["tax"]["note"] = (f"{ws.FIFO_NOTE}; {ws.SCOPE_NOTE}. Only a loss sale in a taxable account opens a wash-sale "
                            "window; a repurchase in an IRA within the window disallows the loss permanently.")
    if facts.capped:
        gaps.append(f"fact cap reached ({facts.cap}); later rows are shown without citations")
    return block


def _window_events(reader: Any, sym: str, s: list, start: date, end: date, threshold: float, fills: list,
                   facts: _Facts, who: str, gaps: list, raw_account: Optional[str]) -> list[dict]:
    out: list[dict] = []
    try:
        cats = reader.events(sym, start, end) or []
    except Exception as exc:  # noqa: BLE001
        cats = []
        if f"catalyst_events: {type(exc).__name__}" not in gaps:
            gaps.append(f"catalyst_events: {type(exc).__name__}")
    seen = set()
    for c in cats:
        d = _d(c.get("at"))
        head = str(c.get("headline") or "").strip()
        key = head.lower()[:80]
        if not d or not head or key in seen:
            continue
        seen.add(key)
        ctype = str(c.get("catalyst_type") or "event")
        out.append({"date": d.isoformat(), "kind": "earnings" if "earn" in ctype.lower() else "catalyst", "type": ctype,
                    "headline": head[:200], **reaction(s, d)})
    out += big_moves(s, start, end, threshold)
    for f in fills or []:
        d = _d(f.get("fill_date"))
        if d and start <= d <= end + timedelta(days=1) and (raw_account is None or _acct_key(f.get("account")) == _acct_key(raw_account)):
            out.append({"date": d.isoformat(), "kind": "stop_fill", "type": "stop filled",
                        "headline": f"Stop filled at {_f(f.get('stop_price'))} ({account_name(f.get('account'))}); "
                                    f"sold {f.get('fill_qty'):g} @ {f.get('fill_price')} per the journal",
                        **reaction(s, d)})
        elif not d and f.get("captured_at") and "stop fill dates" not in " ".join(gaps):
            gaps.append("stop fill dates: a filled stop in stop_last_known has no matching journal sell, so it is not "
                        "placed on the timeline (stop_last_known.captured_at is the snapshot time, not the fill time)")
    priority = {"stop_fill": 0, "earnings": 1, "big_move": 2, "catalyst": 3}
    out.sort(key=lambda e: (priority.get(e["kind"], 9), -abs(e.get("move_pct") or e.get("five_day_pct") or 0)))
    out = sorted(out[:MAX_EVENTS_PER_WINDOW], key=lambda e: e["date"])
    for e in out:
        bits = []
        if e.get("move_pct") is not None:
            bits.append(f"day move {e['move_pct']:+.2f}%")
        if e.get("next_day_pct") is not None:
            bits.append(f"{'next session' if e['kind'] == 'big_move' else 'day-of reaction'} {e['next_day_pct']:+.2f}%")
        if e.get("five_day_pct") is not None:
            bits.append(f"5-session {e['five_day_pct']:+.2f}%")
        what = e.get("headline") or ("|day move| ≥ %g%%" % threshold)
        e["fact"] = facts.add(f"{who} while held: {e['kind'].replace('_', ' ')} {e['date']}",
                              text=f"{what}; " + ", ".join(bits) if bits else what,
                              source=SRC_CAT if e["kind"] in ("catalyst", "earnings") else
                              ("stop_last_known" if e["kind"] == "stop_fill" else SRC_PX), as_of=e["date"])
    return out


def _acct_key(raw: Any) -> str:
    """Canonical account key (holdings say ``schwab_roth``, stop rows ``schwab_roth_ira``)."""
    try:
        return _plib("account_display").canonical_key(raw)
    except Exception:  # noqa: BLE001
        return str(raw or "").lower().replace("_ira", "").replace("-", "_")


def date_stop_fills(fills: Iterable[dict], txs: Iterable[dict], *, price_tol: float = 0.01) -> list[dict]:
    """Date each filled stop by its matching journal SELL (same account, price within 1 % of the stop, on or before
    the observation), never by ``stop_last_known.captured_at``: that column is the time the read snapshot was taken —
    every row of one read carries the same instant — so an older fill showed up as "today" with a reaction computed
    from the wrong day (accuracy audit 2026-10-26). An unmatched fill keeps ``fill_date`` None."""
    sells = [t for t in txs or [] if str(t.get("action") or "").strip().lower().startswith("sell")]
    out = []
    for f in fills or []:
        row = dict(f)
        stop = _f(f.get("stop_price"))
        seen = _d(f.get("captured_at"))
        cands = [t for t in sells if stop and _f(t.get("price")) and abs(_f(t["price"]) / stop - 1) <= price_tol
                 and _acct_key(t.get("account")) == _acct_key(f.get("account"))
                 and (seen is None or (_d(t.get("trade_date")) or date.max) <= seen)]
        best = max(cands, key=lambda t: str(t.get("trade_date") or ""), default=None)
        row["fill_date"] = _d(best.get("trade_date")) if best else None
        row["fill_qty"] = abs(_f(best.get("quantity")) or 0) if best else None
        row["fill_price"] = _f(best.get("price")) if best else None
        out.append(row)
    return out


def _lessons(trips: list[dict], facts: _Facts, sym: str) -> list[dict]:
    closed = [t for t in trips if t.get("realized_pct") is not None]
    out: list[dict] = []

    def stat(sid: str, label: str, value: Any, n: int, unit: str = "", note: str = "") -> None:
        if value is None:
            return
        fid = facts.add(f"Lesson stat: {label}", value=value, unit=unit, source=f"derived: {SRC_TRIP} + {SRC_PX}")
        out.append({"id": sid, "label": label, "value": value, "unit": unit, "n": n, "note": note, "fact": fid})

    if len(closed) < 2:
        return out
    wins = [t for t in closed if t["realized_pct"] > 0]
    losses = [t for t in closed if t["realized_pct"] < 0]
    aw, al = _mean([t["realized_usd"] for t in wins if t.get("realized_usd") is not None]), \
        _mean([t["realized_usd"] for t in losses if t.get("realized_usd") is not None])
    if aw is not None and al:
        stat("payoff", "payoff ratio (average win $ ÷ |average loss $|)", round(aw / abs(al), 2), len(closed))
    ranged = [t for t in closed if t.get("entry_vs_52w_range_pct") is not None]
    hi = [t["realized_pct"] for t in ranged if t["entry_vs_52w_range_pct"] >= 50]
    lo = [t["realized_pct"] for t in ranged if t["entry_vs_52w_range_pct"] < 50]
    if hi and lo:
        stat("entry_upper_half", "average result of entries in the upper half of the 52-week range %", _mean(hi), len(hi), "%")
        stat("entry_lower_half", "average result of entries in the lower half of the 52-week range %", _mean(lo), len(lo), "%")
    holds = sorted(t["hold_days"] for t in closed if t.get("hold_days") is not None)
    if len(holds) >= 2:
        med = statistics.median(holds)
        short = [t["realized_pct"] for t in closed if t.get("hold_days") is not None and t["hold_days"] <= med]
        long_ = [t["realized_pct"] for t in closed if t.get("hold_days") is not None and t["hold_days"] > med]
        stat("hold_median", "median days held", med, len(holds))
        if short and long_:
            stat("hold_short", "average result of holds at or below the median length %", _mean(short), len(short), "%")
            stat("hold_long", "average result of holds longer than the median %", _mean(long_), len(long_), "%")
    stops = [t for t in closed if t.get("stopped_out")]
    journaled = [t for t in closed if t.get("journaled")]
    if journaled:
        stat("stop_rate", "share of journaled trips that ended at a stop %", round(len(stops) / len(journaled) * 100, 1),
             len(journaled), "%", "journal exit type hard_stop / trailing_stop")
        if stops:
            stat("stop_result", "average result of stopped-out trips %", _mean([t["realized_pct"] for t in stops]), len(stops), "%")
    ordered = sorted(closed, key=lambda t: t.get("exit_date") or "")
    reentries = 0
    for t in ordered:
        if t["realized_pct"] < 0 and t.get("exit_date"):
            x = date.fromisoformat(t["exit_date"])
            if any(o.get("entry_date") and 0 <= (date.fromisoformat(o["entry_date"]) - x).days <= _LOSS_REENTRY_DAYS
                   for o in trips if o is not t):
                reentries += 1
    if losses:
        stat("reentry_after_loss", f"losing trips followed by a re-entry in {sym} within {_LOSS_REENTRY_DAYS} days", reentries,
             len(losses))
    return out


# ── prompt + writer note ──────────────────────────────────────────────────────────────────────────────────────────
def prompt_lines(bundle: Any) -> list[str]:
    mh = bundle.blocks.get("my_history") or {}
    if not (mh.get("open_lots") or mh.get("trips")):
        return []
    return ["",
            f"MY HISTORY — this reader's own trades in {bundle.symbol}: the facts labelled \"My open position\", \"Trip N\", "
            "\"My history\", \"while held\", \"Lesson stat\" and \"tax flag\" are their open lots (by account name), every "
            "round trip, what happened while each was held, deterministic lesson statistics and tax flags.",
            "Also return \"notes\".\"my_history\": {\"summary\": \"<3-5 sentences: average cost and open P/L, lifetime realized "
            "P/L and win/loss across round trips, and the catalysts or big moves that hit while held, citing fact ids>\", "
            "\"lessons\": \"<2-4 sentences interpreting the lesson statistics and journal lessons, citing fact ids; describe "
            "patterns only, never advise a trade>\"}. Use only these facts' numbers. Omit the key when there are no such facts."]


def apply_writer_note(blocks: dict, parsed: dict, guard: Callable[[str, str], str]) -> None:
    mh = blocks.get("my_history")
    if not isinstance(mh, dict):
        return
    notes = (parsed or {}).get("notes") if isinstance((parsed or {}).get("notes"), dict) else {}
    raw = notes.get("my_history") if isinstance(notes.get("my_history"), dict) else {}
    mh["writer_note"] = {k: (guard(str(raw.get(k) or ""), f"notes.my_history.{k}")[:900] or None) for k in ("summary", "lessons")}
