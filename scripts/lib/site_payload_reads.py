"""Bounded, read-only list adapters for the Command Center (site audit W2).

No provider, execution engine, subprocess, scheduler trigger or durable write belongs
here. Callers supply existing owner projections/SELECT access; paging never changes
their populations or their truth fields. Offsets always refer to the filtered source.
"""

from __future__ import annotations

import json
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

POLL_BUDGET = 480_000  # leave room for the HTTP response envelope (<500 KB)
CANDIDATE_BUDGET = 190_000  # leave room for the HTTP response envelope (<200 KB)


def value(query, key, default=None):
    v = (query or {}).get(key, default)
    return (v[0] if v else default) if isinstance(v, list) else v


def integer(query, key, default, low=0, high=1_000_000):
    try:
        return min(high, max(low, int(value(query, key, default))))
    except (TypeError, ValueError, OverflowError):
        return default


def window(query):
    return integer(query, "offset", 0), integer(query, "limit", 50, 1, 100)


def _count(row):
    return int(row["n"]) if row is not None and row.get("n") is not None else None


def encoded_size(payload):
    # The server uses the standard encoder (including ASCII escaping and spaces).
    return len(json.dumps(payload, default=str).encode("utf-8"))


def page_rows(payload, key, query=None, *, budget=POLL_BUDGET, total=None, source_offset=0):
    """Page before serialization, retaining global totals and naming oversized rows.

    source_offset lets SELECT-backed adapters pass just the requested SQL window.
    A byte-constrained page advances by the number consumed, never the requested
    limit: no boundary duplicates or skipped ordinary rows when row sizes vary.
    """
    offset, limit = window(query)
    source = payload.get(key) or []
    total = len(source) if total is None else total
    rows = source[max(0, offset - source_offset) : max(0, offset - source_offset) + limit]
    out = {**payload, key: []}
    paging = {
        "offset": offset,
        "limit": limit,
        "total": total,
        "returned": 0,
        "next_offset": None,
        "has_more": offset < total,
        "budget_bytes": budget,
    }
    out["pagination"] = paging
    for row in rows:
        out[key].append(row)
        if encoded_size(out) + 100 > budget:
            out[key].pop()
            if not out[key]:
                # Never fabricate a slim replacement carrying invented financial facts.
                out["payload_gap"] = {
                    "reason": "row_exceeds_payload_budget",
                    "offset": offset,
                    "symbol": row.get("symbol") if isinstance(row, dict) else None,
                }
            break
    returned = len(out[key])
    paging.update(
        returned=returned,
        has_more=offset + returned < total,
        next_offset=offset + returned if returned and offset + returned < total else None,
    )
    if encoded_size(out) > budget:
        # A giant non-row field must not evade the poll budget either.
        return {
            key: [],
            "pagination": {**paging, "returned": 0, "next_offset": None},
            "payload_gap": {"reason": "metadata_exceeds_payload_budget"},
        }
    return out


def _actionable(row):
    if row.get("conflicts") or row.get("classification") == "PENDING":
        return True
    ta, at = row.get("trade_ai") or {}, row.get("active_trader") or {}
    if at.get("session_state") == "CURRENT_SESSION" and at.get("observations"):
        return True
    if ta.get("session_state") == "CURRENT_SESSION" and ta.get("observations"):
        facts = ta["observations"][0].get("setup_evidence") or {}
        return bool(
            facts.get("passed_count")
            or (facts.get("catalyst") or {}).get("text")
            or set(ta.get("verdicts") or ()) & {"GO", "WAIT", "NOGO", "NO_GO", "AVOID", "MANUAL_REVIEW"}
        )
    return False


def candidates_page(payload, query=None):
    rows = payload.get("candidates") or []
    mode = str(value(query, "filter", "ACTIONABLE")).upper()
    cid = value(query, "candidate_id")
    counts = {
        "ALL": len(rows),
        "ACTIONABLE": sum(_actionable(r) for r in rows),
        "CONFLICT": sum(bool(r.get("conflicts")) for r in rows),
        "CURRENT": sum(
            any((r.get(k) or {}).get("session_state") == "CURRENT_SESSION" for k in ("trade_ai", "active_trader"))
            for r in rows
        ),
    }
    if payload.get("candidate_count") is None:
        counts = {k: None for k in counts}
    if value(query, "view") == "summary":
        return page_rows(
            {**payload, "candidates": [], "filter_counts": counts, "projection_mode": "summary"},
            "candidates",
            query,
            budget=CANDIDATE_BUDGET,
        )
    if cid:
        row = next((r for r in rows if r.get("candidate_id") == cid), None)
        if row is None:
            return page_rows(
                {
                    **payload,
                    "candidates": [],
                    "filter_counts": counts,
                    "payload_gap": {"reason": "candidate_not_in_snapshot"},
                },
                "candidates",
                query,
                budget=CANDIDATE_BUDGET,
            )
        source_key = (
            "active_trader"
            if str(value(query, "history_source", "TRADE_AI")).upper() == "ACTIVE_TRADER"
            else "trade_ai"
        )
        detail = {**row}
        for key in ("trade_ai", "active_trader"):
            source = row.get(key) or {}
            detail[key] = {**source, "observations": [], "observation_count": len(source.get("observations") or [])}
        base = {
            **payload,
            "candidates": [detail],
            "filter_counts": counts,
            "history_scope": "paged_source",
            "history_source": source_key.upper(),
        }
        out = page_rows(
            {**base, "_observations": (row.get(source_key) or {}).get("observations") or []},
            "_observations",
            query,
            budget=CANDIDATE_BUDGET - 500,
        )
        if "candidates" not in out:
            return out
        observations = out.pop("_observations")
        detail[source_key]["observations"] = observations
        return out

    def keep(row):
        if mode == "CONFLICT":
            return bool(row.get("conflicts"))
        if mode == "CURRENT":
            return any(
                (row.get(k) or {}).get("session_state") == "CURRENT_SESSION" for k in ("trade_ai", "active_trader")
            )
        return True if mode == "ALL" else _actionable(row)

    selected = []
    for row in rows:
        if not keep(row):
            continue
        r = dict(row)
        for key in ("trade_ai", "active_trader"):
            source = row.get(key) or {}
            obs = source.get("observations") or []
            r[key] = {**source, "observations": obs[:1], "observation_count": len(obs)}
        selected.append(r)
    return page_rows(
        {
            **payload,
            "candidates": selected,
            "filter_counts": counts,
            "filter": mode,
            "history_scope": "latest_observation",
        },
        "candidates",
        query,
        budget=CANDIDATE_BUDGET,
    )


_CANDIDATE_CACHE = {}
_CANDIDATE_LOCK = threading.Lock()


def read_candidates(root, query=None, *, now=None):
    """Read owner snapshots once per file generation, never once per tab/poll."""
    from .scanner_candidate_projection import build_candidate_projection, read_candidate_snapshot

    root = Path(root)
    paths = (root / "data/runtime/trade_ai_cache.json", root / "data/active_trader/momentum_alerts.jsonl")

    def signature(path):
        try:
            s = path.stat()
            return str(path), s.st_mtime_ns, s.st_size, s.st_ino
        except OSError:
            return str(path), None

    # Include the ET date: an unchanged file becomes stale at the session boundary.
    from zoneinfo import ZoneInfo

    now = now or datetime.now(ZoneInfo("America/New_York"))
    key = (now.date().isoformat(), int(now.timestamp()) // 30, *(signature(p) for p in paths))
    with _CANDIDATE_LOCK:
        if _CANDIDATE_CACHE.get("key") != key:
            if not (root / "PERSISTENT_STATE_ROOT.json").is_file():
                data = build_candidate_projection(
                    None, None, now=now, source_status={"TRADE_AI": "UNAVAILABLE", "ACTIVE_TRADER": "UNAVAILABLE"}
                )
            else:
                data = read_candidate_snapshot(*paths, now=now)
            _CANDIDATE_CACHE.update(key=key, data=data)
        return candidates_page(_CANDIDATE_CACHE["data"], query)


def scanner_page(payload, query=None):
    rows = payload.get("tickers") or []
    symbol = str(value(query, "symbol", "")).upper().strip()
    decision = str(value(query, "decision", "")).upper().strip()
    if symbol:
        rows = [r for r in rows if symbol in str(r.get("symbol") or "").upper()]
    if decision:
        rows = [r for r in rows if str(r.get("decision") or "").upper() == decision]
    # ETags for a whole owner snapshot cannot identify differently paged responses.
    out = {k: v for k, v in payload.items() if k != "__etag__"}
    return page_rows({**out, "tickers": rows, "unfiltered_total": len(payload.get("tickers") or [])}, "tickers", query)


def scheduler_page(payload, query=None):
    return page_rows(payload, "rows", query)


def canonical_rows(rows, *, resolver=None, projection=None):
    """One batch GUID read through W1; lower-level opinions remain conflicts."""
    if resolver is None:
        try:
            from .cio_truth import stance_for
            from .data_broker.cio_prospect import get_prospects
            from .data_broker.watch_prospects import _db_query

            resolver = stance_for
            projection = get_prospects(
                db_query=_db_query(), symbols={r.get("security_guid") for r in rows if r.get("security_guid")}
            )
        except (ImportError, OSError, ValueError):
            resolver = lambda guid, **kw: {
                "stance": None,
                "conviction": None,
                "stale": True,
                "gap": {"reason": "Canonical CIO view unavailable"},
            }
    out = []
    from .data_broker.watch_prospects import family

    for row in rows:
        truth = resolver(row.get("security_guid"), projection=projection)
        r = {**row, "conflicts": list(row.get("conflicts") or [])}
        for key in ("stance", "conviction"):
            if (
                not truth.get("gap")
                and row.get(key) is not None
                and truth.get(key) is not None
                and row.get(key) != truth.get(key)
            ):
                r["conflicts"].append(
                    {
                        "kind": f"cio_{key}",
                        "summary": f"Source {key} differs from the CIO record",
                        "a": {"value": truth.get(key), "source": "CIO record", "at": truth.get("as_of")},
                        "b": {
                            "value": row.get(key),
                            "source": row.get("conviction_source") or "source signal",
                            "at": row.get("conviction_as_of"),
                        },
                    }
                )
        for conflict in truth.get("conflicts") or []:
            a, b = conflict.get("source_a") or {}, conflict.get("source_b") or {}
            r["conflicts"].append(
                {
                    "kind": "cio_record_conflict",
                    **({"resolved": True} if conflict.get("resolved") is True else {}),
                    "summary": conflict.get("summary") or conflict.get("label"),
                    "a": {"value": a.get("value"), "source": a.get("source_label"), "at": a.get("as_of")},
                    "b": {"value": b.get("value"), "source": b.get("source_label"), "at": b.get("as_of")},
                }
            )
        r.update(
            stance=truth.get("stance"),
            conviction=truth.get("conviction"),
            stance_family=family(truth.get("stance")),
            conviction_source="cio_truth",
            conviction_as_of=truth.get("as_of"),
            conviction_stale=truth.get("stale", True),
            cio_truth=truth,
            conviction_components_scope="lower_source_factors",
            source_signal={
                "stance": row.get("stance"),
                "conviction": row.get("conviction"),
                "source": row.get("conviction_source"),
                "as_of": row.get("conviction_as_of"),
                "lane": row.get("lane"),
                "stage": row.get("stage"),
                "why": row.get("why"),
                "summary": row.get("summary"),
            },
        )
        if truth.get("gap"):
            r["whats_missing"] = [*(row.get("whats_missing") or []), truth["gap"]["reason"]]
        added = r["conflicts"][len(row.get("conflicts") or []) :]
        unresolved = [c for c, raw in zip(added, _sources(row, truth)) if raw.get("resolved") is not True]
        kind = (row.get("next_action") or {}).get("kind")
        if unresolved:
            r["next_action"] = {
                "kind": "resolve_conflict",
                "label": "Ask the CIO",
                "reason": "Sources disagree with the canonical CIO view; a recorded CIO review is needed.",
            }
        elif truth.get("gap") and kind not in {"protect", "resolve_conflict"}:
            # No CIO stance is a missing view, not a disagreement (batch 31): never labelled as a conflict.
            r["next_action"] = {
                "kind": "cio_missing",
                "label": "Ask the CIO for a view",
                "reason": truth["gap"]["reason"],
                "gap": dict(truth["gap"]),
            }
        if r.get("lane") == "actionable" and r["next_action"].get("kind") in {"resolve_conflict", "cio_missing"}:
            # The source setup is preserved above. Its go lane cannot describe a composed row
            # whose current next step requires a CIO review (operator capture, 2026-10-27).
            r.update(lane="forming", stage="setup_forming", why=f"CIO review required — {r['next_action']['reason']}")
        out.append(r)
    return out


def _sources(row, truth):
    """The raw origin of each conflict canonical_rows appends, in append order (stance/conviction, then record)."""
    out = [
        {}
        for key in ("stance", "conviction")
        if not truth.get("gap")
        if row.get(key) is not None and truth.get(key) is not None and row.get(key) != truth.get(key)
    ]
    return out + [c for c in truth.get("conflicts") or []]


def attach_review_states(rows, *, reader=None):
    """One batch read of each row's CIO review request state (queue + acquisition outcome); read-only.

    An unreadable source is a named gap on the row, never "not requested".
    """
    symbols = sorted({str(r.get("symbol") or "").upper() for r in rows if r.get("symbol")})
    states, gap = {}, None
    if symbols:
        try:
            if reader is None:
                from .symbol_thesis_priority import review_states as reader
            states = reader(symbols)
        except (ImportError, OSError, ValueError) as exc:
            gap = f"Review request state unavailable ({type(exc).__name__})"
    out = []
    for row in rows:
        sym = str(row.get("symbol") or "").upper()
        r = dict(row)
        if sym in states:
            from .data_broker.watch_review_status import presentation_state

            r["review_state"] = presentation_state(states[sym], r.get("cio_truth") or {})
        elif sym:
            r["review_state"] = {
                "status": "unavailable",
                "label": gap or "Review request state unavailable",
                "open": False,
            }
        out.append(r)
    return out


def attach_conflict_sections(rows, *, reader=None, root=None):
    """One accepted W10 batch read; sections are forwarded byte-for-byte in shape.

    This consumer never classifies a value, chooses a headline, changes a finding
    or makes per-row HTTP requests. An unavailable dependency is not "no flags".
    """
    guids = sorted(
        {str(r["security_guid"]) for r in rows if r.get("security_guid") and r.get("identity_status") == "CONFIRMED"}
    )
    sections, gap = {}, None
    if guids:
        try:
            if reader is None:
                from .conflicts.api import sections_for_guids

                reader = sections_for_guids
            if root is None:
                from .lane_registry import state_root

                root = state_root()
            sections = reader(root, guids)
        except (ImportError, OSError, ValueError):
            gap = "Conflict batch reader unavailable"
    out = []
    for row in rows:
        r = dict(row)
        guid = str(row.get("security_guid") or "")
        if guid in sections and row.get("identity_status") == "CONFIRMED":
            r["conflict_section"] = sections[guid]
            r.pop("conflict_section_gap", None)
        else:
            r["conflict_section_gap"] = {"reason": gap or "Confirmed conflict section unavailable for this security"}
        out.append(r)
    return out


def _flagged_name_count(rows):
    if any(
        r.get("conflict_section_gap")
        or not isinstance(r.get("conflict_section"), dict)
        or r["conflict_section"].get("gap")
        for r in rows
    ):
        return None
    return len({r["security_guid"] for r in rows if r["conflict_section"].get("headline")})


def prospects_page(
    payload,
    query=None,
    *,
    stance_resolver=None,
    stance_projection=None,
    section_reader=None,
    section_root=None,
    review_reader=None,
):
    lane = str(value(query, "lane", "actionable"))
    lanes = payload.get("lanes") or []
    if lane not in {r.get("id") for r in lanes}:
        lane = "actionable"
    records = [r for item in lanes for r in item.get("items") or []]
    canonical = canonical_rows(records, resolver=stance_resolver, projection=stance_projection)
    resolved = iter(canonical)
    membership = {}
    out = {**payload, "lanes": [], "conflict_count": None, "conflict_count_scope": "flagged_names_on_page"}
    selected = []
    composed_lanes = [{**item, "items": [next(resolved) for _ in item.get("items") or []]} for item in lanes]
    if any(row.get("lane", item["id"]) != item["id"] for item in composed_lanes for row in item["items"]):
        from .data_broker.watch_prospects import _sort_key

        buckets = {item["id"]: [] for item in composed_lanes}
        deltas = Counter()
        for item in composed_lanes:
            for row in item["items"]:
                target = row.get("lane") if row.get("lane") in buckets else item["id"]
                buckets[target].append(row)
                deltas[item["id"]] -= 1
                deltas[target] += 1
        # Overflow names have no loaded row to validate. Preserve their source assignment
        # and expose that scope instead of claiming a canonical read of unseen records.
        out["lane_membership_unverified"] = {
            item["id"]: list(item["overflow"]) for item in lanes if item.get("overflow")
        }
        out["counts"] = dict(payload.get("counts") or {})
        regrouped = []
        for item in composed_lanes:
            rows = sorted(buckets[item["id"]], key=_sort_key)
            cap = item.get("cap") if isinstance(item.get("cap"), int) else len(rows)
            shown, overflow, system_shown = [], [], 0
            for row in rows:
                if row.get("mine") or system_shown < cap:
                    shown.append(row)
                    system_shown += not bool(row.get("mine"))
                else:
                    overflow.append(row["symbol"])
            count = max(0, item.get("count", len(item["items"]) + len(item.get("overflow") or [])) + deltas[item["id"]])
            out["counts"][item["id"]] = count
            regrouped.append(
                {
                    **item,
                    "items": shown,
                    "count": count,
                    "overflow": list(dict.fromkeys([*(item.get("overflow") or []), *overflow])),
                }
            )
        composed_lanes = regrouped
    from .data_broker.watch_prospects import filter_payload

    out = filter_payload({**out, "lanes": composed_lanes}, query or {})
    composed_lanes, out["lanes"] = out["lanes"], []
    for item in composed_lanes:
        for symbol in [*(r.get("symbol") for r in item["items"]), *(item.get("overflow") or [])]:
            if symbol:
                membership[str(symbol).upper()] = item["id"]
        if item.get("id") == lane:
            selected = item["items"]
        out["lanes"].append({**item, "items": []})
    out["lane_membership"] = membership
    offset, limit = window(query)
    attached = attach_review_states(
        attach_conflict_sections(selected[offset : offset + limit], reader=section_reader, root=section_root),
        reader=review_reader,
    )
    paged = page_rows(
        {**out, "_items": attached},
        "_items",
        query,
        budget=POLL_BUDGET - 1_000,
        total=len(selected),
        source_offset=offset,
    )
    if "lanes" not in paged:
        return {"ok": False, "status": "unavailable", "payload_gap": paged.get("payload_gap")}
    rows = paged.pop("_items")
    paged["conflict_count"] = None if paged.get("payload_gap") else _flagged_name_count(rows)
    for item in paged["lanes"]:
        if item.get("id") == lane:
            item["items"] = rows
            if paged.get("payload_gap"):
                item["payload_gap"] = paged["payload_gap"]
    return paged


def read_curation(
    query=None,
    *,
    stance_resolver=None,
    stance_projection=None,
    section_reader=None,
    section_root=None,
    review_reader=None,
):
    """Validate stages BEFORE ranking so expired names never consume suggestion slots."""
    from .data_broker.watch_prospects import gather
    from .data_broker.watch_curation import build_curation, read_dismissed, eligible_opportunities, my_rows

    g = gather(query or {})
    now = g.get("now") or datetime.now(timezone.utc)
    eligible = eligible_opportunities(g.get("opps") or {}, g["row_for"], now=now)
    dismissed, status = read_dismissed(now=now)
    out = build_curation(g, n=value(query, "n", 20), dismissed=dismissed, dismissed_status=status, filters={}, now=now)
    filtered = build_curation(
        {**g, "opps": eligible},
        n=value(query, "n", 20),
        dismissed=dismissed,
        dismissed_status=status,
        filters={},
        now=now,
    )
    out["suggests"] = filtered["suggests"]
    mine_count = len(out["my_watchlist"]["rows"])
    records = canonical_rows(
        out["my_watchlist"]["rows"] + out["suggests"]["rows"], resolver=stance_resolver, projection=stance_projection
    )
    out["my_watchlist"]["rows"], out["suggests"]["rows"] = records[:mine_count], records[mine_count:]
    mine = out["my_watchlist"]
    from .data_broker import watch_position_facts as wpf

    # Compose first, then filter/facet/sort the operator's complete uncapped list.
    # Filtering the lower source first could both hide matching canonical rows
    # and display a canonical 71 under an "at least 80" filter.
    lookup = {r["symbol"]: r for r in mine.get("rows") or []}
    canonical_mine = my_rows({s: {} for s in lookup}, lookup.__getitem__, g.get("opps") or {})
    active = wpf.active_filters(query or {})
    mine_rows = [r for r in canonical_mine if wpf.passes(r, active, now=now)] if active else canonical_mine
    sort = str(value(query, "sort", ""))
    if sort in wpf.SORTS:
        mine_rows.sort(key=lambda r: (*wpf.sort_key(sort, r, r.get("conviction")), r["symbol"]))
    mine.update(
        rows=mine_rows,
        count=len(mine_rows),
        starred=sum(bool(r.get("starred")) for r in mine_rows),
        filters=active,
        position_facets=wpf.facet_counts(canonical_mine, now=now, filters=active),
    )
    kinds = {"all": len(mine_rows), "starred": sum(bool(r.get("starred")) for r in mine_rows)}
    for row in mine_rows:
        for kind in {m.get("kind") for m in row.get("membership") or [] if m.get("kind")}:
            if kind != "starred":
                kinds[kind] = kinds.get(kind, 0) + 1
    mine["kind_counts"] = kinds
    kind = value(query, "mine", "")
    if kind:
        mine["rows"] = [
            r
            for r in mine_rows
            if (
                r.get("starred") if kind == "starred" else any(m.get("kind") == kind for m in r.get("membership") or [])
            )
        ]
        mine["count"] = len(mine["rows"])
    out["suggests"]["universe_note"] = (
        "Eligible names from the ranked research universe; Prospects shows a capped stage view."
    )
    view = value(query, "view", "both")
    for section in ("my_watchlist", "suggests"):
        data = out[section]
        if view in {"mine", "suggests"} and (view == "mine") != (section == "my_watchlist"):
            out[section] = {k: v for k, v in data.items() if k != "rows"}
            out[section]["rows"] = []
        else:
            out[section] = page_rows(data, "rows", query, budget=210_000)
    emitted = out["my_watchlist"]["rows"] + out["suggests"]["rows"]
    # Only displayed suggestions need this batch. Personal-list market evidence
    # already came from gather; never turn a research universe into N+1 reads.
    if out["suggests"]["rows"] and "market_reader" in g:
        from .data_broker.watch_market_facts import load_snapshot, view

        symbols = [r["symbol"] for r in out["suggests"]["rows"]]
        market = load_snapshot(g["market_reader"], symbols, now=now, cards=g.get("cards"))
        for row in out["suggests"]["rows"]:
            row["market_facts"] = view(market, row["symbol"], now=now)
    attached = attach_review_states(
        attach_conflict_sections(emitted, reader=section_reader, root=section_root), reader=review_reader
    )
    n_mine = len(out["my_watchlist"]["rows"])
    for section, rows in (("my_watchlist", attached[:n_mine]), ("suggests", attached[n_mine:])):
        data = out[section]
        if "pagination" not in data:
            continue
        meta = data["pagination"]
        data = page_rows(
            {**data, "rows": rows}, "rows", query, budget=210_000, total=meta["total"], source_offset=meta["offset"]
        )
        data["conflict_count"] = None if data.get("payload_gap") else _flagged_name_count(data["rows"])
        data["conflict_count_scope"] = "flagged_names_on_page"
        out[section] = data
    if encoded_size(out) > POLL_BUDGET:
        return {
            "schema": out.get("schema"),
            "ok": False,
            "status": "unavailable",
            "payload_gap": {"reason": "metadata_exceeds_payload_budget"},
        }
    return out


WATCHPOOL_CTE = """WITH population AS (
 SELECT DISTINCT ON (sp.symbol, sp.strategy_id, sp.origin_system)
 sp.id, sp.strategy_id, sp.symbol, sp.screener_id, sp.bucket, sp.current_status,
 sp.entered_at, sp.expires_at, sp.origin_system, sp.directive_id, d.label AS directive_label
 FROM strategy_watchpool sp LEFT JOIN watch_directives d ON d.id=sp.directive_id
 ORDER BY sp.symbol, sp.strategy_id, sp.origin_system, sp.entered_at DESC, sp.id DESC
) """


def read_watchpool(query=None, *, db_query, clean=lambda x: x):
    offset, limit = window(query)
    status = str(value(query, "status", "all"))
    counts = db_query(
        WATCHPOOL_CTE
        + "SELECT current_status, COALESCE(origin_system,'screener') AS origin_system, count(*) AS n FROM population GROUP BY 1,2"
    )
    if counts is None:
        return {"rows": [], "count": None, "by_status": {}, "by_origin": {}, "status": "unavailable"}
    by_status, by_origin = Counter(), Counter()
    for row in counts:
        by_status[row.get("current_status") or "?"] += int(row["n"])
        by_origin[row["origin_system"]] += int(row["n"])
    where, params = ("", []) if status == "all" else ("WHERE upper(COALESCE(current_status,'?'))=upper(%s)", [status])
    rows = db_query(
        WATCHPOOL_CTE + f"SELECT * FROM population {where} ORDER BY entered_at DESC, id DESC LIMIT %s OFFSET %s",
        tuple(params + [limit, offset]),
    )
    if rows is None:
        return {"rows": [], "count": None, "status": "unavailable"}
    total = (
        sum(by_status.values())
        if status == "all"
        else sum(n for key, n in by_status.items() if key.upper() == status.upper())
    )
    return page_rows(
        {
            "rows": [{k: clean(v) for k, v in r.items()} for r in rows],
            "count": sum(by_status.values()),
            "by_status": dict(by_status),
            "by_origin": dict(by_origin),
        },
        "rows",
        query,
        total=total,
        source_offset=offset,
    )


def read_broker_list(root, query=None, *, now=None):
    """Serve an exact-query stored list; even refresh=1 cannot start recalibration.

    This adapter never imports the broker/proposal subsystem. Missing and stale
    snapshots are explicit; only the owner lane may refresh their contents.
    """
    now = now or datetime.now(timezone.utc)
    normalized = {
        k: (v[0] if len(v) == 1 else v) if isinstance(v, list) else v
        for k, v in sorted((query or {}).items())
        if k not in {"refresh", "_"}
    }
    key = "v2|" + ("|".join(f"{k}={v}" for k, v in normalized.items()) if normalized else "default")
    try:
        path = Path(root) / "data/runtime/broker_list_cache.json"
        if path.stat().st_size > 2_000_000:
            raise ValueError("oversized_cache")
        blob = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(blob, dict):
            raise ValueError("invalid_cache")
        entry = blob.get(key) or {}
        if not isinstance(entry, dict):
            raise ValueError("invalid_cache_entry")
        data = entry.get("data")
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("proposals"), list)
            or not isinstance(data.get("pagination"), dict)
            or data["pagination"].get("total") is None
        ):
            raise ValueError("snapshot_missing_for_query")
        age = max(0, int(now.timestamp() - float(entry["ts"])))
        out = {
            **data,
            "cached": True,
            "cache_age_sec": age,
            "stale": age > 180,
            "quotes_live": False,
            "refresh_policy": "owner_lane_only",
            "provider_calls": 0,
            "cache_status": "stale" if age > 180 else "fresh",
        }
        if encoded_size(out) > POLL_BUDGET:
            raise ValueError("stored_page_exceeds_payload_budget")
        return out
    except (OSError, ValueError, TypeError, KeyError):
        return {
            "proposals": [],
            "cached": True,
            "stale": True,
            "cache_status": "unavailable",
            "quotes_live": False,
            "provider_calls": 0,
            "refresh_policy": "owner_lane_only",
            "gap_reason": "Stored proposal list unavailable for these filters; owner lane has not published it.",
            "pagination": {"total": None, "page": 1, "page_size": 0, "total_pages": None},
        }


def read_broker_summary(root, *, now=None):
    """The shared chrome also reads a stored summary, never a background warmer."""
    now = now or datetime.now(timezone.utc)
    try:
        path = Path(root) / "data/runtime/broker_list_cache.json"
        if path.stat().st_size > 2_000_000:
            raise ValueError("oversized_cache")
        blob = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(blob, dict):
            raise ValueError("invalid_cache")
        entries = [
            e
            for e in blob.values()
            if isinstance(e, dict)
            and isinstance(e.get("data"), dict)
            and isinstance(e["data"].get("queue_summary"), dict)
        ]
        latest = max(entries, key=lambda e: float(e.get("ts") or 0))
        age = max(0, int(now.timestamp() - float(latest["ts"])))
        summary = {
            **latest["data"]["queue_summary"],
            "cached": True,
            "cache_age_sec": age,
            "stale": age > 180,
            "provider_calls": 0,
            "refresh_policy": "owner_lane_only",
        }
        if encoded_size(summary) <= POLL_BUDGET:
            return summary
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return {
        "total": None,
        "status": "unavailable",
        "cached": True,
        "provider_calls": 0,
        "gap_reason": "Stored queue summary unavailable; owner lane has not published it.",
    }


def read_stored_stops(query=None, *, db_query, clean=lambda x: x, stop_resolver=None, now=None):
    """SELECT the owner's last observations; GET never imports a broker reader.

    A table of positive observations does not prove an account-wide successful
    read. Do not manufacture read-ok accounts from the presence of stop rows.
    """
    rows = db_query("""SELECT broker, account, symbol, order_id,
        order_type, stop_price, qty, status, captured_at, origin
        FROM stop_last_known ORDER BY account, symbol, captured_at DESC, order_id DESC""")
    by_key = {}
    groups = {}
    from .account_display import canonical_key

    if stop_resolver is None:
        try:
            from .cio_truth import stop_for

            stop_resolver = stop_for
        except ImportError:
            rows = None  # no alternate implementation of the CIO stop-state rules
    for row in rows or []:
        account, symbol = canonical_key(row.get("account")), str(row.get("symbol") or "").upper()
        if not account or not symbol:
            continue
        groups.setdefault((account, symbol), []).append(row)
    for (account, symbol), observations in groups.items():
        truth = stop_resolver(account, symbol, broker_rows=observations, now=now)
        by_key[f"{symbol}:{account}"] = {
            **{k: clean(v) for k, v in truth.items()},
            "account": account,
            "status": truth.get("stop_status_raw"),
            "qty": truth.get("stop_qty"),
            "source": "broker",
            "broker_verified": False,
            "fetched_at": truth.get("stop_captured_at"),
            "note": "Last stored broker observation; complete account read not verified by this cache.",
        }
    result = {
        "by_key": by_key,
        "fetched_at": max((str(r.get("fetched_at") or "") for r in by_key.values()), default=None),
        "source": "stop_last_known",
        "cached": True,
        "provider_calls": 0,
        "attempted": False,
        "complete": False,
        "degraded": True,
        "unverified_accounts": ["*"],
        "broker_stop_read_ok_accounts": [],
        "successful_accounts": [],
        "cache_status": "stored_observations" if rows is not None else "unavailable",
        "refresh_policy": "owner_lane_only",
        "broker_stop_count": len(by_key) if rows is not None else None,
        "broker_stop_count_scope": "stored_observation_positions",
        "safe_error_code": "cached_account_coverage_unverified",
        "safe_error_summary": "Showing stored stops; account-wide coverage comes from the owner lane receipt.",
    }
    if encoded_size(result) > POLL_BUDGET:
        result.update(by_key={}, cache_status="unavailable", safe_error_code="cached_stops_exceed_payload_budget")
    return result


def read_comms_retention(*, db_query):
    """Aggregate the retained ledger, independent of the last Events page visited."""
    rows = db_query("""SELECT COALESCE(retention_class,'unknown') AS retention_class,
        COALESCE(knowledge_status,'none') AS knowledge_status, count(*) AS n
        FROM communication_events GROUP BY 1,2""")
    by_class, by_knowledge = Counter(), Counter()
    for row in rows or []:
        by_class[row["retention_class"]] += int(row["n"])
        by_knowledge[row["knowledge_status"]] += int(row["n"])
    from .comms.classify import categories

    return {
        "status": "ok" if rows is not None else "unavailable",
        "scope": "all_retained_ledger_rows",
        "byClass": dict(by_class),
        "byKnowledge": dict(by_knowledge),
        "total": sum(by_class.values()) if rows is not None else None,
        "categories": categories(),
    }


def read_hermes_findings(query=None, *, db_query, clean=lambda x: x):
    """SQL paging and full-population counts; embeddings do not duplicate findings."""
    offset, limit = window(query)
    status = str(value(query, "status", "all"))
    where, params = ("", []) if status == "all" else ("WHERE r.status=%s", [status])
    embedded = (
        "EXISTS (SELECT 1 FROM content_embeddings ce WHERE ce.source_type='hermes_research' AND ce.source_id=r.id)"
    )
    total = db_query(
        f"""SELECT count(*) AS total,
        count(*) FILTER (WHERE r.status='promoted') AS promoted,
        count(*) FILTER (WHERE r.status='staged') AS staged,
        count(*) FILTER (WHERE {embedded}) AS embedded
        FROM hermes_research_intelligence r {where}""",
        tuple(params),
        fetch="one",
    )
    if total is None:
        return {"ok": False, "rows": [], "total": None, "status": "unavailable"}
    rows = db_query(
        f"""SELECT r.id,r.hermes_agent_name,r.research_type,r.symbol,r.topic,
        LEFT(r.summary,500) AS summary, LEFT(r.thesis,300) AS thesis,r.confidence_score,
        r.status,r.freshness_date,r.model_used,r.created_at,{embedded} AS embedded
        FROM hermes_research_intelligence r {where}
        ORDER BY r.created_at DESC,r.id DESC LIMIT %s OFFSET %s""",
        tuple(params + [limit, offset]),
    )
    if rows is None:
        return {"ok": False, "rows": [], "total": None, "status": "unavailable"}
    audit_offset = integer(query, "audit_offset", 0)
    audit_total = db_query("SELECT count(*) AS n FROM hermes_promotion_audit", fetch="one")
    audit = db_query(
        """SELECT source_id,target_table,promoted_at FROM hermes_promotion_audit
        ORDER BY promoted_at DESC,source_id DESC LIMIT %s OFFSET %s""",
        (50, audit_offset),
    )
    audit_page = (
        page_rows(
            {"audit": [{k: clean(v) for k, v in r.items()} for r in audit]},
            "audit",
            {"offset": audit_offset, "limit": 50},
            total=int(audit_total["n"]),
            source_offset=audit_offset,
            budget=40_000,
        )
        if audit is not None and audit_total is not None
        else {
            "audit": [],
            "pagination": {
                "offset": audit_offset,
                "limit": 50,
                "returned": 0,
                "total": None,
                "has_more": False,
                "next_offset": None,
            },
        }
    )
    return page_rows(
        {
            "ok": True,
            "rows": [{k: clean(v) for k, v in r.items()} for r in rows],
            **total,
            "audit": audit_page["audit"],
            "audit_pagination": audit_page["pagination"],
            "audit_status": "ok" if audit is not None and audit_total is not None else "unavailable",
        },
        "rows",
        query,
        total=int(total["total"]),
        source_offset=offset,
    )


def bounded_routes(*, root, db_query, clean, scanner, evidence_packet):
    """Only registration here; owner readers run lazily on their GET request.

    API owner installs with one ROUTES.update hunk. root is a callable resolving
    the canonical state root, so import/registration never reads a store.
    """

    def broker_list(query=None):
        out = read_broker_list(root(), query)
        if out.get("cache_status") == "unavailable":
            # The existing queue has an HTTP error state; an empty 200 is read as
            # "nothing queued". Keep the last-good list and show the actual gap.
            raise RuntimeError(out["gap_reason"])
        return out

    return {
        "/api/v2/trade-ai/candidates": lambda q=None: read_candidates(root(), q),
        "/api/v2/trade-ai/scanner": lambda q=None: scanner_page(scanner(), q),
        "/api/v2/watchpool": lambda q=None: read_watchpool(q, db_query=db_query, clean=clean),
        "/api/v2/watch-directives": lambda q=None: read_watch_directives(
            q, db_query=db_query, clean=clean, root=root()
        ),
        "/api/v2/holdings/live-stops": lambda q=None: read_stored_stops(q, db_query=db_query, clean=clean),
        "/api/v2/broker-proposals": broker_list,
        "/api/v2/broker-proposals/summary": lambda q=None: read_broker_summary(root()),
        "/api/v2/hermes/intelligence": lambda q=None: read_hermes_findings(q, db_query=db_query, clean=clean),
        "/api/v2/hermes/research": lambda q=None: read_hermes_findings(q, db_query=db_query, clean=clean),
        "/api/v2/hermes/research-backlog": lambda q=None: read_hermes_backlog(
            q, db_query=db_query, clean=clean, evidence_packet=evidence_packet
        ),
        "/api/v2/communications/retention-summary": lambda q=None: read_comms_retention(db_query=db_query),
    }


def read_watch_directives(query=None, *, db_query, clean=lambda x: x, root, now=None):
    """GET /api/v2/watch-directives — operator watch directives + recent hits + Hermes staging (read-only)."""
    _db_query, _json_clean, PROJECT_ROOT = db_query, clean, Path(root)
    clock = now or datetime.now(timezone.utc)
    offset, limit = window(query)
    totals = _db_query(
        "SELECT count(*) AS total, count(*) FILTER (WHERE status='proposed') AS proposed FROM watch_directives",
        fetch="one",
    )
    if totals is None:
        return {"directives": [], "directive_count": None, "status": "unavailable"}
    directives = (
        _db_query(
            """SELECT id, kind, label, status, priority, trade_ai_enabled, hermes_enabled,
                              last_serviced_at, created_at, spec, created_by, rationale, ttl_days,
                              CASE WHEN ttl_days IS NOT NULL
                                   THEN ttl_days - extract(days FROM now() - created_at)::int
                              END AS expires_in_days
                              FROM watch_directives ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s""",
            (limit, offset),
        )
        or []
    )
    hits = (
        _db_query("""SELECT h.directive_id, d.label, h.symbol, h.surfaced_by, h.divergence, h.promotion_status,
                        h.surfaced_at FROM watch_directive_hits h JOIN watch_directives d ON d.id=h.directive_id
                        ORDER BY h.surfaced_at DESC, h.id DESC LIMIT 40""")
        or []
    )
    # Dedicated desk-suggestions inbox (not drowned by Hermes volume in recent_hits)
    desk_suggestions = (
        _db_query("""
        SELECT h.id AS hit_id, h.directive_id, d.label, d.created_by, h.symbol, h.surfaced_by,
               h.divergence, h.promotion_status, h.hit_reason, h.surfaced_at
        FROM watch_directive_hits h
        JOIN watch_directives d ON d.id = h.directive_id
        WHERE h.promotion_status = 'STAGED_FOR_REVIEW'
          AND h.surfaced_by IN ('cio','advisory','defense','rotation','reentry')
          AND h.surfaced_at > now() - interval '7 days'
        ORDER BY h.surfaced_at DESC
        LIMIT 40
    """)
        or []
    )
    # Per-directive surfaced symbols (fix 2026-06-19): trend/sector directives link items via hits, NOT
    # by setting directive_id on the item — so the Watchlist directive filter must match on these symbols.
    _hs = (
        _db_query("""SELECT directive_id, (array_agg(DISTINCT upper(symbol)))[1:20] syms,
                              count(*) hit_count,
                              count(*) FILTER (WHERE promotion_status='STAGED_FOR_REVIEW') staged_count,
                              max(surfaced_at) AS last_hit_at,
                              count(*) FILTER (WHERE surfaced_at > now() - interval '7 days')  AS hits_7d,
                              count(*) FILTER (WHERE surfaced_at > now() - interval '30 days') AS hits_30d
                       FROM watch_directive_hits GROUP BY directive_id""")
        or []
    )
    # Watch Desk v2 (B3): 8-week hit sparkline per directive (one grouped query)
    _spark_rows = (
        _db_query("""SELECT directive_id, (extract(days from now() - surfaced_at)::int / 7) AS wk, count(*) AS n
                               FROM watch_directive_hits
                               WHERE surfaced_at > now() - interval '56 days'
                               GROUP BY 1, 2""")
        or []
    )
    _spark: dict = {}
    for r in _spark_rows:
        _spark.setdefault(r["directive_id"], [0] * 8)
        wk = int(r["wk"])
        if 0 <= wk < 8:
            _spark[r["directive_id"]][7 - wk] = r["n"]
    _hit_meta = {r["directive_id"]: r for r in _hs}
    # Watch Desk v3 (A3): per-directive outcome evidence from the source scoreboard —
    # the input the 150-cap and Sunday hygiene were missing (cull by evidence)
    _score_meta = {}
    try:
        from lib.data_broker.watch_discovery import directive_score_meta as _brk_wd_score

        _score_meta = _brk_wd_score(_db_query)  # Phase 4: dead feed read via projection
    except Exception:
        _score_meta = {}
    _hit_sym_map = {r["directive_id"]: (r["syms"] or []) for r in _hs}
    # Per-directive TOTAL counts (fix 2026-06-19): the chip count must come from here, NOT from the global
    # recent_hits feed below — that feed is LIMIT 40 (most-recent activity), so older/ticker-tag hits fall
    # out of the window and the chip wrongly shows "0 hits" for a directive that did surface symbols.
    _hit_cnt = {r["directive_id"]: (r["hit_count"], r["staged_count"]) for r in _hs}
    staging = (
        _db_query(
            "SELECT count(*) c, count(*) FILTER (WHERE NOT drained) undrained FROM hermes_directive_hits_staging",
            fetch="one",
        )
        or {}
    )
    promoted = _db_query("SELECT count(*) c FROM watchlist_items WHERE source='operator_directive'", fetch="one") or {}
    health = {}
    try:
        import json as _jw

        _h = _jw.loads((PROJECT_ROOT / "data" / "runtime" / "watch_directives_history.json").read_text()).get(
            "snapshots", []
        )
        if _h:
            _l = _h[-1]
            health = {
                "status": _l.get("status"),
                "hits_24h": _l.get("hits_24h"),
                "by_status_24h": _l.get("by_status_24h"),
                "by_surfaced_24h": _l.get("by_surfaced_24h"),
                "promoted_total": _l.get("promoted_total"),
                "staging_undrained": _l.get("staging_undrained"),
                "stale_directives": _l.get("stale_directives"),
                "notes": _l.get("notes", []),
                "trend": [
                    {"date": s["date"], "hits_7d": s.get("hits_7d"), "promoted_total": s.get("promoted_total")}
                    for s in _h[-14:]
                ],
            }
    except Exception:
        pass
    critique_summary = {}
    critique_snapshot_at = None
    try:
        import sys as _sysc2

        _sysc2.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from research_critique_pipeline import load_critique_snapshot, extract_critique_fields

        _critique_snap = load_critique_snapshot()
        critique_summary = _critique_snap.get("summary") or {}
        critique_snapshot_at = _critique_snap.get("updated_at")
        _extract = extract_critique_fields
    except Exception:
        _extract = lambda _s: {}

    result = {
        "note": "Operator-owned watch directives honored by Trade AI + Hermes (firewall: Hermes proposes via "
        "staging only). Advisory; no GO/WAIT or scoring change.",
        "critique_summary": {k: _json_clean(v) for k, v in critique_summary.items()},
        "critique_snapshot_at": critique_snapshot_at,
        "directive_count": int(totals.get("total") or 0),
        # surface the spec context (gap_type/sleeve/symbol) + created_by so the Watchpool can label
        # rotate-gap directives instead of showing them as generic ticker directives (operator 2026-06-19)
        # Watch Desk v2 (B3+E): reviewable rows — age/last-hit/7d/30d/sparkline —
        # with the LIST payload slimmed (full spec/rationale only behind ?full=1;
        # the list was 793 KB of specs nobody reads in a table)
        "directives": [
            {
                **{
                    k: _json_clean(v)
                    for k, v in r.items()
                    if (query or {}).get("full") or k not in ("spec", "rationale")
                },
                "symbol": (r.get("spec") or {}).get("symbol"),
                "gap_type": (r.get("spec") or {}).get("gap_type"),
                "sleeve": (r.get("spec") or {}).get("sleeve"),
                "aliases_n": len((r.get("spec") or {}).get("aliases") or []),
                "rationale_short": (str(r.get("rationale") or "")[:160] or None),
                "critique": {k: _json_clean(v) for k, v in _extract(r.get("spec") or {}).items()},
                "hit_symbols": _hit_sym_map.get(r["id"], [])[:20],
                "hit_count": _hit_cnt.get(r["id"], (0, 0))[0],
                "staged_count": _hit_cnt.get(r["id"], (0, 0))[1],
                "last_hit_at": _json_clean((_hit_meta.get(r["id"]) or {}).get("last_hit_at")),
                "hits_7d": (_hit_meta.get(r["id"]) or {}).get("hits_7d") or 0,
                "hits_30d": (_hit_meta.get(r["id"]) or {}).get("hits_30d") or 0,
                "spark_8w": _spark.get(r["id"], [0] * 8),
                "alpha_21d_median": _json_clean((_score_meta.get(r["id"]) or {}).get("alpha_21d_median")),
                "alpha_n": (_score_meta.get(r["id"]) or {}).get("scored") or 0,
                "conv_pct": _json_clean(
                    round(
                        100.0
                        * (_score_meta.get(r["id"]) or {}).get("proposed_n", 0)
                        / max(1, (_score_meta.get(r["id"]) or {}).get("events") or 1),
                        1,
                    )
                    if _score_meta.get(r["id"])
                    else None
                ),
                "age_days": _json_clean(
                    (clock - r["created_at"]).days
                    if r.get("created_at") is not None and hasattr(r.get("created_at"), "year")
                    else None
                ),
            }
            for r in directives
        ],
        "proposed_count": int(totals.get("proposed") or 0),
        "recent_hits": [{k: _json_clean(v) for k, v in r.items()} for r in hits],
        "desk_suggestions": [{k: _json_clean(v) for k, v in r.items()} for r in desk_suggestions],
        "desk_suggestions_count": _count(
            _db_query(
                "SELECT count(*) AS n FROM watch_directive_hits WHERE promotion_status='STAGED_FOR_REVIEW' AND surfaced_by IN ('cio','advisory','defense','rotation','reentry') AND surfaced_at > now() - interval '7 days'",
                fetch="one",
            )
        ),
        "recent_hits_count": _count(_db_query("SELECT count(*) AS n FROM watch_directive_hits", fetch="one")),
        "hermes_staging": {"total": staging.get("c"), "undrained": staging.get("undrained")},
        "promoted_to_watchlist": promoted.get("c"),
        "health": health,
    }
    return page_rows(result, "directives", query, total=int(totals.get("total") or 0), source_offset=offset)


def read_hermes_backlog(query=None, *, db_query, evidence_packet, clean=lambda x: x):
    """GET /api/v2/hermes/research-backlog — read-only research backlog items.

    Query: status=active (default, excludes archived) | staged | archived | all
    """
    _db_query, _evidence_packet, _json_clean = db_query, evidence_packet, clean
    offset, limit = window(query)
    qs = {k: value(query, k) for k in query or {}}
    status_f = (qs.get("status") or "active").strip().lower()
    where = ["research_type = 'research_backlog'"]
    params: list = []
    if status_f == "active":
        where.append("status <> 'archived'")
    elif status_f in ("staged", "archived", "promoted", "embedded"):
        where.append("status = %s")
        params.append(status_f)
    totals = _db_query(
        f"SELECT count(*) AS n FROM hermes_research_intelligence WHERE {' AND '.join(where)}",
        tuple(params),
        fetch="one",
    )
    # status=all → no extra filter
    rows = (
        _db_query(
            f"""
        SELECT id, symbol, topic, LEFT(summary, 400) AS summary, confidence_score,
               status, evidence_json, source_urls_json, created_at
        FROM hermes_research_intelligence
        WHERE {" AND ".join(where)}
        ORDER BY created_at DESC, id DESC
        LIMIT %s OFFSET %s
    """,
            params=tuple(params + [limit, offset]),
        )
        or []
    )
    items = []
    for r in rows:
        ej = r.get("evidence_json") or []
        if isinstance(ej, str):
            import json as _jrb

            try:
                ej = _jrb.loads(ej)
            except Exception:
                ej = []
        meta = ej[0] if ej else {}
        _hep = _evidence_packet(meta if isinstance(meta, dict) else ej)
        items.append(
            {
                "id": r["id"],
                "symbol": r.get("symbol"),
                "topic": r.get("topic", ""),
                "summary": r.get("summary", ""),
                "confidence_score": r.get("confidence_score"),
                "status": r.get("status"),
                "priority": meta.get("priority", "unknown"),
                "owner_agent": meta.get("owner_agent", "unknown"),
                "backlog_type": meta.get("backlog_type", "unknown"),
                "created_at": _json_clean(r.get("created_at")),
                "evidence": _hep.get("evidence") or [],
                "data_i_doubt": _hep.get("data_i_doubt"),
                "agent_contract": _hep.get("agent_contract"),
            }
        )
    result = {
        "ok": totals is not None,
        "items": items,
        "total": int(totals["n"]) if totals else None,
        "advisory_notice": "Research Backlog — Advisory Only — Not Execution — No Autonomous Research",
    }
    return (
        page_rows(result, "items", query, total=result["total"], source_offset=offset) if totals is not None else result
    )
