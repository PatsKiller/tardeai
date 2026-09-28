"""memory_compliance — MemoryCompliance@v1 (01 §6): per lane, did it read before acting, write after acting,
publish deltas, touch freshness/contradiction state; how much of it ran blind; how many writes bypass the door.

Pure builder over the façade's receipts (contexts + retrieval receipts), the heartbeat files (runs), and the
Ring 1 baseline (orphan writes). No Postgres. Wave 1 tranche 4: the report is computed inside the nightly
platform-conformance lane and written next to it (memory_compliance_latest.json). Thresholds are the W2 exit
thresholds from 01 §6; in Wave 1 they are reported, never enforced.

Authority: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import datetime as _dt
import json
from collections import defaultdict
from pathlib import Path

SCHEMA = "MemoryCompliance@v1"
THRESHOLDS = {"read_before_act": 0.99, "write_after_act": 0.95, "delta_published": 0.95, "freshness_updated": 0.90,
              "contradiction_state_touched": 0.90, "blind_runs_decide": 0.0}
DECIDE_PURPOSES = ("DECIDE", "ADVISE")


def _rows(p: Path, since: _dt.datetime | None, keys=("opened_at", "committed_at", "created_at")) -> list[dict]:
    out: list[dict] = []
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if since:
            ts = next((r.get(k) for k in keys if r.get(k)), None)
            try:
                t = _dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                if t.tzinfo is None:
                    t = t.replace(tzinfo=_dt.timezone.utc)
            except (TypeError, ValueError):
                continue
            if t < since:
                continue
        out.append(r)
    return out


def build(*, contexts_path: Path, receipts_path: Path, heartbeats: list[dict], ring1_baseline: dict | None,
          now: _dt.datetime, window_hours: int = 24) -> dict:
    since = now - _dt.timedelta(hours=window_hours)
    ctx_rows = _rows(contexts_path, since)
    rr_rows = _rows(receipts_path, since, ("created_at",))
    opened = [r for r in ctx_rows if r.get("event") == "OPENED"]
    refused = [r for r in ctx_rows if r.get("event") == "REFUSED"]
    committed = {r.get("context_id"): r for r in ctx_rows if r.get("event") == "COMMITTED"}
    rr_by_ctx = defaultdict(list)
    for r in rr_rows:
        rr_by_ctx[r.get("context_id")].append(r)
    hb_by_lane = {h.get("lane_id"): h for h in heartbeats if isinstance(h, dict)}

    lanes: dict[str, dict] = {}
    for o in opened:
        lane = str(o.get("lane_id") or (o.get("actor") or {}).get("lane_id"))
        L = lanes.setdefault(lane, {"lane_id": lane, "contexts": 0, "decide_contexts": 0, "committed": 0, "degraded": 0,
                                    "with_retrieval_receipt": 0, "deltas_recorded": 0, "freshness_touched": 0,
                                    "contradiction_touched": 0, "influence_consulted": 0, "purposes": defaultdict(int)})
        L["contexts"] += 1
        L["purposes"][str(o.get("purpose"))] += 1
        if o.get("purpose") in DECIDE_PURPOSES:
            L["decide_contexts"] += 1
        if o.get("degraded"):
            L["degraded"] += 1
        c = committed.get(o.get("context_id"))
        if c:
            L["committed"] += 1
            if c.get("delta_count"):
                L["deltas_recorded"] += 1
            if c.get("freshness_updates"):
                L["freshness_touched"] += 1
            if c.get("contradiction_updates") or o.get("contradiction_state") in ("NONE", "OPEN"):
                L["contradiction_touched"] += 1
            if (c.get("influence") or {}).get("consulted"):
                L["influence_consulted"] += 1
        if rr_by_ctx.get(o.get("context_id")):
            L["with_retrieval_receipt"] += 1

    report_lanes = []
    for lane, L in sorted(lanes.items()):
        n = L["contexts"] or 1
        hb = hb_by_lane.get(lane) or {}
        runs = int(hb.get("work_claimed") or 0)
        measures = {
            # a context row IS the read receipt; the honest "before act" share needs runs from heartbeats
            "read_before_act": (min(1.0, L["contexts"] / runs) if runs else None),
            "write_after_act": L["committed"] / n,
            "delta_published": (L["deltas_recorded"] / L["committed"]) if L["committed"] else None,
            "freshness_updated": (L["freshness_touched"] / L["committed"]) if L["committed"] else None,
            "contradiction_state_touched": L["contradiction_touched"] / n,
            "retrieval_receipt_share": L["with_retrieval_receipt"] / n,
            "blind_runs": L["degraded"] / n,
            "blind_runs_decide": (sum(1 for o in opened if str(o.get("lane_id") or (o.get("actor") or {}).get("lane_id")) == lane
                                      and o.get("purpose") in DECIDE_PURPOSES and o.get("degraded")) / L["decide_contexts"]) if L["decide_contexts"] else None,
        }
        below = [k for k, v in THRESHOLDS.items() if measures.get(k) is not None and
                 ((measures[k] < v) if k != "blind_runs_decide" else (measures[k] > v))]
        report_lanes.append({**{k: v for k, v in L.items() if k != "purposes"}, "purposes": dict(L["purposes"]),
                             "runs_from_heartbeat": runs or None, "measures": measures, "below_threshold": below})

    ring1 = ring1_baseline or {}
    return {
        "schema": SCHEMA, "as_of": now.isoformat(), "window_hours": window_hours, "authority": "READ_ONLY_ADVISORY",
        "mode": "SHADOW (reported, not enforced until Wave 2)", "thresholds": THRESHOLDS,
        "totals": {"contexts_opened": len(opened), "contexts_refused": len(refused), "contexts_committed": len(committed),
                   "retrieval_receipts": len(rr_rows), "lanes_with_contexts": len(lanes),
                   "decisions_by_ladder": dict(_count(rr_rows, "decision")),
                   "duplicate_generation_shadow": sum(1 for r in rr_rows if r.get("decision") == "HIT_FRESH" and r.get("generated"))},
        "orphan_writes": {"direct_silo_imports": ring1.get("total"), "files": len(ring1.get("files", {})),
                          "note": "Ring 1 baseline; may only shrink (01 §2)"},
        "lanes": report_lanes,
        "unmeasured": ["read_before_act needs heartbeat runs (work_claimed) — hooked producers beat from shadow_open since tranche 4",
                       "delta_published counts deltas RECORDED on the commit; the write path (bus publish) is Wave 2"],
    }


def _count(rows, key):
    c: dict = defaultdict(int)
    for r in rows:
        c[str(r.get(key))] += 1
    return c


__all__ = ["build", "SCHEMA", "THRESHOLDS"]
