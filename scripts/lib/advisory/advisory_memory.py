"""Advisory Desk L4 memory — verdict history, operator feedback, outcomes.

Phase 3. All memory enters prompts as **evidence**, never as instruction.
Deterministic only for thrash / outcomes — no model self-assessment.

Storage (append-only JSONL under data/runtime/):
  - advisory_rows.jsonl      prior verdicts per run
  - advisory_feedback.jsonl  operator rate/ack/snooze
  - advisory_outcomes.jsonl  scored horizons (30/60/90d)
"""
from __future__ import annotations

import fcntl
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUNTIME = PROJECT_ROOT / "data" / "runtime"
ROWS_PATH = RUNTIME / "advisory_rows.jsonl"
FEEDBACK_PATH = RUNTIME / "advisory_feedback.jsonl"
OUTCOMES_PATH = RUNTIME / "advisory_outcomes.jsonl"
CALIBRATION_PATH = RUNTIME / "advisory_calibration.json"
PRICE_CACHE = PROJECT_ROOT / "data" / "portfolios" / "state" / "price_ohlc_cache.json"

# Fixed reason codes (design §5.2) — feedback without a code teaches nothing
REASON_CODES = frozenset({
    "WRONG_FACT",
    "STALE",
    "MISSING_CONTEXT",
    "TOO_SMALL",
    "DISAGREE_THESIS",
    "ALREADY_KNEW",
    "WRONG_TIMING",
    "USEFUL",  # positive path
})

# Thrash: 3+ flips in 90d → conviction penalty
THRASH_WINDOW_DAYS = 90
THRASH_FLIP_THRESHOLD = 3
THRASH_PENALTY_PER_FLIP = 5   # conviction points (0-100 scale)
THRASH_PENALTY_MAX = 25

OUTCOME_HORIZONS = (30, 60, 90)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return t
    except Exception:
        return None


def _append_jsonl(path: Path, entry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, default=str, ensure_ascii=False) + "\n"
    with open(path, "a", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(line)
        f.flush()
        fcntl.flock(f, fcntl.LOCK_UN)


def _read_jsonl(path: Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if limit is not None and limit > 0:
        return out[-limit:]
    return out


def row_key(symbol: str, account: str = "") -> str:
    return f"{(symbol or '').strip().upper()}:{(account or '').strip()}"


def make_row_id(symbol: str, account: str, advisory_row_hash: str, as_of: str = "") -> str:
    day = (as_of or _now_iso())[:10]
    h = (advisory_row_hash or "nohash")[:12]
    return f"{row_key(symbol, account)}|{day}|{h}"


# ── 3A Verdict history ───────────────────────────────────────────────────────

def append_run_history(
    rows: list[dict[str, Any]],
    *,
    opinions: dict[str, dict[str, Any]] | None = None,
    run_id: str | None = None,
    source: str = "advisory_desk",
) -> int:
    """Append one JSONL line per desk row for this run. Returns count written."""
    opinions = opinions or {}
    run_id = run_id or _now_iso()
    n = 0
    for row in rows:
        sym = str(row.get("symbol") or "").strip().upper()
        if not sym:
            continue
        acct = str(row.get("account") or "")
        rh = str(row.get("advisory_row_hash") or "")
        det_v = row.get("verdict")
        if hasattr(det_v, "value"):
            det_v = det_v.value
        det_v = str(det_v or "")
        conf = row.get("confidence")
        opinion = opinions.get(rh) or {}
        model_v = opinion.get("verdict") or det_v
        conviction = opinion.get("conviction")
        if conviction is None and conf is not None:
            try:
                conviction = int(float(conf) * 100)
            except (TypeError, ValueError):
                conviction = None
        entry = {
            "ts": _now_iso(),
            "run_id": run_id,
            "row_id": make_row_id(sym, acct, rh, _now_iso()),
            "symbol": sym,
            "account": acct,
            "row_key": row_key(sym, acct),
            "row_class": row.get("row_class"),
            "advisory_row_hash": rh,
            "deterministic_verdict": det_v,
            "verdict": model_v,
            "conviction": conviction,
            "confidence": conf,
            "key_risk": opinion.get("key_risk") or "",
            "what_changed": opinion.get("what_changed") or "",
            "rationale": (opinion.get("rationale") or row.get("rationale") or "")[:400],
            "market_value": row.get("market_value"),
            "weight_pct": row.get("weight_pct"),
            "gain_loss_pct": row.get("gain_loss_pct"),
            "source": source,
        }
        _append_jsonl(ROWS_PATH, entry)
        n += 1
    return n


def _history_for_key(rk: str, *, since: datetime | None = None) -> list[dict[str, Any]]:
    entries = []
    for e in _read_jsonl(ROWS_PATH):
        if e.get("row_key") != rk and not (
            not e.get("row_key") and row_key(e.get("symbol", ""), e.get("account", "")) == rk
        ):
            # also match symbol-only if account empty on either side
            if str(e.get("symbol") or "").upper() != rk.split(":")[0]:
                continue
            if e.get("account") and rk.split(":")[1] and e.get("account") != rk.split(":")[1]:
                continue
        ts = _parse_ts(e.get("ts"))
        if since and ts and ts < since:
            continue
        entries.append(e)
    entries.sort(key=lambda x: x.get("ts") or "")
    return entries


def count_verdict_changes(history: list[dict[str, Any]]) -> int:
    """Count verdict flips along chronological history."""
    flips = 0
    prev = None
    for e in history:
        v = str(e.get("verdict") or e.get("deterministic_verdict") or "")
        if not v:
            continue
        if prev is not None and v != prev:
            flips += 1
        prev = v
    return flips


def thrash_penalty_points(flips_90d: int) -> int:
    """Conviction points to subtract (0–THRASH_PENALTY_MAX)."""
    if flips_90d < THRASH_FLIP_THRESHOLD:
        return 0
    extra = flips_90d - THRASH_FLIP_THRESHOLD + 1
    return min(THRASH_PENALTY_MAX, extra * THRASH_PENALTY_PER_FLIP)


def apply_thrash_penalty(conviction: int | float | None, flips_90d: int) -> tuple[int, int]:
    """Return (adjusted_conviction, penalty_applied)."""
    if conviction is None:
        conviction = 50
    try:
        c = int(conviction)
    except (TypeError, ValueError):
        c = 50
    pen = thrash_penalty_points(flips_90d)
    return max(0, min(100, c - pen)), pen


def load_prior_for_row(symbol: str, account: str = "") -> dict[str, Any]:
    """Prior verdict block for prompt injection (L4-A)."""
    rk = row_key(symbol, account)
    since = _now() - timedelta(days=THRASH_WINDOW_DAYS)
    hist = _history_for_key(rk, since=since)
    # Prefer exact row_key match when present
    exact = [e for e in hist if e.get("row_key") == rk]
    if exact:
        hist = exact
    flips = count_verdict_changes(hist)
    prior = hist[-1] if hist else None
    prior_prior = hist[-2] if len(hist) >= 2 else None
    prior_risk = (prior or {}).get("key_risk") or ""
    risk_materialized = None
    # Heuristic: if prior key_risk mentioned and verdict flipped, flag
    if prior_prior and prior and prior.get("verdict") != prior_prior.get("verdict"):
        risk_materialized = True

    return {
        "row_key": rk,
        "prior_verdict": (prior or {}).get("verdict"),
        "prior_conviction": (prior or {}).get("conviction"),
        "prior_date": ((prior or {}).get("ts") or "")[:10] or None,
        "prior_key_risk": prior_risk[:200] if prior_risk else "",
        "prior_risk_materialized": risk_materialized,
        "verdict_changes_90d": flips,
        "thrash_penalty": thrash_penalty_points(flips),
        "history_n": len(hist),
        "has_prior": prior is not None,
    }


# ── 3B Operator feedback ─────────────────────────────────────────────────────

def record_feedback(
    *,
    row_id: str = "",
    symbol: str = "",
    account: str = "",
    rating: str,
    reason_code: str = "",
    note: str = "",
    pattern: str = "",
) -> dict[str, Any]:
    """Store operator feedback. rating: useful|notuseful|ack|snooze."""
    rating = (rating or "").strip().lower()
    if rating not in ("useful", "notuseful", "ack", "snooze"):
        raise ValueError("rating must be useful|notuseful|ack|snooze")
    code = (reason_code or "").strip().upper()
    if rating == "notuseful" and code and code not in REASON_CODES:
        raise ValueError(f"reason_code must be one of {sorted(REASON_CODES)}")
    if rating == "useful":
        code = code or "USEFUL"
    if rating == "notuseful" and not code:
        raise ValueError("notuseful requires a reason_code")

    # Parse row_id if provided: SYMBOL:acct|date|hash
    if row_id and not symbol:
        parts = row_id.split("|")
        head = parts[0]
        if ":" in head:
            symbol, account = head.split(":", 1)
        else:
            symbol = head

    entry = {
        "ts": _now_iso(),
        "row_id": row_id,
        "symbol": (symbol or "").strip().upper(),
        "account": account or "",
        "row_key": row_key(symbol, account),
        "rating": rating,
        "reason_code": code,
        "note": (note or "")[:500],
        "pattern": pattern or "",
    }
    _append_jsonl(FEEDBACK_PATH, entry)
    return entry


def load_feedback_for_symbol(symbol: str, account: str = "", *, limit: int = 20) -> list[dict[str, Any]]:
    sym = (symbol or "").strip().upper()
    rk = row_key(sym, account)
    items = [
        e for e in _read_jsonl(FEEDBACK_PATH)
        if e.get("row_key") == rk
        or (e.get("symbol") == sym and (not account or e.get("account") == account))
    ]
    return items[-limit:]


def latest_disagree_thesis(symbol: str, account: str = "") -> dict[str, Any] | None:
    for e in reversed(load_feedback_for_symbol(symbol, account, limit=50)):
        if e.get("reason_code") == "DISAGREE_THESIS":
            return e
    return None


# ── Memory block for prompts ─────────────────────────────────────────────────

def format_memory_block(
    *,
    prior: dict[str, Any] | None = None,
    feedback: list[dict[str, Any]] | None = None,
    calibration: dict[str, Any] | None = None,
    lessons: list[dict[str, Any]] | None = None,
) -> str:
    """Human-readable memory section — context only, not instruction."""
    lines: list[str] = []
    prior = prior or {}
    if prior.get("has_prior"):
        lines.append(
            f"Prior: {prior.get('prior_verdict')} @{prior.get('prior_conviction')} "
            f"on {prior.get('prior_date')}. Changes in 90d: {prior.get('verdict_changes_90d', 0)}."
        )
        if prior.get("prior_key_risk"):
            lines.append(f"Prior key_risk: {prior['prior_key_risk']}")
        if prior.get("thrash_penalty"):
            lines.append(
                f"Thrash penalty: −{prior['thrash_penalty']} conviction "
                f"({prior.get('verdict_changes_90d')} flips in 90d)."
            )
        if prior.get("prior_risk_materialized"):
            lines.append("Prior risk note: verdict changed since last review (possible risk materialization).")
    else:
        lines.append("Prior: none (first observation or no history).")

    disagree = None
    for e in reversed(feedback or []):
        if e.get("reason_code") == "DISAGREE_THESIS":
            disagree = e
            break
        if e.get("rating") == "notuseful" and e.get("reason_code"):
            if disagree is None:
                disagree = e
    if disagree:
        lines.append(
            f"Operator: rated {disagree.get('rating')}/{disagree.get('reason_code')} "
            f"on {(disagree.get('ts') or '')[:10]}"
            + (f" — {disagree.get('note')}" if disagree.get("note") else "")
            + (" — held the position." if disagree.get("reason_code") == "DISAGREE_THESIS" else "")
        )

    if calibration:
        v = calibration.get("verdict") or "TRIM"
        hit = calibration.get("hit_rate")
        n = calibration.get("n") or 0
        if hit is not None and n:
            lines.append(
                f"Desk calibration: {v} verdicts {hit:.0%} correct over {n} scored "
                f"({'n is small' if n < 20 else 'ok'})."
            )

    if lessons:
        bits = []
        for L in lessons[:5]:
            bits.append(
                f"{L.get('title') or L.get('id')} (hit {L.get('hit_rate', '?')})"
            )
        if bits:
            lines.append("Lessons: [" + "; ".join(bits) + "]")

    lines.append(
        "Standing rule: memory informs, never overrides current evidence. "
        "State conflicts between memory and evidence explicitly."
    )
    return "\n".join(lines)


def build_memory_for_row(row: dict[str, Any], *, calibration: dict[str, Any] | None = None) -> dict[str, Any]:
    """Full memory payload for one desk row (injection + thrash + lessons)."""
    sym = str(row.get("symbol") or "")
    acct = str(row.get("account") or "")
    prior = load_prior_for_row(sym, acct)
    fb = load_feedback_for_symbol(sym, acct, limit=10)
    # Sector/verdict calibration slice if provided globally
    cal = None
    v = row.get("verdict")
    if hasattr(v, "value"):
        v = v.value
    v_str = str(v or "")
    if calibration:
        cal = (calibration.get("by_verdict") or {}).get(v_str) or calibration.get("global")
        if cal:
            cal = {**cal, "verdict": v_str}

    lessons_fmt: list[dict[str, Any]] = []
    lesson_ids: list[str] = []
    try:
        from lib.advisory.kb_lessons import (
            format_lessons_for_prompt,
            retrieve_lessons_for_row,
        )
        sector = ""
        inst = row.get("instrument") or {}
        if isinstance(inst, dict):
            sector = str(inst.get("sector") or "")
        q = f"{sym} {v_str} {row.get('rationale') or ''}"
        lessons = retrieve_lessons_for_row(
            symbol=sym, sector=sector, verdict=v_str, query_text=q, limit=5,
        )
        lessons_fmt = format_lessons_for_prompt(lessons)
        lesson_ids = [str(l.get("id")) for l in lessons if l.get("id")]
    except Exception:
        pass

    block = format_memory_block(
        prior=prior, feedback=fb, calibration=cal, lessons=lessons_fmt,
    )
    cognition_refs: dict[str, Any] = {
        "security_guid": None,
        "research_state_version": None,
        "curation_version": None,
        "producer": False,
        "authority": "READ_ONLY_ADVISORY",
    }
    try:
        from scripts.lib.cio_persistent_cognition import advisory_fields, cognition_for_symbol

        if sym:
            cognition_refs = advisory_fields(cognition_for_symbol(PROJECT_ROOT, sym))
    except Exception:
        pass
    return {
        "prior": prior,
        "feedback": fb,
        "lessons": lessons_fmt,
        "lesson_ids": lesson_ids,
        "memory_block": block,
        "thrash_penalty": prior.get("thrash_penalty") or 0,
        "disagree_thesis": latest_disagree_thesis(sym, acct),
        "security_guid": cognition_refs.get("security_guid"),
        "research_state_version": cognition_refs.get("research_state_version"),
        "curation_version": cognition_refs.get("curation_version"),
    }


# ── 3C Outcome scoring (deterministic) ───────────────────────────────────────

def _load_price_series(symbol: str) -> dict[str, float]:
    """Return {YYYY-MM-DD: close} from price_ohlc_cache if present."""
    if not PRICE_CACHE.exists():
        return {}
    try:
        raw = json.loads(PRICE_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if raw.get("state"):
        return {}
    data = raw.get(symbol) or raw.get(symbol.upper()) or {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, float] = {}
    for d, bar in data.items():
        if not isinstance(bar, dict):
            continue
        c = bar.get("c") if "c" in bar else bar.get("close")
        if c is not None:
            try:
                out[str(d)[:10]] = float(c)
            except (TypeError, ValueError):
                pass
    return out


def _price_on_or_after(series: dict[str, float], day: str) -> float | None:
    if day in series:
        return series[day]
    keys = sorted(k for k in series if k >= day)
    return series[keys[0]] if keys else None


def _price_on_or_before(series: dict[str, float], day: str) -> float | None:
    if day in series:
        return series[day]
    keys = sorted(k for k in series if k <= day)
    return series[keys[-1]] if keys else None


def score_verdict_outcome(
    verdict: str,
    ret_pct: float,
) -> dict[str, Any]:
    """Deterministic outcome label for a verdict vs realized return.

    TRIM/EXIT: helpful if return negative (avoided further loss) or < -2%
    ADD/RE_ENTER: helpful if return positive
    HOLD: helpful if |return| < 10% (no disaster); harmful if return < -15%
    """
    v = (verdict or "").upper()
    if v in ("TRIM", "EXIT"):
        correct = ret_pct <= -1.0
        # Partial credit if flat/down slightly vs large rally against
        if ret_pct > 10:
            correct = False
        return {"correct": correct, "label": "avoided_drawdown" if correct else "missed_or_wrong"}
    if v in ("ADD", "RE_ENTER"):
        correct = ret_pct >= 1.0
        return {"correct": correct, "label": "captured_upside" if correct else "missed_upside"}
    if v == "HOLD":
        correct = ret_pct > -15.0
        return {"correct": correct, "label": "held_ok" if correct else "held_drawdown"}
    if v in ("AVOID", "WAIT", "INSUFFICIENT_DATA"):
        return {"correct": None, "label": "unscored"}
    return {"correct": None, "label": "unscored"}


def score_pending_outcomes(
    *,
    horizons: tuple[int, ...] = OUTCOME_HORIZONS,
    max_new: int = 200,
) -> dict[str, Any]:
    """Score history rows that have reached a horizon and lack an outcome record."""
    history = _read_jsonl(ROWS_PATH)
    existing = {
        (e.get("source_row_id"), e.get("horizon_d"))
        for e in _read_jsonl(OUTCOMES_PATH)
    }
    written = 0
    scored_ok = 0
    today = _now().date()

    for e in reversed(history):
        if written >= max_new:
            break
        ts = _parse_ts(e.get("ts"))
        if not ts:
            continue
        sym = str(e.get("symbol") or "").upper()
        verdict = str(e.get("verdict") or e.get("deterministic_verdict") or "")
        row_id = e.get("row_id") or ""
        series = _load_price_series(sym)
        if not series:
            continue
        day0 = ts.date().isoformat()
        p0 = _price_on_or_after(series, day0) or _price_on_or_before(series, day0)
        if not p0 or p0 <= 0:
            continue
        for h in horizons:
            key = (row_id, h)
            if key in existing:
                continue
            target = (ts + timedelta(days=h)).date()
            if target > today:
                continue
            p1 = _price_on_or_after(series, target.isoformat()) or _price_on_or_before(
                series, target.isoformat()
            )
            if not p1:
                continue
            ret_pct = (p1 / p0 - 1.0) * 100.0
            sc = score_verdict_outcome(verdict, ret_pct)
            entry = {
                "ts": _now_iso(),
                "source_row_id": row_id,
                "symbol": sym,
                "account": e.get("account"),
                "verdict": verdict,
                "conviction": e.get("conviction"),
                "horizon_d": h,
                "price_t0": p0,
                "price_t1": p1,
                "return_pct": round(ret_pct, 3),
                "correct": sc["correct"],
                "label": sc["label"],
                "scored_at": _now_iso(),
            }
            _append_jsonl(OUTCOMES_PATH, entry)
            existing.add(key)
            written += 1
            if sc["correct"] is True:
                scored_ok += 1

    cal = rebuild_calibration()
    return {
        "ok": True,
        "written": written,
        "calibration": cal,
    }


def rebuild_calibration() -> dict[str, Any]:
    """Aggregate hit rates by verdict (and optional conviction band)."""
    outcomes = _read_jsonl(OUTCOMES_PATH)
    by_v: dict[str, list[bool]] = defaultdict(list)
    for e in outcomes:
        c = e.get("correct")
        if c is None:
            continue
        by_v[str(e.get("verdict") or "?")].append(bool(c))

    by_verdict: dict[str, Any] = {}
    all_hits: list[bool] = []
    for v, hits in by_v.items():
        n = len(hits)
        rate = sum(1 for x in hits if x) / n if n else None
        by_verdict[v] = {"n": n, "hit_rate": rate}
        all_hits.extend(hits)

    n_all = len(all_hits)
    cal = {
        "rebuilt_at": _now_iso(),
        "n_scored": n_all,
        "global": {
            "n": n_all,
            "hit_rate": (sum(1 for x in all_hits if x) / n_all) if n_all else None,
        },
        "by_verdict": by_verdict,
    }
    try:
        CALIBRATION_PATH.parent.mkdir(parents=True, exist_ok=True)
        CALIBRATION_PATH.write_text(json.dumps(cal, indent=2), encoding="utf-8")
    except Exception:
        pass
    return cal


def load_calibration() -> dict[str, Any]:
    if CALIBRATION_PATH.exists():
        try:
            return json.loads(CALIBRATION_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return rebuild_calibration()
