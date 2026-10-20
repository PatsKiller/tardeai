#!/usr/bin/env python3
"""check_registry_runtime_truth.py — does what the repo DECLARES about a lane match what the host DOES?

2026-10-18 external review (packet docs/ops/packets/registry-runtime-truth-20261018/): five Hermes fabric step lanes
were declared NEVER_SCHEDULED with health contracts at shadow while n8n owned their effect keys and ran them live
every day. Every gate was green, because each gate compares the repo with itself (or the host with one file). This
checker joins the declared state with host evidence and reports each disagreement as a CONTRADICTION.

Declared (repo, read):
  config/lane_registry.json        state, scheduler.kind/stage/expression, effect_ownership (parent cron rows)
  config/n8n_health_contracts.json contract status + stage
  config/n8n_run_allowlist.json    live_arg
  config/n8n_fabric_processes.json process mode, step lane ids
Host evidence (read-only, each source optional; an unreadable source is NOT_MEASURED, never "clean"):
  coordination ledger (sqlite mode=ro + PRAGMA query_only)  runs (live RUN_DONE in the window), effect_owners
  ~/.config/tradeai/n8n-live-lanes.env                      ONLY TRADEAI_N8N_RELAY_LIVE_LANES is parsed; nothing
                                                            else is read into memory; only lane names are printed
  `crontab -l`                                              active (uncommented) lines, matched by substring
  n8n workflow_entity (docker exec psql SELECT, read-only)  active workflow ids (scripts/lib/n8n_live_inventory.py)

Contradiction codes (rules are pure functions over the two sides; tests/test_registry_runtime_truth_20261018.py):
  DECLARED_OFF_BUT_RUNS_LIVE     state NEVER_SCHEDULED/RETIRED/PAUSED, but live RUN_DONE runs exist in the window
  EFFECT_OWNER_N8N_KIND_NOT_N8N  effect_owners says n8n, registry scheduler.kind is not n8n
  EFFECT_OWNER_N8N_NOT_LIVE      effect_owners says n8n, registry row is not ACTIVE or is at stage shadow
  LIVE_LIST_REGISTRY_NOT_LIVE    on the relay live list, registry row not ACTIVE or stage not canary/cutover
  LIVE_LIST_CONTRACT_NOT_LIVE    on the relay live list, contract missing, not REVIEWED, or at stage shadow
  LIVE_LIST_NO_LIVE_ARG          on the relay live list, allowlist entry missing or live_arg null
  CONTRACT_STAGE_MISMATCH        registry stage canary/cutover vs contract shadow, or registry shadow vs contract canary
  PROCESS_LIVE_STEP_NOT_ACTIVE   fabric process mode live, step allowlisted with a live_arg, registry row not ACTIVE
  ACTIVE_N8N_WORKFLOW_INACTIVE   ACTIVE kind-n8n row whose workflow (dispatcher rows: tradeai-dispatcher) is inactive
  CUTOVER_CRON_LINE_ACTIVE       registry stage cutover, but an active crontab line still runs scheduler.match
  EFFECT_OWNERSHIP_DRIFT         a parent row's declared effect_ownership disagrees with effect_owners

    python3 scripts/check_registry_runtime_truth.py              # --dry-run (default): print, write nothing
    python3 scripts/check_registry_runtime_truth.py --json       # dry run, JSON only
    python3 scripts/check_registry_runtime_truth.py --apply      # + LaneRunReceipt@v2 + one DIGEST host intent

--apply (the n8n lane registry-runtime-truth, dispatcher daily, measure-only) writes exactly two things: the receipt
<state root>/data/runtime/registry-runtime-truth_last.json (LaneRunReceipt@v2; produced_count 1 = one complete
report), and — only when contradictions exist — ONE host comms intent (fabric/registry_runtime_contradiction,
producer registry_runtime_truth, config/host_comms_intent_routes.json; queued through CommsIntentStore directly, see
:func:`queue_host_intent`, DIGEST -> P2 via the comms-intent consumer and
the incident notifier). It edits no registry, no contract, no crontab and no n8n row (AGENTS.md §0 rule 5: report both
sides, never auto-remediate). Exit 0 = the report completed (contradictions are findings, not failures); 1 = the
registry or the coordination ledger could not be read (fatal dependency_unavailable); 2 = usage.
--fail-on-contradiction makes contradictions exit 1 (gate use from a terminal).

MBI_BEHAVIOR = 0. No broker, no send, no network beyond the local docker CLI. Authority: READ_ONLY_ADVISORY.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LANE_ID = "registry-runtime-truth"
SCRIPT = "scripts/check_registry_runtime_truth.py"
SCHEMA = "RegistryRuntimeTruth@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
PRODUCER = "registry_runtime_truth"
INTENT_DOMAIN = "fabric"
INTENT_KIND = "registry_runtime_contradiction"
LIVE_LANES_KEY = "TRADEAI_N8N_RELAY_LIVE_LANES"
DEFAULT_STATE_ROOT = Path.home() / "trade-ai-releases" / "persistent-state"
DEFAULT_LIVE_LANES_ENV = Path.home() / ".config" / "tradeai" / "n8n-live-lanes.env"
LEDGER_REL = Path("data") / "governance" / "n8n_coordination_ledger.sqlite"
DISPATCHER_EXPRESSIONS = frozenset({"dispatcher", "tradeai-dispatcher"})
OFF_STATES = ("NEVER_SCHEDULED", "RETIRED", "PAUSED")
LIVE_STAGES = ("canary", "cutover")
DEFAULT_WINDOW_DAYS = 7

#: Expected-output vocabulary (config/n8n_health_contracts.json registry-runtime-truth expected_output).
SKIP_DEPENDENCY = "dependency_unavailable"

SOURCE_OK = "ok"
SOURCE_UNAVAILABLE = "unavailable"
SOURCE_SKIPPED = "skipped"


# ── host evidence readers (each returns (status, value, note)) ───────────────────────────────────────────────────


def parse_live_lanes(text: str) -> list[str]:
    """Lane names of ``TRADEAI_N8N_RELAY_LIVE_LANES=`` (comma or space separated, optional quotes, optional
    ``export``). Every other line is ignored. Pure."""
    names: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("export "):
            s = s[len("export "):].strip()
        if not s.startswith(LIVE_LANES_KEY + "="):
            continue
        value = s[len(LIVE_LANES_KEY) + 1:].strip().strip("'\"")
        for tok in value.replace(",", " ").split():
            tok = tok.strip()
            if tok and tok not in names:
                names.append(tok)
    return names


def read_live_lanes(path: Path) -> tuple[str, list[str], str]:
    try:
        with path.open(encoding="utf-8") as fh:
            wanted = [ln for ln in fh if ln.lstrip().startswith((LIVE_LANES_KEY + "=", "export " + LIVE_LANES_KEY + "="))]
    except OSError as exc:
        return SOURCE_UNAVAILABLE, [], type(exc).__name__
    return SOURCE_OK, parse_live_lanes("".join(wanted)), f"{LIVE_LANES_KEY} names only"


def active_cron_lines(text: str) -> list[str]:
    """Uncommented, non-assignment crontab lines. Pure."""
    out = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        head = s.split(None, 1)[0]
        if "=" in head and not head[0].isdigit() and head[0] not in "*@":
            continue
        out.append(s)
    return out


def read_crontab(runner: Optional[Callable[[], tuple[int, str]]] = None) -> tuple[str, list[str], str]:
    try:
        if runner is not None:
            rc, out = runner()
        else:
            p = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=20, check=False)
            rc, out = p.returncode, p.stdout
    except (OSError, subprocess.SubprocessError) as exc:
        return SOURCE_UNAVAILABLE, [], type(exc).__name__
    if rc != 0:
        return SOURCE_UNAVAILABLE, [], f"crontab -l rc {rc}"
    lines = active_cron_lines(out)
    return SOURCE_OK, lines, f"{len(lines)} active lines (text never written to the report)"


def read_n8n_active(reader: Optional[Callable[[], list[dict]]] = None) -> tuple[str, list[str], str]:
    try:
        if reader is None:
            from scripts.lib import n8n_live_inventory as inv

            rows = inv.read_active_workflows()
        else:
            rows = reader()
    except Exception as exc:  # noqa: BLE001 — an unreadable n8n DB is NOT_MEASURED, never clean
        return SOURCE_UNAVAILABLE, [], type(exc).__name__
    ids = sorted({str(r.get("id") or r.get("expression") or "") for r in rows or []} - {""})
    return SOURCE_OK, ids, f"{len(ids)} active workflows (read-only SELECT)"


def connect_ro(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(str(path))
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    conn.execute("PRAGMA query_only = ON")
    return conn


def read_ledger(path: Path, since: datetime) -> tuple[str, dict[str, Any], str]:
    """{live_runs: {lane: {count, last}}, owners: {process: {owner, epoch, switched_at}}} from the ledger, mode=ro."""
    try:
        conn = connect_ro(path)
    except (OSError, sqlite3.Error) as exc:
        return SOURCE_UNAVAILABLE, {}, type(exc).__name__
    try:
        live: dict[str, dict[str, Any]] = {}
        for lane, n, last in conn.execute(
            "SELECT lane_id, COUNT(*), MAX(requested_at) FROM runs WHERE mode = 'live' AND state = 'RUN_DONE' "
            "AND requested_at >= ? GROUP BY lane_id",
            (since.isoformat(),),
        ):
            live[str(lane)] = {"count": int(n), "last": last}
        owners: dict[str, dict[str, Any]] = {}
        has_owners = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'effect_owners'"
        ).fetchone()
        if has_owners:
            for process, owner, epoch, switched in conn.execute(
                "SELECT process, owner, epoch, switched_at FROM effect_owners"
            ):
                owners[str(process)] = {"owner": str(owner), "epoch": epoch, "switched_at": switched}
    except sqlite3.Error as exc:
        return SOURCE_UNAVAILABLE, {}, type(exc).__name__
    finally:
        conn.close()
    return SOURCE_OK, {"live_runs": live, "owners": owners}, f"{len(live)} lanes with live RUN_DONE, {len(owners)} owners"


# ── declared side ────────────────────────────────────────────────────────────────────────────────────────────────


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def declared(root: Path) -> dict[str, Any]:
    reg = load_json(root / "config" / "lane_registry.json")
    contracts = load_json(root / "config" / "n8n_health_contracts.json")
    allow = load_json(root / "config" / "n8n_run_allowlist.json")
    try:
        processes = load_json(root / "config" / "n8n_fabric_processes.json")
    except (OSError, json.JSONDecodeError):
        processes = {}
    return {
        "rows": {str(r.get("lane_id")): r for r in reg.get("lanes") or []},
        "contracts": {str(c.get("id")): c for c in contracts.get("contracts") or [] if c.get("kind", "lane") == "lane"},
        "allow": {str(e.get("lane_id")): e for e in allow.get("lanes") or []},
        "processes": (processes or {}).get("processes") or {},
        "grandfathered_draft": list(contracts.get("grandfathered_draft") or []),
    }


# ── rules (pure) ─────────────────────────────────────────────────────────────────────────────────────────────────


def _c(code: str, lane: str, detail: str, **evidence: Any) -> dict[str, Any]:
    return {"code": code, "lane_id": lane, "detail": detail, "evidence": evidence}


def _sched(row: Mapping[str, Any]) -> Mapping[str, Any]:
    return row.get("scheduler") or {}


def _stage_is_live(row: Mapping[str, Any]) -> bool:
    """canary/cutover; or a per-lane n8n workflow row from before the stage field existed (kind n8n, own workflow id,
    no stage): the pilot lanes of 2026-10-08/09 whose workflow is the live scheduler."""
    s = _sched(row)
    if s.get("stage") in LIVE_STAGES:
        return True
    return s.get("stage") is None and s.get("kind") == "n8n" and str(s.get("expression") or "") not in DISPATCHER_EXPRESSIONS


def evaluate(
    decl: Mapping[str, Any],
    *,
    ledger: Optional[Mapping[str, Any]],
    live_lanes: Optional[Iterable[str]],
    cron_lines: Optional[list[str]],
    n8n_active: Optional[Iterable[str]],
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    """(contradictions, not_measured rule codes, accepted debt). A source passed as None was not readable: its rules
    are skipped and named in not_measured. Pure."""
    rows, contracts, allow, processes = decl["rows"], decl["contracts"], decl["allow"], decl["processes"]
    grandfathered = set(decl.get("grandfathered_draft") or ())
    accepted: list[dict[str, Any]] = []
    out: list[dict[str, Any]] = []
    not_measured: list[str] = []

    if ledger is None:
        not_measured += ["DECLARED_OFF_BUT_RUNS_LIVE", "EFFECT_OWNER_N8N_KIND_NOT_N8N", "EFFECT_OWNER_N8N_NOT_LIVE",
                         "EFFECT_OWNERSHIP_DRIFT"]
    else:
        live_runs = ledger.get("live_runs") or {}
        owners = ledger.get("owners") or {}
        for lane, ev in sorted(live_runs.items()):
            row = rows.get(lane)
            if row is not None and row.get("state") in OFF_STATES:
                out.append(_c("DECLARED_OFF_BUT_RUNS_LIVE", lane,
                              f"registry state {row.get('state')} but {ev['count']} live RUN_DONE run(s) in the window",
                              live_run_done=ev["count"], last_requested_at=ev["last"], registry_state=row.get("state")))
        for process, o in sorted(owners.items()):
            if o.get("owner") != "n8n":
                continue
            row = rows.get(process)
            if row is None:
                continue  # an owner key with no lane row is not a registry claim; process names may differ
            s = _sched(row)
            dispatch_live = (row.get("dispatch") or {}).get("mode") == "live" and s.get("stage") in LIVE_STAGES
            if s.get("kind") != "n8n" and not dispatch_live:
                # A cron-kind row at canary/cutover with dispatch.mode live IS the declared dual state (cron line kept,
                # effect-claim wrapped; the dispatcher fires the lane live), so only a row with no live n8n path is a
                # contradiction.
                out.append(_c("EFFECT_OWNER_N8N_KIND_NOT_N8N", process,
                              f"effect owner n8n (epoch {o.get('epoch')}) but registry scheduler.kind {s.get('kind')!r}",
                              owner="n8n", epoch=o.get("epoch"), switched_at=o.get("switched_at"),
                              registry_kind=s.get("kind")))
            elif row.get("state") != "ACTIVE" or (s.get("stage") == "shadow" and not dispatch_live):
                out.append(_c("EFFECT_OWNER_N8N_NOT_LIVE", process,
                              f"effect owner n8n but registry state {row.get('state')} stage {s.get('stage')!r}",
                              owner="n8n", epoch=o.get("epoch"), switched_at=o.get("switched_at"),
                              registry_state=row.get("state"), registry_stage=s.get("stage")))
        for lane, row in sorted(rows.items()):
            eo = row.get("effect_ownership")
            if not isinstance(eo, Mapping):
                continue
            for side, want in (("n8n_owned_steps", "n8n"), ("cron_owned_steps", "cron")):
                for step, step_lane in sorted((eo.get(side) or {}).items()):
                    key = str(step_lane).split(" ", 1)[0]
                    got = (owners.get(key) or {}).get("owner")
                    if got is not None and got != want:
                        out.append(_c("EFFECT_OWNERSHIP_DRIFT", lane,
                                      f"declares step {step} ({key}) owned by {want}; effect_owners says {got}",
                                      step=step, step_lane=key, declared_owner=want, ledger_owner=got))
                    elif got is None and want == "n8n":
                        out.append(_c("EFFECT_OWNERSHIP_DRIFT", lane,
                                      f"declares step {step} ({key}) owned by n8n; effect_owners has no row",
                                      step=step, step_lane=key, declared_owner=want, ledger_owner=None))

    if live_lanes is None:
        not_measured += ["LIVE_LIST_REGISTRY_NOT_LIVE", "LIVE_LIST_CONTRACT_NOT_LIVE", "LIVE_LIST_NO_LIVE_ARG"]
    else:
        for lane in sorted(set(live_lanes)):
            row = rows.get(lane)
            s = _sched(row or {})
            if row is None or row.get("state") != "ACTIVE" or not _stage_is_live(row):
                out.append(_c("LIVE_LIST_REGISTRY_NOT_LIVE", lane,
                              "on the relay live list but registry "
                              + ("has no row" if row is None else f"state {row.get('state')} stage {s.get('stage')!r}"),
                              registry_state=(row or {}).get("state"), registry_stage=s.get("stage")))
            c = contracts.get(lane)
            # The stage half is CONTRACT_STAGE_MISMATCH (not reported twice); a grandfathered DRAFT (2026-10-10 gate
            # baseline, config/n8n_health_contracts.json grandfathered_draft) is accepted debt, listed separately.
            if c is not None and c.get("status") != "REVIEWED" and lane in grandfathered:
                accepted.append({"code": "LIVE_LIST_CONTRACT_GRANDFATHERED_DRAFT", "lane_id": lane})
            elif c is None or c.get("status") != "REVIEWED":
                out.append(_c("LIVE_LIST_CONTRACT_NOT_LIVE", lane,
                              "on the relay live list but health contract "
                              + ("missing" if c is None else f"status {c.get('status')} stage {c.get('stage')!r}"),
                              contract_status=(c or {}).get("status"), contract_stage=(c or {}).get("stage")))
            e = allow.get(lane)
            if e is None or e.get("live_arg") is None:
                out.append(_c("LIVE_LIST_NO_LIVE_ARG", lane,
                              "on the relay live list but allowlist " + ("has no entry" if e is None else "live_arg null"),
                              allowlisted=e is not None))

    for lane, row in sorted(rows.items()):
        s = _sched(row)
        c = contracts.get(lane)
        stage = s.get("stage")
        if c is None or stage not in ("shadow", *LIVE_STAGES) or row.get("state") != "ACTIVE":
            continue
        cstage = c.get("stage")
        if (stage in LIVE_STAGES and cstage == "shadow") or (stage == "shadow" and cstage in LIVE_STAGES):
            out.append(_c("CONTRACT_STAGE_MISMATCH", lane, f"registry stage {stage} but contract stage {cstage}",
                          registry_stage=stage, contract_stage=cstage, contract_status=c.get("status")))

    for pname, p in sorted(processes.items()):
        if (p or {}).get("mode") != "live":
            continue
        for sid, st in sorted(((p or {}).get("steps") or {}).items()):
            lane = str((st or {}).get("lane_id") or "")
            if not lane or (st or {}).get("blocked"):
                continue
            e, row = allow.get(lane), rows.get(lane)
            if e is not None and e.get("live_arg") is not None and row is not None and row.get("state") != "ACTIVE":
                out.append(_c("PROCESS_LIVE_STEP_NOT_ACTIVE", lane,
                              f"fabric process {pname} mode live, step {sid} has live_arg, registry state "
                              f"{row.get('state')}", process=pname, step=sid, registry_state=row.get("state")))

    if n8n_active is None:
        not_measured.append("ACTIVE_N8N_WORKFLOW_INACTIVE")
    else:
        active = set(n8n_active)
        for lane, row in sorted(rows.items()):
            s = _sched(row)
            if row.get("state") != "ACTIVE" or s.get("kind") != "n8n":
                continue
            wid = str(s.get("expression") or "")
            probe = "tradeai-dispatcher" if wid in DISPATCHER_EXPRESSIONS else wid
            if probe not in active:
                out.append(_c("ACTIVE_N8N_WORKFLOW_INACTIVE", lane, f"ACTIVE kind-n8n row but workflow {probe} inactive",
                              workflow_id=probe))

    if cron_lines is None:
        not_measured.append("CUTOVER_CRON_LINE_ACTIVE")
    else:
        for lane, row in sorted(rows.items()):
            s = _sched(row)
            if row.get("state") != "ACTIVE" or s.get("kind") != "n8n" or s.get("stage") != "cutover":
                continue
            match = str(s.get("match") or "").strip()
            if not match:
                continue
            hits = [ln for ln in cron_lines if match in ln and "effect_claim_cron.sh" not in ln]
            if hits:
                out.append(_c("CUTOVER_CRON_LINE_ACTIVE", lane,
                              f"stage cutover but {len(hits)} active crontab line(s) still run {match!r} unwrapped",
                              lines=len(hits), line_sha256=[hashlib.sha256(h.encode()).hexdigest()[:12] for h in hits]))
    out.sort(key=lambda c: (c["code"], c["lane_id"]))
    return out, sorted(set(not_measured)), accepted


# ── report / receipt / intent ────────────────────────────────────────────────────────────────────────────────────


def fingerprint(contradictions: Iterable[Mapping[str, Any]]) -> str:
    keys = sorted(f"{c['code']}|{c['lane_id']}" for c in contradictions)
    return hashlib.sha256("\n".join(keys).encode("utf-8")).hexdigest()[:16]


def counts_by_code(contradictions: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in contradictions:
        out[c["code"]] = out.get(c["code"], 0) + 1
    return dict(sorted(out.items()))


def intent_text(contradictions: list[Mapping[str, Any]]) -> tuple[str, str]:
    n = len(contradictions)
    subject = f"registry/runtime truth: {n} contradiction(s) between declared lane state and host evidence"
    parts = [f"{code} x{k}" for code, k in counts_by_code(contradictions).items()]
    lanes = sorted({c["lane_id"] for c in contradictions})
    summary = ("; ".join(parts) + ". Lanes: " + ", ".join(lanes[:12]) + (" ..." if len(lanes) > 12 else "")
               + ". Run scripts/check_registry_runtime_truth.py --dry-run for the evidence; nothing was changed.")
    return subject, summary


def lane_output(report: Mapping[str, Any]) -> dict[str, Any]:
    """LaneRunReceipt@v2 output fields. produced 1 = one complete report; a fatal source is dependency_unavailable."""
    if report.get("error"):
        return {"produced_count": 0, "attempted_count": 1, "skipped_reasons": {SKIP_DEPENDENCY: 1}, "empty_reason": None}
    skipped = {f"not_measured_{s}": 1 for s, st in (report.get("sources") or {}).items() if st.get("status") != SOURCE_OK}
    return {"produced_count": 1, "attempted_count": 1, "skipped_reasons": skipped, "empty_reason": None}


def build_report(
    *,
    root: Path,
    ledger_path: Path,
    live_lanes_env: Path,
    now: datetime,
    window_days: int,
    cron_runner: Optional[Callable[[], tuple[int, str]]] = None,
    n8n_reader: Optional[Callable[[], list[dict]]] = None,
    skip_cron: bool = False,
    skip_n8n: bool = False,
) -> dict[str, Any]:
    report: dict[str, Any] = {"schema": SCHEMA, "authority": AUTHORITY, "as_of": now.isoformat(),
                              "window_days": window_days, "sources": {}}
    try:
        decl = declared(root)
    except (OSError, json.JSONDecodeError) as exc:
        report["error"] = f"declared config unreadable: {type(exc).__name__}"
        return report
    since = now - timedelta(days=window_days)
    st, ledger, note = read_ledger(ledger_path, since)
    report["sources"]["coordination_ledger"] = {"status": st, "note": note}
    if st != SOURCE_OK:
        report["error"] = f"coordination ledger unreadable: {note}"
        return report
    st, lanes, note = read_live_lanes(live_lanes_env)
    report["sources"]["relay_live_lanes"] = {"status": st, "note": note, "count": len(lanes)}
    live = lanes if st == SOURCE_OK else None
    if skip_cron:
        report["sources"]["crontab"] = {"status": SOURCE_SKIPPED, "note": "--no-crontab"}
        cron = None
    else:
        st, lines, note = read_crontab(cron_runner)
        report["sources"]["crontab"] = {"status": st, "note": note}
        cron = lines if st == SOURCE_OK else None
    if skip_n8n:
        report["sources"]["n8n_workflows"] = {"status": SOURCE_SKIPPED, "note": "--no-n8n"}
        n8n = None
    else:
        st, ids, note = read_n8n_active(n8n_reader)
        report["sources"]["n8n_workflows"] = {"status": st, "note": note}
        n8n = ids if st == SOURCE_OK else None
    contradictions, not_measured, accepted = evaluate(decl, ledger=ledger, live_lanes=live, cron_lines=cron,
                                                      n8n_active=n8n)
    report.update(
        accepted_debt=accepted,
        contradictions=contradictions,
        contradiction_count=len(contradictions),
        by_code=counts_by_code(contradictions),
        fingerprint=fingerprint(contradictions),
        not_measured=not_measured,
        declared_counts={"registry_rows": len(decl["rows"]), "lane_contracts": len(decl["contracts"]),
                         "allowlist_entries": len(decl["allow"]), "fabric_processes": len(decl["processes"])},
    )
    return report


def render(report: Mapping[str, Any]) -> str:
    lines = [f"registry/runtime truth  {report.get('as_of')}  (window {report.get('window_days')} d, {AUTHORITY})"]
    for name, s in (report.get("sources") or {}).items():
        lines.append(f"  source {name:<20} {s.get('status'):<12} {s.get('note')}")
    if report.get("error"):
        lines.append(f"CANNOT RUN: {report['error']}")
        return "\n".join(lines)
    dc = report.get("declared_counts") or {}
    lines.append("  declared: " + ", ".join(f"{k} {v}" for k, v in dc.items()))
    lines.append(f"contradictions: {report.get('contradiction_count')}  fingerprint {report.get('fingerprint')}")
    for code, n in (report.get("by_code") or {}).items():
        lines.append(f"  {code}: {n}")
    for c in report.get("contradictions") or []:
        lines.append(f"  x {c['code']} {c['lane_id']}: {c['detail']}")
    if report.get("accepted_debt"):
        lines.append("accepted debt (not contradictions): " + ", ".join(
            f"{d['code']} {d['lane_id']}" for d in report["accepted_debt"]))
    if report.get("not_measured"):
        lines.append("NOT_MEASURED (source unreadable or skipped; not clean): " + ", ".join(report["not_measured"]))
    if not report.get("contradiction_count") and not report.get("not_measured"):
        lines.append("registry/runtime truth: clean")
    return "\n".join(lines)


def queue_alert(report: Mapping[str, Any], *, ledger_path: Path, execution_id: str,
                queue: Optional[Callable[..., dict]] = None) -> dict[str, Any]:
    """Queue ONE DIGEST host comms intent for this run's contradictions. Never sends. Returns a small status dict."""
    contradictions = list(report.get("contradictions") or [])
    if not contradictions:
        return {"queued": False, "reason": "no_contradictions"}
    subject, summary = intent_text(contradictions)
    try:
        rec = (queue or queue_host_intent)(
            producer=PRODUCER, domain=INTENT_DOMAIN, kind=INTENT_KIND, subject=subject, summary=summary,
            execution_id=execution_id, node=str(report.get("fingerprint") or ""), ledger_path=ledger_path)
    except IntentRefused as exc:
        return {"queued": False, "reason": f"intent_{exc.reason}"}
    return {"queued": True, "duplicate": bool((rec or {}).get("duplicate")), "intent_id": (rec or {}).get("intent_id")}


class IntentRefused(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _LedgerConn:
    """The two attributes CommsIntentStore uses (``_conn``, ``lock``) on a plain sqlite connection to an EXISTING
    ledger. Same rows, dedupe and cap as scripts/lib/host_comms_intents.queue_intent, whose import closure (via
    scripts/n8n_coordination_gateway.py) reaches broker modules — an n8n-allowlisted lane must not
    (tests/test_lane_transitive_capabilities_20261015.py), so this lane talks to the store directly."""

    read_only = False

    def __init__(self, path: Path) -> None:
        import threading

        self.lock = threading.RLock()  # CommsIntentStore re-enters it (accept -> _receipt -> get)
        self._conn = sqlite3.connect(str(path), timeout=10, isolation_level=None)
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self._conn.close()


def queue_host_intent(*, producer: str, domain: str, kind: str, subject: str, summary: str, execution_id: str,
                      node: str, ledger_path: Path, now: Optional[float] = None,
                      host_routes_path: Optional[Path] = None, n8n_routes_path: Optional[Path] = None) -> dict:
    """Queue one host comms intent (never a send). Raises IntentRefused(<reason>) like host_comms_intents."""
    import time

    from scripts.lib.n8n_fabric_store import (
        PRODUCER_RE, SUBJECT_MAX, SUMMARY_MAX, CommsIntentStore, FabricStoreError, load_host_intent_routes,
        load_intent_routes, merged_intent_routes,
    )

    if not PRODUCER_RE.fullmatch(producer):
        raise IntentRefused("producer_refused")
    try:
        hosts = load_host_intent_routes(host_routes_path)
        routes = merged_intent_routes(load_intent_routes(n8n_routes_path), hosts)
    except FabricStoreError as exc:
        raise IntentRefused(getattr(exc, "reason", "intent_routes_unreadable")) from exc
    route = hosts["routes"].get((domain, kind))
    if route is None:
        raise IntentRefused("intent_unrouted")
    if route.get("producer") != producer:
        raise IntentRefused("producer_refused")
    if not Path(ledger_path).exists():
        raise IntentRefused("ledger_absent")

    def clean(text: Any, limit: int) -> str:
        flat = " ".join("".join(" " if ord(ch) < 32 or ord(ch) == 127 else ch for ch in str(text or "")).split())
        return flat if len(flat) <= limit else flat[: max(0, limit - 1)] + "…"

    request = {"domain": domain, "kind": kind, "subject": clean(subject, SUBJECT_MAX),
               "summary": clean(summary, SUMMARY_MAX), "workflow_id": f"host.{producer}",
               # the store's execution id is [A-Za-z0-9_-]{1,40}: a run id d:<lane>:live:<slot> keeps its tail
               "execution_id": ("".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in str(execution_id))[-40:]
                                or "run"),
               "node": clean(node, 64)}
    try:
        ledger = _LedgerConn(Path(ledger_path))
    except (sqlite3.Error, OSError) as exc:
        raise IntentRefused("intent_store_unavailable") from exc
    try:
        store = CommsIntentStore(ledger, routes=routes)
        return dict(store.accept(request, caller_id=f"host:{producer}", now=time.time() if now is None else now))
    except FabricStoreError as exc:
        raise IntentRefused(getattr(exc, "reason", "intent_store_unavailable")) from exc
    except sqlite3.Error as exc:
        raise IntentRefused("intent_store_unavailable") from exc
    finally:
        ledger.close()


def _resolve(state_root: Optional[str], ledger: Optional[str]) -> tuple[Path, Path]:
    sr = Path(state_root) if state_root else Path(os.environ.get("TRADEAI_STATE_ROOT") or DEFAULT_STATE_ROOT)
    if ledger:
        return sr, Path(ledger)
    explicit = os.environ.get("TRADEAI_N8N_COORDINATION_LEDGER")
    return sr, (Path(explicit) if explicit else sr / LEDGER_REL)


def _parse_now(text: Optional[str]) -> Optional[datetime]:
    if not text:
        return datetime.now(timezone.utc).replace(microsecond=0)
    try:
        d = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.astimezone(timezone.utc) if d.tzinfo else None


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="the default: print the report, write nothing")
    g.add_argument("--apply", action="store_true", help="write the LaneRunReceipt and queue one DIGEST intent")
    ap.add_argument("--json", action="store_true", help="print the report as JSON only")
    ap.add_argument("--fail-on-contradiction", action="store_true", help="exit 1 when contradictions exist")
    ap.add_argument("--state-root", help="persistent-state root (default TRADEAI_STATE_ROOT)")
    ap.add_argument("--ledger", help="coordination ledger (default TRADEAI_N8N_COORDINATION_LEDGER, else state root)")
    ap.add_argument("--live-lanes-env", help=f"relay live-lane env file (default {DEFAULT_LIVE_LANES_ENV})")
    ap.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    ap.add_argument("--no-crontab", action="store_true", help="skip crontab -l (its rule is NOT_MEASURED)")
    ap.add_argument("--no-n8n", action="store_true", help="skip the n8n DB SELECT (its rule is NOT_MEASURED)")
    ap.add_argument("--root", help=argparse.SUPPRESS)  # tests: a fixture repo root
    ap.add_argument("--now", help=argparse.SUPPRESS)  # tests: pin the clock
    try:
        a = ap.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    now = _parse_now(a.now)
    if now is None or a.window_days < 1:
        print("--now must be an aware ISO 8601 timestamp and --window-days >= 1", file=sys.stderr)
        return 2
    state_root, ledger_path = _resolve(a.state_root, a.ledger)
    report = build_report(
        root=Path(a.root) if a.root else ROOT,
        ledger_path=ledger_path,
        live_lanes_env=Path(a.live_lanes_env) if a.live_lanes_env else DEFAULT_LIVE_LANES_ENV,
        now=now,
        window_days=a.window_days,
        skip_cron=a.no_crontab,
        skip_n8n=a.no_n8n,
    )
    ok = not report.get("error")
    from scripts.lib import lane_last_receipt as R

    receipt = R.receipt_path(LANE_ID, state_root)
    if not a.apply:
        if a.json:
            print(json.dumps(report, indent=1, default=str, sort_keys=True))
        else:
            print(render(report))
            would = [str(receipt)] + (["host comms intent fabric/registry_runtime_contradiction (DIGEST)"]
                                      if report.get("contradictions") else [])
            R.dry_run_report(LANE_ID, {k: report.get(k) for k in ("contradiction_count", "by_code", "fingerprint",
                                                                   "not_measured", "error")},
                             would_write=would, receipt=receipt)
        if not ok:
            return 1
        return 1 if (a.fail_on_contradiction and report.get("contradictions")) else 0
    alert: dict[str, Any] = {"queued": False, "reason": "not_run"}
    if ok:
        run_id = os.environ.get("TRADEAI_RUN_ID") or f"{LANE_ID}:{now.strftime('%Y%m%dT%H%M%SZ')}"
        alert = queue_alert(report, ledger_path=ledger_path, execution_id=run_id)
    output = lane_output(report)
    if alert.get("reason", "").startswith("intent_"):
        output["skipped_reasons"] = {**output.get("skipped_reasons", {}), alert["reason"]: 1}
    summary = {k: report.get(k) for k in ("schema", "as_of", "window_days", "sources", "contradiction_count",
                                          "by_code", "fingerprint", "not_measured", "declared_counts", "error")}
    summary["contradictions"] = [{"code": c["code"], "lane_id": c["lane_id"]} for c in report.get("contradictions") or []]
    summary["alert"] = alert
    written = R.write_lane_receipt(LANE_ID, ok=ok, exit_code=0 if ok else 1, started_at=now, script=SCRIPT,
                                   summary=summary, error=report.get("error"), path=receipt, output=output)
    print(json.dumps({"mode": "apply", "ok": ok, "receipt": str(written) if written else None,
                      "contradiction_count": report.get("contradiction_count"), "by_code": report.get("by_code"),
                      "not_measured": report.get("not_measured"), "alert": alert, "error": report.get("error")},
                     default=str))
    if written is None or not ok:
        return 1
    return 1 if (a.fail_on_contradiction and report.get("contradictions")) else 0


if __name__ == "__main__":
    raise SystemExit(main())
