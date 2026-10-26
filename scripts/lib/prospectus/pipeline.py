"""Universe, cadence, the first-build order and the queue runner.

Cadence (contract): holdings — full rewrite monthly and after each earnings report, a weekly short delta, and an
immediate rewrite on material news, a day move of at least 8%, a stop event or a CIO stance change. Watch — full
quarterly and after earnings, on material news, and fresh when the CIO stage reaches a proposal. First build:
premium top N holdings, then the other holdings by value, then the watch list, paced by the credit's daily cap
(the queue simply stops for the day at PAUSED_TODAY and resumes on the next run).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from . import quality_gate, render, store
from .generate import GenerationFailed, QueueLater, governed_generate, write
from .blocks import book_returns
from .domains import full_assemble
from .inputs import earnings_passed, holdings_ranked

PRIORITY_PREMIUM, PRIORITY_HOLDING, PRIORITY_WATCH, PRIORITY_OPERATOR = 10, 100, 1000, 1


def _dt(value: Any) -> datetime | None:
    try:
        out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return out if out.tzinfo else out.replace(tzinfo=timezone.utc)


def plan_universe(sources: Any, cfg: dict, *, scope: str = "all", symbols: list[str] | None = None) -> list[dict]:
    """Holdings (ranked by $ value; top N premium) then the watch list, de-duplicated (a holding wins)."""
    rows: list[dict] = []
    held = {}
    if scope in ("all", "holdings") or symbols:
        held = sources.holdings() or {}
    top = int(cfg.get("premium_top_n", 5))
    for rank, (sym, value) in enumerate(holdings_ranked(held)):
        rows.append({"symbol": sym, "scope": "holding", "value_usd": round(value, 2), "rank": rank,
                     "premium": rank < top})
    if scope in ("all", "watch") or symbols:
        seen = {r["symbol"] for r in rows}
        for sym in sources.watch_symbols() or []:
            if store.norm_symbol(sym) and sym not in seen:
                rows.append({"symbol": sym, "scope": "watch", "value_usd": None, "rank": None, "premium": False})
                seen.add(sym)
    if scope == "holdings":
        rows = [r for r in rows if r["scope"] == "holding"]
    elif scope == "watch":
        rows = [r for r in rows if r["scope"] == "watch"]
    if symbols:
        wanted = {store.norm_symbol(s) for s in symbols} - {None}
        rows = [r for r in rows if r["symbol"] in wanted] + [
            {"symbol": s, "scope": "watch", "value_usd": None, "rank": None, "premium": False}
            for s in sorted(wanted - {r["symbol"] for r in rows})]
    return rows


def first_build_rows(universe: list[dict]) -> list[dict]:
    out = []
    for row in universe:
        if row["scope"] == "holding":
            prio = (PRIORITY_PREMIUM if row["premium"] else PRIORITY_HOLDING) + int(row["rank"] or 0)
        else:
            prio = PRIORITY_WATCH
        out.append({"symbol": row["symbol"], "scope": row["scope"], "premium": row["premium"], "priority": prio,
                    "mode": "full", "reason": "first_build", "requested_by": "first_build"})
    return sorted(out, key=lambda r: (r["priority"], r["symbol"]))


def next_due(entry: dict, cfg: dict) -> str | None:
    gen = _dt(entry.get("generated_at"))
    if gen is None:
        return None
    cad = (cfg.get("cadence") or {}).get(entry.get("scope") or "watch") or {}
    days = cad.get("delta_days") or cad.get("full_days") or 30
    due = gen + timedelta(days=int(days))
    earn = _dt(entry.get("earnings_date"))
    if earn is not None and earn > gen:
        due = min(due, earn + timedelta(days=1))
    return due.isoformat()


def due_rows(universe: list[dict], index: dict, sources: Any, cfg: dict, *, now: datetime) -> list[dict]:
    """Rows whose cadence or a trigger says rewrite now."""
    items = index.get("items") or {}
    trig = (cfg.get("cadence") or {}).get("triggers") or {}
    out = []
    for row in universe:
        sym, scope = row["symbol"], row["scope"]
        entry = items.get(sym) or {}
        base = {"symbol": sym, "scope": scope, "premium": row["premium"],
                "priority": (PRIORITY_PREMIUM if row["premium"] else PRIORITY_HOLDING if scope == "holding" else PRIORITY_WATCH)}
        gen = _dt(entry.get("generated_at"))
        if gen is None:
            out.append(dict(base, mode="full", reason="missing"))
            continue
        cad = (cfg.get("cadence") or {}).get(scope) or {}
        age = (now - gen).days
        digest = entry.get("inputs_digest") or {}
        reason, mode = None, "full"
        if age >= int(cad.get("full_days", 30 if scope == "holding" else 90)):
            reason = "cadence_full"
        elif cad.get("after_earnings") and earnings_passed(entry.get("earnings_date"), gen.date(), now.date()):
            reason = "after_earnings"
        else:
            reason = _trigger(sources, sym, scope, gen, digest, trig)
            if reason is None and scope == "holding" and age >= int(cad.get("delta_days", 7)):
                reason, mode = "weekly_delta", "delta"
        if reason:
            out.append(dict(base, mode=mode, reason=reason))
    return out


def _trigger(sources: Any, sym: str, scope: str, gen: datetime, digest: dict, trig: dict) -> str | None:
    try:
        if trig.get("material_news"):
            cats = sources.catalysts(sym) or []
            if any((_dt(c.get("at")) or gen) > gen for c in cats):
                return "material_news"
        if scope == "holding" and trig.get("day_move_abs_pct"):
            bars = [b for b in (sources.bars(sym) or [])[-2:] if b.get("close")]
            if len(bars) == 2 and abs(float(bars[1]["close"]) / float(bars[0]["close"]) - 1) * 100 >= float(trig["day_move_abs_pct"]):
                return "day_move"
        cio = sources.cio(sym) or {}
        if scope == "holding" and trig.get("cio_stance_change") and digest.get("cio_stance") != cio.get("stance") and cio.get("stance"):
            return "cio_stance_change"
        if scope == "watch" and trig.get("promoted_to_proposal") and "propos" in str(cio.get("stage") or "").lower() \
                and "propos" not in str(digest.get("cio_stage") or "").lower():
            return "promoted_to_proposal"
    except Exception:  # noqa: BLE001 - a trigger read failure never blocks the cadence path
        return None
    return None


def run_queue(base: Path, sources: Any, cfg: dict, *, limit: int, holdings: dict | None = None,
              generate_fn: Callable = governed_generate, now_fn: Callable[[], datetime] | None = None,
              manual: bool = False, log: Callable[[str], None] = print) -> dict:
    """Process up to ``limit`` queued rows (priority order). Stops for the day when the credit is unavailable."""
    now_fn = now_fn or (lambda: datetime.now(timezone.utc))
    holdings = holdings if holdings is not None else (sources.holdings() or {})
    universe = {r["symbol"]: r for r in store.read_universe(base)}
    procs = cfg["processes"]
    brave = cfg.get("brave") or {}
    summary = {"done": [], "queued": [], "failed": [], "stopped_reason": None, "cost_usd": 0.0}
    book = None
    for row in list(store.read_queue(base)["items"]):
        if len(summary["done"]) + len(summary["failed"]) >= limit:
            break
        if row.get("state") not in ("queued", None):
            continue
        sym, scope = row["symbol"], row.get("scope", "watch")
        if scope == "holding" and sym not in holdings:
            scope = "watch"  # sold since it was queued
        store.mark(base, sym, state="running")
        store.update_index(base, sym, status="running", scope=scope)
        now = now_fn()
        if book is None:
            try:
                book = book_returns(holdings, sources.bars)
            except Exception:  # noqa: BLE001
                book = {}
        bundle = full_assemble(sources, sym, scope, cfg=cfg, holding=holdings.get(sym), now=now, book=book,
                               request_refresh=True)
        limit_day = int(brave.get("daily_limit", 40))
        previous = store.read_prospectus(base, sym) if row.get("mode") == "delta" else None
        mode = "delta" if previous else "full"
        version = store.stamp(now)
        try:
            doc = write(bundle, processes=procs, premium=bool(row.get("premium") or (universe.get(sym) or {}).get("premium")),
                        mode=mode, previous=previous, cfg=cfg, generate_fn=generate_fn, manual=manual, now=now,
                        version=version, search_fn=getattr(sources, "search", None),
                        allowance_fn=lambda take: store.search_allowance(base, limit_day, take=take))
        except QueueLater as exc:
            store.mark(base, sym, state="queued", error=f"credit: {exc}"[:240])
            store.update_index(base, sym, status="queued", last_error=f"credit: {exc}"[:240])
            summary["queued"].append(sym)
            summary["stopped_reason"] = str(exc)[:200]
            log(f"QUEUED {sym}: credit unavailable ({str(exc)[:120]}) — stopping for this run")
            break
        except quality_gate.DataBlocked as exc:
            # Data-quality gate HARD_FAIL: no model was called. Park the row (no retry loop), file the repair.
            repairs = quality_gate.request_repairs(sym, exc.gate)
            store.mark(base, sym, state="blocked_data", error=str(exc)[:240])
            store.update_index(base, sym, status="blocked_data", last_error=str(exc)[:240], failure_reason=None,
                               gate_repairs=repairs, **quality_gate.index_fields(exc.gate))
            summary.setdefault("blocked_data", []).append(sym)
            log(f"BLOCKED_DATA {sym}: {str(exc)[:160]}")
            continue
        except GenerationFailed as exc:
            attempts = int(row.get("attempts", 0)) + 1
            final = attempts >= int(cfg.get("max_attempts_per_day", 2))
            store.mark(base, sym, state="failed" if final else "queued", error=str(exc)[:240])
            store.update_index(base, sym, status="failed" if final else "queued", last_error=str(exc)[:240],
                               failure_reason=str(exc)[:240])
            summary["failed"].append(sym)
            log(f"FAILED {sym}: {str(exc)[:160]}")
            continue
        files = render.render_all(doc)
        store.write_version(base, sym, version, doc, files)
        entry = {"name": doc["name"], "scope": scope, "version": version, "generated_at": doc["generated_at"],
                 "model": doc["model"], "cost_usd": doc["cost_usd"], "status": doc.get("status") or "ready",
                 "verdict_line": doc["verdict_line"], "partial_gaps": doc.get("partial_gaps") or [], "failure_reason": None,
                 "earnings_date": bundle.context.get("next_earnings_date"), "last_error": None,
                 "inputs_digest": doc["inputs_digest"], "formats": sorted(k.split(".")[-1] for k in files if "/" not in k),
                 **quality_gate.index_fields(doc.get("gate") or {}, (doc.get("gate") or {}).get("layers", {}).get("post_write"))}
        entry["next_due"] = next_due(entry, cfg)
        store.update_index(base, sym, **entry)
        store.mark(base, sym, state="done", done=True)
        if (doc.get("gate") or {}).get("rewrite_requested") and row.get("reason") != "gate_rewrite":
            store.enqueue(base, [{"symbol": sym, "scope": scope, "premium": bool(row.get("premium")), "mode": "full",
                                  "priority": PRIORITY_WATCH + 500, "reason": "gate_rewrite",
                                  "requested_by": "quality_gate"}], now=now)  # one rewrite, never a loop
        summary["done"].append(sym)
        summary["cost_usd"] += float(doc.get("cost_usd") or 0)
        log(f"READY {sym} {version} model={doc['model']} cost=${float(doc.get('cost_usd') or 0):.4f}")
    summary["cost_usd"] = round(summary["cost_usd"], 4)
    return summary


def estimate(prompt: str, cfg: dict, *, premium: bool, pricing: dict) -> dict:
    """Dry-run cost estimate from the prompt size (no provider call)."""
    est = cfg.get("estimate") or {}
    tokens_in = int(len(prompt) / float(est.get("chars_per_token", 3.6)))
    tokens_out = int(est.get("expected_output_tokens", 9000))
    model = "claude-fable-5-1" if premium else "claude-opus-5-5"
    p = pricing.get(model) or {}
    usd = tokens_in * float(p.get("input", 0)) / 1e6 + tokens_out * float(p.get("output", 0)) / 1e6
    worst_in = len(prompt.encode("utf-8")) + 4096
    hold = (worst_in * float(p.get("cache_write_5m", 0)) + int(cfg.get("max_output_tokens", 16000)) * float(p.get("output", 0))) / 1e6 * 2
    return {"model": model, "prompt_bytes": len(prompt.encode("utf-8")), "input_tokens_est": tokens_in,
            "output_tokens_est": tokens_out, "cost_usd_est": round(usd, 4), "reservation_hold_usd": round(hold, 4)}
