#!/usr/bin/env python3
"""edge_fanout_consumer.py — bus consumer: memory.delta / thesis.changed → graph traversal → work items.

Wave 2 items 3 and 4 (pkg-20260928-wave-2-enforcement-35c4). Replaces the hard-coded per-agent routing
list for thesis changes with fan-out derived from the Global Intelligence Record's edges (07 §4):

    event subject  →  SEC:<guid>
        ←HOLDS←  ACCOUNT        (who holds it)
        —BELIEVES→ BELIEF       (which beliefs depend on it)
        —HAS_THESIS→ THESIS     (which thesis versions)
        —CONTRADICTS→ CONTRA    (open contradictions)
        ←ISSUES←  ISS  →ISSUES→ SEC*   (sibling listings of the same issuer)
        ←AFFECTED_BY← EVENT     (filing / market events, tranche 4)
    depth ≤ 3, ≤ 200 nodes per subject

Outputs, per event × subject:
  * EdgeFanoutWorkItem@v1 rows (data/cio/edge_fanout_work_items.jsonl, idempotent) — kind `reproject`
    (the projector re-projects the subject on its next incremental run) and kind `notify` (the agents /
    accounts the traversal reached; consumed by the reactive cycle when it is pointed here — until then
    the rows are the proof of what WOULD be routed);
  * data/runtime/gir_projector_dirty.json — the incremental projector treats it as a changed source.

Read-only against Postgres (the traversal), append-only on JSONL. Zero authority. Fail-soft without a DSN
(traversal empty → subject-only reproject items). `--dry-run` is the default; `--apply` writes and
advances the bus cursor. Heartbeat: lane edge-fanout-consumer.
"""
NO_CONSUMER_REASON = (
    "EdgeFanoutWorkItem@v1 rows are consumed by gir_projector --incremental (kind reproject, via the dirty file) "
    "and by the reactive cycle once its routing is pointed at the fan-out (Wave 2 tranche 4); lane "
    "lane edge-fanout-consumer is ACTIVE (tradeai-edge-fanout-consumer.timer, every 5 min, installed 2026-09-27 "
    "22:44 ET under the pkg-20260928-wave-2-enforcement-35c4 service grant)"
)

import argparse
import datetime as _dt
import hashlib
import json
import os
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJ / "scripts" / "lib"))
sys.path.insert(0, str(PROJ / "scripts"))

SCHEMA = "EdgeFanoutWorkItem@v1"
LANE = "edge-fanout-consumer"
CONSUMER = "edge-fanout"
EVENT_TYPES = ("memory.delta", "thesis.changed")
RELATIONS = ("HOLDS", "BELIEVES", "HAS_THESIS", "CONTRADICTS", "ISSUES", "AFFECTED_BY", "DECIDED_ON", "SUPERSEDES")
MAX_DEPTH = 3
MAX_NODES = 200
TENANT = "tradeai:tenant:primary"
AUTHORITY = "READ_ONLY_ADVISORY"


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def state_root(env: dict) -> Path:
    if env.get("TRADEAI_STATE_ROOT"):
        return Path(env["TRADEAI_STATE_ROOT"])
    try:
        from canonical_store_registry import production_state_root  # type: ignore
        return Path(production_state_root())
    except Exception:  # noqa: BLE001
        return Path.home() / "trade-ai-releases" / "persistent-state"


def _guid_of(subject: str) -> str | None:
    """'SEC:<uuid>' | '<uuid>' → uuid; anything else → None."""
    s = str(subject or "").strip()
    if s.upper().startswith("SEC:"):
        s = s[4:]
    return s if len(s) == 36 and s.count("-") == 4 else None


def subjects_for(event: dict, resolve_symbol=None) -> list[str]:
    """Security GUIDs named by one event (memory.delta subjects; thesis.changed symbol)."""
    p = event.get("payload") or {}
    out: list[str] = []
    for s in p.get("subjects") or []:
        g = _guid_of(s)
        if g:
            out.append(g)
    if not out and p.get("symbol") and resolve_symbol:
        try:
            ent = resolve_symbol(str(p["symbol"]))
            g = (ent or {}).get("security_guid") or (ent or {}).get("guid")
            if g:
                out.append(str(g))
        except Exception:  # noqa: BLE001
            pass
    return sorted(set(out))


_NEIGHBOURS = """
SELECT e.from_guid, e.to_guid, e.relation
  FROM intelligence.gir_edge e
 WHERE (e.from_guid = %(g)s OR e.to_guid = %(g)s) AND e.relation = ANY(%(relations)s) AND upper_inf(e.valid_period)
 LIMIT %(lim)s
"""
STATEMENT_TIMEOUT_MS = 5000


def traverse(conn, start_guid: str) -> list[dict]:
    """Neighbourhood of SEC:<guid> up to MAX_DEPTH over RELATIONS — a bounded breadth-first walk (one
    indexed query per visited node, ≤ MAX_NODES nodes, 5 s statement timeout). Read-only. [] without a
    connection or on any error."""
    if conn is None:
        return []
    start = f"SEC:{start_guid}"
    seen: dict[str, int] = {start: 0}
    frontier = [start]
    out: list[dict] = []
    try:
        with conn.cursor() as cur:
            cur.execute("SET app.tenant_id = %s", (TENANT,))
            cur.execute("SET LOCAL statement_timeout = %s", (STATEMENT_TIMEOUT_MS,))
            for depth in range(1, MAX_DEPTH + 1):
                nxt: list[str] = []
                for g in frontier:
                    cur.execute(_NEIGHBOURS, {"g": g, "relations": list(RELATIONS), "lim": MAX_NODES})
                    for f, t_, rel in cur.fetchall():
                        other = t_ if f == g else f
                        if other in seen:
                            continue
                        seen[other] = depth
                        out.append({"guid": other, "depth": depth, "via": rel, "class": "", "kind": ""})
                        nxt.append(other)
                        if len(out) >= MAX_NODES:
                            break
                    if len(out) >= MAX_NODES:
                        break
                if not nxt or len(out) >= MAX_NODES:
                    break
                frontier = nxt
        conn.rollback()
        return out
    except Exception:  # noqa: BLE001
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass
        return []


def work_items(event: dict, subject_guid: str, neighbours: list[dict], now: _dt.datetime) -> list[dict]:
    """Pure: the work items one (event, subject) pair implies."""
    eid = str(event.get("event_id") or "")
    etype = str(event.get("event_type") or "")
    base = {"schema": SCHEMA, "source_event_id": eid, "event_type": etype, "subject_guid": subject_guid,
            "produced_at": now.isoformat(), "authority": AUTHORITY, "memory_behavior_influence": 0}

    def _item(kind: str, **extra) -> dict:
        key = hashlib.sha256(f"{eid}|{subject_guid}|{kind}|{extra.get('target', '')}".encode("utf-8")).hexdigest()[:32]
        return {**base, "item_id": f"efw_{key}", "kind": kind, "idempotency_key": key, **extra}

    out = [_item("reproject", reason=f"{etype} touched SEC:{subject_guid}", neighbourhood=len(neighbours))]
    accounts = sorted({n["guid"] for n in neighbours if n["guid"].startswith("ACCOUNT:")})
    agents = sorted({n["guid"] for n in neighbours if n["guid"].startswith(("AGENT:", "BELIEF:"))})
    contras = sorted({n["guid"] for n in neighbours if n["guid"].startswith("CONTRA")})
    events = sorted({n["guid"] for n in neighbours if n["guid"].startswith("EVENT:")})
    siblings = sorted({n["guid"] for n in neighbours if n["guid"].startswith("SEC:") and n["guid"] != f"SEC:{subject_guid}"})
    for tgt in accounts:
        out.append(_item("notify", target=tgt, target_kind="ACCOUNT", reason="HOLDS the subject"))
    for tgt in agents:
        out.append(_item("notify", target=tgt, target_kind="BELIEF", reason="belief depends on the subject"))
    for tgt in siblings:
        out.append(_item("reproject", target=tgt, target_kind="SECURITY", reason="same issuer"))
    if contras:
        out.append(_item("notify", target="cio", target_kind="AGENT", reason=f"{len(contras)} open contradiction(s) on the subject",
                         contradictions=contras[:20]))
    if events:
        out[0]["events"] = events[:20]
    return out


def _read_keys(path: Path) -> set[str]:
    keys: set[str] = set()
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    keys.add(json.loads(line).get("idempotency_key") or "")
                except (json.JSONDecodeError, AttributeError):
                    continue
    except OSError:
        pass
    return keys


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="write work items + dirty file and advance the bus cursor")
    ap.add_argument("--root", help="state root (default: production persistent-state)")
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--since-hours", type=float, default=48.0, help="ignore bus events older than this (bounds the first run's backlog)")
    a = ap.parse_args()
    env = dict(os.environ)
    root = Path(a.root) if a.root else state_root(env)
    now = _now()

    try:
        from cio_event_bus import CIOEventBus  # type: ignore
        bus = CIOEventBus()
        since = (now - _dt.timedelta(hours=a.since_hours)).isoformat() if a.since_hours and a.since_hours > 0 else None
        events = bus.poll(consumer=CONSUMER, since=since, event_types=list(EVENT_TYPES), limit=a.limit)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"schema": "EdgeFanoutRun@v1", "as_of": now.isoformat(), "error": f"bus:{type(exc).__name__}:{exc}"}))
        return 2
    events = sorted(events, key=lambda e: e.timestamp)  # oldest first; poll returns newest first

    resolve = None
    try:
        import intelligence_client as ic  # type: ignore
        resolve = ic.default_loaders(root, env).resolve_subject
    except Exception:  # noqa: BLE001
        resolve = None
    conn = None
    try:
        import db_adapter  # type: ignore
        conn = db_adapter._get_conn()
    except Exception:  # noqa: BLE001
        conn = None

    items_path = root / "data" / "cio" / "edge_fanout_work_items.jsonl"
    dirty_path = root / "data" / "runtime" / "gir_projector_dirty.json"
    seen = _read_keys(items_path) if a.apply else set()
    new_rows: list[dict] = []
    touched: set[str] = set()
    unresolved = 0
    for ev in events:
        evd = {"event_id": ev.event_id, "event_type": ev.event_type, "payload": ev.payload, "timestamp": ev.timestamp}
        subs = subjects_for(evd, resolve)
        if not subs:
            unresolved += 1
            continue
        for g in subs:
            touched.add(g)
            for it in work_items(evd, g, traverse(conn, g), now):
                if it["idempotency_key"] in seen:
                    continue
                seen.add(it["idempotency_key"])
                new_rows.append(it)

    summary = {"schema": "EdgeFanoutRun@v1", "as_of": now.isoformat(), "events": len(events), "subjects": len(touched),
               "unresolved_events": unresolved, "new_items": len(new_rows), "pg": conn is not None,
               "by_kind": {k: sum(1 for r in new_rows if r["kind"] == k) for k in ("reproject", "notify")},
               "mode": "apply" if a.apply else "dry_run", "authority": AUTHORITY}
    print(json.dumps(summary, indent=1))
    if not a.apply:
        for r in new_rows[:10]:
            print(json.dumps(r, default=str)[:300])
        return 0

    items_path.parent.mkdir(parents=True, exist_ok=True)
    with items_path.open("a", encoding="utf-8") as fh:
        for r in new_rows:
            fh.write(json.dumps(r, sort_keys=True, default=str) + "\n")
    if touched:
        dirty_path.parent.mkdir(parents=True, exist_ok=True)
        prev = {}
        try:
            prev = json.loads(dirty_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            prev = {}
        pending = sorted(set(prev.get("subjects") or []) | touched) if not prev.get("consumed_at") else sorted(touched)
        tmp = dirty_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"schema": "GirProjectorDirty@v1", "ts": now.isoformat(), "subjects": pending,
                                   "source": LANE}, indent=1) + "\n", encoding="utf-8")
        os.replace(tmp, dirty_path)
    latest = root / "data" / "runtime" / "edge_fanout_consumer_latest.json"
    tmp = latest.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, latest)
    if events:
        try:
            bus.advance_cursor(CONSUMER, events[-1].event_id, events[-1].event_type)
        except Exception as exc:  # noqa: BLE001
            print(f"cursor advance failed: {type(exc).__name__}: {exc}", file=sys.stderr)
    try:
        import supervisor_heartbeat as hb  # type: ignore
        if conn is not None:
            with conn.cursor() as c:
                c.execute("SET app.tenant_id = %s", (TENANT,))
        print("heartbeat:", hb.beat(LANE, conn=conn, success=True, output_signal=True, work_claimed=len(events),
                                    work_done=len(new_rows), root=root, env=env).get("pg"))
    except Exception as exc:  # noqa: BLE001
        print(f"heartbeat skipped: {type(exc).__name__}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
