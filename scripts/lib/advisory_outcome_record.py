"""Immutable advisory prediction and outcome ledger.

``OutcomeRecord@v1`` freezes a DecisionPayload prediction before its governed
horizon and later appends a separate evaluated record.  Evaluation is
deterministic and candidate-only: no row can mutate policy or trading authority.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

SCHEMA = "OutcomeRecord@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
FROZEN = "PREDICTION_FROZEN"
EVALUATED = "OUTCOME_EVALUATED"
DEFAULT_HORIZONS = (30, 60, 90)
PRICE_CACHE_REL = Path("data/portfolios/state/price_ohlc_cache.json")
LEDGER_REL = Path("data/cio/advisory_outcomes_v1.jsonl")


def _utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        out = value
    elif value:
        try:
            out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if out.tzinfo is None:
        out = out.replace(tzinfo=timezone.utc)
    return out.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("schema") == SCHEMA:
            out.append(row)
    return out


def _append(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")
        handle.flush()
        fcntl.flock(handle, fcntl.LOCK_UN)


def _quote(value: dict[str, Any] | None, *, name: str) -> dict[str, Any]:
    q = dict(value or {})
    try:
        price = float(q.get("price"))
    except (TypeError, ValueError):
        raise ValueError(f"{name}_price_missing") from None
    if price <= 0:
        raise ValueError(f"{name}_price_invalid")
    as_of = _utc(q.get("as_of"))
    source = str(q.get("source") or "").strip()
    if as_of is None or not source:
        raise ValueError(f"{name}_provenance_incomplete")
    return {
        "symbol": str(q.get("symbol") or "").upper() or None,
        "price": price,
        "as_of": _iso(as_of),
        "source": source,
        "source_record_id": q.get("source_record_id"),
        "low": float(q["low"]) if q.get("low") is not None else None,
    }


def _record_id(decision_id: str, horizon_days: int) -> str:
    return "out_" + _digest([decision_id, int(horizon_days)])[:20]


def freeze_prediction(
    decision: dict[str, Any],
    *,
    horizon_days: int,
    starting_quote: dict[str, Any],
    benchmark_quote: dict[str, Any],
    sector_benchmark_quote: dict[str, Any] | None = None,
    path: Path,
    frozen_at: datetime | None = None,
) -> dict[str, Any]:
    """Append one immutable prediction, or return the existing frozen row."""
    if decision.get("schema") != "DecisionPayload@v1":
        raise ValueError("decision_payload_required")
    decision_id = str(decision.get("decision_id") or "").strip()
    symbol = str(decision.get("symbol") or "").strip().upper()
    if not decision_id or symbol in {"", "DATA_UNAVAILABLE"}:
        raise ValueError("decision_identity_incomplete")
    if int(horizon_days) <= 0:
        raise ValueError("horizon_invalid")
    prediction_at = _utc(decision.get("as_of"))
    frozen_at = frozen_at or datetime.now(timezone.utc)
    if prediction_at is None:
        raise ValueError("prediction_timestamp_missing")
    if frozen_at - prediction_at > timedelta(hours=24):
        raise ValueError("retroactive_freeze_forbidden")

    rid = _record_id(decision_id, horizon_days)
    existing = next((r for r in _rows(path) if r.get("record_id") == rid and r.get("status") == FROZEN), None)
    if existing:
        return {**existing, "deduped": True}

    start = _quote(starting_quote, name="starting")
    benchmark = _quote(benchmark_quote, name="benchmark")
    sector = _quote(sector_benchmark_quote, name="sector_benchmark") if sector_benchmark_quote else None
    frozen = {
        "decision_id": decision_id,
        "symbol": symbol,
        "thesis_version": decision.get("thesis_version"),
        "prediction_timestamp": _iso(prediction_at),
        "advisory_stance": str(decision.get("current_action") or "DATA_UNAVAILABLE").upper(),
        "expected_catalyst": decision.get("expected_catalyst"),
        "expected_invalidation": decision.get("expected_invalidation"),
        "measurement_horizon_days": int(horizon_days),
        "starting_quote": start,
        "benchmark": benchmark,
        "sector_benchmark": sector,
        "decision_inputs_digest": decision.get("inputs_digest"),
    }
    row = {
        "schema": SCHEMA,
        "status": FROZEN,
        "record_id": rid,
        **frozen,
        "prediction_hash": _digest(frozen),
        "frozen_at": _iso(frozen_at),
        "outcome_timestamp": None,
        "data_quality": {"state": "VERIFIED_START", "missing": []},
        "candidate_outputs_only": True,
        "authority": AUTHORITY,
        "financial_action": False,
    }
    _append(path, row)
    return row


def _return(start: float, end: float) -> float:
    return round((end / start - 1.0) * 100.0, 6)


def evaluate_frozen_prediction(
    frozen: dict[str, Any],
    *,
    ending_quote: dict[str, Any],
    benchmark_quote: dict[str, Any],
    sector_benchmark_quote: dict[str, Any] | None = None,
    invalidation_occurred: bool | None = None,
    catalyst_correct: bool | None = None,
    path: Path,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    """Append a deterministic outcome without rewriting its prediction."""
    if frozen.get("schema") != SCHEMA or frozen.get("status") != FROZEN:
        raise ValueError("frozen_outcome_record_required")
    evaluated_at = evaluated_at or datetime.now(timezone.utc)
    prediction_at = _utc(frozen.get("prediction_timestamp"))
    due_at = prediction_at + timedelta(days=int(frozen.get("measurement_horizon_days") or 0)) if prediction_at else None
    if due_at is None or evaluated_at < due_at:
        raise ValueError("outcome_window_not_due")
    rid = str(frozen.get("record_id") or "")
    existing = next((r for r in _rows(path) if r.get("record_id") == rid and r.get("status") == EVALUATED), None)
    if existing:
        return {**existing, "deduped": True}

    end = _quote(ending_quote, name="ending")
    benchmark_end = _quote(benchmark_quote, name="benchmark_ending")
    sector_end = _quote(sector_benchmark_quote, name="sector_benchmark_ending") if sector_benchmark_quote else None
    symbol_return = _return(float(frozen["starting_quote"]["price"]), end["price"])
    benchmark_return = _return(float(frozen["benchmark"]["price"]), benchmark_end["price"])
    sector_return = None
    if frozen.get("sector_benchmark") and sector_end:
        sector_return = _return(float(frozen["sector_benchmark"]["price"]), sector_end["price"])
    drawdown = None
    if end.get("low") is not None:
        drawdown = min(0.0, _return(float(frozen["starting_quote"]["price"]), float(end["low"])))

    stance = str(frozen.get("advisory_stance") or "").upper()
    relative = round(symbol_return - benchmark_return, 6)
    if invalidation_occurred is True:
        thesis_result = "INVALIDATED"
    elif catalyst_correct is True:
        thesis_result = "CATALYST_CONFIRMED"
    elif stance in {"ADD", "BUY", "RE_ENTER", "HOLD"}:
        thesis_result = "SUPPORTED" if relative >= 0 else "NOT_SUPPORTED"
    elif stance in {"TRIM", "EXIT", "AVOID", "WAIT"}:
        thesis_result = "SUPPORTED" if relative <= 0 else "NOT_SUPPORTED"
    else:
        thesis_result = "INCONCLUSIVE"

    row = {
        **{k: v for k, v in frozen.items() if k not in {"status", "outcome_timestamp", "data_quality", "deduped"}},
        "status": EVALUATED,
        "ending_quote": end,
        "benchmark_ending_quote": benchmark_end,
        "sector_benchmark_ending_quote": sector_end,
        "future_return_pct": symbol_return,
        "benchmark_return_pct": benchmark_return,
        "benchmark_relative_return_pct": relative,
        "sector_benchmark_return_pct": sector_return,
        "sector_relative_return_pct": round(symbol_return - sector_return, 6) if sector_return is not None else None,
        "drawdown_pct": drawdown,
        "invalidation_occurred": invalidation_occurred,
        "catalyst_correct": catalyst_correct,
        "thesis_result": thesis_result,
        "outcome_timestamp": _iso(evaluated_at),
        "data_quality": {
            "state": "VERIFIED_OUTCOME",
            "missing": ["sector_benchmark"] if sector_return is None else [],
        },
        "lesson_candidate": {
            "status": "CANDIDATE",
            "decision_id": frozen.get("decision_id"),
            "thesis_result": thesis_result,
            "auto_promote": False,
        },
        "memory_candidate": {"status": "CANDIDATE", "auto_promote": False},
        "hypothesis_candidate": {"status": "CANDIDATE", "auto_promote": False},
        "candidate_outputs_only": True,
        "authority": AUTHORITY,
        "financial_action": False,
    }
    _append(path, row)
    return row


def load_price_series(root: Path, symbol: str) -> dict[str, float]:
    """Load deterministic daily closes from the existing price cache."""
    path = root / PRICE_CACHE_REL
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    data = raw.get(symbol.upper()) if isinstance(raw, dict) else None
    if not isinstance(data, dict):
        return {}
    out: dict[str, float] = {}
    for day, bar in data.items():
        if not isinstance(bar, dict):
            continue
        try:
            out[str(day)[:10]] = float(bar.get("c", bar.get("close")))
        except (TypeError, ValueError):
            continue
    return out


def cached_quote(root: Path, symbol: str, when: datetime) -> dict[str, Any] | None:
    series = load_price_series(root, symbol)
    eligible = sorted(day for day in series if day <= when.date().isoformat())
    if not eligible:
        eligible = sorted(day for day in series if day >= when.date().isoformat())
    if not eligible:
        return None
    day = eligible[-1] if eligible[-1] <= when.date().isoformat() else eligible[0]
    return {"symbol": symbol.upper(), "price": series[day], "as_of": f"{day}T21:00:00+00:00", "source": "price_ohlc_cache"}


def run_outcome_cycle(
    *,
    root: Path,
    now: datetime | None = None,
    horizons: Iterable[int] = DEFAULT_HORIZONS,
    quote_loader: Callable[[Path, str, datetime], dict[str, Any] | None] = cached_quote,
) -> dict[str, Any]:
    """Freeze new decisions and evaluate due rows from existing deterministic prices."""
    now = now or datetime.now(timezone.utc)
    ledger = root / LEDGER_REL
    traces_path = root / "data/cio/agent_run_traces.jsonl"
    traces: list[dict[str, Any]] = []
    if traces_path.is_file():
        for line in traces_path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                trace = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(trace, dict) and isinstance(trace.get("decision"), dict):
                traces.append(trace)

    frozen_n = skipped_n = 0
    for trace in traces:
        decision = trace["decision"]
        prediction_at = _utc(decision.get("as_of"))
        if prediction_at is None or now - prediction_at > timedelta(hours=24):
            skipped_n += 1
            continue
        symbol = str(decision.get("symbol") or "").upper()
        start = quote_loader(root, symbol, prediction_at)
        bench = quote_loader(root, str(decision.get("benchmark") or "SPY"), prediction_at)
        if not start or not bench:
            skipped_n += 1
            continue
        for horizon in horizons:
            try:
                row = freeze_prediction(
                    decision,
                    horizon_days=int(horizon),
                    starting_quote=start,
                    benchmark_quote=bench,
                    path=ledger,
                    frozen_at=now,
                )
                frozen_n += int(not row.get("deduped"))
            except ValueError:
                skipped_n += 1

    evaluated_n = 0
    for frozen in [r for r in _rows(ledger) if r.get("status") == FROZEN]:
        prediction_at = _utc(frozen.get("prediction_timestamp"))
        due = prediction_at + timedelta(days=int(frozen.get("measurement_horizon_days") or 0)) if prediction_at else None
        if due is None or due > now:
            continue
        end = quote_loader(root, str(frozen.get("symbol") or ""), now)
        bench_end = quote_loader(root, str((frozen.get("benchmark") or {}).get("symbol") or "SPY"), now)
        if not end or not bench_end:
            continue
        row = evaluate_frozen_prediction(
            frozen,
            ending_quote=end,
            benchmark_quote=bench_end,
            path=ledger,
            evaluated_at=now,
        )
        evaluated_n += int(not row.get("deduped"))
    return {
        "ok": True,
        "schema": "OutcomeCycleResult@v1",
        "predictions_frozen": frozen_n,
        "outcomes_evaluated": evaluated_n,
        "skipped": skipped_n,
        "ledger": str(LEDGER_REL),
        "authority": AUTHORITY,
        "financial_action": False,
    }
