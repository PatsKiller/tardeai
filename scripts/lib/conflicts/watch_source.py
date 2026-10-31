"""Read-only Watch/CIO card source for the conflict resolver (gap (g), 2026-10-25). Stored state only.

The resolver used to compose the Watch universe exactly as the served Watch page does
(data_broker.watch_intelligence.compose_universe -> watchlist_intelligence.list_intelligence ->
rockville.live_projection -> shadow_decision_service / decision_action_policy, plus watch_decision.reentry_rows ->
reentry_decision_desk.build_decision_desk). That path recomputes live projections, can fetch quotes, rewrites the
re-entry snapshot and statically reaches broker transports, order verbs and the stance-review notifier (the
reviewed DD01 / AGENTS.md 23.3 exception rows of #2111).

This module is the pure reader that replaces it. It reads, and only reads:
  * membership: operator_starred_symbols, watchlist_items, watch_directives, watchlist_events, screener_find_pins
    (the same SELECTs as data_broker.watch_domains membership_* and watch_intelligence._universe_symbols)
  * the CIO watch review: data/runtime/watchlist_intelligence/{artifacts,quarantine}/<SYM>_*.json, authorized
    exactly as watch_domains.authorize_review_artifact (provenance fields + llm_consumption_log link)
  * desk synthesis: the latest non-superseded watchlist_final_synthesis row (raw, with its time: R1 judges age)
  * Trade AI: the latest live decision_packets row, projected by the pure rockville.decision_projection with the
    packet's STORED action policy (no live re-evaluation), current holdings first
  * re-entry desk: the stored snapshot data/runtime/reentry_decision_desk_latest.json (never rebuilt here)
Database access is an injected ``query(sql, params) -> rows`` callable; ``readonly_query`` opens a read-only
session (default_transaction_read_only) with the DB_* names only. No broker, order, notifier or model import:
tests/test_conflict_watch_source_20261025.py proves the transitive closure with the DD01 audit.
"""
from __future__ import annotations

import ast
from datetime import datetime
from functools import lru_cache
import json
import os
from pathlib import Path

SCHEMA = "WatchConflictSource@v1"
NO_CONSUMER_REASON = ("read-only Watch source for scripts/conflict_resolver.py collect_inputs; the runner swap is "
                      "held for the conflict-producers-a claim on that file (docs/ops/CONFLICT_GOLDEN_REPLAY_20261025.md)")
ROOT = Path(__file__).resolve().parents[3]
REVIEW_AGENT = "cio"
_DB_NAMES = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")
# watch_domains.authorize_review_artifact: real authorization + provenance, never operator_approved=true.
_AUTH_REQUIRED = ("process_id", "provider", "model", "provider_request_id", "input_hash", "artifact_id",
                  "artifact_hash", "started_at", "completed_at", "requested_policy", "executed_policy")
_OPERATOR_READS = (
    ("starred", "SELECT upper(symbol) AS s, starred_at AS at FROM operator_starred_symbols"),
    ("personal_watchlist", "SELECT upper(symbol) AS s, min(first_seen_at) AS at FROM watchlist_items "
                           "WHERE status IN ('active','researched') AND source = 'personal_watchlist' GROUP BY 1"),
    ("directive", "SELECT upper(spec->>'symbol') AS s, created_at AS at FROM watch_directives WHERE kind = 'ticker' "
                  "AND status = 'active' AND created_by = 'operator' AND coalesce(spec->>'symbol', '') <> ''"),
    ("operator_added", "SELECT upper(symbol) AS s, min(first_seen_at) AS at FROM watchlist_items "
                       "WHERE status IN ('active','researched') AND source <> 'personal_watchlist' "
                       "AND (origin_system = 'operator' OR source = 'operator') GROUP BY 1"),
)


def readonly_query():
    """A SELECT-only callable over a read-only PostgreSQL session (psycopg2 imported lazily)."""
    if not os.getenv("DB_PASSWORD"):
        from scripts.lib.env_bootstrap import load_env
        load_env(names=_DB_NAMES)
    import psycopg2
    import psycopg2.extras
    conn = psycopg2.connect(host=os.getenv("DB_HOST", "localhost"), port=int(os.getenv("DB_PORT", "5432")),
                            dbname=os.getenv("DB_NAME", "trade_ai"), user=os.getenv("DB_USER", "trade_ai"),
                            password=os.getenv("DB_PASSWORD", ""), connect_timeout=10,
                            application_name="conflict_watch_source",
                            options="-c default_transaction_read_only=on -c statement_timeout=60000")
    conn.set_session(readonly=True, autocommit=True)

    def query(sql, params=None):
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or ())
            return [dict(row) for row in cur.fetchall() or []]
    query.close = conn.close
    return query


def _get(row, key, index):
    return row.get(key) if hasattr(row, "get") else row[index]


def _iso(value):
    if value is None or value == "":
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _at(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else None


def looks_like_cusip(symbol: str) -> bool:
    """Same filter as watch_intelligence._universe_symbols (9-char alphanumeric settlement ids)."""
    return len(symbol) == 9 and symbol.isalnum() and not any(c in symbol for c in (".", "-", "/", "^", " "))


@lru_cache(maxsize=1)
def default_priority() -> tuple[str, ...]:
    """watchlist_intelligence.DEFAULT_PRIORITY, read from its source without importing that module."""
    tree = ast.parse((ROOT / "scripts/lib/watchlist_intelligence.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "DEFAULT_PRIORITY" for t in node.targets):
            return tuple(ast.literal_eval(node.value))
    raise ValueError("DEFAULT_PRIORITY not found in scripts/lib/watchlist_intelligence.py")


def _symbols(rows):
    return {str(_get(r, "s", 0) or "").strip().upper() for r in rows or []} - {""}


def operator_names(query, sources):
    """watch_domains.membership_operator: the four operator sources minus names removed after their last reason."""
    names: dict[str, list] = {}
    for kind, sql in _OPERATOR_READS:
        try:
            rows = query(sql) or []
        except Exception as exc:  # noqa: BLE001 - one source failing never empties the others
            sources[f"operator:{kind}"] = {"status": "error", "error": type(exc).__name__}
            continue
        for row in rows:
            symbol = str(_get(row, "s", 0) or "").strip().upper()
            if symbol and not looks_like_cusip(symbol):
                names.setdefault(symbol, []).append(_at(_iso(_get(row, "at", 1))))
        sources[f"operator:{kind}"] = {"status": "ok", "count": len(rows)}
    try:
        events = query("SELECT DISTINCT ON (upper(symbol)) upper(symbol) AS s, event_type, created_at FROM watchlist_events "
                       "WHERE event_type IN ('watch_mine_added', 'watch_mine_removed') "
                       "ORDER BY upper(symbol), created_at DESC, id DESC") or []
        for row in events:
            symbol = str(_get(row, "s", 0) or "").upper()
            if _get(row, "event_type", 1) != "watch_mine_removed" or symbol not in names:
                continue
            removed_at = _at(_iso(_get(row, "created_at", 2)))
            if not [at for at in names[symbol] if removed_at is not None and at is not None and at > removed_at]:
                names.pop(symbol)
        sources["operator:removed"] = {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        sources["operator:removed"] = {"status": "error", "error": type(exc).__name__}
    return set(names)


def _read(query, sources, name, sql, params=None):
    try:
        rows = query(sql, params) or []
        sources[name] = {"status": "ok", "count": len(rows)}
        return rows
    except Exception as exc:  # noqa: BLE001 - a failed source is a reported gap, never an empty truth
        sources[name] = {"status": "error", "error": type(exc).__name__}
        return []


def universe(query, *, held_symbols=(), sources=None, extra_limit=120, screener_limit=40):
    """watch_intelligence._universe_symbols(view="all"): priority + starred + operator + held + screener + recent."""
    sources = {} if sources is None else sources
    starred = _symbols(_read(query, sources, "starred", "SELECT upper(symbol) AS s FROM operator_starred_symbols"))
    screener = _symbols(_read(query, sources, "screener_pins", "SELECT upper(symbol) AS s FROM screener_find_pins WHERE active = true"))
    screener |= _symbols(_read(query, sources, "screener_items", """
        SELECT DISTINCT upper(symbol) AS s FROM watchlist_items
         WHERE status IN ('active','researched')
           AND (lower(coalesce(source,'')) LIKE '%%screener%%' OR lower(coalesce(trigger_source,'')) LIKE '%%screener%%')
         LIMIT 500"""))
    ordered, seen = [], set()
    for symbol in (list(default_priority()) + sorted(starred) + sorted(operator_names(query, sources))
                   + sorted({str(s).upper() for s in held_symbols}) + sorted(screener)[:screener_limit]):
        if symbol not in seen:
            seen.add(symbol)
            ordered.append(symbol)
    for row in _read(query, sources, "watchlist_items", """
            SELECT s FROM (
                SELECT DISTINCT ON (upper(symbol)) upper(symbol) AS s, (status = 'active') AS is_active, updated_at
                  FROM watchlist_items WHERE status IN ('active','researched')
                 ORDER BY upper(symbol), (status = 'active') DESC, updated_at DESC NULLS LAST
            ) w ORDER BY is_active DESC, updated_at DESC NULLS LAST, s LIMIT %s""", (extra_limit,)):
        symbol = str(_get(row, "s", 0) or "").upper()
        if symbol and symbol not in seen:
            seen.add(symbol)
            ordered.append(symbol)
    return [s for s in ordered if not looks_like_cusip(s)]


def _review_files(root: Path, symbol: str):
    base = Path(root) / "data/runtime/watchlist_intelligence"
    out = {"quarantine": [], "artifacts": []}
    for kind in out:
        folder = base / kind
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob(f"{symbol}_*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            agent = str(raw.get("agent_id") or path.stem.split("_", 1)[-1]).lower()
            if agent == REVIEW_AGENT:
                out[kind].append(raw)
    return out


def review_disposition(raw, *, linked_request_ids):
    """watch_domains._disposition_from_candidate for the CIO agent, reduced to what the engine compares."""
    if not raw:
        return {"status": "NOT_RUN", "reason_code": "NOT_SCHEDULED"}
    if raw.get("status") == "QUARANTINED" or raw.get("quarantine") or raw.get("artifact_disposition") == "QUARANTINED":
        return {"status": "NOT_RUN", "reason_code": "QUARANTINED"}
    if not (raw.get("authorization_event_id") or raw.get("operator_command_id") or raw.get("authorized_by_event")):
        reason = "UNVERIFIED_OPERATOR_AUTHORIZATION"
    else:
        missing = [k for k in _AUTH_REQUIRED if raw.get(k) in (None, "", "NONE")]
        reason = (f"MISSING_{missing[0].upper()}" if missing else "MISSING_FALLBACK_USED" if raw.get("fallback_used") is None
                  else None if raw.get("provider_request_id") in linked_request_ids else "CONSUMPTION_REQUEST_ID_UNLINKED")
    if reason is None and raw.get("status") in ("COMPLETE", None, "complete"):
        return {"status": "COMPLETE", "verdict": raw.get("verdict"), "completed_at": raw.get("completed_at"),
                "started_at": raw.get("started_at"), "artifact_id": raw.get("artifact_id"),
                **({"inputs_as_of": raw["inputs_as_of"]} if raw.get("inputs_as_of") else {})}
    if reason is None and raw.get("status") in ("FAILED", "FAIL"):
        return {"status": "NOT_RUN", "reason_code": raw.get("reason_code") or "FAILED"}
    return {"status": "NOT_RUN", "reason_code": reason or raw.get("reason_code") or "NOT_SCHEDULED"}


def cio_reviews(query, root, symbols, sources):
    files = {s: _review_files(root, s) for s in symbols}
    request_ids = sorted({str(r.get("provider_request_id")) for f in files.values() for r in f["artifacts"]
                          if r.get("provider_request_id")})
    linked = set()
    if request_ids:
        linked = {str(_get(r, "provider_request_id", 0)) for r in _read(
            query, sources, "llm_consumption_log",
            "SELECT DISTINCT provider_request_id FROM llm_consumption_log WHERE provider_request_id = ANY(%s)",
            (request_ids,))}
    out = {}
    for symbol, found in files.items():
        if found["quarantine"]:
            out[symbol] = {"status": "NOT_RUN", "reason_code": "QUARANTINED"}      # quarantine wins
            continue
        dispositions = [review_disposition(raw, linked_request_ids=linked) for raw in found["artifacts"]]
        complete = [d for d in dispositions if d["status"] == "COMPLETE"]
        out[symbol] = max(complete, key=lambda d: str(d.get("completed_at") or "")) if complete else (
            dispositions[0] if dispositions else {"status": "NOT_RUN", "reason_code": "NOT_SCHEDULED"})
    return out


def trade_ai_states(query, symbols, *, held_symbols, held_known, now, sources):
    """Latest live packet -> stored action policy -> pure projection (current holdings win over the packet's flag)."""
    from scripts.decision_packet import materialize_packet
    from scripts.lib.rockville.decision_projection import packet_expired, project_watch_decision
    rows = _read(query, sources, "decision_packets", """
        SELECT DISTINCT ON (upper(symbol)) upper(symbol) AS s, packet_id, generated_at, packet FROM decision_packets
         WHERE upper(symbol) = ANY(%s) AND superseded_by IS NULL ORDER BY upper(symbol), generated_at DESC""",
                 (sorted(symbols),))
    out = {s: {"state": "DATA_UNAVAILABLE", "as_of": None, "packet_id": None, "reason": "no live decision packet"}
           for s in symbols}
    if sources.get("decision_packets", {}).get("status") != "ok":
        for value in out.values():
            value["reason"] = "decision packets unreadable"
        return out
    for row in rows:
        symbol = str(_get(row, "s", 0)).upper()
        packet = _get(row, "packet", 3)
        packet = json.loads(packet) if isinstance(packet, str) else dict(packet or {})
        generated = _get(row, "generated_at", 2)
        packet = materialize_packet(packet)
        if held_known:
            held = symbol in held_symbols
        else:
            held = bool((packet.get("ownership") or {}).get("held")) and not packet_expired(packet, generated_at=generated, now=now)
        packet["ownership"] = {**(packet.get("ownership") or {}), "held": held}
        decision = project_watch_decision(packet, packet.get("action_policy"), symbol=symbol, current_held=held,
                                          generated_at=generated, now=now)
        out[symbol] = {"state": decision.get("primary_state") or "DATA_UNAVAILABLE", "as_of": _iso(generated),
                       "packet_id": _get(row, "packet_id", 1), "reason": None}
    return out


def syntheses(query, symbols, sources):
    rows = _read(query, sources, "watchlist_final_synthesis", """
        SELECT DISTINCT ON (upper(symbol)) upper(symbol) AS s, recommendation, confidence, updated_at
          FROM watchlist_final_synthesis WHERE upper(symbol) = ANY(%s) AND NOT COALESCE(superseded, FALSE)
         ORDER BY upper(symbol), updated_at DESC NULLS LAST""", (sorted(symbols),))
    return {str(_get(r, "s", 0)).upper(): {"recommendation": str(_get(r, "recommendation", 1) or "").upper(),
                                           "confidence": _get(r, "confidence", 2), "at": _iso(_get(r, "updated_at", 3))}
            for r in rows}


def reentry_snapshot(root, sources):
    """The stored re-entry desk snapshot, mapped like watch_decision.reentry_rows (never rebuilt here)."""
    path = Path(root) / "data/runtime/reentry_decision_desk_latest.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        sources["reentry_snapshot"] = {"status": "error", "error": type(exc).__name__}
        return {}
    rows = {}
    for row in doc.get("rows") or []:
        intel = row.get("intel") or {}
        symbol = str(row.get("symbol") or "").upper()
        if symbol:
            rows[symbol] = {"state": intel.get("state"), "action": intel.get("action"), "reason": intel.get("reason"),
                            "price_as_of": row.get("price_as_of"), "plan_as_of": row.get("plan_as_of"),
                            "held": bool(row.get("held"))}
    sources["reentry_snapshot"] = {"status": "ok", "count": len(rows),
                                   "as_of": doc.get("generated_at") or doc.get("as_of")}
    return rows


def read_watch_state(query, *, root, now, held_symbols=None):
    """{cards, reentry, symbols, sources, gaps} for the resolver; cards carry only what the adapters compare.

    ``held_symbols`` is the canonical holdings set (cio_truth positions); None = holdings unknown.
    """
    sources: dict = {}
    held = {str(s).upper() for s in held_symbols or ()}
    symbols = universe(query, held_symbols=held, sources=sources)
    desk = reentry_snapshot(root, sources)
    every = sorted(set(symbols) | set(desk))
    reviews = cio_reviews(query, root, every, sources)
    synth = syntheses(query, every, sources)
    trade = trade_ai_states(query, every, held_symbols=held, held_known=held_symbols is not None, now=now, sources=sources)
    cards = {}
    for symbol in every:
        card = {"symbol": symbol, "cio_review": reviews.get(symbol) or {"status": "NOT_RUN"},
                "trade_ai_state": trade[symbol]["state"], "trade_ai_as_of": trade[symbol]["as_of"],
                "trade_ai_packet_id": trade[symbol]["packet_id"], "decision": {"inputs": {}}}
        if symbol in synth and synth[symbol]["recommendation"]:
            card["decision"]["inputs"] = {"synthesis": synth[symbol]["recommendation"],
                                          "synthesis_at": synth[symbol]["at"],
                                          "synthesis_confidence": synth[symbol]["confidence"]}
        cards[symbol] = card
    gaps = [f"{name}: {row.get('error')}" for name, row in sorted(sources.items()) if row.get("status") != "ok"]
    return {"schema": SCHEMA, "as_of": now.isoformat(), "symbols": every, "watch_universe": symbols, "cards": cards,
            "reentry": desk, "sources": sources, "gaps": gaps}
