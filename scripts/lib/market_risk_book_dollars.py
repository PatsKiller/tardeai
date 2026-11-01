"""Home market-risk card, design home/v005: the API-side dollar join (SPEC "Data the projection must start passing
through", items 5 and 6).

The engine assessment carries symbols, look-through shares and opaque account ids only — it feeds the CIO and model
curation, and position dollars / account identity are not cleared for an external provider (AGENTS.md §2A). The
dollars and account labels are joined HERE, in the Command Center API, from the holdings store Home already reads
(``portfolio_positions.load_store``). Nothing here is written anywhere or sent to a model.

Pure functions over dicts; the API route does the reads. MBI_BEHAVIOR = 0: every output is a fact or a review prompt;
no size, order or stop level to set.
"""

from __future__ import annotations

import hashlib
from typing import Any, Callable

SCHEMA = "MarketRiskBookExposure@v1"
STRESSED_STATES = ("STRESS", "WEAK")


def _f(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def opaque_account(label: Any) -> str:
    """Same opaque id as ``market_risk.exposure.opaque_account`` (kept here so the API need not import the engine)."""
    return "acct-" + hashlib.sha256(str(label or "").encode("utf-8")).hexdigest()[:8]


def stressed_share(groups: dict[str, float], kinds: dict[str, str], stressed: set[str]) -> float:
    """Share of a position in stressed groups, never double-counted: sectors partition a position, themes overlap
    sectors -> min(1, max(sum of stressed sector shares, largest stressed theme share))."""
    sec = sum(_f(w) for g, w in groups.items() if g in stressed and kinds.get(g) == "sector")
    th = max([_f(w) for g, w in groups.items() if g in stressed and kinds.get(g) != "sector"] or [0.0])
    return round(min(1.0, max(sec, th)), 4)


def scope_labels(keys: list[str], label_fn: Callable[[str], str], canon_fn: Callable[[str], str]) -> dict[str, str]:
    """Opaque scope id -> account label, for every raw and canonical spelling of every known account key."""
    out: dict[str, str] = {}
    for k in keys:
        for spelling in {k, canon_fn(k)}:
            if spelling:
                out[opaque_account(spelling)] = label_fn(k)
    return out


def build(
    projection: dict[str, Any],
    store: dict[str, Any],
    *,
    stops: list[dict[str, Any]] | None,
    policy: dict[str, Any] | None,
    label_fn: Callable[[str], str],
    canon_fn: Callable[[str], str],
    ledger_sells: list[dict[str, Any]] | None = None,
    deferred_loss: Callable[[str, str, str], float | None] | None = None,
) -> dict[str, Any]:
    """Return ``{book_exposure, review, scope_labels, budgets, reentry}`` for the projection. ``stops``: last-known
    resting stops ``{account, symbol, stop_price}``. ``ledger_sells``: trade-ledger sales after the holdings build
    with no later buy (``{symbol, account, date}``), for the data-conflict review item. ``deferred_loss(symbol,
    scope, loss_sale_date)``: the loss a wash sale deferred, in dollars, when the API can read it."""
    pol = policy or {}
    rv_cfg = pol.get("home_review") or {}
    mat = ((pol.get("positions") or {}).get("materiality") or {})
    min_mv = _f(mat.get("min_market_value", 1000.0))
    min_sh = _f(mat.get("min_shares", 1.0))
    stop_near = _f(rv_cfg.get("stop_near_pct", 5.0))
    stressed_min = _f(rv_cfg.get("stressed_min_usd", 1000.0))
    max_items = int(rv_cfg.get("max_items", 5))
    max_rows = int(rv_cfg.get("max_position_rows", 5))
    # the book total must match the Home "All accounts" total within this many dollars, else dollars are hidden
    tolerance = _f(rv_cfg.get("reconcile_tolerance_usd", 1.0))
    # stops unread (the stop read failed) is NOT "no stop": no stop items and no stop column (review of #2447, B2)
    stops_known = stops is not None

    heat = [h for h in projection.get("heatmap") or [] if isinstance(h, dict)]
    kinds = {h.get("key"): h.get("kind") for h in heat}
    stressed = {h.get("key") for h in heat if h.get("state") in STRESSED_STATES and h.get("kind") in ("sector", "theme")}
    positions = {k: v for k, v in (projection.get("positions") or {}).items() if isinstance(v, dict) and not k.startswith("_")}
    residual_lt = ((projection.get("positions") or {}).get("_book") or {}).get("residual_look_through") or {}

    holdings = [h for h in store.get("holdings") or [] if isinstance(h, dict) and h.get("symbol")]
    total = round(sum(_f(h.get("market_value")) for h in holdings), 2)
    cash = round(sum(_f(h.get("market_value")) for h in holdings if h.get("is_cash")), 2)
    invested = round(total - cash, 2)
    home_total = _f((store.get("portfolio_totals") or {}).get("total_value"))
    reconciles = bool(home_total) and abs(home_total - total) <= tolerance
    acct_tot: dict[str, float] = {}
    for h in holdings:
        acct_tot[str(h.get("account"))] = acct_tot.get(str(h.get("account")), 0.0) + _f(h.get("market_value"))

    stop_dist: dict[tuple[str, str], float] = {}
    for s in stops or []:
        k = (canon_fn(str(s.get("account") or "")), str(s.get("symbol") or "").upper())
        stop_dist[k] = _f(s.get("stop_price"))

    rows, groups_usd, unmapped = [], {}, []
    for h in holdings:
        if h.get("is_cash"):
            continue
        mv = _f(h.get("market_value"))
        if mv <= 0:
            continue
        sym = str(h["symbol"]).upper()
        acct = str(h.get("account"))
        rec = positions.get(sym) or {}
        lt = rec.get("look_through") or residual_lt.get(sym) or {}
        g = {k: _f(v) for k, v in (lt.get("groups") or {}).items() if v}
        for k, w in g.items():
            groups_usd[k] = groups_usd.get(k, 0.0) + mv * w
        if not g:
            unmapped.append({"symbol": sym, "account_label": label_fn(acct), "usd": round(mv, 2),
                             "reason": lt.get("note") or lt.get("basis") or "not in the engine's look-through"})
        sh = stressed_share(g, kinds, stressed)
        px = _f(h.get("canonical_mark") or h.get("price") or h.get("current_price"))
        lvl = stop_dist.get((canon_fn(acct), sym))
        dist = round((px - lvl) / px * 100.0, 1) if lvl and px else None
        material = mv >= min_mv and _f(h.get("shares") or h.get("quantity")) >= min_sh
        rows.append({
            "symbol": sym, "account_label": label_fn(acct), "account_scope": opaque_account(acct),
            "value_usd": round(mv, 2),
            "pct_account": round(100.0 * mv / acct_tot[acct], 1) if acct_tot.get(acct) else None,
            "stressed_share": sh, "usd_exposed": round(mv * sh, 2), "stop_distance_pct": dist,
            "stance": rec.get("label") if material else "residual", "material": material,
            "look_through_basis": lt.get("basis"),
        })
    rows.sort(key=lambda r: (-r["usd_exposed"], -r["value_usd"]))
    stressed_usd = round(sum(r["usd_exposed"] for r in rows), 2)
    exposed = [r for r in rows if r["usd_exposed"] > 0]
    top = exposed[0] if exposed else None
    largest = None
    if top:
        tg = max(((k, w) for k, w in ((positions.get(top["symbol"]) or {}).get("look_through") or {}).get("groups", {}).items()
                  if k in stressed), key=lambda kv: _f(kv[1]), default=(None, None))
        largest = {"symbol": top["symbol"], "account_label": top["account_label"], "group": tg[0], "share": tg[1]}
    zero = sorted({r["symbol"] for r in rows if r["material"] and r["usd_exposed"] == 0})
    book_exposure = {
        "schema": SCHEMA,
        "total_usd": total, "home_total_usd": home_total or None, "reconciles": reconciles,
        "cash_usd": cash, "invested_usd": invested,
        "stressed_groups": sorted(stressed),
        "stressed_usd": stressed_usd,
        "stressed_pct_book": round(100.0 * stressed_usd / total, 2) if total else None,
        "stressed_pct_invested": round(100.0 * stressed_usd / invested, 2) if invested else None,
        "cash_pct_book": round(100.0 * cash / total, 1) if total else None,
        "largest_contributor": largest,
        "groups": {k: {"usd": round(v, 2), "pct_book": round(100.0 * v / total, 2) if total else None}
                   for k, v in sorted(groups_usd.items(), key=lambda kv: -kv[1])},
        "unmapped": unmapped,
        "rows": exposed[:max_rows],
        "more": {"count": max(0, len(exposed) - max_rows), "usd": round(sum(r["usd_exposed"] for r in exposed[max_rows:]), 2)},
        "zero_exposure_symbols": zero,
        "as_of": store.get("data_as_of"),
        "stops_known": stops_known,
    }

    # Review now: one item per (symbol, account), reasons merged, ranked by dollars at risk
    items: dict[tuple[str, str], dict[str, Any]] = {}

    def add(r: dict[str, Any], kind: str, text: str, usd: float, to: str) -> None:
        k = (r["symbol"], r["account_scope"])
        it = items.setdefault(k, {"symbol": r["symbol"], "account_label": r["account_label"], "kinds": [], "reasons": [],
                                  "usd": 0.0, "to": to})
        it["kinds"].append(kind)
        it["reasons"].append(text)
        it["usd"] = round(max(it["usd"], usd), 2)
        if kind in ("stop_near", "no_stop"):
            it["to"] = to

    for r in rows:
        stop_to = f"/risk?tab=exposure&symbol={r['symbol']}"
        page_to = f"/prospectus/{r['symbol']}"
        if r["stop_distance_pct"] is not None and r["stop_distance_pct"] <= stop_near:
            add(r, "stop_near", f"stop {r['stop_distance_pct']:.1f}% below last", r["value_usd"], stop_to)
        if stops_known and r["material"] and r["stop_distance_pct"] is None:
            add(r, "no_stop", "no stop", r["value_usd"], stop_to)
        if r["usd_exposed"] >= stressed_min:
            add(r, "stressed_exposure", f"{round(100 * r['stressed_share'])}% in stressed groups", r["usd_exposed"], page_to)
        if r["material"] and r["look_through_basis"] in ("stock_unknown", "fund_unknown", None):
            add(r, "no_lookthrough", "no look-through (sector unknown)", r["value_usd"], page_to)
    held_keys = {(str(h["symbol"]).upper(), canon_fn(str(h.get("account")))): h for h in holdings if not h.get("is_cash")}
    # sales after the holdings build, summed per (symbol, account) — several partial sales can close a position; the
    # ledger may sign a sale's quantity either way (review of PR 2447)
    sold_by: dict[tuple[str, str], dict[str, Any]] = {}
    for s in ledger_sells or []:
        key = (str(s.get("symbol")).upper(), canon_fn(str(s.get("account"))))
        agg = sold_by.setdefault(key, {"symbol": key[0], "account": s.get("account"), "date": s.get("date"), "quantity": 0.0,
                                       "known": True})
        q = s.get("quantity")
        if q is None:
            agg["known"] = False
        agg["quantity"] += abs(_f(q))
        agg["date"] = max(str(agg["date"] or ""), str(s.get("date") or ""))
    for key, s in sold_by.items():
        h = held_keys.get(key)
        # a conflict only when the sales would have closed out what the holdings still show (a partial sale leaves
        # shares; without every sold quantity the ledger cannot say)
        sold = s["quantity"] if s["known"] else 0.0
        if h and _f(h.get("shares")) > 0 and sold > 0 and sold >= _f(h.get("shares")):
            r = next((x for x in rows if x["symbol"] == str(s["symbol"]).upper() and x["account_scope"] == opaque_account(h.get("account"))), None)
            if r:
                add(r, "data_conflict", f"ledger says sold {s.get('date')}, holdings still show it — confirm with the broker",
                    r["value_usd"], f"/prospectus/{r['symbol']}")
    review = sorted(items.values(), key=lambda i: -i["usd"])[:max_items]
    for i in review:
        i["text"] = " · ".join(i.pop("reasons"))

    labels = scope_labels(sorted(set(acct_tot) | {str(s.get("account")) for s in stops or []}), label_fn, canon_fn)

    # Budget breaches with account labels and dollars; drivers sorted by dollars (the engine truncates alphabetically)
    budgets = []
    by_scope_sym: dict[tuple[str, str], float] = {}
    unprotected: dict[str, list[tuple[str, float]]] = {}
    scope_total: dict[str, float] = {}
    for a, t in acct_tot.items():
        for sp in {opaque_account(a), opaque_account(canon_fn(a))}:
            scope_total[sp] = t
    for h in holdings:
        if h.get("is_cash") or _f(h.get("market_value")) <= 0:
            continue
        acct, sym, mv = str(h.get("account")), str(h["symbol"]).upper(), _f(h.get("market_value"))
        no_stop = (canon_fn(acct), sym) not in stop_dist
        for sp in {opaque_account(acct), opaque_account(canon_fn(acct))}:
            by_scope_sym[(sp, sym)] = mv
            if no_stop:
                unprotected.setdefault(sp, []).append((sym, mv))
    for b in (projection.get("book") or {}).get("budgets") or []:
        sc = b.get("scope_id") or b.get("scope")
        tot = scope_total.get(sc)
        drivers = []
        for d in b.get("drivers") or []:
            usd = by_scope_sym.get((sc, str(d).upper()))
            drivers.append({"name": d, "usd": round(usd, 2) if usd is not None else None})
        if b.get("budget") == "unprotected_pct" and stops_known:
            # every unprotected holding of the account is a driver, largest first (the engine list is alphabetical
            # and truncated, so it can miss the largest one)
            known = {d["name"] for d in drivers}
            drivers += [{"name": sym, "usd": round(v, 2)} for sym, v in unprotected.get(sc, []) if sym not in known]
        drivers.sort(key=lambda d: -(d["usd"] or 0))
        actual = b.get("actual")
        budgets.append({
            "account_label": labels.get(sc, "one account"), "budget": b.get("budget"), "limit": b.get("limit"),
            "actual": actual, "unit": b.get("unit") or "%",
            "actual_usd": round(_f(actual) / 100.0 * tot, 2) if tot and actual is not None and (b.get("unit") or "%") == "%" else None,
            "drivers": drivers,
        })

    # Re-entry: account labels and the deferred wash-sale loss
    reentry = {}
    for sym, card in (projection.get("reentry_watch") or {}).items():
        if not isinstance(card, dict) or sym.startswith("_"):
            continue
        w = dict(card.get("wash_sale") or {}) or None
        if w:
            w["account_label"] = labels.get(w.get("account_scope"), "one account")
            if w.get("state") == "occurred" and deferred_loss:
                try:
                    w["deferred_loss_usd"] = deferred_loss(sym, w.get("account_scope"), w.get("loss_sale_date"))
                except Exception:  # noqa: BLE001 — the amount is optional; the line reads without it
                    w["deferred_loss_usd"] = None
        reentry[sym] = {
            "exit_account_label": labels.get(card.get("exit_account_scope")),
            "held_elsewhere_labels": [labels.get(x, "one account") for x in card.get("held_elsewhere") or []],
            "wash_sale": w,
        }
    return {"book_exposure": book_exposure, "review": review, "scope_labels": labels, "budgets": budgets,
            "reentry": reentry}
