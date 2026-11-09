"""Read-only projection of saved CIO InstrumentRecord research, keyed by GUID.

No Watch cache is a company-fact authority. No HTTP reader joins upstream sources.
"""
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timedelta, timezone
from copy import deepcopy
import threading
from scripts.lib.cio_company_facts import missing, public_research, timestamp
from scripts.lib import cio_company_quality as quality


# The InstrumentRecord store is one append-only JSONL of ~400 MB. Re-parsing it on every
# request made /api/v2/portfolio/holdings take 4.5 s in resolve alone, 4.2 s of it here
# (LQ-20261107-201, cProfile 2026-11-07: 41,809 json.loads per call). The snapshot is
# memoised per store file and recomputed whenever the file's identity, size or mtime
# changes, so an append is always seen. Each caller gets its own deep copy (~0.1 s).
#
# LQ-20261107-1580: every append to that store invalidates the memo, and the rebuild is
# the expensive step — 4.7 s on an idle host, and 93–175 s on 2026-11-09 while the unit sat
# at memory.high and the kernel reclaimed the build as fast as it allocated (memory.events
# high=23,781). This lock used to be held across the whole rebuild *and* the per-caller deep
# copy, so every reader of company facts queued behind it: /api/v2/cio/pages took 174.7 s
# and /api/v2/overview — which resolves the same snapshot — outlived the browser's 30 s
# abort. Now the rebuild is serialised per store file, the deep copy happens outside any
# lock, and a caller that finds a rebuild already running waits at most _SNAPSHOT_WAIT_S and
# is then served the previous snapshot instead of queueing. A rebuild that finishes inside
# that window — every rebuild on a healthy host — is still seen by every caller, so the
# "an append is always seen" contract holds everywhere except a caller that arrived while a
# *slow* rebuild was in flight; it sees the append on its next call, and the snapshot it got
# meanwhile was built from the same file a moment earlier rather than being an empty answer.
_SNAPSHOT_MEMO: dict[str, tuple[tuple, dict]] = {}          # store path -> (signature, snapshot)
_SNAPSHOT_LOCKS: dict[str, threading.Lock] = {}             # store path -> its one builder
_SNAPSHOT_LOCK = threading.Lock()                           # guards _SNAPSHOT_LOCKS only
_SNAPSHOT_WAIT_S = 2.0


def _file_signature(path: Path) -> tuple | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)


def _build_lock(key: str) -> threading.Lock:
    with _SNAPSHOT_LOCK:
        lock = _SNAPSHOT_LOCKS.get(key)
        if lock is None:
            lock = _SNAPSHOT_LOCKS[key] = threading.Lock()
        return lock


def load_snapshot(root: Path | str | None = None, *, records: list[dict] | None = None) -> dict:
    if records is not None:
        return _build_snapshot(records)
    from scripts.lib.cio_instrument_record import _store_for_root
    store = _store_for_root(root)
    key = str(store.path)
    sig = _file_signature(store.path)
    hit = _SNAPSHOT_MEMO.get(key)
    if sig is not None and hit is not None and hit[0] == sig:
        return deepcopy(hit[1])
    lock = _build_lock(key)
    if not lock.acquire(timeout=_SNAPSHOT_WAIT_S):
        # Another caller is rebuilding this store. Serve what we last published rather than
        # queue behind work whose duration is not ours to bound (see the note above).
        prev = _SNAPSHOT_MEMO.get(key)
        if prev is not None:
            return deepcopy(prev[1])
        lock.acquire()
    try:
        sig = _file_signature(store.path)
        hit = _SNAPSHOT_MEMO.get(key)
        if sig is not None and hit is not None and hit[0] == sig:
            snap = hit[1]          # the builder we waited for already published this signature
        else:
            snap = _build_snapshot(store.all())
            # Only memoise when the file did not change while it was read.
            if sig is not None and _file_signature(store.path) == sig:
                _SNAPSHOT_MEMO[key] = (sig, snap)
            else:
                _SNAPSHOT_MEMO.pop(key, None)
    finally:
        lock.release()
    # The per-caller copy is ~0.1 s and ~100 MB on the production store; keep it outside the
    # build lock so one reader's copy cannot stall the next reader's rebuild.
    return deepcopy(snap)


def _build_snapshot(records: list[dict]) -> dict:
    from scripts.lib.cio_instrument_record import select_canonical_record
    grouped: dict[str, list[dict]] = {}
    for r in records:
        if r.get("security_guid"):
            grouped.setdefault(str(r["security_guid"]), []).append(r)
    out: dict[str, dict] = {}
    for guid, rs in grouped.items():
        canonical, violation = select_canonical_record(rs)
        if violation:
            # Two judged prospects (e.g. HELD + WATCH) is a judgment conflict, not a facts conflict.
            # Company facts are not judgments and live on the fact-only SECURITY record by design, so
            # still render them from there; the review lifecycle keeps the violation visible.
            # (2026-11-06: this dropped ~$267k of direct stocks from Look-through/Allocation.)
            out[guid] = {
                "company_facts": _fact_only_facts(rs, guid) or missing("", guid, violation),
                "review_lifecycle": {"status": "MISSING", "missing_reason": violation},
            }
            continue
        out[guid] = public_research(_with_facts_fallback(canonical, rs, guid), guid)
    return out


def _fact_only_facts(records: list[dict], guid: str) -> dict | None:
    """Available company facts from exactly one fact-only record for this GUID, else None."""
    from scripts.lib.cio_instrument_record import is_fact_only_record
    found = [public_research(r, guid)["company_facts"] for r in records if is_fact_only_record(r)]
    found = [f for f in found if f.get("status") != "MISSING"]
    return found[0] if len(found) == 1 else None


def _with_facts_fallback(canonical: dict, records: list[dict], guid: str) -> dict:
    """Render company facts even when the canonical (judged prospect) record lacks them.

    The fact-only SECURITY record is the designed home of ``research.company_facts``
    (2026-10-24 design). If the canonical record carries no facts but a sibling fact-only
    record does, surface the sibling's facts instead of silently dropping them.
    """
    if _public_facts_status(public_research(canonical, guid)) != "MISSING":
        return canonical
    for r in records:
        if r is canonical:
            continue
        sibling = public_research(r, guid)
        if _public_facts_status(sibling) != "MISSING":
            merged = dict(canonical)
            merged["research"] = {
                **(canonical.get("research") or {}),
                "company_facts": sibling["company_facts"],
            }
            return merged
    return canonical


def _public_facts_status(rendered: dict) -> str | None:
    return ((rendered or {}).get("company_facts") or {}).get("status")


def for_security(snapshot: dict, symbol: str, security_guid: str | None, *, now=None) -> dict:
    out = deepcopy(snapshot.get(str(security_guid)) or {
        "company_facts": missing(symbol, security_guid, "cio_record_missing" if security_guid else "identity_unresolved"),
        "review_lifecycle": {"status": "MISSING", "missing_reason": "cio_record_missing"}})
    facts = out["company_facts"]
    catalyst = facts.get("catalyst") or {}
    ref = now or datetime.now(timezone.utc)
    _legacy_quality(facts, symbol)
    if catalyst.get("status") == "CURRENT" and catalyst.get("catalyst_class") == quality.UPCOMING:
        # A scheduled event is current until its date passes, not for 30 days after it was published.
        when = quality.parse_when(catalyst.get("event_at"))
        if not when or when.date() < ref.date():
            catalyst.update(status="STALE", missing_reason="scheduled_event_date_passed")
        return out
    at = timestamp(catalyst.get("published_at")) or timestamp(catalyst.get("observed_at"))
    if catalyst.get("status") == "CURRENT" and (not at or not ref - timedelta(days=30) <= at <= ref):
        catalyst.update(status="STALE", missing_reason="catalyst_outside_30_day_window")
    return out


def _legacy_quality(facts: dict, symbol: str) -> None:
    """Records written before the C1 quality rules carry no display name, date or class. The read projection
    applies the same reviewed rules to what is stored (no new evidence, no provider): a display name derived
    from the stored registered name/description, the stored event's own date, and a stored non-catalyst
    (price prediction, insider trade ...) shown as None on file until the next populate pass rewrites it."""
    company = facts.get("company")
    if isinstance(company, dict) and company.get("value") and not company.get("display_name"):
        company.update(quality.display_name(symbol or str(facts.get("symbol") or ""), company.get("value"),
                                            description=(facts.get("description") or {}).get("value")))
    cat = facts.get("catalyst")
    if not isinstance(cat, dict) or cat.get("status") != "CURRENT" or cat.get("catalyst_class"):
        return
    names = [n for n in ((company or {}).get("display_name"), (company or {}).get("value")) if n]
    verdict = quality.classify(cat, symbol=symbol or str(facts.get("symbol") or ""), names=names)
    day, kind = quality.fact_date(cat)
    cat.update(date=day, date_kind=kind, source_label=quality.source_label(cat))
    if verdict["class"] == quality.NEWS:
        facts.setdefault("recent_news", [{"headline": cat.get("headline"), "date": day, "date_kind": kind,
                                          "source_label": cat.get("source_label"), "feed": cat.get("feed"),
                                          "url": cat.get("url"), "not_catalyst_reason": verdict["reason"]}])
        cat.update(status="NONE_ON_FILE", headline=None, missing_reason="stored_catalyst_fails_quality_rules",
                   reason=f"Stored headline is news, not a catalyst ({str(verdict['reason']).replace('_', ' ')}).")
    else:
        cat.update(catalyst_class=verdict["class"], event_type=verdict["event_type"])
