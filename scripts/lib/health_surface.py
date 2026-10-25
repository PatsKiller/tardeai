"""Read-only Health page normalization over existing snapshots and remediation logs.

No action, retry, broker import or persistent write. Deduplication changes the
displayed population only; control state and the collector's score stay intact.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re


def _at(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (ValueError, TypeError):
        return None


def normalize_snapshot(snapshot):
    snap = dict(snapshot or {})
    findings = [deepcopy(row) for row in snap.get("findings") or [] if isinstance(row, dict)]
    switches = [row for row in findings if row.get("type") == "kill_switch_active"]
    unique = {}
    rank = {"critical": 0, "warning": 1, "info": 2}
    for finding in findings:
        kind = finding.get("type")
        message = str(finding.get("message") or "")
        if switches and kind == "execution_state_conflict" and "kill_switch" in message:
            # This collector explicitly mirrors the control-state summary. Keep
            # its evidence under the actual control finding, never count it twice.
            switches[0].setdefault("related_evidence", []).append(finding)
            continue
        control = None
        if kind == "kill_switch_active":
            match = re.search(r"Kill switch ([a-z0-9_]+):", message, re.I)
            control = finding.get("level") or (match[1] if match else message)
        key = (finding.get("category"), kind, control, finding.get("symbol"), finding.get("account"),
               None if control else message)
        if key not in unique:
            unique[key] = finding
        else:
            prior = unique[key]
            if rank.get(finding.get("severity"), 9) < rank.get(prior.get("severity"), 9):
                finding.setdefault("related_evidence", []).append(prior)
                unique[key] = finding
            else:
                prior.setdefault("related_evidence", []).append(finding)
    rows = list(unique.values())
    counts = Counter(row.get("severity") for row in rows)
    snap["findings"] = rows
    snap["counts"] = {**{key: counts[key] for key in ("critical", "warning", "info")},
                      "total": len(rows), "actionable": sum(bool(row.get("actionable")) for row in rows)}
    status = str(snap.get("status") or "unknown").lower()
    score = snap.get("overall_score")
    snap.update(healthy=status == "healthy", headline=f"{status.upper()} {score if score is not None else '?'}/100 — "
                f"{counts['critical']} critical, {counts['warning']} warning")
    return snap


def get_health(*, reader):
    return normalize_snapshot(reader())


def _preview(row):
    return (row.get("dry_run") is True or bool(re.search(r"dry[-_ ]?run|preview|shadow|preflight", str(row.get("mode") or ""), re.I))
            or bool(re.search(r"(?:^|\s)--dry[-_]run(?:\s|$)", str(row.get("cmd") or row.get("script") or ""))))


def _event(row, source):
    preview = _preview(row)
    code = row.get("exit_code")
    verified = (row.get("verified") is True if source == "inspector" else
                row.get("ok") is True and row.get("verified_by_recheck") is True)
    verified = bool(not preview and verified and (code is None or type(code) is int and code == 0))
    failed = row.get("ok") is False or row.get("success") is False or code is not None and code != 0
    return {**row, "timestamp": row.get("timestamp") or row.get("at"), "agent": row.get("agent") or "health_agent",
            "finding": row.get("finding") or row.get("type") or "Recorded event", "verified": verified,
            "dry_run": preview, "mode": "preview" if preview else row.get("mode"),
            "evidence_state": "Preview" if preview else "Verified" if verified else "Failed" if failed else "Unverified",
            "script": row.get("script") or row.get("cmd"), "new_state": row.get("new_state") or row.get("outcome")}


def get_remediation(*, paths, now=None, max_bytes=4 * 1024 * 1024):
    """Read the existing raw records so preview/recheck fields cannot be lost by an adapter."""
    clock = now or datetime.now(timezone.utc)
    agent, inspector = paths() if callable(paths) else paths
    files = [(Path(agent), "agent"), *((Path(path), "inspector") for path in inspector)]
    seen, events, gaps = set(), [], []
    readable = 0
    truncated = False
    for path, source in files:
        resolved = str(path.resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            with path.open("rb") as stream:
                stream.seek(0, 2)
                start = max(0, stream.tell() - max_bytes)
                stream.seek(start)
                raw = stream.read(max_bytes)
            readable += 1
        except OSError:
            gaps.append(f"{source} event history unavailable")
            continue
        if start:
            raw = raw.partition(b"\n")[2]
            truncated = True
        for line in raw.splitlines():
            try:
                row = json.loads(line)
            except (ValueError, UnicodeError):
                gaps.append(f"{source} event record unreadable")
                continue
            if not isinstance(row, dict):
                continue
            at = _at(row.get("timestamp") or row.get("at"))
            if not at or not clock - timedelta(hours=24) <= at <= clock:
                continue
            events.append(_event(row, source))
    events.sort(key=lambda row: _at(row["timestamp"]), reverse=True)
    previews = sum(row["dry_run"] for row in events)
    verified = sum(row["verified"] for row in events)
    attempts = len(events) - previews
    known = readable > 0
    return {"remediations": events[:500], "as_of": clock.isoformat(),
        "stats": {"total_events_24h": len(events) if known else None, "total_events": len(events) if known else None,
                  "preview_events_24h": previews if known else None, "attempts_24h": attempts if known else None,
                  "verified_fixes_24h": verified if known else None, "total_fixes_24h": verified if known else None,
                  "success_rate": f"{verified/attempts*100:.0f}%" if attempts else "N/A",
                  "by_agent": dict(Counter(row["agent"] for row in events)),
                  "by_severity": dict(Counter(row.get("severity") or "unknown" for row in events)),
                  "stats_truncated": truncated},
        "coverage": {"status": "UNAVAILABLE" if not known else "PARTIAL" if gaps or truncated else "AVAILABLE",
                     "gaps": sorted(set(gaps)), "counts_scope": "Observed retained 24h records; partial counts are lower bounds"}}
