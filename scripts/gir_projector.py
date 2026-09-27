#!/usr/bin/env python3
"""gir_projector.py — Global Intelligence Record projection v1 (02 §5), batch.

Projects EXISTING canonical stores into the `intelligence` schema (or, without Postgres, into a
dry-run JSON): entities, the eight-field envelope, and edges. Zero authority — canonical stores keep
their single writers; every row carries source_store / source_ref / idempotency_key so a re-run is
a no-op and the projection can be rebuilt from scratch at any time (the M2-projector pattern).

v1 sources and what they become
  identity registry (CONFIRMED securities)   → COMPANY:SECURITY entities `SEC:<security_guid>` (+ ISS:<issuer_guid>)
  cio_theses projection (symbol_* current)   → RESEARCH:THESIS `THESIS:<thesis_id>@v<n>`; edges SEC —HAS_THESIS→ THESIS,
                                               THESIS —SUPERSEDES→ prior version (from parent_version)
  instrument records (beliefs[])             → AGENT:BELIEF `BELIEF:<subject_key>:<belief_key>`; SEC —BELIEVES→ BELIEF
  holdings snapshot                          → edges ACCOUNT —HOLDS→ SEC (account nodes OPERATIONAL:ACCOUNT)
  contradiction candidates (streamed, capped)→ RISK:CONTRADICTION `CONTRA:<candidate_id>`; edges CONTRA —CONTRADICTS→ SEC
The "re-key": ticker-keyed rows (HELD:<tkr>, symbol slugs) are resolved to `SEC:` through the registry
HERE, in the projection — the canonical stores are not rewritten (no new writer of an authoritative store).

Dry-run by default: prints counts and writes data/runtime/gir_projection_dryrun.json.
``--apply`` upserts through db_adapter when `intelligence.gir_entity` exists (else exit 3).

Approval: pkg-20260927-cogx-w1-d9e1 items 3 and 6. Authority: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

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

VERSION = "GIR@v1"
TENANT = "tradeai:tenant:primary"
THESIS_SLA_H = 30 * 24


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _parse(ts):
    if not ts:
        return None
    try:
        t = _dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=_dt.timezone.utc)
    except ValueError:
        return None


def _idem(*parts) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:32]


def state_root(env: dict) -> Path:
    if env.get("TRADEAI_STATE_ROOT"):
        return Path(env["TRADEAI_STATE_ROOT"])
    try:
        from canonical_store_registry import production_state_root  # type: ignore
        return Path(production_state_root())
    except Exception:  # noqa: BLE001
        return Path.home() / "trade-ai-releases" / "persistent-state"


class Projection:
    def __init__(self, now: _dt.datetime, release_sha: str | None):
        self.now = now; self.sha = release_sha
        self.entities: dict[str, dict] = {}
        self.envelopes: dict[str, dict] = {}
        self.edges: dict[str, dict] = {}
        self.counts: dict[str, int] = {}

    def entity(self, guid, cls, kind, store, ref):
        if guid in self.entities:
            return
        self.entities[guid] = {"guid": guid, "class": cls, "kind": kind, "tenant_id": TENANT, "source_store": store,
                               "source_ref": str(ref), "source_sha": self.sha, "projection_version": VERSION,
                               "idempotency_key": _idem("E", guid, store, ref)}
        self.counts[f"entity:{cls}:{kind}"] = self.counts.get(f"entity:{cls}:{kind}", 0) + 1

    def envelope(self, guid, **fields):
        env = {"guid": guid, "tenant_id": TENANT, "memory": {}, "history": {}, "contradictions": {"state": "UNKNOWN"},
               "confidence": {"basis": "UNKNOWN"}, "lineage": {}, "ownership": {}, "freshness": {"state": "UNKNOWN"},
               "dependencies": {}, "projection_version": VERSION}
        env.update(fields)
        env["idempotency_key"] = _idem("V", guid, json.dumps({k: env[k] for k in ("memory", "history", "freshness", "confidence")}, sort_keys=True, default=str))
        self.envelopes[guid] = env

    def edge(self, f, t, rel, store, ref, valid_from=None):
        key = _idem("R", f, t, rel, ref)
        if key in self.edges:
            return
        self.edges[key] = {"from_guid": f, "to_guid": t, "relation": rel, "tenant_id": TENANT, "source_ref": str(ref),
                           "source_store": store, "valid_from": valid_from, "idempotency_key": key}
        self.counts[f"edge:{rel}"] = self.counts.get(f"edge:{rel}", 0) + 1


def build(root: Path, *, now: _dt.datetime | None = None, env: dict | None = None, contra_max_lines: int = 200_000) -> Projection:
    env = os.environ if env is None else env
    now = now or _now()
    pj = Projection(now, env.get("TRADEAI_RELEASE_SHA"))
    data = root / "data"
    # 1. identity registry
    reg_p = Path(env.get("TRADEAI_IDENTITY_REGISTRY") or data / "runtime" / "identity_registry.json")
    reg = json.loads(reg_p.read_text(encoding="utf-8")) if reg_p.exists() else {"entities": {}, "by_symbol": {}}
    by_symbol: dict[str, str] = {}
    for guid, e in (reg.get("entities") or {}).items():
        if not isinstance(e, dict) or not e.get("security_guid"):
            continue
        sec = f"SEC:{e['security_guid']}"
        pj.entity(sec, "COMPANY", "SECURITY", "identity_registry", e["security_guid"])
        pj.envelope(sec, memory={"ticker_alias": e.get("ticker_alias"), "identity_status": e.get("identity_status")},
                    history={"first_seen": e.get("first_seen"), "last_seen": e.get("last_seen"), "supersedes": e.get("supersedes") or []},
                    lineage={"produced_by": "mint_identity_registry", "record": e.get("subject_guid")},
                    ownership={"writer": "scripts/mint_identity_registry.py", "registry_row": "identity"},
                    freshness={"as_of": e.get("last_seen"), "state": "CURRENT" if e.get("active") else "STALE"},
                    confidence={"basis": "DECLARED", "score": 1.0 if e.get("identity_status") == "CONFIRMED" else 0.5})
        if e.get("issuer_guid"):
            iss = f"ISS:{e['issuer_guid']}"
            pj.entity(iss, "COMPANY", "ISSUER", "identity_registry", e["issuer_guid"])
            pj.edge(iss, sec, "ISSUES", "identity_registry", e["security_guid"])
        for alias in [e.get("ticker_alias")] + list(e.get("aliases") or []):
            if alias:
                by_symbol.setdefault(str(alias).upper(), sec)
    pj.counts["symbols_resolvable"] = len(by_symbol)

    def sec_for(symbol: str | None) -> str | None:
        return by_symbol.get(str(symbol or "").upper())

    # 2. symbol theses
    th_p = data / "cio" / "cio_theses_projection.json"
    if th_p.exists():
        cur = (json.loads(th_p.read_text(encoding="utf-8")).get("current") or {})
        unresolved = 0
        for tid, rec in cur.items():
            if not str(tid).startswith("symbol_") or not isinstance(rec, dict):
                continue
            sym = rec.get("symbol") or str(tid)[len("symbol_"):].upper()
            ver = rec.get("version")
            tg = f"THESIS:{tid}@v{ver}"
            pj.entity(tg, "RESEARCH", "THESIS", "cio_theses", f"{tid}@v{ver}")
            upd = rec.get("updated_ts") or rec.get("published_ts")
            age_h = ((now - _parse(upd)).total_seconds() / 3600) if _parse(upd) else None
            pj.envelope(tg, memory={"stance": rec.get("stance"), "summary": (rec.get("summary") or "")[:500], "status": rec.get("status"),
                                    "evidence_for_n": len(rec.get("evidence_for") or []), "counter_evidence_n": len(rec.get("counter_evidence") or []),
                                    "invalidation_n": len(rec.get("invalidation_conditions") or [])},
                        history={"version": ver, "parent_version": rec.get("parent_version"), "created": rec.get("created_ts"), "updated": upd},
                        lineage={"produced_by": rec.get("source_lane"), "research_id": rec.get("source_research_id"), "evidence_refs": rec.get("evidence_refs") or []},
                        ownership={"writer": "scripts/lib/research_thesis_delta.py:accept_research_result", "owner_agent": rec.get("owner_agent")},
                        freshness={"as_of": upd, "age_hours": age_h, "sla_hours": THESIS_SLA_H,
                                   "state": "UNKNOWN" if age_h is None else ("CURRENT" if age_h <= THESIS_SLA_H else "STALE")},
                        confidence={"basis": "DECLARED", "grade": rec.get("substantiveness_grade")},
                        dependencies={"symbol": sym})
            sec = sec_for(sym)
            if sec:
                pj.edge(sec, tg, "HAS_THESIS", "cio_theses", f"{tid}@v{ver}", upd)
            else:
                unresolved += 1
            if rec.get("parent_version"):
                pj.edge(tg, f"THESIS:{tid}@v{rec['parent_version']}", "SUPERSEDES", "cio_theses", f"{tid}@v{ver}", upd)
        pj.counts["theses_symbol_unresolved"] = unresolved

    # 3. instrument records → beliefs (re-keyed HELD:<tkr> → SEC:)
    ir_p = data / "cio" / "cio_instrument_records.jsonl"
    if ir_p.exists():
        last: dict[str, dict] = {}
        for line in ir_p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    r = json.loads(line); last[r.get("subject_key")] = r
                except json.JSONDecodeError:
                    continue
        rekeyed = 0
        for key, r in last.items():
            kind, _, name = str(key).partition(":")
            sec = sec_for(name) if kind in ("HELD", "EXIT", "WATCH") else None
            if sec:
                rekeyed += 1
            for b in r.get("beliefs") or []:
                if not isinstance(b, dict):
                    continue
                bg = f"BELIEF:{key}:{b.get('belief_key')}"
                pj.entity(bg, "AGENT", "BELIEF", "cio_instrument_records", f"{key}:{b.get('belief_key')}:r{b.get('revision')}")
                n = int(b.get("sample_size") or 0)
                pj.envelope(bg, memory={"recommendation": b.get("recommendation"), "population": b.get("population"), "horizon": b.get("horizon"), "success_rate": b.get("success_rate")},
                            history={"revision": b.get("revision"), "as_of": b.get("as_of")},
                            confidence={"basis": "CALIBRATED" if n >= 5 else "EVIDENCE_COUNT", "n_outcomes": n, "score": b.get("success_rate")},
                            lineage={"produced_by": "cio_belief_writer", "outcome_ids": b.get("outcome_ids") or []},
                            ownership={"writer": "scripts/lib/cio_belief_writer.py:apply_belief"},
                            freshness={"as_of": b.get("as_of"), "state": "CURRENT"},
                            dependencies={"subject_key": key, "security_guid": sec})
                if sec:
                    pj.edge(sec, bg, "BELIEVES", "cio_instrument_records", f"{key}:{b.get('belief_key')}", b.get("as_of"))
        pj.counts["instrument_records"] = len(last); pj.counts["instrument_records_rekeyed_to_sec"] = rekeyed

    # 4. holdings → HOLDS edges
    h_p = data / "cio" / "holdings_snapshot_latest.json"
    if h_p.exists():
        h = json.loads(h_p.read_text(encoding="utf-8"))
        unresolved = 0
        for row in h.get("holdings") or []:
            acct = f"ACCOUNT:{row.get('account')}"
            pj.entity(acct, "OPERATIONAL", "ACCOUNT", "holdings_snapshot", row.get("account"))
            sec = sec_for(row.get("symbol"))
            if sec:
                pj.edge(acct, sec, "HOLDS", "holdings_snapshot", f"{row.get('account')}:{row.get('symbol')}", row.get("updated_at"))
            else:
                unresolved += 1
        pj.counts["holdings_symbol_unresolved"] = unresolved

    # 5. contradiction candidates (streamed, capped)
    c_p = data / "cio" / "research_contradiction_candidates.jsonl"
    if c_p.exists():
        n = 0
        with c_p.open("r", encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                if i >= contra_max_lines:
                    pj.counts["contradictions_capped_at"] = contra_max_lines; break
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get("schema") != "ResearchContradictionCandidate@v1":
                    continue
                cg = f"CONTRA:{r.get('candidate_id')}"
                pj.entity(cg, "RISK", "CONTRADICTION", "research_contradiction_candidates", r.get("candidate_id"))
                for sym in {r.get("left_symbol"), r.get("right_symbol")}:
                    sec = sec_for(sym)
                    if sec:
                        pj.edge(cg, sec, "CONTRADICTS", "research_contradiction_candidates", r.get("candidate_id"))
                n += 1
        pj.counts["contradictions_projected"] = n
    return pj


def apply(pj: Projection) -> dict:
    import db_adapter  # type: ignore
    conn = db_adapter._get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('intelligence.gir_entity')")
        if cur.fetchone()[0] is None:
            raise RuntimeError("intelligence.gir_entity absent — apply migrations/2026_09_27_intelligence_v1.sql first")
        cur.execute("SET LOCAL app.tenant_id = %s", (TENANT,))
        for e in pj.entities.values():
            cur.execute("""INSERT INTO intelligence.gir_entity (guid,class,kind,tenant_id,source_store,source_ref,source_sha,projected_at,projection_version,idempotency_key)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,now(),%s,%s) ON CONFLICT (guid) DO UPDATE SET source_ref=EXCLUDED.source_ref, source_sha=EXCLUDED.source_sha, projected_at=now()""",
                        (e["guid"], e["class"], e["kind"], e["tenant_id"], e["source_store"], e["source_ref"], e["source_sha"], e["projection_version"], e["idempotency_key"]))
        for v in pj.envelopes.values():
            cur.execute("""INSERT INTO intelligence.gir_envelope (guid,tenant_id,memory,history,contradictions,confidence,lineage,ownership,freshness,dependencies,projected_at,projection_version,idempotency_key)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),%s,%s)
                           ON CONFLICT (guid) DO UPDATE SET memory=EXCLUDED.memory, history=EXCLUDED.history, contradictions=EXCLUDED.contradictions, confidence=EXCLUDED.confidence,
                           lineage=EXCLUDED.lineage, ownership=EXCLUDED.ownership, freshness=EXCLUDED.freshness, dependencies=EXCLUDED.dependencies, projected_at=now(), idempotency_key=EXCLUDED.idempotency_key""",
                        (v["guid"], v["tenant_id"], *[json.dumps(v[k], default=str) for k in ("memory", "history", "contradictions", "confidence", "lineage", "ownership", "freshness", "dependencies")], v["projection_version"], v["idempotency_key"]))
        for r in pj.edges.values():
            cur.execute("""INSERT INTO intelligence.gir_edge (tenant_id,from_guid,to_guid,relation,valid_period,source_ref,source_store,projected_at,idempotency_key)
                           VALUES (%s,%s,%s,%s,tstzrange(COALESCE(%s::timestamptz, now()), NULL, '[)'),%s,%s,now(),%s) ON CONFLICT (idempotency_key) DO NOTHING""",
                        (r["tenant_id"], r["from_guid"], r["to_guid"], r["relation"], r["valid_from"], r["source_ref"], r["source_store"], r["idempotency_key"]))
    conn.commit()
    return {"entities": len(pj.entities), "envelopes": len(pj.envelopes), "edges": len(pj.edges)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", help="state root (default: production persistent-state)")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--out", help="dry-run JSON (default data/runtime/gir_projection_dryrun.json under --root or cwd)")
    ap.add_argument("--contra-max-lines", type=int, default=200_000)
    a = ap.parse_args()
    root = Path(a.root) if a.root else state_root(os.environ)
    pj = build(root, contra_max_lines=a.contra_max_lines)
    summary = {"schema": "GirProjectionRun@v1", "as_of": pj.now.isoformat(), "root": str(root), "entities": len(pj.entities),
               "envelopes": len(pj.envelopes), "edges": len(pj.edges), "counts": pj.counts, "authority": "READ_ONLY_ADVISORY"}
    print(json.dumps(summary, indent=1))
    if a.apply:
        try:
            print(json.dumps({"applied": apply(pj)}))
        except Exception as exc:  # noqa: BLE001
            print(f"apply failed: {type(exc).__name__}: {exc}", file=sys.stderr); return 3
    else:
        out = Path(a.out) if a.out else (Path.cwd() / "data" / "runtime" / "gir_projection_dryrun.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({**summary, "sample_entities": list(pj.entities.values())[:5], "sample_edges": list(pj.edges.values())[:5]}, indent=1, default=str) + "\n")
        print(f"dry run: wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
