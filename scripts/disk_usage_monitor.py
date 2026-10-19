#!/usr/bin/env python3
"""disk_usage_monitor.py — disk-usage bands for the configured mounts, alerting once per band change.

Operator, 2026-10-18: "monitor when a threshold is over 80%, fix and move to n8n where monitored." n8n lane
``disk-usage-monitor`` (*/15, tradeai-dispatcher). Thresholds, mounts and consumer categories:
``config/disk_hygiene_rules.json`` ``monitor``.

Each run, per mount: used% as df prints it (used / (used + available): the root reserve is not "free" to a normal
writer; disk_pressure_guard.py learned this 2026-09-21), band = ok | warn (>= warn_pct) | critical (>= critical_pct).
A band CHANGE (ok->warn, warn->critical, critical->warn, warn/critical->ok) queues ONE host comms intent
(routes config/host_comms_intent_routes.json host/disk_usage_*), which the comms
intent consumer turns into an incident fan-in incident and the incident notifier sends (DIGEST -> P2). The intent is
queued through CommsIntentStore directly (:func:`queue_host_intent`, same rows/dedupe/cap as host_comms_intents): that
module's import closure reaches broker modules via the gateway, which an n8n lane must not
(tests/test_lane_transitive_capabilities_20261015.py). Staying in a
band sends nothing: dedupe is by band, never by the raw percent. The intent carries the top consumers by category
and the reclaimable estimate from the latest disk_hygiene manifest. This lane never sends, never deletes, never
calls a sender (the n8n never-list); the host P1 backstop is the systemd disk_pressure_guard (proposed at
monitor.host_backstop_pct, packet docs/ops/packets/disk-hygiene-n8n-20261018/), because n8n's own Postgres fails
when the disk is full.

    python3 scripts/disk_usage_monitor.py --dry-run     # measure and print; writes nothing, queues nothing
    python3 scripts/disk_usage_monitor.py --apply       # state file + intent on a band change + LaneRunReceipt

Exit: 0 = every mount measured and every due intent queued; 1 = rules unreadable, a mount unmeasurable, an intent
could not be queued (the band is NOT recorded, so the next run retries), or a write failed; 2 = usage.

MBI_BEHAVIOR = 0. No broker, no network, no Telegram import, no DB.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import disk_hygiene as DH  # noqa: E402
from scripts.lib import lane_last_receipt as R  # noqa: E402

NO_CONSUMER_REASON = (
    "self-contained monitor: DiskUsageMonitorState@v1 is read back only by this script (band dedupe); results reach "
    "consumers via the LaneRunReceipt@v2 receipt and the host comms intent"
)
LANE_ID = "disk-usage-monitor"
SCRIPT = "scripts/disk_usage_monitor.py"
STATE_SCHEMA = "DiskUsageMonitorState@v1"
BANDS = ("ok", "warn", "critical")
SKIP_DEPENDENCY = "dependency_unavailable"


def measure(mount: str) -> Optional[dict[str, Any]]:
    """df-style usage of ``mount``; None when statvfs fails."""
    try:
        st = os.statvfs(mount)
    except OSError:
        return None
    used = (st.f_blocks - st.f_bfree) * st.f_frsize
    avail = st.f_bavail * st.f_frsize
    reach = used + avail
    return {
        "mount": mount,
        "used_pct": round(used / reach * 100.0, 2) if reach else 0.0,
        "used_bytes": used,
        "avail_bytes": avail,
        "size_bytes": st.f_blocks * st.f_frsize,
    }


def band_of(pct: float, mon: Mapping[str, Any]) -> str:
    if pct >= float(mon["critical_pct"]):
        return "critical"
    if pct >= float(mon["warn_pct"]):
        return "warn"
    return "ok"


def transition(prev: Optional[str], cur: str) -> Optional[str]:
    """The alert a band change calls for: the new band's name, or None (no change, or a first run at ok)."""
    if prev == cur:
        return None
    if prev in (None, "ok") and cur == "ok":
        return None
    return cur


def latest_manifest(rules: Mapping[str, Any], state_root: Optional[Path]) -> Optional[dict[str, Any]]:
    try:
        p = DH.manifest_dir(rules, state_root) / rules["manifest"]["latest_name"]
        m = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError):
        return None
    t = m.get("totals") or {}
    return {
        "generated_at": m.get("generated_at"),
        "candidates": t.get("candidates"),
        "reclaimable_bytes": t.get("reclaimable_bytes"),
        "by_kind": t.get("by_kind"),
    }


def top_consumers(rules: Mapping[str, Any], mon: Mapping[str, Any], manifest: Optional[Mapping[str, Any]]) -> list:
    """[(category, bytes)] largest first: du of the configured category paths plus the git-tree total from the
    latest manifest (candidates + excluded), never a guess (an unmeasurable path is left out)."""
    sizes: dict[str, int] = {}
    to = float(mon.get("du_timeout_s") or 60)
    for c in mon.get("consumer_categories") or []:
        p = DH._expand(str(c["path"]), rules["_home"])
        if p.exists():
            b = DH.du_bytes(p, to)
            if b is not None:
                sizes[c["category"]] = sizes.get(c["category"], 0) + b
    if manifest and manifest.get("by_kind"):
        git = sum(v.get("bytes") or 0 for k, v in manifest["by_kind"].items() if k.startswith("G:"))
        if git:
            sizes["git_trees_reclaimable"] = git
    return sorted(sizes.items(), key=lambda kv: -kv[1])[: int(mon.get("top_consumers") or 5)]


def _gb(n: Optional[int]) -> str:
    return f"{(n or 0) / 1024**3:.1f}G"


def intent_text(
    m: Mapping[str, Any], band: str, mon: Mapping[str, Any], consumers: list, manifest: Optional[Mapping[str, Any]]
) -> tuple[str, str]:
    """(subject, summary). The subject is band-stable (no percent) so the store's own dedupe agrees with ours."""
    mount = m["mount"]
    if band == "ok":
        subject = f"Disk {mount} recovered: below {float(mon['warn_pct']):.0f}% used"
    else:
        thr = float(mon["critical_pct"] if band == "critical" else mon["warn_pct"])
        subject = f"Disk {mount} {band.upper()}: at or above {thr:.0f}% used"
    parts = [f"{m['used_pct']:.1f}% used, {_gb(m['avail_bytes'])} free of {_gb(m['size_bytes'])}"]
    if consumers:
        parts.append("top: " + ", ".join(f"{c} {_gb(b)}" for c, b in consumers))
    if manifest and manifest.get("reclaimable_bytes") is not None:
        parts.append(
            f"reclaimable {_gb(manifest['reclaimable_bytes'])} in {manifest.get('candidates')} items per hygiene"
            f" manifest {str(manifest.get('generated_at') or '')[:16]} (apply is operator-gated)"
        )
    else:
        parts.append("no hygiene manifest yet")
    return subject, "; ".join(parts)


def _execution_id(now: datetime) -> str:
    rid = os.environ.get("TRADEAI_RUN_ID") or f"manual-{now.strftime('%Y%m%dT%H%M%S')}"
    return re.sub(r"[^A-Za-z0-9_-]", "-", rid)[-40:]


class HostIntentError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def default_ledger_path(environ: Optional[Mapping[str, str]] = None) -> Path:
    """Same resolution as scripts/n8n_coordination_gateway.default_ledger_path (not imported: see queue_host_intent)."""
    source = environ if environ is not None else os.environ
    explicit = source.get("TRADEAI_N8N_COORDINATION_LEDGER")
    if explicit:
        return Path(explicit)
    root = source.get("TRADEAI_STATE_ROOT") or str(Path.home() / "trade-ai-releases" / "persistent-state")
    return Path(root) / "data" / "governance" / "n8n_coordination_ledger.sqlite"


class _LedgerConn:
    """The two attributes CommsIntentStore uses (``_conn``, ``lock``) on a plain sqlite connection to an EXISTING
    ledger. Same rows, dedupe and cap as scripts/lib/host_comms_intents.queue_intent, whose import closure (via
    scripts/n8n_coordination_gateway.py) reaches broker modules — an n8n-allowlisted lane must not
    (tests/test_lane_transitive_capabilities_20261015.py), so this lane talks to the store directly. Mirrors
    scripts/check_registry_runtime_truth.py."""

    read_only = False

    def __init__(self, path: Path) -> None:
        import sqlite3
        import threading

        self.lock = threading.RLock()  # CommsIntentStore re-enters it (accept -> _receipt -> get)
        self._conn = sqlite3.connect(str(path), timeout=10, isolation_level=None)
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self._conn.close()


def queue_host_intent(
    *, producer: str, domain: str, kind: str, subject: str, summary: str, execution_id: str, node: str,
    ledger_path: Optional[Path], now: Optional[float] = None,
) -> dict[str, Any]:
    """Queue one host comms intent (never a send). Raises HostIntentError(<reason>) with host_comms_intents' reasons:
    producer_refused, intent_unrouted, intent_rate_limited, intent_routes_unreadable, malformed_event, ledger_absent
    (the consumer and gateway create the ledger; a lane never does), intent_store_unavailable."""
    import sqlite3
    import time

    from scripts.lib.n8n_fabric_store import (
        PRODUCER_RE, SUBJECT_MAX, SUMMARY_MAX, CommsIntentStore, FabricStoreError, load_host_intent_routes,
        load_intent_routes, merged_intent_routes,
    )

    if not PRODUCER_RE.fullmatch(producer):
        raise HostIntentError("producer_refused")
    try:
        hosts = load_host_intent_routes()
        routes = merged_intent_routes(load_intent_routes(), hosts)
    except FabricStoreError as exc:
        raise HostIntentError(getattr(exc, "reason", "intent_routes_unreadable")) from exc
    route = hosts["routes"].get((domain, kind))
    if route is None:
        raise HostIntentError("intent_unrouted")
    if route.get("producer") != producer:
        raise HostIntentError("producer_refused")
    path = Path(ledger_path) if ledger_path is not None else default_ledger_path()
    if not path.exists():
        raise HostIntentError("ledger_absent")

    def clean(text: Any, limit: int) -> str:
        flat = " ".join("".join(" " if ord(ch) < 32 or ord(ch) == 127 else ch for ch in str(text or "")).split())
        return flat if len(flat) <= limit else flat[: max(0, limit - 1)] + "…"

    request = {"domain": domain, "kind": kind, "subject": clean(subject, SUBJECT_MAX),
               "summary": clean(summary, SUMMARY_MAX), "workflow_id": f"host.{producer}",
               "execution_id": str(execution_id)[:40], "node": clean(node, 64)}
    try:
        ledger = _LedgerConn(path)
    except (sqlite3.Error, OSError) as exc:
        raise HostIntentError("intent_store_unavailable") from exc
    try:
        store = CommsIntentStore(ledger, routes=routes)
        return dict(store.accept(request, caller_id=f"host:{producer}", now=time.time() if now is None else now))
    except FabricStoreError as exc:
        raise HostIntentError(getattr(exc, "reason", "intent_store_unavailable")) from exc
    except sqlite3.Error as exc:
        raise HostIntentError("intent_store_unavailable") from exc
    finally:
        ledger.close()


def run(
    *, rules: Mapping[str, Any], state_root: Optional[Path], ledger: Optional[Path], apply: bool, now: datetime,
    wall_start: Optional[datetime] = None,
) -> int:
    # the receipt's started_at is the real start (the executor binds it to the attempt window); `now` is the
    # logical clock for bands and idle math and may be injected
    wall_start = wall_start or datetime.now(timezone.utc)
    mon = rules["monitor"]
    state_path = R.runtime_dir(state_root) / mon["state_name"]
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("schema") != STATE_SCHEMA:
            state = {}
    except (OSError, ValueError):
        state = {}
    mounts_state: dict[str, Any] = dict(state.get("mounts") or {})
    manifest = latest_manifest(rules, state_root)
    results: list[dict[str, Any]] = []
    failures = 0
    for mount in mon["mounts"]:
        m = measure(mount)
        if m is None:
            results.append({"mount": mount, "error": "statvfs_failed"})
            failures += 1
            continue
        cur = band_of(m["used_pct"], mon)
        prev = (mounts_state.get(mount) or {}).get("band")
        alert = transition(prev, cur)
        row: dict[str, Any] = {**m, "band": cur, "previous_band": prev, "alert": alert}
        if alert:
            consumers = top_consumers(rules, mon, manifest) if mon.get("measure_consumers_on") == "alert" else []
            subject, summary = intent_text(m, cur, mon, consumers, manifest)
            row.update(subject=subject, summary=summary)
            if apply:
                try:
                    rec = queue_host_intent(
                        producer=mon["producer"],
                        domain=mon["intent_domain"],
                        kind=mon["intent_kinds"][cur],
                        subject=subject,
                        summary=summary,
                        execution_id=_execution_id(now),
                        node="disk_usage_monitor",
                        ledger_path=ledger,
                        now=now.timestamp(),
                    )
                    row["intent"] = {"intent_id": rec.get("intent_id"), "duplicate": rec.get("duplicate")}
                except HostIntentError as exc:
                    row["intent_error"] = exc.reason
                    failures += 1
                    results.append(row)
                    continue  # band NOT recorded: the next run retries the alert
        if apply:
            entry = dict(mounts_state.get(mount) or {})
            if entry.get("band") != cur:
                entry["since"] = now.isoformat()
            entry.update(band=cur, last_pct=m["used_pct"], checked_at=now.isoformat())
            if alert:
                entry["alerted_at"] = now.isoformat()
                entry["alerted_band"] = cur
            mounts_state[mount] = entry
        results.append(row)
    summary = {"mounts": results, "manifest": manifest, "failures": failures}
    if not apply:
        R.dry_run_report(LANE_ID, summary, would_write=[str(state_path)], receipt=R.receipt_path(LANE_ID, state_root))
        return 0 if not failures else 1
    measured = sum(1 for r in results if "band" in r)
    ok = failures == 0
    try:
        from scripts.lib.atomic_json_store import atomic_write_json

        atomic_write_json(
            state_path, {"schema": STATE_SCHEMA, "updated_at": now.isoformat(), "mounts": mounts_state}, indent=1
        )
    except OSError as exc:
        ok = False
        summary["error"] = f"state_write_failed:{type(exc).__name__}"
    output = {
        "produced_count": measured,
        "attempted_count": len(mon["mounts"]),
        "skipped_reasons": {SKIP_DEPENDENCY: len(mon["mounts"]) - measured} if measured < len(mon["mounts"]) else {},
        "empty_reason": None,
        "output_evidence": [{"kind": "file", "ref": str(state_path)}],
    }
    written = R.write_lane_receipt(
        LANE_ID,
        ok=ok,
        exit_code=0 if ok else 1,
        started_at=wall_start,
        script=SCRIPT,
        summary=summary,
        error=summary.get("error"),
        path=R.receipt_path(LANE_ID, state_root),
        output=output,
    )
    print(
        json.dumps(
            {
                "mode": "apply",
                "ok": ok,
                "receipt": str(written) if written else None,
                "bands": {r["mount"]: r.get("band") for r in results},
                "alerts": {r["mount"]: r.get("alert") for r in results if r.get("alert")},
                "failures": failures,
            }
        )
    )
    return 0 if ok and written else 1


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="the default: measure and print, write nothing")
    g.add_argument("--apply", action="store_true", help="record bands, queue an intent on a band change, receipt")
    ap.add_argument("--rules", help="rules file (default config/disk_hygiene_rules.json)")
    ap.add_argument("--state-root", help="persistent-state root (default TRADEAI_STATE_ROOT / resolver)")
    ap.add_argument("--ledger", help="coordination ledger (default: TRADEAI_N8N_COORDINATION_LEDGER, else state root)")
    ap.add_argument("--home", help=argparse.SUPPRESS)  # tests
    ap.add_argument("--now", help=argparse.SUPPRESS)  # tests: aware ISO 8601
    try:
        a = ap.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    wall_start = datetime.now(timezone.utc)
    now = DH._parse_now(a.now)
    if now is None:
        print("--now must be an aware ISO 8601 timestamp", file=sys.stderr)
        return 2
    state_root = Path(a.state_root) if a.state_root else None
    try:
        rules = DH.load_rules(Path(a.rules) if a.rules else None, home=Path(a.home) if a.home else None)
        mon = rules["monitor"]
        for key in ("mounts", "warn_pct", "critical_pct", "state_name", "producer", "intent_domain", "intent_kinds"):
            if key not in mon:
                raise DH.RulesError(f"rules_missing:monitor.{key}")
        if not float(mon["warn_pct"]) < float(mon["critical_pct"]):
            raise DH.RulesError("monitor_thresholds_out_of_order")
    except (DH.RulesError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        if a.apply:
            R.write_lane_receipt(
                LANE_ID,
                ok=False,
                exit_code=1,
                started_at=wall_start,
                script=SCRIPT,
                summary={"error": str(exc)},
                path=R.receipt_path(LANE_ID, state_root),
                output={
                    "produced_count": 0,
                    "attempted_count": 0,
                    "skipped_reasons": {SKIP_DEPENDENCY: 1},
                    "empty_reason": None,
                },
            )
        return 1
    ledger = Path(a.ledger) if a.ledger else None
    if ledger is None and state_root is not None and not os.environ.get("TRADEAI_N8N_COORDINATION_LEDGER"):
        ledger = state_root / "data" / "governance" / "n8n_coordination_ledger.sqlite"
    return run(rules=rules, state_root=state_root, ledger=ledger, apply=bool(a.apply), now=now, wall_start=wall_start)


if __name__ == "__main__":
    raise SystemExit(main())
