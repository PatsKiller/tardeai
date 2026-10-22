"""CIO prospect shadow builder — assembles one prospect per security_guid from the existing stores.

AGENTS.md §26 (18.0.0, ACTIVE); docs/architecture/CIO_PROSPECT_DATA_FOUNDATION.md §7 P1 "Shadow".

The prospect is ``InstrumentRecord@v1`` extended (§13.5): each one is minted in memory with
``cio_instrument_record.new_record`` and filled ONLY through ``apply_prospect`` — the same rail the
single writer uses — so the shadow output is exactly what the single writer (the record store's prospect upsert)
would persist. This module never calls the store: it writes nothing. Persisting the shadow artifact is
the CLI's job (``scripts/cio_prospect_shadow_build.py --write-shadow``), and only outside the shadow
stage.

Inputs (every one read-only; a missing input is reported, never invented):

  file   data/cio/cio_opportunity_projection.json   opportunity curator (stance, conviction, factors)
  file   data/cio/cio_theses_projection.json        CIOThesisStore heads (thesis stance, version)
  file   data/cio/security_research_spine.jsonl     SecurityResearchSpine@v1 (NO SILOS; last row/symbol)
  file   data/cio/cio_instrument_records.jsonl      InstrumentRecord@v1 tips (subject_key kind)
  file   data/runtime/reentry_decision_desk_latest.json   re-entry desk snapshot (never build_decision_desk)
  file   data/runtime/hermes_watchlist_lifecycle.json     Hermes lifecycle (stage, conviction_score)
  file   data/runtime/trade_ai_cache.json            scanner verdicts (source_observations)
  reader data_broker.positions_context (holdings through lib/portfolio_positions, the approved holdings
         accessor) — never positions_current (no approved reader batch) and never the Watch held reader, whose
         import closure reaches positions_sync / broker transport
  db     decision_packets, cio_decisions, cio_entry_states, watchlist_items, operator_starred_symbols —
         only when a read-only ``db_query`` is injected (bulk DISTINCT ON SELECTs; no positions_current)

Identity: ``identity_carriage.resolve_security_identity`` (lookup only, never mints). A symbol without a
CONFIRMED registry GUID gets no prospect and is listed as "identity unresolved" (§7, §26.1).

Conflicts (§26.5) are recorded with both values, both sources and both times — never resolved here.

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0: no field carries a size, order, stop or weight; the
re-entry / entry-state rows' stop/target/entry levels are never copied (only reference levels from the
opportunity's risk/reward ladder, labelled as information).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from scripts.lib import cio_instrument_record as ir
from scripts.lib import cio_prospect_lifecycle as lcm
from scripts.lib import cio_prospect_watchlist_rules as wl_rules

SCHEMA = "CioProspectShadowBuild@v1"
BUILDER = "scripts/lib/cio_prospect_builder.py"
PROSPECT_SURFACE = "cio_prospect"
MARKET_STALE_H = 0.5          # registry row cio_prospect stale_after_hours
CLOSED_STALE_H = 26.0         # registry row cio_prospect stale_after_hours_closed

# Conviction component weights (reproducible: conviction = weighted mean of the components present).
COMPONENT_WEIGHTS = {
    "opportunity_score": 0.45,   # the CIO curator's own conviction (cio_opportunity_projection)
    "unified_edge": 0.15,        # unified_edge_score.edge_from_trade_context, persisted with its inputs
    "hermes_score": 0.15,        # Hermes lifecycle conviction_score
    "thesis_quality": 0.15,      # SecurityResearchSpine thesis.conviction (0-1 -> 0-100)
    "scanner_score": 0.10,       # trade_ai_scans score (db only)
}
NOT_WIRED_COMPONENTS = {
    "fused_score": "fused_signals has no GUID and no registry domain yet (proposed row fused_signals)",
    "catalyst_grade": "Gate 2 Momentum Core grade is not produced yet (catalyst_events proposed)",
    "regime_fit": "no per-security regime-fit producer exists",
}

FILES = {
    "opportunity": "data/cio/cio_opportunity_projection.json",
    "theses": "data/cio/cio_theses_projection.json",
    "spine": "data/cio/security_research_spine.jsonl",
    "instrument_records": "data/cio/cio_instrument_records.jsonl",
    "reentry": "data/runtime/reentry_decision_desk_latest.json",
    "hermes": "data/runtime/hermes_watchlist_lifecycle.json",
    "scanner_cache": "data/runtime/trade_ai_cache.json",
    "assessment_versions": "data/cio/cio_opportunity_assessments.jsonl",
    "cio_events": "data/cio/cio_events.jsonl",
    "indicators": "data/portfolios/state/data_broker/indicator_snapshot.json",
}

_BUY = {"ADD", "BUY", "BUY_SETUP", "RE_ENTER", "STRONG_BUY", "ACCUMULATE", "BUY_READY", "ENTRY_NEAR", "LONG"}
_HOLD = {"HOLD", "MAINTAIN", "KEEP"}
_WATCH = {"WATCH", "MONITOR", "NEUTRAL", "WAIT", "NOT_YET"}
_SELL = {"TRIM", "EXIT", "SELL", "AVOID", "REDUCE", "TRIM_REVIEW", "EXIT_REVIEW", "INVALIDATED", "BLOCKED"}


def posture(value: Any) -> Optional[str]:
    """Normalise a stance/action from any store to buy / hold / watch / sell (None if unknown)."""
    v = str(value or "").strip().upper().replace(" ", "_").replace("-", "_")
    if not v:
        return None
    for name, bag in (("buy", _BUY), ("hold", _HOLD), ("watch", _WATCH), ("sell", _SELL)):
        if v in bag:
            return name
    return None


def disagree(a: Any, b: Any) -> bool:
    """Two stances disagree when both are known and their postures differ — except hold vs watch, which is the
    same "no new action" posture seen from a held and a watched book (not a conflict worth an operator's time)."""
    pa, pb = posture(a), posture(b)
    return bool(pa and pb and pa != pb and {pa, pb} != {"hold", "watch"})


def _ts(v: Any) -> Optional[datetime]:
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.astimezone(timezone.utc).isoformat() if dt else None


def market_open(now: datetime) -> bool:
    """US equity regular session, Mon-Fri 09:30-16:00 America/New_York (holidays not modelled)."""
    try:
        from zoneinfo import ZoneInfo
        et = now.astimezone(ZoneInfo("America/New_York"))
    except Exception:  # noqa: BLE001
        et = now.astimezone(timezone(timedelta(hours=-4)))
    if et.weekday() >= 5:
        return False
    minutes = et.hour * 60 + et.minute
    return 9 * 60 + 30 <= minutes < 16 * 60


# ── input loading (read-only) ───────────────────────────────────────────────


def _read_json(path: Path) -> tuple[Optional[Any], Optional[str]]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except FileNotFoundError:
        return None, "missing"
    except (OSError, ValueError) as exc:
        return None, f"unreadable:{type(exc).__name__}"


def _last_rows_by(path: Path, key: Callable[[dict], Optional[str]]) -> tuple[dict[str, dict], Optional[str]]:
    out: dict[str, dict] = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                k = key(row)
                if k:
                    out[k] = row
    except FileNotFoundError:
        return {}, "missing"
    except OSError as exc:
        return {}, f"unreadable:{type(exc).__name__}"
    return out, None


def _source(name: str, rel: str, rows: dict, as_of: Any, err: Optional[str]) -> dict[str, Any]:
    return {"name": name, "path": rel, "rows": rows, "count": len(rows), "as_of": as_of,
            "status": "ok" if err is None else err}


def load_file_inputs(state_root: Path) -> dict[str, dict[str, Any]]:
    root = Path(state_root)
    out: dict[str, dict[str, Any]] = {}

    doc, err = _read_json(root / FILES["opportunity"])
    items = {str(k).upper(): v for k, v in ((doc or {}).get("items") or {}).items() if isinstance(v, dict)}
    out["opportunity"] = _source("opportunity", FILES["opportunity"], items, (doc or {}).get("as_of"), err)

    doc, err = _read_json(root / FILES["theses"])
    heads: dict[str, dict] = {}
    for tid, head in ((doc or {}).get("current") or {}).items():
        if not isinstance(head, dict) or not str(tid).startswith("symbol_"):
            continue
        syms = head.get("linked_symbols") or []
        sym = str(syms[0] if syms else "").upper() or str(tid)[len("symbol_"):].upper()
        if sym.startswith("S_"):
            sym = sym[2:]
        heads[sym] = {**head, "thesis_id": tid}
    out["theses"] = _source("theses", FILES["theses"], heads, (doc or {}).get("updated_ts"), err)

    spine, err = _last_rows_by(root / FILES["spine"], lambda r: str(r.get("symbol") or "").upper() or None)
    out["spine"] = _source("spine", FILES["spine"], spine,
                           max((str(r.get("as_of") or "") for r in spine.values()), default=None), err)

    tips, err = _last_rows_by(root / FILES["instrument_records"], lambda r: str(r.get("subject_key") or "") or None)
    by_sym: dict[str, dict] = {}
    for key, row in tips.items():
        kind, name = ir.parse_subject_key(key)
        if kind in ("HELD", "EXIT", "WATCH") and name:
            prev = by_sym.get(name.upper())
            if prev is None or str(row.get("updated_ts") or "") > str(prev.get("updated_ts") or ""):
                by_sym[name.upper()] = row
    out["instrument_records"] = _source("instrument_records", FILES["instrument_records"], by_sym,
                                        max((str(r.get("updated_ts") or "") for r in by_sym.values()), default=None),
                                        err)

    doc, err = _read_json(root / FILES["reentry"])
    rows = (doc or {}).get("rows") or ((doc or {}).get("data") or {}).get("rows") or []
    re_rows = {str(r.get("symbol") or "").upper(): r for r in rows if isinstance(r, dict) and r.get("symbol")}
    out["reentry"] = _source("reentry", FILES["reentry"], re_rows, (doc or {}).get("computed_at"), err)

    doc, err = _read_json(root / FILES["hermes"])
    hs = {str(k).upper(): v for k, v in ((doc or {}).get("symbols") or {}).items() if isinstance(v, dict)}
    out["hermes"] = _source("hermes", FILES["hermes"], hs, (doc or {}).get("updated_at"), err)

    doc, err = _read_json(root / FILES["scanner_cache"])
    scans: dict[str, dict] = {}
    for v in (doc or {}).values() if isinstance(doc, dict) else []:
        if isinstance(v, list):
            for r in v:
                if isinstance(r, dict) and r.get("symbol") and r.get("decision"):
                    sym = str(r["symbol"]).upper()
                    if str(r.get("observed_at") or "") >= str((scans.get(sym) or {}).get("observed_at") or ""):
                        scans[sym] = r
    # position lifecycle inputs (operator 2026-10-22, NAVN): the curator's versioned assessments (what Home and
    # Telegram showed, when) and the cio_entry_state signals (the HIGH CONVICTION ENTRY card source)
    versions: dict[str, list[dict]] = {}
    signals: dict[str, list[dict]] = {}
    err_v = err_e = None
    try:
        with open(root / FILES["assessment_versions"], encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("symbol"):
                    versions.setdefault(str(r["symbol"]).upper(), []).append(r)
    except FileNotFoundError:
        err_v = "missing"
    except OSError as exc:
        err_v = f"unreadable:{type(exc).__name__}"
    try:
        with open(root / FILES["cio_events"], encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"watch.new_signal"' not in line or "cio_entry_state" not in line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                sym = str((r.get("payload") or {}).get("symbol") or "").upper()
                if sym:
                    signals.setdefault(sym, []).append(r)
    except FileNotFoundError:
        err_e = "missing"
    except OSError as exc:
        err_e = f"unreadable:{type(exc).__name__}"
    out["assessment_versions"] = _source("assessment_versions", FILES["assessment_versions"], versions,
                                         max((v[-1].get("written_at") or "" for v in versions.values()), default=None),
                                         err_v)
    out["entry_signals"] = _source("entry_signals", FILES["cio_events"], signals,
                                   max((s[-1].get("timestamp") or "" for s in signals.values()), default=None), err_e)
    doc, err = _read_json(root / FILES["indicators"])
    ind = {str(k).upper(): v for k, v in ((doc or {}).get("by_symbol") or {}).items() if isinstance(v, dict)}
    out["indicators"] = _source("indicators", FILES["indicators"], ind, (doc or {}).get("computed_at"), err)

    out["scanner"] = _source("scanner", FILES["scanner_cache"], scans,
                             (doc or {}).get("latest_run_timestamp") if isinstance(doc, dict) else None, err)
    return out


DB_QUERIES = {
    "decision_packets": (
        "SELECT DISTINCT ON (upper(symbol)) upper(symbol) AS symbol, generated_at, actionable, thesis_state, "
        "no_trade_valid, data_quality FROM decision_packets WHERE superseded_by IS NULL "
        "ORDER BY upper(symbol), generated_at DESC"),
    "cio_decisions": (
        "SELECT DISTINCT ON (upper(symbol)) upper(symbol) AS symbol, action, action_class, status, priority, "
        "confidence_calibrated, created_at, expires_at FROM cio_decisions ORDER BY upper(symbol), created_at DESC"),
    "entry_states": (
        "SELECT DISTINCT ON (upper(symbol)) upper(symbol) AS symbol, state, evaluated_at FROM cio_entry_states "
        "ORDER BY upper(symbol), evaluated_at DESC"),
    "scanner_db": (
        "SELECT DISTINCT ON (upper(symbol)) upper(symbol) AS symbol, score, grade, decision, scanned_at "
        "FROM trade_ai_scans WHERE scanned_at > now() - interval '7 days' ORDER BY upper(symbol), scanned_at DESC"),
    "watchlist_items": (
        "SELECT upper(symbol) AS symbol, source, status, hermes_composite_score, first_seen_at, updated_at "
        "FROM watchlist_items WHERE status IN ('active', 'queued', 'researching', 'researched', 'review', 'promoted')"),
    "starred": "SELECT upper(symbol) AS symbol, created_at FROM operator_starred_symbols",
}
_DB_TIME = {"decision_packets": "generated_at", "cio_decisions": "created_at", "entry_states": "evaluated_at",
            "scanner_db": "scanned_at", "watchlist_items": "updated_at", "starred": "created_at"}


# List-valued, read-only lifecycle inputs (per symbol, many rows). schwab_round_trips is the journal's round-trip
# store (the learning-loop linker reads it); trade_transactions (proposed domain `transactions`) and stop_lifecycle
# (proposed domain `broker_stops`, an observation) are read only, never positions_current. A reader batch for this
# lane is PROPOSED in docs/architecture/CIO_PROSPECT_DATA_FOUNDATION.md §11 — the operator grants it (§17).
LIFECYCLE_QUERIES = {
    "round_trips": (
        "SELECT 'srt:' || s.id AS round_trip_key, s.account, upper(s.symbol) AS symbol, s.entry_time, s.exit_time, "
        "s.entry_price, s.exit_price, s.net_pnl, s.classification, tc.stop_used AS journal_stop "
        "FROM schwab_round_trips s LEFT JOIN trade_closed tc ON tc.dedupe_key = 'srt:' || s.id "
        "WHERE s.entry_time IS NOT NULL AND s.exit_time > now() - interval '45 days' "
        "AND s.basis_status IS NULL AND s.canary IS NOT TRUE ORDER BY s.exit_time"),
    "fills": (
        "SELECT upper(symbol) AS symbol, account, lower(action) AS action, price AS fill_price, trade_date, "
        "trade_time, dedupe_key FROM trade_transactions WHERE trade_date > now() - interval '120 days' "
        "AND (lower(action) LIKE 'buy%%' OR lower(action) LIKE 'sell%%') ORDER BY trade_date, trade_time"),
    "stop_history": (
        "SELECT upper(symbol) AS symbol, account, order_id, order_type, status, stop_price, snapshot_at, id AS seq "
        "FROM stop_lifecycle WHERE stop_price IS NOT NULL ORDER BY symbol, id"),
    "rec_links": (
        "SELECT l.round_trip_key, l.rec_id, l.rec_source, l.link_confidence, l.origin, l.plan_stop, l.plan_target, "
        "l.r_multiple, l.planned_rr FROM trade_recommendation_links l "
        "WHERE to_regclass('public.trade_recommendation_links') IS NOT NULL"),
}


def load_lifecycle_inputs(db_query: Optional[Callable[..., list[dict]]],
                          captured: Optional[dict[str, Any]] = None) -> dict[str, dict[str, Any]]:
    """Per-symbol lists for the lifecycle. ``captured`` (``--captured-inputs``) supplies the same rows captured
    read-only elsewhere (a report run where this process may not open the database), labelled as such."""
    out: dict[str, dict[str, Any]] = {}
    for name, sql in LIFECYCLE_QUERIES.items():
        rows: Optional[list[dict]] = None
        status = "not_read (no read-only db_query injected)"
        path = f"db:{name}"
        if captured is not None and name in captured:
            rows, status, path = list(captured[name] or []), "ok", f"captured:{name}"
        elif db_query is not None:
            try:
                rows, status = list(db_query(sql) or []), "ok"
            except Exception as exc:  # noqa: BLE001
                status = f"error:{type(exc).__name__}"
        by: dict[str, list[dict]] = {}
        key = "round_trip_key" if name == "rec_links" else "symbol"
        for r in rows or []:
            k = str(r.get(key) or "")
            if k:
                by.setdefault(k.upper() if key == "symbol" else k, []).append(dict(r))
        out[name] = _source(name, path, by, None, status)
    bars = (captured or {}).get("bars")
    out["bars"] = _source("bars", "captured:bars" if bars is not None else "db:ticker_prices",
                          {str(k).upper(): v for k, v in (bars or {}).items()}, None,
                          "ok" if bars is not None else ("deferred" if db_query is not None else
                                                         "not_read (no read-only db_query injected)"))
    return out


BARS_SQL = ("SELECT price_date AS time, close_price AS close FROM ticker_prices WHERE upper(symbol) = %s "
            "AND price_date > now() - interval '120 days' ORDER BY price_date")


def load_db_inputs(db_query: Optional[Callable[[str], list[dict]]]) -> dict[str, dict[str, Any]]:
    """Bulk read-only SELECTs through an injected ``db_query(sql) -> rows``. No positions_current."""
    out: dict[str, dict[str, Any]] = {}
    for name, sql in DB_QUERIES.items():
        if db_query is None:
            out[name] = _source(name, f"db:{name}", {}, None, "not_read (no read-only db_query injected)")
            continue
        try:
            rows = db_query(sql) or []
        except Exception as exc:  # noqa: BLE001
            out[name] = _source(name, f"db:{name}", {}, None, f"error:{type(exc).__name__}")
            continue
        by = {str(r.get("symbol") or "").upper(): dict(r) for r in rows if r.get("symbol")}
        tcol = _DB_TIME[name]
        newest = max((str(r.get(tcol) or "") for r in by.values()), default=None)
        out[name] = _source(name, f"db:{name}", by, newest, None)
    return out


def _positions_context_held(state_root: Path) -> dict:
    """Held set through the registered ``positions_context`` projection (the reader the architecture names for
    stage ``held``), which reads holdings through ``lib/portfolio_positions`` — the approved holdings_accounts
    accessor. Never positions_current (an unapproved reader batch), never the Watch held reader (its closure
    reaches positions_sync, i.e. broker modules, which a dispatched lane must not import)."""
    try:
        from scripts.lib import portfolio_positions as pp
        from scripts.lib.data_broker.positions_context import get_positions_context
    except ImportError:  # scripts/ (not the repo root) on sys.path
        from lib import portfolio_positions as pp  # type: ignore
        from lib.data_broker.positions_context import get_positions_context  # type: ignore
    doc = pp.load_store() or {}
    syms = sorted({str(h.get("symbol") or "").upper() for h in doc.get("holdings") or [] if isinstance(h, dict)} - {""})
    ctx = get_positions_context(None, syms) if syms else {}
    return {"symbols": {s for s, o in ctx.items() if o.get("owned")},
            "source": "positions_context (holdings_accounts via lib.portfolio_positions)",
            "as_of": doc.get("updated_at") or doc.get("as_of") or doc.get("data_as_of")}


def load_held(state_root: Path, held_reader: Optional[Callable[[], dict]] = None) -> dict[str, Any]:
    """The held set through the registered positions projection (never positions_current directly)."""
    if held_reader is None:
        def held_reader() -> dict:
            return _positions_context_held(Path(state_root))
    try:
        h = held_reader() or {}
    except Exception as exc:  # noqa: BLE001
        return {"symbols": set(), "source": "unavailable", "status": f"error:{type(exc).__name__}", "as_of": None}
    return {"symbols": {str(s).upper() for s in h.get("symbols") or ()}, "source": h.get("source"),
            "as_of": h.get("as_of"), "stale": h.get("stale"), "status": "ok"}


# ── assembly ────────────────────────────────────────────────────────────────


def _comp(value: Any, *, source: str, evidence_at: Any, weight: float, scale: float = 1.0,
          detail: Any = None) -> dict[str, Any]:
    try:
        v = None if value is None else round(max(0.0, min(100.0, float(value) * scale)), 2)
    except (TypeError, ValueError):
        v = None
    out = {"value": v, "weight": weight, "source": source, "evidence_at": evidence_at}
    if detail is not None:
        out["detail"] = detail
    return out


def _conflict(field: str, a: tuple[Any, str, Any], b: tuple[Any, str, Any], note: str = "") -> dict[str, Any]:
    out = {"field": field, "values": [{"value": a[0], "source": a[1], "at": a[2]},
                                      {"value": b[0], "source": b[1], "at": b[2]}],
           "resolved": False}
    if note:
        out["note"] = note
    return out


SETUP_MIN_CONVICTION = 70.0   # config/opportunity_conviction.yaml add_if / re_enter_if bar
SETUP_MIN_RR = 2.0


def _setup_forming(opp: Optional[dict[str, Any]]) -> bool:
    """The curator sees a new-position or add-on setup clearing the add bar (conviction ≥ 70, R:R ≥ 2)."""
    if not opp or opp.get("type") not in ("new_position", "add_on"):
        return False
    try:
        return (float(opp.get("conviction") or 0) >= SETUP_MIN_CONVICTION
                and float((opp.get("risk_reward") or {}).get("rr") or 0) >= SETUP_MIN_RR)
    except (TypeError, ValueError):
        return False


def rank_key(row: dict[str, Any]) -> tuple:
    """Shadow ranking: prospects the CIO curator assessed (an opportunity_score) rank first, by conviction.

    A conviction built from one peripheral component (e.g. a Hermes score alone) is reproducible but
    thin; it is shown, never ranked above a CIO-assessed security. Ties: symbol.
    """
    comps = row.get("conviction_components") or {}
    assessed = (comps.get("opportunity_score") or {}).get("value") is not None
    return (not assessed, -float(row.get("conviction") or 0.0), str(row.get("symbol") or ""))


def _home_bar() -> dict[str, Any]:
    import yaml

    try:
        cfg = yaml.safe_load(OPPORTUNITY_CONFIG.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        cfg = {}
    return (cfg.get("presets") or {}).get("top5") or {"min_conviction": 80, "min_rr": 2.0, "min_coverage": 0.8,
                                                       "limit": 5}


def lifecycle_for(sym: str, inputs: dict[str, dict[str, Any]], *, is_held: bool, held: dict[str, Any],
                  identity: dict[str, Any], opp: Optional[dict], thesis: Optional[dict], decision: Optional[dict],
                  now: datetime) -> Optional[dict[str, Any]]:
    """The position lifecycle on the prospect (operator 2026-10-22, NAVN): origin, fills, observed stops,
    excursion, exit cause, post-exit review, re-entry advice — or None when the security has no position history
    in the window. A closed round trip newer than the last buy fill means the position is closed even when the
    holdings file still lists it; that disagreement is recorded as a conflict, never resolved silently (§26.5)."""
    rows = lambda name: (inputs.get(name) or {}).get("rows", {}).get(sym) or []  # noqa: E731
    rts = sorted(rows("round_trips"), key=lambda r: str(r.get("exit_time") or ""))
    fills = rows("fills")
    buys = sorted((f for f in fills if str(f.get("action") or "").startswith("buy")),
                  key=lambda f: str(f.get("trade_time") or f.get("trade_date") or ""))
    last_rt = rts[-1] if rts else None
    last_buy_at = lcm._ts(buys[-1].get("trade_time") or buys[-1].get("trade_date")) if buys else None
    closed = bool(last_rt and lcm._ts(last_rt.get("exit_time")) and (
        last_buy_at is None or lcm._ts(last_rt.get("exit_time")) >= last_buy_at))
    if last_rt and closed and now - lcm._ts(last_rt["exit_time"]) > timedelta(days=lcm.REENTRY_WATCH_DAYS):
        closed, last_rt = False, None
    if not closed and not is_held:
        return None
    if closed:
        rt = dict(last_rt)
    elif buys:
        b = buys[-1]
        rt = {"round_trip_key": f"open:{sym}:{b.get('dedupe_key') or b.get('trade_date')}", "symbol": sym,
              "account": b.get("account"), "entry_time": b.get("trade_time") or b.get("trade_date"),
              "entry_price": b.get("fill_price"), "exit_time": None, "exit_price": None}
    else:
        return {"stage": None, "conflicts": [], "events": [], "origin": None, "review": None, "advice": None,
                "life": {"status": "open", "entry_fill": None,
                         "note": "held, but no buy fill in the window this lane read (fills not read or older)"}}
    acct = rt.get("account")
    versions = rows("assessment_versions")
    recs = lcm.recommendations_from_records(sym, versions, rows("entry_signals"))
    link = ((inputs.get("rec_links") or {}).get("rows") or {}).get(str(rt.get("round_trip_key") or ""))
    origin = lcm.attribute_origin(rt, recs, link_row=(link[0] if link else None), home_bar=_home_bar(),
                                  decisions=[decision] if decision else [])
    stop_rows = [r for r in rows("stop_history") if not acct or not r.get("account") or r.get("account") == acct]
    stops = lcm.stop_path(stop_rows)
    bars = list(rows("bars"))
    entry_at, exit_at = rt.get("entry_time"), rt.get("exit_time")
    exc = lcm.excursion(rt.get("entry_price"), entry_at, exit_at or now, bars)
    t0, t1 = lcm._ts(entry_at), lcm._ts(exit_at) or now
    while_held = []
    for v in sorted(versions, key=lambda v: str(v.get("written_at") or "")):
        at = lcm._ts(v.get("written_at"))
        if at and t0 and t0 <= at <= t1:
            a = v.get("assessment") or {}
            while_held.append({"at": lcm._iso(at), "conviction": a.get("conviction"), "stance": a.get("stance"),
                               "rank": a.get("rank"), "record": f"{FILES['assessment_versions']} {sym}:v{v.get('version')}",
                               "changes": v.get("change_reasons")})
    life: dict[str, Any] = {
        "schema": lcm.SCHEMA, "status": "closed" if closed else "open", "round_trip_key": rt.get("round_trip_key"),
        "account": acct, "entry_fill": {"at": lcm._iso(entry_at), "price": lcm._f(rt.get("entry_price"))},
        "fills": [{"at": lcm._iso(f.get("trade_time") or f.get("trade_date")), "side": str(f.get("action") or ""),
                   "fill_price": lcm._f(f.get("fill_price")), "ref": f.get("dedupe_key")}
                  for f in fills if (lcm._ts(f.get("trade_time") or f.get("trade_date")) or now) >= (t0 or now)],
        "observed_stops": stops, "excursion": exc, "conviction_while_held": while_held,
        "hold_days": None if not t0 else (t1.date() - t0.date()).days,
    }
    review = advice = None
    conflicts: list[dict[str, Any]] = []
    stage = stage_phase = stance = None
    why: dict[str, Any] = {}
    plan_target = (origin.get("linkage") or {}).get("plan_target")
    if closed:
        life["exit_fill"] = {"at": lcm._iso(exit_at), "price": lcm._f(rt.get("exit_price"))}
        life["exit_cause"] = lcm.classify_exit(rt.get("exit_price"), rt.get("entry_price"), stops, plan_target)
        ent_px, ex_px = rt.get("entry_price"), rt.get("exit_price")
        plan_inval = next((r.get("plan_stop") for r in sorted(recs, key=lambda r: r["created_at"], reverse=True)
                           if r["source"] == "cio_opportunity_curator" and lcm._ts(r["created_at"]) <= lcm._ts(entry_at)
                           and r.get("plan_stop") is not None), None)
        life["pnl"] = {"net_pnl_usd": lcm._f(rt.get("net_pnl")),
                       "pnl_pct": lcm._pct(lcm._f(ex_px), lcm._f(ent_px)),
                       "r_multiple": (origin.get("linkage") or {}).get("r_multiple"),
                       "r_basis": "linked plan_stop (learning-loop rule); null when the linked recommendation has none",
                       "r_on_initial_observed_stop": lcm.lk.r_multiple(ent_px, ex_px, stops.get("initial"))[0],
                       "r_on_plan_invalidation_at_entry": lcm.lk.r_multiple(ent_px, ex_px, plan_inval)[0],
                       "plan_invalidation_at_entry": plan_inval}
        review = lcm.post_exit_review(entry_price=rt.get("entry_price"), exit_price=rt.get("exit_price"),
                                      exit_at=exit_at, bars=bars, stops=stops, exc=exc, exit_cause=life["exit_cause"])
        latest = recs and max((r for r in recs if r["source"] == "cio_opportunity_curator"),
                              key=lambda r: r["created_at"], default=None)
        rk = (opp or {}).get("risk_reward") or {}
        ind = ((inputs.get("indicators") or {}).get("rows") or {}).get(sym) or {}
        advice = lcm.reentry_advice(
            symbol=sym, security_guid=identity["security_guid"], round_trip_key=rt.get("round_trip_key"),
            exit_price=rt.get("exit_price"), exit_at=exit_at, entry_price=rt.get("entry_price"),
            net_pnl=rt.get("net_pnl"), price=rk.get("current_price"), price_as_of=(opp or {}).get("as_of"),
            rsi=ind.get("rsi"), entry_zone=rk.get("entry_zone") or ([latest["entry_low"], latest["entry_high"]]
                                                                    if latest else None),
            resistance=None, conviction=(opp or {}).get("conviction"),
            thesis_status=(thesis or {}).get("status"), now=now)
        stage, stage_phase = lcm.stage_phase_for(exit_at, now)
        stance = "WATCH"
        why = {"source": "schwab_round_trips", "event": "exit_fill", "round_trip_key": rt.get("round_trip_key"),
               "at": lcm._iso(exit_at), "cause": life["exit_cause"]["class"]}
        if is_held:
            conflicts.append(_conflict(
                "held", ("held", f"positions[{held.get('source')}]", held.get("as_of")),
                ("closed", f"schwab_round_trips {rt.get('round_trip_key')} exit fill", lcm._iso(exit_at)),
                note="the round trip closed after the last buy fill but the holdings file still lists it"))
        if posture((opp or {}).get("stance")) in ("buy", "hold") and (opp or {}).get("position_status") == "owned":
            conflicts.append(_conflict(
                "stance_after_exit", ((opp or {}).get("stance"), "cio_opportunity_projection", (opp or {}).get("as_of")),
                ("exited", f"schwab_round_trips {rt.get('round_trip_key')}", lcm._iso(exit_at)),
                note="the curator still treats the position as owned"))
    events = lcm.lifecycle_events(identity["security_guid"], origin, life, review, advice)
    return {"stage": stage, "stage_phase": stage_phase, "stance": stance, "why": why, "origin": origin,
            "life": life, "review": review, "advice": advice, "conflicts": conflicts, "events": events}


def assemble(sym: str, inputs: dict[str, dict[str, Any]], held: dict[str, Any], identity: dict[str, Any],
             *, now: datetime, rules: dict[str, Any]) -> dict[str, Any]:
    """One prospect record (InstrumentRecord@v1 extended) for ``sym``, through ``apply_prospect``."""
    g = lambda name: (inputs.get(name) or {}).get("rows", {}).get(sym)  # noqa: E731
    opp, thesis, spine, irec = g("opportunity"), g("theses"), g("spine"), g("instrument_records")
    reentry, hermes, scan = g("reentry"), g("hermes"), g("scanner")
    packet, decision, entry = g("decision_packets"), g("cio_decisions"), g("entry_states")
    scan_db, wl_item, star = g("scanner_db"), g("watchlist_items"), g("starred")
    is_held = sym in held.get("symbols", set())
    held_src = f"positions[{held.get('source')}]"

    # ---- stage + stance (deterministic, named evidence) ----
    opp_stance = str((opp or {}).get("stance") or "").upper() or None
    entry_state = str((entry or {}).get("state") or "").upper() or None
    re_state = str(((reentry or {}).get("intel") or {}).get("state") or "").upper() or None
    if is_held:
        stage, why = "held", {"source": held_src, "at": held.get("as_of")}
    elif re_state in ("READY TO REVIEW", "NEAR ENTRY") or opp_stance == "RE_ENTER" or \
            (opp or {}).get("position_status") == "recently_sold":
        stage, why = "re_entry", {"source": "reentry_desk/opportunity", "state": re_state or opp_stance,
                                  "at": (inputs.get("reentry") or {}).get("as_of")}
    elif entry_state == "BUY_READY" or (packet or {}).get("actionable") is True:
        stage, why = "actionable", {"source": "cio_entry_states/decision_packets",
                                    "state": entry_state or "packet.actionable",
                                    "at": _iso(_ts((entry or {}).get("evaluated_at") or (packet or {}).get("generated_at")))}
    elif entry_state == "ENTRY_NEAR" or _setup_forming(opp):
        stage, why = "setup_forming", {"source": "cio_entry_states/opportunity",
                                       "state": entry_state or f"{(opp or {}).get('type')} conviction "
                                                               f"{(opp or {}).get('conviction')} rr "
                                                               f"{((opp or {}).get('risk_reward') or {}).get('rr')}",
                                       "at": (opp or {}).get("as_of")}
    else:
        stage, why = "watching", {"source": "default", "reason": "no setup evidence"}

    thesis_stance = str((thesis or {}).get("stance") or "").upper() or None
    if opp_stance:
        if is_held:
            stance = {"ADD": "ADD", "TRIM": "TRIM_REVIEW", "EXIT": "EXIT_REVIEW"}.get(opp_stance, "HOLD")
        else:
            stance = {"ADD": "BUY_SETUP", "RE_ENTER": "BUY_SETUP"}.get(opp_stance, "WATCH")
        stance_src = "opportunity_curator"
    elif thesis_stance:
        p = posture(thesis_stance)
        stance = {"buy": "BUY_SETUP", "hold": "HOLD" if is_held else "WATCH", "sell": "AVOID"}.get(p or "", "WATCH")
        stance_src = "cio_theses"
    else:
        stance, stance_src = ("HOLD" if is_held else "WATCH"), "default"

    # ---- position lifecycle (origin, fills, stops, exit, review, re-entry) ----
    lc = lifecycle_for(sym, inputs, is_held=is_held, held=held, identity=identity, opp=opp, thesis=thesis,
                       decision=decision, now=now)
    stage_phase = None
    if lc and lc.get("stage"):
        stage, why, stage_phase = lc["stage"], lc["why"], lc.get("stage_phase")
        stance, stance_src = lc["stance"], "position_lifecycle"

    # ---- conviction components ----
    W = COMPONENT_WEIGHTS
    comps: dict[str, Any] = {}
    opp_at = (opp or {}).get("as_of")
    comps["opportunity_score"] = _comp((opp or {}).get("conviction"), source="cio_opportunity_projection",
                                       evidence_at=opp_at, weight=W["opportunity_score"])
    if opp and opp.get("conviction") is not None:
        rr = ((opp.get("risk_reward") or {}).get("rr"))
        tech = ((opp.get("factors") or {}).get("technical") or {}).get("score")
        ctx = {"confidence": float(opp["conviction"]) / 100.0}
        if rr is not None:
            ctx["risk_reward"] = rr
        if tech is not None:
            ctx["technical_score"] = tech
        cat = (reentry or {}).get("catalyst") or {}
        if cat.get("verified") and cat.get("confidence") is not None:
            ctx["catalyst_strength"] = cat.get("confidence")
        comps["unified_edge"] = ir.unified_edge_component(ctx, source="opportunity+reentry inputs",
                                                          evidence_at=opp_at, weight=W["unified_edge"])
    else:
        comps["unified_edge"] = _comp(None, source="unified_edge_score", evidence_at=None, weight=W["unified_edge"],
                                      detail="no opportunity inputs")
    comps["hermes_score"] = _comp((hermes or {}).get("conviction_score"), source="hermes_watchlist_lifecycle",
                                  evidence_at=(inputs.get("hermes") or {}).get("as_of"), weight=W["hermes_score"])
    th = (spine or {}).get("thesis") or {}
    comps["thesis_quality"] = _comp(th.get("conviction"), source="security_research_spine",
                                    evidence_at=(spine or {}).get("as_of"), weight=W["thesis_quality"], scale=100.0)
    comps["scanner_score"] = _comp((scan_db or {}).get("score"), source="trade_ai_scans",
                                   evidence_at=_iso(_ts((scan_db or {}).get("scanned_at"))), weight=W["scanner_score"])
    for name, why_nw in NOT_WIRED_COMPONENTS.items():
        comps[name] = {"value": None, "weight": 0.0, "source": None, "evidence_at": None, "detail": why_nw}
    conviction = ir.conviction_from_components(comps)

    # ---- conflicts (shown, never resolved) ----
    conflicts: list[dict[str, Any]] = []
    t_at = (thesis or {}).get("published_ts") or (thesis or {}).get("updated_ts")
    if disagree(opp_stance, thesis_stance):
        conflicts.append(_conflict("stance", (opp_stance, "cio_opportunity_projection", opp_at),
                                   (thesis_stance.lower(), f"cio_theses {(thesis or {}).get('thesis_version')}", t_at)))
    sp_stance = str(th.get("stance") or "").upper() or None
    if disagree(opp_stance, sp_stance) and posture(sp_stance) != posture(thesis_stance):
        conflicts.append(_conflict("stance", (opp_stance, "cio_opportunity_projection", opp_at),
                                   (sp_stance, "security_research_spine", (spine or {}).get("as_of"))))
    if opp and opp.get("position_status") in ("owned", "not_owned", "watchlist") and \
            (opp.get("position_status") == "owned") != is_held:
        conflicts.append(_conflict("held", (opp.get("position_status"), "cio_opportunity_projection", opp_at),
                                   ("held" if is_held else "not_held", held_src, held.get("as_of"))))
    if irec:
        kind, _ = ir.parse_subject_key(str(irec.get("subject_key") or ""))
        if (kind == "WATCH" and is_held) or (kind == "HELD" and not is_held):
            conflicts.append(_conflict("subject_key_kind", (irec.get("subject_key"), "cio_instrument_records",
                                                            irec.get("updated_ts")),
                                       ("held" if is_held else "not_held", held_src, held.get("as_of")),
                                       note="the kind prefix splits one security in two; stage replaces it"))
    if entry_state and opp_stance and posture(entry_state) in ("buy", "sell") and posture(opp_stance) and \
            {posture(entry_state), posture(opp_stance)} == {"buy", "sell"}:
        conflicts.append(_conflict("entry_state", (entry_state, "cio_entry_states", _iso(_ts(entry.get("evaluated_at")))),
                                   (opp_stance, "cio_opportunity_projection", opp_at)))
    if decision and disagree(decision.get("action"), opp_stance):
        conflicts.append(_conflict("decision", (decision.get("action"), "cio_decisions",
                                                _iso(_ts(decision.get("created_at")))),
                                   (opp_stance, "cio_opportunity_projection", opp_at)))
    h_stage = str((hermes or {}).get("lifecycle_stage") or "").lower()
    if h_stage in ("demoted", "archived", "blacklisted") and posture(opp_stance) == "buy":
        conflicts.append(_conflict("hermes_lifecycle", (h_stage, "hermes_watchlist_lifecycle",
                                                        (inputs.get("hermes") or {}).get("as_of")),
                                   (opp_stance, "cio_opportunity_projection", opp_at)))

    if lc:
        conflicts.extend(lc.get("conflicts") or [])

    # ---- evidence / expiry ----
    times = [_ts(x) for x in (opp_at, (spine or {}).get("as_of"), t_at, (irec or {}).get("updated_ts"),
                              (inputs.get("hermes") or {}).get("as_of") if hermes else None,
                              (entry or {}).get("evaluated_at"), (packet or {}).get("generated_at"))]
    times = [t for t in times if t is not None and t <= now + timedelta(minutes=5)]
    evidence_at = max(times) if times else now
    window = MARKET_STALE_H if market_open(now) else CLOSED_STALE_H
    expires_at = evidence_at + timedelta(hours=window)

    # ---- trigger / missing / action ----
    rrl = (opp or {}).get("risk_reward") or {}
    advice = (lc or {}).get("advice")
    if advice:
        next_trigger = {"kind": "reentry", "state": advice["state"], "alert_levels": advice["alert_levels"],
                        "observed_by": "cio-prospect-shadow (re-entry desk rules)",
                        "note": "references for a person, never orders"}
    elif stage in ("held",):
        next_trigger = {"kind": "reference_level", "invalidation_level": rrl.get("invalidation_level"),
                        "observed_by": "cio-opportunity-curator", "note": "information, never an order"}
    elif rrl.get("entry_zone") or rrl.get("entry_ref"):
        next_trigger = {"kind": "reference_level", "entry_zone": rrl.get("entry_zone"),
                        "entry_ref": rrl.get("entry_ref"), "invalidation_level": rrl.get("invalidation_level"),
                        "observed_by": "cio-entry-state", "note": "information, never an order"}
    else:
        next_trigger = {"kind": "evidence", "what": "an entry plan (no reference levels on record)",
                        "observed_by": "watchlist-entry-planner"}
    missing: list[str] = []
    for f in (opp or {}).get("factors_missing") or []:
        missing.append(f"opportunity factor: {f}")
    if not opp:
        missing.append("no opportunity assessment (curator has not covered this security)")
    if not thesis:
        missing.append("no CIO thesis (cio_theses)")
    if not spine:
        missing.append("no research spine row (NO SILOS)")
    for name in ("hermes_score", "thesis_quality", "scanner_score"):
        if comps[name]["value"] is None:
            missing.append(f"conviction component {name} has no value")
    if advice:
        cause = (((lc or {}).get("life") or {}).get("exit_cause") or {}).get("class")
        next_action = {"who": "operator", "what": f"read the post-exit review ({cause}); re-entry: "
                                                  f"{advice['state']} — {advice['action']}",
                       "conflicts_to_resolve": sorted({c['field'] for c in conflicts})}
    elif conflicts:
        next_action = {"who": "cio", "what": f"resolve {len(conflicts)} conflict(s) with a recorded reason",
                       "fields": sorted({c['field'] for c in conflicts})}
    elif stage == "actionable":
        next_action = {"who": "operator", "what": "review the setup (stance is posture, never an order)"}
    elif (irec or {}).get("next_research_question"):
        next_action = {"who": "cio", "what": "research", "question": irec.get("next_research_question")}
    elif missing:
        next_action = {"who": "cio", "what": "close the evidence gap", "gap": missing[0]}
    else:
        next_action = {"who": "lane", "what": "wait for the next trigger", "observed_by": next_trigger.get("observed_by")}

    # ---- watchlist membership (one per security; ways in with a reason) ----
    cands: list[dict[str, Any]] = []
    if star:
        cands.append({"origin": "operator_star", "reason": "operator starred", "at": _iso(_ts(star.get("created_at")))})
    if wl_item and str(wl_item.get("source") or "").lower() in ("operator", "operator_ui", "manual"):
        cands.append({"origin": "operator_add", "reason": f"operator added ({wl_item.get('source')})",
                      "at": _iso(_ts(wl_item.get("first_seen_at")))})
    if is_held:
        cands.append({"origin": "held_position", "reason": f"held per {held_src}", "at": held.get("as_of")})
    min_conv = float(((rules.get("ways_in") or {}).get("min_conviction")) or 60)
    if opp_stance in ("ADD", "RE_ENTER") or float((opp or {}).get("conviction") or 0) >= min_conv:
        cands.append({"origin": "cio_curator",
                      "reason": f"opportunity stance {opp_stance} conviction {(opp or {}).get('conviction')}",
                      "at": opp_at})
    if posture(thesis_stance) in ("buy", "watch", "hold"):
        cands.append({"origin": "cio_thesis", "reason": f"thesis {(thesis or {}).get('thesis_version')} "
                                                        f"stance {thesis_stance.lower()}", "at": t_at})
    if advice:
        cands.append({"origin": "reentry_desk", "reason": f"exited {why.get('at')} ({why.get('cause')}); "
                                                          f"re-entry watch: {advice['state']}", "at": why.get("at")})
    elif stage == "re_entry":
        cands.append({"origin": "reentry_desk", "reason": f"re-entry desk {re_state or opp_stance}", "at": why.get("at")})
    if posture((scan_db or scan or {}).get("decision")) == "buy" or str((scan or {}).get("decision") or "").upper() == "GO":
        cands.append({"origin": "scanner_verdict", "reason": f"scanner {(scan_db or scan).get('decision')}",
                      "at": _iso(_ts((scan_db or scan).get("scanned_at") or (scan or {}).get("observed_at")))})
    if h_stage in ("promoted", "watch"):
        cands.append({"origin": "hermes", "reason": f"hermes lifecycle {h_stage}",
                      "at": (inputs.get("hermes") or {}).get("as_of")})
    if wl_item and not any(c["origin"] == "operator_add" for c in cands):
        cands.append({"origin": "existing_member", "reason": f"watchlist_items {wl_item.get('status')} "
                                                             f"({wl_item.get('source')})",
                      "at": _iso(_ts(wl_item.get("updated_at")))})
    watch = wl_rules.membership(cands, rules)

    research = {"thesis_stance": (thesis_stance or "").lower() or None,
                "thesis_version": (thesis or {}).get("thesis_version"),
                "thesis_status": (thesis or {}).get("status"),
                "spine_stance": sp_stance, "spine_state": th.get("state"),
                "spine_as_of": (spine or {}).get("as_of"),
                "contribution_count": (spine or {}).get("contribution_count")}

    sources_used = {n: (inputs.get(n) or {}).get("as_of") for n in inputs if g(n) is not None}
    base = ir.new_record("HELD" if is_held else "WATCH", sym)
    for k in ("subject_guid", "issuer_guid", "security_guid", "identity_status", "identity_lookup"):
        if identity.get(k) is not None:
            base[k] = identity[k]
    if (thesis or {}).get("thesis_version"):
        base["thesis_ref"] = thesis.get("thesis_version")
    if irec:
        for k in ir.COGNITION_FIELDS:
            if irec.get(k) is not None:
                base[k] = irec.get(k)
    block = {
        "security_guid": identity["security_guid"], "issuer_guid": identity["issuer_guid"],
        "stage": stage, "stage_evidence": why, "conviction": conviction if conviction is not None else 0.0,
        "conviction_components": comps, "stance": stance, "catalyst_grade": None,
        "next_trigger": next_trigger, "whats_missing": missing, "next_action": next_action,
        "research": research, "position_ref": {"held": is_held, "source": held_src, "as_of": held.get("as_of")},
        "watchlist": watch, "conflicts": conflicts, "evidence_at": _iso(evidence_at),
        "expires_at": _iso(expires_at),
        "provenance": {"builder": BUILDER, "mode": "shadow", "class": "D", "stance_source": stance_src,
                       "sources": sources_used, "conviction_reproducible": conviction is not None},
    }
    if lc:
        block.update({"stage_phase": stage_phase, "origin": lc.get("origin"), "position_lifecycle": lc.get("life"),
                      "post_exit_review": lc.get("review"), "reentry_advice": lc.get("advice")})
    if conviction is None:
        block["conviction_components"] = {k: v for k, v in comps.items() if v.get("value") is None}
        block["whats_missing"] = missing + ["no conviction component has a value (conviction rendered 0, unknown)"]
        block["provenance"]["conviction_unknown"] = True
    rec, _ = ir.apply_prospect(base, prospect=block)
    rec["_lifecycle_events"] = (lc or {}).get("events") or []     # the events table rows; not a record field
    return rec


def build(state_root: Path, *, db_query: Optional[Callable[[str], list[dict]]] = None,
          held_reader: Optional[Callable[[], dict]] = None,
          identity_resolver: Optional[Callable[[str], dict]] = None,
          symbols: Optional[Iterable[str]] = None, now: Optional[datetime] = None,
          rules: Optional[dict[str, Any]] = None,
          captured: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Assemble every prospect. Pure with respect to stores: reads, never writes. ``captured`` supplies the
    lifecycle rows (round trips, fills, observed stops, links, bars) captured read-only elsewhere."""
    now = now or datetime.now(timezone.utc)
    rules = rules if rules is not None else wl_rules.load_rules()
    inputs = load_file_inputs(Path(state_root))
    inputs.update(load_db_inputs(db_query))
    inputs.update(load_lifecycle_inputs(db_query, captured))
    held = load_held(Path(state_root), held_reader)
    if inputs["bars"]["status"] == "deferred" and db_query is not None:
        want = set(held["symbols"]) | set(inputs["round_trips"]["rows"].keys())
        bars: dict[str, list] = {}
        try:
            for s in sorted(want):
                bars[s] = list(db_query(BARS_SQL, (s,)) or [])
            inputs["bars"].update(rows=bars, count=len(bars), status="ok")
        except Exception as exc:  # noqa: BLE001
            inputs["bars"].update(status=f"error:{type(exc).__name__}")
    if identity_resolver is None:
        from scripts.lib.identity_carriage import resolve_security_identity

        def identity_resolver(s: str) -> dict:
            return resolve_security_identity(s, root=Path(state_root))
    universe: set[str] = set(held["symbols"])
    for name in ("opportunity", "theses", "instrument_records", "reentry", "watchlist_items", "starred",
                 "round_trips"):
        universe |= set((inputs.get(name) or {}).get("rows", {}).keys())
    if symbols is not None:
        universe = {str(s).upper() for s in symbols}
    universe = {s for s in universe if s and s not in ir.NON_INSTRUMENT_SYMBOLS}

    prospects: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    seen_guid: dict[str, str] = {}
    duplicates: list[dict[str, Any]] = []
    for sym in sorted(universe):
        ident = identity_resolver(sym) or {}
        if ident.get("identity_status") != "CONFIRMED" or not ident.get("security_guid") or \
                not ident.get("issuer_guid"):
            unresolved.append({"symbol": sym, "identity_status": ident.get("identity_status"),
                               "reason": ident.get("identity_lookup_reason") or "identity unresolved"})
            continue
        guid = str(ident["security_guid"])
        if guid in seen_guid:
            duplicates.append({"security_guid": guid, "symbols": [seen_guid[guid], sym]})
            continue
        seen_guid[guid] = sym
        try:
            prospects.append(assemble(sym, inputs, held, ident, now=now, rules=rules))
        except Exception as exc:  # noqa: BLE001 — one bad security never sinks the build; it is reported
            errors.append({"symbol": sym, "error": f"{type(exc).__name__}: {exc}"[:240]})

    rows = [{**ir.prospect_row(p), "lifecycle_events": p.get("_lifecycle_events") or []} for p in prospects]
    curation = wl_rules.curate(rows, rules, now=now)
    for r in rows:
        d = curation["decisions"].get(r["security_guid"])
        if d and r.get("watchlist"):
            r["watchlist"] = {**r["watchlist"], "curation": d}
    rows.sort(key=rank_key)
    for i, r in enumerate(rows, 1):
        r["shadow_rank"] = i
        r["rankable"] = not rank_key(r)[0]

    stage_counts: dict[str, int] = {}
    for r in rows:
        stage_counts[r["stage"]] = stage_counts.get(r["stage"], 0) + 1
    return {
        "schema": SCHEMA,
        "as_of": _iso(now),
        "mode": "shadow",
        "writes": "none",
        "authority": ir.AUTHORITY,
        "memory_behavior_influence": ir.MBI_BEHAVIOR,
        "store_status": ir.prospect_store_status(),
        "sources": {n: {k: v for k, v in s.items() if k != "rows"} for n, s in inputs.items()},
        "held": {k: (len(v) if k == "symbols" else v) for k, v in held.items()},
        "counts": {"universe": len(universe), "prospects": len(rows), "identity_unresolved": len(unresolved),
                   "duplicate_guid": len(duplicates), "errors": len(errors),
                   "with_conflicts": sum(1 for r in rows if r["conflicts"]),
                   "conflicts": sum(len(r["conflicts"]) for r in rows), "by_stage": stage_counts,
                   "with_position_lifecycle": sum(1 for r in rows if r.get("position_lifecycle")),
                   "exited_in_window": sum(1 for r in rows if (r.get("position_lifecycle") or {}).get("status")
                                           == "closed"),
                   "origin": {k: sum(1 for r in rows if (r.get("origin") or {}).get("classification") == k)
                              for k in ("internal", "operator_initiated")},
                   "lifecycle_events": sum(len(r["lifecycle_events"]) for r in rows)},
        "watchlist_curation": {k: v for k, v in curation.items() if k != "decisions"},
        "prospects": rows,
        "identity_unresolved": unresolved,
        "duplicate_guid": duplicates,
        "errors": errors,
    }


# ── comparison vs today's surfaces ──────────────────────────────────────────


OPPORTUNITY_CONFIG = Path(__file__).resolve().parents[2] / "config" / "opportunity_conviction.yaml"


def home_best_opportunities(opp_items: dict[str, dict], *, preset: str = "top5") -> list[dict[str, Any]]:
    """What Home "Best opportunities" shows: /api/v3/opportunities?preset=top5 over the same projection.

    Reads the preset from config/opportunity_conviction.yaml and applies its min_conviction / min_rr /
    min_coverage bars, sorted by conviction — the same rule as ``lib.data_broker.opportunity.passes`` /
    ``sort_items`` for these keys (a test pins the equivalence). Not imported from there: that module's import
    closure reaches market_quote -> broker transport, which a dispatched lane must not import (§23.14).
    """
    import yaml

    try:
        cfg = yaml.safe_load(OPPORTUNITY_CONFIG.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        cfg = {}
    q = (cfg.get("presets") or {}).get(preset) or {"min_conviction": 80, "min_rr": 2.0, "min_coverage": 0.8,
                                                   "limit": 5, "sort": "conviction"}

    def ok(a: dict[str, Any]) -> bool:
        for key, val in (("min_conviction", a.get("conviction")), ("min_rr", (a.get("risk_reward") or {}).get("rr")),
                         ("min_coverage", a.get("coverage"))):
            if q.get(key) is not None and (val is None or float(val) < float(q[key])):
                return False
        return True

    rows = [a for a in opp_items.values() if ok(a)]
    rows.sort(key=lambda a: (a.get("conviction") is None, -(a.get("conviction") or 0)))
    return rows[: int(q.get("limit") or 5)]


def compare(build_doc: dict[str, Any], state_root: Path, *, watch_top_ideas: Optional[list[str]] = None,
            watch_source: Optional[str] = None, top_n: int = 50, now: Optional[datetime] = None) -> dict[str, Any]:
    """Per-symbol agreements / conflicts between the shadow prospect and Home, Watch and Telegram."""
    now = now or datetime.now(timezone.utc)
    opp = load_file_inputs(Path(state_root))["opportunity"]
    opp_items = opp["rows"]
    opp_age_h = None
    if _ts(opp.get("as_of")):
        opp_age_h = round((now - _ts(opp["as_of"])).total_seconds() / 3600.0, 2)
    telegram_live = opp_age_h is not None and opp_age_h <= 26
    home5 = [a.get("symbol") for a in home_best_opportunities(opp_items)]
    home_rank = {str(a.get("symbol")).upper(): a.get("rank") for a in opp_items.values() if a.get("rank")}
    watch = [str(s).upper() for s in (watch_top_ideas or [])]
    by_sym = {r["symbol"]: r for r in build_doc["prospects"]}
    shadow_top = [r["symbol"] for r in build_doc["prospects"][:top_n]]
    home_top = [s for s, _ in sorted(home_rank.items(), key=lambda kv: kv[1])[:top_n]]
    subjects = list(dict.fromkeys(shadow_top + home5 + watch))

    rows = []
    for sym in subjects:
        p, a = by_sym.get(sym), opp_items.get(sym) or {}
        sh_post = posture((p or {}).get("stance"))
        home_post = posture(a.get("stance"))
        verdict = []
        if p is None:
            verdict.append("no_shadow_prospect (identity unresolved or not in universe)")
        else:
            if a and sh_post and home_post and sh_post != home_post:
                verdict.append(f"stance: shadow {p['stance']} vs home {a.get('stance')}")
            if a.get("conviction") is not None and abs(float(p["conviction"]) - float(a["conviction"])) >= 10:
                verdict.append(f"conviction: shadow {p['conviction']} vs home {a.get('conviction')}")
            if p["conflicts"]:
                verdict.append("inputs disagree: " + ", ".join(sorted({c['field'] for c in p['conflicts']})))
            if sym in watch and p["stage"] in ("watching",) and posture(p["stance"]) != "buy":
                verdict.append("watch ranks it a top idea; shadow stage watching/no setup")
        rows.append({
            "symbol": sym,
            "shadow": None if p is None else {"rank": p.get("shadow_rank"), "stage": p["stage"],
                                              "stance": p["stance"], "conviction": p["conviction"],
                                              "conflicts": [c["field"] for c in p["conflicts"]]},
            "home": {"rank": a.get("rank"), "conviction": a.get("conviction"), "stance": a.get("stance"),
                     "in_best_opportunities": sym in home5} if a else None,
            "watch": {"top_idea_rank": (watch.index(sym) + 1) if sym in watch else None} if watch_top_ideas is not None
            else None,
            "telegram": ({"conviction_line": f"Conviction {round(float(a['conviction']))}/100 · #{a.get('rank')} · "
                                             f"{a.get('stance')}"} if (a and telegram_live
                                                                         and a.get("conviction") is not None)
                         else {"conviction_line": None,
                               "why": "projection older than 26h" if a else "symbol not curated"}),
            "agrees": not verdict,
            "differences": verdict,
        })
    summary = {
        "subjects": len(rows),
        "agree": sum(1 for r in rows if r["agrees"]),
        "differ": sum(1 for r in rows if not r["agrees"]),
        "shadow_top_vs_home_top_overlap": len(set(shadow_top) & set(home_top)),
        "home_best_opportunities": home5,
        "home_best_in_shadow_top": [s for s in home5 if s in shadow_top],
        "watch_top_ideas": watch if watch_top_ideas is not None else None,
        "watch_in_shadow_top": [s for s in watch if s in shadow_top] if watch_top_ideas is not None else None,
        "stance_differences": sum(1 for r in rows if any(d.startswith("stance") for d in r["differences"])),
        "conviction_differences": sum(1 for r in rows if any(d.startswith("conviction") for d in r["differences"])),
        "with_input_conflicts": sum(1 for r in rows if any(d.startswith("inputs") for d in r["differences"])),
    }
    return {
        "schema": "CioProspectSurfaceComparison@v1",
        "as_of": _iso(now),
        "top_n": top_n,
        "surfaces": {
            "home": {"source": "data/cio/cio_opportunity_projection.json via opportunity preset top5 "
                               "(/api/v3/opportunities, HomeDecision BestOpportunities)", "as_of": opp.get("as_of")},
            "watch": {"source": watch_source or "not captured (the Watch read path rebuilds the re-entry desk, "
                                                "which writes; the shadow lane never calls it)"},
            "telegram": {"source": "scripts/lib/opportunity_alert.enrich reads the same projection; suppressed "
                                   "when older than 26h", "projection_age_h": opp_age_h, "live": telegram_live},
        },
        "summary": summary,
        "rows": rows,
    }
