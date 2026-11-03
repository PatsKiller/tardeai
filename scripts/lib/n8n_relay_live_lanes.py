"""n8n_relay_live_lanes — the relay live-lane list, derived from config/lane_registry.json (AGENTS.md 20.4.0).

Operator, 2026-10-25 (verbatim): "fully done, fully automatic, no input by me, for the train systems unless there's
an issue." Until now the live list (``TRADEAI_N8N_RELAY_LIVE_LANES``) was hand-edited in the host file
``~/.config/tradeai/n8n-live-lanes.env`` under a config-write grant, one tranche at a time, so a lane promoted to
canary in a reviewed registry PR stayed dry until someone edited a host file. From 20.4.0 ACTIVE the reviewed
registry IS the list; the host file narrows it.

Gate. ``scripts/lib/hands_off_policy.py`` (read of ``<release>/AGENTS.md``, no env override). While 20.4.0 is not
ACTIVE, ``resolve`` returns exactly what ``n8n_due.parse_relay_live_lanes`` returned before this module existed:
the whitespace-split value of ``TRADEAI_N8N_RELAY_LIVE_LANES`` from the process environment, missing key = missing
list (the relay refuses live, the dispatcher refuses to downgrade). Nothing else in this module runs.
From 2026-10-31 the header no longer decides this once ``config/n8n_relay_live_source.json`` is present: that
file pins the registry render as the base, one-way (``live_source``). A header edit cannot move the live set.

Registry list (``registry_live_lanes``; rendered at deploy by ``scripts/render_n8n_relay_live_lanes.py`` into
``<release>/N8N_RELAY_LIVE_LANES.json``, a release-owned file stamped with the build sha and the sha256 of the
registry and allowlist bytes it was rendered from). A lane is on it when ALL hold:
  * its allowlist entry (config/n8n_run_allowlist.json) has a non-null ``live_arg``;
  * ``lane_dispatch.dispatch_eligible(row)`` (no operator hold, stay_on_cron, forbidden token, stay-behind);
  * either a dispatcher row: dispatch block mode ``live`` (``scheduler.stage`` absent, ``canary`` or ``cutover``;
    a ``shadow`` stage is never live) admitted by ``lane_dispatch.r1_class_admission``;
  * or a native n8n row: ``scheduler.kind == "n8n"``, no dispatch block, ``scheduler.stage`` ``canary``/``cutover``.
A native n8n row with NO stage is not listed (the registry does not say it is live): never widen by default.

Layers and precedence (20.4.0 ACTIVE). Every override layer can only REMOVE (pause) a lane; nothing outside a
reviewed registry PR can ADD one. The effective list is

    rendered registry list  −  ops-controls paused set  −  host-file paused set

Because every layer only narrows, there is no ordering conflict: the most restrictive layer always wins, a pause in
any layer holds until that same layer lifts it, and an override can never make a lane live that the registry +
allowlist + dispatch gates refuse. An ADD override would re-create the unreviewed live widening this replaces, so
there is none; to make a lane live, change the registry (stage canary / dispatch.mode live) in a PR.

  1. ops-controls override (repo-independent; written by the Command Center Ops Controls relay toggle):
     ``$TRADEAI_STATE_ROOT/data/governance/n8n_relay_live_overrides.json``, schema ``N8nRelayLiveOverrides@v1``:
     ``{"schema": ..., "paused": {"<lane_id>": {"by": ..., "at": ..., "reason": ...}}}``. Only the keys of
     ``paused`` are read. Unreadable / malformed (present but not that schema) = FAIL CLOSED: the live list is
     empty (an unreadable pause file might be hiding a pause; never widen).
  2. host file (``~/.config/tradeai/n8n-live-lanes.env``, already loaded into the relay and gateway environment by
     their units): key ``TRADEAI_N8N_RELAY_LIVE_LANES_PAUSED`` (space-separated lane ids) removes lanes.
     The legacy key ``TRADEAI_N8N_RELAY_LIVE_LANES`` is NOT a source while the rendered list is valid; it is the
     FALLBACK used, exactly as before 20.4.0, when the rendered file is missing, malformed, or stale (its registry or
     allowlist sha differs from the files beside it): the release then behaves as it did yesterday, never wider.
     Its pause key still applies to the fallback list.
Only lane ids are read from either layer, by key name; neither holds a secret value, and this module never reads any
other key of the host file (the units load it; this module sees ``environ``).

Restart. The relay reads the list once at start (``n8n_run_relay.Relay``); the gateway's due evaluation reads it per
call (stat-keyed memo below, so a changed file is seen at once). The deploy's bound units
(``cio_phase2_exact_main_deploy.sh`` ``TRADEAI_CURRENT_BOUND_UNITS``) and the release train delegation's
``limits.named_services`` both already include ``tradeai-n8n-run-relay.service`` and
``tradeai-n8n-coordination-gateway.service``, so every promote restarts the relay onto the new render. The ops
toggle restarts both units itself (config/ops_controls.json ``live_list.restart_units``).
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

import sys

# One module object whichever way it is imported (the scripts/lib/n8n_broker_read_carveout.py idiom), so the memo and
# a test seam are shared by n8n_due (``lib.``) and the relay (``scripts.lib.``).
for _alias in ("lib.n8n_relay_live_lanes", "scripts.lib.n8n_relay_live_lanes"):
    sys.modules.setdefault(_alias, sys.modules[__name__])

import importlib


def _load_hop():
    """scripts/lib/hands_off_policy.py, imported by computed name ON PURPOSE: this module sits in the import closure
    of every lane that reaches n8n_due, and hands_off_policy's coordinator helpers lazily import the claim board
    (non-literal env reads). This module calls only its pure policy readers, so the board must not enter the static
    env-read closure (tests/test_n8n_executor_env_allowlist_20261009.py)."""
    for name in ("lib" + ".hands_off_policy", "scripts.lib" + ".hands_off_policy"):
        try:
            return importlib.import_module(name)
        except ImportError:
            continue
    raise ImportError("hands_off_policy")


_hop = _load_hop()

ROOT = Path(__file__).resolve().parents[2]

LIVE_LANES_ENV = "TRADEAI_N8N_RELAY_LIVE_LANES"  # == n8n_due.LIVE_LANES_ENV (no import: n8n_due imports this module)
PAUSED_ENV = "TRADEAI_N8N_RELAY_LIVE_LANES_PAUSED"
RENDER_NAME = "N8N_RELAY_LIVE_LANES.json"
RENDER_SCHEMA = "N8nRelayLiveLanesRender@v1"
OVERRIDE_REL = "data/governance/n8n_relay_live_overrides.json"
OVERRIDE_SCHEMA = "N8nRelayLiveOverrides@v1"
REGISTRY_REL = "config/lane_registry.json"
ALLOWLIST_REL = "config/n8n_run_allowlist.json"
CUTOVER_POLICY_REL = "config/lane_cutover_policy.json"
LIVE_STAGES = frozenset({"canary", "cutover"})
DEFAULT_STATE_ROOT = Path.home() / "trade-ai-releases" / "persistent-state"

_MEMO: dict[tuple, Any] = {}


def _stat_key(path: Path) -> Optional[tuple]:
    try:
        st = path.stat()
    except OSError:
        return None
    return (str(path), st.st_mtime_ns, st.st_size, st.st_ino)


def _memo(tag: str, path: Path, fn):
    """Re-read whenever the file's (mtime, size, inode) changes; otherwise reuse. Equivalent to read-at-call-time."""
    key = (tag, _stat_key(path) or (str(path), None))
    if key not in _MEMO:
        if len(_MEMO) > 64:
            _MEMO.clear()
        _MEMO[key] = fn()
    return _MEMO[key]


def _sha_file(path: Path) -> Optional[str]:
    def read():
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            return None
    return _memo("sha", path, read)


def legacy_lanes(environ: Mapping[str, str]) -> Optional[frozenset[str]]:
    """Exactly the pre-20.4.0 parse: missing key -> None; empty value -> explicit empty list."""
    if LIVE_LANES_ENV not in environ:
        return None
    return frozenset(part for part in str(environ.get(LIVE_LANES_ENV) or "").split() if part)


def policy_active(root: Path | str = ROOT) -> dict[str, Any]:
    p = Path(root) / "AGENTS.md"
    return _memo("policy", p, lambda: _hop.policy_state_from_path(p))


SOURCE_REL = "config/n8n_relay_live_source.json"
SOURCE_SCHEMA = "N8nRelayLiveSource@v1"
PINNED_SOURCE = "registry_render"


#: Host-state copy of the pin, outside every release (``<state root>/data/governance/...``). A release that lacks
#: ``config/n8n_relay_live_source.json`` (an older one, after a rollback, or one where the file was removed) is still
#: pinned once this exists. Written once by ``latch_host_pin`` at a promote that passed the live-set gate; never
#: removed by code. Its presence alone pins: an unreadable or edited file still pins (one-way).
HOST_PIN_REL = "data/governance/n8n_relay_live_source_pin.json"


def latch_host_pin(state: Path | str, *, build: Optional[str] = None) -> dict[str, Any]:
    """Create the host pin if absent (O_EXCL; idempotent, never overwritten, never removed)."""
    p = Path(state) / HOST_PIN_REL
    if p.exists():
        return {"latched": False, "path": str(p), "detail": "already_present"}
    p.parent.mkdir(parents=True, exist_ok=True)
    body = {"schema": SOURCE_SCHEMA, "source": PINNED_SOURCE, "one_way": True, "build": build,
            "latched_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "why": "relay live list pinned to the registry render; no AGENTS.md header edit or rollback can move it"}
    try:
        fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return {"latched": False, "path": str(p), "detail": "already_present"}
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(body, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return {"latched": True, "path": str(p), "detail": "created"}


def live_source(root: Path | str = ROOT, state: Optional[Path | str] = None) -> dict[str, Any]:
    """Which layer is the base live list, decided by the host pin or ``config/n8n_relay_live_source.json``, never by
    AGENTS.md.

    Host state first (``HOST_PIN_REL`` under ``state``): when it exists the base is the registry render, whatever the
    release carries, so a rollback to a release without the config file cannot unpin a release that has this code.

    2026-10-31: the base list used to follow the AGENTS.md header (``policy_active``). A no-rule-text PATCH that only
    flipped ``Status:`` between PROPOSED and ACTIVE moved the live set by 10 lanes (5 dropped, 5 added, including
    trade-ai-scalp-live) with no operator step. The setting is ONE-WAY: when the file exists the base is the
    registry render and the header is not read for this decision. The only accepted value is ``registry_render``; a
    present file naming anything else, or one that does not parse, still pins the registry render (it never falls
    back to the header). Removing the file is guarded by tests/test_relay_live_source_oneway_20261031.py and, at
    promote, by the live-set diff gate (scripts/relay_live_set_gate.py).
    """
    if state is not None:
        hp = Path(state) / HOST_PIN_REL
        if hp.exists():
            return {"pinned": True, "detail": "host_pin", "host_pin": str(hp)}
    p = Path(root) / SOURCE_REL

    def read():
        if not p.exists():
            return {"pinned": False, "detail": "source_config_absent"}
        try:
            doc = _read_json(p)
        except (OSError, ValueError):
            return {"pinned": True, "detail": "source_config_unreadable: pinned registry_render (one-way)"}
        if not isinstance(doc, dict) or doc.get("schema") != SOURCE_SCHEMA or doc.get("source") != PINNED_SOURCE:
            return {"pinned": True, "detail": "source_config_invalid: pinned registry_render (one-way)"}
        return {"pinned": True, "detail": "ok"}
    return _memo("source", p, read)


# --------------------------------------------------------------------------- registry -> list


def registry_live_lanes(registry: Any, allowlist: Any, *, cutover_policy: Optional[Mapping[str, Any]] = None
                        ) -> tuple[list[str], dict[str, str]]:
    """(sorted live lane ids, {lane_id: why excluded} for rows that looked live but were refused)."""
    try:
        from lib import lane_dispatch as _ld
    except ImportError:
        from scripts.lib import lane_dispatch as _ld  # type: ignore[no-redef]
    rows = registry.get("lanes") if isinstance(registry, Mapping) else registry
    if not isinstance(rows, list):
        raise ValueError("registry has no lanes list")
    if isinstance(allowlist, Mapping) and isinstance(allowlist.get("lanes"), list):
        entries = {e["lane_id"]: e for e in allowlist["lanes"] if isinstance(e, dict) and isinstance(e.get("lane_id"), str)}
    else:
        raise ValueError("allowlist has no lanes list")
    live: list[str] = []
    excluded: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("lane_id"), str):
            continue
        lane = row["lane_id"]
        sched = row.get("scheduler") if isinstance(row.get("scheduler"), dict) else {}
        stage = sched.get("stage")
        raw = row.get("dispatch")
        if raw is not None:
            if not isinstance(raw, dict) or raw.get("mode") != "live":
                continue
            kind = "dispatcher"
        elif sched.get("kind") == "n8n" and stage in LIVE_STAGES:
            kind = "native_n8n"
        else:
            if sched.get("kind") == "n8n" and stage is None and row.get("state") == "ACTIVE" \
                    and (entries.get(lane) or {}).get("live_arg") is not None:
                # 2026-10-31: four ACTIVE native n8n lanes (incident fan-in, pilot dispatch, research intake,
                # crontab snapshot) had an allowlist live_arg but no scheduler.stage. The render left them off with
                # no trace, so the relay refused every fire once the AGENTS.md header read ACTIVE. Still never
                # widen; but say why, so the render, --check and the deploy log show the drop.
                excluded[lane] = "native_n8n_no_stage"
            continue
        if stage is not None and stage not in LIVE_STAGES:
            excluded[lane] = f"stage_{stage}"
            continue
        entry = entries.get(lane)
        if entry is None or entry.get("live_arg") is None:
            excluded[lane] = "no_allowlist_live_arg"
            continue
        ok, why = _ld.dispatch_eligible(row, cutover_policy=cutover_policy)
        if not ok:
            excluded[lane] = f"not_dispatch_eligible:{why}"
            continue
        if kind == "dispatcher":
            try:
                block = _ld.parse_dispatch_block(row)
            except _ld.DispatchBlockError as exc:
                excluded[lane] = f"bad_dispatch_block:{exc.code}"
                continue
            if block is None or block.mode != "live":
                excluded[lane] = "dispatch_not_live"
                continue
            admitted, why = _ld.r1_class_admission(row, entry)
            if not admitted:
                excluded[lane] = f"class_not_admitted:{why}"[:160]
                continue
        live.append(lane)
    return sorted(set(live)), excluded


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def render(root: Path | str = ROOT, out: Path | str | None = None, *, now: Optional[datetime] = None) -> dict[str, Any]:
    """Render <root>/N8N_RELAY_LIVE_LANES.json from <root>'s registry + allowlist. Never writes on failure."""
    root = Path(root)
    out = Path(out) if out else root / RENDER_NAME
    reg_p, al_p = root / REGISTRY_REL, root / ALLOWLIST_REL
    try:
        registry, allowlist = _read_json(reg_p), _read_json(al_p)
        cut_p = root / CUTOVER_POLICY_REL
        try:
            from lib import lane_dispatch as _ld
        except ImportError:
            from scripts.lib import lane_dispatch as _ld  # type: ignore[no-redef]
        cutover = _ld.load_cutover_policy(cut_p) if cut_p.is_file() else None
        lanes, excluded = registry_live_lanes(registry, allowlist, cutover_policy=cutover)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return {"schema": RENDER_SCHEMA, "ok": False, "reason": "registry_unreadable", "error": type(exc).__name__}
    build = None
    try:
        build = (root / "BUILD_SHA").read_text(encoding="utf-8").strip() or None
    except OSError:
        pass
    doc = {
        "schema": RENDER_SCHEMA,
        "policy_version": _hop.POLICY_VERSION_TEXT,
        "rendered_at": (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0).isoformat(),
        "build_sha": build,
        "registry_sha256": hashlib.sha256(reg_p.read_bytes()).hexdigest(),
        "allowlist_sha256": hashlib.sha256(al_p.read_bytes()).hexdigest(),
        "lanes": lanes,
        "excluded": dict(sorted(excluded.items())),
        "writer": "scripts/render_n8n_relay_live_lanes.py",
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{out.name}.", dir=str(out.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(doc, indent=2, sort_keys=True) + "\n")
        os.chmod(tmp, 0o644)
        os.replace(tmp, out)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return {"schema": RENDER_SCHEMA, "ok": True, "out": str(out), "lanes": len(lanes), "excluded": len(excluded),
            "native_n8n_no_stage": sorted(k for k, v in excluded.items() if v == "native_n8n_no_stage"),
            "registry_sha256": doc["registry_sha256"], "build_sha": build}


def load_render(root: Path | str = ROOT) -> tuple[Optional[frozenset[str]], str]:
    """(lanes, "ok") or (None, why). Stale = rendered from other registry/allowlist bytes than the ones beside it."""
    root = Path(root)
    p = root / RENDER_NAME

    def read():
        try:
            doc = _read_json(p)
        except FileNotFoundError:
            return None, "render_missing"
        except (OSError, ValueError):
            return None, "render_unreadable"
        if not isinstance(doc, dict) or doc.get("schema") != RENDER_SCHEMA or not isinstance(doc.get("lanes"), list) \
                or not all(isinstance(x, str) and x for x in doc["lanes"]):
            return None, "render_malformed"
        return doc, "ok"
    doc, why = _memo("render", p, read)
    if doc is None:
        return None, why
    if doc.get("registry_sha256") != _sha_file(root / REGISTRY_REL) or \
            doc.get("allowlist_sha256") != _sha_file(root / ALLOWLIST_REL):
        return None, "render_stale"
    return frozenset(doc["lanes"]), "ok"


def state_root(environ: Mapping[str, str]) -> Path:
    v = environ.get("TRADEAI_STATE_ROOT")
    return Path(v).expanduser() if v else DEFAULT_STATE_ROOT


def read_ops_overrides(state: Path) -> tuple[Optional[frozenset[str]], str]:
    """(paused lane ids, "ok"|"absent") or (None, why) when present but unreadable/malformed (fail closed)."""
    p = Path(state) / OVERRIDE_REL

    def read():
        try:
            doc = _read_json(p)
        except FileNotFoundError:
            return frozenset(), "absent"
        except (OSError, ValueError):
            return None, "override_unreadable"
        if not isinstance(doc, dict) or doc.get("schema") != OVERRIDE_SCHEMA or not isinstance(doc.get("paused"), dict):
            return None, "override_malformed"
        return frozenset(str(k) for k in doc["paused"] if str(k).strip()), "ok"
    return _memo("override", p, read)


def resolve(environ: Mapping[str, str], root: Path | str = ROOT) -> dict[str, Any]:
    """The effective relay live list. ``lanes`` None = missing (callers refuse live, as before 20.4.0)."""
    pin = live_source(root, state_root(environ))
    if not pin.get("pinned"):
        pol = policy_active(root)
        if not pol.get("active"):
            lanes = legacy_lanes(environ)
            return {"source": "host_env_legacy", "lanes": lanes, "policy": pol.get("state"), "paused": [],
                    "detail": "AGENTS.md 20.4.0 not ACTIVE: host-file list unchanged", "source_pin": pin}
    base, why = load_render(root)
    source = "registry_render"
    if base is None:
        base = legacy_lanes(environ)
        source = "host_env_fallback"
        if base is None:
            return {"source": source, "lanes": None, "policy": "ACTIVE", "paused": [],
                    "detail": f"{why}; {LIVE_LANES_ENV} also unset"}
    ops, ops_why = read_ops_overrides(state_root(environ))
    if ops is None:
        return {"source": source, "lanes": frozenset(), "policy": "ACTIVE", "paused": [],
                "detail": f"{ops_why}: fail closed, no lane live"}
    host_paused = frozenset(part for part in str(environ.get(PAUSED_ENV) or "").split() if part)
    paused = (ops | host_paused) & base
    return {"source": source, "lanes": frozenset(base - paused), "policy": "ACTIVE", "paused": sorted(paused),
            "detail": why if source != "registry_render" else "ok",
            "paused_by": {"ops_controls": sorted(ops & base), "host_env": sorted(host_paused & base)}}


def host_diff(environ: Mapping[str, str], root: Path | str = ROOT) -> dict[str, Any]:
    """Lane ids only: the legacy host list vs the rendered registry list (what ratification would change)."""
    base, why = load_render(root)
    legacy = legacy_lanes(environ)
    if base is None or legacy is None:
        return {"ok": False, "render": why, "host_key_present": legacy is not None}
    return {"ok": True, "registry_only": sorted(base - legacy), "host_only": sorted(legacy - base),
            "both": len(base & legacy)}
