"""Operator env overlay: Ops -> Controls toggles that used to be hand edits of ``.env`` (2026-10-25).

Operator 2026-10-25 (verbatim): "this should have just been a toggle to turn on/off on the control ops."

Source of truth: the Postgres ``operator_settings`` table (AGENTS.md §27.2), changed only through Ops -> Controls
(``setting.set`` / ``setting.unset``, preview -> passkey + typed phrase -> the one governed host applier). Catalog
entries in ``config/ops_controls.json`` ``settings_catalog`` that carry an ``env_key`` are projected by the applier,
after every applied change, into one small JSON file (``settings_projection.file``; registered as a derived copy of
the ``operator_settings`` domain in ``config/data_source_authority.json``). Consumers read that projection here.

Why a projection and not a write into ``.env``: the cron lines source the primary checkout's ``.env`` (``set -a; .
./.env``), which also holds every credential; rewriting it from a web-triggered process puts every secret and every
cron job (~all of them source it) behind one line-edit. The projection is non-secret, is read at call time (no
restart, no re-source), and when it is absent or unreadable every consumer falls back to its environment exactly as
before (backward compatible).

Precedence for the managed names only: projection value (operator setting) > process environment (.env) > the
consumer's own default. ``MANAGED`` is a hard allowlist of non-secret names; nothing else is ever read from or written
by the projection, and a secret-looking name is refused at render time.

``sync_environ()`` copies projected values into ``os.environ`` (literal names) so code that reads the environment
directly (``scripts/alerting.send_sms`` reads ``ENABLE_SMS`` / ``OPERATOR_SMS_EMAIL``) sees the operator's setting.
It touches only names the projection sets, remembers each one's previous value and restores it when the setting is
unset; a process whose projection never names a key is never changed. ``scripts/lib/comms/mode.resolve_mode`` calls
it, and every gateway send resolves the mode first. No environment variable is read by name other than the three
managed ones (the projection path comes from the config file; tests set ``PATH_OVERRIDE``). MBI_BEHAVIOR = 0.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

SCHEMA = "OpsSettingsEnvProjection@v1"
CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "ops_controls.json"

#: The only names the projection may carry. Non-secret by construction (reviewed PR to change).
MANAGED: tuple[str, ...] = ("COMMS_GATEWAY_MODE", "ENABLE_SMS", "OPERATOR_SMS_EMAIL")
SECRET_NAME_RE = re.compile(r"(?i)(TOKEN|SECRET|PASSWORD|PASSWD|PRIVATE|BEARER|DSN|AUTH|API_?KEY|_KEY$|^KEY_)")

#: Tests point the reader at a temp file; production reads ``settings_projection.file`` from the config.
PATH_OVERRIDE: Optional[Path] = None

_cache: dict[str, Any] = {"sig": None, "values": {}, "doc": None, "state": "ABSENT"}
_applied: dict[str, Optional[str]] = {}   # name -> environment value before the overlay first set it


def is_secret_name(name: str) -> bool:
    return bool(SECRET_NAME_RE.search(str(name or "")))


def projection_path(cfg: Optional[Mapping[str, Any]] = None) -> Optional[Path]:
    if PATH_OVERRIDE is not None:
        return Path(PATH_OVERRIDE)
    try:
        doc = cfg if cfg is not None else json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    f = (doc.get("settings_projection") or {}).get("file") if isinstance(doc, Mapping) else None
    return Path(os.path.expanduser(str(f))) if f else None


def read_projection(path: Optional[Path] = None) -> dict[str, Any]:
    """{"state": OK|ABSENT|INVALID, "values": {name: str}, "doc": dict|None, "path": str|None}. Cached on mtime."""
    p = Path(path) if path is not None else projection_path()
    if p is None:
        return {"state": "ABSENT", "values": {}, "doc": None, "path": None}
    try:
        st = p.stat()
    except OSError:
        return {"state": "ABSENT", "values": {}, "doc": None, "path": str(p)}
    sig = (str(p), st.st_mtime_ns, st.st_size)
    if _cache["sig"] != sig:
        state, values, doc = "INVALID", {}, None
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(doc, dict) and doc.get("schema") == SCHEMA and isinstance(doc.get("values"), dict):
                values = {k: v for k, v in doc["values"].items() if k in MANAGED and isinstance(v, str)}
                state = "OK"
        except (OSError, ValueError):
            doc = None
        _cache.update(sig=sig, values=values, doc=doc, state=state)
    return {"state": _cache["state"], "values": dict(_cache["values"]), "doc": _cache["doc"], "path": str(p)}


def value(name: str) -> Optional[str]:
    """The operator's projected value for one managed name, or None (then the environment applies)."""
    if name not in MANAGED:
        return None
    return read_projection()["values"].get(name)


def _set_env(name: str, prev: Optional[str]) -> None:
    if name == "COMMS_GATEWAY_MODE":
        if prev is None:
            os.environ.pop("COMMS_GATEWAY_MODE", None)
        else:
            os.environ["COMMS_GATEWAY_MODE"] = prev
    elif name == "ENABLE_SMS":
        if prev is None:
            os.environ.pop("ENABLE_SMS", None)
        else:
            os.environ["ENABLE_SMS"] = prev
    elif name == "OPERATOR_SMS_EMAIL":
        if prev is None:
            os.environ.pop("OPERATOR_SMS_EMAIL", None)
        else:
            os.environ["OPERATOR_SMS_EMAIL"] = prev


def _current(name: str) -> Optional[str]:
    if name == "COMMS_GATEWAY_MODE":
        return os.environ.get("COMMS_GATEWAY_MODE")
    if name == "ENABLE_SMS":
        return os.environ.get("ENABLE_SMS")
    if name == "OPERATOR_SMS_EMAIL":
        return os.environ.get("OPERATOR_SMS_EMAIL")
    return None


def baseline(name: str) -> Optional[str]:
    """The process environment's own value (what .env / the unit gave it), ignoring anything the overlay set."""
    if name in _applied:
        return _applied[name]
    return _current(name)


def sync_environ() -> dict[str, str]:
    """Make ``os.environ`` agree with the projection for the managed names it sets. Returns the applied values.

    Never raises: an unreadable projection leaves the environment exactly as it is (and restores nothing it did not
    set)."""
    try:
        vals = read_projection()["values"]
    except Exception:  # noqa: BLE001 — the overlay never breaks a consumer
        return {}
    for name in MANAGED:
        if name in vals:
            if name not in _applied:
                _applied[name] = _current(name)
            _set_env(name, vals[name])
        elif name in _applied:
            _set_env(name, _applied.pop(name))
    return dict(vals)


# ── writer side (the host applier only) ─────────────────────────────────────────────────────────────────────────────


def _env_text(entry: Mapping[str, Any], v: Any) -> str:
    if entry.get("type") == "bool":
        return "true" if v is True else "false"
    return str(v)


def render(settings: Mapping[str, Mapping[str, Any]], catalog: Iterable[Mapping[str, Any]], *,
           now: Optional[datetime] = None) -> dict[str, Any]:
    """The projection document for the active settings whose catalog entry names a managed ``env_key``. Pure."""
    values: dict[str, str] = {}
    meta: dict[str, dict] = {}
    for e in catalog:
        name = e.get("env_key")
        if not name:
            continue
        if name not in MANAGED or is_secret_name(name):
            raise ValueError(f"env_key {name!r} is not a managed non-secret name")
        row = settings.get(e.get("key")) or {}
        if not row.get("active"):
            continue
        values[name] = _env_text(e, row.get("value"))
        at = row.get("updated_at")
        meta[name] = {"key": e.get("key"), "updated_by": row.get("updated_by"), "request_id": row.get("request_id"),
                      "updated_at": at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
                      if isinstance(at, datetime) else at}
    ts = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return {"schema": SCHEMA, "generated_at": ts, "writer": "scripts/ops/operator_controls_applier.py",
            "source": "operator_settings (Postgres); precedence: this file > process environment > consumer default",
            "values": values, "settings": meta}


def write_projection(path: Path, doc: Mapping[str, Any]) -> None:
    """Atomic write (tmp + fsync + rename, 0600) in the target directory."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(doc, indent=1, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
