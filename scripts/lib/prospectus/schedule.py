"""Run windows and the trigger queue for Ticker Prospectuses (operator 2026-10-26).

Operator, verbatim: "Those new reports shouldn't just run ad hoc independently. They should be queued up and run a
certain time of the day, like if something moves plus or minus the 8% threshold".

* **Triggers only enqueue.** Cadence (monthly holdings full, quarterly watch full, weekly holdings delta), earnings
  after, |day move| >= 8% on the CLOSE, material news, a stop event, a CIO stance change and a promotion to proposal
  each put the symbol on the queue with a reason. Nothing is written outside a window.
* **Run windows** (``config/prospectus.json`` ``run_windows``, America/New_York wall clock, so DST is handled by
  ``zoneinfo``): a window that is due evaluates its triggers, then drains the queue in priority order (operator
  rewrites, then holdings by $ value, then the watch list) up to its ``max_reports``; the governed credit path stops
  the drain for the day at its cap (``QueueLater``). Whatever is left stays queued for the next window.
* **"Rewrite now"** (operator POST, priority 1) stays immediate: every lane fire that is not a window drains only the
  operator rows.
* **Delivery is not done here.** A run writes one outbox record (``delivery.write_outbox``); the host sender
  ``scripts/prospectus_deliver.py`` sends it. This module and its lane import no sender (AGENTS.md §23.14, §24.1).

READ_ONLY_ADVISORY (MBI_BEHAVIOR=0): nothing here sizes, orders, stops or weights.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import importlib
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from . import store
from .inputs import earnings_passed, holdings_ranked

PRIORITY_OPERATOR, PRIORITY_PREMIUM, PRIORITY_HOLDING, PRIORITY_WATCH = 1, 10, 100, 1000
DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
WEEKDAYS = DAY_NAMES[:5]
ALL_TRIGGERS = ("missing", "cadence_full", "after_earnings", "day_move", "material_news", "stop_event",
                "cio_stance_change", "promoted_to_proposal", "weekly_delta")
HELD = "held_for_window"
WINDOWS_FILE = "windows.json"
MARKET_CLOSE_ET = time(16, 0)


def _dt(value: Any) -> datetime | None:
    try:
        out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return out if out.tzinfo else out.replace(tzinfo=timezone.utc)


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


# ── windows ───────────────────────────────────────────────────────────────────────────────────────────────────
def window_cfg(cfg: dict) -> dict:
    return cfg.get("run_windows") or {}


def tz(cfg: dict) -> ZoneInfo:
    return ZoneInfo(str(window_cfg(cfg).get("timezone") or "America/New_York"))


def window_days(win: dict) -> tuple[str, ...]:
    days = tuple(str(d).lower()[:3] for d in (win.get("days") or WEEKDAYS))
    if win.get("weekend"):
        days = tuple(dict.fromkeys(days + ("sat", "sun")))
    return days


def window_start(win: dict, day: date, zone: ZoneInfo) -> datetime:
    hh, mm = (int(x) for x in str(win["time"]).split(":"))
    return datetime.combine(day, time(hh, mm), tzinfo=zone)


def window_key(win: dict, day: date) -> str:
    return f"{day.isoformat()}:{win['id']}"


def read_window_state(base: Path) -> dict:
    doc = store._read_json(base / WINDOWS_FILE, None)
    if not isinstance(doc, dict) or not isinstance(doc.get("runs"), dict):
        return {"schema": "ProspectusWindows@v1", "runs": {}, "spend_by_month": {}}
    doc.setdefault("spend_by_month", {})
    return doc


def due_window(cfg: dict, base: Path, now: datetime) -> dict | None:
    """The enabled window that should run now, or None.

    A window is due from its wall-clock start (ET) until ``catch_up_minutes`` later, on its days, once per day: a
    missed or late n8n fire still runs it, and a second fire inside the span does not run it twice.
    """
    wc = window_cfg(cfg)
    zone = tz(cfg)
    local = now.astimezone(zone)
    runs = read_window_state(base)["runs"]
    catch_up = timedelta(minutes=int(wc.get("catch_up_minutes", 120)))
    for win in sorted((w for w in wc.get("windows") or [] if w.get("enabled", True)), key=lambda w: w["time"]):
        if DAY_NAMES[local.weekday()] not in window_days(win):
            continue
        start = window_start(win, local.date(), zone)
        if start <= local < start + catch_up and window_key(win, local.date()) not in runs:
            return dict(win, key=window_key(win, local.date()), start=start.isoformat())
    return None


def next_windows(cfg: dict, now: datetime, count: int = 3) -> list[dict]:
    """The next ``count`` window starts (for receipts and the dry run)."""
    zone = tz(cfg)
    local = now.astimezone(zone)
    out = []
    for offset in range(0, 8):
        day = local.date() + timedelta(days=offset)
        for win in sorted((w for w in window_cfg(cfg).get("windows") or [] if w.get("enabled", True)),
                          key=lambda w: w["time"]):
            start = window_start(win, day, zone)
            if start > local and DAY_NAMES[day.weekday()] in window_days(win):
                out.append({"id": win["id"], "start": start.isoformat()})
    return out[:count]


# ── triggers: enqueue only ────────────────────────────────────────────────────────────────────────────────────
def _close_at(bar_date: date, zone: ZoneInfo) -> datetime:
    return datetime.combine(bar_date, MARKET_CLOSE_ET, tzinfo=zone)


def day_move(bars: list[dict]) -> tuple[float, date] | None:
    """(% move of the last close vs the one before, the last bar's date), from closes only."""
    rows = [b for b in (bars or []) if b.get("close") and _date(b.get("price_date") or b.get("date"))][-2:]
    if len(rows) != 2:
        return None
    prev, last = float(rows[0]["close"]), float(rows[1]["close"])
    if prev <= 0:
        return None
    return (last / prev - 1) * 100, _date(rows[1].get("price_date") or rows[1].get("date"))


def _trigger_reason(sources: Any, row: dict, entry: dict, gen: datetime, holding: dict | None, cfg: dict,
                    allowed: set[str], now: datetime) -> str | None:
    trig = (cfg.get("cadence") or {}).get("triggers") or {}
    sym, scope = row["symbol"], row["scope"]
    digest = entry.get("inputs_digest") or {}
    zone = tz(cfg)
    if "day_move" in allowed and trig.get("day_move_abs_pct") and scope in (trig.get("day_move_scopes") or ["holding"]):
        try:
            mv = day_move(sources.bars(sym))
        except Exception:  # noqa: BLE001 - an unreadable series never blocks the other triggers
            mv = None
        # On the CLOSE: the bar's session close (16:00 ET) must be after the last report, so one close fires once.
        if mv and abs(mv[0]) >= float(trig["day_move_abs_pct"]) and _close_at(mv[1], zone) > gen \
                and _close_at(mv[1], zone) <= now:
            return f"day_move {mv[0]:+.1f}% close {mv[1].isoformat()}"
    if "material_news" in allowed and trig.get("material_news"):
        try:
            cats = sources.catalysts(sym) or []
        except Exception:  # noqa: BLE001
            cats = []
        fresh = [c for c in cats if (_dt(c.get("at")) or gen) > gen]
        if fresh:
            return "material_news"
    if "stop_event" in allowed and trig.get("stop_event") and scope == "holding" and holding \
            and digest.get("stop_levels") is not None:
        try:
            levels = sorted(float(s["stop_price"]) for s in sources.stops(sym, holding.get("accounts") or [])
                            if s.get("stop_price") is not None)
        except Exception:  # noqa: BLE001
            levels = None
        if levels is not None and [round(x, 4) for x in levels] != [round(float(x), 4) for x in digest["stop_levels"]]:
            return "stop_event"
    if ("cio_stance_change" in allowed or "promoted_to_proposal" in allowed):
        try:
            cio = sources.cio(sym) or {}
        except Exception:  # noqa: BLE001
            cio = {}
        if "cio_stance_change" in allowed and trig.get("cio_stance_change") and scope == "holding" \
                and cio.get("stance") and digest.get("cio_stance") != cio.get("stance"):
            return "cio_stance_change"
        if "promoted_to_proposal" in allowed and trig.get("promoted_to_proposal") and scope == "watch" \
                and "propos" in str(cio.get("stage") or "").lower() \
                and "propos" not in str(digest.get("cio_stage") or "").lower():
            return "promoted_to_proposal"
    return None


def evaluate_triggers(universe: list[dict], index: dict, sources: Any, cfg: dict, *, now: datetime,
                      triggers: list[str] | str = "all", scopes: list[str] | None = None,
                      holdings: dict | None = None) -> list[dict]:
    """Rows to ENQUEUE (never to write now): ``{symbol, scope, premium, priority, mode, reason, requested_by}``.

    Priority: holdings by $ value (premium first), then the watch list.
    """
    allowed = set(ALL_TRIGGERS if triggers == "all" else triggers)
    items = index.get("items") or {}
    cad_all = cfg.get("cadence") or {}
    holdings = holdings or {}
    out = []
    for row in universe:
        sym, scope = row["symbol"], row["scope"]
        if scopes and scope not in scopes:
            continue
        rank = int(row.get("rank") or 0)
        prio = (PRIORITY_PREMIUM if row.get("premium") else PRIORITY_HOLDING) + rank if scope == "holding" \
            else PRIORITY_WATCH
        base = {"symbol": sym, "scope": scope, "premium": bool(row.get("premium")), "priority": prio,
                "requested_by": "schedule"}
        entry = items.get(sym) or {}
        gen = _dt(entry.get("generated_at"))
        if gen is None:
            if "missing" in allowed:
                out.append(dict(base, mode="full", reason="missing"))
            continue
        cad = cad_all.get(scope) or {}
        age = (now - gen).days
        reason, mode = None, "full"
        if "cadence_full" in allowed and age >= int(cad.get("full_days", 30 if scope == "holding" else 90)):
            reason = "monthly_due" if scope == "holding" else "quarterly_due"
        elif "after_earnings" in allowed and cad.get("after_earnings") \
                and earnings_passed(entry.get("earnings_date"), gen.date(), now.date()):
            reason = "after_earnings"
        else:
            reason = _trigger_reason(sources, row, entry, gen, holdings.get(sym), cfg, allowed, now)
            if reason is None and "weekly_delta" in allowed and scope == "holding" \
                    and age >= int(cad.get("delta_days", 7)):
                reason, mode = "weekly_delta", "delta"
        if reason:
            out.append(dict(base, mode=mode, reason=reason))
    return sorted(out, key=lambda r: (r["priority"], r["symbol"]))


def plan_universe(holdings: dict, watch: list[str], cfg: dict) -> list[dict]:
    """Holdings ranked by $ value (top N premium), then the watch list; a holding wins a duplicate."""
    top = int(cfg.get("premium_top_n", 5))
    rows = [{"symbol": s, "scope": "holding", "value_usd": round(v, 2), "rank": i, "premium": i < top}
            for i, (s, v) in enumerate(holdings_ranked(holdings or {}))]
    seen = {r["symbol"] for r in rows}
    for sym in watch or []:
        sym = store.norm_symbol(sym)
        if sym and sym not in seen:
            rows.append({"symbol": sym, "scope": "watch", "value_usd": None, "rank": None, "premium": False})
            seen.add(sym)
    return rows


# ── draining: hold the rows a run may not take, restore them after ───────────────────────────────────────────
def is_operator_row(row: dict) -> bool:
    return int(row.get("priority", 500)) <= PRIORITY_OPERATOR or str(row.get("reason") or "").startswith("operator")


def hold_rows(base: Path, eligible: Callable[[dict], bool]) -> int:
    """Park queued rows the run may not take (state ``held_for_window``) so ``run_queue`` skips them."""
    held = 0
    with store.locked(base):
        doc = store.read_queue(base)
        for row in doc["items"]:
            if row.get("state") in ("queued", None) and not eligible(row):
                row["state"] = HELD
                held += 1
        store.write_json(base / "queue.json", doc)
    return held


def release_held(base: Path) -> int:
    """Return every parked row to ``queued`` (also run first on every fire, so a crash never strands a row)."""
    released = 0
    with store.locked(base):
        doc = store.read_queue(base)
        for row in doc["items"]:
            if row.get("state") == HELD:
                row["state"] = "queued"
                released += 1
        if released:
            store.write_json(base / "queue.json", doc)
    return released


def batch_hook(cfg: dict) -> Callable | None:
    """The Batch submitter for watch rows, when the cost-settings PR provides one; None means run synchronously.

    Contract (for that PR): ``scripts.lib.prospectus.batch.submit_window(base, rows, cfg) -> {"submitted": [sym]}``.
    """
    if not ((window_cfg(cfg).get("watch_batch") or {}).get("enabled")):
        return None
    for name in ("scripts.lib.prospectus.batch", "lib.prospectus.batch"):
        try:
            mod = importlib.import_module(name)
        except ImportError:
            continue
        fn = getattr(mod, "submit_window", None)
        if callable(fn):
            return fn
    return None


def drain(base: Path, sources: Any, cfg: dict, *, limit: int, eligible: Callable[[dict], bool],
          run_queue_fn: Callable, holdings: dict, manual: bool = False) -> dict:
    """Run ``run_queue`` over the eligible rows only, in queue (priority) order, up to ``limit``."""
    hold_rows(base, eligible)
    try:
        return run_queue_fn(base, sources, cfg, limit=max(0, int(limit)), holdings=holdings, manual=manual)
    finally:
        release_held(base)


def record_window(base: Path, key: str, receipt: dict, *, month: str, cost_usd: float) -> dict:
    """Mark a window run (once per day) and add its cost to the month's prospectus spend."""
    with store.locked(base, ".windows.lock"):
        doc = read_window_state(base)
        if key:
            doc["runs"][key] = receipt
            # keep the file small: the last 120 window runs
            for old in sorted(doc["runs"])[:-120]:
                doc["runs"].pop(old, None)
        doc["spend_by_month"][month] = round(float(doc["spend_by_month"].get(month, 0.0)) + float(cost_usd or 0), 4)
        store.write_json(base / WINDOWS_FILE, doc)
        return doc
