#!/usr/bin/env python3
"""Incident ledger CLI for agents — open, update, fix, block, list, show (IncidentRecord@v1).

Operator 2026-10-27: an agent that hits an error "can't just drop and leave it … fix it and report it somewhere in a
log that you could come back in as a coordinator and look at it." This is that log. One writer:
scripts/lib/incidents.py. Store: <persistent-state>/data/coordination/incidents/ (TRADEAI_INCIDENTS_DIR overrides;
tests always set it). Doc: docs/ops/INCIDENT_LEDGER.md.

  incident.py open  --title "..." --where scripts/x.py --source agent --session $AGENT_CLAIM_SESSION [--job J] [--evidence E ...]
  incident.py update INC-… --note "trying X" [--status fixing] [--owner S]
  incident.py fix    INC-… --ref pr:2232 [--ref commit:<sha>] [--note "..."]
  incident.py block  INC-… --reason "needs grant" --handoff "operator: …"
  incident.py list   [--status open,fixing] [--session S] [--json]
  incident.py show   INC-… [--json]
  incident.py rebuild-index
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.lib import incidents as L  # noqa: E402


def _session(a) -> str:
    return a.session or os.environ.get("AGENT_CLAIM_SESSION") or ""


def _print(rec, as_json: bool) -> None:
    if as_json:
        print(json.dumps(rec, indent=1, default=str))
        return
    print(f"{rec['id']}  [{rec['status']}]  {rec['title']}")
    print(f"  opened {rec['opened_at']}  source {rec['source']}  owner {rec.get('owner') or '-'}")
    if rec.get("where"):
        print(f"  where  {rec['where']}")
    for e in rec.get("evidence") or []:
        print(f"  evidence {e}")
    for a in rec.get("attempts") or []:
        print(f"  attempt {a.get('at')} {a.get('actor')} {a.get('action')}: {a.get('result')}")
    for r in rec.get("fix_refs") or []:
        print(f"  fix_ref {r['kind']}:{r['ref']}")
    if rec.get("blocked_reason"):
        print(f"  blocked {rec['blocked_reason']} -> handoff: {rec.get('handoff')}")


def seed(doc: dict, d: Path, *, apply: bool) -> list[dict]:
    """Open each seed row at its own ``opened_at`` and mark it fixed at ``fixed_at``; skip a known fingerprint."""
    known = {r.get("fingerprint") for r in L.load_records(d).values()}
    out = []
    for row in doc.get("incidents") or []:
        fp = row["fingerprint"]
        if fp in known:
            out.append({"fingerprint": fp, "action": "skip_existing"})
            continue
        if not apply:
            out.append({"fingerprint": fp, "action": "would_seed", "title": row["title"]})
            continue
        opened = L.parse_ts(row["opened_at"])
        rec, _ = L.open_incident(source=row["source"], title=row["title"], where=row.get("where", ""),
                                 evidence=row.get("evidence"), fingerprint=fp, severity=row.get("severity", "P2"),
                                 actor="seed:incident-ledger-20261027", note="seeded history (2026-10-27)", d=d, now=opened)
        rec = L.fix(rec["id"], actor="seed:incident-ledger-20261027", fix_refs=row["fix_refs"], note=row.get("note"),
                    d=d, now=L.parse_ts(row.get("fixed_at")) or L.utcnow())
        out.append({"fingerprint": fp, "action": "seeded", "id": rec["id"], "status": rec["status"]})
    return out


def _seed(a, d: Path) -> int:
    doc = json.loads(Path(a.file).read_text(encoding="utf-8"))
    for row in seed(doc, d, apply=a.apply):
        print(json.dumps(row))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("open")
    o.add_argument("--title", required=True)
    o.add_argument("--where", default="")
    o.add_argument("--source", default="agent", choices=L.SOURCE_KINDS)
    o.add_argument("--session", default=None)
    o.add_argument("--agent", default=None)
    o.add_argument("--job", default=None)
    o.add_argument("--lane", default=None)
    o.add_argument("--evidence", nargs="*", default=[])
    o.add_argument("--owner", default=None)
    o.add_argument("--severity", default="P2", choices=["P1", "P2", "P3"])
    o.add_argument("--fingerprint", default=None)
    o.add_argument("--note", default=None)
    u = sub.add_parser("update")
    u.add_argument("id")
    u.add_argument("--note", default=None)
    u.add_argument("--status", choices=["open", "fixing"], default=None)
    u.add_argument("--owner", default=None)
    u.add_argument("--evidence", nargs="*", default=None)
    u.add_argument("--session", default=None)
    f = sub.add_parser("fix")
    f.add_argument("id")
    f.add_argument("--ref", action="append", required=True, help="pr:N | #N | commit:SHA | receipt:PATH | doc:PATH")
    f.add_argument("--note", default=None)
    f.add_argument("--session", default=None)
    b = sub.add_parser("block")
    b.add_argument("id")
    b.add_argument("--reason", required=True)
    b.add_argument("--handoff", required=True, help="the exact next step for whoever picks this up")
    b.add_argument("--session", default=None)
    ls = sub.add_parser("list")
    ls.add_argument("--status", default="open,fixing,blocked")
    ls.add_argument("--session", default=None)
    ls.add_argument("--json", action="store_true")
    sh = sub.add_parser("show")
    sh.add_argument("id")
    sh.add_argument("--json", action="store_true")
    sub.add_parser("rebuild-index")
    sd = sub.add_parser("seed", help="import historical incidents (idempotent by fingerprint); dry run unless --apply")
    sd.add_argument("--file", required=True)
    sd.add_argument("--apply", action="store_true")
    for p in (o, u, f, b):
        p.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    d = L.incidents_dir()
    try:
        if a.cmd == "open":
            sess = _session(a)
            src = {k: v for k, v in {"kind": a.source, "session": sess or None, "agent": a.agent, "job": a.job,
                                     "lane": a.lane}.items() if v}
            rec, created = L.open_incident(source=src, title=a.title, where=a.where, evidence=a.evidence,
                                           owner=a.owner or sess, fingerprint=a.fingerprint, severity=a.severity,
                                           actor=sess or a.source, note=a.note, d=d)
            if not a.json:
                print(("opened " if created else "already open (same fingerprint) ") + rec["id"])
            else:
                _print(rec, True)
            return 0
        if a.cmd == "update":
            rec = L.update(a.id, actor=_session(a) or "agent", note=a.note, status=a.status, owner=a.owner,
                           evidence=a.evidence, d=d)
        elif a.cmd == "fix":
            rec = L.fix(a.id, actor=_session(a) or "agent", fix_refs=[L.parse_ref(r) for r in a.ref], note=a.note, d=d)
        elif a.cmd == "block":
            rec = L.block(a.id, actor=_session(a) or "agent", blocked_reason=a.reason, handoff=a.handoff, d=d)
        elif a.cmd == "list":
            want = {s.strip() for s in a.status.split(",") if s.strip()}
            rows = [r for r in L.load_records(d).values() if r["status"] in want or "all" in want]
            if a.session:
                rows = [r for r in rows if (r.get("source") or {}).get("session") == a.session or r.get("owner") == a.session]
            rows.sort(key=lambda r: r["opened_at"])
            if a.json:
                print(json.dumps(rows, indent=1, default=str))
            else:
                for r in rows:
                    print(f"{r['id']}  [{r['status']:7}] {r['opened_at']}  {r['title'][:100]}")
                print(f"{len(rows)} incident(s)")
            return 0
        elif a.cmd == "show":
            rec = L.load_records(d).get(a.id)
            if not rec:
                print(f"no such incident {a.id}", file=sys.stderr)
                return 2
        elif a.cmd == "seed":
            return _seed(a, d)
        else:
            idx = L.rebuild_index(d)
            print(json.dumps(idx["summary"]))
            return 0
    except L.LedgerError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    _print(rec, getattr(a, "json", False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
