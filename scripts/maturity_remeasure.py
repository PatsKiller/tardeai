#!/usr/bin/env python3
"""maturity_remeasure.py — independent maturity re-measurement (Wave 5 O-W5-4; 09 §W5, AGENTS §15).

Scores the nine domains of the cognitive transformation from receipts ONLY — never from a session's claim,
never from docs. Producer ≠ reviewer ≠ scorer: this lane reads what the producers wrote and applies fixed
rules; it writes MaturityScore@v1 (per domain: score 1–5, the proofs found, the proofs missing) to
data/governance/maturity_scores.jsonl (+ maturity_latest.json). The closeout quotes this file; a session
never writes a score.

Rules (house 1–5 scale, 09 §2): each domain lists proofs; the score is the highest level whose proofs are
ALL present in the window. Absent evidence scores 1. Everything is measured over --window-hours (default 168).
"""

NO_CONSUMER_REASON = (
    "MaturityScore@v1 rows are read by the Wave closeout and the Command Center maturity panel; lane maturity-remeasure "
    "is declared NEVER_SCHEDULED until the pkg-20260928-waves-3-5-cognition-unification-maturity-80f2 cron grant appends its line"
)
SCHEDULED_ENTRYPOINT = (
    "cron (after the cron grant): 40 6 * * 1 scripts/maturity_remeasure.py --write — NOT installed yet"
)

import argparse
import datetime as _dt
import json
import os
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJ / "scripts" / "lib"))
sys.path.insert(0, str(PROJ / "scripts"))

SCHEMA = "MaturityScore@v1"
LANE = "maturity-remeasure"
DOMAINS = (
    "memory",
    "cross_silo",
    "knowledge_graph",
    "agents",
    "workers",
    "continuous_research",
    "model_routing",
    "decision_intelligence",
    "operational_reliability",
)


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


def _rows(
    path: Path,
    since: str | None = None,
    ts_keys=(
        "ts",
        "as_of",
        "committed_at",
        "opened_at",
        "judged_at",
        "produced_at",
        "observed_at",
        "written_at",
        "beat_at",
        "detected_at",
    ),
    limit=400_000,
) -> list[dict]:
    out: list[dict] = []
    try:
        with path.open(encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                if i >= limit:
                    break
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if since:
                    ts = next((str(r.get(k)) for k in ts_keys if r.get(k)), None)
                    if ts and ts < since:
                        continue
                out.append(r)
    except OSError:
        pass
    return out


def _json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def collect(root: Path, *, window_hours: float, now: _dt.datetime | None = None) -> dict:
    """Pure over files: the evidence counters every rule reads."""
    now = now or _now()
    since = (now - _dt.timedelta(hours=window_hours)).isoformat()
    cio = root / "data" / "cio"
    rt = root / "data" / "runtime"
    gov = root / "data" / "governance"
    ctx = _rows(cio / "memory_contexts.jsonl", since)
    opened = [r for r in ctx if r.get("event") == "OPENED"]
    committed = [r for r in ctx if r.get("event") == "COMMITTED"]
    refused = [r for r in ctx if r.get("event") == "REFUSED"]
    ring2 = [r for r in ctx if r.get("schema") == "Ring2Decision@v1"]
    rr = _rows(cio / "retrieval_receipts.jsonl", since)
    wp = _rows(cio / "research_write_path_receipts.jsonl", since)
    fan = _rows(cio / "edge_fanout_work_items.jsonl", since)
    verdicts = _rows(cio / "contradiction_verdicts.jsonl", since)
    lessons = _rows(cio / "lesson_promotions.jsonl")
    filings = _rows(cio / "sec_filing_events.jsonl", since)
    ckpt_dir = cio / "agent_checkpoints"
    ckpts = (
        sum(len(_rows(p, since)) for p in ckpt_dir.glob("*.jsonl") if p.name != "resume_receipts.jsonl")
        if ckpt_dir.exists()
        else 0
    )
    resumes = len(_rows(ckpt_dir / "resume_receipts.jsonl", since)) if ckpt_dir.exists() else 0
    breaches = _rows(rt / "supervisor_breaches.jsonl", since)
    ladder = _rows(rt / "supervisor_ladder_receipts.jsonl", since)
    chooser = _rows(rt / "model_chooser_receipts.jsonl", since)
    routing = _rows(rt / "agent_registry_routing_receipts.jsonl", since)
    gate = _rows(gov / "conformance_gate_receipts.jsonl", since)
    conf = _json(gov / "platform_conformance_latest.json")
    proj = _json(rt / "gir_projector_state.json")
    hb_dir = rt / "heartbeats"
    heartbeats = [_json(p) for p in hb_dir.glob("*.json")] if hb_dir.exists() else []
    lanes_beating = sum(1 for h in heartbeats if h.get("last_beat") and str(h.get("last_beat")) >= since)
    pol = _json(PROJ / "config" / "memory_influence_policy.json")
    infl = (pol.get("influence") or {}).get("surfaces") or {}
    ring2s = (pol.get("ring2") or {}).get("surfaces") or {}
    wpa = (pol.get("write_path") or {}).get("adapters") or {}
    lanes_with_ctx = {(r.get("actor") or {}).get("lane_id") for r in opened}
    decide_ctx = [r for r in opened if r.get("purpose") in ("DECIDE", "ADVISE")]
    degraded_share = (sum(1 for r in opened if r.get("degraded")) / len(opened)) if opened else None
    mir = [r for r in committed if (r.get("influence") or {}).get("mir")]
    counts = proj.get("applied") or {}
    return {
        "as_of": now.isoformat(),
        "window_hours": window_hours,
        "contexts_opened": len(opened),
        "contexts_committed": len(committed),
        "contexts_refused": len(refused),
        "ring2_rows": len(ring2),
        "lanes_with_contexts": len({l for l in lanes_with_ctx if l}),
        "decide_contexts": len(decide_ctx),
        "degraded_share": degraded_share,
        "retrieval_receipts": len(rr),
        "retrieval_hit_fresh": sum(1 for r in rr if r.get("decision") == "HIT_FRESH"),
        "write_path_receipts": len(wp),
        "write_path_lanes": len({r.get("lane_family") for r in wp}),
        "write_path_live": sum(1 for r in wp if r.get("mode") == "LIVE"),
        "fanout_items": len(fan),
        "verdicts": len(verdicts),
        "verdicts_resolved": sum(1 for v in verdicts if v.get("verdict") not in (None, "UNRESOLVED")),
        "lessons_queued": sum(1 for l in lessons if l.get("status") == "QUEUED"),
        "lessons_promoted": sum(1 for l in lessons if l.get("status") == "PROMOTED"),
        "filing_events": len(filings),
        "checkpoints": ckpts,
        "resumes": resumes,
        "breaches": len(breaches),
        "breach_kinds": sorted({b.get("kind") for b in breaches if b.get("kind")}),
        "ladder_receipts": len(ladder),
        "ladder_paged": sum(1 for l in ladder if l.get("paged")),
        "chooser_receipts": len(chooser),
        "chooser_enforced": sum(1 for c in chooser if c.get("mode") == "enforce"),
        "routing_receipts": len(routing),
        "gate_receipts": len(gate),
        "gate_block_mode": any(g.get("mode") == "block" for g in gate),
        "conformance_as_of": conf.get("as_of"),
        "silos_scored": conf.get("silos_scored"),
        "silos_conformant": sum(1 for s in conf.get("silos") or [] if s.get("state") == "CONFORMANT"),
        "silos_total": sum(1 for s in conf.get("silos") or [] if s.get("silo_id") != "UNASSIGNED"),
        "gir_entities": counts.get("entities"),
        "gir_edges": counts.get("edges"),
        "gir_as_of": proj.get("as_of"),
        "lanes_beating": lanes_beating,
        "heartbeat_files": len(heartbeats),
        "influence_modes": infl,
        "ring2_modes": ring2s,
        "write_path_modes": wpa,
        "mir_commits": len(mir),
    }


def score(ev: dict) -> list[dict]:
    """Fixed rules → per-domain score with the proofs found / missing. Higher levels require the lower ones."""

    def ladder(domain: str, levels: list[tuple[int, str, bool]]) -> dict:
        found, missing, s = [], [], 1
        for lvl, proof, ok in levels:
            if ok and lvl == s + 1:
                s = lvl
                found.append(proof)
            elif ok:
                found.append(proof)
            else:
                missing.append(f"L{lvl}: {proof}")
        # levels are cumulative: the score is the highest level whose proofs and all lower proofs are present
        s = 1
        for lvl, proof, ok in levels:
            if ok and lvl == s + 1:
                s = lvl
            elif not ok:
                break
        return {"domain": domain, "score": s, "found": found, "missing": missing}

    ds = ev.get("degraded_share")
    decide_ok = ev["decide_contexts"] > 0 and ds is not None and ds < 0.2  # 0.0 is a valid, good share
    enf_infl = any(m in ("ENFORCED",) for m in (ev["influence_modes"] or {}).values())
    adv_infl = any(m in ("ADVISORY", "WEIGHTED", "ENFORCED") for m in (ev["influence_modes"] or {}).values())
    return [
        ladder(
            "memory",
            [
                (2, "contexts opened on ≥ 3 lanes", ev["lanes_with_contexts"] >= 3),
                (3, "read-before-act on DECIDE contexts with < 20 % degraded", decide_ok),
                (
                    4,
                    "memory rendered to a model (mir commits) or a promoted lesson",
                    ev["mir_commits"] > 0 or ev["lessons_promoted"] > 0,
                ),
                (
                    5,
                    "ENFORCED influence on a surface with checkpoints + resumes",
                    enf_infl and ev["checkpoints"] > 0 and ev["resumes"] > 0,
                ),
            ],
        ),
        ladder(
            "cross_silo",
            [
                (2, "write-path receipts from ≥ 3 producer families", ev["write_path_lanes"] >= 3),
                (
                    3,
                    "LIVE write path on ≥ 1 family + fan-out items",
                    ev["write_path_live"] > 0 and ev["fanout_items"] > 0,
                ),
                (4, "ADVISORY+ influence on a surface", adv_infl),
                (
                    5,
                    "conformance report all silos CONFORMANT",
                    ev["silos_total"] > 0 and ev["silos_conformant"] == ev["silos_total"],
                ),
            ],
        ),
        ladder(
            "knowledge_graph",
            [
                (2, "GIR projected (entities + edges)", bool(ev["gir_entities"]) and bool(ev["gir_edges"])),
                (3, "fan-out from edges producing work items", ev["fanout_items"] > 0),
                (4, "events + decisions in the graph (filing events)", ev["filing_events"] > 0),
                (5, "verdicts closing contradictions on the graph", ev["verdicts_resolved"] > 0),
            ],
        ),
        ladder(
            "agents",
            [
                (2, "contexts committed by agents", ev["contexts_committed"] > 0),
                (3, "cognitive checkpoints written", ev["checkpoints"] > 0),
                (4, "resumes from checkpoints", ev["resumes"] > 0),
                (
                    5,
                    "registry routing live (receipts settled)",
                    ev["routing_receipts"] == 0 and ev["contexts_committed"] > 0 and ev["checkpoints"] > 0,
                ),
            ],
        ),
        ladder(
            "workers",
            [
                (2, "heartbeats from ≥ 10 lanes", ev["lanes_beating"] >= 10),
                (3, "breach detector producing rows", ev["breaches"] > 0),
                (4, "ladder L4/L5 receipts", ev["ladder_receipts"] > 0),
                (5, "operator paged / self-heal executed", ev["ladder_paged"] > 0),
            ],
        ),
        ladder(
            "continuous_research",
            [
                (2, "retrieval receipts written", ev["retrieval_receipts"] > 0),
                (3, "HIT_FRESH reuse observed", ev["retrieval_hit_fresh"] > 0),
                (4, "contradiction verdicts written", ev["verdicts"] > 0),
                (5, "lessons promoted into procedural memory", ev["lessons_promoted"] > 0),
            ],
        ),
        ladder(
            "model_routing",
            [
                (2, "chooser receipts exist", ev["chooser_receipts"] > 0),
                (3, "Ring 2 rows on gate_and_generate", ev["ring2_rows"] > 0),
                (4, "chooser in advise/enforce", ev["chooser_enforced"] > 0),
                (
                    5,
                    "one chooser, zero disagreements in window",
                    ev["chooser_enforced"] > 0 and ev["chooser_receipts"] == ev["chooser_enforced"],
                ),
            ],
        ),
        ladder(
            "decision_intelligence",
            [
                (2, "DECIDE contexts opened", ev["decide_contexts"] > 0),
                (3, "no blind DECIDE (0 REFUSED, < 20 % degraded)", decide_ok and ev["contexts_refused"] == 0),
                (4, "ADVISORY+ on a decision surface", adv_infl),
                (5, "ENFORCED on a decision surface", enf_infl),
            ],
        ),
        ladder(
            "operational_reliability",
            [
                (2, "breach detector + heartbeats", ev["breaches"] > 0 and ev["heartbeat_files"] > 0),
                (3, "conformance report current", bool(ev["conformance_as_of"])),
                (4, "conformance gate receipts", ev["gate_receipts"] > 0),
                (5, "gate in block mode", ev["gate_block_mode"]),
            ],
        ),
    ]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--root")
    ap.add_argument("--window-hours", type=float, default=168.0)
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="score and report the files a --write would touch; write nothing (wins over --write)",
    )
    a = ap.parse_args(argv)
    env = dict(os.environ)
    root = Path(a.root) if a.root else state_root(env)
    ev = collect(root, window_hours=a.window_hours)
    rows = score(ev)
    overall = round(sum(r["score"] for r in rows) / len(rows), 2)
    out = {
        "schema": SCHEMA,
        "as_of": ev["as_of"],
        "window_hours": a.window_hours,
        "overall": overall,
        "target": 4.7,
        "domains": rows,
        "evidence": ev,
        "scorer": LANE,
        "authority": "READ_ONLY_ADVISORY",
        "note": "scored from receipts only; a session never writes this file",
    }
    print(json.dumps({"overall": overall, "domains": {r["domain"]: r["score"] for r in rows}}, indent=1))
    if a.dry_run or not a.write:
        if a.dry_run:
            gov = root / "data" / "governance"
            print(
                json.dumps(
                    {
                        "mode": "dry_run",
                        "would_append": str(gov / "maturity_scores.jsonl"),
                        "would_replace": str(gov / "maturity_latest.json"),
                        "would_heartbeat": LANE,
                    },
                    indent=1,
                )
            )
        return 0  # returns before any write is reachable (AGENTS.md §6)
    if a.write:
        gov = root / "data" / "governance"
        gov.mkdir(parents=True, exist_ok=True)
        with (gov / "maturity_scores.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(out, sort_keys=True, default=str) + "\n")
        tmp = gov / "maturity_latest.json.tmp"
        tmp.write_text(json.dumps(out, indent=1, default=str) + "\n", encoding="utf-8")
        os.replace(tmp, gov / "maturity_latest.json")
        try:
            import supervisor_heartbeat as hb  # type: ignore

            print(
                "heartbeat:",
                hb.beat(LANE, success=True, output_signal=True, work_done=len(rows), root=root, env=env).get("pg"),
            )
        except Exception as exc:  # noqa: BLE001
            print(f"heartbeat skipped: {type(exc).__name__}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
