#!/usr/bin/env python3
"""check_n8n_activation_grants.py — every n8n activation since T is covered by a grant naming its id.

AGENTS.md 3.0.0 §23.10 P16 (audit C G5): n8n records `import` as the author of every version and has no
audit log, so an activation is attributable only by reconciling the n8n database against the operator
approval ledger (`bin/guard log`, whose source is the guard audit jsonl). On 2026-10-09 seventeen shadow
workflows were activated at 12:39-12:40Z with only a release-write grant active; this makes that a
check instead of a hand measurement.

Activation evidence (read-only SELECTs, scripts/lib/n8n_live_inventory.py):

  * ``workflow_publish_history`` rows with event ``activated`` (UI activations);
  * ``workflow_published_version`` rows — ``createdAt`` is when the current version was published
    (``updatedAt`` is touched on every n8n restart and is NOT an activation time);
  * ``workflow_history`` — when that version was imported, used as a second time a grant may cover.

One event per (workflow id, version id). A ``grant-issued`` ledger entry covers it when its reason names
the workflow id (a tranche grant listing several ids covers each), its tier is one of ``--tiers``
(default cron, config-write, service) and the event time falls inside [ts - skew, ts + seconds + skew].

Verdicts: GRANTED; NAMED_IN_OTHER_TIER (the id is named, but under a tier that does not authorise an
activation, e.g. release-write); NAME_ONLY_GRANT (the grant names the workflow/lane name, not the id —
weak attribution); UNGRANTED_ACTIVATION (nothing names it inside the window).

    python3 scripts/check_n8n_activation_grants.py --since 2026-10-08T00:00:00Z --dry-run
    python3 scripts/check_n8n_activation_grants.py --since ... --write     # receipt under the state root
    python3 scripts/check_n8n_activation_grants.py --evidence-json F --guard-log G   # offline / CI

Receipt: ``$TRADEAI_STATE_ROOT/data/runtime/n8n_activation_grants_last.json``. The receipt carries
``fanin_findings`` shaped like scripts/n8n_incident_fanin.py findings; nothing is wired to send.
Exit codes: 0 report, 1 UNGRANTED_ACTIVATION with --fail-on-ungranted, 2 cannot run.

AUTHORITY: READ_ONLY_ADVISORY. SELECTs against the n8n DB and a read of the guard audit log; no n8n
write, no ledger write, no send.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import n8n_live_inventory as inv  # noqa: E402

NO_CONSUMER_REASON = (
    "AGENTS.md 3.0.0 §23.10 P16 attribution check, run by hand or by a future lane; its receipt carries "
    "fan-in-shaped findings that no fan-in source reads yet (Telegram deliberately not wired)."
)
SCHEMA = "N8nActivationAttribution@v1"
RECEIPT_REL = Path("data") / "runtime" / "n8n_activation_grants_last.json"

GRANTED = "GRANTED"
NAMED_IN_OTHER_TIER = "NAMED_IN_OTHER_TIER"
NAME_ONLY_GRANT = "NAME_ONLY_GRANT"
UNGRANTED_ACTIVATION = "UNGRANTED_ACTIVATION"
FINDINGS = (UNGRANTED_ACTIVATION, NAMED_IN_OTHER_TIER, NAME_ONLY_GRANT)

DEFAULT_TIERS = ("cron", "config-write", "service")
DEFAULT_SKEW_S = 120


def _state_root() -> Path:
    env = os.environ.get("TRADEAI_STATE_ROOT")
    if env:
        return Path(env)
    try:
        from scripts.lib.canonical_store_registry import production_state_root

        return Path(production_state_root())
    except Exception:  # noqa: BLE001
        return Path.home() / "trade-ai-releases" / "persistent-state"


def default_guard_log() -> Path:
    """Same resolution as .cursor/hooks/guard-lib.sh (the file `bin/guard log` reads)."""
    env = os.environ.get("GUARD_AUDIT_LOG")
    return Path(env) if env else Path.home() / "logs" / "cursor-agent-audit.jsonl"


def parse_ts(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    text = str(value).strip().replace(" ", "T", 1)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    # psql renders "+00" offsets; fromisoformat wants "+00:00"
    m = re.match(r"^(.*[T].*?)([+-]\d{2})$", text)
    if m:
        text = m.group(1) + m.group(2) + ":00"
    try:
        ts = datetime.fromisoformat(text)
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def load_grants(path: Path) -> list[dict]:
    """grant-issued entries from the guard audit jsonl. Torn lines are skipped, as `guard log` does."""
    out: list[dict] = []
    if not path.exists():
        raise FileNotFoundError(f"guard audit log not found: {path}")
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or '"grant-issued"' not in line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("event") != "grant-issued":
                continue
            ts = parse_ts(rec.get("ts"))
            if ts is None:
                continue
            try:
                seconds = int(rec.get("seconds") or 0)
            except (TypeError, ValueError):
                seconds = 0
            out.append(
                {
                    "ts": ts,
                    "seconds": seconds,
                    "tier": str(rec.get("tier") or ""),
                    "reason": str(rec.get("reason") or ""),
                    "event_id": rec.get("event_id"),
                }
            )
    return out


def activation_events(evidence: dict, *, since: datetime) -> list[dict]:
    """One event per (workflow id, version id) published or activated at or after `since`."""
    names = {str(w.get("id")): str(w.get("name") or "") for w in evidence.get("workflows") or []}
    active = {str(w.get("id")): bool(w.get("active")) for w in evidence.get("workflows") or []}
    imported: dict[tuple[str, str], datetime] = {}
    for h in evidence.get("version_history") or []:
        ts = parse_ts(h.get("at"))
        if ts is not None:
            imported[(str(h.get("workflow_id")), str(h.get("version_id")))] = ts
    groups: dict[tuple[str, str], dict] = {}

    def add(wid: str, vid: str, at: Optional[datetime], source: str) -> None:
        if at is None or at < since:
            return
        g = groups.setdefault((wid, vid), {"workflow_id": wid, "version_id": vid, "times": [], "sources": []})
        g["times"].append(at)
        g["sources"].append(source)

    for p in evidence.get("publish_history") or []:
        if str(p.get("event") or "").lower() == "activated":
            add(str(p.get("workflow_id")), str(p.get("version_id")), parse_ts(p.get("at")), "publish_history:activated")
    for p in evidence.get("published_versions") or []:
        add(str(p.get("workflow_id")), str(p.get("version_id")), parse_ts(p.get("at")), "published_version")

    out = []
    for (wid, vid), g in sorted(groups.items(), key=lambda kv: min(kv[1]["times"])):
        times = sorted(g["times"])
        imp = imported.get((wid, vid))
        out.append(
            {
                "workflow_id": wid,
                "version_id": vid,
                "name": names.get(wid, ""),
                "currently_active": active.get(wid, False),
                "activated_at": times[0],
                "imported_at": imp,
                "sources": sorted(set(g["sources"])),
            }
        )
    return out


def _window(g: dict, skew: timedelta) -> tuple[datetime, datetime]:
    return g["ts"] - skew, g["ts"] + timedelta(seconds=max(g["seconds"], 0)) + skew


def _names(text: str, token: str) -> bool:
    return bool(token) and re.search(rf"(?<![A-Za-z0-9_-]){re.escape(token)}(?![A-Za-z0-9_-])", text) is not None


def reconcile(
    events: Iterable[dict], grants: list[dict], *, tiers: Iterable[str] = DEFAULT_TIERS, skew_s: int = DEFAULT_SKEW_S
) -> list[dict]:
    tiers = set(tiers)
    skew = timedelta(seconds=skew_s)
    rows = []
    for ev in events:
        times = [t for t in (ev["activated_at"], ev.get("imported_at")) if t is not None]

        def covering(match_name: bool) -> list[dict]:
            hits = []
            for g in grants:
                token = ev["name"] if match_name else ev["workflow_id"]
                if not _names(g["reason"], token):
                    continue
                lo, hi = _window(g, skew)
                if any(lo <= t <= hi for t in times):
                    hits.append(g)
            return hits

        by_id = covering(False)
        good = [g for g in by_id if g["tier"] in tiers]
        if good:
            status, used = GRANTED, good
        elif by_id:
            status, used = NAMED_IN_OTHER_TIER, by_id
        else:
            by_name = [g for g in covering(True) if g["tier"] in tiers]
            status, used = (NAME_ONLY_GRANT, by_name) if by_name else (UNGRANTED_ACTIVATION, [])
        rows.append(
            {
                "workflow_id": ev["workflow_id"],
                "name": ev["name"],
                "version_id": ev["version_id"],
                "currently_active": ev["currently_active"],
                "activated_at": ev["activated_at"].isoformat(),
                "imported_at": ev["imported_at"].isoformat() if ev.get("imported_at") else None,
                "sources": ev["sources"],
                "status": status,
                "grants": [
                    {
                        "ts": g["ts"].isoformat(),
                        "tier": g["tier"],
                        "event_id": g.get("event_id"),
                        "reason": g["reason"][:160],
                    }
                    for g in used
                ],
            }
        )
    return rows


def build_receipt(
    rows: list[dict],
    *,
    since: datetime,
    source: str,
    guard_log: Path,
    tiers: Iterable[str],
    now: Optional[datetime] = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    counts = {
        s: sum(1 for r in rows if r["status"] == s)
        for s in (GRANTED, NAMED_IN_OTHER_TIER, NAME_ONLY_GRANT, UNGRANTED_ACTIVATION)
    }
    findings = [r for r in rows if r["status"] in FINDINGS]
    return {
        "schema": SCHEMA,
        "as_of": now.replace(microsecond=0).isoformat(),
        "since": since.isoformat(),
        "source": source,
        "guard_log": guard_log.name,
        "tiers": sorted(set(tiers)),
        "authority": "READ_ONLY_ADVISORY",
        "events": len(rows),
        "counts": counts,
        "verdict": "CLEAN" if not counts[UNGRANTED_ACTIVATION] else UNGRANTED_ACTIVATION,
        "activations": rows,
        "fanin_findings": [
            {
                "source": "n8n_activation_grants",
                "item": f"{r['workflow_id']}:{r['status']}",
                "severity": "P2" if r["status"] == UNGRANTED_ACTIVATION else "P3",
                "detail": f"{r['name']} activated {r['activated_at']}",
                "artifact_rel": str(RECEIPT_REL),
                "store": "data/runtime",
                "detected_at": r["activated_at"],
            }
            for r in findings
        ],
        # Fan-in source note: n8n_incident_fanin.py can read `fanin_findings` from this receipt as a new
        # source in its own PR. Not wired here, and nothing here sends (Telegram is out of scope).
        "fanin_wired": False,
    }


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="print the verdicts; write nothing (default)")
    mode.add_argument("--write", action="store_true", help="write the receipt under the state root")
    ap.add_argument("--since", default=None, help="ISO time (default: 7 days ago)")
    ap.add_argument(
        "--evidence-json",
        default=None,
        help="read {workflows, publish_history, published_versions, version_history} from this file "
        "instead of the live n8n DB",
    )
    ap.add_argument("--container", default=inv.DB_CONTAINER)
    ap.add_argument("--guard-log", default=None, help="guard audit jsonl (default: what `bin/guard log` reads)")
    ap.add_argument(
        "--tiers", default=",".join(DEFAULT_TIERS), help="grant tiers that authorise an activation (comma separated)"
    )
    ap.add_argument("--skew-s", type=int, default=DEFAULT_SKEW_S)
    ap.add_argument("--receipt", default=None)
    ap.add_argument("--fail-on-ungranted", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    since = parse_ts(a.since) if a.since else datetime.now(timezone.utc) - timedelta(days=7)
    if since is None:
        print(f"n8n activation grants CANNOT RUN: bad --since {a.since!r}", file=sys.stderr)
        return 2
    tiers = [t.strip() for t in a.tiers.split(",") if t.strip()]
    guard_log = Path(a.guard_log) if a.guard_log else default_guard_log()
    try:
        if a.evidence_json:
            evidence = json.loads(Path(a.evidence_json).read_text(encoding="utf-8"))
            source = f"file:{Path(a.evidence_json).name}"
        else:
            evidence = inv.read_activation_evidence(container=a.container)
            source = f"docker exec {a.container} psql (SELECT publish/published/history)"
        grants = load_grants(guard_log)
    except Exception as exc:  # noqa: BLE001 — cannot run != clean
        print(f"n8n activation grants CANNOT RUN: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    rows = reconcile(activation_events(evidence, since=since), grants, tiers=tiers, skew_s=a.skew_s)
    receipt = build_receipt(rows, since=since, source=source, guard_log=guard_log, tiers=tiers)
    if a.write:
        path = Path(a.receipt) if a.receipt else _state_root() / RECEIPT_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(receipt, indent=1) + "\n", encoding="utf-8")
        tmp.replace(path)
        receipt["receipt_path"] = str(path)

    if a.json:
        print(json.dumps(receipt, indent=1))
    else:
        c = receipt["counts"]
        print(
            f"n8n activations since {since.isoformat()}: {receipt['events']}  GRANTED={c[GRANTED]} "
            f"NAMED_IN_OTHER_TIER={c[NAMED_IN_OTHER_TIER]} NAME_ONLY_GRANT={c[NAME_ONLY_GRANT]} "
            f"UNGRANTED_ACTIVATION={c[UNGRANTED_ACTIVATION]}  "
            f"({'written ' + receipt['receipt_path'] if a.write else 'dry-run, nothing written'})"
        )
        for r in rows:
            if r["status"] != GRANTED:
                print(f"    ✗ {r['status']} {r['workflow_id']} {r['name']} at {r['activated_at']}")
    if a.fail_on_ungranted and receipt["verdict"] != "CLEAN":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
