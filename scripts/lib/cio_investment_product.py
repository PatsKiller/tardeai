"""CIO Investment Intelligence Product — the four canonical books.

READ_ONLY_ADVISORY. Turns existing desks (re-entry, watchlist/queue, research,
Financial Senses, lessons, memory, regime) into:

  1. Market Temperament
  2. Re-Entry Book
  3. Opportunity Book
  4. Portfolio Action Book

and a CIORunWorker-compatible synthesis_fn that emits real recommendations.

Desk READY / IN_ZONE / NEAR is never auto-promoted to RE_ENTER.
A candidate-specific governed RE_ENTER is created only by adjudication:

  * explicit queue verdict RE_ENTER, or
  * IN_ZONE/READY + explicit ADD + valid FS + no restricting lesson
    when advisory influence is ACTIVE_ADVISORY/CANARY.

MEMORY_BEHAVIOR_INFLUENCE stays 0. Memory/lessons/FS never grant broker authority.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from scripts.lib.maturity_control.store import resolve_root

SCHEMA = "CIOInvestmentProduct@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

READY_STATES = frozenset({"READY TO REVIEW", "NEAR ENTRY", "OVERSOLD REVIEW", "IN_ZONE", "READY"})
AVOID_SIGNALS = frozenset({"ABOVE_ZONE"})
RESTRICT_LESSON = frozenset({"RESTRICTED", "RETIRED"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(now: Optional[datetime] = None) -> str:
    return (now or _now()).replace(microsecond=0).isoformat()


def _env(name: str, default: str = "", env: Optional[dict[str, str]] = None) -> str:
    return str((env or os.environ).get(name) or default).strip()


def _influence_active(env: Optional[dict[str, str]] = None) -> dict[str, Any]:
    from scripts.lib.advisory_influence.gates import current_gates, present_enhanced
    from scripts.lib.agent_memory_shadow import memory_mode
    gates = current_gates(env)
    mem = memory_mode(env)
    return {
        "gates": gates,
        "lesson_enhanced": present_enhanced(gates["lesson_mode"]),
        "fs_enhanced": present_enhanced(gates["financial_senses_mode"]),
        "memory_enhanced": mem in {"CANARY", "ACTIVE_ADVISORY"},
        "memory_mode": mem,
        "memory_behavior_influence": _env("MEMORY_BEHAVIOR_INFLUENCE", "0", env) or "0",
        "financial_action": False,
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}
    return obj if isinstance(obj, dict) else {}


def _read_jsonl(path: Path, n: int = 200) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for line in lines[-n:]:
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def paths(root: Path | str | None = None) -> dict[str, Path]:
    base = resolve_root(root) / "data" / "cio"
    return {
        "brief": base / "cio_investment_brief.json",
        "briefs": base / "cio_investment_briefs.jsonl",
        "verdicts": base / "cio_governed_verdicts.json",
        "verdicts_log": base / "cio_governed_verdicts.jsonl",
    }


# ── Collectors (fail-soft) ──────────────────────────────────────────────────


def collect_queue(root: Path | str | None = None) -> dict[str, Any]:
    try:
        from scripts.lib.cio_opportunity_queue import build_queue_from_executor
        from scripts.db_adapter import _execute  # type: ignore
        return build_queue_from_executor(_execute)
    except Exception:
        pass
    try:
        import scripts.api_v2 as v2
        from scripts.lib.cio_opportunity_queue import build_queue_from_executor
        return build_queue_from_executor(v2._db_query)
    except Exception:
        return {"items": [], "top": [], "count": 0, "by_source": {}, "material": False}


def collect_previously_traded() -> list[dict[str, Any]]:
    sql = (
        "SELECT symbol, last_exit_price, current_price, reentry_zone_low, reentry_zone_high, "
        "reentry_signal, pct_above_exit, best_pnl_pct, is_currently_held "
        "FROM previously_traded_watchlist WHERE is_currently_held=false "
        "ORDER BY CASE reentry_signal WHEN 'IN_ZONE' THEN 0 WHEN 'WATCH' THEN 1 "
        "WHEN 'BELOW_ZONE' THEN 2 ELSE 3 END, best_pnl_pct DESC NULLS LAST LIMIT 40"
    )
    try:
        import scripts.api_v2 as v2
        rows = v2._db_query(sql, fetch="all") or []
        return [dict(r) for r in rows]
    except Exception:
        return []


def collect_holdings(root: Path | str | None = None) -> dict[str, Any]:
    base = resolve_root(root)
    for rel in (
        "data/portfolios/state/holdings.json",
        "data/state/holdings.json",
    ):
        doc = _read_json(base / rel)
        if doc:
            return doc
    return {}


def collect_lessons(root: Path | str | None = None) -> dict[str, Any]:
    try:
        from scripts.lib.maturity_control.lessons import collect_lessons
        return collect_lessons(root=root)
    except Exception:
        return {"lessons": [], "counts": {}}


def collect_fs(root: Path | str | None = None) -> list[dict[str, Any]]:
    rows = _read_jsonl(resolve_root(root) / "data/cio/agent_tool_traces.jsonl", 80)
    return [r for r in rows if r.get("fs_provider") or r.get("fs_capability")]


def collect_memory(root: Path | str | None = None) -> dict[str, Any]:
    try:
        from scripts.lib.agent_durable_memory import get_durable_provider
        p = get_durable_provider(root)
        return {"health": p.health(), "counts": p.counts(), "sample": list(p._store.values())[:8]}
    except Exception:
        return {"health": {"status": "NOT_CONFIGURED"}, "counts": {}, "sample": []}


def collect_regime() -> dict[str, Any]:
    try:
        import scripts.api_v2 as v2
        row = v2._db_query(
            "SELECT regime_label, created_at FROM market_regime_snapshots ORDER BY created_at DESC LIMIT 1",
            fetch="one",
        )
        if row:
            return {"label": row.get("regime_label") or row.get("label"), "as_of": row.get("created_at")}
    except Exception:
        pass
    return {"label": "UNKNOWN", "as_of": None}


# ── Adjudication ────────────────────────────────────────────────────────────


def _queue_by_symbol(queue: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for it in (queue.get("items") or queue.get("top") or []):
        if not isinstance(it, dict):
            continue
        sym = str(it.get("symbol") or "").upper()
        if not sym:
            continue
        out.setdefault(sym, []).append(it)
    return out


def _lesson_restricts(lessons: dict[str, Any], symbol: str) -> bool:
    for les in lessons.get("lessons") or []:
        if les.get("lifecycle") in RESTRICT_LESSON:
            syms = [str(s).upper() for s in (les.get("symbols") or [])]
            if symbol in syms:
                return True
    return False


def _fs_ok(fs_rows: list[dict[str, Any]]) -> bool:
    from scripts.lib.advisory_influence.gates import fs_receipt_eligible
    recent = fs_rows[-8:]
    if not recent:
        return False
    return any(fs_receipt_eligible(r) for r in recent)


def adjudicate_reentry(
    row: dict[str, Any],
    *,
    qitems: list[dict[str, Any]],
    lessons: dict[str, Any],
    fs_ok: bool,
    infl: dict[str, Any],
) -> dict[str, Any]:
    symbol = str(row.get("symbol") or "").upper()
    signal = str(row.get("reentry_signal") or row.get("state") or "").upper()
    verdicts = [str(i.get("verdict") or "").upper() for i in qitems]
    sources = {str(i.get("source") or "") for i in qitems}
    why_sold = f"Prior profitable exit; last exit {row.get('last_exit_price') or 'n/a'}."
    vs_exit = row.get("pct_above_exit")
    zone = f"{row.get('reentry_zone_low') or '?'}–{row.get('reentry_zone_high') or '?'}"
    restrict = _lesson_restricts(lessons, symbol)

    status = "WAIT"
    governed = None
    change = "A candidate-specific governed RE_ENTER verdict plus non-stale confirmation."
    if "EXIT" in verdicts or "TRIM" in verdicts:
        status = "AVOID"
        change = "Restricting desk verdict is lifted."
    elif "RE_ENTER" in verdicts:
        status = "REENTER"
        governed = "RE_ENTER"
        change = "Governed RE_ENTER verdict is revoked or freshness blocks it."
    elif signal in AVOID_SIGNALS or (isinstance(vs_exit, (int, float)) and vs_exit > 25):
        status = "AVOID"
        change = "Price returns to the re-entry zone without chasing the extension."
    elif signal in READY_STATES or any(str(i.get("state") or "").upper() in READY_STATES for i in qitems):
        if restrict:
            status = "WAIT"
            change = "Restricting lesson is retired and zone confirmation remains."
        elif infl.get("lesson_enhanced") and "ADD" in verdicts and fs_ok:
            status = "REENTER"
            governed = "RE_ENTER"
            change = "ADD confluence, FS, or zone confirmation fails."
        elif len(sources) >= 2 or "ADD" in verdicts:
            status = "NEAR"
            change = "Second independent source + valid FS, or an explicit RE_ENTER verdict."
        else:
            status = "NEAR" if signal in {"IN_ZONE", "READY TO REVIEW", "READY"} else "WAIT"
            change = "Independent research/queue confluence plus valid Financial Senses."
    rec = {
        "symbol": symbol,
        "status": status,
        "governed_verdict": governed,
        "why_sold": why_sold,
        "what_happened_since": f"Signal {signal or 'n/a'}; {vs_exit}% vs exit" if vs_exit is not None else f"Signal {signal or 'n/a'}.",
        "current_price": row.get("current_price"),
        "last_exit_price": row.get("last_exit_price"),
        "setup": f"Zone {zone}; desk {signal or 'n/a'}",
        "financial_senses": "valid_recent" if fs_ok else "none_or_stale",
        "research_change": f"queue_sources={sorted(sources)} verdicts={verdicts}",
        "market_fit": "see temperament",
        "prior_lessons": "restricting" if restrict else "none_blocking",
        "entry_trigger": "Price in zone + governed RE_ENTER + non-stale confirmation",
        "invalidation": "Extension >25% above exit, restricting lesson, or stale FS used as truth",
        "suggested_advisory_size": "policy default; cash/risk first",
        "what_would_change": change,
        "authority": AUTHORITY,
        "financial_action": False,
    }
    return rec


def apply_governed_verdicts(queue: dict[str, Any], verdicts: list[dict[str, Any]]) -> dict[str, Any]:
    q = dict(queue or {})
    items = [dict(it) for it in (q.get("items") or q.get("top") or [])]
    by_v = {str(v.get("symbol") or "").upper(): v for v in verdicts if v.get("governed_verdict")}
    seen: set[str] = set()
    for it in items:
        sym = str(it.get("symbol") or "").upper()
        if sym in by_v:
            it["verdict"] = by_v[sym]["governed_verdict"]
            it["governed"] = True
            it["adjudication_status"] = by_v[sym].get("status")
            seen.add(sym)
    for sym, v in by_v.items():
        if sym in seen:
            continue
        items.append({
            "opportunity_key": f"cio-gov-{sym}",
            "source": "cio",
            "symbol": sym,
            "directive_label": f"CIO adjudicated {v['governed_verdict']}",
            "verdict": v["governed_verdict"],
            "state": None,
            "governed": True,
        })
    q["items"] = items
    q["top"] = items[:12]
    q["count"] = len(items)
    return q


# ── Books ───────────────────────────────────────────────────────────────────


def build_temperament(
    *,
    regime: dict[str, Any],
    holdings: dict[str, Any],
    fs_rows: list[dict[str, Any]],
    lessons: dict[str, Any],
    infl: dict[str, Any],
) -> dict[str, Any]:
    label = str(regime.get("label") or "UNKNOWN").replace("_", " ")
    cash = holdings.get("cash") or holdings.get("cash_value") or holdings.get("total_cash")
    try:
        cash_f = float(cash) if cash is not None else None
    except (TypeError, ValueError):
        cash_f = None
    fs_n = len(fs_rows)
    ratified = (lessons.get("counts") or {}).get("RATIFIED_CONTEXT") or 0
    if label.upper() in {"UNKNOWN", ""}:
        title = "CAUTIOUS / SELECTIVE — REGIME UNCONFIRMED"
    else:
        title = f"{label.upper()} — SELECTIVE RISK"
    implication = (
        "Preserve quality growth exposure, keep cash for dislocations, "
        "and do not force lower-quality replacements. Re-entries need "
        "candidate-specific governed verdicts — desk zone marks are not authorization."
    )
    return {
        "title": title,
        "regime": label,
        "regime_as_of": regime.get("as_of"),
        "cash": cash_f,
        "financial_senses_receipts": fs_n,
        "ratified_lessons": ratified,
        "influence": {
            "lesson_mode": infl["gates"]["lesson_mode"],
            "fs_mode": infl["gates"]["financial_senses_mode"],
            "memory_mode": infl["memory_mode"],
            "memory_behavior_influence": infl["memory_behavior_influence"],
        },
        "narrative": (
            f"Temperament {title}. Regime source as-of {regime.get('as_of') or 'n/a'}. "
            f"FS receipts in store: {fs_n}. Ratified lessons available: {ratified}."
        ),
        "portfolio_implication": implication,
        "authority": AUTHORITY,
    }


def build_reentry_book(
    prev: list[dict[str, Any]],
    queue: dict[str, Any],
    lessons: dict[str, Any],
    fs_rows: list[dict[str, Any]],
    infl: dict[str, Any],
) -> dict[str, Any]:
    by_q = _queue_by_symbol(queue)
    fs_ok = _fs_ok(fs_rows)
    rows = []
    for row in prev:
        rec = adjudicate_reentry(
            row, qitems=by_q.get(str(row.get("symbol") or "").upper(), []),
            lessons=lessons, fs_ok=fs_ok, infl=infl,
        )
        rows.append(rec)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {
        "count": len(rows),
        "counts": counts,
        "names": rows,
        "note": "IN_ZONE / READY / NEAR is not RE_ENTER. Governed verdicts are candidate-specific.",
        "authority": AUTHORITY,
    }


def build_opportunity_book(queue: dict[str, Any], reentry: dict[str, Any]) -> dict[str, Any]:
    re_syms = {r["symbol"]: r["status"] for r in reentry.get("names") or []}
    ranked = []
    for i, it in enumerate((queue.get("items") or queue.get("top") or [])[:20], 1):
        if not isinstance(it, dict):
            continue
        sym = str(it.get("symbol") or "").upper()
        vs_re = re_syms.get(sym)
        ranked.append({
            "rank": i,
            "symbol": sym,
            "source": it.get("source"),
            "verdict": it.get("verdict"),
            "state": it.get("state"),
            "label": it.get("directive_label"),
            "vs_former_holdings": vs_re or "not_former",
            "why_outranks_cash_or_reentry": (
                f"Desk {it.get('source')} {it.get('verdict') or it.get('state') or 'watch'}; "
                f"former-holding status {vs_re or 'n/a'}."
            ),
        })
    return {
        "count": len(ranked),
        "top": ranked,
        "note": "New capital uses are ranked against cash and former holdings, not in isolation.",
        "authority": AUTHORITY,
    }


def build_action_book(reentry: dict[str, Any], opportunities: dict[str, Any], temperament: dict[str, Any]) -> dict[str, Any]:
    do_now, watch, re_if, new_if, cash_for, avoid, research = [], [], [], [], [], [], []
    for r in reentry.get("names") or []:
        if r["status"] == "REENTER":
            do_now.append({"symbol": r["symbol"], "action": "RE_ENTER", "why": r["what_would_change"]})
        elif r["status"] == "NEAR":
            watch.append({"symbol": r["symbol"], "action": "WATCH", "why": r["setup"]})
            re_if.append({"symbol": r["symbol"], "action": "RE_ENTER_IF", "why": r["what_would_change"]})
        elif r["status"] == "AVOID":
            avoid.append({"symbol": r["symbol"], "action": "AVOID", "why": r["what_happened_since"]})
        else:
            re_if.append({"symbol": r["symbol"], "action": "RE_ENTER_IF", "why": r["what_would_change"]})
    for o in opportunities.get("top") or []:
        if o.get("verdict") == "ADD" and o.get("symbol") not in {x["symbol"] for x in do_now}:
            new_if.append({"symbol": o["symbol"], "action": "ADD_IF", "why": o["why_outranks_cash_or_reentry"]})
        if not o.get("verdict"):
            research.append({"symbol": o["symbol"], "action": "RESEARCH", "why": o.get("label")})
    cash_for.append({
        "symbol": "CASH",
        "action": "HOLD_CASH_FOR",
        "why": temperament.get("portfolio_implication"),
    })
    return {
        "DO_NOW": do_now,
        "WATCH_CLOSELY": watch,
        "RE_ENTER_IF": re_if,
        "NEW_POSITION_IF": new_if[:8],
        "HOLD_CASH_FOR": cash_for,
        "AVOID": avoid,
        "RESEARCH_NEXT": research[:8],
        "authority": AUTHORITY,
        "financial_action": False,
    }


def build_product(
    *,
    root: Path | str | None = None,
    env: Optional[dict[str, str]] = None,
    now: Optional[datetime] = None,
    queue: Optional[dict[str, Any]] = None,
    previously_traded: Optional[list[dict[str, Any]]] = None,
    holdings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    infl = _influence_active(env)
    queue = queue if queue is not None else collect_queue(root)
    prev = previously_traded if previously_traded is not None else collect_previously_traded()
    holdings = holdings if holdings is not None else collect_holdings(root)
    lessons = collect_lessons(root)
    fs_rows = collect_fs(root)
    mem = collect_memory(root)
    regime = collect_regime()
    temperament = build_temperament(regime=regime, holdings=holdings, fs_rows=fs_rows, lessons=lessons, infl=infl)
    reentry = build_reentry_book(prev, queue, lessons, fs_rows, infl)
    opportunities = build_opportunity_book(queue, reentry)
    actions = build_action_book(reentry, opportunities, temperament)
    verdicts = [r for r in reentry.get("names") or [] if r.get("governed_verdict")]
    merged = apply_governed_verdicts(queue, verdicts)
    recs = _recommendations(actions, temperament)
    product = {
        "schema": SCHEMA,
        "as_of": _iso(now),
        "authority": AUTHORITY,
        "financial_action": False,
        "memory_behavior_influence": infl["memory_behavior_influence"],
        "temperament": temperament,
        "reentry_book": reentry,
        "opportunity_book": opportunities,
        "action_book": actions,
        "governed_verdicts": verdicts,
        "merged_queue": merged,
        "memory": {"provider": (mem.get("health") or {}).get("provider"), "counts": mem.get("counts")},
        "recommendations": recs,
        "summary": _summary(temperament, reentry, actions),
        "decision_id": "cio_books_" + _iso(now).replace(":", "").replace("-", "")[:15],
        "final_position": "HOLD",
        "requires_operator_review": True,
        "confidence": 0.55 if verdicts or (queue.get("count") or 0) else 0.35,
    }
    return product


def _recommendations(actions: dict[str, Any], temperament: dict[str, Any]) -> list[dict[str, Any]]:
    recs = [{
        "action": "NO_ACTION",
        "action_type": "ADVISORY",
        "title": f"Market temperament — {temperament.get('title')}",
        "description": temperament.get("portfolio_implication"),
        "domain": "CIO",
        "priority": "NORMAL",
        "recommended_action": "HOLD_POSTURE",
        "rationale": temperament.get("narrative"),
        "evidence_refs": ["temperament"],
    }]
    for bucket, key in (
        ("DO_NOW", "do_now"),
        ("WATCH_CLOSELY", "watch"),
        ("RE_ENTER_IF", "reenter_if"),
        ("AVOID", "avoid"),
    ):
        for row in (actions.get(bucket) or [])[:8]:
            recs.append({
                "action": "NO_ACTION",
                "action_type": "ADVISORY",
                "title": f"{row.get('action')} {row.get('symbol')}",
                "description": row.get("why"),
                "domain": "CIO",
                "priority": "HIGH" if bucket == "DO_NOW" else "NORMAL",
                "recommended_action": row.get("action"),
                "rationale": row.get("why"),
                "evidence_refs": [f"book:{key}:{row.get('symbol')}"],
                "symbol": row.get("symbol"),
            })
    return recs


def _summary(temperament: dict[str, Any], reentry: dict[str, Any], actions: dict[str, Any]) -> str:
    counts = reentry.get("counts") or {}
    do_n = len(actions.get("DO_NOW") or [])
    return (
        f"{temperament.get('title')}. "
        f"Re-entry book: {reentry.get('count') or 0} former names "
        f"(REENTER={counts.get('REENTER', 0)} NEAR={counts.get('NEAR', 0)} "
        f"WAIT={counts.get('WAIT', 0)} AVOID={counts.get('AVOID', 0)}). "
        f"DO NOW {do_n}. "
        "No material financial Telegram unless a candidate-specific governed act-now exists. "
        "Advisory only."
    )


def persist_product(product: dict[str, Any], *, root: Path | str | None = None) -> dict[str, Any]:
    from scripts.lib.autonomy_watchdog.io import append_jsonl, atomic_write_json
    p = paths(root)
    slim = {k: product[k] for k in product if k != "merged_queue"}
    atomic_write_json(p["brief"], slim)
    append_jsonl(p["briefs"], {
        "as_of": product.get("as_of"),
        "summary": product.get("summary"),
        "verdict_count": len(product.get("governed_verdicts") or []),
        "reentry_count": (product.get("reentry_book") or {}).get("count"),
    })
    atomic_write_json(p["verdicts"], {
        "as_of": product.get("as_of"),
        "verdicts": product.get("governed_verdicts") or [],
        "authority": AUTHORITY,
    })
    append_jsonl(p["verdicts_log"], {
        "as_of": product.get("as_of"),
        "verdicts": [
            {"symbol": v.get("symbol"), "verdict": v.get("governed_verdict"), "status": v.get("status")}
            for v in (product.get("governed_verdicts") or [])
        ],
    })
    return product


def load_brief(root: Path | str | None = None) -> dict[str, Any]:
    return _read_json(paths(root)["brief"])


def load_verdicts(root: Path | str | None = None) -> list[dict[str, Any]]:
    return list((_read_json(paths(root)["verdicts"]).get("verdicts") or []))


def merge_queue_with_stored_verdicts(queue: dict[str, Any], *, root: Path | str | None = None) -> dict[str, Any]:
    return apply_governed_verdicts(queue, load_verdicts(root))


def build_investment_product_synthesis_fn(
    *,
    root: Path | str | None = None,
    env: Optional[dict[str, str]] = None,
) -> Callable[..., dict[str, Any]]:
    def fn(run: dict[str, Any], snapshot: dict[str, Any], specialist_result: dict[str, Any], hermes_result: dict[str, Any]) -> dict[str, Any]:
        product = persist_product(build_product(root=root, env=env))
        product["run_id"] = (run or {}).get("run_id")
        product["snapshot_ref"] = (snapshot or {}).get("snapshot_id")
        product["specialist_count"] = len((specialist_result or {}).get("artifacts") or [])
        product["hermes_present"] = bool(hermes_result)
        product["opportunity_queue"] = {
            "top": ((run or {}).get("context") or {}).get("top") or (product.get("opportunity_book") or {}).get("top"),
            "opportunity_count": ((run or {}).get("context") or {}).get("opportunity_count"),
        }
        return product
    return fn
