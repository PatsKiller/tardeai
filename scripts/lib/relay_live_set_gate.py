"""relay_live_set_gate — what a promote or a rollback would change in the n8n relay's EFFECTIVE live-lane set.

2026-10-31: the relay's live list changed by 10 lanes at a promote that changed no rule text (5 lanes stopped, 5
went live, including trade-ai-scalp-live), and nothing said so. This module compares the live set a release WOULD
serve with the one the CURRENT release serves. Each side is computed with that release's OWN resolver
(``<release>/scripts/lib/n8n_relay_live_lanes.py``, run in a child process), because that is the code the relay
runs after the switch; a release without the module falls back to this process's resolver.

  * prepare: WARN line, ``<release>/N8N_RELAY_LIVE_SET_DIFF.json``, and ONE page per ``diff_id`` (a durable marker in
    host state; the page names only the diff_id, the build and the counts, so a re-prepare cannot page again);
  * promote: refuses while the change is not acknowledged by the OPERATOR. The acknowledgement is an operator guard
    grant: a ``release-write`` row in the guard ledger (``bin/guard``, keyboard or Ops → Controls passkey) whose
    reason contains ``relay-live-set:<diff_id>``, not revoked. There is no agent-runnable ack command, and no ack
    command is printed into deploy logs. ``diff_id`` binds the build sha AND the exact lane delta;
  * rollback: the same diff, WARN and page, never blocking (rollback is the recovery path);
  * records every exclusion: each lane that could be live but is not in the effective set, with the reason.

Inputs are lane ids only. The host file ``~/.config/tradeai/n8n-live-lanes.env`` is read for exactly two keys
(``TRADEAI_N8N_RELAY_LIVE_LANES`` and ``..._PAUSED``, lane-id lists); every other line is skipped unread.

AUTHORITY: READ_ONLY_ADVISORY. It changes no lane; only a reviewed registry PR does that.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

try:
    from lib import n8n_relay_live_lanes as RLL
except ImportError:  # pragma: no cover - imported as scripts.lib
    from scripts.lib import n8n_relay_live_lanes as RLL  # type: ignore[no-redef]

SCHEMA = "RelayLiveSetDiff@v1"
DIFF_NAME = "N8N_RELAY_LIVE_SET_DIFF.json"
#: Durable "this diff_id was paged" markers (host state, one file per diff_id, created O_EXCL).
PAGED_REL = "data/governance/relay_live_set_paged"
#: The guard tier and reason token that acknowledge a live-set change (operator-issued only).
ACK_TIER = "release-write"
ACK_TOKEN = "relay-live-set:"
#: Marker line on stderr when promote is held; deploy_on_main and release_window parse it.
HELD_MARKER = "RELAY_LIVE_SET_HELD"
DEFAULT_HOST_FILE = Path.home() / ".config" / "tradeai" / "n8n-live-lanes.env"
HOST_KEYS = (RLL.LIVE_LANES_ENV, RLL.PAUSED_ENV)


def host_env(path: Optional[Path]) -> dict[str, str]:
    """{key: lane ids} for the two lane-list keys only; every other line is skipped unread.

    Missing or unreadable file = {}: no host list and no host pauses. Under the registry pin the host list is only the
    fallback when the release's render is missing, and ``..._PAUSED`` only narrows the rendered set; an unpinned
    release (header not ACTIVE, no host pin) uses the host list as its whole live set.
    """
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


_OWN_CODE = r"""
import json, sys
root, env = sys.argv[1], json.loads(sys.stdin.read())
sys.path[:0] = [root, root + "/scripts"]
from scripts.lib import n8n_relay_live_lanes as R
res = R.resolve(env, root)
lanes = res.get("lanes")
print(json.dumps({"lanes": None if lanes is None else sorted(lanes), "source": res.get("source"),
                  "detail": res.get("detail"), "paused": list(res.get("paused") or [])}))
"""


def _own_module(root: Path) -> Optional[Path]:
    p = Path(root) / "scripts" / "lib" / "n8n_relay_live_lanes.py"
    return p if p.is_file() else None


def effective(root: Path, environ: Mapping[str, str]) -> dict[str, Any]:
    """The live set ``root`` would serve, computed by ``root``'s own resolver when it has one (an older release runs
    older code: a rollback target may not know the pin at all, and that is what the relay will do)."""
    if _own_module(root) is not None:
        try:
            r = subprocess.run([sys.executable, "-c", _OWN_CODE, str(root)], input=json.dumps(dict(environ)),
                               capture_output=True, text=True, timeout=60, check=False, cwd=str(root))
            if r.returncode == 0:
                out = json.loads(r.stdout.strip().splitlines()[-1])
                out["resolver"] = "own"
                return out
            why = (r.stderr or "").strip().splitlines()[-1:] or ["rc=%d" % r.returncode]
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            why = [f"{type(exc).__name__}"]
        return {"lanes": None, "source": "resolver_failed", "detail": f"own resolver failed: {why[0][:160]}",
                "paused": [], "resolver": "own_failed"}
    res = RLL.resolve(environ, root)
    lanes = res.get("lanes")
    return {"lanes": None if lanes is None else sorted(lanes), "source": res.get("source"),
            "detail": res.get("detail"), "paused": list(res.get("paused") or []), "resolver": "gate"}


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


def _guard_rows() -> dict[str, dict[str, Any]]:
    """All guard ledger rows (any status), read-only. GUARD_APPROVALS_DIR selects the ledger (tests)."""
    import importlib.util

    for base in (Path(__file__).resolve().parents[2], Path.home() / "trade-ai-v12-rebuild" / "trade-ai-v12-rebuild"):
        path = base / ".cursor" / "hooks" / "guard_ledger.py"
        if path.is_file():
            break
    else:
        return {}
    spec = importlib.util.spec_from_file_location("_rlsg_guard_ledger", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    try:
        return dict(mod.ledger_list(mod.approvals_dir()).get("rows") or {})
    except Exception:  # noqa: BLE001 - an unreadable ledger acknowledges nothing (fail closed)
        return {}


def acknowledgement(report: Mapping[str, Any], rows: Optional[Mapping[str, Mapping[str, Any]]] = None
                    ) -> Optional[dict[str, Any]]:
    """The operator guard grant that acknowledges exactly this change, or None.

    A ``release-write`` ledger row whose reason contains ``relay-live-set:<diff_id>`` and that was not revoked. The
    diff_id already binds the build and the lane delta, so a grant for one delta never acknowledges another.
    """
    token = ACK_TOKEN + str(report["diff_id"])
    rows = _guard_rows() if rows is None else rows
    for key, row in sorted(rows.items()):
        if not isinstance(row, Mapping) or row.get("tier") != ACK_TIER or row.get("status") == "revoked":
            continue
        reason = str(row.get("reason") or "")
        if token in reason.replace(" ", ""):
            return {"grant_id": row.get("grant_id") or key.split("@", 1)[-1], "status": row.get("status")}
    return None


def is_acked(report: Mapping[str, Any], rows: Optional[Mapping[str, Mapping[str, Any]]] = None) -> bool:
    return acknowledgement(report, rows) is not None


def gate(report: Mapping[str, Any], rows: Optional[Mapping[str, Mapping[str, Any]]] = None) -> tuple[bool, str]:
    if not report["changed"]:
        return True, "unchanged"
    if is_acked(report, rows):
        return True, "acknowledged"
    return False, "unacknowledged"


def message(report: Mapping[str, Any], *, event: str = "promote") -> str:
    """Page text. Names only the diff_id, the build and the counts: stable for one diff_id, so it dedupes, and it
    carries no release path and no command."""
    build = str(report.get("new_build") or "?")[:12]
    held = ("Promote is held until the operator acknowledges this diff_id."
            if event == "promote" else "Rollback is not held; review the diff.")
    return (f"RELAY LIVE SET CHANGE ({event}) diff_id {report['diff_id']} build {build}: "
            f"{len(report['added'])} lanes would go live, {len(report['removed'])} would stop. {held}")


def _paged_marker(state: Path, did: str) -> Path:
    return Path(state) / PAGED_REL / f"{did}.json"


def notify(report: Mapping[str, Any], state: Path, *, event: str = "promote",
           sender: Optional[Callable[..., Any]] = None) -> dict:
    """At most one page per diff_id, ever: the marker is created O_EXCL BEFORE sending, so concurrent or repeated
    prepares cannot page twice. Fail-soft; the result goes in the report."""
    marker = _paged_marker(state, f"{report['diff_id']}-{event}")
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(marker), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return {"accepted": False, "skipped": "already_paged", "marker": str(marker)}
    except OSError as exc:
        return {"accepted": False, "error": f"marker: {type(exc).__name__}"}
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"diff_id": report["diff_id"], "build": report.get("new_build"), "event": event,
                             "at": datetime.now(timezone.utc).replace(microsecond=0).isoformat()}) + "\n")
    try:
        if sender is None:
            from telegram_alert import send_telegram as sender  # type: ignore[no-redef]
        ok = sender(message(report, event=event), priority="P1", dedupe_minutes=60, producer="relay_live_set_gate")
        return {"accepted": bool(ok), "marker": str(marker)}
    except Exception as exc:  # noqa: BLE001 - recorded, never fatal
        return {"accepted": False, "error": f"{type(exc).__name__}: {str(exc)[:160]}", "marker": str(marker)}
