"""Read-only projections for restored desks A (approved boards 1–4).

Re-Entry, Strategy, Defense and Agents. Each payload is display rows built only
from stored fields; a missing field is an explicit gap ("not on file", "not
measured"), never a zero or a guess. CIO stance, regime, holdings and stops come
from ``scripts.lib.cio_truth`` (the one CIO source); this module never
recomputes them. No job, provider, broker, write, DDL or subprocess: files are
read with a byte cap and SQL is SELECT only through the injected ``db_query``.

Several existing GET handlers for these pages have side effects (DDL + commit,
cache rewrites, a Yahoo fetch, ``crontab -l``); this module deliberately reads
their stores directly instead of calling them. Field trace:
``docs/ops/DESKS_A_REDESIGN_20261025.md``.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

READ_LIMIT = 4 * 1024 * 1024
MAX_ROWS = 12
DESKS = ("reentry", "strategy", "defense", "agents")
GAP_NOT_ON_FILE = "not on file"
GAP_NOT_MEASURED = "not measured"

DbQuery = Callable[..., Any]
_ET = ZoneInfo("America/New_York")


# Board 3 / board 15 stop vocabulary (display only; categories come from cio_truth.resolve "stop_category").
BOOK_STOP_TEXT = {"active": "stop active", "pending_activation": "stop pending activation",
                  "filled": "stop filled · awaiting holdings sync", "unknown": "stop state not recorded",
                  "planned": "planned level only · no resting order", "none": "no stop"}


def _stop_category(p: dict) -> str:
    cat = p.get("stop_category")
    if cat in BOOK_STOP_TEXT:
        return cat
    state = p.get("stop_state")
    if state in ("active", "pending_activation", "filled", "unknown"):
        return state
    return "planned" if p.get("stop_source") == "planned" and p.get("stop_price") is not None else "none"


# ── primitives ────────────────────────────────────────────────────────────────
def _time(raw: Any) -> datetime | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return raw.astimezone(timezone.utc) if raw.tzinfo else None
    try:
        stamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp.astimezone(timezone.utc) if stamp.tzinfo else None


def _iso(raw: Any) -> str | None:
    at = _time(raw)
    return at.isoformat() if at else None


def _num(raw: Any) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _read_json(path: Path) -> tuple[Any, str | None]:
    """(document, gap). A missing, oversized or unreadable file is a named gap."""
    try:
        with Path(path).open("rb") as handle:
            raw = handle.read(READ_LIMIT + 1)
    except FileNotFoundError:
        return None, f"{Path(path).name} is not on file."
    except OSError as exc:
        return None, f"{Path(path).name} could not be read ({type(exc).__name__})."
    if len(raw) > READ_LIMIT:
        return None, f"{Path(path).name} exceeds the desk read limit."
    try:
        return json.loads(raw.decode("utf-8")), None
    except (UnicodeDecodeError, ValueError):
        return None, f"{Path(path).name} is not valid JSON."


def _select(db_query: DbQuery | None, sql: str, params: tuple | None = None) -> list[dict] | None:
    """SELECT only; None means the read failed or no database is configured."""
    if not sql.lstrip().upper().startswith(("SELECT", "WITH")):
        raise ValueError("desk projections run SELECT statements only")
    if db_query is None:
        return None
    try:
        rows = db_query(sql, params)
    except Exception:  # noqa: BLE001 -- a failed read is a gap, never an empty list
        return None
    return [dict(r) for r in rows] if isinstance(rows, list) else None


def _money(value: Any, signed: bool = False) -> str:
    n = _num(value)
    if n is None:
        return GAP_NOT_ON_FILE
    sign = ("+" if n > 0 else "−" if n < 0 else "") if signed else ("−" if n < 0 else "")
    return f"{sign}${abs(n):,.0f}"


def _pct(value: Any, digits: int = 1) -> str:
    n = _num(value)
    return GAP_NOT_ON_FILE if n is None else f"{n:.{digits}f}%"


def _count(value: Any) -> str:
    n = _num(value)
    return GAP_NOT_ON_FILE if n is None else f"{int(n):,}"


def _date(raw: Any) -> str:
    """Readable Eastern time ("Fri Oct 23 17:55 ET"); a stamp without a zone shows its date only."""
    at = _time(raw)
    if at:
        return at.astimezone(_ET).strftime("%a %b %d %H:%M ET").replace(" 0", " ")
    return str(raw)[:10] if raw else GAP_NOT_ON_FILE


def _row(rid: str, label: str, value: str, tone: str | None = None, *, href: str | None = None,
         detail: dict | None = None) -> dict:
    out: dict[str, Any] = {"id": rid, "label": label, "value": value, "tone": tone}
    if href:
        out["href"] = href
    if detail:
        out["detail"] = detail
    return out


def _detail(title: str, fields: list[tuple[str, Any]], source: str, href: str | None = None,
            href_label: str | None = None) -> dict:
    out = {"title": title, "source": source,
           "fields": [{"label": k, "value": GAP_NOT_ON_FILE if v is None or v == "" else str(v)} for k, v in fields]}
    if href:
        out["href"], out["href_label"] = href, href_label or "Open →"
    return out


def _panel(pid: str, title: str, rows: list[dict], *, sub: str | None = None, span: int = 1,
           gap: str | None = None, empty: str | None = None) -> dict:
    return {"id": pid, "title": title, "sub": sub, "span": span, "rows": rows, "gap": gap, "empty": empty}


def _source(sid: str, label: str, as_of: Any, lanes: list[str], *, gap: str | None = None,
            max_age_hours: float | None = None) -> dict:
    out = {"id": sid, "label": label, "as_of": _iso(as_of), "lane_ids": lanes, "gap": gap}
    if max_age_hours is not None:
        out["max_age_hours"] = max_age_hours
    return out


def lane_states(root: Path) -> dict[str, str] | None:
    """lane_id → registry state, or None when the registry cannot be read."""
    doc, _gap = _read_json(Path(root) / "config" / "lane_registry.json")
    if not isinstance(doc, dict) or not isinstance(doc.get("lanes"), list):
        return None
    return {str(l.get("lane_id")): str(l.get("state") or "") for l in doc["lanes"] if isinstance(l, dict)}


def _plural(n: int, word: str) -> str:
    return f"{n:,} {word}" + ("" if n == 1 else "s")


def _writer_decisions(sources: list[dict], states: dict[str, str] | None, labels: dict[str, str]) -> list[dict]:
    """Decisions that follow from the registry: a paused, retired or missing writer behind a panel."""
    out = []
    for s in sources:
        if s["id"] not in labels:
            continue
        s = {**s, "label": s["label"].split(" · ")[0]}
        lanes = s["lane_ids"]
        if not lanes:
            out.append({"id": f"writer-{s['id']}", "title": f"{s['label']}: no scheduled writer",
                        "detail": f"{labels[s['id']]} Schedule a writer as an n8n lane, or retire the panel."})
            continue
        if states is None:
            continue
        bad = [f"{lane} {states.get(lane) or 'NOT REGISTERED'}" for lane in lanes
               if states.get(lane) in (None, "PAUSED", "RETIRED", "NEVER_SCHEDULED")]
        if bad and len(bad) == len(lanes):
            out.append({"id": f"writer-{s['id']}", "title": f"{s['label']}: writer {', '.join(bad)}",
                        "detail": f"{labels[s['id']]} Restore the writer as an n8n lane, or retire the panel."})
    return out


def _lane_gap(lanes: list[str], states: dict[str, str] | None, what: str) -> str | None:
    if not lanes:
        return f"No job writes {what}: it has no scheduled writer."
    if states is None:
        return None
    off = [f"{lane} is {states.get(lane) or 'not registered'}" for lane in lanes
           if states.get(lane) in (None, "PAUSED", "RETIRED", "NEVER_SCHEDULED")]
    return f"{what[0].upper() + what[1:]} is not being refreshed: {'; '.join(off)}." if off and len(off) == len(lanes) else None


def _envelope(desk: str, now: datetime, sources: list[dict], tabs: dict, decisions: list[dict],
              errors: list[str]) -> dict:
    return {"ok": True, "desk": desk, "read_only": True, "financial_action": False, "as_of": now.isoformat(),
            "sources": sources, "decisions": decisions,
            "decision_gap": None if decisions else "No writer or data decisions are open for this desk.",
            "tabs": tabs, "errors": errors}


def _cio_stance_text(stance: dict | None) -> str:
    if not stance or stance.get("gap") or stance.get("stance") is None:
        return "CIO stance not on file"
    conviction = _num(stance.get("conviction"))
    return f"{stance['stance']}" + (f" · conviction {conviction:.0f}" if conviction is not None else "")


# ── Board 1 · Re-Entry ────────────────────────────────────────────────────────
REENTRY_LANES = {
    "packets": ["cio-entry-state"],
    "regime": ["market-regime-classifier"],
    "holdings": ["portfolio-repricer"],
    "resistance": ["watch-alerts-eval"],
    "analyst": ["hermes-analyst-coverage", "pro-analyst-fetch"],
    "dividends": ["portfolio-ai-analyst", "sync-dividend-data"],
}


def reentry_payload(*, root: Path, db_query: DbQuery | None = None, now: datetime | None = None,
                    packets: dict | None = None, truth: dict | None = None, stances: dict | None = None,
                    exits: dict | None = None, states: dict | None = None) -> dict:
    """Board 1. ``packets`` = buy_ready_packets_index.index_packets (48 h window);
    ``truth`` = cio_truth.resolve; ``stances`` = cio_truth.stances_for_symbols;
    ``exits`` = redeploy_capital_book.build_history (sells vs deploy events)."""
    now = now or datetime.now(timezone.utc)
    root = Path(root)
    errors: list[str] = []
    packets = packets if isinstance(packets, dict) else {}
    truth = truth if isinstance(truth, dict) else {}
    stances = stances if isinstance(stances, dict) else {}
    rows = [r for r in packets.get("rows") or [] if isinstance(r, dict)]
    stale = [r for r in packets.get("stale") or [] if isinstance(r, dict)]
    newest = max((r.get("saved_at") for r in rows if _time(r.get("saved_at"))), key=lambda v: _time(v), default=None)
    packet_gap = None if packets else "The buy-ready packet index could not be read."

    ready_rows = []
    for r in rows[:MAX_ROWS]:
        sym = str(r.get("symbol") or "?")
        lo, hi = _num(r.get("entry_low")), _num(r.get("entry_high"))
        zone = f"zone ${lo:,.2f}–${hi:,.2f}" if lo is not None and hi is not None else "zone not on file"
        st = stances.get(sym.upper())
        ready_rows.append(_row(f"pkt-{sym}", f"{sym} · {zone}", str(r.get("state") or GAP_NOT_ON_FILE),
                               "good" if r.get("state") == "BUY_READY" else "info",
                               detail=_detail(f"{sym} · {r.get('state') or 'packet'}", [
                                   ("Stage (packet)", r.get("state")),
                                   ("Entry zone", zone.removeprefix("zone ")),
                                   ("Price at quote", f"${_num(r.get('price')):,.2f}" if _num(r.get("price")) is not None else None),
                                   ("Planned stop", f"${_num(r.get('stop')):,.2f}" if _num(r.get("stop")) is not None else None),
                                   ("Planned target", f"${_num(r.get('target')):,.2f}" if _num(r.get("target")) is not None else None),
                                   ("Plan R:R", r.get("rr_plan")),
                                   ("Catalyst", r.get("catalyst") if isinstance(r.get("catalyst"), str) else (r.get("catalyst") or {}).get("summary") if isinstance(r.get("catalyst"), dict) else None),
                                   ("CIO stance (cio_truth)", _cio_stance_text(st)),
                                   ("Packet saved", _date(r.get("saved_at"))),
                               ], "data/runtime/buy_ready_packets/<SYM>.json via buy_ready_packets_index; stance via cio_truth.stances_for_symbols",
                                   href=f"/watch?symbol={sym}", href_label="Set an alert on Watch →")))
    if len(rows) > MAX_ROWS:
        ready_rows.append(_row("pkt-more", f"{len(rows) - MAX_ROWS} more current packets", "Classic view →", "info",
                               href="/portfolio/re-entry/classic"))
    ready_rows.append(_row("pkt-alert", "Set an alert on any name", "→ Watch alerts", "info", href="/watch"))
    stale_note = (f"{_plural(len(stale), 'packet')} older than {packets.get('max_age_h', 48):g} h {'is' if len(stale) == 1 else 'are'} hidden here and kept in history."
                  if stale else None)

    # Exits: sells (trade_transactions vs deploy_events) + your saved classifications (ui_prefs).
    exit_rows_raw = [r for r in (exits or {}).get("rows") or [] if isinstance(r, dict)] if isinstance(exits, dict) else []
    exit_gap = None if isinstance(exits, dict) and exits.get("ok", True) is not False and "rows" in exits else "Sell history could not be read."
    prefs = _select(db_query, "SELECT key, value, updated_at FROM ui_prefs WHERE key = ANY(%s)",
                    (["portfolio.reentry.event-classifications.v1", "portfolio.reentry.resistance.v1"],))
    pref = {r.get("key"): r for r in prefs or []}
    classes_doc = (pref.get("portfolio.reentry.event-classifications.v1") or {}).get("value")
    classes = classes_doc if isinstance(classes_doc, dict) else {}
    resist_doc = (pref.get("portfolio.reentry.resistance.v1") or {}).get("value")
    resist_doc = resist_doc if isinstance(resist_doc, dict) else {}
    resist = resist_doc.get("symbols") if isinstance(resist_doc.get("symbols"), dict) else {}
    cutoff = (now - timedelta(days=30)).date().isoformat()
    recent = [r for r in exit_rows_raw if str(r.get("trade_date") or "") >= cutoff]
    saved = {k: v for k, v in classes.items() if isinstance(v, dict) and v.get("eventType")}
    exit_symbols = sorted({str(r.get("symbol") or "").upper() for r in exit_rows_raw if r.get("symbol")})
    missing_res = [s for s in exit_symbols if not isinstance(resist.get(s), dict) or resist[s].get("state") in (None, "UNAVAILABLE")]
    class_gap = "Your saved exit classifications could not be read." if prefs is None else None
    classification = [
        _row("cls-stopped", "Stopped out (saved by you)", _count(sum(1 for v in saved.values() if v.get("eventType") == "stopped_out")) if prefs is not None else GAP_NOT_ON_FILE),
        _row("cls-saved", "Exits classified (saved by you)", _count(len(saved)) if prefs is not None else GAP_NOT_ON_FILE),
        _row("cls-res", "Sold names with no resistance level on file", _count(len(missing_res)) if prefs is not None and exit_gap is None else GAP_NOT_ON_FILE,
             "warn" if missing_res else None),
        _row("cls-edit", "Classify or edit an exit", "Classic view →", "info", href="/portfolio/re-entry/classic"),
    ]
    workbench = []
    for r in sorted(recent, key=lambda r: str(r.get("trade_date") or ""), reverse=True)[:MAX_ROWS]:
        sym, key = str(r.get("symbol") or "?"), str(r.get("event_key") or "")
        c = saved.get(key) or {}
        workbench.append(_row(f"exit-{key or sym}", f"{sym} sold {str(r.get('trade_date') or '')[:10]}",
                              str(c.get("eventType") or "not classified").replace("_", " "),
                              None if c else "warn",
                              detail=_detail(f"{sym} · exit {str(r.get('trade_date') or '')[:10]}", [
                                  ("Account", r.get("account_label") or r.get("account")),
                                  ("Proceeds", _money(r.get("proceeds_usd"))),
                                  ("Your classification", str(c.get("eventType") or "not classified").replace("_", " ")),
                                  ("Your reason", c.get("reason")),
                                  ("Redeploy event", r.get("event_status") or "not matched"),
                                  ("Reclaim price vs now", GAP_NOT_MEASURED),
                              ], "trade_transactions + deploy_events (redeploy_capital_book.build_history); ui_prefs portfolio.reentry.event-classifications.v1")))

    levels = []
    ranked = sorted(((s, v) for s, v in resist.items() if isinstance(v, dict) and _num(v.get("distance_pct")) is not None),
                    key=lambda kv: abs(_num(kv[1].get("distance_pct")) or 0))
    for sym, v in ranked[:MAX_ROWS]:
        levels.append(_row(f"res-{sym}", f"{sym} · resistance ${_num(v.get('resistance')) or 0:,.2f}" if _num(v.get("resistance")) is not None else f"{sym} · resistance not on file",
                           f"{v.get('state') or '?'} · {_num(v.get('distance_pct')):+.1f}%",
                           "good" if v.get("state") == "ABOVE" else "warn" if v.get("state") == "TESTING" else None,
                           detail=_detail(f"{sym} · resistance", [
                               ("State", v.get("state")), ("Resistance", v.get("resistance")),
                               ("Last close", v.get("current_close")), ("Distance", _pct(v.get("distance_pct"))),
                               ("Days held above", v.get("hold_days")), ("Tests", v.get("tests")),
                               ("Method", v.get("method")), ("As of", v.get("as_of")),
                           ], "ui_prefs portfolio.reentry.resistance.v1 (watch_alerts_eval → reentry_resistance.refresh_resistance_cache)")))

    pills_doc, pills_gap = _read_json(root / "data" / "runtime" / "pro_analyst_pills_latest.json")
    pills_doc = pills_doc if isinstance(pills_doc, dict) else {}
    pills = {str(p.get("symbol") or "").upper(): p for p in pills_doc.get("pills") or [] if isinstance(p, dict)}
    focus = list(dict.fromkeys([str(r.get("symbol") or "").upper() for r in rows] + exit_symbols))
    analyst = []
    for sym in [s for s in focus if s in pills][:MAX_ROWS]:
        p = pills[sym]
        tgt = _num(p.get("target_mean_price"))
        analyst.append(_row(f"an-{sym}", f"{sym} consensus target", f"${tgt:,.2f}" if tgt is not None else GAP_NOT_ON_FILE,
                            detail=_detail(f"{sym} · analyst evidence", [
                                ("Consensus target (mean)", f"${tgt:,.2f}" if tgt is not None else None),
                                ("Upside to mean target", _pct(p.get("upside_to_mean_target_pct"))),
                                ("Recommendation", p.get("recommendation_key")),
                                ("Analyst opinions", p.get("number_of_analyst_opinions")),
                                ("Street direction", p.get("street_direction")),
                                ("Revisions, 30 days", GAP_NOT_MEASURED),
                            ], "data/runtime/pro_analyst_pills_latest.json (build_pro_analyst_read_model)")))

    portfolio = truth.get("portfolio") or {}
    regime = truth.get("regime") or {}
    div_doc, div_gap = _read_json(root / "data" / "portfolios" / "state" / "dividend_calendar.json")
    div_raw = (div_doc or {}).get("last_updated") if isinstance(div_doc, dict) else None
    states = states if states is not None else lane_states(root)
    sources = [
        _source("packets", f"Buy-ready packets · {len(rows)} current", newest, REENTRY_LANES["packets"],
                gap=packet_gap or (stale_note and f"{_plural(len(stale), 'packet')} older than 48 h (hidden from Ready now, kept in history).")),
        _source("regime", "Market regime (CIO)", regime.get("as_of"), REENTRY_LANES["regime"],
                gap=(regime.get("gap") or {}).get("reason") if isinstance(regime.get("gap"), dict) else None, max_age_hours=26),
        _source("holdings", "Holdings priced", portfolio.get("quote_as_of"), REENTRY_LANES["holdings"],
                gap=None if portfolio.get("quote_as_of") else "Holdings reprice time is not on file."),
        _source("resistance", "Resistance levels", resist_doc.get("generated_at"), REENTRY_LANES["resistance"],
                gap=class_gap or (None if resist_doc else "No resistance cache on file.")),
        _source("analyst", f"Pro-analyst pills · {_count(pills_doc.get('symbol_count'))}", pills_doc.get("updated_at"),
                REENTRY_LANES["analyst"], gap=pills_gap),
        _source("dividends", "Dividends calendar", None, REENTRY_LANES["dividends"],
                gap=div_gap or (f"Last updated {div_raw} (recorded without a time zone)." if div_raw else "Dividend calendar update time is not on file.")),
    ]
    decisions = _writer_decisions(sources, states, {
        "regime": "The regime classifier writer is not running, so the regime clock is frozen.",
        "dividends": "Dividend data upstream (sync-dividend-data) is retired while the calendar is still rebuilt from it.",
        "packets": "Buy-ready packets are the Telegram BUY_READY / ENTRY_NEAR source.",
    })
    if stale:
        decisions.append({"id": "packet-expiry", "title": f"{_plural(len(stale), 'buy-ready packet')} older than 48 h",
                          "detail": "They are hidden from Ready now and kept in history. Decide an expiry rule for the packet store."})
    tabs = {
        "ready-now": {"panels": [
            _panel("ready", "Ready now", ready_rows, sub="BUY_READY / ENTRY_NEAR packets — the same ones Telegram sends", span=2,
                   gap=packet_gap or stale_note, empty="No current buy-ready or entry-near packet."),
            _panel("classification", "Classification", classification, sub="why you exited", gap=class_gap or exit_gap),
            _panel("owned", "Owned elsewhere — linked, not repeated", [
                _row("own-lt", "Look-through & sectors", "→ Portfolio › Look-through", "info", href="/portfolio?tab=Look-through"),
                _row("own-rot", "Rotation workspace", "→ Rotation desk", "info", href="/rotation"),
                _row("own-alert", "Set alert", "→ Watch alerts", "info", href="/watch"),
            ], sub="board 13: one home per subject"),
        ]},
        "exits-review": {"panels": [
            _panel("workbench", "Exit workbench", workbench, sub="sells in the last 30 days", span=2, gap=exit_gap,
                   empty="No sells in the last 30 days."),
            _panel("classification-x", "Classification", classification, sub="why you exited", gap=class_gap or exit_gap),
        ]},
        "resistance-levels": {"panels": [
            _panel("levels", "Resistance & levels", levels, sub=f"nearest first · {_count(resist_doc.get('symbol_count')) if resist_doc else GAP_NOT_ON_FILE} names cached", span=2,
                   gap=class_gap or (None if resist else "No resistance levels on file."), empty="No resistance levels on file."),
        ]},
        "analyst-evidence": {"panels": [
            _panel("analyst", "Analyst evidence", analyst, sub=f"pro-analyst pills {_count(pills_doc.get('symbol_count'))} · {_date(pills_doc.get('updated_at'))}", span=2,
                   gap=pills_gap or ("30-day revisions are not measured by the analyst read model." if analyst else None),
                   empty="No analyst pill for a current packet or recent exit."),
        ]},
    }
    return _envelope("reentry", now, sources, tabs, decisions, errors)


# ── Board 2 · Strategy ────────────────────────────────────────────────────────
STRATEGY_LANES = {
    "snapshots": ["feedback-loop-processor"],
    "incubator": ["daily-incubator-refresh", "weekly-incubator-builder", "incubator-proposal-promoter"],
    "backtests": ["proposal-backtest-engine"],
    "readiness": [],
    "setup": ["setup-quality-prior"],
    "transitions": ["strategy-weekly-review"],
}


def strategy_payload(*, root: Path, db_query: DbQuery | None = None, now: datetime | None = None,
                     leaderboard: dict | None = None, states: dict | None = None) -> dict:
    """Board 2. ``leaderboard`` = the existing pure-SELECT ``_strategy_leaderboard()`` so both
    pages rank strategies one way. Paper readiness is read from its file, never recomputed."""
    now = now or datetime.now(timezone.utc)
    root = Path(root)
    lb = [r for r in (leaderboard or {}).get("leaderboard") or [] if isinstance(r, dict)] if isinstance(leaderboard, dict) else []
    lb_gap = (leaderboard or {}).get("error") if isinstance(leaderboard, dict) else "The leaderboard could not be read."
    board = []
    for r in lb[:MAX_ROWS]:
        live = r.get("live") or {}
        snap = r.get("snapshot") or {}
        bt = r.get("backtest") or {}
        sid = str(r.get("strategy_id") or "?")
        pnl = _num(live.get("total_pnl"))
        board.append(_row(f"lb-{sid}", f"{sid.replace('_', ' ')} · win {_pct(live.get('win_rate'))} · {_count(live.get('n'))} trades",
                          _money(pnl, signed=True), "good" if (pnl or 0) > 0 else "bad" if (pnl or 0) < 0 else None,
                          detail=_detail(f"{sid.replace('_', ' ')} · rank {r.get('rank')}", [
                              ("Closed paper trades", _count(live.get("n"))), ("Wins", _count(live.get("wins"))),
                              ("Win rate", _pct(live.get("win_rate"))), ("Total P/L", _money(live.get("total_pnl"), True)),
                              ("Average R (live)", live.get("avg_r") if not live.get("avg_r_suspect") else f"{live.get('avg_r')} (sign disagrees with P/L on some trades)"),
                              ("Backtest expectancy (R)", bt.get("expectancy_r")), ("Backtest sample", bt.get("sample")),
                              ("Latest snapshot", snap.get("snapshot_date")), ("Snapshot assessment", snap.get("assessment")),
                              ("Confidence", r.get("confidence")), ("Tilt multiplier", r.get("tilt")),
                          ], "paper_trades, strategy_backtest_results, strategy_performance_snapshots, strategy_tilt_multipliers (the leaderboard read)")))
    board.append(_row("lb-sort", "Ranked by", "live expectancy (avg R), then P/L, then win rate"))

    stats, stats_gap = _read_json(root / "data" / "paper_trading" / "paper_trade_statistics_latest.json")
    stats = stats if isinstance(stats, dict) else {}
    closed = _num(stats.get("closed_usable"))
    readiness = [
        _row("rd-phase", "Phase", str(stats.get("level") or GAP_NOT_ON_FILE).replace("_", " ")),
        _row("rd-closed", "Closed trades", f"{_count(closed)} / 2,000" if closed is not None else GAP_NOT_ON_FILE),
        _row("rd-wr", "Win rate (all closed)", _pct(stats.get("win_rate"))),
        _row("rd-gate", "Next gate", "2,000 closed trades (P4 strong paper evidence)" if closed is not None and closed < 2000
             else "4,000 closed trades (P5 live-readiness candidate)" if closed is not None else GAP_NOT_ON_FILE),
    ]

    snaps = _select(db_query, "SELECT max(snapshot_date) AS d, count(DISTINCT strategy_id) AS n FROM strategy_performance_snapshots")
    pvp = _select(db_query, """SELECT count(*) AS trades,
                   round(avg(COALESCE(oa.planned_r, tto.expected_r))::numeric, 2) AS planned_r,
                   round(avg(COALESCE(oa.realized_r, tto.actual_r))::numeric, 2) AS realized_r
              FROM (SELECT id FROM paper_trades WHERE status = 'closed' ORDER BY id DESC LIMIT 100) pt
              LEFT JOIN paper_trade_outcome_analytics oa ON oa.paper_trade_id = pt.id
              LEFT JOIN trade_thesis_outcomes tto ON tto.paper_trade_id = pt.id""")
    drift = _select(db_query, """SELECT pt.strategy_id, round(avg(oa.realized_r - oa.planned_r)::numeric, 2) AS drift_r, count(*) AS n
              FROM paper_trades pt JOIN paper_trade_outcome_analytics oa ON oa.paper_trade_id = pt.id
             WHERE pt.status = 'closed' AND oa.planned_r IS NOT NULL AND oa.realized_r IS NOT NULL
             GROUP BY pt.strategy_id HAVING count(*) >= 3 ORDER BY abs(avg(oa.realized_r - oa.planned_r)) DESC LIMIT 1""")
    p = (pvp or [{}])[0]
    d = (drift or [{}])[0]
    plan_rows = [
        _row("pv-planned", "Planned expectancy (last 100 closed)", f"{_num(p.get('planned_r')):+.2f} R" if _num(p.get("planned_r")) is not None else GAP_NOT_ON_FILE),
        _row("pv-real", "Realized expectancy (last 100 closed)", f"{_num(p.get('realized_r')):+.2f} R" if _num(p.get("realized_r")) is not None else GAP_NOT_ON_FILE),
        _row("pv-drift", "Biggest drift (realized − planned, ≥3 trades)",
             f"{str(d.get('strategy_id')).replace('_', ' ')} · {_num(d.get('drift_r')):+.2f} R" if d.get("strategy_id") else GAP_NOT_ON_FILE, "warn" if d.get("strategy_id") else None),
    ]
    pv_gap = "Plan vs performance could not be read." if pvp is None else None

    trans = _select(db_query, """SELECT strategy_id, from_status, to_status, reason, created_at FROM strategy_state_transitions
             WHERE created_at > now() - interval '30 days' ORDER BY created_at DESC LIMIT 10""")
    reg = _select(db_query, "SELECT status, count(*) AS n FROM strategy_registry GROUP BY status")
    desk_rows = [_row(f"st-{r.get('strategy_id')}-{_iso(r.get('created_at'))}", f"{str(r.get('strategy_id')).replace('_', ' ')} {r.get('from_status')} → {r.get('to_status')}",
                      _date(r.get("created_at")), detail=_detail(f"{r.get('strategy_id')} state change", [
                          ("From", r.get("from_status")), ("To", r.get("to_status")), ("Reason", r.get("reason")), ("When", _date(r.get("created_at")))],
                          "strategy_state_transitions (strategy_weekly_review)")) for r in trans or []]
    desk_rows.insert(0, _row("st-count", "Promotions / pauses (30 days)", _count(len(trans)) if trans is not None else GAP_NOT_ON_FILE))
    for r in sorted(reg or [], key=lambda r: str(r.get("status"))):
        desk_rows.append(_row(f"reg-{r.get('status')}", f"Registered strategies · {r.get('status')}", _count(r.get("n"))))
    desk_gap = ("Strategy state changes could not be read." if trans is None else
                "No strategy changed state in 30 days. The transition writer (strategy-weekly-review, Sundays) records only changes it decides." if not trans else None)

    inc = _select(db_query, """SELECT count(*) AS total, count(*) FILTER (WHERE status = 'ACTIVE') AS active,
                   count(promoted_to_proposal_at) AS promoted, max(updated_at) AS updated_at FROM incubator_universe""")
    i = (inc or [{}])[0]
    incubator_rows = [
        _row("inc-cand", "Candidates", _count(i.get("total")) if inc is not None else GAP_NOT_ON_FILE),
        _row("inc-active", "Active", _count(i.get("active")) if inc is not None else GAP_NOT_ON_FILE),
        _row("inc-prom", "Promoted to a proposal", _count(i.get("promoted")) if inc is not None else GAP_NOT_ON_FILE),
        _row("inc-sched", "Promotion runs", "hourly 07–17 weekdays (incubator-proposal-promoter)"),
    ]
    setup = _select(db_query, "SELECT count(*) AS n, max(snapshot_date) AS d FROM candidate_setup_advisory")
    s = (setup or [{}])[0]
    if setup is not None:
        incubator_rows.append(_row("inc-setup", "Setup advisory rows", _count(s.get("n"))))

    bts = _select(db_query, """SELECT count(*) AS n, max(created_at) AS latest FROM strategy_backtest_results WHERE run_id IS NOT NULL""")
    btr = _select(db_query, """SELECT strategy_id, run_type, total_trades, win_rate, expectancy_r, profit_factor, created_at
              FROM strategy_backtest_results WHERE run_id IS NOT NULL ORDER BY created_at DESC LIMIT 10""")
    b = (bts or [{}])[0]
    bt_rows = [_row(f"bt-{n}", f"{str(r.get('strategy_id')).replace('_', ' ')} · {r.get('run_type') or 'run'} · {_count(r.get('total_trades'))} trades",
                    f"{_num(r.get('expectancy_r')):+.2f} R" if _num(r.get("expectancy_r")) is not None else GAP_NOT_ON_FILE,
                    detail=_detail(f"{r.get('strategy_id')} backtest", [
                        ("Run type", r.get("run_type")), ("Simulated trades", _count(r.get("total_trades"))),
                        ("Win rate", _pct(r.get("win_rate"))), ("Expectancy", r.get("expectancy_r")),
                        ("Profit factor", r.get("profit_factor")), ("Recorded", _date(r.get("created_at")))],
                        "strategy_backtest_results")) for n, r in enumerate(btr or [])]
    bt_rows.insert(0, _row("bt-count", "Backtest results on file", _count(b.get("n")) if bts is not None else GAP_NOT_ON_FILE))

    states = states if states is not None else lane_states(root)
    snap_d = (snaps or [{}])[0].get("d")
    sources = [
        _source("snapshots", "Strategy snapshots", None, STRATEGY_LANES["snapshots"],
                gap=f"Latest snapshot dated {str(snap_d)[:10]} (date only, no time recorded)." if snap_d else "Strategy snapshots are not on file."),
        _source("incubator", f"Incubator · {_count(i.get('total'))} names · {_count(i.get('promoted'))} promoted" if inc else "Incubator",
                i.get("updated_at"), STRATEGY_LANES["incubator"], gap=None if inc else "The incubator could not be read."),
        _source("backtests", f"Backtests · {_count(b.get('n'))}" if bts else "Backtests", b.get("latest"), STRATEGY_LANES["backtests"],
                gap=None if bts else "Backtest results could not be read."),
        _source("readiness", f"Readiness · {_count(closed)} of 2,000 closed trades" if closed is not None else "Paper-trade readiness",
                stats.get("timestamp"), STRATEGY_LANES["readiness"], gap=stats_gap),
        _source("setup", f"Setup advisory · {_count(s.get('n'))} rows" if setup else "Setup advisory", None, STRATEGY_LANES["setup"],
                gap=f"Latest advisory dated {str(s.get('d'))[:10]} (date only)." if s.get("d") else "Setup advisory is not on file."),
    ]
    decisions = _writer_decisions(sources, states, {
        "readiness": "Paper-trade statistics are recomputed by the readiness page read itself; no lane writes them.",
        "setup": "Setup advisory feeds the Incubator advisory column.",
    })
    tabs = {
        "leaderboard": {"panels": [
            _panel("leaderboard", "Leaderboard", board, sub=f"{len(lb)} strategies with closed paper trades", span=2, gap=lb_gap,
                   empty="No strategy has closed paper trades."),
            _panel("readiness", "Paper-trade readiness", readiness, sub="gate to live", gap=stats_gap),
        ]},
        "plan-vs-performance": {"panels": [
            _panel("pvp", "Plan vs performance", plan_rows, sub=f"{_count(p.get('trades'))} closed trades" if pvp else None, span=2, gap=pv_gap),
        ]},
        "planner": {"panels": [
            _panel("planner", "Planner", [_row("pl-open", "Strategy planner (what-if sizing, approvals)", "Classic planner →", "info",
                                               href="/strategy/classic?tab=Planner")],
                   sub="the planner submits plans, so it stays on the classic page",
                   gap="This desk is read-only; plan and approve run on the classic Planner."),
        ]},
        "desk": {"panels": [_panel("desk", "Desk · state changes", desk_rows, sub="last 30 days", span=2, gap=desk_gap)]},
        "incubator": {"panels": [_panel("incubator", "Incubator", incubator_rows, sub="refresh 08:15 weekdays · build Sun 19:00",
                                        gap=None if inc is not None else "The incubator could not be read.")]},
        "backtests": {"panels": [_panel("backtests", "Backtests", bt_rows, sub="Strategy owns backtests (board 13)", span=2,
                                        gap=None if bts is not None else "Backtest results could not be read.")]},
    }
    return _envelope("strategy", now, sources, tabs, decisions, [])


# ── Board 3 · Defense ─────────────────────────────────────────────────────────
DEFENSE_LANES = {
    "posture": ["sector-momentum-engine"],
    "industries": ["industry-momentum-groups"],
    "recommendations": ["defense-recommendations"],
    "stoplights": ["defense-inverse-stoplights"],
    "options": ["options-lifecycle-run"],
    "cash": [],
    "review": [],
}


def defense_payload(*, root: Path, db_query: DbQuery | None = None, now: datetime | None = None,
                    truth: dict | None = None, states: dict | None = None) -> dict:
    """Board 3. Regime, holdings and stops come from ``truth`` (cio_truth.resolve)."""
    now = now or datetime.now(timezone.utc)
    root = Path(root)
    rt = root / "data" / "runtime"
    truth = truth if isinstance(truth, dict) else {}
    states = states if states is not None else lane_states(root)
    momentum, m_gap = _read_json(rt / "sector_momentum_latest.json")
    momentum = momentum if isinstance(momentum, dict) else {}
    industries, i_gap = _read_json(rt / "industry_momentum_latest.json")
    industries = industries if isinstance(industries, dict) else {}
    recs, r_gap = _read_json(rt / "defense_recommendations_latest.json")
    recs = recs if isinstance(recs, dict) else {}
    lights, l_gap = _read_json(rt / "inverse_stoplights_latest.json")
    lights = lights if isinstance(lights, dict) else {}
    options, o_gap = _read_json(rt / "options_lifecycle_latest.json")
    options = options if isinstance(options, dict) else {}
    cash, c_gap = _read_json(rt / "defense_cash_alternatives_latest.json")
    cash = cash if isinstance(cash, dict) else {}
    review, v_gap = _read_json(root / "config" / "promote_criteria.json")
    review = review if isinstance(review, dict) else {}

    regime = truth.get("regime") or {}
    groups = recs.get("groups") if isinstance(recs.get("groups"), dict) else {}
    total_recs = sum(len(v) for v in groups.values() if isinstance(v, list))
    transitions = [t for t in momentum.get("transitions_today") or [] if isinstance(t, dict)]
    act = [
        _row("act-regime", "Market regime (CIO)", str(regime.get("label") or "not on file"),
             detail=_detail("Market regime (CIO record)", [("Regime", regime.get("label")), ("VIX", regime.get("vix")),
                            ("Confidence", regime.get("confidence")), ("As of", _date(regime.get("as_of")))],
                            "cio_truth.regime_for (market_regime_snapshots)")),
        _row("act-trans", "Sector transitions today", _plural(len(transitions), "sector") if momentum else GAP_NOT_ON_FILE,
             "warn" if transitions else None,
             detail=_detail("Sector transitions today", [(f"{t.get('sector')} ({t.get('etf')})", f"{t.get('from')} → {t.get('to')}") for t in transitions[:MAX_ROWS]]
                            or [("Transitions", "none today")], "data/runtime/sector_momentum_latest.json transitions_today",
                            href="/watch?tab=sectors", href_label="Sector detail on Watch › Sectors →") if momentum else None),
        _row("act-recs", "Recommendations by group",
             " · ".join(f"{k.replace('_', ' ')} {len(v)}" for k, v in groups.items() if isinstance(v, list)) or GAP_NOT_ON_FILE,
             detail=_detail("Defense recommendations", [(k.replace("_", " "), f"{len(v)}") for k, v in groups.items() if isinstance(v, list)]
                            + [("Mode", recs.get("mode")), ("Generated", _date(recs.get("generated_at")))],
                            "data/runtime/defense_recommendations_latest.json groups") if groups else None),
        _row("act-intents", "Open intents and execution", "Classic view →", "info", href="/defense/classic"),
        _row("act-sectors", "Sector momentum & leaders", "→ Watch › Sectors", "info", href="/watch?tab=sectors"),
    ]

    positions = [p for p in (truth.get("positions") or {}).get("rows") or [] if isinstance(p, dict)]
    portfolio = truth.get("portfolio") or {}
    stops = truth.get("stops") or {}
    book = []
    # Board 3 "Your book": the counted positions (same set as Home/Risk counts) by stop category from cio_truth.
    has_counted = any(isinstance(p.get("counted"), bool) for p in positions)
    shown = [p for p in positions if p.get("counted")] if has_counted else positions
    for p in sorted(shown, key=lambda p: -(_num(p.get("market_value")) or 0))[:MAX_ROWS]:
        sym = str(p.get("symbol") or "?")
        cat = _stop_category(p)
        # A dated cio_truth note (filled / settled fill) beats the generic category text (2026-10-31 stale V).
        state = p.get("stop_note") if cat in ("filled", "none") and p.get("stop_note") else BOOK_STOP_TEXT[cat]
        dist = next((p.get(k) for k in ("distance_to_stop_pct", "resting_stop_distance_pct", "planned_stop_distance_pct")
                     if _num(p.get(k)) is not None), None)
        book.append(_row(f"bk-{sym}-{p.get('account_id')}", f"{sym} · {p.get('account_label') or p.get('account_id')}",
                         f"{_money(p.get('market_value'))} · {state}",
                         "good" if p.get("broker_protected") else "warn",
                         detail=_detail(f"{sym} · {p.get('account_label') or ''}", [
                             ("Market value", _money(p.get("market_value"))), ("Stop", state),
                             ("Stop source", str(p.get("stop_source") or "none").replace("_", " ")),
                             ("Stop price", p.get("stop_price")), ("Distance to stop", _pct(dist, 2)),
                             ("Defensive score", GAP_NOT_MEASURED), ("Beta", GAP_NOT_MEASURED)],
                             "cio_truth.resolve positions + stops (stop_last_known before stops.json)",
                             href=f"/risk?tab=exposure&detail=position:{p.get('account_id')}:{sym}",
                             href_label="Stop review on Risk →")))
    breakdown = (truth.get("positions") or {}).get("stop_breakdown")
    if isinstance(breakdown, dict):
        def _n(cat):
            return int((breakdown.get(cat) or {}).get("count") or 0)

        def _syms(cat):
            names = [str(s.get("symbol")) for s in (breakdown.get(cat) or {}).get("symbols") or [] if isinstance(s, dict)]
            return ", ".join(f"{n} ×{names.count(n)}" if names.count(n) > 1 else n for n in dict.fromkeys(names))

        values = [(breakdown.get(c) or {}).get("value_usd") for c in ("none", "planned")]
        no_stop = _n("none") + _n("planned")
        book_rows = [
            _row("bk-unprot", "Positions with no broker stop", f"{no_stop:,}" + (f" ({_n('planned')} planned level only)" if _n("planned") else ""),
                 "warn" if no_stop else None, href="/risk?tab=exposure"),
            _row("bk-heat", "Value with no broker stop", _money(sum(values)) if all(_num(v) is not None for v in values) else GAP_NOT_ON_FILE),
            _row("bk-pending", "Stops resting · pending activation", f"{_n('pending_activation'):,}", "warn" if _n("pending_activation") else None),
            _row("bk-filled", "Stops filled · awaiting holdings sync",
                 f"{_n('filled'):,}" + (f" · {_syms('filled')}" if _n("filled") else ""), "warn" if _n("filled") else None),
        ] + ([_row("bk-unknown", "Broker stop, state not recorded", f"{_n('unknown'):,} · {_syms('unknown')}", "warn")] if _n("unknown") else [])
    else:
        book_rows = [
            _row("bk-unprot", "Positions without an active broker stop", _count(stops.get("unprotected_count"))
                 if stops.get("unprotected_count") is not None else GAP_NOT_ON_FILE, "warn" if stops.get("unprotected_count") else None),
            _row("bk-heat", "Unprotected value", _money((truth.get("positions") or {}).get("unprotected_value_usd"))),
        ]
    book_rows += [
        _row("bk-hedged", "Hedged share of book", GAP_NOT_MEASURED),
        _row("bk-exposed", "Most exposed (beta)", GAP_NOT_MEASURED),
    ] + book
    book_gap = (None if positions else "Holdings are not on file in the CIO record.") or None
    if positions:
        book_gap = "Defensive score, beta and hedged share are not computed by any writer; rows are ordered by value."

    light_rows = []
    for c in [c for c in lights.get("candidates") or [] if isinstance(c, dict)][:MAX_ROWS]:
        ls = c.get("lights") if isinstance(c.get("lights"), dict) else {}
        summary = " · ".join(f"{k} {str((v or {}).get('state') or '?')}" for k, v in ls.items())
        reds = sum(1 for v in ls.values() if (v or {}).get("state") == "RED")
        light_rows.append(_row(f"il-{c.get('inverse')}", f"{c.get('inverse')} (inverse {c.get('bench')}, {c.get('leverage')})", summary or GAP_NOT_ON_FILE,
                               "bad" if reds else "good",
                               detail=_detail(f"{c.get('inverse')} · stoplights", [(k, f"{(v or {}).get('state')} — {(v or {}).get('reason') or (v or {}).get('label') or ''}") for k, v in ls.items()]
                                              + [("Max hold (sessions)", c.get("max_hold_sessions")), ("Path dependence", c.get("path_dependence_warning"))],
                                              "data/runtime/inverse_stoplights_latest.json (defense_inverse_stoplights)")))
    short_rows = [_row(f"ss-{n}", str(g.get("title") or "?"), ", ".join(str(i.get("symbol")) for i in g.get("instruments") or [] if isinstance(i, dict)) or GAP_NOT_ON_FILE,
                       detail=_detail(str(g.get("title") or "Short-side idea"), [
                           ("Instruments", ", ".join(f"{i.get('symbol')} ({i.get('kind')})" for i in g.get("instruments") or [] if isinstance(i, dict))),
                           ("Note", "; ".join(str(i.get("note")) for i in g.get("instruments") or [] if isinstance(i, dict) and i.get("note"))),
                           ("Mode", recs.get("mode"))], "data/runtime/defense_recommendations_latest.json groups.short_side"))
                  for n, g in enumerate(g for g in groups.get("short_side") or [] if isinstance(g, dict))][:MAX_ROWS]
    counts = options.get("counts") if isinstance(options.get("counts"), dict) else {}
    opt_rows = [_row("op-open", "Positions tracked", _count(counts.get("open_strategies")) if counts else GAP_NOT_ON_FILE),
                _row("op-act", "Needing action now", _count(counts.get("action_now")) if counts else GAP_NOT_ON_FILE),
                _row("op-link", "Options lifecycle detail", "→ Trading › Options", "info", href="/trading?tab=Options")]
    opt_gap = o_gap or _lane_gap(DEFENSE_LANES["options"], states, "the options lifecycle")
    if opt_gap and options.get("generated_at"):
        opt_gap += f" Last output {_date(options.get('generated_at'))}."
    cash_rows = [_row(f"ca-{c.get('symbol')}", f"{c.get('symbol')} · {c.get('category') or ''}",
                      _pct(((c.get("yield_data") or {}).get("sec_yield") or (c.get("yield_data") or {}).get("div_yield")), 2)
                      if ((c.get("yield_data") or {}).get("sec_yield") or (c.get("yield_data") or {}).get("div_yield")) is not None else "yield not on file",
                      detail=_detail(f"{c.get('symbol')} · {c.get('name') or ''}", [
                          ("Category", c.get("category")), ("SEC yield", (c.get("yield_data") or {}).get("sec_yield")),
                          ("Dividend yield", (c.get("yield_data") or {}).get("div_yield")), ("Score", c.get("total_score")),
                          ("Thesis", c.get("thesis"))], "data/runtime/defense_cash_alternatives_latest.json top3"))
                 for c in (cash.get("top3") or []) if isinstance(c, dict)]
    cash_rows.insert(0, _row("ca-upd", "Last update", _date(cash.get("generated_at")), "warn"))
    cash_gap = c_gap or _lane_gap(DEFENSE_LANES["cash"], states, "this file")

    review_rows = [
        _row("rv-locked", "Criteria locked", "yes" if review.get("criteria_locked") else "no" if review else GAP_NOT_ON_FILE),
        _row("rv-lock", "Last lock", _date(review.get("locked_at")), "warn"),
        _row("rv-amend", "Amendments", _count(len(review.get("amendments") or [])) if review else GAP_NOT_ON_FILE),
        _row("rv-dec", "Decisions recorded", _count(len(review.get("decisions") or [])) if review else GAP_NOT_ON_FILE),
        _row("rv-open", "Review console (rate, lock, decide)", "Classic view →", "info", href="/defense/classic"),
    ]

    sources = [
        _source("posture", "Sector posture", momentum.get("generated_at"), DEFENSE_LANES["posture"], gap=m_gap, max_age_hours=26),
        _source("industries", f"Industries · {len(industries.get('industries') or [])}" if industries else "Industries",
                industries.get("captured_at"), DEFENSE_LANES["industries"], gap=i_gap),
        _source("recommendations", f"Recommendations · {total_recs}" if recs else "Recommendations",
                recs.get("generated_at"), DEFENSE_LANES["recommendations"], gap=r_gap),
        _source("stoplights", "Inverse stoplights", lights.get("generated_at"), DEFENSE_LANES["stoplights"], gap=l_gap),
        _source("options", "Options lifecycle", options.get("generated_at"), DEFENSE_LANES["options"], gap=o_gap),
        _source("cash", "Cash alternatives", cash.get("generated_at"), DEFENSE_LANES["cash"], gap=c_gap),
        _source("review", "Review console", None, DEFENSE_LANES["review"],
                gap=v_gap or (f"Last lock {_date(review.get('locked_at'))} (recorded without a time zone, so only the date is shown)." if review.get("locked_at") else "No lock on file.")),
    ]
    decisions = _writer_decisions(sources, states, {
        "options": "The options lifecycle panel shows the last output of a paused writer.",
        "cash": "Cash alternatives yields are frozen at their last manual run.",
    })
    if review.get("locked_at"):
        decisions.append({"id": "review-console", "title": f"Review console last locked {_date(review.get('locked_at'))}",
                          "detail": "Keep it as a log or retire it (board 3)."})
    tabs = {
        "where-to-act": {"panels": [
            _panel("act", "Where to act", act, sub="posture + transitions since yesterday", span=2, gap=m_gap or r_gap),
            _panel("act-owned", "Owned elsewhere — linked, not repeated", [
                _row("own-sectors", "Sector momentum & leaders", "→ Watch › Sectors", "info", href="/watch?tab=sectors"),
                _row("own-reports", "Briefs and digests", "→ Reports", "info", href="/reports"),
            ], sub="board 13"),
        ]},
        "your-book": {"panels": [_panel("book", "Your book", book_rows, sub="held names · stops from the CIO record", span=2, gap=book_gap)]},
        "hedges": {"panels": [
            _panel("stoplights", "Inverse-ETF hedges", light_rows, sub=f"stoplights {_date(lights.get('generated_at'))}", gap=l_gap,
                   empty="No inverse candidates on file."),
            _panel("short", "Short side", short_rows, sub=f"{recs.get('mode') or ''} recommendations".strip(), gap=r_gap,
                   empty="No short-side ideas in the latest run."),
            _panel("options", "Options protection", opt_rows, sub="lifecycle positions", gap=opt_gap),
            _panel("cash", "Cash alternatives", cash_rows, sub="T-bills / money market yields", gap=cash_gap),
        ]},
        "review-log": {"panels": [_panel("review", "Review log", review_rows, sub="config/promote_criteria.json", span=2, gap=v_gap)]},
    }
    return _envelope("defense", now, sources, tabs, decisions, [])


# ── Board 4 · Agents ──────────────────────────────────────────────────────────
AGENT_RUNTIME_LANES = ["tradeai-agent-runtime-alex", "tradeai-agent-runtime-atlas", "tradeai-agent-runtime-concierge",
                       "tradeai-agent-runtime-hermes", "tradeai-agent-runtime-morgan", "tradeai-agent-runtime-pulse",
                       "tradeai-agent-runtime-steph"]
AGENTS_LANES = {
    "pipeline": ["run-watchlist-agent-jobs-offpeak"],
    "timeline": AGENT_RUNTIME_LANES,
    "memory": ["cio-memory-shadow-measure"],
    "calibration": ["agent-calibration-engine"],
    "weekly": ["multi-tier-trade-reviewer-weekly"],
    "lessons": ["advisory-lessons-reflect"],
}
TAIL_BYTES = 2 * 1024 * 1024
JOURNAL_SCAN_LIMIT = 250_000
MEMORY_READ_LIMIT = 32 * 1024 * 1024
# Day-volume window over the run journals: file mtime picks candidates (with slack), the record ``ts`` decides.
RUN_WINDOW_HOURS = 24
RUN_WINDOW_OPEN_LIMIT = 10_000

# Gate-B sentinel. Mirrors the "error" text returned by ``_build_governed_gateway_provider`` in
# scripts/agent_runtime_live_providers.py (not imported: this module stays side-effect free).
# tests/test_desks_a_20261025.py pins the two texts together, so a drift fails CI.
# A run carrying exactly this text never contacted a provider: it is "no model by design", not a model error.
GATE_B_PLACEHOLDER = ("PROVIDER_BLOCKED: Financial agent must route through governed gateway. "
                      "Direct provider calls removed in Gate-B.")
GATE_B_STATE = "No model by design (Gate-B: reasoning goes through the CIO governed bridge)"
RUN_TIMER_UNIT = "tradeai-agent-runtime@"


def run_model_state(run: dict) -> str:
    """``none`` (no model error), ``gate_b`` (the Gate-B placeholder, exact text) or ``error`` (a real model error)."""
    err = run.get("model_error")
    if not err:
        return "none"
    return "gate_b" if str(err).strip() == GATE_B_PLACEHOLDER else "error"


def _tail_records(path: Path, limit: int = TAIL_BYTES) -> tuple[list[dict], str | None]:
    """Parse whole JSON lines from the last ``limit`` bytes; the oldest partial line is dropped."""
    try:
        with Path(path).open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - limit))
            raw = handle.read(limit)
    except FileNotFoundError:
        return [], f"{Path(path).name} is not on file."
    except OSError as exc:
        return [], f"{Path(path).name} could not be read ({type(exc).__name__})."
    lines = raw.split(b"\n")
    if size > limit:
        lines = lines[1:]
    out = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out, None


def run_timeline(journal_root: Path, *, limit: int = MAX_ROWS, now: datetime | None = None) -> dict:
    """Run timeline from the producers' own journals.

    Board 4 fix: live runtime producers write one JSONL per run under
    data/runtime/agent_runtime_journals/<agent>/<run_id>.jsonl and no longer insert
    ``agentic_runtime.agent_runs`` (the no-op ``record_shadow_outcome`` hook since
    aedac0989), so the old reader stopped at early August. File modification time
    only chooses which files to open; the run clock is the record's own ``ts``.
    """
    root = Path(journal_root)
    if not root.is_dir():
        return {"runs": [], "count": None, "by_agent": {}, "newest": None, "window": None,
                "gap": "The agent run journals are not on file."}
    cached = _cached_journal_listing(root, now)
    if cached is not None:
        entries, by_agent, scanned = cached
    else:
        entries, by_agent, scanned = _scan_journal_listing(root)
    if isinstance(entries, str):
        return {"runs": [], "count": None, "by_agent": {}, "newest": None, "window": None, "gap": entries}
    entries.sort(key=lambda e: e[0], reverse=True)
    runs = []
    for _mtime, f in entries[: limit * 3]:
        rows, _gap = _tail_records_cached(f)
        row = rows[-1] if rows else None
        if row and _time(row.get("ts")):
            runs.append(row)
    runs.sort(key=lambda r: _time(r.get("ts")), reverse=True)
    return {"runs": runs[:limit], "count": sum(by_agent.values()), "by_agent": by_agent,
            "newest": runs[0].get("ts") if runs else None, "window": _run_window(entries, now),
            "gap": "Journal scan stopped at the listing limit; counts are partial." if scanned > JOURNAL_SCAN_LIMIT else None}


# ── journal listing / tail caches (perf + memory 2026-10-25) ───────────────────────────────────────────────────
# The run journals are one write-once JSONL per run (~91k files, ~500 B each). Every cold Agents desk build listed
# and stat()ed all of them and built ~91k Path objects (~1.5-2 s, the bulk of a ~150 MB per-request peak). Now each
# agent directory's {name: mtime} is kept and refreshed only when the directory itself changes (a new run file
# changes the directory mtime; only the new names are stat()ed), and only the files the timeline actually opens
# (newest ``MAX_ROWS * 3`` plus the 24 h window candidates) become Paths. Parsed tails are cached per
# (path, mtime_ns, size), bounded, so an unchanged run file is never re-read.
_LISTING_MAX_DIRS = 64
_TAIL_CACHE_MAX = 4096
# Plain dicts (this module keeps its stdlib-only import set, see tests/test_desks_a_20261025.py): each read or
# write is one dict operation, so concurrent requests at worst redo a listing; insertion order gives LRU eviction.
_LISTING: dict[str, tuple[int, int, int, dict[str, float], list[tuple[float, str]]]] = {}
_TAILS: dict[tuple[str, int, int], tuple[list[dict], str | None]] = {}


def _agent_dir_listing(agent_dir: Path) -> tuple[int, int, dict[str, float], list[tuple[float, str]]] | None:
    """(entries in the directory, .jsonl names, {jsonl name: mtime}, newest MAX_ROWS*3 (mtime, name)) — refreshed
    only when the directory mtime changes."""
    try:
        dir_sig = agent_dir.stat().st_mtime_ns
    except OSError:
        return None
    key = str(agent_dir)
    hit = _LISTING.get(key)
    if hit is not None and hit[0] == dir_sig:
        return hit[1], hit[2], hit[3], hit[4]
    try:
        entries = list(agent_dir.iterdir())
    except OSError:
        return None
    old = hit[3] if hit is not None else {}
    mtimes: dict[str, float] = {}
    n_jsonl = 0
    for f in entries:
        if f.suffix != ".jsonl":
            continue
        n_jsonl += 1
        name = f.name
        if name in old:
            mtimes[name] = old[name]
            continue
        try:
            mtimes[name] = f.stat().st_mtime
        except OSError:
            continue
    top = sorted(((mt, name) for name, mt in mtimes.items()), reverse=True)[: MAX_ROWS * 3]
    _LISTING.pop(key, None)
    _LISTING[key] = (dir_sig, len(entries), n_jsonl, mtimes, top)
    while len(_LISTING) > _LISTING_MAX_DIRS:
        _LISTING.pop(next(iter(_LISTING)), None)
    return len(entries), n_jsonl, mtimes, top


def _cached_journal_listing(root: Path, now: datetime | None):
    """(entries, by_agent, scanned) like ``_scan_journal_listing`` but from the per-directory cache, with
    ``entries`` holding only the files ``run_timeline`` / ``_run_window`` can use. None = use the full scan
    (listing limit reached or a directory unreadable), so partial-scan behaviour is unchanged."""
    try:
        agent_dirs = [d for d in sorted(root.iterdir()) if d.is_dir()]
    except OSError:
        return None
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=RUN_WINDOW_HOURS) - timedelta(hours=2)).timestamp()
    by_agent: dict[str, int] = {}
    scanned = 0
    keep: list[tuple[float, str, str]] = []
    newest: list[tuple[float, str, str]] = []
    for agent_dir in agent_dirs:
        got = _agent_dir_listing(agent_dir)
        if got is None:
            return None
        n_entries, n_jsonl, mtimes, top = got
        scanned += n_entries
        if scanned > JOURNAL_SCAN_LIMIT:
            return None
        by_agent[agent_dir.name] = n_jsonl
        d = str(agent_dir)
        for name, mt in mtimes.items():
            if mt >= cutoff:
                keep.append((mt, d, name))
        newest.extend((mt, d, name) for mt, name in top)
    chosen = {(d, n): mt for mt, d, n in keep}
    for mt, d, n in sorted(newest, reverse=True)[: MAX_ROWS * 3]:
        chosen[(d, n)] = mt
    entries = [(mt, Path(d) / n) for (d, n), mt in chosen.items()]
    return entries, by_agent, scanned


def _tail_records_cached(path: Path, limit: int = 64 * 1024) -> tuple[list[dict], str | None]:
    """``_tail_records`` cached per (path, mtime_ns, size). Callers treat the rows as read-only."""
    try:
        st = Path(path).stat()
    except OSError:
        return _tail_records(path, limit)
    key = (str(path), st.st_mtime_ns, st.st_size)
    hit = _TAILS.pop(key, None)
    if hit is None:
        hit = _tail_records(path, limit)
    _TAILS[key] = hit  # (re)inserted last = most recently used
    while len(_TAILS) > _TAIL_CACHE_MAX:
        _TAILS.pop(next(iter(_TAILS)), None)
    return hit


def _scan_journal_listing(root: Path):
    """The original full listing: (entries, by_agent, scanned), or (gap text, {}, 0) when unreadable."""
    entries, by_agent, scanned = [], {}, 0
    try:
        for agent_dir in sorted(root.iterdir()):
            if not agent_dir.is_dir():
                continue
            n = 0
            for f in agent_dir.iterdir():
                scanned += 1
                if scanned > JOURNAL_SCAN_LIMIT:
                    break
                if f.suffix == ".jsonl":
                    n += 1
                    try:
                        entries.append((f.stat().st_mtime, f))
                    except OSError:
                        continue
            by_agent[agent_dir.name] = n
    except OSError as exc:
        return f"The agent run journals could not be listed ({type(exc).__name__}).", {}, 0
    return entries, by_agent, scanned


def _run_window(entries: list[tuple[float, Path]], now: datetime | None) -> dict:
    """Per-agent run volume over the last RUN_WINDOW_HOURS by record ``ts``.

    File mtime only picks candidates (with 2 h slack); each candidate's own ``ts`` decides membership.
    Counts per agent: runs, Gate-B placeholder runs, real model errors, and runs with retrieval_count 0.
    """
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(hours=RUN_WINDOW_HOURS)
    cutoff = (start - timedelta(hours=2)).timestamp()
    candidates = [f for mtime, f in entries if mtime >= cutoff]
    agents: dict[str, dict[str, int]] = {}
    for f in candidates[:RUN_WINDOW_OPEN_LIMIT]:
        rows, _gap = _tail_records_cached(f)
        for r in rows:
            at = _time(r.get("ts"))
            if not at or not (start < at <= now):
                continue
            a = agents.setdefault(str(r.get("agent_id") or f.parent.name),
                                  {"runs": 0, "gate_b": 0, "error": 0, "no_retrieval": 0})
            a["runs"] += 1
            state = run_model_state(r)
            if state != "none":
                a[state] += 1
            if _num(r.get("retrieval_count")) == 0:
                a["no_retrieval"] += 1
    return {"hours": RUN_WINDOW_HOURS, "agents": dict(sorted(agents.items())),
            "partial": len(candidates) > RUN_WINDOW_OPEN_LIMIT}


def _memory_summary(path: Path, admissions: Path, now: datetime) -> dict:
    try:
        size = Path(path).stat().st_size
    except FileNotFoundError:
        return {"gap": "The durable memory ledger is not on file."}
    except OSError as exc:
        return {"gap": f"The durable memory ledger could not be read ({type(exc).__name__})."}
    if size > MEMORY_READ_LIMIT:
        return {"gap": "The durable memory ledger exceeds the desk read limit; record count not measured."}
    latest: dict[str, dict] = {}
    with Path(path).open("rb") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("memory_id"):
                latest[str(row["memory_id"])] = row
    active = [r for r in latest.values() if str(r.get("status") or "").upper() == "ACTIVE"]
    newest = max((r.get("created_at") for r in latest.values() if _time(r.get("created_at"))), key=_time, default=None)
    adm, adm_gap = _tail_records(admissions)
    day = now.date()
    today = [a for a in adm if a.get("display_status") == "ADMITTED" and _time(a.get("admitted_at")) and _time(a.get("admitted_at")).date() == day]
    types: dict[str, int] = {}
    for r in active:
        types[str(r.get("memory_type") or "unknown")] = types.get(str(r.get("memory_type") or "unknown"), 0) + 1
    return {"records": len(latest), "active": len(active), "newest": newest, "types": types,
            "admitted_today": None if adm_gap else len(today), "admission_gap": adm_gap,
            "admitted_today_partial": bool(adm) and not adm_gap}


RUN_SOURCE = "data/runtime/agent_runtime_journals/<agent>/<run_id>.jsonl (agent_runtime_live_providers)"
GATE_B_SOURCE = ("scripts/agent_runtime_live_providers.py _build_governed_gateway_provider (Gate-B placeholder); "
                 "counts from data/runtime/agent_runtime_journals record ts, model_error, retrieval_count")


def _run_row(r: dict) -> dict:
    state = run_model_state(r)
    model = ([("Model", GATE_B_STATE), ("Recorded placeholder", r.get("model_error"))] if state == "gate_b"
             else [("Model error", r.get("model_error") or "none recorded")])
    return _row(f"run-{r.get('run_id')}", f"{r.get('agent_id')} · {str(r.get('job_type') or '').replace('_', ' ')}",
                _date(r.get("ts")), {"error": "bad", "gate_b": "info"}.get(state),
                detail=_detail(f"{r.get('agent_id')} run {r.get('run_id')}", [
                    ("Agent", r.get("agent_id")), ("Job", r.get("job_type")), ("Objective", r.get("objective")),
                    ("Environment", r.get("environment")), ("Retrievals", r.get("retrieval_count")),
                    *model, ("Run time", _date(r.get("ts"))), ("Authority", r.get("authority"))], RUN_SOURCE))


def _gate_b_units(agents: dict) -> str:
    names = sorted(agents)
    return f"{RUN_TIMER_UNIT}{names[0]}" if len(names) == 1 else f"{RUN_TIMER_UNIT}{{{','.join(names)}}}"


def _gate_b_row(n: int, of: int, agents: dict, window: dict) -> dict:
    hours = window.get("hours") or RUN_WINDOW_HOURS
    fields = [("State", GATE_B_STATE), ("Recorded text", GATE_B_PLACEHOLDER), ("Provider contacted", "no"),
              ("Newest runs with this state", f"{n} of {of}")]
    for a, c in agents.items():
        fields.append((f"{a} · last {hours} h", f"{_plural(c['runs'], 'run')} · {c['gate_b']:,} no model · "
                                                f"{c['no_retrieval']:,} with retrieval_count 0"))
    if window.get("partial"):
        fields.append(("Coverage", f"partial: the window opened the newest {RUN_WINDOW_OPEN_LIMIT:,} journal files"))
    return _row("run-gate-b", "No model by design", f"{n} of {of} newest runs", "info",
                detail=_detail(GATE_B_STATE, fields, GATE_B_SOURCE))


def _gate_b_decision(agents: dict, window: dict) -> dict:
    hours = window.get("hours") or RUN_WINDOW_HOURS
    runs = sum(c["runs"] for c in agents.values())
    gate_b = sum(c["gate_b"] for c in agents.values())
    empty = sum(c["no_retrieval"] for c in agents.values())
    partial = " Counts are partial (journal open limit reached)." if window.get("partial") else ""
    return {"id": "runs-gate-b-shadow",
            "title": f"{_gate_b_units(agents)} timers: {_plural(runs, 'run')} in the last {hours} h, no model by design",
            "detail": (f"{gate_b:,} of these runs carry the Gate-B placeholder: no provider is contacted and no AI finding is "
                       f"produced; {empty:,} recorded retrieval_count 0. The choice is to pause or slow these timers, or to "
                       f"wire these agents to the CIO governed bridge.{partial}"),
            "href": "/agents?tab=runtime&detail=timeline:run-gate-b"}


def agents_payload(*, root: Path, db_query: DbQuery | None = None, now: datetime | None = None,
                   states: dict | None = None, data_root: Path | None = None) -> dict:
    """Board 4. ``data_root`` is the tree holding data/ (defaults to ``root``)."""
    now = now or datetime.now(timezone.utc)
    root = Path(root)
    data = Path(data_root or root) / "data"
    states = states if states is not None else lane_states(root)

    jobs = _select(db_query, """SELECT count(*) FILTER (WHERE status = 'completed') AS completed,
                   count(*) FILTER (WHERE status = 'failed') AS failed,
                   count(*) FILTER (WHERE status IN ('queued', 'pending')) AS queued,
                   count(*) FILTER (WHERE status = 'processing') AS processing,
                   count(*) AS total, max(completed_at) AS newest
              FROM watchlist_agent_jobs WHERE created_at > now() - interval '24 hours'""")
    j = (jobs or [{}])[0]
    runtime_registered = [l for l in (states or {}) if l.startswith("tradeai-agent-runtime-")]
    runtime_active = [l for l in runtime_registered if (states or {}).get(l) == "ACTIVE"]
    timeline = run_timeline(data / "runtime" / "agent_runtime_journals", now=now)
    runtime_rows = [
        _row("rt-done", "Jobs completed (24 h)", _count(j.get("completed")) if jobs else GAP_NOT_ON_FILE),
        _row("rt-failed", "Failed (24 h)", _count(j.get("failed")) if jobs else GAP_NOT_ON_FILE, "bad" if (_num(j.get("failed")) or 0) > 0 else None),
        _row("rt-queued", "Queued (24 h)", _count(j.get("queued")) if jobs else GAP_NOT_ON_FILE),
        _row("rt-catalog", "Agent runtime lanes", f"{len(runtime_registered)} registered · {len(runtime_active)} active" if states else GAP_NOT_ON_FILE),
    ]
    run_rows = [_run_row(r) for r in timeline["runs"]]
    run_rows.insert(0, _row("run-total", "Runs on file", _count(timeline["count"]) if timeline["count"] is not None else GAP_NOT_ON_FILE))
    states_newest = [run_model_state(r) for r in timeline["runs"]]
    blocked = states_newest.count("error")
    gate_b = states_newest.count("gate_b")
    window = timeline.get("window") or {}
    gate_b_agents = {a: c for a, c in (window.get("agents") or {}).items() if c["gate_b"]}
    if gate_b:
        run_rows.insert(1, _gate_b_row(gate_b, len(timeline["runs"]), gate_b_agents, window))
    timeline_gap = timeline["gap"] or (f"{blocked} of the {len(timeline['runs'])} newest runs recorded a model error." if blocked else None)

    cal = _select(db_query, """SELECT DISTINCT ON (agent_name) agent_name, brier_score, accuracy, resolved, low_sample_size, created_at
              FROM agent_calibration_windows ORDER BY agent_name, created_at DESC""")
    scored = [r for r in cal or [] if _num(r.get("brier_score")) is not None and not r.get("low_sample_size")]
    best = min(scored, key=lambda r: _num(r["brier_score"]), default=None)
    worst = max(scored, key=lambda r: _num(r["brier_score"]), default=None)
    cal_newest = max((r.get("created_at") for r in cal or [] if _time(r.get("created_at"))), key=_time, default=None)
    cal_rows = [
        _row("cal-last", "Last run", _date(cal_newest) if cal else GAP_NOT_ON_FILE),
        _row("cal-best", "Best calibrated (lowest Brier)", f"{best['agent_name']} · {_num(best['brier_score']):.3f}" if best else GAP_NOT_MEASURED),
        _row("cal-worst", "Worst calibrated (highest Brier)", f"{worst['agent_name']} · {_num(worst['brier_score']):.3f}" if worst else GAP_NOT_MEASURED,
             "warn" if worst else None),
    ] + [_row(f"cal-{r.get('agent_name')}", str(r.get("agent_name")),
              f"Brier {_num(r.get('brier_score')):.3f}" if _num(r.get("brier_score")) is not None else "Brier not measured",
              detail=_detail(f"{r.get('agent_name')} · calibration", [
                  ("Brier score", r.get("brier_score")), ("Accuracy", r.get("accuracy")), ("Resolved", r.get("resolved")),
                  ("Low sample", "yes" if r.get("low_sample_size") else "no"), ("Window recorded", _date(r.get("created_at")))],
                  "agent_calibration_windows (agent_calibration_engine)"))
           for r in (cal or [])[:MAX_ROWS]]
    cal_gap = "Calibration windows could not be read." if cal is None else (
        "No agent has enough resolved outcomes for a Brier score." if cal and not scored else None)

    lessons, lessons_gap = _tail_records(data / "runtime" / "advisory_kb_lessons.jsonl")
    newest_lesson = lessons[-1] if lessons else {}
    weekly = _select(db_query, "SELECT max(created_at) AS newest, count(*) AS n FROM paper_trade_multi_reviews WHERE created_at > now() - interval '30 days'")
    weekly_all = _select(db_query, "SELECT max(created_at) AS newest FROM paper_trade_multi_reviews")
    w = (weekly or [{}])[0]
    w_newest = (weekly_all or [{}])[0].get("newest")
    learning_rows = [
        _row("ln-newest", "Newest lesson appended", _date(newest_lesson.get("ts") or newest_lesson.get("created_at")) if lessons else GAP_NOT_ON_FILE,
             detail=_detail("Newest lesson", [("Title", newest_lesson.get("title")), ("Status", newest_lesson.get("status")),
                                              ("Symbols", ", ".join(newest_lesson.get("symbols") or [])), ("Applications", newest_lesson.get("applications")),
                                              ("Ratified by", newest_lesson.get("ratified_by")), ("Recorded", _date(newest_lesson.get("ts")))],
                            "data/runtime/advisory_kb_lessons.jsonl (last appended record)") if lessons else None),
        _row("ln-weekly", "Trade reviews (30 days)", _count(w.get("n")) if weekly else GAP_NOT_ON_FILE),
        _row("ln-weekly-newest", "Newest trade review", _date(w_newest) if weekly_all else GAP_NOT_ON_FILE),
        _row("ln-classic", "Lesson detail, applications and authority", "Classic view →", "info", href="/agents/classic"),
    ]

    mem = _memory_summary(data / "cio" / "aif_memory.jsonl", data / "cio" / "aif_memory_admissions.jsonl", now)
    memory_rows = [] if mem.get("gap") else [
        _row("mem-records", "Records", _count(mem["records"])),
        _row("mem-active", "Active", _count(mem["active"])),
        _row("mem-today", "Admitted today", _count(mem["admitted_today"]) if mem.get("admitted_today") is not None else GAP_NOT_ON_FILE),
    ] + [_row(f"mem-type-{k}", f"Active · {k.replace('_', ' ').lower()}", _count(v)) for k, v in sorted(mem["types"].items(), key=lambda kv: -kv[1])[:6]]
    mem_gap = mem.get("gap") or ("Admitted today counts the newest 2 MB of the admission log." if mem.get("admitted_today_partial") else mem.get("admission_gap"))

    cases, cases_gap = _tail_records(data / "cio" / "cio_production_cases.jsonl")
    promo, promo_gap = _read_json(data / "cio" / "maturity_promotions.json")
    case_rows = [_row(f"case-{n}", f"{c.get('symbol') or '—'} · {str(c.get('event_type') or '').replace('_', ' ').lower()}", _date(c.get("occurred_at")),
                      detail=_detail(f"Case {c.get('case_id')}", [("Event", c.get("event_type")), ("Symbol", c.get("symbol")),
                                                                  ("Decision", c.get("decision_id")), ("Source", c.get("source")),
                                                                  ("Auto-promoted", c.get("auto_promoted")), ("Occurred", _date(c.get("occurred_at")))],
                                     "data/cio/cio_production_cases.jsonl"))
                 for n, c in enumerate(reversed(cases[-MAX_ROWS:]))]
    promo_rows = [_row("pr-snapshot", "Promotion snapshot", "on file" if isinstance(promo, dict) else GAP_NOT_ON_FILE,
                       None if isinstance(promo, dict) else "warn")]

    legacy = [
        _row("lg-workflow", "Workflow (jobs, handoffs, debates)", "Legacy analytics below", "info"),
        _row("lg-classic", "Classic Agents page", "Classic view →", "info", href="/agents/classic"),
    ]
    sources = [
        _source("summary", "Agent runtime lanes", None, [],
                gap=None if states else "The lane registry could not be read."),
        _source("pipeline", f"Pipeline · {_count(j.get('total'))} jobs / 24 h" if jobs else "Pipeline", j.get("newest"), AGENTS_LANES["pipeline"],
                gap=None if jobs else "Agent jobs could not be read."),
        _source("memory", f"Memory · {_count(mem.get('records'))} records" if not mem.get("gap") else "Memory", mem.get("newest"),
                AGENTS_LANES["memory"], gap=mem.get("gap")),
        _source("calibration", "Calibration · weekly Sun 12:00", cal_newest, AGENTS_LANES["calibration"], gap=cal_gap if cal is None else None),
        _source("timeline", "Run timeline", timeline["newest"], AGENTS_LANES["timeline"], gap=timeline["gap"]),
        _source("lessons", "Lessons", newest_lesson.get("ts") if lessons else None, AGENTS_LANES["lessons"], gap=lessons_gap),
        _source("weekly", "Weekly learning", w_newest, AGENTS_LANES["weekly"], gap=None if weekly_all else "Trade reviews could not be read."),
    ]
    sources[0]["gap"] = sources[0]["gap"] or "Lane counts come from config/lane_registry.json; it carries no update time."
    decisions = _writer_decisions(sources, states, {
        "lessons": "The advisory lesson store feeds the Learning tab.",
        "weekly": "Weekly trade reviews feed the Learning tab.",
    })
    if blocked:
        decisions.append({"id": "runs-model-error", "title": f"{_plural(blocked, 'recent agent run')} recorded a model error",
                          "detail": "Open a run in the Run timeline for the recorded error."})
    if gate_b_agents:
        decisions.append(_gate_b_decision(gate_b_agents, window))
    tabs = {
        "runtime": {"panels": [
            _panel("runtime", "Runtime", runtime_rows, sub="pipeline, last 24 h", span=2, gap=None if jobs else "Agent jobs could not be read."),
            _panel("timeline", "Run timeline", run_rows, sub="newest runs from the producer journals", gap=timeline_gap),
        ]},
        "learning": {"panels": [_panel("learning", "Learning", learning_rows, sub="lessons + trade reviews (Evidence merged here)", span=2,
                                       gap=lessons_gap)]},
        "calibration": {"panels": [_panel("calibration", "Calibration", cal_rows, sub="Sun 12:00 weekly", span=2, gap=cal_gap)]},
        "memory": {"panels": [_panel("memory", "Memory", memory_rows, sub=f"newest {_date(mem.get('newest'))}" if mem.get("newest") else None,
                                     span=2, gap=mem_gap)]},
        "promotion-cases": {"panels": [
            _panel("cases", "Cases", case_rows, sub="newest production case events", span=2, gap=cases_gap, empty="No cases on file."),
            _panel("promotions", "Promotion", promo_rows, gap=promo_gap),
        ]},
        "legacy-analytics": {"panels": [_panel("legacy", "Legacy analytics", legacy, sub="roster · calibration · workflow · weekly learning")]},
    }
    return _envelope("agents", now, sources, tabs, decisions, [])


def build(desk: str, **kwargs) -> dict:
    if desk not in DESKS:
        raise ValueError(f"unknown desk {desk!r}")
    return {"reentry": reentry_payload, "strategy": strategy_payload,
            "defense": defense_payload, "agents": agents_payload}[desk](**kwargs)
