#!/usr/bin/env python3
"""contradiction_adjudicator.py — paid judge over research contradiction candidates (Wave 3 O-W3-3; 07 §5, 03 §6).

129,547 ResearchContradictionCandidate@v1 rows exist and every one is still CANDIDATE: the consumer
escalates and never resolves. This lane adjudicates the newest subjects first:

    candidates ──digest (freshness-ranked)──▶ unjudged pairs ──DeepSeek Flash (FAST)──▶ ContradictionVerdict@v1
                                                                                          data/cio/contradiction_verdicts.jsonl

Verdicts: LEFT (left artifact stands) · RIGHT · BOTH_STALE · NOT_A_CONTRADICTION · UNRESOLVED (needs research).
Advisory rows only — the thesis writer stays research_thesis_delta; the façade subtracts adjudicated pairs
from ``open_contradictions`` and the GIR envelope shows the net state.

Spend controls, all fail-closed: the process's own cap (registry ``contradiction_adjudicator``, $0.50/day),
the Tier-2 paid-judge policy (``TRADEAI_TIER2_*``: $2/day, off-peak only, provider deepseek) checked with
today's ledger spend before every call, the off-peak deferral, and ``--max-pairs``. ``--dry-run`` (default)
selects and prints; ``--apply`` calls the judge and appends verdicts. Heartbeat: lane contradiction-adjudicator.
"""
NO_CONSUMER_REASON = (
    "ContradictionVerdict@v1 rows are read by intelligence_client.open_context (net open contradictions), "
    "gir_projector (entity contradictions envelope) and the conformance report; lane contradiction-adjudicator "
    "is ACTIVE (tradeai-contradiction-adjudicator.timer, daily 19:30 local, installed 2026-09-28 08:18 ET under the pkg-20260928-waves-3-5-cognition-unification-maturity-80f2 service grant)"
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
sys.path.insert(0, str(PROJ))

SCHEMA = "ContradictionVerdict@v1"
LANE = "contradiction-adjudicator"
PROCESS_ID = "contradiction_adjudicator"
LLM_LANE = "deepseek-flash"
VERDICTS = ("LEFT", "RIGHT", "BOTH_STALE", "NOT_A_CONTRADICTION", "UNRESOLVED")
AUTHORITY = "READ_ONLY_ADVISORY"
PROMPT_VERSION = "adjudicate-v1"
MAX_ARTIFACT_CHARS = 1500

INSTRUCTION = (
    "You adjudicate whether two research artifacts about the same subject genuinely contradict each other, "
    "and if so which one better survives the evidence. Use ONLY the material given. Answer with one JSON object: "
    '{"verdict": "LEFT|RIGHT|BOTH_STALE|NOT_A_CONTRADICTION|UNRESOLVED", "confidence": 0.0-1.0, '
    '"rationale": "<= 80 words", "decisive_evidence_refs": ["..."], "what_would_resolve": "<= 30 words or empty"}. '
    "Never recommend sizing, orders, stops or weights. If the artifacts talk past each other (different horizons, "
    "different questions) answer NOT_A_CONTRADICTION. If both rest on evidence older than the other material, BOTH_STALE."
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


def verdicts_path(root: Path) -> Path:
    return root / "data" / "cio" / "contradiction_verdicts.jsonl"


def read_jsonl(path: Path, limit: int = 500_000) -> list[dict]:
    out: list[dict] = []
    try:
        with path.open(encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                if i >= limit:
                    break
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return out


def judged_ids(root: Path) -> set[str]:
    return {r.get("candidate_id") for r in read_jsonl(verdicts_path(root)) if r.get("candidate_id")}


def select_pairs(candidates: list[dict], *, already: set[str], max_pairs: int, now: _dt.datetime | None = None,
                 subjects_top_n: int = 20) -> list[dict]:
    """Pure: newest subjects first (consumer digest), then unjudged pairs in digest order, capped."""
    ranked: list[dict] = []
    try:
        import research_contradiction_consumer as rcc  # type: ignore
        dg = rcc.digest(candidates, now=now, top_n=subjects_top_n)
        order = [str(s.get("subject") or s.get("symbol") or "").upper() for s in dg.get("top_subjects") or []]
        by_sym: dict[str, list[dict]] = {}
        for c in candidates:
            for k in ("left_symbol", "right_symbol"):
                by_sym.setdefault(str(c.get(k) or "").upper(), []).append(c)
        for sym in order:
            ranked.extend(by_sym.get(sym, []))
    except Exception:  # noqa: BLE001
        ranked = []
    if not ranked:
        ranked = list(reversed(candidates))  # newest appended last
    out: list[dict] = []
    seen: set[str] = set()
    for c in ranked:
        cid = c.get("candidate_id")
        if not cid or cid in already or cid in seen or str(c.get("status") or "CANDIDATE") != "CANDIDATE":
            continue
        seen.add(cid)
        out.append(c)
        if len(out) >= max_pairs:
            break
    return out


def artifact_text(ref: str, root: Path, loaders) -> str:
    """Best-effort: the artifact's summary/recommendation from the research stores; the ref alone otherwise."""
    if not ref:
        return ""
    try:
        for fname in ("hermes_research_results.jsonl", "research_thesis_deltas.jsonl"):
            for r in read_jsonl(root / "data" / "cio" / fname, limit=200_000):
                rid = str(r.get("result_id") or r.get("research_id") or r.get("delta_id") or r.get("artifact_id") or "")
                if rid and rid == str(ref):
                    body = r.get("result") if isinstance(r.get("result"), dict) else r
                    return json.dumps({k: body.get(k) for k in ("summary", "recommendation", "classification", "evidence_as_of", "what_changed", "evidence") if body.get(k) is not None}, default=str)[:MAX_ARTIFACT_CHARS]
    except Exception:  # noqa: BLE001
        pass
    return f"[artifact {ref}: body not on file]"


def build_request(c: dict, left: str, right: str) -> dict:
    return {"candidate_id": c.get("candidate_id"), "left_symbol": c.get("left_symbol"), "right_symbol": c.get("right_symbol"),
            "shared_context": c.get("shared_context"), "opposition": c.get("opposition"),
            "left_artifact": {"id": c.get("left_artifact_id"), "text": left}, "right_artifact": {"id": c.get("right_artifact_id"), "text": right},
            "evidence_refs": list(c.get("evidence_refs") or [])[:20]}


def parse_verdict(text: str) -> dict:
    t = (text or "").strip()
    obj: dict = {}
    try:
        obj = json.loads(t)
    except Exception:  # noqa: BLE001
        s, e = t.find("{"), t.rfind("}")
        if s >= 0 and e > s:
            try:
                obj = json.loads(t[s:e + 1])
            except Exception:  # noqa: BLE001
                obj = {}
    v = str(obj.get("verdict") or "").upper()
    if v not in VERDICTS:
        return {"verdict": "UNRESOLVED", "confidence": 0.0, "rationale": "SCHEMA_INVALID: " + t[:200], "decisive_evidence_refs": [], "schema_invalid": True}
    try:
        conf = max(0.0, min(1.0, float(obj.get("confidence") or 0.0)))
    except (TypeError, ValueError):
        conf = 0.0
    return {"verdict": v, "confidence": conf, "rationale": str(obj.get("rationale") or "")[:600],
            "decisive_evidence_refs": [str(x) for x in (obj.get("decisive_evidence_refs") or [])][:10],
            "what_would_resolve": str(obj.get("what_would_resolve") or "")[:200]}


def tier2_gate(env: dict, now: _dt.datetime) -> str | None:
    """Why the paid judge may NOT run now (None = may). Fail-closed on unknown spend."""
    try:
        from tiered_validation import TierPolicy  # type: ignore
        pol = TierPolicy.from_env(env)
    except Exception as exc:  # noqa: BLE001
        return f"TIER_POLICY_UNAVAILABLE:{type(exc).__name__}"
    if not getattr(pol, "tier2_enabled", False):
        return "TIER2_DISABLED"
    spent = None
    try:
        from llm_consumption import ledger_paid_usd_today  # type: ignore
        spent = float(ledger_paid_usd_today(None))
    except Exception:  # noqa: BLE001
        spent = None
    return pol.tier2_denial(spent_today_usd=spent, now=now, judge_provider="deepseek")


def judge(request: dict, *, call_fn=None) -> tuple[str, dict]:
    """One governed call. call_fn(prompt) -> (text, provenance) is injectable for tests."""
    prompt = INSTRUCTION + "\n\n" + json.dumps(request, sort_keys=True, default=str)
    if call_fn is not None:
        return call_fn(prompt)
    from llm_consumption import gate_and_generate  # type: ignore
    res = gate_and_generate(prompt, lane=LLM_LANE, process_id=PROCESS_ID, task_summary=f"adjudicate {request.get('candidate_id')}",
                            response_json=True, max_tokens=600, return_provenance=True,
                            metadata={"candidate_id": request.get("candidate_id"), "prompt_version": PROMPT_VERSION})
    if isinstance(res, tuple):
        return str(res[0] or ""), dict(res[1] or {})
    return str(res or ""), {}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="adjudicate research contradiction candidates (paid judge, capped)")
    ap.add_argument("--apply", action="store_true", help="call the judge and append verdicts (default: dry run)")
    ap.add_argument("--max-pairs", type=int, default=20)
    ap.add_argument("--root")
    ap.add_argument("--scan-max-lines", type=int, default=400_000)
    a = ap.parse_args(argv)
    env = dict(os.environ)
    root = Path(a.root) if a.root else state_root(env)
    now = _now()
    cands = [r for r in read_jsonl(root / "data" / "cio" / "research_contradiction_candidates.jsonl", limit=a.scan_max_lines)
             if r.get("schema") == "ResearchContradictionCandidate@v1"]
    already = judged_ids(root)
    pairs = select_pairs(cands, already=already, max_pairs=a.max_pairs, now=now)
    gate = tier2_gate(env, now) if a.apply else None
    summary = {"schema": "AdjudicationRun@v1", "as_of": now.isoformat(), "candidates_scanned": len(cands), "already_judged": len(already),
               "selected": len(pairs), "mode": "apply" if a.apply else "dry_run", "tier2_gate": gate, "authority": AUTHORITY}
    print(json.dumps(summary, indent=1))
    for c in pairs[:10]:
        print(f"  {c.get('candidate_id')} {c.get('left_symbol')}/{c.get('right_symbol')} {json.dumps(c.get('opposition'))[:80]}")
    if not a.apply:
        return 0
    if gate:
        print(f"paid judge NOT consulted: {gate}")
        return 0
    loaders = None
    out_p = verdicts_path(root)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    written = failed = 0
    by_verdict: dict[str, int] = {}
    for c in pairs:
        req = build_request(c, artifact_text(c.get("left_artifact_id"), root, loaders), artifact_text(c.get("right_artifact_id"), root, loaders))
        try:
            text, prov = judge(req)
        except Exception as exc:  # noqa: BLE001 — deferred / cap / outage: stop the batch, nothing half-written
            print(f"judge stopped: {type(exc).__name__}: {str(exc)[:160]}")
            failed += 1
            break
        v = parse_verdict(text)
        row = {"schema": SCHEMA, "verdict_id": "cv_" + hashlib.sha256(f"{c.get('candidate_id')}|{PROMPT_VERSION}|{now.isoformat()}".encode()).hexdigest()[:16],
               "candidate_id": c.get("candidate_id"), "left_symbol": c.get("left_symbol"), "right_symbol": c.get("right_symbol"),
               "left_artifact_id": c.get("left_artifact_id"), "right_artifact_id": c.get("right_artifact_id"), **v,
               "provider": prov.get("provider") or "deepseek", "model": prov.get("model"), "cost_usd": prov.get("cost_usd") or prov.get("actual_usd"),
               "prompt_version": PROMPT_VERSION, "process_id": PROCESS_ID, "judged_at": _now().isoformat(),
               "authority": AUTHORITY, "memory_behavior_influence": 0, "financial_action": False}
        with out_p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
        written += 1
        by_verdict[v["verdict"]] = by_verdict.get(v["verdict"], 0) + 1
    latest = root / "data" / "runtime" / "contradiction_adjudicator_latest.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    tmp = latest.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({**summary, "written": written, "failed": failed, "by_verdict": by_verdict}, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, latest)
    print(json.dumps({"written": written, "failed": failed, "by_verdict": by_verdict}))
    try:
        import supervisor_heartbeat as hb  # type: ignore
        conn = None
        try:
            import db_adapter  # type: ignore
            conn = db_adapter._get_conn()
            with conn.cursor() as cur:
                cur.execute("SET app.tenant_id = 'tradeai:tenant:primary'")
        except Exception:  # noqa: BLE001
            conn = None
        print("heartbeat:", hb.beat(LANE, conn=conn, success=failed == 0, output_signal=True, work_claimed=len(pairs), work_done=written,
                                    work_failed=failed, root=root, env=env).get("pg"))
    except Exception as exc:  # noqa: BLE001
        print(f"heartbeat skipped: {type(exc).__name__}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
