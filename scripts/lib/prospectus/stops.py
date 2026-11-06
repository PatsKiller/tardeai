"""Stop plan for a held name: the house stop policy's recommended stop beside the broker stop and its state.

Operator 2026-10-26: "it should also recommend what the stops are". Nothing here computes a new stop. The two
inputs are the house's existing readers, both read-only:

* **Recommended stop** — the persisted house protection advisory (``holding_protection_advisor.py``, the
  ``protection_advisory`` rows in ``hermes_research_intelligence``; the same "advised stop" the Stop Management
  drawer and ``stop_drift_alert.py`` show). That advisory is bounded by the deterministic stop policy
  (``config/stop_policy.yaml`` through ``holding_family.classify_family`` / ``protection_bounds``), whose band is
  shown beside it and used to flag an advisory that sits outside the current band. With no advisory on file, the
  level stays empty and the band is shown instead; the band is never turned into a level here.
* **Broker stop** — the persisted broker observations in ``stop_last_known`` read exactly as the Risk page reads
  them (``cio_truth.resolve``: every row, then ``cio_truth.stop_for`` per account, with ``stops.json`` planned
  levels as the fallback), so the prospectus and Risk agree on active / resting / filled / none.

Distance and dollars at risk are plain arithmetic on the last close and the shares held, the same way Risk derives
``distance_to_stop_pct`` and ``loss_at_stop_usd``. The writer model receives the level as a fact and may explain it;
generate.py's guards drop any sentence that sizes, orders or moves a stop. READ_ONLY_ADVISORY (MBI_BEHAVIOR=0): no
broker call, no order path, no store write.
"""
from __future__ import annotations

from datetime import datetime, timezone
import importlib
import json
from typing import Any, Callable, Optional

ADVISORY = "advisory — no AI places, sizes or stops orders"
POLICY = "holding_protection_advisor (protection_advisory) within holding_family.protection_bounds (config/stop_policy.yaml)"
BROKER_SOURCE = "stop_last_known (persisted broker observations, read as Risk reads them: cio_truth.stop_for)"
ADVISORY_MAX_AGE_DAYS = 21  # default; config/prospectus.json → stop_plan.advisory_max_age_days overrides
# One state per name: an order still resting in any account (active, pending, or on record without a reported
# state) outranks a filled one, so a fill in one account never hides a stop still working in another.
# Risk's categories map onto the contract's five states.
_STATE_ORDER = ("active", "pending_activation", "unknown", "filled", "planned", "none")
_CONTRACT_STATE = {"active": "active", "pending_activation": "resting", "filled": "filled", "unknown": "unknown",
                   "planned": "none", "none": "none"}


def _f(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out and abs(out) != float("inf") else None


def _dt(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return out if out.tzinfo else out.replace(tzinfo=timezone.utc)


def _iso(value: Any) -> Optional[str]:
    d = _dt(value)
    return d.isoformat() if d else (str(value) if value else None)


def _mod(*names: str):
    for name in names:
        try:
            return importlib.import_module(name)
        except ImportError:
            continue
    raise ImportError(names[0])


def _money(v: Optional[float]) -> str:
    return "n/a" if v is None else f"${v:,.2f}"


# ── readers (read-only; injectable through ``sources`` for tests) ─────────────────────────────────────────────
def read_broker_rows(sources: Any, sym: str) -> Optional[list[dict]]:
    """Persisted broker stop observations for one symbol, the columns Risk reads. None = store unreadable."""
    if hasattr(sources, "broker_stop_rows"):
        return sources.broker_stop_rows(sym)
    try:
        rows = sources.db()("SELECT account, symbol, order_id, stop_price, qty, status, captured_at FROM stop_last_known "
                            "WHERE upper(symbol) = %s", (sym,), fetch="all")
    except Exception:  # noqa: BLE001 - an unreadable store is a gap, never an error page
        return None
    return [dict(r) for r in rows] if isinstance(rows, (list, tuple)) else None


def read_fills(sources: Any, rows: Optional[list[dict]]) -> Optional[dict]:
    """Ledger settlement of filled stop observations (cio_truth.fill_ledger). None = ledger unreadable."""
    if hasattr(sources, "stop_fills"):
        return sources.stop_fills(rows)
    truth = _mod("lib.cio_truth", "scripts.lib.cio_truth")
    try:
        db = sources.db()
    except Exception:  # noqa: BLE001 - no ledger means filled states say so, never an error page
        return None
    return truth.fill_ledger(rows, db_query=db)


def read_planned(sources: Any) -> dict:
    if hasattr(sources, "planned_stops"):
        return sources.planned_stops() or {}
    reader = getattr(sources, "_json", None)
    doc = reader("data/portfolios/state/stops.json") if callable(reader) else None
    return doc if isinstance(doc, dict) else {}


def read_advisory(sources: Any, sym: str) -> Optional[dict]:
    """Newest persisted house protection advisory for one symbol (the row protection_rec_for_symbol reads)."""
    if hasattr(sources, "protection_advisory"):
        return sources.protection_advisory(sym)
    try:
        rows = sources.db()("SELECT summary, model_used, evidence_json, created_at FROM hermes_research_intelligence "
                            "WHERE research_type = 'protection_advisory' AND upper(symbol) = %s "
                            "ORDER BY created_at DESC LIMIT 1", (sym,), fetch="all") or []
    except Exception:  # noqa: BLE001
        return None
    if not rows:
        return None
    row = dict(rows[0])
    ev = row.get("evidence_json") or {}
    if isinstance(ev, str):
        try:
            ev = json.loads(ev)
        except ValueError:
            ev = {}
    rec = ev.get("recommendation") if isinstance(ev.get("recommendation"), dict) else {}
    return {"stop_price": _f(rec.get("stop_price")), "trail_recommended": bool(rec.get("trail_recommended")),
            "trail_type": rec.get("trail_type"), "trail_offset": _f(rec.get("trail_offset")),
            "family": ev.get("family"), "family_bounds": ev.get("family_bounds") if isinstance(ev.get("family_bounds"), dict) else {},
            "sanity": (ev.get("sanity") or {}).get("verdict") if isinstance(ev.get("sanity"), dict) else ev.get("sanity"),
            "price": _f((ev.get("inputs") or {}).get("price")) if isinstance(ev.get("inputs"), dict) else None,
            "rationale": row.get("summary"), "model": row.get("model_used"), "created_at": _iso(row.get("created_at"))}


def policy_band(sym: str, *, atr_pct: Optional[float], position_value: Optional[float],
                regime: Any = "live") -> Optional[dict]:
    """The deterministic policy band for this name (holding_family). ``regime="live"`` reads the house regime."""
    try:
        hf = _mod("holding_family", "scripts.holding_family")
    except ImportError:
        return None
    try:
        family, source = hf.classify_family(sym, atr_pct)
        if regime == "live":
            regime = hf.current_regime()
        is_stock = (((hf._cfg().get("asset_type_overrides") or {}).get(sym) or "").lower() == "stock"
                    or str(source).startswith("stock"))
        band = hf.protection_bounds(family, regime=regime, position_value_usd=position_value, is_stock=is_stock)
    except Exception:  # noqa: BLE001
        return None
    return {"family": family, "family_source": source, "label": band.get("label") or family,
            "stop_min_pct": _f(band.get("stop_min_pct")), "stop_max_pct": _f(band.get("stop_max_pct")),
            "trail_min_pct": _f(band.get("trail_min_pct")), "trail_max_pct": _f(band.get("trail_max_pct")),
            "regime": band.get("regime")}


# ── the block ─────────────────────────────────────────────────────────────────────────────────────────────────
def broker_view(rows: Optional[list[dict]], planned: dict, accounts: list[str], sym: str, *,
                now: datetime, label_fn: Callable[[Any], str], fills: Optional[dict] = None) -> dict:
    """One state for the name across its accounts, from the same stop_for Risk uses."""
    if rows is None:
        return {"level": None, "state": "unknown", "as_of": None, "source": BROKER_SOURCE,
                "accounts": [], "gap": "broker stop store unreadable"}
    truth = _mod("lib.cio_truth", "scripts.lib.cio_truth")
    per = []
    for account in accounts or []:
        st = truth.stop_for(account, sym, broker_rows=rows, planned=planned, now=now, fills=fills)
        cat = st.get("stop_state") if st.get("stop_state") in ("active", "pending_activation", "filled", "unknown") else (
            "planned" if st.get("stop_source") == "planned" and st.get("stop_price") is not None else "none")
        per.append({"account": label_fn(account), "category": cat, "state": _CONTRACT_STATE[cat],
                    "level": _f(st.get("stop_price")), "as_of": _iso(st.get("stop_captured_at")),
                    "raw_status": st.get("stop_status_raw"), "note": st.get("stop_note")})
    best = min(per, key=lambda p: _STATE_ORDER.index(p["category"]), default=None)
    if best is None:
        return {"level": None, "state": "none", "as_of": None, "source": BROKER_SOURCE, "accounts": []}
    source = BROKER_SOURCE if best["category"] != "planned" else "stops.json planned level (not a broker order)"
    others = [p for p in per if p is not best and p["state"] != best["state"] and p["state"] != "none"]
    note = "; ".join(f"{p['account']}: {p['state']}" + (f" {_money(p['level'])}" if p["level"] is not None else "")
                     for p in others) or None
    return {"level": best["level"], "state": best["state"], "category": best["category"], "as_of": best["as_of"],
            "source": source, "accounts": per, "other_accounts": note}


def recommended_view(advisory: Optional[dict], band: Optional[dict], *, last: Optional[float],
                     shares: Optional[float], now: datetime, max_age_days: float) -> tuple[dict, list[str]]:
    gaps: list[str] = []
    rec = {"level": None, "method": None, "distance_pct": None, "usd_at_risk": None, "policy": POLICY, "as_of": None}
    if band:
        rec["band"] = {k: band.get(k) for k in ("family", "label", "stop_min_pct", "stop_max_pct",
                                                "trail_min_pct", "trail_max_pct", "regime", "family_source")}
        if last and band.get("stop_min_pct") is not None and band.get("stop_max_pct") is not None:
            rec["band"]["levels"] = [round(last * (1 - band["stop_max_pct"] / 100), 2),
                                     round(last * (1 - band["stop_min_pct"] / 100), 2)]
    band_text = (f"{band['label']} band {band['stop_min_pct']:g}–{band['stop_max_pct']:g}% below"
                 if band and band.get("stop_min_pct") is not None and band.get("stop_max_pct") is not None else None)
    if not advisory or advisory.get("stop_price") is None:
        rec["method"] = band_text
        gaps.append("no house stop advisory on file (holding_protection_advisor); the policy band is shown instead")
        return rec, gaps
    created = _dt(advisory.get("created_at"))
    age = (now - created).total_seconds() / 86400 if created else None
    rec["as_of"] = advisory.get("created_at")
    rec["advisory_model"] = advisory.get("model")
    rec["advisory_sanity"] = advisory.get("sanity")
    level = advisory["stop_price"]
    if advisory.get("trail_recommended") and advisory.get("trail_offset") is not None:
        unit = "%" if str(advisory.get("trail_type") or "PERCENT").upper() == "PERCENT" else " $"
        method = f"trailing {advisory['trail_offset']:g}{unit} (initial stop {_money(level)})"
    else:
        method = "fixed stop anchored at or below the 20-day swing low"
    rec["method"] = method + (f"; {band_text}" if band_text else "")
    if age is None or age > max_age_days:
        rec["stale_level"] = level
        gaps.append(f"house stop advisory is {'undated' if age is None else f'{age:.0f} days old'} "
                    f"(over {max_age_days:g}); level withheld until the advisor runs again")
        return rec, gaps
    if str(advisory.get("sanity") or "").lower() == "fail":
        rec["stale_level"] = level
        gaps.append("house stop advisory failed its sanity check; level withheld")
        return rec, gaps
    rec["level"] = level
    if last:
        dist = (last - level) / last * 100
        rec["distance_pct"] = round(dist, 2)
        if dist <= 0:
            gaps.append("house level is at or above the last close; the advisory predates the latest move")
        elif band and band.get("stop_min_pct") is not None and band.get("stop_max_pct") is not None and not (
                band["stop_min_pct"] - 1.0 <= dist <= band["stop_max_pct"] + 1.0):
            gaps.append(f"house level is {dist:.1f}% below the last close, outside the current policy band")
        if shares is not None:
            rec["usd_at_risk"] = round(max(0.0, last - level) * shares, 2)
    return rec, gaps


def comparison(rec: dict, broker: dict, *, last: Optional[float]) -> str:
    h, b, state = rec.get("level"), broker.get("level"), broker.get("state")
    if state == "filled":
        note = next((a.get("note") for a in broker.get("accounts") or [] if a.get("category") == "filled" and a.get("note")),
                    None)
        if note:
            return f"The broker {note}."
        return (f"The broker stop filled{(' on ' + str(broker.get('as_of'))[:10]) if broker.get('as_of') else ''}; "
                "holdings may not have synced yet.")
    if b is not None and state in ("active", "resting", "unknown") and h:
        diff = (b - h) / h * 100
        word = "above" if diff > 0 else "below"
        where = "at" if abs(diff) < 0.05 else f"{abs(diff):.1f}% {word}"
        kind = {"active": "Active broker stop", "resting": "Resting broker stop (pending activation)",
                "unknown": "Broker stop (state not reported)"}[state]
        return f"{kind} {_money(b)} sits {where} the house level {_money(h)}."
    if b is not None and state in ("active", "resting", "unknown"):
        return f"Broker stop {_money(b)} ({state}); no current house level to compare."
    if h and last:
        return f"No resting broker stop; the house level is {_money(h)}, {(last - h) / last * 100:.1f}% below the last close."
    if h:
        return f"No resting broker stop; the house level is {_money(h)}."
    return "No resting broker stop and no current house level."


def stop_tile(rec: dict, broker: dict) -> dict:
    """Server-supplied Stop verdict tile (prospectusModel.verdictTiles honours blocks.verdict_tiles.stop)."""
    state, b, h = broker.get("state"), broker.get("level"), rec.get("level")
    house = f"house {_money(h)}" if h is not None else None
    if state in ("active", "resting", "unknown") and b is not None:
        label = {"active": "active", "resting": "resting, pending activation", "unknown": "state not reported"}[state]
        return {"value": _money(b), "sub": " · ".join(x for x in (label, house) if x),
                "tone": "success" if state == "active" else "warning"}
    if state == "filled":
        return {"value": "Filled", "sub": " · ".join(x for x in ("broker stop filled", house) if x), "tone": "warning"}
    if broker.get("category") == "planned" and b is not None:
        return {"value": _money(b), "sub": " · ".join(x for x in ("planned level, no broker order", house) if x),
                "tone": "warning"}
    if broker.get("gap"):
        return {"value": "Unknown", "sub": " · ".join(x for x in ("broker stop store unreadable", house) if x),
                "tone": "neutral"}
    return {"value": "None", "sub": " · ".join(x for x in ("no broker stop on record", house) if x), "tone": "danger"}


def build(sources: Any, bundle: Any, *, holding: Optional[dict], cfg: dict | None = None,
          now: Optional[datetime] = None, regime: Any = None) -> dict:
    """Compute blocks.stop_plan (and the Stop tile and facts) for one bundle. Never raises."""
    now = now or datetime.now(timezone.utc)
    if bundle.scope != "holding" or not holding:
        return {"not_applicable": "not held"}
    sym = bundle.symbol
    conf = (cfg or {}).get("stop_plan") or {}
    if regime is None:
        # The house regime is a DB read: only the production reader takes it; fixtures and tests stay neutral.
        from .inputs import HouseSources
        regime = getattr(sources, "stop_regime", None) or ("live" if isinstance(sources, HouseSources) else "neutral")
    try:
        last = next((f.get("value") for f in bundle.facts if f.get("label") == "Last close"), None)
        shares = _f(holding.get("shares"))
        atr = _f((bundle.blocks.get("risk_technicals") or {}).get("atr20"))
        band = policy_band(sym, atr_pct=(atr / last * 100) if atr and last else None,
                           position_value=_f(holding.get("market_value")), regime=regime)
        rec, gaps = recommended_view(read_advisory(sources, sym), band, last=last, shares=shares, now=now,
                                     max_age_days=float(conf.get("advisory_max_age_days", ADVISORY_MAX_AGE_DAYS)))
        label_fn = _mod("lib.account_display", "scripts.lib.account_display").account_label
        broker_rows = read_broker_rows(sources, sym)
        broker = broker_view(broker_rows, read_planned(sources), list(holding.get("accounts") or []),
                             sym, now=now, label_fn=label_fn, fills=read_fills(sources, broker_rows))
    except Exception as exc:  # noqa: BLE001 - the stop plan never blocks the prospectus
        return {"recommended": {"level": None, "method": None, "distance_pct": None, "usd_at_risk": None,
                                "policy": POLICY, "as_of": None},
                "broker": {"level": None, "state": "unknown", "as_of": None, "source": BROKER_SOURCE},
                "comparison": "Stop plan unavailable.", "advisory": ADVISORY,
                "gaps": [f"stop plan failed: {type(exc).__name__}"]}
    if broker.get("gap"):
        gaps.append(broker["gap"])
    compare = comparison(rec, broker, last=last)
    if broker.get("other_accounts"):
        compare += f" Other accounts: {broker['other_accounts']}."
    plan = {"recommended": rec, "broker": broker, "comparison": compare,
            "advisory": ADVISORY, "gaps": gaps}
    _facts(bundle, plan)
    tile = stop_tile(rec, broker)
    if broker.get("other_accounts"):
        tile["sub"] = f"{tile['sub']} · other accounts: {broker['other_accounts']}"
    bundle.blocks.setdefault("verdict_tiles", {})["stop"] = tile
    return plan


def _facts(bundle: Any, plan: dict) -> None:
    """The level, distance, dollars and state as facts, so the writer can cite them and never derive them."""
    rec, broker = plan["recommended"], plan["broker"]
    src = f"house stop policy: {POLICY}"
    bundle.add("stop_plan", "House recommended stop level (advisory)", value=rec.get("level"), unit="$", source=src,
               as_of=rec.get("as_of"))
    bundle.add("stop_plan", "House recommended stop distance below last close %", value=rec.get("distance_pct"),
               unit="%", source="derived: last close vs house level", as_of=rec.get("as_of"))
    bundle.add("stop_plan", "Dollars at risk at the house stop $", value=rec.get("usd_at_risk"), unit="$",
               source="derived: shares held × (last close − house level)", as_of=rec.get("as_of"))
    bundle.add("stop_plan", "House stop method", text=rec.get("method"), source=src, as_of=rec.get("as_of"))
    band = rec.get("band") or {}
    if band.get("stop_min_pct") is not None:
        bundle.add("stop_plan", "House stop policy band low % below", value=band["stop_min_pct"], unit="%", source=src)
        bundle.add("stop_plan", "House stop policy band high % below", value=band["stop_max_pct"], unit="%", source=src)
    bundle.add("stop_plan", "Broker stop state", text=f"{broker.get('state')}: {plan['comparison']}",
               source=broker.get("source") or BROKER_SOURCE, as_of=broker.get("as_of"))


def stop_plan_table(doc: dict) -> list[dict]:
    """The stop plan as one plain table for the HTML / PDF / DOCX renderers (tables.py shape). Holdings only."""
    plan = (doc.get("blocks") or {}).get("stop_plan") or {}
    if not plan or plan.get("not_applicable"):
        return []
    rec, broker = plan.get("recommended") or {}, plan.get("broker") or {}
    band = rec.get("band") or {}
    pct = (lambda v: "n/a" if v is None else f"{v:.1f}%")
    rows = [["House recommended stop", _money(rec.get("level")), rec.get("method") or "n/a"],
            ["Distance below last close", pct(rec.get("distance_pct")), "from the last close in this report"],
            ["Dollars at risk at the house stop", _money(rec.get("usd_at_risk")), "shares held × (last close − house level)"],
            ["Broker stop", _money(broker.get("level")), f"state: {broker.get('state') or 'unknown'}"]]
    if band.get("stop_min_pct") is not None:
        lv = band.get("levels") or [None, None]
        rows.append(["Policy band", f"{band['stop_min_pct']:g}–{band['stop_max_pct']:g}% below",
                     f"{band.get('label') or band.get('family')}: {_money(lv[0])}–{_money(lv[1])}"])
    note = " ".join(x for x in [plan.get("comparison"), plan.get("advisory"), "; ".join(plan.get("gaps") or [])] if x)
    return [{"id": "stop_plan", "title": "Stop plan · house policy vs broker", "columns": ["Measure", "Value", "Basis"],
             "rows": rows, "note": note}]


__all__ = ["ADVISORY", "POLICY", "build", "broker_view", "comparison", "policy_band", "read_advisory",
           "read_broker_rows", "recommended_view", "stop_plan_table", "stop_tile"]
