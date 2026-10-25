"""Read-only conflict producers over STORED state — EXCEPTIONS_MATRIX R9, R10, R12 (2026-10-25).

Operator 2026-10-25, verbatim: "I need you to fix everything that's missing before deployment."

Each producer turns rows that existing jobs already write into typed engine ``Input`` observations:

  R9  wash windows      trade_transactions (Schwab ingest) → scripts/lib/wash_sale.py (the ONE implementation) →
                        one ``wash_sale`` gate per security: BLOCKED (taxable LOSS sale inside 30 d), UNKNOWN (taxable
                        sale, gain not computable), CLEAR (gain: house hold only). The gate covers every account.
  R10 option outcomes   options_strategy_positions (+ latest options_lifecycle_decisions) → one claim per open,
                        non-paper strategy with metadata instrument="option": never an equity stance; the profile only
                        checks the cross-instrument contradiction (long call vs equity EXIT).
  R12 pending fills     trade_transactions fills recorded AFTER the account's last broker-confirmed position sync in
                        the canonical holdings store (portfolio_positions.load_store — the same store the ``held``
                        flag comes from; per-row ``broker_position_as_of_at`` / ``updated_at``) → the name is frozen
                        (context pending_fill) with a ``pending_fill`` fact. Stance/position vs fill
                        mismatches already diagnosed by the CIO prospect builder (saved ``held`` /
                        ``stance_after_exit`` conflicts) → an ownership DATA_ERROR fact (see ownership_facts).
                        Filled/pending broker stops arrive separately as protection inputs (cio_truth stop_last_known).

Identity: producer rows carry symbols; each symbol resolves through the identity registry to a CONFIRMED security GUID
and attaches only to the bundle with that GUID (R16: sides join by GUID only). Unresolved symbols are counted, never
joined by label.

SELECT only. MBI_BEHAVIOR = 0: no broker call, no credential, no order/stop code path. A producer that cannot read its
store marks every bundle with a visible gap (and R9 an UNKNOWN wash gate) — never a silent clear.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any, Callable, Iterable, Optional
from zoneinfo import ZoneInfo

from .engine import Input

NY = ZoneInfo("America/New_York")
SCHEMA = "ConflictProducerSummary@v1"

#: options_strategy_positions.strategy_type → the option claim value (never an equity stance).
OPTION_CLAIMS = {"long_call": "LONG_CALL", "long_put": "LONG_PUT", "covered_call": "COVERED_CALL",
                 "cash_secured_put": "SHORT_PUT", "protective_put": "PROTECTIVE_PUT", "collar": "COLLAR",
                 "debit_spread": "DEBIT_SPREAD", "credit_spread": "CREDIT_SPREAD", "straddle": "STRADDLE",
                 "strangle": "STRANGLE", "unknown_multi_leg": "UNKNOWN_MULTI_LEG"}
OPTION_OPEN_STATUSES = ("open", "closing")
#: Structure unknown → the claim is "no opinion" (R14), never a side.
OPTION_PARTIAL_QUALITY = {"ambiguous", "missing_leg"}
#: Saved CIO prospect diagnostics that are stance/position-vs-fill disagreements (cio_prospect_builder._conflict).
OWNERSHIP_FIELDS = {"held": "positions still list the name after a recorded exit fill",
                    "stance_after_exit": "the CIO record still treats the name as owned after a recorded exit fill"}

WASH_SQL = """SELECT upper(symbol) AS symbol, account, action, trade_date, trade_time, quantity, price, amount, fees
               FROM trade_transactions WHERE upper(symbol) = ANY(%s) ORDER BY trade_date, trade_time"""
OPTION_SQL = """SELECT p.strategy_position_id, p.broker, p.account_key, p.strategy_type, upper(p.underlying) AS underlying,
                       p.status, p.source, p.opened_at, p.updated_at, p.data_quality_status,
                       d.recommendation, d.created_at AS recommendation_at
                  FROM options_strategy_positions p
                  LEFT JOIN LATERAL (SELECT recommendation, created_at FROM options_lifecycle_decisions x
                                      WHERE x.strategy_position_id = p.strategy_position_id
                                      ORDER BY created_at DESC LIMIT 1) d ON TRUE
                 WHERE lower(p.status) = ANY(%s) AND lower(coalesce(p.source, '')) <> 'paper_lane'"""
FILLS_SQL = """SELECT upper(symbol) AS symbol, account, action, trade_date, trade_time, quantity, price
                 FROM trade_transactions
                WHERE trade_date >= %s AND (lower(action) LIKE 'buy%%' OR lower(action) LIKE 'sell%%')"""


def _aware(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo and value.utcoffset() is not None else None
    if isinstance(value, date):
        return datetime.combine(value, time(0), NY)
    if value:
        try:
            at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        return at if at.tzinfo else None
    return None


def _account(value: Any) -> str:
    try:
        from scripts.lib.account_display import canonical_key
    except ImportError:  # scripts/ on sys.path
        from lib.account_display import canonical_key  # type: ignore
    return canonical_key(value)


def _default_query():
    from db_adapter import _execute

    def query(sql, params=None):
        return _execute(sql, params, fetch="all") or []
    return query


def _default_resolver():
    from scripts.lib.identity_carriage import resolve_security_identity
    return resolve_security_identity


# ── R9 ──────────────────────────────────────────────────────────────────────

def wash_inputs(windows: dict[str, dict], *, now: datetime) -> dict[str, Input]:
    """{SYMBOL: Input} from wash_sale.windows_from_transactions output."""
    from scripts.lib import wash_sale
    out = {}
    for sym, w in windows.items():
        value = wash_sale.RESOLVER_VALUE.get(w.get("kind"), "UNKNOWN")
        sale = _aware(w.get("sell_date"))
        detail = (f"wash window through {w.get('until')} — taxable sale {w.get('sell_date')} in {w.get('account')}"
                  + ("; replacement purchases inside the 61-day window already wash the loss" if w.get("loss_washed")
                     else "") if w.get("gated") else f"no wash window ({w.get('label')})")
        out[sym] = Input("wash_sale", value, min(sale, now) if sale else now, role="gate", account=None, detail=detail,
                         metadata={"accounts_gated": "all", "wash_kind": w.get("kind"), "until": w.get("until"),
                                   "loss_washed": w.get("loss_washed", False), "wash_status": w.get("wash_status"),
                                   "matched_quantity": w.get("matched_quantity"),
                                   "ira_permanent_quantity": w.get("ira_permanent_quantity"), "scope": w.get("scope"),
                                   "replacements": w.get("replacements") or [],
                                   "sale_date": w.get("sell_date"), "sale_account": w.get("account"),
                                   "realized_gain": w.get("realized_gain"), "label": w.get("label")})
    return out


def wash_windows(symbols: Iterable[str], *, now: datetime, query: Callable) -> dict[str, dict]:
    from scripts.lib import wash_sale
    rows = query(WASH_SQL, (sorted({s.upper() for s in symbols}),)) or []
    return wash_sale.windows_from_transactions([dict(r) for r in rows], today=now.astimezone(NY).date())


# ── R10 ─────────────────────────────────────────────────────────────────────

def option_inputs(rows: Iterable[dict]) -> dict[str, list[Input]]:
    """{UNDERLYING: [Input]} — one option claim per open, non-paper strategy position."""
    out: dict[str, list[Input]] = {}
    for r in rows:
        status = str(r.get("status") or "").lower()
        if status not in OPTION_OPEN_STATUSES or str(r.get("source") or "").lower() == "paper_lane":
            continue
        sym = str(r.get("underlying") or "").upper()
        if not sym:
            continue
        stype = str(r.get("strategy_type") or "").lower()
        quality = "partial" if str(r.get("data_quality_status") or "").lower() in OPTION_PARTIAL_QUALITY else "complete"
        at = _aware(r.get("updated_at")) or _aware(r.get("opened_at"))
        out.setdefault(sym, []).append(Input(
            "option_position", OPTION_CLAIMS.get(stype, "UNKNOWN_MULTI_LEG"), at, role="claim",
            account=_account(r.get("account_key")) or None,
            detail=f"{stype or 'unknown'} #{r.get('strategy_position_id')} ({status})",
            metadata={"instrument": "option", "quality": quality, "strategy_type": stype,
                      "strategy_position_id": r.get("strategy_position_id"),
                      "option_recommendation": r.get("recommendation"),
                      "option_recommendation_at": str(r.get("recommendation_at") or "") or None,
                      "data_quality_status": r.get("data_quality_status")}))
    return out


# ── R12 ─────────────────────────────────────────────────────────────────────

def holdings_snapshots(holdings_doc: dict) -> dict[str, datetime]:
    """{account: last broker-confirmed sync time} from the canonical holdings document (cash rows included).

    schwab_position_sync stamps ``updated_at`` (and ``broker_position_as_of_at`` when present) on every row the broker
    confirmed; date-only or naive stamps are not times and are skipped (the account then has no snapshot → gap).
    """
    out: dict[str, datetime] = {}
    for row in (holdings_doc or {}).get("holdings") or []:
        if not isinstance(row, dict):
            continue
        acct = _account(row.get("account_id") or row.get("account"))
        raw = row.get("broker_position_as_of_at") or row.get("updated_at")
        at = _aware(raw) if not isinstance(raw, date) or isinstance(raw, datetime) else None
        if acct and at and (acct not in out or at > out[acct]):
            out[acct] = at
    return out



def pending_fill_inputs(fills: Iterable[dict], snapshots: dict[str, Any]) -> tuple[dict[str, list[Input]], dict[str, set]]:
    """Fills recorded after the account's positions snapshot → {SYMBOL: [pending_fill fact]}.

    A fill with a trade_time is pending when trade_time > snapshot; without one, when its NY trade date is after
    the snapshot's NY date. A fill in an account with no positions snapshot cannot be judged → returned as
    {SYMBOL: {account}} gaps.
    """
    out: dict[str, list[Input]] = {}
    gaps: dict[str, set] = {}
    snaps = {_account(k): _aware(v) for k, v in snapshots.items()}
    for f in fills:
        acct = _account(f.get("account"))
        sym = str(f.get("symbol") or "").upper()
        if not sym or not acct:
            continue
        snap = snaps.get(acct)
        if snap is None:
            gaps.setdefault(sym, set()).add(acct)
            continue
        at = _aware(f.get("trade_time"))
        day = f.get("trade_date")
        day = day if isinstance(day, date) and not isinstance(day, datetime) else _aware(day).date() if _aware(day) else None
        if at is not None:
            pending = at > snap
        elif day is not None:
            pending = day > snap.astimezone(NY).date()
        else:
            continue
        if not pending:
            continue
        when = at or _aware(day)
        out.setdefault(sym, []).append(Input(
            "pending_fill", "PENDING_FILL", when, role="fact", account=acct,
            detail=f"{f.get('action')} {f.get('quantity')} recorded {when.isoformat()} after the positions snapshot "
                   f"{snap.isoformat()}",
            metadata={"positions_as_of": snap.isoformat(), "action": f.get("action"),
                      "quantity": str(f.get("quantity")) if f.get("quantity") is not None else None}))
    return out, gaps


def ownership_facts(saved_diagnostics: Iterable[dict], *, subject_id: Optional[str]) -> list[Input]:
    """Unresolved stance/position-vs-fill diagnostics the CIO prospect builder saved → ownership DATA_ERROR facts."""
    out = []
    for raw in saved_diagnostics or []:
        if not isinstance(raw, dict) or raw.get("field") not in OWNERSHIP_FIELDS or raw.get("resolved"):
            continue
        sides = raw.get("sides") or raw.get("values") or []
        times = [t for t in (_aware(s.get("as_of") or s.get("at")) for s in sides if isinstance(s, dict)) if t]
        shown = " · ".join(f"{s.get('source_label') or s.get('source')}: {s.get('value')}" for s in sides
                           if isinstance(s, dict))
        out.append(Input(f"fill_vs_{raw['field']}", "MISMATCH", max(times) if times else None, role="fact",
                         subject_id=subject_id, detail=f"{OWNERSHIP_FIELDS[raw['field']]} ({shown})",
                         metadata={"mismatch": True, "ownership": True, "diagnostic_id": raw.get("id"),
                                   "sides": sides}))
    return out


# ── attach ──────────────────────────────────────────────────────────────────

def attach(bundles: list, *, now: datetime, root: Any = None, holdings: Optional[dict] = None,
           query: Optional[Callable] = None, resolve_identity: Optional[Callable] = None) -> tuple[list, dict]:
    """Add R9/R10/R12 producer inputs to security bundles in place. Returns (bundles, summary).

    ``holdings`` is the canonical holdings document; when omitted it is loaded from ``root`` (the lane's state root)
    through portfolio_positions.load_store.
    """
    summary: dict[str, Any] = {"schema": SCHEMA, "as_of": now.isoformat(), "bundles": len(bundles),
                               "wash_windows": {}, "option_claims": 0, "pending_fills": 0, "ownership_facts": 0,
                               "unresolved_symbols": [], "gaps": []}
    securities = [b for b in bundles if b.subject.kind == "security"]
    for b in bundles:
        summary["ownership_facts"] += sum(1 for i in b.inputs if i.metadata.get("ownership"))
    if not securities:
        return bundles, summary
    gaps: list[str] = []
    try:
        query = query or _default_query()
    except Exception as exc:  # noqa: BLE001 -- no store reader: every producer is unavailable, visibly
        query, gaps = None, [f"stored-state reader unavailable: {type(exc).__name__}"]
    try:
        resolve_identity = resolve_identity or _default_resolver()
    except Exception as exc:  # noqa: BLE001
        resolve_identity, gaps = None, gaps + [f"identity registry unavailable: {type(exc).__name__}"]
    by_guid = {b.subject.id: b for b in securities}
    cache: dict[str, Optional[str]] = {}

    def guid_for(symbol: str) -> Optional[str]:
        if symbol not in cache:
            ident = (resolve_identity(symbol) if resolve_identity else None) or {}
            cache[symbol] = ident.get("security_guid") if ident.get("identity_status") == "CONFIRMED" else None
        return cache[symbol]

    def place(symbol: str, items: list[Input]) -> Optional[Any]:
        guid = guid_for(symbol)
        bundle = by_guid.get(guid) if guid else None
        if bundle is None:
            if guid is None:
                summary["unresolved_symbols"].append(symbol)
            return None
        for item in items:
            item.subject_id = guid
        bundle.inputs.extend(items)
        return bundle

    symbols = sorted({str(b.subject.label or "").upper() for b in securities if b.subject.label})
    # R9 — one wash gate per security; a failed read is an UNKNOWN gate (never a silent clear).
    wash_failed = None
    if query:
        try:
            windows = wash_windows(symbols, now=now, query=query)
            summary["wash_windows"] = {k: sorted(s for s, w in windows.items() if w["kind"] == k)
                                       for k in {w["kind"] for w in windows.values()}}
            for sym, item in wash_inputs(windows, now=now).items():
                place(sym, [item])
        except Exception as exc:  # noqa: BLE001
            wash_failed = f"wash-window producer unavailable: {type(exc).__name__}"
    else:
        wash_failed = "wash-window producer unavailable: no stored-state reader"
    if wash_failed:
        gaps.append(wash_failed)
        for b in securities:
            b.inputs.append(Input("wash_sale", "UNKNOWN", now, role="gate", subject_id=b.subject.id,
                                  detail=wash_failed, metadata={"accounts_gated": "all", "producer_gap": True}))
    # R10 — open option strategies (read-only lifecycle mirror).
    if query:
        try:
            rows = [dict(r) for r in query(OPTION_SQL, (list(OPTION_OPEN_STATUSES),)) or []]
            for sym, items in option_inputs(rows).items():
                if place(sym, items):
                    summary["option_claims"] += len(items)
        except Exception as exc:  # noqa: BLE001
            gaps.append(f"option-position producer unavailable: {type(exc).__name__}")
    # R12 — fills recorded after the positions snapshot freeze the name.
    if query:
        try:
            if holdings is None:
                try:
                    from scripts.lib.portfolio_positions import load_store, store_path
                except ImportError:  # scripts/ on sys.path
                    from lib.portfolio_positions import load_store, store_path  # type: ignore
                holdings = load_store(store_path(root))
            snaps = holdings_snapshots(holdings)
            if not snaps:
                raise LookupError("holdings store has no broker-confirmed sync time")
            oldest = min((_aware(v) for v in snaps.values() if _aware(v)), default=None)
            since = (oldest.astimezone(NY).date() if oldest else now.astimezone(NY).date())
            fills = [dict(r) for r in query(FILLS_SQL, (since,)) or []]
            pending, no_snapshot = pending_fill_inputs(fills, snaps)
            for sym, items in pending.items():
                bundle = place(sym, items)
                if bundle is not None:
                    bundle.subject.context["pending_fill"] = True
                    summary["pending_fills"] += len(items)
            for sym, accounts in no_snapshot.items():
                bundle = by_guid.get(guid_for(sym) or "")
                if bundle is not None:
                    bundle.gaps.append("pending fill cannot be judged: no positions snapshot for "
                                       + ", ".join(sorted(accounts)))
                    summary["pending_fill_gaps"] = summary.get("pending_fill_gaps", 0) + 1
        except Exception as exc:  # noqa: BLE001
            gaps.append(f"pending-fill producer unavailable: {type(exc).__name__}")
    summary["gaps"] = gaps
    summary["unresolved_symbols"] = sorted(set(summary["unresolved_symbols"]))
    if gaps:
        for b in securities:
            b.gaps.extend(g for g in gaps if g not in b.gaps)
    return bundles, summary
