#!/usr/bin/env python3
"""report_platform_conformance.py — PlatformConformance@v1 per silo, v0 = MEASURE ONLY (05 §3–§4).

Five standards per silo (identity, memory, research, worker, monitoring). In v0 only what has data
is scored; everything else is UNMEASURED, and the UNMEASURED count is the first number printed —
it is the governance-debt baseline (05 §8). Nothing is remediated. Dry-run prints; ``--write`` writes
``data/governance/platform_conformance_latest.json`` (tmp+replace) with every query it ran.

Inputs (all repo/persistent-state files, no Postgres in v0):
  config/lane_registry.json, config/platform_silos.json,
  data/runtime/supervisor_sla_seed.json (seed_supervisor_sla.py --json-out),
  data/runtime/heartbeats/*.json (supervisor_heartbeat),
  data/cio/memory_contexts.jsonl and data/cio/retrieval_receipts.jsonl (intelligence_client, last 24 h),
  config/memory_chokepoint_baseline.json (Ring 1 debt).

Approval: pkg-20260927-cogx-w1-d9e1 item 1 (the lane); this script is the lane's body.
Authority: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

PROJ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJ / "scripts" / "lib"))

SCHEMA = "PlatformConformance@v1"
WEIGHTS = {"identity": 0.20, "memory": 0.30, "research": 0.20, "worker": 0.15, "monitoring": 0.15}
CONFORMANT, DEGRADED = 0.95, 0.80


def _load_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _jsonl(p: Path, since: _dt.datetime | None = None, ts_key: str = "opened_at") -> list[dict]:
    out = []
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if since:
            ts = row.get(ts_key) or row.get("created_at") or row.get("committed_at")
            try:
                t = _dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                if t.tzinfo is None:
                    t = t.replace(tzinfo=_dt.timezone.utc)
            except (TypeError, ValueError):
                continue
            if t < since:
                continue
        out.append(row)
    return out


def silo_of(lane_id: str, owner: str | None, silos: list[dict]) -> str:
    l = (lane_id or "").lower()
    for s in silos:
        if any(l.startswith(p) for p in s.get("lane_prefixes", [])):
            return s["silo_id"]
    for s in silos:
        if owner and owner in s.get("owners", []):
            return s["silo_id"]
    return "UNASSIGNED"


def state_of(score: float | None) -> str:
    if score is None:
        return "UNMEASURED"
    return "CONFORMANT" if score >= CONFORMANT else ("DEGRADED" if score >= DEGRADED else "NON_CONFORMANT")


def build(root: Path, *, now: _dt.datetime | None = None, env: dict | None = None) -> dict:
    env = os.environ if env is None else env
    now = now or _dt.datetime.now(_dt.timezone.utc)
    since = now - _dt.timedelta(hours=24)
    reg = _load_json(root / "config" / "lane_registry.json", {"lanes": []})
    silos_cfg = _load_json(root / "config" / "platform_silos.json", {"silos": []})["silos"]
    sla_seed = _load_json(root / "data" / "runtime" / "supervisor_sla_seed.json", {"rows": []})
    sla_by_lane = {r["lane_id"]: r for r in sla_seed.get("rows", [])}
    hb_dir = Path(env.get("TRADEAI_HEARTBEAT_DIR") or root / "data" / "runtime" / "heartbeats")
    heartbeats = {p.stem: _load_json(p, {}) for p in hb_dir.glob("*.json")} if hb_dir.exists() else {}
    cio_dir = Path(env.get("TRADEAI_CIO_DIR") or root / "data" / "cio")
    contexts = _jsonl(Path(env.get("TRADEAI_MEMORY_CONTEXTS_PATH") or cio_dir / "memory_contexts.jsonl"), since)
    receipts = _jsonl(Path(env.get("TRADEAI_RETRIEVAL_RECEIPTS_PATH") or cio_dir / "retrieval_receipts.jsonl"), since, "created_at")
    ring1 = _load_json(root / "config" / "memory_chokepoint_baseline.json", {})

    lanes_by_silo: dict[str, list[dict]] = defaultdict(list)
    for lane in reg.get("lanes", []):
        lanes_by_silo[silo_of(lane.get("lane_id", ""), lane.get("owner"), silos_cfg)].append(lane)
    ctx_by_lane: dict[str, list[dict]] = defaultdict(list)
    for c in contexts:
        ctx_by_lane[str(c.get("lane_id") or (c.get("actor") or {}).get("lane_id"))].append(c)
    rr_by_lane: dict[str, list[dict]] = defaultdict(list)
    for r in receipts:
        rr_by_lane[str(r.get("lane_id"))].append(r)

    report_silos = []
    unmeasured_total = 0
    for s in silos_cfg + [{"silo_id": "UNASSIGNED", "title": "lanes matching no silo (finding)"}]:
        sid = s["silo_id"]
        lanes = lanes_by_silo.get(sid, [])
        active = [l for l in lanes if l.get("state") == "ACTIVE"]
        findings = []
        measures: dict[str, float | None] = {}
        # worker: ACTIVE lanes with an output_signal that is not 'none' and a cadence
        if active:
            ok = sum(1 for l in active if (l.get("output_signal") or {}).get("kind") not in (None, "none") and l.get("expected_cadence_hours"))
            measures["worker"] = ok / len(active)
            if ok < len(active):
                findings.append({"standard": "worker", "measure": "lanes_with_output_signal_and_cadence", "value": f"{ok}/{len(active)}", "threshold": "all", "class": "B"})
        else:
            measures["worker"] = None
        # monitoring: ACTIVE lanes with an SLA seed row AND a heartbeat file (v0: heartbeat presence only)
        if active:
            with_sla = sum(1 for l in active if l.get("lane_id") in sla_by_lane)
            with_hb = sum(1 for l in active if l.get("lane_id") in heartbeats)
            measures["monitoring"] = (0.5 * with_sla + 0.5 * with_hb) / len(active)
            if with_hb < len(active):
                findings.append({"standard": "monitoring", "measure": "lanes_with_heartbeat", "value": f"{with_hb}/{len(active)}", "threshold": "all", "class": "A", "action": "add supervisor_heartbeat.beat() to the launcher"})
            if with_sla < len(active):
                findings.append({"standard": "monitoring", "measure": "lanes_with_sla_row", "value": f"{with_sla}/{len(active)}", "threshold": "all", "class": "A", "action": "seed_supervisor_sla.py --json-out"})
        else:
            measures["monitoring"] = None
        # memory: contexts opened by this silo's lanes in 24 h → read_before_act share among those with a commit
        lane_ids = {l.get("lane_id") for l in lanes}
        ctxs = [c for lid in lane_ids for c in ctx_by_lane.get(str(lid), [])]
        opened = [c for c in ctxs if c.get("event") == "OPENED"]
        committed = {c.get("context_id") for c in ctxs if c.get("event") == "COMMITTED"}
        if opened:
            wa = sum(1 for c in opened if c.get("context_id") in committed) / len(opened)
            degraded = sum(1 for c in opened if c.get("degraded")) / len(opened)
            measures["memory"] = max(0.0, (0.6 * 1.0) + 0.4 * wa - 0.2 * degraded)  # v0 proxy; read_before_act is 1.0 by construction for receipts
            findings.append({"standard": "memory", "measure": "contexts_opened_24h", "value": len(opened), "note": f"write_after_act={wa:.2f} degraded_share={degraded:.2f}"})
        else:
            measures["memory"] = None
        # research: retrieval receipts in 24 h → share not MISS-with-empty-ladder; DGR proxy = HIT_FRESH that generated
        rrs = [r for lid in lane_ids for r in rr_by_lane.get(str(lid), [])]
        if rrs:
            bad = sum(1 for r in rrs if r.get("decision") == "MISS" and not r.get("ladder"))
            dup = sum(1 for r in rrs if r.get("decision") == "HIT_FRESH" and r.get("generated"))
            measures["research"] = max(0.0, 1.0 - bad / len(rrs) - 0.5 * dup / len(rrs))
            findings.append({"standard": "research", "measure": "retrieval_receipts_24h", "value": len(rrs), "note": f"shadow_duplicate_generation={dup}/{len(rrs)} (DGR proxy)"})
        else:
            measures["research"] = None
        # identity: share of subjects in this silo's contexts (24 h) that resolved to a registry GUID
        subj = [s for c in opened for s in (c.get("subjects") or []) if isinstance(s, dict)]
        if subj:
            ok_id = sum(1 for s in subj if s.get("identity_status") in ("CONFIRMED", "CANDIDATE", "NAMESPACED"))
            measures["identity"] = ok_id / len(subj)
            if ok_id < len(subj):
                findings.append({"standard": "identity", "measure": "subjects_resolved_to_guid", "value": f"{ok_id}/{len(subj)}", "threshold": "all", "class": "B",
                                 "action": "unresolved symbols: identity registry mint or UNRESOLVABLE stamp"})
        else:
            measures["identity"] = None
        um = [k for k, v in measures.items() if v is None]
        unmeasured_total += len(um)
        scored = {k: v for k, v in measures.items() if v is not None}
        score = round(sum(WEIGHTS[k] * v for k, v in scored.items()) / sum(WEIGHTS[k] for k in scored), 3) if scored else None
        report_silos.append({"silo_id": sid, "title": s.get("title"), "lanes": len(lanes), "active_lanes": len(active),
                             "standards": measures, "unmeasured": um, "score": score, "state": state_of(score), "findings": findings})

    return {
        "schema": SCHEMA, "as_of": now.isoformat(), "release_sha": env.get("TRADEAI_RELEASE_SHA"),
        "authority": "READ_ONLY_ADVISORY", "version": "v0.1 (measure only; identity from context receipts; no remediation)",
        "unmeasured_standards_total": unmeasured_total,
        "silos_scored": sum(1 for s in report_silos if s["score"] is not None),
        "silos": report_silos,
        "ring1_memory_chokepoint_debt": {"files": len(ring1.get("files", {})), "imports": ring1.get("total")},
        "inputs": {"lanes": len(reg.get("lanes", [])), "sla_seed_rows": len(sla_by_lane), "heartbeat_files": len(heartbeats),
                   "memory_contexts_24h": len(contexts), "retrieval_receipts_24h": len(receipts)},
        "commands": ["python3 scripts/report_platform_conformance.py --write",
                     "python3 scripts/seed_supervisor_sla.py --json-out data/runtime/supervisor_sla_seed.json",
                     "python3 scripts/check_memory_chokepoint.py"],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(PROJ))
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args()
    root = Path(a.root)
    rep = build(root)
    head = {k: rep[k] for k in ("as_of", "unmeasured_standards_total", "silos_scored", "inputs")}
    print(json.dumps(head, indent=1))
    for s in rep["silos"]:
        print(f"{s['state']:<14} {s['silo_id']:<24} lanes={s['lanes']:<3} active={s['active_lanes']:<3} score={s['score']} unmeasured={','.join(s['unmeasured'])}")
    if a.write:
        out = Path(a.out) if a.out else root / "data" / "governance" / "platform_conformance_latest.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".json.tmp"); tmp.write_text(json.dumps(rep, indent=1) + "\n", encoding="utf-8"); os.replace(tmp, out)
        print(f"wrote {out}")
    else:
        print("dry run: nothing written (add --write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
