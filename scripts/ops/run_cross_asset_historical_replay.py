#!/usr/bin/env python3
"""Offline archive replay through the existing advisory expression evaluator.

Input contracts (JSONL; never resolved from production state):
* signals.jsonl: CrossAssetHistoricalReplaySignal@v1 wraps a native
  CrossAssetDecisionEvent@v1 as `event`, confirmed timestamped `identity`, and
  optional timestamped `position` using the existing held/shares vocabulary.
* prices.jsonl: CrossAssetHistoricalPrice@v1 contains symbol, security_guid,
  aware as_of, positive finite spot `price`, and nonempty source_ref.
* expression_facts.jsonl (optional): CrossAssetHistoricalExpressionFacts@v1
  contains event_id, symbol, security_guid, aware as_of, source_ref and
  facts_by_structure. Each fact has its own aware as_of and uses the existing
  cross_asset_decision.evaluate_expressions vocabulary without policy changes.

The window is inclusive [as_of - days, as_of]. Facts and prices must be known
at the signal instant. Supplied scores support SCORING_COMPARISON_ONLY, never
realized option superiority, fills, inferred option prices or production READY.
`--as-of` reproduces a captured window; default captures the current time once.
"""
from __future__ import annotations

# CLI-only: this does not install a scheduler or become a production writer.
NO_CONSUMER_REASON = (
    "CrossAssetHistoricalReplayMetrics@v1 is emitted by this offline CLI only; "
    "no production consumer or EV/counterfactual authority is established."
)

import argparse
import json
import math
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.lib.cross_asset_decision import (  # noqa: E402
    AUTHORITY, EVENT_SCHEMA, apply_expression_evaluation, build_decision_object,
    normalize_signal,
)

SIGNAL_SCHEMA = "CrossAssetHistoricalReplaySignal@v1"
PRICE_SCHEMA = "CrossAssetHistoricalPrice@v1"
FACT_SCHEMA = "CrossAssetHistoricalExpressionFacts@v1"
_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")
_NUMERIC_FACTS = {"score", "expected_return", "capital_required", "maximum_risk",
                  "quote_age_minutes", "open_interest", "spread_pct"}
_BOOL_FACTS = {"contract_available", "liquid", "earnings_before_expiry",
               "position_size_ok", "thesis_complete", "cio_approved", "cio_required"}
_STOCK = {"shares", "sell_shares", "trim_shares", "reduce_shares", "no_action"}


def _instant(value, field):
    if not isinstance(value, str) or not _TIME.fullmatch(value):
        raise ValueError(f"{field}:aware_timestamp_required")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError as exc:
        raise ValueError(f"{field}:invalid_timestamp") from exc


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _mapping(value, field):
    if not isinstance(value, dict):
        raise ValueError(f"{field}:object_required")
    return value


def _nonempty(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field}:nonempty_string_required")
    return value


def _reject_constant(_value):
    raise ValueError("nonfinite_json_number")


def _rows(path, schema):
    if not path.exists():
        return []
    rows = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = _mapping(json.loads(line, parse_constant=_reject_constant), "row")
            if row.get("schema") != schema:
                raise ValueError("unsupported_schema")
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{path.name}:{line_no}:{exc}") from exc
        rows.append(row)
    return rows


def _signal(row):
    event = _mapping(row.get("event"), "event")
    if event.get("schema") != EVENT_SCHEMA:
        raise ValueError("event_schema_required")
    _nonempty(event.get("event_id"), "event.event_id")
    symbol = _nonempty(event.get("symbol"), "event.symbol").strip().upper()
    normalize_signal(event.get("signal"))
    _nonempty(event.get("source"), "event.source")
    _mapping(event.get("payload"), "event.payload")
    observed = _instant(event.get("observed_at"), "event.observed_at")
    identity = _mapping(row.get("identity"), "identity")
    if identity.get("symbol") != symbol:
        raise ValueError("identity_symbol_mismatch")
    _nonempty(identity.get("security_guid"), "identity.security_guid")
    if identity.get("identity_status") != "CONFIRMED":
        raise ValueError("identity_not_confirmed")
    if _instant(identity.get("as_of"), "identity.as_of") > observed:
        raise ValueError("identity_lookahead")
    position = _mapping(row.get("position", {}), "position")
    if position:
        if _instant(position.get("as_of"), "position.as_of") > observed:
            raise ValueError("position_lookahead")
        if "held" in position and not isinstance(position["held"], bool):
            raise ValueError("position.held:boolean_required")
        if "shares" in position and (not _number(position["shares"]) or position["shares"] < 0):
            raise ValueError("position.shares:nonnegative_finite_number_required")
    return observed


def _snapshot(row, *, facts=False):
    for key in ("symbol", "security_guid", "source_ref"):
        _nonempty(row.get(key), key)
    known = _instant(row.get("as_of"), "as_of")
    if not facts:
        if not _number(row.get("price")) or row["price"] <= 0:
            raise ValueError("price:positive_finite_spot_required")
        return known
    _nonempty(row.get("event_id"), "event_id")
    for structure, fact in _mapping(row.get("facts_by_structure"), "facts_by_structure").items():
        _nonempty(structure, "structure")
        _mapping(fact, "fact")
        if _instant(fact.get("as_of"), "fact.as_of") > known:
            raise ValueError("fact_lookahead")
        for key in _NUMERIC_FACTS & fact.keys():
            if fact[key] is not None and not _number(fact[key]):
                raise ValueError(f"fact.{key}:finite_number_required")
        for key in _BOOL_FACTS & fact.keys():
            if not isinstance(fact[key], bool):
                raise ValueError(f"fact.{key}:boolean_required")
    return known


def _validated(rows, validator, filename):
    for line_no, row in enumerate(rows, 1):
        try:
            validator(row)
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError(f"{filename}:row{line_no}:{exc}") from exc
    return rows


def run_window(days: int, *, archive_dir: Path | None, as_of: str | None = None) -> dict:
    """Replay explicit immutable input snapshots; never fetch or invent missing facts."""
    captured = as_of or datetime.now(timezone.utc).isoformat()
    result = {
        "window_days": days, "as_of": captured, "authority": AUTHORITY,
        "financial_action": False, "data_quality": "INSUFFICIENT_DATA",
        "evaluation_scope": "CANDIDATE_COVERAGE_ONLY", "signals_in_window": 0,
        "signals_evaluated": 0, "signals_skipped": 0, "signals_outside_window": 0,
        "future_signals_excluded": 0, "future_prices_excluded": 0, "future_facts_excluded": 0,
        "duplicate_signals_ignored": 0, "prices_covered": 0, "price_coverage_ratio": None,
        "scoring_comparisons": 0, "scoring_winner_counts": {}, "shares_chosen": None,
        "options_would_be_superior": None, "options_superior_rate": None,
        "insufficient_reasons": [], "refusals": [], "evaluations": [],
        "note": "Snapshot scores are not realized counterfactuals; EV readiness is not established.",
        "archives": {"archive_dir": str(archive_dir) if archive_dir else None},
    }
    try:
        if not isinstance(days, int) or isinstance(days, bool) or days <= 0:
            raise ValueError("window_days:positive_integer_required")
        end = _instant(captured, "as_of")
        start = end - timedelta(days=days)
        result["window_start"] = start.isoformat()
        if archive_dir is None:
            result["insufficient_reasons"] = ["SIGNAL_ARCHIVE_MISSING", "PRICE_ARCHIVE_MISSING", "OPTION_COMPARISON_MISSING"]
            return result
        archive_dir = Path(archive_dir)
        for key, filename in (("signals", "signals.jsonl"), ("prices", "prices.jsonl"), ("expression_facts", "expression_facts.jsonl")):
            result["archives"][key] = (archive_dir / filename).is_file()
        result["archives"]["option_chains"] = (archive_dir / "option_chains").exists()
        signals = _validated(_rows(archive_dir / "signals.jsonl", SIGNAL_SCHEMA), _signal, "signals.jsonl")
        prices = _validated(_rows(archive_dir / "prices.jsonl", PRICE_SCHEMA), _snapshot, "prices.jsonl")
        facts = _validated(_rows(archive_dir / "expression_facts.jsonl", FACT_SCHEMA),
                           lambda row: _snapshot(row, facts=True), "expression_facts.jsonl")
        seen = {}
        winners = Counter()
        for signal in sorted(signals, key=lambda row: (_signal(row), row["event"]["event_id"])):
            event = signal["event"]
            event_id = event["event_id"]
            if event_id in seen:
                if signal != seen[event_id]:
                    raise ValueError("signals.jsonl:conflicting_event_id")
                result["duplicate_signals_ignored"] += 1
                continue
            seen[event_id] = signal
            observed = _signal(signal)
            if observed > end:
                result["future_signals_excluded"] += 1
                continue
            if observed < start:
                result["signals_outside_window"] += 1
                continue
            result["signals_in_window"] += 1
            identity = signal["identity"]
            matching = [row for row in prices if row["symbol"] == identity["symbol"] and row["security_guid"] == identity["security_guid"]]
            usable = [row for row in matching if _snapshot(row) <= observed]
            result["future_prices_excluded"] += len(matching) - len(usable)
            if not usable:
                result["signals_skipped"] += 1
                result["refusals"].append({"event_id": event_id, "reason": "PRICE_AS_OF_MISSING"})
                continue
            price = max(usable, key=_snapshot)
            if any(_snapshot(row) == _snapshot(price) and row["price"] != price["price"] for row in usable):
                raise ValueError("prices.jsonl:conflicting_price_snapshot")
            matching = [row for row in facts if row["event_id"] == event_id and row["symbol"] == identity["symbol"] and row["security_guid"] == identity["security_guid"]]
            usable = [row for row in matching if _snapshot(row, facts=True) <= observed]
            result["future_facts_excluded"] += len(matching) - len(usable)
            selected = max(usable, key=lambda row: _snapshot(row, facts=True)) if usable else None
            if selected and any(_snapshot(row, facts=True) == _snapshot(selected, facts=True) and row != selected for row in usable):
                raise ValueError("expression_facts.jsonl:conflicting_fact_snapshot")
            obj = build_decision_object(event=event, identity=identity, position=signal.get("position"))
            obj = apply_expression_evaluation(obj, selected["facts_by_structure"] if selected else {})
            comparison = obj["expression_comparison"]
            if any(row["score"] is not None and not _number(row["score"]) for row in comparison["candidates"]):
                raise ValueError("expression_facts.jsonl:derived_nonfinite_comparison")
            scored = {row["structure"] for row in comparison["candidates"] if row["state"] == "SCORED"}
            if scored & _STOCK and scored - _STOCK:
                result["scoring_comparisons"] += 1
                winners[comparison["winner"]] += 1
            result["signals_evaluated"] += 1
            result["prices_covered"] += 1
            result["evaluations"].append({
                "event_id": event_id, "evaluation_id": obj["evaluation_id"], "symbol": identity["symbol"],
                "security_guid": identity["security_guid"], "observed_at": event["observed_at"],
                "price": price, "fact_source_ref": selected["source_ref"] if selected else None,
                "comparison": comparison, "authority": AUTHORITY, "financial_action": False,
            })
        count = result["signals_in_window"]
        result["price_coverage_ratio"] = result["prices_covered"] / count if count else None
        result["scoring_winner_counts"] = dict(sorted(winners.items()))
        if not signals:
            result["insufficient_reasons"].append("SIGNAL_ARCHIVE_MISSING_OR_EMPTY")
        if not count:
            result["insufficient_reasons"].append("NO_SIGNALS_IN_WINDOW")
        if result["prices_covered"] < count or not prices:
            result["insufficient_reasons"].append("PRICE_COVERAGE_INCOMPLETE")
        if result["scoring_comparisons"] < count or not count:
            result["insufficient_reasons"].append("OPTION_COMPARISON_MISSING")
        if result["scoring_comparisons"]:
            result["evaluation_scope"] = "SCORING_COMPARISON_ONLY"
            if not result["insufficient_reasons"]:
                result["data_quality"] = "SCORING_COMPARISON_ONLY"
    except (ValueError, TypeError, OverflowError, OSError) as exc:
        result.update(data_quality="INVALID_DATA", signals_evaluated=0, prices_covered=0,
                      scoring_comparisons=0, scoring_winner_counts={}, evaluations=[],
                      price_coverage_ratio=None, evaluation_scope="CANDIDATE_COVERAGE_ONLY")
        result["refusals"] = [{"reason": str(exc)}]
    return result


def _output_aliases_inputs(archive: Path, output: Path) -> bool:
    """Resolve path aliases and inode aliases before permitting an artifact write."""
    target = output.resolve()
    if target.is_relative_to(archive.resolve()):
        return True
    try:
        output_stat = output.stat()
    except FileNotFoundError:
        output_stat = None
    for name in ("signals.jsonl", "prices.jsonl", "expression_facts.jsonl"):
        source = archive / name
        if source.resolve() == target:
            return True
        try:
            source_stat = source.stat()
        except FileNotFoundError:
            continue
        if output_stat and (source_stat.st_dev, source_stat.st_ino) == (output_stat.st_dev, output_stat.st_ino):
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, nargs="+", default=[30, 60, 90])
    ap.add_argument("--archive-dir", default="")
    ap.add_argument("--as-of", default="", help="aware ISO timestamp; captured once if omitted")
    ap.add_argument("--out", default="")
    args = ap.parse_args(argv)
    archive = Path(args.archive_dir) if args.archive_dir else None
    if archive and args.out:
        try:
            alias = _output_aliases_inputs(archive, Path(args.out))
        except (OSError, RuntimeError):
            print(json.dumps({"ok": False, "reason": "output_archive_alias_check_failed"}))
            return 2
        if alias:
            print(json.dumps({"ok": False, "reason": "output_must_not_alias_read_only_archive"}))
            return 2
    captured = args.as_of or datetime.now(timezone.utc).isoformat()
    metrics = {
        "schema": "CrossAssetHistoricalReplayMetrics@v1", "as_of": captured,
        "windows": [run_window(d, archive_dir=archive, as_of=captured) for d in args.days],
        "authority": AUTHORITY, "financial_action": False,
    }
    ok = all(window["data_quality"] != "INVALID_DATA" for window in metrics["windows"])
    text = json.dumps(metrics, indent=2, allow_nan=False)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(json.dumps({"ok": ok, "wrote": args.out}))
    else:
        print(text)
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
