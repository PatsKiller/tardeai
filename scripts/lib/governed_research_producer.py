#!/usr/bin/env python3
"""governed_research_producer.py — canonical recurring research → wake feed producer.

Phase 2 of the Grok-closure campaign. This is the ONE canonical recurring path
that turns a scheduled trigger into fresh, governed research objects that the
persistent-wake subject selector can consume:

    scheduled trigger
      → governed Brave router (budget governance, fail-closed)
      → durable ResearchObject@v1 artifact (only after real research succeeds)
      → atomic append to the stable wake feed (TRADEAI_WAKE_RESEARCH_OBJECTS_PATH)
      → wake_subject_selector → run_persistent_wake (scheduled wake consumption)

Why this exists. ``wake_subject_selector.load_selection_inputs`` reads a JSONL
feed of research objects, but nothing in the serving tree wrote that feed. Every
research cron (research_scheduler → hermes_external_researcher → the
``hermes_external_research`` desk store, and ~56 other research crons) produced
research into its own store and never emitted a ``ResearchObject@v1`` into the
wake feed. Result: the selector's research candidates were always empty, so no
``unconsumed_research``-typed wake object was ever produced. This module is the
missing producer, and it is governed end to end.

Rules (fail-closed):
  * Feature flag OFF → no side effects, no provider call, no feed write.
  * No hardcoded provider-plan claims; capacity is the local cost policy only.
  * No direct provider bypass — the ONLY network path is ``brave_router.search``.
  * A research object is created only after a real provider result is returned.
  * Dedupe by stable identity (research_id == idempotency key); a duplicate
    result never writes a second feed row.
  * ``nothing eligible`` (no targets) is reported separately from ``broken``
    (provider unavailable / budget denied / corrupt quota).
  * Feed writes are atomic (tmp + rename); the feed is append-only.
  * Disable = set the flag off; rollback = stop appending + the health file
    records the last write, and the feed is never truncated by this module.

Authority: READ_ONLY_ADVISORY. Never sizes, orders, stops, or writes broker state.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

SCHEMA = "GovernedResearchProducer@v1"
FEATURE_FLAG = "GOVERNED_RESEARCH_PRODUCER_ENABLED"
FEED_ENV = "TRADEAI_WAKE_RESEARCH_OBJECTS_PATH"
HEALTH_ENV = "GOVERNED_RESEARCH_PRODUCER_HEALTH_PATH"

Clock = Callable[[], datetime]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def enabled(env: Mapping[str, str] | None = None) -> bool:
    src = env if env is not None else os.environ
    return str(src.get(FEATURE_FLAG, "")).strip().lower() in {"1", "true", "yes", "on"}


def source_sha(env: Mapping[str, str] | None = None) -> str:
    """Served source identity. Never a hardcoded SHA; falls back to 'unknown'."""
    src = env if env is not None else os.environ
    return src.get("TRADEAI_SOURCE_SHA") or src.get("BUILD_SHA") or src.get("SOURCE_COMMIT") or "unknown"


def feed_path(env: Mapping[str, str] | None = None) -> Path | None:
    src = env if env is not None else os.environ
    raw = str(src.get(FEED_ENV, "")).strip()
    return Path(raw) if raw else None


def health_path(env: Mapping[str, str] | None = None) -> Path | None:
    src = env if env is not None else os.environ
    raw = str(src.get(HEALTH_ENV, "")).strip()
    return Path(raw) if raw else None


@dataclass
class ProducerResult:
    ok: bool
    disabled: bool = False
    produced: int = 0
    deduped: int = 0
    failed: int = 0
    budget_denied: int = 0
    eligible: int = 0
    outcome: str = "nothing_eligible"  # nothing_eligible | produced | broken | disabled
    errors: list[str] = field(default_factory=list)
    feed_rows: int = 0
    feed_latest_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "ok": self.ok,
            "disabled": self.disabled,
            "produced": self.produced,
            "deduped": self.deduped,
            "failed": self.failed,
            "budget_denied": self.budget_denied,
            "eligible": self.eligible,
            "outcome": self.outcome,
            "errors": list(self.errors),
            "feed_rows": self.feed_rows,
            "feed_latest_at": self.feed_latest_at,
        }


def _load_feed(path: Path) -> list[dict]:
    """Read the existing feed. Malformed lines are skipped, never fatal."""
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def _feed_ids(path: Path) -> set[str]:
    out: set[str] = set()
    for row in _load_feed(path):
        rid = str(row.get("research_object_id") or row.get("id") or row.get("research_id") or "")
        if rid:
            out.add(rid)
    return out


def _append_feed(path: Path, rows: list[dict]) -> None:
    """Atomic append: write to a temp file then rename over the target.

    The rename is atomic on the same filesystem, so a concurrent reader sees
    either the old feed or the new feed, never a torn write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_feed(path)
    merged = existing + rows
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        "".join(json.dumps(r, sort_keys=True, default=str) + "\n" for r in merged),
        encoding="utf-8",
    )
    tmp.replace(path)


def _write_health(path: Path, doc: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(doc, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
    except Exception:
        pass


def _resolve_targets(targets: Iterable[Mapping[str, Any]] | None, env: Mapping[str, str]) -> list[dict]:
    """Normalize research targets to ``{symbol, subject_guid, query}``.

    ``subject_guid`` is looked up from the identity registry (never minted here);
    a target without a resolvable subject_guid is not eligible and is skipped.
    """
    out: list[dict] = []
    for t in targets or []:
        if not isinstance(t, Mapping):
            continue
        symbol = str(t.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        subject_guid = str(t.get("subject_guid") or "").strip() or None
        if not subject_guid:
            try:
                from scripts.lib.cio_subject_guid import lookup_subject

                subject_guid = lookup_subject(symbol, root=None).get("subject_guid")
            except Exception:
                subject_guid = None
        if not subject_guid:
            continue
        query = str(t.get("query") or "").strip() or f"{symbol} stock catalyst news"
        out.append({"symbol": symbol, "subject_guid": subject_guid, "query": query})
    # Deterministic order: symbol.
    out.sort(key=lambda x: x["symbol"])
    return out


def _build_feed_row(
    ro: Any,
    *,
    symbol: str,
    subject_guid: str,
    sha: str,
    trigger: dict,
) -> dict:
    """Map a ResearchObject@v1 to the selector-compatible feed row.

    Emits BOTH ``research_object_id`` and ``id`` (the selector accepts either),
    plus ``subject_guid``, ``published_at``/``produced_at``, source URL, content
    hash, created time, source SHA, and trigger provenance.
    """
    d = ro.to_dict() if hasattr(ro, "to_dict") else dict(ro)
    rid = str(d.get("research_id") or "")
    return {
        "research_object_id": rid,
        "id": rid,
        "subject_guid": str(subject_guid),
        "symbol": symbol,
        "source_url": d.get("source_url"),
        "source_url_canonical": d.get("source_url_canonical"),
        "published_at": d.get("published_at"),
        "produced_at": d.get("captured_at") or d.get("published_at"),
        "captured_at": d.get("captured_at"),
        "content_hash": d.get("content_hash"),
        "title": d.get("title"),
        "body": d.get("body"),
        "schema_version": d.get("schema_version", "ResearchObject@v1"),
        "interface_version": d.get("interface_version"),
        "authoritative_source_rank": d.get("authoritative_source_rank"),
        "lifecycle_state": d.get("lifecycle_state"),
        "source_sha": sha,
        "trigger": trigger,
        "provenance": d.get("provenance") or {},
    }


def produce_research(
    *,
    targets: Iterable[Mapping[str, Any]] | None,
    env: Mapping[str, str] | None = None,
    clock: Clock | None = None,
    transport: Any = None,
    api_key: str | None = None,
    root: Path | None = None,
    feed: Path | str | None = None,
    health: Path | str | None = None,
) -> ProducerResult:
    """Run one governed research pass and append fresh research objects to the feed.

    ``transport`` / ``api_key`` / ``root`` are threaded to ``brave_router.search``;
    tests inject a fake transport, production injects nothing (live is explicitly
    armed by ``BRAVE_ROUTER_LIVE``). This module NEVER opens a network socket
    itself — the router is the only provider boundary.
    """
    clock = clock or _now
    now = clock()
    env_map = dict(env if env is not None else os.environ)

    if not enabled(env_map):
        return ProducerResult(ok=False, disabled=True, outcome="disabled", errors=["feature_flag_off"])

    fp = Path(feed) if feed is not None else feed_path(env_map)
    hp = Path(health) if health is not None else health_path(env_map)
    sha = source_sha(env_map)

    trigger = {
        "kind": "scheduled",
        "producer": "governed_research_producer",
        "triggered_at": _iso(now),
        "source_sha": sha,
    }

    resolved = _resolve_targets(targets, env_map)
    if not resolved:
        result = ProducerResult(ok=True, eligible=0, outcome="nothing_eligible")
        if hp:
            _write_health(
                hp,
                {
                    "schema": "GovernedResearchProducerHealth@v1",
                    "as_of": _iso(now),
                    "outcome": "nothing_eligible",
                    "source_sha": sha,
                    "feed_path": str(fp) if fp else None,
                    "note": "no eligible targets (empty or no resolvable subject_guid)",
                },
            )
        return result

    from scripts.lib import brave_router as router
    from scripts.lib.research_object import build_research_object

    feed_id_set = _feed_ids(fp) if fp else set()
    new_rows: list[dict] = []
    produced = 0
    deduped = 0
    failed = 0
    budget_denied = 0
    errors: list[str] = []
    last_success: str | None = None

    for t in resolved:
        sym, sg, query = t["symbol"], t["subject_guid"], t["query"]
        idem = f"grp|{sym}|{query}|{sha}"
        resp = router.search(
            query,
            kind="web",
            count=3,
            caller="governed_research_producer",
            purpose="wake_research",
            idempotency_key=idem,
            clock=clock,
            root=root,
            transport=transport,
            api_key=api_key,
            enabled=True,
        )
        if not resp.ok:
            failed += 1
            reason = resp.reason or "PROVIDER_ERROR"
            if "BUDGET_REFUSED" in str(reason):
                budget_denied += 1
            errors.append(f"{sym}:{reason}")
            continue

        results = list(resp.results or [])
        if not results:
            # Provider answered but returned nothing → stale-only input; not an
            # object, and not a producer break. Counted as eligible-but-empty.
            continue

        for r in results:
            url = str(r.get("url") or "").strip()
            if not url:
                continue
            title = str(r.get("title") or query)[:400]
            body = str(r.get("description") or "")[:4000]
            ro = build_research_object(
                source_url=url,
                title=title,
                body=body,
                primary_symbol=sym,
                primary_subject_guid=sg,
                published_at="",
                producer="governed_research_producer",
                policy_decisions=["governed_brave_router", "budget_governed"],
                source_sha=sha,
                clock=clock,
                provenance_extra={"trigger": trigger, "reservation_id": resp.reservation_id},
            )
            rid = ro.research_id
            if rid in feed_id_set:
                deduped += 1
                continue
            row = _build_feed_row(ro, symbol=sym, subject_guid=sg, sha=sha, trigger=trigger)
            new_rows.append(row)
            feed_id_set.add(rid)
            produced += 1
            last_success = _iso(now)

    if fp and new_rows:
        _append_feed(fp, new_rows)

    total_rows = len(_load_feed(fp)) if fp else 0
    outcome = "produced" if produced else ("broken" if failed else "nothing_eligible")

    if hp:
        _write_health(
            hp,
            {
                "schema": "GovernedResearchProducerHealth@v1",
                "as_of": _iso(now),
                "outcome": outcome,
                "eligible": len(resolved),
                "produced": produced,
                "deduped": deduped,
                "failed": failed,
                "budget_denied": budget_denied,
                "errors": errors,
                "feed_rows": total_rows,
                "last_success_at": last_success,
                "source_sha": sha,
                "feed_path": str(fp) if fp else None,
            },
        )

    return ProducerResult(
        ok=produced > 0,
        produced=produced,
        deduped=deduped,
        failed=failed,
        budget_denied=budget_denied,
        eligible=len(resolved),
        outcome=outcome,
        errors=errors,
        feed_rows=total_rows,
        feed_latest_at=last_success,
    )


def feed_summary(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Feed count / age / latest row for observability (never mutates)."""
    fp = feed_path(env)
    if not fp:
        return {"schema": SCHEMA, "feed_path": None, "rows": 0, "latest_at": None, "age_seconds": None}
    rows = _load_feed(fp)
    latest: datetime | None = None
    for r in rows:
        ts = r.get("produced_at") or r.get("captured_at") or r.get("published_at")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if latest is None or dt > latest:
                latest = dt
        except Exception:
            continue
    age = (datetime.now(timezone.utc) - latest).total_seconds() if latest else None
    return {
        "schema": SCHEMA,
        "feed_path": str(fp),
        "rows": len(rows),
        "latest_at": _iso(latest) if latest else None,
        "age_seconds": round(age, 1) if age is not None else None,
    }


__all__ = [
    "SCHEMA",
    "FEATURE_FLAG",
    "FEED_ENV",
    "HEALTH_ENV",
    "enabled",
    "source_sha",
    "feed_path",
    "health_path",
    "ProducerResult",
    "produce_research",
    "feed_summary",
]
