"""Trade journey — the record behind TradeInView (operator directive 2026-10-22). Read-only. Zero provider calls.

Operator, 2026-10-22, verbatim: "navn was one of the top picks with the highest conviction. I got into it a few days
ago. I got stopped out today. I want to make sure that the trade and view actually tracks where that stock came from.
I didn't pick it on my own. It came from internal. It examines the ups and downs and what was the cause of getting out
and advises me on when to get back in. All on the same data backend. Not a separate work stream."

What it returns: one row per trade (open positions and round trips closed in the window) with

* **origin** — where the idea came from: an internal surface (which one, its rank and conviction when the trade was
  entered, the CIO entry state that called it ready) or the operator's own pick, or "unknown" when no link can be
  made. Never claims "your own trade" without a recorded link that says so;
* **timeline** — origin recommendation → entry fill → each stop level change → conviction / stance changes while held
  → exit fill and its cause;
* **exit cause** — stop-out, trailing-stop ratchet, target, manual, or "stop likely filled — not yet confirmed"
  (deterministic rules over fills and observed stops; see ``classify_exit``);
* **review** — facts first (entry, exit, high/low while held, giveback, stop raises, conviction then and now); model
  prose only when a stored advisory exists, labelled advisory with its model;
* **re-entry** — the deterministic re-entry desk row (the SAME record the Watch page's "Re-entry near" lane reads:
  ``data/runtime/reentry_decision_desk_latest.json``, written by ``reentry_decision_desk.build_decision_desk``): its
  conditions, zone / invalidation / target reference levels, distance, plus the reclaim of the exit price as a
  reference level, and a seed for the existing Set-alert form;
* **conflicts** — every disagreement between inputs, both values, both sources, both times. Shown, never resolved here
  (AGENTS.md §26.5).

Where the record comes from (AGENTS.md §26.1, §26.3):

* **The CIO prospect projection, when its store is live.** ``lib.data_broker.cio_prospect.get_prospects`` (built on
  its own branch, docs/architecture/CIO_PROSPECT_DATA_FOUNDATION.md §5.3). When it imports and reads the live store
  (``source.kind == "store"``) each journey takes the prospect's stage, conviction, stance and conflicts, and — when
  the prospect record carries the position lifecycle (``cio_prospect_lifecycle`` on PR #1944: ``origin``,
  ``position_lifecycle``, ``post_exit_review``, ``reentry_advice``, ``lifecycle_events``) — those blocks, mapped into this
  row's shape (``from_cio_prospect``). A shadow build is not read: switching a surface onto it is §17.
* **Until then, an interim adapter** builds the identical shape from today's sources, and every payload says so
  (``interim = True``, ``source_label = INTERIM_LABEL``):

  - closed trades: ``schwab_round_trips`` (canary rows excluded), the journal's round-trip table;
  - open trades: ``lib.portfolio_positions.load_store`` (the one accessor of the holdings_accounts store) for the
    position, ``trade_transactions`` buys after the last sell for the entry fill;
  - origin: ``trade_recommendation_links`` + ``recommendation_registry`` (learning loop PR1) when present; the CIO
    opportunity history (``cio_opportunity_assessments.jsonl`` via ``CIOOpportunityStore``; registry domain
    ``opportunity_assessment``) for rank / conviction / stance at entry; ``cio_entry_states`` for the CIO entry call;
  - stops: ``stop_last_known`` (one durable row per observed stop order, captured_at; ``stop_lifecycle`` is rebuilt
    every scan and cannot hold history);
  - price band: the ``ohlc_bars`` projection (``market_ohlcv_bars`` daily, ``ticker_prices`` closes fallback);
  - re-entry: the re-entry desk snapshot (above); advisory prose: ``ui_prefs`` ``portfolio.reentry.llm_insights.v1``.

``MBI_BEHAVIOR = 0``: nothing here sizes, orders, stops or weights. Levels carry ``_ref`` keys and fill sizes are
``fill_qty`` so no payload key is a ``cio_instrument_record.BEHAVIOR_FIELDS`` name (a test pins it). The re-entry
block is advice for the operator's decision; Set alert reuses the existing advisory Watch-alert form.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

SCHEMA = "TradeJourneys@v1"
ROW_SCHEMA = "TradeJourney@v1"
INTERIM_LABEL = "interim — CIO prospect store not live"
ROUND_TRIPS = "schwab_round_trips"  # the journal round-trip TABLE (a store name for provenance), not a broker
CIO_LABEL = "CIO prospect record · 1 writer"

#: recommendation_registry.source → the surface the operator saw it on.
SURFACE_OF_SOURCE: dict[str, str] = {
    "cio_opportunity": "Home",
    "paper_trade_proposal": "Proposals",
    "scalp_alert": "Trade AI",
    "entry_alert": "Entry alert",
}
SURFACE_HREF: dict[str, str] = {"Home": "/v3/", "Proposals": "/v3/trading?tab=Proposals", "Trade AI": "/v3/trading",
                                "Watch": "/v3/watch"}
EXIT_KINDS = ("stop_out", "trailing_ratchet", "target", "manual", "stop_likely_filled", "open", "unknown")
EXIT_LABEL = {
    "stop_out": "Stop-out",
    "trailing_ratchet": "Trailing stop (ratchet)",
    "target": "Target reached",
    "manual": "Manual sell",
    "stop_likely_filled": "Stop likely filled — not confirmed",
    "open": "Still open",
    "unknown": "Exit cause unknown",
}
EXIT_TONE = {"stop_out": "danger", "trailing_ratchet": "warning", "target": "success", "manual": "info",
             "stop_likely_filled": "warning", "open": "neutral", "unknown": "neutral"}
#: An exit within this % of the last working stop is a stop fill (a stop-market fills at or a little below it).
STOP_FILL_TOL_PCT = 0.6
#: An exit within this % below the plan target counts as the target.
TARGET_TOL_PCT = 0.5
DEFAULT_DAYS = 30
OPEN_ENTRY_LOOKBACK_DAYS = 180
CACHE_S = 60.0
REENTRY_STALE_HOURS = 96.0  # reentry_decision_desk.STALE_HOURS
STOP_DEAD = {"filled", "canceled", "cancelled", "rejected", "expired", "replaced", "not_in_read"}


# ── small helpers ────────────────────────────────────────────────────────────


def _f(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        x = float(v)
        return x if x == x and x not in (float("inf"), float("-inf")) else None
    except (TypeError, ValueError):
        return None


def _ts(v: Any) -> Optional[datetime]:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if hasattr(v, "isoformat") and not isinstance(v, str):  # a date
        try:
            return datetime(v.year, v.month, v.day, 20, 0, tzinfo=timezone.utc)  # 16:00 ET close
        except Exception:  # noqa: BLE001
            return None
    s = str(v).strip()
    try:
        t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if len(s) == 10:  # a bare date: the session close
        t = t.replace(hour=20)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _iso(t: Optional[datetime]) -> Optional[str]:
    return t.isoformat() if t else None


def _up(v: Any) -> str:
    return str(v or "").strip().upper()


def _money(v: Optional[float]) -> str:
    if v is None:
        return "—"
    return f"${v:,.2f}"


def _pct(a: Optional[float], b: Optional[float]) -> Optional[float]:
    """% change from a to b."""
    if a is None or b is None or a == 0:
        return None
    return round((b - a) / a * 100, 2)


def _md(t: Optional[datetime]) -> str:
    return t.strftime("%m-%d") if t else "—"


# ── stops ────────────────────────────────────────────────────────────────────


def stop_path(stops: Iterable[dict[str, Any]], *, start: Optional[datetime], end: Optional[datetime]
              ) -> list[dict[str, Any]]:
    """The ordered stop levels observed for one position between ``start`` and ``end`` (inclusive of the level that
    was working at ``start``). One step per level change; a re-observation of the same level is not a step.

    Each step: {at, level_ref, prior_ref, change_pct, kind (initial|raise|lower), status, source, order_ref}.
    A row with no capture time but a ``seq`` (a relayed stop read) is kept, in ``seq`` order after the timed rows, with
    ``at`` null — the page shows "time not recorded", never an invented time."""
    rows = []
    untimed = []
    for i, s in enumerate(stops):
        lvl = _f(s.get("stop_price", s.get("stop_price_observed")))
        at = _ts(s.get("captured_at") or s.get("snapshot_at") or s.get("at"))
        if lvl is None:
            continue
        if at is None:
            if s.get("seq") is not None:
                untimed.append((_f(s.get("seq")) or float(i), lvl, s))
            continue
        rows.append((at, lvl, s))
    rows.sort(key=lambda r: (r[0], r[1]))
    untimed.sort(key=lambda r: r[0])
    # the level working at start (latest observation before start) leads the path
    before = [r for r in rows if start is not None and r[0] < start]
    inside = [r for r in rows if (start is None or r[0] >= start) and (end is None or r[0] <= end)]
    seq = ([before[-1]] if before else []) + inside + [(None, lvl, s) for _, lvl, s in untimed]
    out: list[dict[str, Any]] = []
    for at, lvl, s in seq:
        prior = out[-1]["level_ref"] if out else None
        if prior is not None and abs(prior - lvl) < 1e-9:
            out[-1]["status"] = str(s.get("status") or out[-1]["status"] or "")
            continue
        kind = "initial" if prior is None else ("raise" if lvl > prior else "lower")
        out.append({"at": _iso(at), "level_ref": round(lvl, 4), "prior_ref": prior,
                    "change_pct": _pct(prior, lvl) if prior is not None else None, "kind": kind,
                    "status": str(s.get("status") or ""), "source": s.get("origin") or s.get("source") or "stop_last_known",
                    "order_ref": s.get("order_id")})
    return out


def stop_chain_label(path: list[dict[str, Any]]) -> str:
    """"24.31 → 24.59 → … → 26.02" (levels only)."""
    return " → ".join(f"{p['level_ref']:.2f}" for p in path)


# ── exit cause ───────────────────────────────────────────────────────────────


def classify_exit(*, closed: bool, entry_ref: Optional[float], exit_ref: Optional[float],
                  path: list[dict[str, Any]], target_ref: Optional[float] = None,
                  mark_ref: Optional[float] = None, mark_at: Optional[str] = None) -> dict[str, Any]:
    """Why the trade ended (deterministic; facts only).

    closed:
      exit within STOP_FILL_TOL_PCT above the last observed stop, or below it (a stop-market can gap through)
                                                                              → stop-out; a trailing ratchet when the
          stop had been raised at least once (it "locked in a gain" only when the last stop was at or above entry);
      exit at or above the plan target (less TARGET_TOL_PCT)                  → target;
      no observed stop at all                                                 → unknown (no stop history);
      otherwise                                                               → manual (a sell not explained by a
          recorded stop or target);
      no exit price                                                           → unknown.
    Same classes as ``cio_prospect_lifecycle.classify_exit`` on the cio-prospect branch (``manual_sell`` → manual,
    ``unknown_no_stop_history`` → unknown); the one difference is the gap-through case, which that rule calls manual.
    open:
      a working stop at or above the latest mark → stop likely filled, not yet confirmed by a fill;
      else                                       → open.
    """
    last = path[-1]["level_ref"] if path else None
    raises = sum(1 for p in path if p["kind"] == "raise")
    chain = stop_chain_label(path) if path else ""
    if not closed:
        if last is not None and mark_ref is not None and mark_ref <= last:
            return {"kind": "stop_likely_filled", "label": EXIT_LABEL["stop_likely_filled"], "confirmed": False,
                    "level_ref": last, "raises": raises,
                    "detail": (f"Latest mark {_money(mark_ref)}{' at ' + mark_at[:16].replace('T', ' ') if mark_at else ''} "
                               f"is at or below the working stop {_money(last)}. The stop has likely filled; the "
                               "position will close here once the broker fill is synced."),
                    "evidence": ["stop_last_known", "holdings_accounts mark"]}
        return {"kind": "open", "label": EXIT_LABEL["open"], "confirmed": True, "level_ref": last, "raises": raises,
                "detail": f"Working stop {_money(last)}" if last is not None else "No stop on record",
                "evidence": ["stop_last_known"] if path else []}
    if exit_ref is None:
        return {"kind": "unknown", "label": EXIT_LABEL["unknown"], "confirmed": False, "level_ref": last,
                "raises": raises, "detail": "No exit price on the round trip.", "evidence": []}
    if last is not None and exit_ref <= last * (1 + STOP_FILL_TOL_PCT / 100):
        ratchet = raises > 0
        kind = "trailing_ratchet" if ratchet else "stop_out"
        gap = _pct(last, exit_ref)
        detail = (f"Sold at {_money(exit_ref)} against a working stop of {_money(last)}"
                  f"{f' ({gap:+.2f}% slippage)' if gap is not None and abs(gap) >= 0.01 else ''}.")
        if raises:
            detail += f" The stop had been raised {raises}× ({chain})."
        if ratchet and entry_ref is not None and last >= entry_ref:
            detail += " The last raise was at or above your entry, so the stop locked in a gain."
        elif ratchet and entry_ref is not None:
            detail += " The last raise was still below your entry, so the stop cut the loss rather than locking a gain."
        return {"kind": kind, "label": EXIT_LABEL[kind], "confirmed": True, "level_ref": last, "raises": raises,
                "detail": detail, "evidence": ["schwab_round_trips exit price", "stop_last_known"]}
    if target_ref is not None and exit_ref >= target_ref * (1 - TARGET_TOL_PCT / 100):
        return {"kind": "target", "label": EXIT_LABEL["target"], "confirmed": True, "level_ref": last,
                "raises": raises, "detail": f"Sold at {_money(exit_ref)}, at or above the plan target {_money(target_ref)}.",
                "evidence": ["schwab_round_trips exit price", "recommendation plan target"]}
    if last is None:
        return {"kind": "unknown", "label": EXIT_LABEL["unknown"], "confirmed": False, "level_ref": None,
                "raises": 0, "detail": f"Sold at {_money(exit_ref)}; no stop was observed on this position, so the cause "
                                       "cannot be told from the records (no stop history).",
                "evidence": ["schwab_round_trips exit price"]}
    detail = f"Sold at {_money(exit_ref)}, above the last recorded stop {_money(last)} — a sell you placed, not a stop fill."
    return {"kind": "manual", "label": EXIT_LABEL["manual"], "confirmed": last is not None, "level_ref": last,
            "raises": raises, "detail": detail,
            "evidence": ["schwab_round_trips exit price"] + (["stop_last_known"] if path else [])}


# ── origin ───────────────────────────────────────────────────────────────────


def opportunity_at(history: list[dict[str, Any]], at: Optional[datetime]) -> Optional[dict[str, Any]]:
    """The CIO opportunity version in force at ``at`` (the latest written at or before it)."""
    if at is None:
        return None
    best = None
    for h in history:
        w = _ts(h.get("written_at"))
        if w is not None and w <= at and (best is None or w >= _ts(best.get("written_at"))):
            best = h
    return best


def entry_state_at(states: list[dict[str, Any]], at: Optional[datetime]) -> Optional[dict[str, Any]]:
    """The latest actionable CIO entry call (BUY_READY / ENTRY_NEAR) at or before ``at`` within 10 days."""
    if at is None:
        return None
    best = None
    for s in states:
        w = _ts(s.get("evaluated_at"))
        if w is None or w > at or (at - w) > timedelta(days=10):
            continue
        if str(s.get("state") or "") not in ("BUY_READY", "ENTRY_NEAR"):
            continue
        if best is None or w >= _ts(best.get("evaluated_at")):
            best = s
    return best


def origin_block(*, entry_at: Optional[datetime], link: Optional[dict[str, Any]], rec: Optional[dict[str, Any]],
                 opp_history: list[dict[str, Any]], entry_states: list[dict[str, Any]],
                 link_status: str) -> dict[str, Any]:
    """Where the trade came from. ``kind``: internal | operator | unknown.

    internal  — a recommendation link (learning loop PR1) names the recommendation, or (interim, no link table) the
                CIO had the name ranked in the opportunity book or called it BUY_READY / ENTRY_NEAR before the entry;
    operator  — the linker recorded ``operator_initiated`` (no active recommendation matched) and the CIO had made no
                entry call either;
    unknown   — nothing recorded either way. Never presented as the operator's own pick.
    """
    opp = opportunity_at(opp_history, entry_at)
    es = entry_state_at(entry_states, entry_at)
    evidence: list[dict[str, Any]] = []
    surface = None
    rank = conv = None
    stance = None
    issued_at = None
    rec_id = rec_source = confidence = None
    plan = None
    if link and link.get("origin") == "recommendation" and rec:
        rec_source = rec.get("source") or link.get("rec_source")
        surface = SURFACE_OF_SOURCE.get(str(rec_source), str(rec_source or "recommendation"))
        conv = _f(rec.get("conviction_at_issue"))
        rank = (rec.get("payload") or {}).get("rank") if isinstance(rec.get("payload"), dict) else None
        stance = rec.get("stance")
        issued_at = _ts(rec.get("created_at"))
        rec_id = rec.get("rec_id") or link.get("rec_id")
        confidence = link.get("link_confidence")
        plan = {"entry_low_ref": _f(rec.get("entry_low")), "entry_high_ref": _f(rec.get("entry_high")),
                "invalidation_ref": _f(rec.get("plan_stop")), "target_ref": _f(rec.get("plan_target"))}
        evidence.append({"source": "trade_recommendation_links", "detail": f"{rec_id} · {confidence or 'linked'}"})
    if opp is not None:
        if surface is None:
            surface = "Home"
        if rank is None:
            rank = opp.get("rank")
        if conv is None:
            conv = _f(opp.get("conviction"))
        if stance is None:
            stance = opp.get("stance")
        if issued_at is None:
            issued_at = _ts(opp.get("written_at"))
        evidence.append({"source": "cio_opportunity_assessments",
                         "detail": f"v{opp.get('version')} {str(opp.get('written_at') or '')[:16]} · #{opp.get('rank')} · "
                                   f"conviction {opp.get('conviction')} · {opp.get('stance')}"})
    if es is not None:
        if surface is None:
            surface = "CIO entry call"
        if issued_at is None:
            issued_at = _ts(es.get("evaluated_at"))
        evidence.append({"source": "cio_entry_states", "detail": f"{es.get('state')} {str(es.get('evaluated_at'))[:16]}"})
    internal = bool(evidence)
    if internal:
        parts = [f"{surface} #{rank}" if rank is not None and surface in ("Home", "Watch") else (surface or "Internal")]
        if conv is not None:
            parts.append(f"conviction {conv:.0f}")
        if es is not None:
            parts.append(f"CIO {es.get('state')} {_md(_ts(es.get('evaluated_at')))}")
        elif stance:
            parts.append(f"stance {stance}")
        return {"kind": "internal", "label": " · ".join(parts), "surface": surface,
                "surface_href": SURFACE_HREF.get(surface or ""), "rank_at_entry": rank, "conviction_at_entry": conv,
                "stance_at_entry": stance, "cio_entry_state": (es or {}).get("state"),
                "cio_entry_state_at": _iso(_ts((es or {}).get("evaluated_at"))), "issued_at": _iso(issued_at),
                "rec_id": rec_id, "rec_source": rec_source, "link_confidence": confidence, "plan": plan,
                "evidence": evidence, "link_status": link_status}
    if link and link.get("origin") == "operator_initiated":
        return {"kind": "operator", "label": "Your pick — no internal recommendation was active",
                "surface": None, "surface_href": None, "rank_at_entry": None, "conviction_at_entry": None,
                "stance_at_entry": None, "cio_entry_state": None, "cio_entry_state_at": None, "issued_at": None,
                "rec_id": None, "rec_source": None, "link_confidence": None, "plan": None,
                "evidence": [{"source": "trade_recommendation_links", "detail": "origin operator_initiated"}],
                "link_status": link_status}
    why = {"unavailable": "the recommendation link tables are not available",
           "ok": "no recommendation, CIO ranking or CIO entry call was recorded before this entry"}.get(
        link_status, "not linked yet")
    if entry_at is None:
        why = "the entry date is not in the transaction ledger, so nothing can be matched to it"
    return {"kind": "unknown", "label": f"Origin unknown — {why}", "surface": None, "surface_href": None,
            "rank_at_entry": None, "conviction_at_entry": None, "stance_at_entry": None, "cio_entry_state": None,
            "cio_entry_state_at": None, "issued_at": None, "rec_id": None, "rec_source": None,
            "link_confidence": None, "plan": None, "evidence": [], "link_status": link_status}


# ── conviction / stance while held ───────────────────────────────────────────


def judgment_changes(opp_history: list[dict[str, Any]], entry_states: list[dict[str, Any]], *,
                     start: Optional[datetime], end: Optional[datetime]) -> list[dict[str, Any]]:
    """Conviction / stance / rank changes and CIO entry-state transitions between entry and exit."""
    out: list[dict[str, Any]] = []
    prev = opportunity_at(opp_history, start) if start else None
    for h in sorted(opp_history, key=lambda r: str(r.get("written_at") or "")):
        w = _ts(h.get("written_at"))
        if w is None or (start and w <= start) or (end and w > end):
            continue
        reasons = [str(x) for x in (h.get("change_reasons") or [])]
        bits = []
        if prev is not None and h.get("stance") != prev.get("stance"):
            bits.append(f"stance {prev.get('stance')} → {h.get('stance')}")
        pc, hc = _f((prev or {}).get("conviction")), _f(h.get("conviction"))
        if pc is not None and hc is not None and abs(hc - pc) >= 0.05:
            bits.append(f"conviction {pc:.0f} → {hc:.0f}")
        if prev is not None and h.get("rank") != prev.get("rank"):
            bits.append(f"rank #{prev.get('rank')} → #{h.get('rank')}")
        if not bits:
            bits = reasons or ["re-assessed"]
        kind = "stance_change" if prev is not None and h.get("stance") != prev.get("stance") else "conviction_change"
        out.append({"at": _iso(w), "kind": kind, "label": "CIO " + " · ".join(bits),
                    "detail": "; ".join(reasons) if reasons else None, "source": "cio_opportunity_assessments",
                    "value": {"conviction": hc, "stance": h.get("stance"), "rank": h.get("rank")}})
        prev = h
    for s in entry_states:
        w = _ts(s.get("evaluated_at"))
        if w is None or (start and w <= start) or (end and w > end):
            continue
        if s.get("prior_state") == s.get("state"):
            continue
        out.append({"at": _iso(w), "kind": "stance_change",
                    "label": f"CIO entry state {s.get('prior_state') or '—'} → {s.get('state')}", "detail": None,
                    "source": "cio_entry_states", "value": {"state": s.get("state")}})
    return out


# ── review ───────────────────────────────────────────────────────────────────


def price_band(bars: list[dict[str, Any]], *, start: Optional[datetime], end: Optional[datetime]) -> dict[str, Any]:
    """High / low while held from daily bars (a bar counts when its session date is within [start, end])."""
    hi = lo = None
    hi_at = lo_at = None
    sd = start.date() if start else None
    ed = end.date() if end else None
    for b in bars:
        t = _ts(b.get("time"))
        if t is None:
            continue
        d = t.date()
        if (sd and d < sd) or (ed and d > ed):
            continue
        h = _f(b.get("high")) if b.get("high") is not None else _f(b.get("close"))
        lw = _f(b.get("low")) if b.get("low") is not None else _f(b.get("close"))
        if h is not None and (hi is None or h > hi):
            hi, hi_at = h, d.isoformat()
        if lw is not None and (lo is None or lw < lo):
            lo, lo_at = lw, d.isoformat()
    return {"high_ref": hi, "high_at": hi_at, "low_ref": lo, "low_at": lo_at}


def review_block(*, entry_ref: Optional[float], exit_ref: Optional[float], closed: bool,
                 band: dict[str, Any], path: list[dict[str, Any]], origin: dict[str, Any],
                 conviction_now: Optional[float], stance_now: Optional[str], hold_days: Optional[float],
                 mark_ref: Optional[float], exit_cause: dict[str, Any],
                 insight: Optional[dict[str, Any]] = None, closes: Optional[list[float]] = None) -> dict[str, Any]:
    """Facts first, each with its source; then the stored model advisory, labelled, or null.

    ``closes`` (daily closes up to the exit) feed the noise-or-trend-break fact — the same rule as
    ``cio_prospect_lifecycle.post_exit_review`` (close-basis): exit-day close below SMA20 (or SMA50) → trend break;
    else a giveback from the high of at most NOISE_MAX_GIVEBACK_PCT → noise; fewer than 20 closes → undetermined."""
    facts: list[dict[str, Any]] = []

    def fact(key: str, label: str, value: str, source: str, tone: str = "neutral") -> None:
        facts.append({"key": key, "label": label, "value": value, "source": source, "tone": tone})

    end_ref = exit_ref if closed else mark_ref
    ret = _pct(entry_ref, end_ref)
    if entry_ref is not None:
        fact("entry", "Entry fill", _money(entry_ref), "fills")
    if closed and exit_ref is not None:
        fact("exit", "Exit fill", _money(exit_ref), "fills", "success" if (ret or 0) > 0 else "danger")
    if ret is not None:
        fact("return", "Return" if closed else "Return so far", f"{ret:+.2f}%", "fills" if closed else "fills + mark",
             "success" if ret > 0 else "danger")
    if hold_days is not None:
        fact("held", "Held", f"{hold_days:.1f} days" if hold_days < 10 else f"{hold_days:.0f} days", "fills")
    hi, lo = band.get("high_ref"), band.get("low_ref")
    mfe = _pct(entry_ref, hi)
    mae = _pct(entry_ref, lo)
    if hi is not None:
        fact("high", "High while held", f"{_money(hi)}{f' ({mfe:+.1f}%)' if mfe is not None else ''} · {band.get('high_at') or ''}",
             "daily bars")
    if lo is not None:
        fact("low", "Low while held", f"{_money(lo)}{f' ({mae:+.1f}%)' if mae is not None else ''} · {band.get('low_at') or ''}",
             "daily bars")
    giveback = captured = None
    if closed and hi is not None and entry_ref is not None and exit_ref is not None and hi > entry_ref:
        captured = round((exit_ref - entry_ref) / (hi - entry_ref) * 100, 1)
        giveback = round((hi - exit_ref) / hi * 100, 2)
        fact("captured", "Share of the run-up kept", f"{captured:.0f}% (gave back {giveback:.1f}% from the high)",
             "fills + daily bars", "success" if captured >= 50 else "warning")
    raises = sum(1 for p in path if p["kind"] == "raise")
    if path:
        fact("stops", "Stop path", f"{stop_chain_label(path)} ({raises} raise{'s' if raises != 1 else ''})", "stop_last_known")
    fact("cause", "Why it ended" if closed else "Status", exit_cause.get("label") or "—", "fills + stops",
         EXIT_TONE.get(exit_cause.get("kind") or "unknown", "neutral"))
    noise = None
    if (closed or exit_cause.get("kind") == "stop_likely_filled") and closes is not None:
        noise = noise_or_trend(closes, high_ref=hi, exit_ref=exit_ref if closed else exit_cause.get("level_ref"))
        fact("noise", "Noise or trend break?", f"{noise['verdict'].replace('_', ' ')} — {noise['basis']}", "daily bars",
             "warning" if noise["verdict"] == "trend_break" else "neutral")
    if origin.get("conviction_at_entry") is not None or conviction_now is not None:
        a = origin.get("conviction_at_entry")
        fact("conviction", "CIO conviction at entry → now",
             f"{'—' if a is None else f'{a:.0f}'} → {'—' if conviction_now is None else f'{conviction_now:.0f}'}"
             f"{f' ({stance_now})' if stance_now else ''}", "cio_opportunity_assessments")
    advisory = None
    if insight:
        parsed = insight.get("analysis_parsed") or {}
        text = " ".join(str(parsed.get(k)) for k in ("key_observation", "stop_quality_reason", "reentry_risk_reason")
                        if parsed.get(k))
        if text:
            advisory = {"text": text, "stop_quality": parsed.get("stop_quality"), "reentry_risk": parsed.get("reentry_risk"),
                        "model": insight.get("model_used") or insight.get("model"), "provider": insight.get("provider"),
                        "generated_at": insight.get("generated_at"),
                        "label": "Advisory — model output, not a fact. Read the facts above first.",
                        "source": "ui_prefs portfolio.reentry.llm_insights.v1"}
    return {"facts": facts, "metrics": {"return_pct": ret, "mfe_pct": mfe, "mae_pct": mae, "giveback_pct": giveback,
                                        "captured_pct": captured, "stop_raises": raises,
                                        "noise_verdict": (noise or {}).get("verdict")},
            "advisory": advisory}


NOISE_MAX_GIVEBACK_PCT = 5.0  # cio_prospect_lifecycle.NOISE_MAX_GIVEBACK_PCT


def _sma(closes: list[float], n: int) -> Optional[float]:
    return round(sum(closes[-n:]) / n, 4) if len(closes) >= n else None


def noise_or_trend(closes: list[float], *, high_ref: Optional[float], exit_ref: Optional[float]) -> dict[str, Any]:
    """Was the exit a shake-out inside an intact trend (noise) or a break of the trend? Close-basis, deterministic."""
    last = closes[-1] if closes else None
    sma20, sma50 = _sma(closes, 20), _sma(closes, 50)
    if last is None or sma20 is None:
        return {"verdict": "undetermined", "basis": "fewer than 20 daily closes up to the exit", "sma20": sma20, "sma50": sma50}
    if last < sma20 or (sma50 is not None and last < sma50):
        return {"verdict": "trend_break", "sma20": sma20, "sma50": sma50,
                "basis": f"exit-day close {last:.2f} below SMA20 {sma20:.2f}" + (f" / SMA50 {sma50:.2f}" if sma50 else "")}
    give = None if high_ref in (None, 0) or exit_ref is None else round((high_ref - exit_ref) / high_ref * 100, 2)
    tail = f"exit-day close {last:.2f} ≥ SMA20 {sma20:.2f}" + (f" and SMA50 {sma50:.2f}" if sma50 else "")
    if give is not None and give <= NOISE_MAX_GIVEBACK_PCT:
        return {"verdict": "noise", "sma20": sma20, "sma50": sma50,
                "basis": f"gave back {give:.2f}% from the high, trend intact: {tail}"}
    return {"verdict": "undetermined", "sma20": sma20, "sma50": sma50,
            "basis": f"gave back {'—' if give is None else f'{give:.2f}%'} from the high; {tail}"}


# ── re-entry ─────────────────────────────────────────────────────────────────


def reentry_block(desk_row: Optional[dict[str, Any]], *, desk_at: Optional[str], exit_ref: Optional[float],
                  closed: bool, now: datetime) -> dict[str, Any]:
    """Conditions and reference levels to get back in — the re-entry desk's deterministic row (the record Watch
    "Re-entry near" reads) plus the reclaim of the exit price. Never an order."""
    base = {"source": "reentry_decision_desk (same record as Watch · Re-entry near)", "desk_as_of": desk_at,
            "stale": None, "state": None, "action": None, "reason": None, "distance_pct": None, "price_ref": None,
            "price_as_of": None, "zone_low_ref": None, "zone_high_ref": None, "invalidation_ref": None,
            "target_ref": None, "reclaim_ref": exit_ref if closed else None, "conditions": [], "summary": None,
            "wash_blocked": None, "wash_until": None, "alert_seed": None, "watch_href": None}
    if not desk_row:
        base["summary"] = ("Not on the re-entry desk yet — the desk lists names sold in the last year once the sell "
                           "is in the transaction ledger." if closed else "Still held — re-entry applies after the exit.")
        if closed and exit_ref is not None:
            base["alert_seed"] = {"entryLow": None, "entryHigh": exit_ref, "price": None, "rsi": None}
        return base
    adv = desk_row.get("advisory") or {}
    intel = desk_row.get("intel") or {}
    at = _ts(desk_at)
    stale = bool(at is None or (now - at) > timedelta(hours=REENTRY_STALE_HOURS))
    lo, hi = _f(desk_row.get("entry_low")), _f(desk_row.get("entry_high"))
    price = _f(desk_row.get("price"))
    conds = []
    for c in adv.get("criteria") or []:
        conds.append({"id": c.get("id"), "label": c.get("label"), "met": c.get("met"), "detail": c.get("detail")})
    if closed and exit_ref is not None:
        conds.append({"id": "reclaim_exit", "label": f"Reclaims your exit price {_money(exit_ref)} (reference)",
                      "met": None if price is None else price >= exit_ref,
                      "detail": None if price is None else f"price {_money(price)} · {_pct(exit_ref, price):+.2f}% vs exit"})
    met = sum(1 for c in conds if c["met"] is True)
    state = intel.get("state")
    summary = f"{state or 'No desk state'} — {intel.get('action') or 'no action'}"
    if lo is not None and hi is not None:
        summary += f". Zone {_money(lo)}–{_money(hi)}"
        if desk_row.get("stop") is not None:
            summary += f", invalidation {_money(_f(desk_row.get('stop')))}"
        summary += "."
    summary += f" {met} of {len(conds)} conditions met."
    base.update({
        "stale": stale, "state": state, "action": intel.get("action"), "reason": intel.get("reason"),
        "distance_pct": _f(intel.get("distance_pct")), "price_ref": price, "price_as_of": desk_row.get("price_as_of"),
        "zone_low_ref": lo, "zone_high_ref": hi, "invalidation_ref": _f(desk_row.get("stop")),
        "target_ref": _f(desk_row.get("target")), "conditions": conds, "summary": summary,
        "wash_blocked": desk_row.get("wash_blocked"), "wash_until": desk_row.get("wash_until"),
        "alert_seed": {"entryLow": lo, "entryHigh": hi, "price": price, "rsi": _f(desk_row.get("rsi"))},
        "watch_href": f"/v3/watch?tab=prospects&lane=reentry&symbol={desk_row.get('symbol')}",
    })
    return base


# ── conflicts ────────────────────────────────────────────────────────────────


def conflicts_for(*, closed: bool, exit_cause: dict[str, Any], holding: Optional[dict[str, Any]],
                  opp_now: Optional[dict[str, Any]], desk_row: Optional[dict[str, Any]],
                  desk_at: Optional[str], exit_at: Optional[str]) -> list[dict[str, Any]]:
    """Disagreements between inputs about this trade — both values, both sources, both times. Never resolved here."""
    out: list[dict[str, Any]] = []
    if exit_cause.get("kind") == "stop_likely_filled" and holding:
        out.append({"field": "position", "summary": "Holdings still show the position; the stop has likely filled",
                    "a": {"value": f"held {holding.get('fill_qty')} sh", "source": "holdings_accounts",
                          "at": holding.get("as_of")},
                    "b": {"value": f"stop {_money(exit_cause.get('level_ref'))} at/above mark", "source": "stop_last_known",
                          "at": holding.get("mark_at")}})
    if closed and opp_now and str(opp_now.get("position_status") or "") == "owned" and not holding:
        out.append({"field": "position_status", "summary": "CIO still treats this as owned after the exit",
                    "a": {"value": f"{opp_now.get('stance')} · owned", "source": "cio_opportunity_projection",
                          "at": opp_now.get("as_of")},
                    "b": {"value": "closed", "source": "schwab_round_trips", "at": exit_at}})
    if desk_row and (desk_row.get("intel") or {}).get("state") == "CURRENTLY HELD" and (closed or exit_cause.get("kind") == "stop_likely_filled"):
        out.append({"field": "reentry_state", "summary": "Re-entry desk still sees the position as held",
                    "a": {"value": "CURRENTLY HELD", "source": "reentry_decision_desk", "at": desk_at},
                    "b": {"value": exit_cause.get("label"), "source": "fills + stops", "at": exit_at}})
    return out


# ── one journey ──────────────────────────────────────────────────────────────


def build_journey(trade: dict[str, Any], *, link: Optional[dict[str, Any]] = None, rec: Optional[dict[str, Any]] = None,
                  link_status: str = "unavailable", opp_history: Optional[list[dict[str, Any]]] = None,
                  opp_now: Optional[dict[str, Any]] = None, entry_states: Optional[list[dict[str, Any]]] = None,
                  stops: Optional[list[dict[str, Any]]] = None, bars: Optional[list[dict[str, Any]]] = None,
                  bars_meta: Optional[dict[str, Any]] = None, desk_row: Optional[dict[str, Any]] = None,
                  desk_at: Optional[str] = None, insight: Optional[dict[str, Any]] = None,
                  identity: Optional[dict[str, Any]] = None, now: Optional[datetime] = None) -> dict[str, Any]:
    """One TradeJourney@v1 row from one trade (a closed round trip or an open position) and its inputs."""
    now = now or datetime.now(timezone.utc)
    opp_history = opp_history or []
    entry_states = entry_states or []
    sym = _up(trade.get("symbol"))
    closed = trade.get("status") == "closed"
    entry_at = _ts(trade.get("entry_at"))
    exit_at = _ts(trade.get("exit_at")) if closed else None
    entry_ref = _f(trade.get("entry_ref"))
    exit_ref = _f(trade.get("exit_ref")) if closed else None
    mark_ref = _f(trade.get("mark_ref"))
    origin = origin_block(entry_at=entry_at, link=link, rec=rec, opp_history=opp_history, entry_states=entry_states,
                          link_status=link_status)
    path = stop_path(stops or [], start=entry_at, end=exit_at or now)
    target_ref = (origin.get("plan") or {}).get("target_ref")
    cause = classify_exit(closed=closed, entry_ref=entry_ref, exit_ref=exit_ref, path=path, target_ref=target_ref,
                          mark_ref=mark_ref, mark_at=trade.get("mark_at"))
    # P/L
    qty = _f(trade.get("fill_qty"))
    pl_amt = _f(trade.get("pl_amount"))
    if pl_amt is None and qty and entry_ref is not None:
        end_ref = exit_ref if closed else mark_ref
        pl_amt = round((end_ref - entry_ref) * qty, 2) if end_ref is not None else None
    pl_pct = _f(trade.get("pl_pct"))
    if pl_pct is None:
        pl_pct = _pct(entry_ref, exit_ref if closed else mark_ref)
    pl = {"amount": pl_amt, "pct": pl_pct, "basis": "realized" if closed else ("unrealized" if pl_amt is not None else "pending"),
          "note": None if pl_amt is not None else "entry fill not in the ledger yet"}
    hold_days = None
    if entry_at:
        hold_days = round(((exit_at or now) - entry_at).total_seconds() / 86400, 1)
    band = price_band(bars or [], start=entry_at, end=exit_at or now)
    last_day = (exit_at or now).date()
    closes = None
    if bars:
        closes = [c for c in (_f(b.get("close")) for b in bars
                              if _ts(b.get("time")) is not None and _ts(b.get("time")).date() <= last_day) if c is not None]
    opp_now_conv = _f((opp_now or {}).get("conviction"))
    review = review_block(entry_ref=entry_ref, exit_ref=exit_ref, closed=closed, band=band, path=path, origin=origin,
                          conviction_now=opp_now_conv, stance_now=(opp_now or {}).get("stance"), hold_days=hold_days,
                          mark_ref=mark_ref, exit_cause=cause, insight=insight, closes=closes)
    reentry = reentry_block(desk_row, desk_at=desk_at, exit_ref=exit_ref if closed else cause.get("level_ref") if cause["kind"] == "stop_likely_filled" else None,
                            closed=closed or cause["kind"] == "stop_likely_filled", now=now)
    holding = trade.get("holding")
    conflicts = conflicts_for(closed=closed, exit_cause=cause, holding=holding, opp_now=opp_now, desk_row=desk_row,
                              desk_at=desk_at, exit_at=_iso(exit_at))

    # timeline
    ev: list[dict[str, Any]] = []
    if origin["kind"] == "internal":
        for e in origin["evidence"]:
            at = None
            if e["source"] == "cio_entry_states":
                at = origin.get("cio_entry_state_at")
            elif e["source"] == "cio_opportunity_assessments":
                at = (opportunity_at(opp_history, entry_at) or {}).get("written_at")
            elif e["source"] == "trade_recommendation_links":
                at = origin.get("issued_at")
            label = {"cio_entry_states": f"CIO called it {origin.get('cio_entry_state')}",
                     "cio_opportunity_assessments": "CIO opportunity book",
                     "trade_recommendation_links": f"Recommendation on {origin.get('surface')}"}[e["source"]]
            ev.append({"at": _iso(_ts(at)), "kind": "origin", "label": label, "detail": e["detail"], "source": e["source"]})
    elif origin["kind"] == "operator":
        ev.append({"at": _iso(entry_at), "kind": "origin", "label": "Your pick", "detail": origin["label"],
                   "source": "trade_recommendation_links"})
    basis = trade.get("entry_at_basis")
    ev.append({"at": _iso(entry_at), "kind": "entry_fill",
               "label": (f"Bought {('%g' % qty) if qty else ''}{' sh' if qty else ''} @ {_money(entry_ref)}".replace("Bought  sh", "Bought")
                         + (" (date approximate)" if basis else "")),
               "detail": basis or trade.get("entry_detail"), "source": trade.get("entry_source"),
               **({"approximate": True} if basis else {})})
    for p in path:
        if p["kind"] == "initial":
            label = f"Stop {_money(p['level_ref'])}" + (" (working at entry)" if entry_at and _ts(p["at"]) and _ts(p["at"]) < entry_at else "")
        else:
            label = f"Stop {'raised' if p['kind'] == 'raise' else 'lowered'} {_money(p['prior_ref'])} → {_money(p['level_ref'])}"
        ev.append({"at": p["at"], "kind": "stop_change", "label": label,
                   "detail": f"{p['change_pct']:+.2f}%" if p.get("change_pct") is not None else None,
                   "source": p["source"], "value": {"level_ref": p["level_ref"], "prior_ref": p["prior_ref"]}})
    ev.extend(judgment_changes(opp_history, entry_states, start=entry_at, end=exit_at or now))
    if closed:
        ev.append({"at": _iso(exit_at), "kind": "exit_fill", "label": f"Sold @ {_money(exit_ref)} · {cause['label']}",
                   "detail": cause["detail"], "source": trade.get("exit_source") or ROUND_TRIPS,
                   "cause": cause["kind"]})
    elif cause["kind"] == "stop_likely_filled":
        ev.append({"at": trade.get("mark_at"), "kind": "exit_fill", "label": cause["label"], "detail": cause["detail"],
                   "source": "stop_last_known + mark", "cause": cause["kind"], "unconfirmed": True})
    phase = {"origin": 0, "entry_fill": 1, "exit_fill": 3}
    anchor = _iso(entry_at) or "0000"
    ev = [e for _, e in sorted(enumerate(ev), key=lambda ie: (ie[1].get("at") or anchor,
                                                                phase.get(ie[1]["kind"], 2), ie[0]))]

    chart = None
    if bars is not None:
        chart = {"kind": (bars_meta or {}).get("kind") or ("candles" if any(b.get("high") is not None for b in bars) else "closes"),
                 "bars": bars, "source": (bars_meta or {}).get("source") or "ohlc_bars",
                 "as_of": (bars_meta or {}).get("as_of"),
                 "marks": {"entry_ref": entry_ref, "entry_at": _iso(entry_at), "exit_ref": exit_ref, "exit_at": _iso(exit_at),
                           "stops": [{"at": p["at"], "level_ref": p["level_ref"]} for p in path],
                           "high_ref": band.get("high_ref"), "high_at": band.get("high_at"),
                           "low_ref": band.get("low_ref"), "low_at": band.get("low_at"),
                           "zone_low_ref": reentry.get("zone_low_ref"), "zone_high_ref": reentry.get("zone_high_ref")}}
    return {
        "schema": ROW_SCHEMA,
        "trade_id": trade.get("trade_id"),
        "symbol": sym,
        "company": trade.get("company") or (opp_now or {}).get("company"),
        "security_guid": (identity or {}).get("security_guid"),
        "identity_status": (identity or {}).get("status") or "unresolved",
        "account": trade.get("account"),
        "status": "closed" if closed else "open",
        "fill_qty": qty,
        "entry": {"price_ref": entry_ref, "at": _iso(entry_at), "source": trade.get("entry_source"),
                  "at_basis": trade.get("entry_at_basis")},
        "exit": {"price_ref": exit_ref, "at": _iso(exit_at), "source": trade.get("exit_source")} if closed else None,
        "mark": {"price_ref": mark_ref, "at": trade.get("mark_at")} if not closed else None,
        "pl": pl,
        "hold_days": hold_days,
        "origin": origin,
        "exit_cause": cause,
        "stop_path": path,
        "timeline": ev,
        "review": review,
        "re_entry": reentry,
        "conflicts": conflicts,
        "conviction_now": opp_now_conv,
        "stance_now": (opp_now or {}).get("stance"),
        "rank_now": (opp_now or {}).get("rank"),
        "stage": None,
        "chart": chart,
        "sort_at": _iso(exit_at or entry_at),
    }


PROSPECT_EXIT_CLASS = {"stop_out": "stop_out", "trailing_ratchet": "trailing_ratchet", "target": "target",
                       "manual_sell": "manual", "unknown_no_stop_history": "unknown"}
PROSPECT_EVENT_KIND = {"origin_attributed": "origin", "entry_fill": "entry_fill", "stop_change": "stop_change",
                       "conviction_change": "conviction_change", "exit_fill": "exit_fill"}


def _prospect_origin(o: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    """The cio_prospect ``origin`` block (cio_prospect_lifecycle.attribute_origin: classification, summary, linkage,
    at_entry.surfaces) in this row's origin shape."""
    cls = o.get("classification")
    kind = "internal" if cls == "internal" else ("operator" if cls == "operator_initiated" else "unknown")
    link = o.get("linkage") or {}
    surfaces = [x for x in ((o.get("at_entry") or {}).get("surfaces") or []) if isinstance(x, dict)]
    home = next((x for x in surfaces if str(x.get("surface") or "").startswith("Home") and x.get("shown")), None)
    ranked = home or next((x for x in surfaces if x.get("conviction") is not None), None)
    call = next((x for x in surfaces if str(x.get("surface") or "").startswith("CIO entry state")), None)
    rank = (ranked or {}).get("rank")
    conv = _f((ranked or {}).get("conviction"))
    surface = "Home" if home else SURFACE_OF_SOURCE.get(str(link.get("rec_source") or ""), "CIO" if surfaces else None)
    zone = link.get("plan_entry_zone") or [None, None]
    evidence = [{"source": x.get("record") or x.get("surface") or "cio_prospect",
                 "detail": " · ".join(str(v) for v in (x.get("surface"), f"#{x.get('rank')}" if x.get("rank") is not None
                                                       else None, x.get("conviction"), x.get("stance") or x.get("state"),
                                                       str(x.get("at") or "")[:16]) if v)}
                for x in surfaces if x.get("shown")]
    if link.get("rec_id"):
        evidence.insert(0, {"source": link.get("source") or "linkage",
                            "detail": f"{link.get('rec_id')} · {link.get('link_confidence') or 'linked'}"})
    if kind == "internal":
        parts = [f"{surface} #{rank}" if surface == "Home" and rank is not None else (surface or "Internal")]
        if conv is not None:
            parts.append(f"conviction {conv:.0f}")
        if call is not None:
            parts.append(f"CIO {call.get('state')} {_md(_ts(call.get('at')))}")
        label = " · ".join(parts)
    elif kind == "operator":
        label = "Your pick — no internal recommendation was active"
    else:
        label = fallback.get("label") or "Origin unknown"
    return {"kind": kind, "label": label, "surface": surface if kind == "internal" else None,
            "surface_href": SURFACE_HREF.get(surface or "") if kind == "internal" else None,
            "rank_at_entry": rank, "conviction_at_entry": conv, "stance_at_entry": (ranked or {}).get("stance"),
            "cio_entry_state": (call or {}).get("state"), "cio_entry_state_at": (call or {}).get("at"),
            "issued_at": link.get("rec_issued_at"), "rec_id": link.get("rec_id"), "rec_source": link.get("rec_source"),
            "link_confidence": link.get("link_confidence"),
            "plan": {"entry_low_ref": _f(zone[0]) if len(zone) > 0 else None,
                     "entry_high_ref": _f(zone[1]) if len(zone) > 1 else None,
                     "invalidation_ref": _f(link.get("plan_stop")), "target_ref": _f(link.get("plan_target"))},
            "evidence": evidence, "link_status": "cio_prospect", "summary": o.get("summary")}


def _prospect_timeline(events: list[dict[str, Any]], row: dict[str, Any]) -> list[dict[str, Any]]:
    """``lifecycle_events`` (append-only cio_prospect_events rows) as this row's timeline."""
    out: list[dict[str, Any]] = []
    prior = None
    for e in events:
        kind = PROSPECT_EVENT_KIND.get(str(e.get("event_type") or ""))
        if kind is None:
            continue
        ch = e.get("change") or {}
        if kind == "origin":
            label = f"Origin: {ch.get('classification')}" + (f" · {ch.get('rec_id')}" if ch.get("rec_id") else "")
        elif kind == "entry_fill":
            label = f"Bought @ {_money(_f(ch.get('fill_price')))}"
        elif kind == "stop_change":
            lvl = _f(ch.get("stop_price_observed"))
            label = (f"Stop {_money(lvl)}" if prior is None else
                     f"Stop {'raised' if (lvl or 0) > prior else 'lowered'} {_money(prior)} → {_money(lvl)}")
            prior = lvl
        elif kind == "conviction_change":
            label = f"CIO conviction {ch.get('conviction')} · {ch.get('stance')} · #{ch.get('rank')}"
        else:
            cause = PROSPECT_EXIT_CLASS.get(str(ch.get("cause") or ""), "unknown")
            label = f"Sold @ {_money(_f(ch.get('fill_price')))} · {EXIT_LABEL[cause]}"
        item = {"at": e.get("at"), "kind": kind, "label": label, "detail": None, "source": "cio_prospect_events"}
        if kind == "exit_fill":
            item["cause"] = PROSPECT_EXIT_CLASS.get(str(ch.get("cause") or ""), "unknown")
            item["detail"] = (row.get("exit_cause") or {}).get("detail")
        out.append(item)
    phase = {"origin": 0, "entry_fill": 1, "exit_fill": 3}
    return [e for _, e in sorted(enumerate(out), key=lambda ie: (ie[1].get("at") or "", phase.get(ie[1]["kind"], 2), ie[0]))]


def from_cio_prospect(row: dict[str, Any], prospect: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Overlay the live CIO prospect record on a journey (AGENTS.md §26.3).

    Always: stage (``stage_phase`` when present), conviction, stance and conflicts (added, never merged away). When the
    record carries the position lifecycle (cio_prospect_lifecycle on the cio-prospect branch: ``origin``,
    ``position_lifecycle``, ``post_exit_review``, ``reentry_advice``, ``lifecycle_events``) those replace the interim
    blocks, mapped into this row's shape; fields the record does not carry (the price band, the desk's invalidation and
    target, the alert seed) keep the interim value. Only one trade per security is mapped: the record's
    ``position_lifecycle.round_trip_key`` must match this row's round trip, or (open) the row must be open."""
    if not prospect:
        return row
    out = dict(row)
    out["stage"] = prospect.get("stage_phase") or prospect.get("stage")
    if prospect.get("conviction") is not None:
        out["conviction_now"] = _f(prospect.get("conviction"))
    if prospect.get("stance"):
        out["stance_now"] = prospect.get("stance")
    life = prospect.get("position_lifecycle") if isinstance(prospect.get("position_lifecycle"), dict) else None
    rk = str((life or {}).get("round_trip_key") or "")
    same = bool(life) and ((row.get("status") == "closed" and rk and rk in str(row.get("trade_id") or ""))
                           or (row.get("status") == "open" and (life or {}).get("status") == "open"))
    if same:
        if isinstance(prospect.get("origin"), dict):
            out["origin"] = _prospect_origin(prospect["origin"], row.get("origin") or {})
        cause = (life or {}).get("exit_cause") or {}
        if cause.get("class"):
            kind = PROSPECT_EXIT_CLASS.get(str(cause.get("class")), "unknown")
            out["exit_cause"] = {**(row.get("exit_cause") or {}), "kind": kind, "label": EXIT_LABEL[kind],
                                 "detail": cause.get("evidence") or (row.get("exit_cause") or {}).get("detail"),
                                 "confirmed": True}
        if isinstance(prospect.get("lifecycle_events"), list) and prospect["lifecycle_events"]:
            out["timeline"] = _prospect_timeline(prospect["lifecycle_events"], out)
        rv = prospect.get("post_exit_review") if isinstance(prospect.get("post_exit_review"), dict) else None
        if rv:
            f = rv.get("facts") or {}
            nvt = rv.get("noise_vs_trend") or {}
            facts = [{"key": "entry", "label": "Entry fill", "value": _money(_f(f.get("entry_price"))), "source": "cio_prospect", "tone": "neutral"},
                     {"key": "exit", "label": "Exit fill", "value": _money(_f(f.get("exit_price"))), "source": "cio_prospect", "tone": "neutral"},
                     {"key": "return", "label": "Return", "value": "—" if f.get("exit_vs_entry_pct") is None else f"{f['exit_vs_entry_pct']:+.2f}%",
                      "source": "cio_prospect", "tone": "success" if (f.get("exit_vs_entry_pct") or 0) > 0 else "danger"},
                     {"key": "high", "label": "High while held", "value": f"{_money(_f((f.get('peak') or {}).get('price')))} · {(f.get('peak') or {}).get('at') or ''}",
                      "source": f"cio_prospect ({(f.get('peak') or {}).get('basis') or 'bars'})", "tone": "neutral"},
                     {"key": "low", "label": "Low while held", "value": f"{_money(_f((f.get('trough') or {}).get('price')))} · {(f.get('trough') or {}).get('at') or ''}",
                      "source": f"cio_prospect ({(f.get('trough') or {}).get('basis') or 'bars'})", "tone": "neutral"},
                     {"key": "giveback", "label": "Gave back from the high", "value": "—" if f.get("giveback_from_peak_pct") is None else f"{f['giveback_from_peak_pct']:.2f}%",
                      "source": "cio_prospect", "tone": "neutral"},
                     {"key": "stops", "label": "Stop path", "value": " → ".join(f"{_f(x):.2f}" for x in f.get("observed_stop_path") or [] if _f(x) is not None) or "—",
                      "source": "cio_prospect", "tone": "neutral"},
                     {"key": "noise", "label": "Noise or trend break?", "value": f"{nvt.get('verdict') or '—'} — {nvt.get('basis') or ''}".strip(" —"),
                      "source": "cio_prospect (deterministic)", "tone": "warning" if nvt.get("verdict") == "trend_break" else "neutral"}]
            adv = None
            if rv.get("prose"):
                adv = {"text": str(rv.get("prose")), "model": rv.get("prose_model"), "label":
                       "Advisory — model output, not a fact. Read the facts above first.", "source": "cio_prospect post_exit_review"}
            out["review"] = {"facts": facts, "metrics": (row.get("review") or {}).get("metrics") or {}, "advisory": adv}
        ra = prospect.get("reentry_advice") if isinstance(prospect.get("reentry_advice"), dict) else None
        if ra:
            lv = ra.get("levels") or {}
            zone = lv.get("entry_zone") or [None, None]
            base = dict(row.get("re_entry") or {})
            conds = [{"id": c.get("id"), "label": c.get("text") or c.get("id"), "met": c.get("met"),
                      "detail": None if c.get("value") is None else str(c.get("value"))} for c in ra.get("conditions") or []]
            met = sum(1 for c in conds if c["met"] is True)
            base.update({"source": "cio_prospect reentry_advice (Re-Entry Decision Desk classifier — same record as "
                                   "Watch · Re-entry near)", "state": ra.get("state"), "action": ra.get("action"),
                         "reason": ra.get("reason"), "distance_pct": _f(ra.get("distance_pct")),
                         "price_ref": _f(lv.get("price")), "price_as_of": lv.get("price_as_of"),
                         "zone_low_ref": _f(zone[0]) if zone else None, "zone_high_ref": _f(zone[1]) if len(zone) > 1 else None,
                         "reclaim_ref": _f(lv.get("reclaim")), "conditions": conds,
                         "summary": f"{ra.get('state') or 'No state'} — {ra.get('action') or 'no action'}. {met} of {len(conds)} conditions met.",
                         "alert_seed": {"entryLow": _f(zone[0]) if zone else None,
                                        "entryHigh": _f(zone[1]) if len(zone) > 1 else None,
                                        "price": _f(lv.get("price")), "rsi": _f(lv.get("rsi"))}})
            out["re_entry"] = base
    out["conflicts"] = list(row.get("conflicts") or [])
    for c in prospect.get("conflicts") or []:
        if not isinstance(c, dict):
            continue
        vals = c.get("values") if isinstance(c.get("values"), list) else None
        a = (vals[0] if vals and len(vals) > 0 else c.get("a")) or {}
        b = (vals[1] if vals and len(vals) > 1 else c.get("b")) or {}
        out["conflicts"].append({"field": c.get("field"), "summary": c.get("summary") or c.get("note")
                                 or f"{c.get('field')}: sources disagree", "a": a, "b": b})
    return out


# ── the payload ──────────────────────────────────────────────────────────────


def freshness_chips(*, now: datetime, trades_at: Optional[str], holdings_at: Optional[str], stops_at: Optional[str],
                    opp_at: Optional[str], desk_at: Optional[str], link_status: str, source_label: str) -> list[dict[str, Any]]:
    def age(at: Optional[str]) -> tuple[str, Optional[float]]:
        t = _ts(at)
        if t is None:
            return "time unknown", None
        h = (now - t).total_seconds() / 3600
        return (f"{h * 60:.0f} min ago" if h < 1 else f"{h:.0f} h ago" if h < 48 else f"{h / 24:.0f} d ago"), h

    def chip(key: str, label: str, at: Optional[str], warn_h: float, tip: str) -> dict[str, Any]:
        txt, h = age(at)
        tone = "neutral" if h is None else ("success" if h <= warn_h else "warning")
        return {"key": key, "label": label, "value": txt, "tone": tone, "at": at, "tip": tip}

    return [
        chip("fills", "Fills", trades_at, 26, "Closed round trips from schwab_round_trips (built from the broker "
             "transaction ledger every 15 min in market hours). A sell that is not in the ledger yet is not shown as closed."),
        chip("holdings", "Holdings", holdings_at, 26, "Open positions from the holdings_accounts store "
             "(lib.portfolio_positions, the one accessor). Its as_of is shown; a stop that filled after it is flagged."),
        chip("stops", "Stops", stops_at, 26, "Observed stop orders from stop_last_known — one durable row per stop order "
             "the scan saw, with the time it was captured. Stop levels are reference facts, never orders."),
        chip("cio", "CIO", opp_at, 6, "Conviction, rank and stance from the CIO opportunity book "
             "(cio_opportunity_projection + its append-only history)."),
        chip("reentry", "Re-entry desk", desk_at, REENTRY_STALE_HOURS, "The deterministic re-entry desk snapshot — the "
             "same record the Watch page's Re-entry near lane reads. No model sets READY / NEAR / BLOCK."),
        {"key": "links", "label": "Origin links", "value": {"ok": "linked", "unavailable": "not available"}.get(link_status, link_status),
         "tone": "success" if link_status == "ok" else "warning", "at": None,
         "tip": "Recommendation → trade links (learning loop PR1: recommendation_registry + trade_recommendation_links). "
                "Without them, origin falls back to the CIO opportunity history and CIO entry calls."},
        {"key": "source", "label": "Record", "value": source_label,
         "tone": "success" if source_label == CIO_LABEL else "warning", "at": None,
         "tip": "AGENTS.md §26: pages read the CIO prospect record through its projection. Until that store is live this "
                "page uses an interim adapter over today's sources with the identical shape."},
    ]


def build_trade_journeys(trades: list[dict[str, Any]], *, inputs: dict[str, Any], now: Optional[datetime] = None,
                         prospects: Optional[dict[str, dict[str, Any]]] = None) -> dict[str, Any]:
    """The TradeJourneys@v1 payload from gathered inputs (pure; the HTTP path gathers ``inputs``)."""
    now = now or datetime.now(timezone.utc)
    rows = []
    for t in trades:
        sym = _up(t.get("symbol"))
        row = build_journey(
            t, link=(inputs.get("links") or {}).get(t.get("round_trip_key") or ""),
            rec=(inputs.get("recs") or {}).get(((inputs.get("links") or {}).get(t.get("round_trip_key") or "") or {}).get("rec_id") or ""),
            link_status=inputs.get("link_status") or "unavailable",
            opp_history=(inputs.get("opp_history") or {}).get(sym) or [],
            opp_now=(inputs.get("opp_now") or {}).get(sym),
            entry_states=(inputs.get("entry_states") or {}).get(sym) or [],
            stops=[s for s in ((inputs.get("stops") or {}).get(sym) or [])
                   if not t.get("account") or not s.get("account") or _acct(s.get("account")) == _acct(t.get("account"))],
            bars=(inputs.get("bars") or {}).get(sym), bars_meta=(inputs.get("bars_meta") or {}).get(sym),
            desk_row=(inputs.get("desk_rows") or {}).get(sym), desk_at=inputs.get("desk_at"),
            insight=(inputs.get("insights") or {}).get(sym), identity=(inputs.get("identities") or {}).get(sym), now=now)
        if prospects is not None:
            row = from_cio_prospect(row, prospects.get(sym))
        rows.append(row)
    # Most recent activity first; a stop that has likely filled (unconfirmed exit) leads, because it needs a look.
    rows.sort(key=lambda r: r.get("sort_at") or "", reverse=True)
    rows.sort(key=lambda r: 0 if r["exit_cause"]["kind"] == "stop_likely_filled" else 1)
    live = prospects is not None
    source_label = CIO_LABEL if live else INTERIM_LABEL
    counts = {"open": sum(1 for r in rows if r["status"] == "open"),
              "closed": sum(1 for r in rows if r["status"] == "closed"),
              "internal": sum(1 for r in rows if r["origin"]["kind"] == "internal"),
              "operator": sum(1 for r in rows if r["origin"]["kind"] == "operator"),
              "unknown": sum(1 for r in rows if r["origin"]["kind"] == "unknown"),
              "conflicts": sum(len(r["conflicts"]) for r in rows)}
    return {
        "ok": True, "schema": SCHEMA, "as_of": _iso(now), "interim": not live, "source_label": source_label,
        "source": {"kind": "cio_prospect" if live else "interim", "projection": "trade_journey",
                   "cio_prospect_status": inputs.get("cio_prospect_status") or "absent",
                   "reads": inputs.get("reads") or []},
        "window_days": inputs.get("days"), "counts": counts,
        "freshness": freshness_chips(now=now, trades_at=inputs.get("trades_at"), holdings_at=inputs.get("holdings_at"),
                                     stops_at=inputs.get("stops_at"), opp_at=inputs.get("opp_at"),
                                     desk_at=inputs.get("desk_at"), link_status=inputs.get("link_status") or "unavailable",
                                     source_label=source_label),
        "gaps": inputs.get("gaps") or [],
        "journeys": rows,
        "provider_calls": 0, "writes": 0, "memory_behavior_influence": 0, "read_only": True,
    }


def _acct(a: Any) -> str:
    s = str(a or "").lower().strip()
    return {"schwab_roth": "schwab_roth_ira"}.get(s, s)


# ── live gather (the HTTP path) ──────────────────────────────────────────────

_CACHE: dict[str, Any] = {}


def _db_query() -> Optional[Callable[..., Any]]:
    try:
        from db_adapter import _execute
    except Exception:  # noqa: BLE001
        return None
    return lambda sql, params=None, fetch="all": _execute(sql, params, fetch=fetch)


def _q(db: Optional[Callable[..., Any]], sql: str, params: Any = None, gaps: Optional[list] = None,
       what: str = "") -> list[dict[str, Any]]:
    if db is None:
        return []
    try:
        return [dict(r) for r in (db(sql, params) or [])]
    except Exception as exc:  # noqa: BLE001
        if gaps is not None:
            gaps.append({"input": what, "why": f"{type(exc).__name__}: {str(exc)[:120]}"})
        return []


def _state_root() -> Path:
    try:
        from lib.canonical_store_registry import production_state_root
    except ImportError:  # pragma: no cover
        from scripts.lib.canonical_store_registry import production_state_root  # type: ignore
    return Path(production_state_root())


DESK_SNAPSHOT_REL = "data/runtime/reentry_decision_desk_latest.json"


def load_desk_snapshot(path: Optional[Path] = None) -> tuple[dict[str, dict[str, Any]], Optional[str]]:
    p = path or (_state_root() / DESK_SNAPSHOT_REL)
    try:
        doc = json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, None
    return {_up(r.get("symbol")): r for r in (doc.get("rows") or []) if r.get("symbol")}, doc.get("computed_at")


def load_opportunity_history(symbols: Iterable[str], event_path: Optional[Path] = None) -> dict[str, list[dict[str, Any]]]:
    """One pass over the CIO opportunity history for a set of symbols (CIOOpportunityStore's append-only log)."""
    want = {_up(s) for s in symbols if s}
    if not want:
        return {}
    if event_path is None:
        try:
            from lib.cio_opportunity_store import CIOOpportunityStore
        except ImportError:  # pragma: no cover
            from scripts.lib.cio_opportunity_store import CIOOpportunityStore  # type: ignore
        event_path = CIOOpportunityStore().event_path
    needles = {s: f'"symbol": "{s}"' for s in want}
    out: dict[str, list[dict[str, Any]]] = {s: [] for s in want}
    try:
        with Path(event_path).open(encoding="utf-8") as fh:
            for line in fh:
                hit = next((s for s, n in needles.items() if n in line), None)
                if hit is None:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("symbol") != hit:
                    continue
                a = row.get("assessment") or {}
                out[hit].append({"version": row.get("version"), "written_at": row.get("written_at"),
                                 "change_reasons": row.get("change_reasons"), "conviction": a.get("conviction"),
                                 "rank": a.get("rank"), "stance": a.get("stance"),
                                 "position_status": a.get("position_status")})
    except OSError:
        return {}
    return out


def approximate_entries(trades: list[dict[str, Any]], *, stops: dict[str, list[dict[str, Any]]],
                        opp_history: dict[str, list[dict[str, Any]]]) -> None:
    """An open position whose buy is not in the transaction ledger (the Schwab transaction ingest has gaps) still
    needs an entry time, or its origin cannot be found. Use the earliest of: the first stop observed on that account's
    position (a stop exists only while held), and just before the first CIO opportunity version that marks it owned.
    The row says the date is approximate and why (``entry_at_basis``); it is never presented as a fill time."""
    for t in trades:
        if t.get("status") != "open" or t.get("entry_at"):
            continue
        cands: list[tuple[datetime, str]] = []
        mine = [s for s in stops.get(t["symbol"]) or []
                if not t.get("account") or not s.get("account") or _acct(s.get("account")) == _acct(t.get("account"))]
        firsts = sorted(filter(None, (_ts(s.get("captured_at")) for s in mine)))
        if firsts:
            cands.append((firsts[0], "first stop observed on the position"))
        owned = sorted(filter(None, (_ts(h.get("written_at")) for h in opp_history.get(t["symbol"]) or []
                                     if h.get("position_status") == "owned")))
        if owned:
            cands.append((owned[0] - timedelta(seconds=1), "first CIO opportunity version that marks it owned"))
        if cands:
            at, why = min(cands, key=lambda c: c[0])
            t["entry_at"] = _iso(at)
            t["entry_at_basis"] = f"approximate — {why}; the buy is not in the transaction ledger"


def _cio_prospects(symbols: list[str]) -> tuple[Optional[dict[str, dict[str, Any]]], str]:
    """Live prospect records by symbol, only when the cio_prospect projection reads the live store."""
    try:
        from lib.data_broker import cio_prospect as cp  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 — not merged yet
        return None, "absent"
    fn = getattr(cp, "get_prospects", None)
    if fn is None:
        return None, "absent"
    try:
        out = fn(db_query=_db_query(), symbols=symbols)
    except Exception:  # noqa: BLE001
        return None, "error"
    kind = str(((out or {}).get("source") or {}).get("kind") or "")
    live = bool(((out or {}).get("store_status") or {}).get("live"))
    if live and kind == "store":
        return {_up(r.get("symbol")): r for r in (out.get("prospects") or [])}, "store"
    return None, "shadow" if kind == "shadow" else "not_live"


def gather(db: Optional[Callable[..., Any]], *, days: int = DEFAULT_DAYS, symbol: Optional[str] = None,
           with_bars: bool = False, now: Optional[datetime] = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """(trades, inputs) from today's sources. Read-only SELECTs and file reads; nothing is written."""
    now = now or datetime.now(timezone.utc)
    gaps: list[dict[str, Any]] = []
    reads: list[str] = []
    sym_f = _up(symbol) if symbol else None
    trades: list[dict[str, Any]] = []

    # closed round trips
    rt = _q(db, """SELECT id, account, symbol, entry_time, exit_time, qty, entry_price, exit_price, net_pnl, pnl_pct,
                          classification, dedupe_key
                     FROM schwab_round_trips
                    WHERE exit_time >= now() - (%s || ' days')::interval AND NOT coalesce(canary, false)
                    ORDER BY exit_time DESC LIMIT 400""", (str(int(days)),), gaps, "schwab_round_trips")
    reads.append("schwab_round_trips")
    trades_at = None
    for r in rt:
        s = _up(r.get("symbol"))
        if sym_f and s != sym_f:
            continue
        x = _ts(r.get("exit_time"))
        trades_at = max(filter(None, [trades_at, _iso(x)]), default=None)
        trades.append({"trade_id": f"rt:{r.get('dedupe_key') or r.get('id')}", "round_trip_key": r.get("dedupe_key"),
                       "symbol": s, "account": r.get("account"), "status": "closed", "fill_qty": _f(r.get("qty")),
                       "entry_at": _iso(_ts(r.get("entry_time"))), "exit_at": _iso(x), "entry_ref": _f(r.get("entry_price")),
                       "exit_ref": _f(r.get("exit_price")), "pl_amount": _f(r.get("net_pnl")), "pl_pct": _f(r.get("pnl_pct")),
                       "entry_source": "schwab_round_trips", "exit_source": "schwab_round_trips",
                       "entry_detail": r.get("classification")})

    # open positions
    holdings_at = None
    try:
        try:
            from lib import portfolio_positions as pp
        except ImportError:  # pragma: no cover
            from scripts.lib import portfolio_positions as pp  # type: ignore
        doc = pp.load_store()
        holdings_at = doc.get("as_of") or doc.get("data_as_of")
        reads.append("holdings_accounts (lib.portfolio_positions)")
        held_syms = sorted({_up(h.get("symbol")) for h in doc.get("holdings") or []
                            if h.get("symbol") and not pp.is_cash(h) and (not sym_f or _up(h.get("symbol")) == sym_f)})
        quotes: dict[str, dict[str, Any]] = {}
        if db is not None and held_syms:
            try:
                from lib.data_broker.latest_quote import get_latest_quotes
                quotes = {k: {**v, "source": "market_quotes"} for k, v in
                          ((get_latest_quotes(db, held_syms) or {}).get("symbols") or {}).items() if v}
                reads.append("latest_quote projection (market_quotes)")
            except Exception as exc:  # noqa: BLE001
                gaps.append({"input": "latest_quote", "why": f"{type(exc).__name__}: {str(exc)[:120]}"})
        for h in doc.get("holdings") or []:
            s = _up(h.get("symbol"))
            q = _f(h.get("shares", h.get("quantity")))
            if not s or not q or q <= 0 or pp.is_cash(h) or (sym_f and s != sym_f) or len(s) > 6:
                continue
            mark = pp.resolve_mark(h, quote=quotes.get(s))
            acct = h.get("account") or h.get("account_key")
            trades.append({"trade_id": f"open:{acct}:{s}", "symbol": s, "account": acct, "status": "open",
                           "fill_qty": q, "entry_ref": pp.per_share_cost(h), "mark_ref": _f((mark or {}).get("price")),
                           "mark_at": (mark or {}).get("as_of") or holdings_at, "entry_source": "holdings avg cost",
                           "holding": {"fill_qty": q, "as_of": holdings_at, "mark_at": (mark or {}).get("as_of")}})
    except Exception as exc:  # noqa: BLE001
        gaps.append({"input": "holdings_accounts", "why": f"{type(exc).__name__}: {str(exc)[:120]}"})

    syms = sorted({t["symbol"] for t in trades})
    # entry fills for open positions: buys after the last sell, per account
    open_syms = sorted({t["symbol"] for t in trades if t["status"] == "open"})
    if open_syms:
        tx = _q(db, """SELECT account, upper(symbol) AS symbol, action, quantity, price, trade_time, trade_date
                         FROM trade_transactions
                        WHERE upper(symbol) = ANY(%s) AND action IN ('Buy','Sell')
                          AND trade_date >= CURRENT_DATE - %s
                        ORDER BY coalesce(trade_time, trade_date::timestamptz)""",
                (open_syms, OPEN_ENTRY_LOOKBACK_DAYS), gaps, "trade_transactions")
        reads.append("trade_transactions")
        for t in trades:
            if t["status"] != "open":
                continue
            mine = [r for r in tx if r.get("symbol") == t["symbol"] and (not t.get("account") or _acct(r.get("account")) == _acct(t["account"]))]
            last_sell = max((i for i, r in enumerate(mine) if r.get("action") == "Sell"), default=-1)
            buys = [r for r in mine[last_sell + 1:] if r.get("action") == "Buy" and _f(r.get("price"))]
            if buys:
                qsum = sum(_f(b.get("quantity")) or 0 for b in buys)
                if qsum > 0:
                    t["entry_ref"] = round(sum((_f(b.get("price")) or 0) * (_f(b.get("quantity")) or 0) for b in buys) / qsum, 4)
                t["entry_at"] = _iso(_ts(buys[0].get("trade_time") or buys[0].get("trade_date")))
                t["entry_source"] = "trade_transactions"
                t["entry_detail"] = f"{len(buys)} buy fill{'s' if len(buys) != 1 else ''}"
            if t.get("entry_ref") is not None and t.get("mark_ref") is not None and t.get("fill_qty"):
                t["pl_amount"] = round((t["mark_ref"] - t["entry_ref"]) * t["fill_qty"], 2)

    # recommendation links (learning loop PR1)
    keys = [t["round_trip_key"] for t in trades if t.get("round_trip_key")]
    links: dict[str, dict[str, Any]] = {}
    recs: dict[str, dict[str, Any]] = {}
    link_status = "unavailable"
    if db is not None:
        lg: list = []
        lrows = _q(db, """SELECT round_trip_key, origin, rec_id, link_confidence FROM trade_recommendation_links
                          WHERE round_trip_key = ANY(%s)""", (keys or [""],), lg, "trade_recommendation_links")
        if not lg:
            link_status = "ok"
            reads.append("trade_recommendation_links")
            links = {r["round_trip_key"]: r for r in lrows}
            ids = sorted({r["rec_id"] for r in lrows if r.get("rec_id")})
            if ids:
                recs = {r["rec_id"]: r for r in _q(db, """SELECT rec_id, source, symbol, entry_low, entry_high, plan_stop,
                                                                 plan_target, created_at, conviction_at_issue, stance, payload
                                                            FROM recommendation_registry WHERE rec_id = ANY(%s)""",
                                                   (ids,), gaps, "recommendation_registry")}
                reads.append("recommendation_registry")
        else:
            gaps.append({"input": "trade_recommendation_links", "why": "table not available (learning loop PR1 migration)"})

    # CIO entry calls
    es_rows = _q(db, """SELECT symbol, state, prior_state, evaluated_at FROM cio_entry_states
                         WHERE upper(symbol) = ANY(%s) AND evaluated_at >= now() - interval '200 days'
                         ORDER BY evaluated_at""", (syms or [""],), gaps, "cio_entry_states")
    reads.append("cio_entry_states")
    entry_states: dict[str, list] = {}
    for r in es_rows:
        entry_states.setdefault(_up(r.get("symbol")), []).append(r)

    # observed stops
    st_rows = _q(db, """SELECT broker, account, upper(symbol) AS symbol, order_id, order_type, stop_price, status,
                               captured_at, origin
                          FROM stop_last_known WHERE upper(symbol) = ANY(%s)
                          ORDER BY captured_at""", (syms or [""],), gaps, "stop_last_known")
    reads.append("stop_last_known")
    stops: dict[str, list] = {}
    stops_at = None
    for r in st_rows:
        stops.setdefault(r["symbol"], []).append(r)
        stops_at = max(filter(None, [stops_at, _iso(_ts(r.get("captured_at")))]), default=None)

    # CIO opportunity — now and history
    opp_now: dict[str, dict[str, Any]] = {}
    opp_at = None
    try:
        try:
            from lib.cio_opportunity_store import CIOOpportunityStore
        except ImportError:  # pragma: no cover
            from scripts.lib.cio_opportunity_store import CIOOpportunityStore  # type: ignore
        proj = CIOOpportunityStore().read_projection() or {}
        opp_at = proj.get("as_of")
        items = proj.get("items") or {}
        items = items if isinstance(items, dict) else {i.get("symbol"): i for i in items if isinstance(i, dict)}
        opp_now = {s: items[s] for s in syms if s in items}
        reads.append("cio_opportunity_projection")
    except Exception as exc:  # noqa: BLE001
        gaps.append({"input": "cio_opportunity_projection", "why": f"{type(exc).__name__}: {str(exc)[:120]}"})
    opp_history = load_opportunity_history(syms)
    reads.append("cio_opportunity_assessments (history)")
    approximate_entries(trades, stops=stops, opp_history=opp_history)

    desk_rows, desk_at = load_desk_snapshot()
    reads.append(DESK_SNAPSHOT_REL)
    if not desk_at:
        gaps.append({"input": "reentry desk snapshot", "why": "no snapshot yet"})

    insights: dict[str, dict[str, Any]] = {}
    pref = _q(db, "SELECT value FROM ui_prefs WHERE key=%s", ("portfolio.reentry.llm_insights.v1",), gaps, "ui_prefs")
    if pref:
        val = pref[0].get("value")
        val = json.loads(val) if isinstance(val, str) else (val or {})
        for k, v in (val.get("insights") or {}).items():
            if str(k).endswith(":quality") and isinstance(v, dict) and v.get("success"):
                insights[_up(v.get("symbol") or str(k).split(":")[0])] = {**v, "generated_at": val.get("generated_at")}

    bars: dict[str, list] = {}
    bars_meta: dict[str, dict[str, Any]] = {}
    if with_bars and db is not None:
        from lib.data_broker.ohlc_bars import get_daily_ohlc
        for s in syms:
            first = min((_ts(t.get("entry_at")) for t in trades if t["symbol"] == s and t.get("entry_at")), default=None)
            span = max(90, int(((now - first).days if first else 30) + 90))
            res = get_daily_ohlc(db, s, days=min(span, 400), now=now)
            bars[s] = res.get("bars") or []
            bars_meta[s] = {"kind": res.get("kind"), "source": (res.get("source") or {}).get("table") or "ohlc_bars",
                            "as_of": res.get("as_of")}
        reads.append("ohlc_bars projection")

    identities: dict[str, dict[str, Any]] = {}
    try:
        from lib import identity_registry as ir
        idoc = ir.load_cached()
        for s in syms:
            ent = ir.lookup_symbol(idoc, s) or {}
            if ent:
                identities[s] = {"security_guid": ent.get("security_guid") or ent.get("subject_guid"),
                                 "status": ent.get("identity_status")}
    except Exception:  # noqa: BLE001
        pass

    inputs = {"days": days, "links": links, "recs": recs, "link_status": link_status, "opp_history": opp_history,
              "opp_now": opp_now, "opp_at": opp_at, "entry_states": entry_states, "stops": stops, "stops_at": stops_at,
              "bars": bars if with_bars else {}, "bars_meta": bars_meta, "desk_rows": desk_rows, "desk_at": desk_at,
              "insights": insights, "identities": identities, "trades_at": trades_at, "holdings_at": holdings_at,
              "gaps": gaps, "reads": reads}
    return trades, inputs


def list_trade_journeys(query: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """GET /api/v3/data-broker/trade-journeys[?days=30&symbol=X] — cached 60 s."""
    q = query or {}
    try:
        days = max(1, min(365, int(str(q.get("days") or DEFAULT_DAYS))))
    except ValueError:
        days = DEFAULT_DAYS
    sym = _up(q.get("symbol")) or None
    key = f"list:{days}:{sym}"
    hit = _CACHE.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_S and str(q.get("fresh") or "") not in ("1", "true"):
        return hit[1]
    db = _db_query()
    trades, inputs = gather(db, days=days, symbol=sym)
    prospects, status = _cio_prospects(sorted({t["symbol"] for t in trades}))
    inputs["cio_prospect_status"] = status
    out = build_trade_journeys(trades, inputs=inputs, prospects=prospects)
    for r in out["journeys"]:
        r.pop("chart", None)
    _CACHE[key] = (time.monotonic(), out)
    return out


def detail_trade_journey(trade_id: str, query: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """GET /api/v3/data-broker/trade-journeys/{trade_id} — one journey with its price band (daily bars)."""
    q = query or {}
    tid = str(trade_id or "")
    sym = None
    if tid.startswith("open:"):
        sym = tid.rsplit(":", 1)[-1]
    try:
        days = max(1, min(365, int(str(q.get("days") or DEFAULT_DAYS))))
    except ValueError:
        days = DEFAULT_DAYS
    db = _db_query()
    trades, inputs = gather(db, days=days, symbol=sym or _up(q.get("symbol")) or None, with_bars=False)
    mine = [t for t in trades if t.get("trade_id") == tid]
    if not mine:
        return {"ok": False, "error": "not_found", "trade_id": tid, "schema": SCHEMA}
    s = mine[0]["symbol"]
    if db is not None:
        from lib.data_broker.ohlc_bars import get_daily_ohlc
        first = _ts(mine[0].get("entry_at"))
        span = max(90, int(((datetime.now(timezone.utc) - first).days if first else 30) + 90))
        res = get_daily_ohlc(db, s, days=min(span, 400))
        inputs["bars"] = {s: res.get("bars") or []}
        inputs["bars_meta"] = {s: {"kind": res.get("kind"), "source": (res.get("source") or {}).get("table") or "ohlc_bars",
                                   "as_of": res.get("as_of")}}
        inputs["reads"].append("ohlc_bars projection")
    prospects, status = _cio_prospects([s])
    inputs["cio_prospect_status"] = status
    out = build_trade_journeys(mine, inputs=inputs, prospects=prospects)
    j = out.pop("journeys")[0]
    out["journey"] = j
    return out
