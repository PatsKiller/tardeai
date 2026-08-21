"""READ-ONLY 14-day provider spend snapshot.

Prefers Flash/bridge ``provider_cost`` events.jsonl (LOCAL_CALCULATED /
PROVIDER_REPORTED with tokens). Never publishes llm_consumption_log
k-char / stale-Aug-3 estimator totals as truth (known garbage ~$12k/14d).

source_quality: TRUSTED | UNTRUSTED
published_as_truth: False when UNTRUSTED (totals omitted).

No Drive upload. No new datastore. No paid LLM calls.
WRITE is opt-in (CLI ``--write``) to data/cio/provider_spend_latest.json.

READ_ONLY_ADVISORY. financial_action=false.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

SCHEMA = "ProviderSpendSnapshot@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
WINDOW_DAYS = 14

QUALITY_TRUSTED = "TRUSTED"
QUALITY_UNTRUSTED = "UNTRUSTED"

# Known-garbage: llm_consumption_log estimated_cost_usd treating k-chars as USD
# and/or stale 2026-08-03 flat prices → ~$12k / 14d. Do not publish as truth.
KCHAR_USD_FLOOR = 10.0
UNTRUSTED_WINDOW_USD_FLOOR = 100.0
STALE_AUG3_SCHEDULE = "deepseek-v4-flat-2026-08-03"

TRUSTED_COST_SOURCES = frozenset({"LOCAL_CALCULATED", "PROVIDER_REPORTED"})
TRUSTED_COST_BASIS = frozenset({"provider_usage_x_registry_snapshot"})
UNTRUSTED_BASIS = frozenset({
    "",
    "oauth_free_or_unset",
    "kchar",
    "k-char",
    "estimated",
    "stale_aug3",
})

_DEFAULT_JSONL = (
    "data/runtime/provider_cost/events.jsonl",
)
_CONSUMPTION_DUMPS = (
    "data/cio/llm_consumption_dump.json",
    "data/cio/llm_consumption_dump.jsonl",
    "data/runtime/llm_consumption_log.jsonl",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _parse_dt(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    s = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        if len(s) >= 10:
            try:
                dt = datetime.fromisoformat(s[:10] + "T00:00:00+00:00")
            except ValueError:
                return None
        else:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _project_root(root: Path | str | None = None) -> Path:
    if root:
        return Path(root)
    for env in ("TRADEAI_ROOT", "MATURITY_CONTROL_ROOT"):
        v = os.environ.get(env)
        if v:
            return Path(v)
    return Path(__file__).resolve().parents[2]


def _money(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v != v or v < 0:  # NaN / negative
        return None
    return v


def _has_tokens(ev: dict[str, Any]) -> bool:
    for k in (
        "input_tokens", "output_tokens", "prompt_tokens", "completion_tokens",
        "tokens_in", "tokens_out", "cached_input_tokens",
    ):
        v = ev.get(k)
        if v is None or v == "":
            continue
        try:
            if float(v) > 0:
                return True
        except (TypeError, ValueError):
            continue
    usage = ev.get("usage")
    if isinstance(usage, dict):
        for k in ("input_tokens", "output_tokens", "prompt_tokens", "completion_tokens"):
            try:
                if float(usage.get(k) or 0) > 0:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def classify_event_quality(ev: dict[str, Any]) -> str:
    """TRUSTED only for token-priced Flash/bridge / provider-reported USD.

    llm_consumption_log estimated_cost_usd without provider_usage basis is
    UNTRUSTED (k-char pollution / stale Aug-3 estimator).
    """
    basis = str(ev.get("cost_basis") or "").strip().lower()
    src = str(ev.get("cost_source") or "").strip().upper()
    schedule = str(ev.get("price_schedule_id") or "")
    origin = str(ev.get("source") or ev.get("source_service") or ev.get("evidence_refs") or "")
    if isinstance(ev.get("evidence_refs"), list):
        origin = " ".join(str(x) for x in ev["evidence_refs"])

    estimated = _money(ev.get("estimated_cost_usd"))
    reported = _money(ev.get("provider_reported_cost_usd"))
    calculated = _money(ev.get("calculated_cost_usd"))
    actual = _money(ev.get("actual_usd") or ev.get("cost_usd") or ev.get("cost"))

    # Explicit k-char / oauth estimator
    if estimated is not None and basis in UNTRUSTED_BASIS:
        return QUALITY_UNTRUSTED
    if estimated is not None and estimated >= KCHAR_USD_FLOOR and not _has_tokens(ev):
        return QUALITY_UNTRUSTED
    if "llm_consumption_log" in origin.lower() and basis not in TRUSTED_COST_BASIS:
        if estimated is not None and (not _has_tokens(ev) or estimated >= KCHAR_USD_FLOOR):
            return QUALITY_UNTRUSTED

    if schedule == STALE_AUG3_SCHEDULE and estimated is not None and not _has_tokens(ev):
        return QUALITY_UNTRUSTED

    if src in TRUSTED_COST_SOURCES and (reported is not None or calculated is not None):
        usd = reported if reported is not None else calculated
        if usd is not None and usd >= KCHAR_USD_FLOOR and not _has_tokens(ev):
            return QUALITY_UNTRUSTED
        return QUALITY_TRUSTED
    if basis in TRUSTED_COST_BASIS and (reported is not None or estimated is not None):
        return QUALITY_TRUSTED
    if actual is not None and _has_tokens(ev) and actual < KCHAR_USD_FLOOR:
        return QUALITY_TRUSTED
    if reported is not None and _has_tokens(ev) and reported < KCHAR_USD_FLOOR:
        return QUALITY_TRUSTED
    if calculated is not None and _has_tokens(ev) and calculated < KCHAR_USD_FLOOR:
        return QUALITY_TRUSTED

    if estimated is not None:
        return QUALITY_UNTRUSTED
    if actual is not None and actual >= KCHAR_USD_FLOOR and not _has_tokens(ev):
        return QUALITY_UNTRUSTED
    return QUALITY_UNTRUSTED


def event_usd(ev: dict[str, Any]) -> Optional[float]:
    """USD for aggregation. Ignores untrusted estimator fields."""
    if classify_event_quality(ev) != QUALITY_TRUSTED:
        return None
    for k in (
        "provider_reported_cost_usd",
        "calculated_cost_usd",
        "actual_usd",
        "cost_usd",
        "cost",
    ):
        v = _money(ev.get(k))
        if v is not None:
            return v
    basis = str(ev.get("cost_basis") or "")
    if basis in TRUSTED_COST_BASIS:
        return _money(ev.get("estimated_cost_usd"))
    return None


def untrusted_estimator_usd(ev: dict[str, Any]) -> Optional[float]:
    if classify_event_quality(ev) != QUALITY_UNTRUSTED:
        return None
    for k in ("estimated_cost_usd", "calculated_cost_usd", "provider_reported_cost_usd", "cost_usd"):
        v = _money(ev.get(k))
        if v is not None:
            return v
    return None


def event_ts(ev: dict[str, Any]) -> Optional[datetime]:
    for k in ("usage_start", "created_at", "at", "ts", "timestamp", "observed_at", "as_of"):
        dt = _parse_dt(ev.get(k))
        if dt is not None:
            return dt
    return None


def event_provider(ev: dict[str, Any]) -> str:
    p = str(ev.get("provider") or ev.get("model_lane") or "").strip().lower()
    if p:
        return p
    model = str(ev.get("model") or "").lower()
    if "deepseek" in model:
        return "deepseek"
    if "grok" in model or "xai" in model:
        return "grok"
    if "claude" in model or "anthropic" in model:
        return "anthropic"
    if "gpt" in model or "openai" in model:
        return "openai"
    if "gemma" in model or "qwen" in model or "ollama" in model:
        return "local"
    return "unknown"


def event_lane(ev: dict[str, Any]) -> str:
    for k in ("source_lane", "lane", "requested_policy", "executed_policy", "model_lane"):
        v = str(ev.get(k) or "").strip()
        if v:
            return v
    svc = str(ev.get("source_service") or "").strip()
    if svc:
        return svc
    model = str(ev.get("model") or "").strip()
    if model:
        return model
    return "unspecified"


def load_json_events(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".jsonl" or path.name.endswith(".jsonl"):
        return _parse_jsonl(text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return _parse_jsonl(text)
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        rows = data.get("events") or data.get("rows") or data.get("items")
        if isinstance(rows, list):
            return [x for x in rows if isinstance(x, dict)]
        # single event object
        if data.get("provider") or data.get("estimated_cost_usd") is not None or data.get("calculated_cost_usd") is not None:
            return [data]
    return []


def _parse_jsonl(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def discover_source_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    env_log = os.environ.get("PROVIDER_COST_EVENT_LOG", "").strip()
    if env_log:
        paths.append(Path(env_log))
    for rel in _DEFAULT_JSONL:
        paths.append(root / rel)
    for rel in _CONSUMPTION_DUMPS:
        paths.append(root / rel)
    # unique, existing
    seen: set[str] = set()
    out: list[Path] = []
    for p in paths:
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        if p.is_file():
            out.append(p)
    return out


def build_snapshot(
    *,
    root: Path | str | None = None,
    now: datetime | None = None,
    events: Optional[Iterable[dict[str, Any]]] = None,
    source_paths: Optional[Iterable[Path | str]] = None,
    write: bool = False,
) -> dict[str, Any]:
    """Build a 14-day spend snapshot. ``write`` is opt-in."""
    root_p = _project_root(root)
    now_dt = now or _now()
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)
    window_start = now_dt - timedelta(days=WINDOW_DAYS)

    loaded: list[tuple[str, dict[str, Any]]] = []
    used_paths: list[str] = []

    if events is not None:
        for ev in events:
            if isinstance(ev, dict):
                loaded.append(("inline", ev))
        used_paths.append("inline")
    else:
        paths = [Path(p) for p in source_paths] if source_paths is not None else discover_source_paths(root_p)
        for p in paths:
            rows = load_json_events(p)
            if not rows:
                continue
            used_paths.append(str(p))
            origin = p.name
            for ev in rows:
                rec = dict(ev)
                rec.setdefault("source", rec.get("source") or origin)
                loaded.append((str(p), rec))

    trusted_rows: list[dict[str, Any]] = []
    untrusted_rows: list[dict[str, Any]] = []
    untrusted_usd = 0.0
    outside = 0

    for _src, ev in loaded:
        ts = event_ts(ev)
        if ts is None or ts < window_start or ts > now_dt + timedelta(days=1):
            outside += 1
            continue
        q = classify_event_quality(ev)
        if q == QUALITY_TRUSTED:
            trusted_rows.append(ev)
        else:
            untrusted_rows.append(ev)
            u = untrusted_estimator_usd(ev)
            if u is not None:
                untrusted_usd += u

    per_provider: dict[str, dict[str, Any]] = {}
    per_lane: dict[str, dict[str, Any]] = {}
    per_day: dict[str, dict[str, Any]] = {}
    total = 0.0
    n_trusted = 0
    for ev in trusted_rows:
        usd = event_usd(ev)
        if usd is None:
            continue
        n_trusted += 1
        total += usd
        prov = event_provider(ev)
        lane = event_lane(ev)
        ts = event_ts(ev)
        day = ts.date().isoformat() if ts else "unknown"
        bucket = per_provider.setdefault(prov, {"usd": 0.0, "events": 0})
        bucket["usd"] += usd
        bucket["events"] += 1
        lb = per_lane.setdefault(lane, {"usd": 0.0, "events": 0})
        lb["usd"] += usd
        lb["events"] += 1
        db = per_day.setdefault(day, {"usd": 0.0, "events": 0})
        db["usd"] += usd
        db["events"] += 1

    notes = [
        "Prefer Flash/bridge provider_cost events.jsonl (LOCAL_CALCULATED / PROVIDER_REPORTED).",
        "llm_consumption_log estimated_cost_usd is UNTRUSTED unless cost_basis="
        "provider_usage_x_registry_snapshot (k-char / stale Aug-3 estimator).",
        "Do not upload this file to Drive.",
        f"TTL window: last {WINDOW_DAYS} days.",
    ]

    # Prefer trusted Flash/bridge. If none, do not publish untrusted estimator.
    if n_trusted > 0 and untrusted_usd >= UNTRUSTED_WINDOW_USD_FLOOR:
        quality = QUALITY_TRUSTED
        published = True
        reason = None
        notes.append(
            f"Discarded UNTRUSTED estimator rows totaling ${untrusted_usd:.2f}; "
            "not mixed into published totals."
        )
    elif n_trusted > 0:
        quality = QUALITY_TRUSTED
        published = True
        reason = None
        if untrusted_rows:
            notes.append(f"Ignored {len(untrusted_rows)} UNTRUSTED estimator rows.")
    elif untrusted_usd >= UNTRUSTED_WINDOW_USD_FLOOR or len(untrusted_rows) > 0:
        quality = QUALITY_UNTRUSTED
        published = False
        reason = (
            "llm_consumption_log / estimator rows are not trustworthy "
            f"(stale Aug-3 prices or k-char-as-USD; discarded_usd={round(untrusted_usd, 2)}). "
            "Known garbage pattern is ~$12k/14d. Not published as truth."
        )
        notes.append(reason)
    else:
        quality = QUALITY_UNTRUSTED
        published = False
        reason = "no_trusted_events_in_window"
        notes.append("No Flash/bridge events in window; snapshot not published as truth.")

    def _round_bucket(b: dict[str, Any]) -> dict[str, Any]:
        return {"usd": round(float(b["usd"]), 6), "events": int(b["events"])}

    payload: dict[str, Any] = {
        "ok": True,
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "financial_action": False,
        "as_of": _iso(now_dt),
        "window_days": WINDOW_DAYS,
        "window_start": _iso(window_start),
        "window_end": _iso(now_dt),
        "source_quality": quality,
        "published_as_truth": published,
        "untrusted_reason": reason,
        "sources_used": used_paths,
        "per_provider": {k: _round_bucket(v) for k, v in sorted(per_provider.items())} if published else {},
        "per_lane": {k: _round_bucket(v) for k, v in sorted(per_lane.items())} if published else {},
        "per_day": {k: _round_bucket(v) for k, v in sorted(per_day.items())} if published else {},
        "totals": {
            "usd": round(total, 6) if published else None,
            "events": n_trusted if published else 0,
            "trusted_events": n_trusted,
            "untrusted_events": len(untrusted_rows),
            "outside_window": outside,
        },
        "diagnostics": {
            "discarded_untrusted_usd": round(untrusted_usd, 4),
            "untrusted_event_n": len(untrusted_rows),
            "trusted_event_n": n_trusted,
            "loaded_n": len(loaded),
        },
        "notes": notes,
    }

    if write:
        path = write_snapshot(payload, root=root_p)
        payload["written_to"] = str(path)
    return payload


def snapshot_path(*, root: Path | str | None = None) -> Path:
    return _project_root(root) / "data" / "cio" / "provider_spend_latest.json"


def write_snapshot(payload: dict[str, Any], *, root: Path | str | None = None) -> Path:
    path = snapshot_path(root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="READ-ONLY 14-day provider spend snapshot")
    ap.add_argument("--root", default=None)
    ap.add_argument("--write", action="store_true", help="Write data/cio/provider_spend_latest.json")
    ap.add_argument("--source", action="append", default=[], help="Extra JSON/JSONL path")
    args = ap.parse_args(argv)
    extra = [Path(p) for p in args.source] if args.source else None
    snap = build_snapshot(root=args.root, source_paths=extra, write=bool(args.write))
    # Print a compact view — never the untrusted $12k as truth.
    print(json.dumps({
        "schema": snap["schema"],
        "source_quality": snap["source_quality"],
        "published_as_truth": snap["published_as_truth"],
        "untrusted_reason": snap["untrusted_reason"],
        "totals": snap["totals"],
        "per_provider": snap["per_provider"],
        "written_to": snap.get("written_to"),
    }, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
