#!/usr/bin/env python3
"""drain_cio_stance_classification.py — give a held symbol what the CIO engine needs.

OPERATOR DECISION 2026-09-23: a GO/BUY with no CIO stance on file stays HELD and
forces a CIO review; follow-up approved the same day: "add the classification
queue follow-up".

Why this exists (measured 2026-09-23): ``cio_decision_engine`` INNER JOINs an
ACTIVE ``ticker_strategy_classifications`` row with a ``strategy_rule_evaluations``
row. The names held for a missing stance (STLD, AES, HOOD, SLB, WDAY, ALLE, ...)
have only INACTIVE classifications (``watchlist_hygiene`` deactivates on removal)
and no rule evaluation, and ``strategy_rule_engine.py`` has been unscheduled since
2026-09-06. So no amount of research gave them a stance.

For each ``classification_requested`` row in the review ledger
(``cio_stance_review_requests.jsonl``) this drain:

1. classifies the symbol with ``multi_strategy_classifier`` Phase 1 only
   (deterministic, no LLM, no spend) — a fresh, evidence-based strategy_type
   instead of re-activating a stale screener label;
2. records the decision in the existing ``agent_classification_suggestions``
   queue (agent ``cio_stance_review``) and upserts an ACTIVE classification plus
   a ``ticker_classification_history`` row, in one transaction;
3. runs ``strategy_rule_engine.evaluate_strategy_rules`` for that symbol, which
   writes its ``strategy_rule_evaluations`` row.

The next ``cio_decision_engine`` run then writes a real ``cio_decisions`` row.
This script does not run the engine (its lane is PAUSED in lane_registry; the
self-heal path runs it). No broker, sizing or order logic is touched.

Default is a dry run: nothing is written, and the rule evaluation is computed in
memory against the proposed classification so the output shows the exact row
the engine would read. ``--apply`` writes.

Usage:
    python3 scripts/drain_cio_stance_classification.py            # dry run
    python3 scripts/drain_cio_stance_classification.py --apply
    python3 scripts/drain_cio_stance_classification.py --symbol STLD
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

SCHEMA = "CIOStanceClassificationDrain@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
AGENT = "cio_stance_review"
SOURCE = "cio_stance_review"

DEFAULT_LOOKBACK_DAYS = 7
#: Phase-1 deterministic matches score 0.70; anything below this is not trusted.
DEFAULT_MIN_CONFIDENCE = 0.6
DEFAULT_MAX_PER_RUN = 50

TERMINAL = frozenset({"applied", "already_classified", "no_deterministic_match", "invalid_strategy_type"})


def _env_float(name: str, default: float) -> float:
    try:
        return float(str(os.environ.get(name) or "").strip() or default)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return max(0, int(float(str(os.environ.get(name) or "").strip() or default)))
    except ValueError:
        return default


def receipts_path() -> Optional[Path]:
    raw = str(os.environ.get("CIO_STANCE_CLASSIFY_RECEIPTS") or "").strip()
    if raw.lower() in {"0", "off", "false", "no"}:
        return None
    if raw:
        return Path(raw)
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    return Path.home() / ".local/state/tradeai/cio_stance_classification_receipts.jsonl"


def _read_jsonl(path: Optional[Path]) -> list[dict[str, Any]]:
    if not path or not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def pending_requests(
    ledger_rows: Iterable[dict[str, Any]],
    receipt_rows: Iterable[dict[str, Any]],
    *,
    now: datetime,
    lookback_days: int,
    only: Optional[set[str]] = None,
) -> list[dict[str, Any]]:
    """Newest classification request per symbol that has no terminal receipt yet."""
    cutoff = now - timedelta(days=lookback_days)
    done = {(r.get("symbol"), r.get("request_as_of")) for r in receipt_rows if r.get("status") in TERMINAL}
    newest: dict[str, dict[str, Any]] = {}
    for row in ledger_rows:
        sym = str(row.get("symbol") or "").upper().strip()
        if not sym or not row.get("classification_requested"):
            continue
        if only and sym not in only:
            continue
        try:
            when = datetime.strptime(str(row.get("as_of")), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if when < cutoff:
            continue
        if sym not in newest or str(row.get("as_of")) > str(newest[sym].get("as_of")):
            newest[sym] = row
    return [r for s, r in sorted(newest.items()) if (s, r.get("as_of")) not in done]


# ── Database seams (injectable for tests) ───────────────────────────────────


def _connect():
    from strategy_rule_engine import _get_conn

    return _get_conn()


def load_state(conn, symbol: str) -> dict[str, Any]:
    cur = conn.cursor()
    cur.execute(
        "SELECT strategy_type, active FROM ticker_strategy_classifications WHERE symbol=%s",
        (symbol,),
    )
    tsc = cur.fetchone()
    cur.execute("SELECT 1 FROM strategy_rule_evaluations WHERE symbol=%s", (symbol,))
    sre = cur.fetchone()
    cur.execute(
        "SELECT symbol, price, rvol, float_m, gap_pct, change_pct, score, decision, grade, catalyst,"
        " catalyst_verified, sector, industry, screener_label FROM trade_ai_scans"
        " WHERE symbol=%s ORDER BY scanned_at DESC LIMIT 1",
        (symbol,),
    )
    scan_row = cur.fetchone()
    scan = dict(zip([d[0] for d in cur.description], scan_row)) if scan_row else {"symbol": symbol}
    cur.execute("SELECT strategy_type FROM strategy_registry")
    registry = {r[0] for r in cur.fetchall()}
    return {
        "prior_strategy_type": tsc[0] if tsc else None,
        "active": bool(tsc[1]) if tsc else False,
        "has_rule_evaluation": bool(sre),
        "scan": scan,
        "registry": registry,
    }


def deterministic_matches(scan: dict[str, Any]) -> list[dict[str, Any]]:
    import multi_strategy_classifier as msc

    cache = msc.load_enrichment_cache()
    strategies = msc.load_all_strategies()
    if not cache or not strategies:
        # Without the Finviz enrichment cache (or strategy configs) every symbol
        # "matches nothing". That is a missing input, not a verdict: raise so the
        # request is retried on a later run instead of receipted as terminal.
        raise RuntimeError("classifier_inputs_unavailable")
    return msc.classify_symbol(scan, strategies, use_llm=False, enrichment_cache=cache)


def write_classification(conn, symbol: str, match: dict[str, Any], prior: Optional[str], request: dict) -> None:
    """One transaction: suggestion (existing queue) + active classification + history."""
    st = match["strategy_id"]
    conf = float(match.get("confidence") or 0)
    rationale = "; ".join(match.get("match_reasons") or [])[:500] or "deterministic match"
    evidence = json.dumps(
        {
            "reason": "cio_stance_missing_review",
            "request_as_of": request.get("as_of"),
            "research_id": request.get("research_id"),
            "match_source": match.get("match_source"),
            "prior_strategy_type": prior,
        },
        default=str,
    )
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO agent_classification_suggestions"
        " (symbol, suggested_strategy_type, agent, confidence, rationale, evidence, status, reviewed_at, reviewed_by)"
        " VALUES (%s,%s,%s,%s,%s,%s,'accepted',now(),%s)",
        (symbol, st, AGENT, conf, rationale, evidence, AGENT),
    )
    cur.execute(
        "INSERT INTO ticker_strategy_classifications"
        " (symbol, strategy_type, classification_source, confidence, assigned_by_agent, rationale, evidence, active)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,TRUE)"
        " ON CONFLICT (symbol) DO UPDATE SET strategy_type=EXCLUDED.strategy_type,"
        " classification_source=EXCLUDED.classification_source, confidence=EXCLUDED.confidence,"
        " assigned_by_agent=EXCLUDED.assigned_by_agent, rationale=EXCLUDED.rationale,"
        " evidence=EXCLUDED.evidence, active=TRUE, updated_at=now()",
        (symbol, st, SOURCE, conf, AGENT, rationale, evidence),
    )
    cur.execute(
        "INSERT INTO ticker_classification_history"
        " (symbol, old_strategy_type, new_strategy_type, classification_source, confidence, assigned_by_agent,"
        " rationale, evidence) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (symbol, prior, st, SOURCE, conf, AGENT, rationale, evidence),
    )
    conn.commit()


def evaluate_rules(symbol: str, *, apply: bool, proposed: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Run the rule engine for one symbol. Dry run: in memory against ``proposed``."""
    import strategy_rule_engine as sre

    if apply:
        return sre.evaluate_strategy_rules(symbol)
    orig_classify, orig_persist = sre.classify_symbol, sre._persist_evaluation
    try:
        if proposed is not None:
            sre.classify_symbol = lambda _s: dict(proposed)  # type: ignore[assignment]
        sre._persist_evaluation = lambda *_a, **_k: None  # type: ignore[assignment]
        return sre.evaluate_strategy_rules(symbol)
    finally:
        sre.classify_symbol, sre._persist_evaluation = orig_classify, orig_persist


# ── Drain ───────────────────────────────────────────────────────────────────


def drain_one(
    request: dict[str, Any],
    *,
    apply: bool,
    conn,
    state_fn: Callable[..., dict[str, Any]] = load_state,
    match_fn: Callable[[dict[str, Any]], list[dict[str, Any]]] = deterministic_matches,
    write_fn: Callable[..., None] = write_classification,
    rules_fn: Callable[..., dict[str, Any]] = evaluate_rules,
    min_confidence: Optional[float] = None,
) -> dict[str, Any]:
    sym = str(request["symbol"]).upper()
    floor = DEFAULT_MIN_CONFIDENCE if min_confidence is None else min_confidence
    out: dict[str, Any] = {"symbol": sym, "request_as_of": request.get("as_of"), "applied": apply}
    state = state_fn(conn, sym)
    out["prior_strategy_type"] = state.get("prior_strategy_type")
    out["prior_active"] = state.get("active")
    if state.get("active"):
        out["status"] = "already_classified"
        if not state.get("has_rule_evaluation"):
            res = rules_fn(sym, apply=apply)
            out["rule_evaluation"] = {k: res.get(k) for k in ("strategy_type", "baseline_action")}
        return out
    matches = [m for m in (match_fn(state.get("scan") or {"symbol": sym}) or []) if m.get("strategy_id")]
    best = max(matches, key=lambda m: float(m.get("confidence") or 0), default=None)
    if not best or float(best.get("confidence") or 0) < floor:
        out["status"] = "no_deterministic_match"
        out["candidates"] = [(m.get("strategy_id"), m.get("confidence")) for m in matches]
        return out
    if best["strategy_id"] not in (state.get("registry") or set()):
        out["status"] = "invalid_strategy_type"
        out["strategy_type"] = best["strategy_id"]
        return out
    out["strategy_type"] = best["strategy_id"]
    out["confidence"] = float(best.get("confidence") or 0)
    out["match_reasons"] = best.get("match_reasons")
    proposed = {
        "symbol": sym,
        "strategy_type": best["strategy_id"],
        "confidence": out["confidence"],
        "classification_source": SOURCE,
        "active": True,
    }
    if apply:
        write_fn(conn, sym, best, state.get("prior_strategy_type"), request)
    res = rules_fn(sym, apply=apply, proposed=proposed)
    out["rule_evaluation"] = {
        k: res.get(k) for k in ("strategy_type", "baseline_action", "human_review_required", "escalation_required")
    }
    out["status"] = "applied" if apply else "would_apply"
    return out


def run(
    *,
    apply: bool,
    only: Optional[set[str]] = None,
    now: Optional[datetime] = None,
    ledger_rows: Optional[list[dict[str, Any]]] = None,
    conn=None,
    **seams: Any,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    if ledger_rows is None:
        from scripts.lib.cio_stance_review_request import requests_path

        ledger_rows = _read_jsonl(requests_path())
    rpath = receipts_path()
    todo = pending_requests(
        ledger_rows,
        _read_jsonl(rpath),
        now=now,
        lookback_days=_env_int("CIO_STANCE_CLASSIFY_LOOKBACK_DAYS", DEFAULT_LOOKBACK_DAYS),
        only=only,
    )[: _env_int("CIO_STANCE_CLASSIFY_MAX_PER_RUN", DEFAULT_MAX_PER_RUN)]
    floor = _env_float("CIO_STANCE_CLASSIFY_MIN_CONFIDENCE", DEFAULT_MIN_CONFIDENCE)
    own = conn is None and bool(todo)
    if own:
        conn = _connect()
    results = []
    try:
        for req in todo:
            try:
                res = drain_one(req, apply=apply, conn=conn, min_confidence=floor, **seams)
            except Exception as exc:  # noqa: BLE001 — one bad symbol never stops the drain
                try:
                    conn.rollback()
                except Exception:  # noqa: BLE001
                    pass
                res = {"symbol": req.get("symbol"), "request_as_of": req.get("as_of"), "status": f"error:{exc}"[:200]}
            res.update({"schema": SCHEMA, "authority": AUTHORITY, "as_of": now.isoformat(), "mbi_behavior": 0})
            results.append(res)
            if apply and rpath is not None:
                rpath.parent.mkdir(parents=True, exist_ok=True)
                with rpath.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(res, sort_keys=True, default=str) + "\n")
    finally:
        if own and conn is not None:
            conn.close()
    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"schema": SCHEMA, "apply": apply, "pending": len(todo), "counts": counts, "results": results}


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    ap.add_argument("--symbol", action="append", help="limit to these symbols (repeatable)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    only = {s.upper() for s in args.symbol} if args.symbol else None
    report = run(apply=args.apply, only=only)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"[{'APPLY' if args.apply else 'DRY-RUN'}] pending={report['pending']} counts={report['counts']}")
        for r in report["results"]:
            ev = r.get("rule_evaluation") or {}
            print(
                f"  {r['symbol']:<6} {r['status']:<24} type={r.get('strategy_type') or r.get('prior_strategy_type')}"
                f" baseline={ev.get('baseline_action')}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
