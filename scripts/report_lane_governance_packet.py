#!/usr/bin/env python3
"""report_lane_governance_packet.py — the weekly (or monthly) per-lane governance packet.

Phase 2 PR-E (2026-10-08, docs/implementation/n8n-parallel/14-execution-week-20261008.md). Renders a packet
from facts that already exist on this host — it probes nothing new:

  lanes      config/lane_registry.json rows measured by scripts.lib.lane_registry.collect_lane_registry_report
             (the same LIVE / SILENT / UNVERIFIABLE verdicts check_lane_registry --state-drift reports)
  ledger     coordination receipts per lane and state from scripts.lib.n8n_coordination_projection.project
  incidents  data/runtime/n8n_incident_fanin_last.json counts by source and severity
  releases   ~/.local/state/cio-phase2-exact-main/deploy_receipt.json (+ the conformance gate receipt when present)
  retention  the last block of logs/db_retention.log and data/runtime/db_hygiene_last.json findings

    python3 scripts/report_lane_governance_packet.py --dry-run --period weekly      # prints the section counts
    python3 scripts/report_lane_governance_packet.py --write --period weekly        # json + md + receipt
    python3 scripts/report_lane_governance_packet.py --write --draft --draft-mode fixture:valid   # model job on fixtures

Outputs (under TRADEAI_STATE_ROOT): data/governance/lane_governance_packet_<period>_<key>.json and .md, and the
receipt data/runtime/lane_governance_packet_last.json (LaneGovernancePacket@v1). The receipt is the artifact the
governed model job reads for the ops-summary DRAFT (output contract ops_summary_draft/v1); the draft is written to
data/governance/ops_summary_draft_<period>_<key>.json. No lane carries the draft yet (the material-change-digest
pilot contract is for detected material changes, not ops summaries): the receipt says so instead of inventing one.

AUTHORITY: READ_ONLY_ADVISORY. No send, no canonical write, no scheduler change.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.lib import n8n_coordination_projection as _proj  # noqa: E402
from scripts.lib import n8n_model_job as _mj  # noqa: E402
from scripts.lib.lane_registry import collect_lane_registry_report  # noqa: E402

SCHEMA = "LaneGovernancePacket@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
RECEIPT_REL = "data/runtime/lane_governance_packet_last.json"
OPS_SCHEMA_ID = "ops_summary_draft/v1"
OPS_PROCESS_ID = "n8n_ops_summary_draft"
NO_LANE_NOTE = ("no lane for ops summary yet: the material-change-digest pilot contract covers detected material "
                "changes only; the draft is an artifact under data/governance and is not posted as a coordination event")
NO_CONSUMER_REASON = ("lane lane-governance-packet-weekly is NEVER_SCHEDULED until the operator grants its cron line; "
                      "read by the operator and by the governed ops-summary model job; never a send")


def state_root() -> Path:
    return Path(os.environ.get("TRADEAI_STATE_ROOT") or ROOT)


def period_key(now: _dt.datetime, period: str) -> str:
    if period == "monthly":
        return now.strftime("%Y-%m")
    iso = now.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _load(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ── sections ──────────────────────────────────────────────────────────────────────────────────────

def lanes_section(*, now: _dt.datetime, registry_path: Optional[Path], root: Path, cron_text: Optional[str],
                  include_systemd: bool) -> dict[str, Any]:
    rep = collect_lane_registry_report(now=now, registry_path=registry_path, root=root, cron_text=cron_text,
                                       include_systemd=include_systemd)
    by_state: Counter = Counter(str(r.get("state") or "") for r in rep.get("lanes") or [])
    return {"declared": rep.get("declared"), "verdict_counts": rep.get("verdict_counts") or {},
            "by_declared_state": dict(by_state), "summary": rep.get("summary"),
            "findings": [{"lane_id": f.get("lane_id"), "verdict": f.get("verdict"), "detail": str(f.get("detail") or "")[:160]}
                         for f in rep.get("findings") or []][:200],
            "undeclared": len(rep.get("undeclared") or []), "registry_path": rep.get("registry_path")}


def ledger_section(*, ledger: Optional[Path], now: _dt.datetime) -> dict[str, Any]:
    out = _proj.project(ledger, limit=500, now=now)
    status = out.get("status")
    per_lane: dict[str, Counter] = {}
    refusals: Counter = Counter()
    for it in out.get("items") or []:
        lane = str(it.get("lane_id") or "?")
        per_lane.setdefault(lane, Counter())[str(it.get("state") or "?")] += 1
        if str(it.get("state") or "") == "REFUSED":
            refusals[str(it.get("reason") or "unspecified")] += 1
    return {"status": status, "ledger": out.get("ledger"), "count": out.get("count", 0),
            "per_lane": {k: dict(v) for k, v in sorted(per_lane.items())},
            "by_state": dict(sum((v for v in per_lane.values()), Counter())),
            "refusal_reasons": dict(refusals)}


def incidents_section(root: Path) -> dict[str, Any]:
    doc = _load(root / "data" / "runtime" / "n8n_incident_fanin_last.json")
    if not doc:
        return {"status": "NO_RECEIPT", "open": 0, "by_severity": {}, "by_source": {}}
    rows = doc.get("incidents") or []
    return {"status": "OK", "as_of": doc.get("as_of"), "open": doc.get("open", len(rows)),
            "by_severity": doc.get("by_severity") or dict(Counter(str(r.get("severity")) for r in rows)),
            "by_source": dict(Counter(str(r.get("source")) for r in rows)),
            "recovered": len(doc.get("recovered") or []), "source_notes": doc.get("source_notes")}


def releases_section(state_dir: Optional[Path], root: Path) -> dict[str, Any]:
    sd = state_dir or Path(os.environ.get("TRADEAI_DEPLOY_STATE_DIR") or (Path.home() / ".local/state/cio-phase2-exact-main"))
    dep = _load(sd / "deploy_receipt.json") or {}
    ci = _load(sd / "post_merge_ci.json") or {}
    conf = _load(root / "data" / "governance" / "platform_conformance_latest.json") or {}
    return {"deployed_sha": dep.get("deployed_sha"), "at": dep.get("at"), "ok": dep.get("ok"), "source_pr": dep.get("source_pr"),
            "prev_release": dep.get("prev_release"), "release_dir": dep.get("release_dir"), "rolled_back": dep.get("rolled_back"),
            "post_merge_ci_ok": ci.get("ok"),
            "conformance": {"as_of": conf.get("as_of") or conf.get("ts"), "verdict": conf.get("verdict") or conf.get("overall"),
                            "silos_below": conf.get("silos_below") or conf.get("below_floor")} if conf else None}


_RET_HEADER = re.compile(r"^DB Retention Policy — (?P<when>.+)$", re.M)
_RET_TOTAL = re.compile(r"Total (?:deleted|would delete): (?P<rows>[\d,]+) rows(?:; archived first: (?P<arch>[\d,]+))?")
_RET_PRUNED = re.compile(r"Total (?:pruned|would prune): (?P<files>[\d,]+) files")
_RET_NOT = re.compile(r"RETENTION NOT ENFORCED on (?P<n>\d+) table")


def parse_retention_log(text: str) -> dict[str, Any]:
    """The LAST run block of logs/db_retention.log: header date, totals, unenforced tables."""
    blocks = [m.start() for m in _RET_HEADER.finditer(text)] if text else []
    if not blocks:
        return {"status": "NO_RUN"}
    last = text[blocks[-1]:]
    head = _RET_HEADER.match(last.splitlines()[0])
    tot = _RET_TOTAL.search(last)
    pr = _RET_PRUNED.search(last)
    ne = _RET_NOT.search(last)
    return {"status": "OK", "ran_at": head.group("when") if head else None,
            "rows_deleted": int(tot.group("rows").replace(",", "")) if tot else None,
            "rows_archived_first": int(tot.group("arch").replace(",", "")) if tot and tot.group("arch") else 0,
            "files_pruned": int(pr.group("files").replace(",", "")) if pr else None,
            "tables_not_enforced": int(ne.group("n")) if ne else 0,
            "dry_run": bool(tot and "would delete" in tot.group(0))}


def retention_section(root: Path, log_path: Optional[Path]) -> dict[str, Any]:
    lp = log_path or (ROOT / "logs" / "db_retention.log")
    try:
        text = lp.read_text(encoding="utf-8", errors="replace")[-200_000:]
    except OSError:
        text = ""
    last_run = parse_retention_log(text)
    hyg = _load(root / "data" / "runtime" / "db_hygiene_last.json") or {}
    findings = hyg.get("findings") or []
    return {"last_run": last_run, "hygiene": {"as_of": hyg.get("as_of"), "ok": hyg.get("ok"), "db_gb": (hyg.get("db_bytes") or 0) / 1e9 if hyg.get("db_bytes") else hyg.get("db_gb"),
                                             "findings": len(findings), "by_code": hyg.get("by_code") or dict(Counter(str(f.get("code")) for f in findings)),
                                             "items": [f"{f.get('severity')} {f.get('code')} {f.get('item')}" for f in findings][:40]}}


# ── packet ────────────────────────────────────────────────────────────────────────────────────────

def build_packet(*, now: _dt.datetime, period: str, root: Path, registry_path: Optional[Path] = None,
                 cron_text: Optional[str] = None, include_systemd: bool = True, ledger: Optional[Path] = None,
                 deploy_state_dir: Optional[Path] = None, retention_log: Optional[Path] = None,
                 served_sha: Optional[str] = None) -> dict[str, Any]:
    key = period_key(now, period)
    packet = {"schema": SCHEMA, "authority": AUTHORITY, "period": period, "period_key": key, "as_of": now.isoformat(),
              "served_sha": served_sha or os.environ.get("TRADEAI_SERVED_SHA") or None, "state_root": str(root),
              "sections": {
                  "lanes": lanes_section(now=now, registry_path=registry_path, root=root, cron_text=cron_text, include_systemd=include_systemd),
                  "ledger": ledger_section(ledger=ledger, now=now),
                  "incidents": incidents_section(root),
                  "releases": releases_section(deploy_state_dir, root),
                  "retention": retention_section(root, retention_log),
              }}
    packet["summary"] = summary_counts(packet)
    return packet


def summary_counts(packet: Mapping[str, Any]) -> dict[str, Any]:
    s = packet["sections"]
    return {"lanes_declared": s["lanes"].get("declared"), "lane_verdicts": s["lanes"].get("verdict_counts"),
            "ledger_by_state": s["ledger"].get("by_state"), "ledger_refusals": s["ledger"].get("refusal_reasons"),
            "incidents_open": s["incidents"].get("open"), "incidents_by_severity": s["incidents"].get("by_severity"),
            "release": {"sha": s["releases"].get("deployed_sha"), "at": s["releases"].get("at"), "ok": s["releases"].get("ok")},
            "retention_last_run": {k: s["retention"]["last_run"].get(k) for k in ("ran_at", "rows_deleted", "rows_archived_first", "tables_not_enforced")},
            "hygiene_findings": s["retention"]["hygiene"].get("findings")}


def render_markdown(packet: Mapping[str, Any]) -> str:
    s = packet["sections"]; sm = packet["summary"]
    lines = [f"# Lane governance packet — {packet['period']} {packet['period_key']}", "",
             f"as_of {packet['as_of']} · served {packet.get('served_sha') or 'unknown'} · authority {AUTHORITY}", "",
             "## Lanes", f"declared {sm['lanes_declared']}; verdicts {json.dumps(sm['lane_verdicts'])}; undeclared {s['lanes'].get('undeclared')}", ""]
    for f in s["lanes"].get("findings") or []:
        lines.append(f"- {f['verdict']} `{f['lane_id']}` — {f['detail']}")
    lines += ["", "## Coordination ledger", f"status {s['ledger'].get('status')}; receipts {s['ledger'].get('count')}; by state {json.dumps(sm['ledger_by_state'])}; refusals {json.dumps(sm['ledger_refusals'])}", ""]
    for lane, c in (s["ledger"].get("per_lane") or {}).items():
        lines.append(f"- `{lane}`: {json.dumps(c)}")
    lines += ["", "## Incidents (fan-in)", f"open {sm['incidents_open']}; by severity {json.dumps(sm['incidents_by_severity'])}; by source {json.dumps(s['incidents'].get('by_source'))}", "",
              "## Releases", f"deployed {sm['release']['sha']} at {sm['release']['at']} ok={sm['release']['ok']} (PR {s['releases'].get('source_pr')}); post-merge CI ok={s['releases'].get('post_merge_ci_ok')}", ""]
    conf = s["releases"].get("conformance")
    if conf:
        lines.append(f"conformance {conf.get('verdict')} as_of {conf.get('as_of')}; silos below floor: {len(conf.get('silos_below') or [])}")
    r = s["retention"]["last_run"]; h = s["retention"]["hygiene"]
    lines += ["", "## Retention", f"last run {r.get('ran_at')}: deleted {r.get('rows_deleted')} rows (archived first {r.get('rows_archived_first')}), pruned {r.get('files_pruned')} files, not enforced {r.get('tables_not_enforced')}",
              f"hygiene as_of {h.get('as_of')}: {h.get('findings')} findings {json.dumps(h.get('by_code'))}", ""]
    for it in h.get("items") or []:
        lines.append(f"- {it}")
    lines += ["", "_Read-only packet. No lane sends it; the governed ops-summary draft (if any) is a separate artifact._", ""]
    return "\n".join(lines)


def write_packet(packet: Mapping[str, Any], *, root: Path) -> dict[str, str]:
    gov = root / "data" / "governance"; rt = root / "data" / "runtime"
    gov.mkdir(parents=True, exist_ok=True); rt.mkdir(parents=True, exist_ok=True)
    base = f"lane_governance_packet_{packet['period']}_{packet['period_key']}"
    pj = gov / f"{base}.json"; pm = gov / f"{base}.md"
    pj.write_text(json.dumps(packet, indent=2, default=str) + "\n", encoding="utf-8")
    pm.write_text(render_markdown(packet), encoding="utf-8")
    receipt = {"schema": SCHEMA, "authority": AUTHORITY, "mode": "write", "as_of": packet["as_of"], "period": packet["period"],
               "period_key": packet["period_key"], "served_sha": packet.get("served_sha"), "packet_json": str(pj), "packet_md": str(pm),
               "packet_sha256": hashlib.sha256(pj.read_bytes()).hexdigest(), "summary": packet["summary"], "ops_summary": None,
               "no_consumer_reason": NO_CONSUMER_REASON}
    rp = root / RECEIPT_REL
    rp.write_text(json.dumps(receipt, indent=2, default=str) + "\n", encoding="utf-8")
    return {"json": str(pj), "md": str(pm), "receipt": str(rp)}


# ── model job #1: ops summary DRAFT from the packet receipt ─────────────────────────────────────────

FIXTURE_ANSWER = {"headline": "Weekly ops summary draft (fixture)",
                  "sections": [{"area": "lanes", "summary": "fixture", "evidence_ids": ["lanes"]}],
                  "open_items": ["fixture"], "sources_cited": ["lane_governance_packet_last.json"],
                  "confidence_note": "fixture answer; not a live model call", "recommendation": "NONE"}


def fixture_call(mode: str) -> Callable[..., dict[str, Any]]:
    """Held-out modes: valid | invalid_json | over_cap | outage | schema_invalid. Never a network call."""
    def call(messages, *, process_id, response_format, request_id):
        base = {"governance_pass": True, "process_id": process_id, "reservation_id": 0, "cost_estimate": 0.0,
                "model_id": "fixture", "provider": "fixture", "mock": True, "usage": {"total_tokens": 0}}
        if mode == "over_cap":
            return {"error": {"code": "DAILY_CAP_EXCEEDED", "status": 429}, "governance_pass": False}
        if mode == "outage":
            return {"error": {"code": "PROVIDER_UNAVAILABLE", "status": 503}, "governance_pass": False}
        if mode == "invalid_json":
            return dict(base, choices=[{"message": {"content": "{not json"}}])
        if mode == "schema_invalid":
            return dict(base, choices=[{"message": {"content": json.dumps({"headline": "x"})}}])
        return dict(base, choices=[{"message": {"content": json.dumps(FIXTURE_ANSWER)}}])
    return call


OPS_TASK_TYPE = "ops_summary"   # X-TradeAI-Task-Type: the bridge maps caller n8n_model_job + this task type to OPS_PROCESS_ID


def live_call() -> Callable[..., dict[str, Any]]:
    """The governed bridge, with the ops-summary task type so the server picks n8n_ops_summary_draft."""
    import functools
    return functools.partial(_mj.bridge_governed_call, task_type=OPS_TASK_TYPE)


def plan_ops_summary(*, root: Path, period: str, key: str, now: _dt.datetime,
                     schemas: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """Live-path preflight WITHOUT a provider call: resolve the caller→process mapping, the registry entry,
    the model policy, the caps, and the prompt size exactly as the bridge would, then stop. Nothing written."""
    out: dict[str, Any] = {"mode": "plan", "process_id": OPS_PROCESS_ID, "task_type": OPS_TASK_TYPE, "schema_id": OPS_SCHEMA_ID,
                           "would_call": False}
    try:
        from scripts.lib.cio_governed_model_bridge import resolve_caller, resolve_model_policy
        mapped = resolve_caller(_mj.BRIDGE_CALLER, task_type=OPS_TASK_TYPE)
        out["caller_maps_to"] = mapped
        out["caller_map_ok"] = mapped == OPS_PROCESS_ID
        pol = resolve_model_policy(OPS_PROCESS_ID, OPS_TASK_TYPE)
        out["policy"] = None if pol is None else {k: pol.get(k) for k in ("provider", "model_id", "requested_policy", "thinking")}
    except Exception as exc:  # noqa: BLE001 — a missing bridge module is a plan finding, not a crash
        out["bridge_import_error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
    try:
        from scripts.lib.llm_consumption import get_process_config
        cfg = get_process_config(OPS_PROCESS_ID)
        out["registered"] = bool(cfg.get("registered"))
        out["caps"] = {k: cfg.get(k) for k in ("daily_cost_cap_usd", "daily_soft_cap", "max_input_tokens", "max_output_tokens",
                                                "allowed_lanes", "deepseek_allowed_policies")}
    except Exception as exc:  # noqa: BLE001
        out["registry_error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
    rp = root / RECEIPT_REL
    if rp.exists():
        raw = rp.read_bytes()
        try:
            schema = (schemas if schemas is not None else _mj.load_schemas()).get(OPS_SCHEMA_ID)
            if schema is None:
                raise KeyError(OPS_SCHEMA_ID)
            job = {"process_id": OPS_PROCESS_ID, "output_schema_id": OPS_SCHEMA_ID, "correlation_id": f"corr-ops-{period}-{key}"}
            artifact = {"path": str(rp), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
                        "body": json.loads(raw.decode("utf-8"))}   # the shape resolve_artifact() hands build_messages()
            msgs = _mj.build_messages(OPS_SCHEMA_ID, schema, artifact, job)
            chars = sum(len(str(mm.get("content") or "")) for mm in msgs)
            out["prompt"] = {"messages": len(msgs), "chars": chars, "est_tokens": chars // 4,
                             "fits_max_input": (out.get("caps") or {}).get("max_input_tokens") is None or chars // 4 <= int((out.get("caps") or {}).get("max_input_tokens") or 0)}
        except Exception as exc:  # noqa: BLE001
            out["prompt_error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
    else:
        out["prompt"] = None
        out["receipt_missing"] = str(rp)
    out["ready"] = bool(out.get("caller_map_ok") and out.get("registered") and out.get("policy") and (out.get("prompt") or {}).get("fits_max_input"))
    return out


def draft_ops_summary(*, root: Path, period: str, key: str, now: _dt.datetime, governed_call: Callable[..., dict[str, Any]],
                      schemas: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    rp = root / RECEIPT_REL
    raw = rp.read_bytes()
    job = {"process_id": OPS_PROCESS_ID, "output_schema_id": OPS_SCHEMA_ID, "correlation_id": f"corr-ops-{period}-{key}",
           "deadline": (now + _dt.timedelta(hours=1)).isoformat(),
           "artifact_ref": {"store": "data/runtime", "ref": RECEIPT_REL.split("data/runtime/", 1)[1], "sha256": hashlib.sha256(raw).hexdigest()}}
    rec = _mj.run_model_job(job, governed_call=governed_call, now=now, root=root, schemas=schemas)
    out = {"state": rec["state"], "reason": rec.get("reason"), "detail": rec.get("detail"), "lane": None, "note": NO_LANE_NOTE,
           "artifact": None, "cost": rec.get("cost")}
    gov = root / "data" / "governance"; gov.mkdir(parents=True, exist_ok=True)
    dp = gov / f"ops_summary_draft_{period}_{key}.json"
    dp.write_text(json.dumps({"schema": "OpsSummaryDraft@v1", "authority": AUTHORITY, "as_of": now.isoformat(), "job": {k: job[k] for k in ("process_id", "output_schema_id", "correlation_id")},
                              "receipt": rec}, indent=2, default=str) + "\n", encoding="utf-8")
    out["artifact"] = str(dp)
    receipt = json.loads(raw.decode("utf-8"))
    receipt["ops_summary"] = out
    rp.write_text(json.dumps(receipt, indent=2, default=str) + "\n", encoding="utf-8")
    return out


# ── cli ───────────────────────────────────────────────────────────────────────────────────────────

def _host_cron_text() -> Optional[str]:
    try:
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=20)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--period", choices=("weekly", "monthly"), default="weekly")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="print the section counts, write nothing (default)")
    g.add_argument("--write", action="store_true", help="write packet json + md and the receipt under the state root")
    ap.add_argument("--draft", action="store_true", help="after --write, run the governed ops-summary model job on the receipt")
    ap.add_argument("--draft-mode", default="live", help="live (governed bridge, task type ops_summary), plan (resolve governance/caps/prompt size, no call), or fixture:<valid|invalid_json|over_cap|outage|schema_invalid>")
    ap.add_argument("--root", type=Path, default=None, help="state root (default TRADEAI_STATE_ROOT)")
    ap.add_argument("--registry", type=Path, default=None)
    ap.add_argument("--ledger", type=Path, default=None)
    ap.add_argument("--retention-log", type=Path, default=None)
    ap.add_argument("--deploy-state-dir", type=Path, default=None)
    ap.add_argument("--no-systemd", action="store_true", help="do not list systemd units (hermetic callers)")
    ap.add_argument("--now", default=None, help="ISO timestamp override (tests)")
    args = ap.parse_args(argv)

    now = _dt.datetime.fromisoformat(args.now) if args.now else _dt.datetime.now(_dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=_dt.timezone.utc)
    root = args.root or state_root()
    packet = build_packet(now=now, period=args.period, root=root, registry_path=args.registry, cron_text=_host_cron_text(),
                          include_systemd=not args.no_systemd, ledger=args.ledger, deploy_state_dir=args.deploy_state_dir,
                          retention_log=args.retention_log)
    print(json.dumps({"mode": "write" if args.write else "dry-run", "period": args.period, "period_key": packet["period_key"],
                      "summary": packet["summary"]}, default=str, indent=1))
    if not args.write:
        print("dry-run: nothing written")
        return 0
    paths = write_packet(packet, root=root)
    print(json.dumps({"written": paths}))
    if args.draft:
        if args.draft_mode == "plan":
            print(json.dumps({"ops_summary_plan": plan_ops_summary(root=root, period=args.period, key=packet["period_key"], now=now)},
                             default=str, indent=1))
            return 0
        if args.draft_mode.startswith("fixture:"):
            call = fixture_call(args.draft_mode.split(":", 1)[1])
        else:
            call = live_call()
        out = draft_ops_summary(root=root, period=args.period, key=packet["period_key"], now=now, governed_call=call)
        print(json.dumps({"ops_summary": {k: out[k] for k in ("state", "reason", "artifact", "note")}}, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
