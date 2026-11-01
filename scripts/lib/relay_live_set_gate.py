"""relay_live_set_gate — what a promote would change in the n8n relay's EFFECTIVE live-lane set, and a hold on it.

2026-10-31: the relay's live list changed by 10 lanes at a promote that changed no rule text (5 lanes stopped, 5
went live, including trade-ai-scalp-live), and nothing said so: the deploy log showed "render OK", the Jobs page
showed "Missed" hours later. This module compares the live set the NEW release would serve with the one the CURRENT
release serves, using the same resolver the relay uses (``n8n_relay_live_lanes.resolve``), and

  * at prepare: reports the difference (WARN line, ``<release>/N8N_RELAY_LIVE_SET_DIFF.json``, one page through the
    communications gateway ``telegram_alert.send_telegram``);
  * at promote: refuses while the difference is not acknowledged by the operator
    (``scripts/relay_live_set_gate.py ack``; ack ids are bound to the new build sha and the exact lane delta);
  * records every exclusion: each lane that could be live (allowlist ``live_arg`` or a live-looking registry row)
    but is not in the effective set, with the reason.

Inputs are lane ids only. The host file ``~/.config/tradeai/n8n-live-lanes.env`` is read for exactly two keys
(``TRADEAI_N8N_RELAY_LIVE_LANES`` and ``..._PAUSED``, lane-id lists); every other line is skipped unread.

AUTHORITY: READ_ONLY_ADVISORY. It changes no lane; only a reviewed registry PR does that.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

try:
    from lib import n8n_relay_live_lanes as RLL
except ImportError:  # pragma: no cover - imported as scripts.lib
    from scripts.lib import n8n_relay_live_lanes as RLL  # type: ignore[no-redef]

SCHEMA = "RelayLiveSetDiff@v1"
ACK_SCHEMA = "RelayLiveSetAck@v1"
DIFF_NAME = "N8N_RELAY_LIVE_SET_DIFF.json"
ACK_REL = "data/governance/relay_live_set_acks.jsonl"
DEFAULT_HOST_FILE = Path.home() / ".config" / "tradeai" / "n8n-live-lanes.env"
HOST_KEYS = (RLL.LIVE_LANES_ENV, RLL.PAUSED_ENV)


def host_env(path: Optional[Path]) -> dict[str, str]:
    """{key: lane ids} for the two lane-list keys only. Missing file = {} (the resolver then sees no host list)."""
    out: dict[str, str] = {}
    if path is None:
        return out
    try:
        fh = Path(path).open(encoding="utf-8")
    except OSError:
        return out
    with fh:
        for line in fh:
            s = line.strip()
            for key in HOST_KEYS:
                if s.startswith(key + "="):
                    out[key] = s.split("=", 1)[1].strip().strip("'\"").replace(",", " ")
    return out


def _build(root: Path) -> Optional[str]:
    try:
        return (Path(root) / "BUILD_SHA").read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def effective(root: Path, environ: Mapping[str, str]) -> dict[str, Any]:
    res = RLL.resolve(environ, root)
    lanes = res.get("lanes")
    return {"lanes": None if lanes is None else sorted(lanes), "source": res.get("source"),
            "detail": res.get("detail"), "paused": list(res.get("paused") or [])}


def _render_excluded(root: Path) -> dict[str, str]:
    try:
        doc = json.loads((Path(root) / RLL.RENDER_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    ex = doc.get("excluded") if isinstance(doc, dict) else None
    return {str(k): str(v) for k, v in ex.items()} if isinstance(ex, dict) else {}


def exclusions(root: Path, eff: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """{lane: {"reason", "registry_state"}} for every lane that could be live but is not in the effective set."""
    root = Path(root)
    try:
        registry = json.loads((root / RLL.REGISTRY_REL).read_text(encoding="utf-8"))
        allowlist = json.loads((root / RLL.ALLOWLIST_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"*": {"reason": "registry_or_allowlist_unreadable", "registry_state": None}}
    rows = {r["lane_id"]: r for r in (registry.get("lanes") or []) if isinstance(r, dict) and isinstance(r.get("lane_id"), str)}
    entries = {e["lane_id"]: e for e in (allowlist.get("lanes") or []) if isinstance(e, dict) and isinstance(e.get("lane_id"), str)}
    candidates = {lane for lane, e in entries.items() if e.get("live_arg") is not None}
    for lane, row in rows.items():
        sched = row.get("scheduler") if isinstance(row.get("scheduler"), dict) else {}
        disp = row.get("dispatch") if isinstance(row.get("dispatch"), dict) else None
        if sched.get("kind") == "n8n" or (disp is not None and disp.get("mode") == "live"):
            candidates.add(lane)
    live = set(eff.get("lanes") or [])
    paused = set(eff.get("paused") or [])
    render_ex = _render_excluded(root)
    out: dict[str, dict[str, Any]] = {}
    for lane in sorted(candidates - live):
        row = rows.get(lane)
        state = row.get("state") if isinstance(row, dict) else None
        if eff.get("lanes") is None:
            reason = f"no_live_list:{eff.get('detail')}"
        elif lane in paused:
            reason = "paused_by_override"
        elif lane in render_ex:
            reason = render_ex[lane]
        elif eff.get("source") != "registry_render":
            reason = f"not_on_{eff.get('source')}_list"
        elif row is None:
            reason = "no_registry_row"
        else:
            sched = row.get("scheduler") if isinstance(row.get("scheduler"), dict) else {}
            disp = row.get("dispatch")
            stage = sched.get("stage")
            entry = entries.get(lane)
            if entry is None or entry.get("live_arg") is None:
                reason = "no_allowlist_live_arg"
            elif isinstance(disp, dict) and disp.get("mode") != "live":
                reason = f"dispatch_mode_{disp.get('mode')}"
            elif disp is None and sched.get("kind") != "n8n":
                reason = f"scheduler_{sched.get('kind')}_not_n8n"
            elif disp is None and stage is None:
                reason = "native_n8n_no_stage"
            elif stage is not None and stage not in RLL.LIVE_STAGES:
                reason = f"stage_{stage}"
            else:
                reason = "not_in_render"
        out[lane] = {"reason": reason, "registry_state": state}
    return out


def diff_id(build: Optional[str], added: list[str], removed: list[str]) -> str:
    blob = json.dumps({"build": build, "added": added, "removed": removed}, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def compute(new_root: Path, served_root: Path, environ: Mapping[str, str]) -> dict[str, Any]:
    new_root, served_root = Path(new_root), Path(served_root)
    new, old = effective(new_root, environ), effective(served_root, environ)
    a, b = set(new["lanes"] or []), set(old["lanes"] or [])
    added, removed = sorted(a - b), sorted(b - a)
    build = _build(new_root)
    return {
        "schema": SCHEMA,
        "computed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "new_release": str(new_root), "new_build": build,
        "served_release": str(served_root), "served_build": _build(served_root),
        "new": {k: new[k] for k in ("source", "detail")} | {"count": len(a), "list_missing": new["lanes"] is None},
        "served": {k: old[k] for k in ("source", "detail")} | {"count": len(b), "list_missing": old["lanes"] is None},
        "added": added, "removed": removed,
        "changed": bool(added or removed) or (new["lanes"] is None) != (old["lanes"] is None),
        "diff_id": diff_id(build, added, removed),
        "exclusions": exclusions(new_root, new),
    }


def _acks(state: Path) -> list[dict]:
    p = Path(state) / ACK_REL
    out = []
    try:
        with p.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and row.get("schema") == ACK_SCHEMA:
                    out.append(row)
    except OSError:
        pass
    return out


def is_acked(state: Path, report: Mapping[str, Any]) -> bool:
    return any(r.get("diff_id") == report["diff_id"] and r.get("new_build") == report["new_build"] for r in _acks(state))


def record_ack(state: Path, report: Mapping[str, Any], by: str) -> dict:
    if not str(by or "").strip():
        raise ValueError("ack needs --by")
    row = {"schema": ACK_SCHEMA, "diff_id": report["diff_id"], "new_build": report["new_build"],
           "added": report["added"], "removed": report["removed"], "by": str(by).strip(),
           "at": datetime.now(timezone.utc).replace(microsecond=0).isoformat()}
    p = Path(state) / ACK_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return row


def gate(report: Mapping[str, Any], state: Path) -> tuple[bool, str]:
    if not report["changed"]:
        return True, "unchanged"
    if is_acked(state, report):
        return True, "acknowledged"
    return False, "unacknowledged"


def message(report: Mapping[str, Any], ack_cmd: str) -> str:
    def lst(xs: list[str]) -> str:
        return ", ".join(xs[:20]) + (f" (+{len(xs) - 20} more)" if len(xs) > 20 else "") if xs else "none"
    return (f"RELAY LIVE SET WOULD CHANGE at promote of {str(report.get('new_build') or '?')[:12]}: "
            f"+{len(report['added'])} / -{len(report['removed'])} lanes "
            f"({report['served']['source']} -> {report['new']['source']}).\n"
            f"Would go live: {lst(report['added'])}\nWould stop: {lst(report['removed'])}\n"
            f"Promote is held until you acknowledge: {ack_cmd}")


def notify(report: Mapping[str, Any], ack_cmd: str, sender: Optional[Callable[..., Any]] = None) -> dict:
    """One page through the communications gateway; fail-soft, the result goes in the report."""
    try:
        if sender is None:
            from telegram_alert import send_telegram as sender  # type: ignore[no-redef]
        ok = sender(message(report, ack_cmd), priority="P1", dedupe_minutes=60, producer="relay_live_set_gate")
        return {"accepted": bool(ok)}
    except Exception as exc:  # noqa: BLE001 - recorded, never fatal at prepare
        return {"accepted": False, "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
