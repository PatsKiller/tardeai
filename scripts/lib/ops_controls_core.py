"""Ops -> Controls core: policy gate, change kinds, phrases, preview (dry run), apply, verify and undo.

AGENTS.md 19.0.0 §27.2-§27.3 (PROPOSED). Shared by the Command Center handler (scripts/lib/ops_controls_api.py, which
only PREVIEWS and records requests) and the one governed host applier (scripts/ops/operator_controls_applier.py, which
is the only process that APPLIES a host change). Docs: docs/ops/OPS_CONTROLS.md, docs/ops/OPS_CONTROLS_API.md.

Inert by construction: :func:`policy_state` reads AGENTS.md at call time and answers ACTIVE only when the 19.0.0
version-history row says ACTIVE and §27.3 is present; every mutating caller refuses ``POLICY_NOT_ACTIVE`` otherwise.

Never touched here: broker-execution code, kill-switch code, credentials, AGENTS.md, guard surfaces. The kill-switch
ENGAGE kind only runs the existing operator CLI (``scripts/brokers/kill_switches.py --enable``) as a subprocess; its
CLEAR kind is NOT_SUPPORTED (an ``execution-engineering`` grant would be needed to call or test the clear path).
Release-train resume and arm (2026-10-22, AGENTS.md 19.0.0 §25.4 / §27.3) are risky kinds executed by the host
applier: the applier hands ``release_control`` a ``PasskeyProof`` and a hook bound to the one HMAC-signed approval it is
applying, which must have been stepped up with a fresh passkey assertion (factor ``passkey``) and must carry the phrase
``release_control`` expects now (``RESUME EPOCH <n>`` / ``ARM EPOCH <n>``). Scope change and revoke stay host-CLI only.

Pre-build check (AGENTS §13.5): reuses ``check_registry_runtime_truth.parse_live_lanes`` / ``active_cron_lines``, the
``# PAUSED <date> <note> <line>`` crontab convention (``options_desk_accuracy``, ``pipeline_freshness_slo``), the
live-list backup naming of ``n8n_cutover_wave`` (``<file>.bak-<UTC>-<tag>``), ``release_train_stop.request_stop`` and
``release_control.ReleaseControl.request_pause``, ``bin/guard grant|revoke|id``, ``pipeline_manifest
.forbidden_command_tokens`` (display only). AUTHORITY: OPERATOR_ONLY. MBI_BEHAVIOR = 0.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:  # served release: scripts/ is on the path, the repo root may not be
    sys.path.append(str(REPO_ROOT))
CONFIG_REL = Path("config") / "ops_controls.json"
LANE_REGISTRY_REL = Path("config") / "lane_registry.json"
AUTHORITY_REL = Path("config") / "data_source_authority.json"
LIVE_LANES_KEY = "TRADEAI_N8N_RELAY_LIVE_LANES"

POLICY_ACTIVE = "ACTIVE"
POLICY_NOT_ACTIVE = "NOT_ACTIVE"
POLICY_UNREADABLE = "UNREADABLE"

SAFE = "safe"
RISKY = "risky"
EXEC_APPLIER = "applier"
EXEC_CC = "cc"

TERMINAL = frozenset({"APPLIED", "FAILED", "REFUSED", "EXPIRED", "CANCELLED"})

PAUSED_RE = re.compile(r"^#\s*PAUSED\s+(\d{4}-\d{2}-\d{2})\s+(\S+)\s+(.+)$")
CRON_LINE_RE = re.compile(r"^(@[a-z]+\s+\S|(\S+\s+){5}\S)")
LANE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,80}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
TIER_RE = re.compile(r"^[a-z][a-z0-9-]{1,40}$")
GRANT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
SETTING_KEY_RE = re.compile(r"^[a-z][a-z0-9_.]{1,95}$")
NAME_RE = re.compile(r"^[A-Za-z0-9 ._'()-]{1,64}$")
SECRETISH_RE = re.compile(r"(?i)\b([A-Z0-9_]*(TOKEN|SECRET|PASSWORD|PASSWD|KEY|BEARER|DSN|AUTH)[A-Z0-9_]*)=(\S+)")
DURATION_RE = re.compile(r"^(\d{1,6})([smhd]?)$")


class OpsError(Exception):
    """A refusal with a stable code and an HTTP status. Never a pass."""

    def __init__(self, code: str, detail: str = "", status: int = 400) -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail
        self.status = status


# ── config ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def load_config(path: Optional[Path] = None) -> dict:
    p = Path(path) if path else REPO_ROOT / CONFIG_REL
    doc = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or doc.get("schema") != "OpsControlsConfig@v1":
        raise OpsError("CONFIG_INVALID", str(p), 503)
    return doc


def expand(path: str | Path) -> Path:
    return Path(os.path.expanduser(os.path.expandvars(str(path))))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if dt else None


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def new_request_id() -> str:
    return "opsreq_" + secrets.token_hex(10)


# ── policy gate (AGENTS.md 19.0.0) ──────────────────────────────────────────────────────────────────────────────────


def _version_tuple(v: str) -> Optional[tuple[int, int, int]]:
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", v.strip())
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def policy_state(agents_path: Optional[Path] = None, *, required: str = "19.0.0",
                 anchor: str = "## 27.3 Safe direction one click; risky direction a passkey and a typed phrase",
                 or_later: bool = False) -> dict:
    """ACTIVE only when AGENTS.md's version-history row for ``required`` begins with ACTIVE and ``anchor`` is present.

    With ``or_later`` any ACTIVE version-history row at or above ``required`` satisfies the version part (the anchor
    is still required), so a gate keyed to the version that introduced a rule survives later versions.

    Read at call time (no cache), so ratification + promotion arms the surface and nothing else does. Fail closed: an
    unreadable file is UNREADABLE, which every caller treats as not active. There is no environment override.
    """
    p = Path(agents_path) if agents_path else REPO_ROOT / "AGENTS.md"
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        return {"state": POLICY_UNREADABLE, "required": required, "detail": f"{p}: {type(exc).__name__}"}
    if or_later:
        floor = _version_tuple(required)
        rows = re.findall(r"^\|\s*(\d+\.\d+\.\d+)\s*\|[^|]*\|\s*([^|]*)\|", text, re.M)
        hit = [v for v, s in rows if floor and (_version_tuple(v) or (0, 0, 0)) >= floor
               and s.strip().upper().startswith("ACTIVE")]
        if not hit:
            return {"state": POLICY_NOT_ACTIVE, "required": required,
                    "detail": f"no ACTIVE version-history row at or above {required}"}
        if anchor not in text:
            return {"state": POLICY_NOT_ACTIVE, "required": required, "detail": f"heading {anchor!r} absent"}
        return {"state": POLICY_ACTIVE, "required": required, "detail": f"{max(hit, key=_version_tuple)} ACTIVE"}
    row_re = re.compile(r"^\|\s*" + re.escape(required) + r"\s*\|[^|]*\|\s*([^|]*)\|", re.M)
    m = row_re.search(text)
    if not m:
        return {"state": POLICY_NOT_ACTIVE, "required": required, "detail": f"no {required} version-history row"}
    status = m.group(1).strip()
    if not status.upper().startswith("ACTIVE"):
        return {"state": POLICY_NOT_ACTIVE, "required": required, "detail": f"{required} row status {status!r}"}
    if anchor not in text:
        return {"state": POLICY_NOT_ACTIVE, "required": required, "detail": "§27.3 heading absent"}
    return {"state": POLICY_ACTIVE, "required": required, "detail": f"{required} ACTIVE"}


def require_policy_active(agents_path: Optional[Path] = None) -> dict:
    st = policy_state(agents_path)
    if st["state"] != POLICY_ACTIVE:
        raise OpsError("POLICY_NOT_ACTIVE", f"AGENTS.md {st['required']} is not ACTIVE ({st['detail']}); the Ops "
                                            f"Controls surface is inert until the operator ratifies it", 409)
    return st


# ── change kinds ────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class KindSpec:
    kind: str
    label: str
    direction: str
    executor: str
    tab: str
    supported: bool = True
    reason: Optional[str] = None


_NS_RELEASE = ("scope change and revoke are not built on this page yet (only resume and arm have the passkey proof, "
               "2026-10-22); each is its own reviewed PR. Host terminal: scripts/release_control_cli.py")
_UNDO_RELEASE = ("the way back is the other direction: STOP or pause (one click); resume and arm issue a new epoch, "
                 "and no earlier epoch is ever valid again")
_NS_CLEAR = ("the kill-switch clear path (scripts/brokers/kill_switches.py --disable) is broker-execution code; calling "
             "or testing it from the applier needs an execution-engineering grant (§0 rule 2, §27.4). Host terminal: "
             "scripts/brokers/kill_switches.py --disable <level> --confirm <phrase>")

KINDS: dict[str, KindSpec] = {k.kind: k for k in (
    KindSpec("release_train.stop", "Release train: STOP", SAFE, EXEC_CC, "jobs"),
    KindSpec("release_train.pause", "Release train: pause after the current train", SAFE, EXEC_CC, "jobs"),
    KindSpec("release_train.resume", "Release train: resume", RISKY, EXEC_APPLIER, "jobs"),
    KindSpec("release_train.arm", "Release train: arm", RISKY, EXEC_APPLIER, "jobs"),
    KindSpec("release_train.change_scope", "Release train: change scope", RISKY, EXEC_CC, "jobs", False, _NS_RELEASE),
    KindSpec("release_train.revoke", "Release train: revoke delegation", RISKY, EXEC_CC, "jobs", False, _NS_RELEASE),
    KindSpec("kill_switch.engage", "Kill switch: engage", SAFE, EXEC_APPLIER, "jobs"),
    KindSpec("kill_switch.clear", "Kill switch: clear", RISKY, EXEC_APPLIER, "jobs", False, _NS_CLEAR),
    KindSpec("crontab.pause", "Pause a cron line", RISKY, EXEC_APPLIER, "jobs"),
    KindSpec("crontab.resume", "Resume a paused cron line", RISKY, EXEC_APPLIER, "jobs"),
    KindSpec("n8n_live_list.add", "Add a lane to the n8n live list", RISKY, EXEC_APPLIER, "n8n"),
    KindSpec("n8n_live_list.remove", "Remove a lane from the n8n live list", RISKY, EXEC_APPLIER, "n8n"),
    KindSpec("setting.set", "Set an operator setting", RISKY, EXEC_APPLIER, "flags"),
    KindSpec("setting.unset", "Unset an operator setting (back to the repository default)", RISKY, EXEC_APPLIER,
             "flags"),
    KindSpec("grant.issue", "Issue a guard grant", RISKY, EXEC_APPLIER, "grants"),
    KindSpec("grant.revoke", "Revoke a guard grant", RISKY, EXEC_APPLIER, "grants"),
    KindSpec("passkey.register", "Add a passkey", RISKY, EXEC_CC, "passkeys"),
    KindSpec("passkey.revoke", "Revoke a passkey", RISKY, EXEC_CC, "passkeys"),
)}


def kind_spec(kind: str) -> KindSpec:
    spec = KINDS.get(str(kind or ""))
    if spec is None:
        raise OpsError("KIND_UNKNOWN", str(kind)[:80], 400)
    return spec


def kinds_view() -> list[dict]:
    return [{"kind": k.kind, "label": k.label, "direction": k.direction, "executor": k.executor, "tab": k.tab,
             "supported": k.supported, "reason": k.reason} for k in KINDS.values()]


def phrase_matches(typed: Any, phrase: Optional[str]) -> bool:
    """Server-side typed-phrase check: whitespace collapsed, otherwise exact (case-sensitive)."""
    if not phrase or not isinstance(typed, str):
        return False
    return " ".join(typed.split()) == " ".join(phrase.split())


def phrase_for(kind: str, params: Mapping[str, Any], today: str) -> Optional[str]:
    spec = kind_spec(kind)
    if spec.direction == SAFE:
        return None
    target = {
        "crontab.pause": lambda: params.get("lane_id") or str(params.get("line_sha256", ""))[:8],
        "crontab.resume": lambda: params.get("lane_id") or str(params.get("line_sha256", ""))[:8],
        "n8n_live_list.add": lambda: params["lane_id"],
        "n8n_live_list.remove": lambda: params["lane_id"],
        "setting.set": lambda: params["key"],
        "setting.unset": lambda: params["key"],
        "grant.issue": lambda: params["tier"],
        "grant.revoke": lambda: params["tier"],
        "passkey.register": lambda: params["name"],
        "passkey.revoke": lambda: params.get("name") or str(params.get("credential_id", ""))[:8],
    }.get(kind, lambda: kind)()
    verb = {
        "crontab.pause": "PAUSE CRON", "crontab.resume": "RESUME CRON", "n8n_live_list.add": "ADD LIVE",
        "n8n_live_list.remove": "REMOVE LIVE", "setting.set": "SET", "setting.unset": "UNSET",
        "grant.issue": "ISSUE GRANT", "grant.revoke": "REVOKE GRANT", "passkey.register": "ADD PASSKEY",
        "passkey.revoke": "REVOKE PASSKEY",
    }.get(kind, kind.upper())
    return f"{verb} {target} {today}"


# ── host adapters (the only I/O; tests inject fakes) ───────────────────────────────────────────────────────────────


Runner = Callable[[list[str], Optional[str]], tuple[int, str, str]]


def _run(argv: list[str], stdin: Optional[str] = None, timeout: int = 60) -> tuple[int, str, str]:
    p = subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=timeout, check=False)
    return p.returncode, p.stdout, p.stderr


@dataclass
class Hosts:
    """Everything a change kind reads or writes on the host. Defaults are the real host; tests pass fakes."""

    cfg: dict
    code_root: Path = REPO_ROOT
    runner: Runner = field(default=_run)
    clock: Callable[[], datetime] = field(default=utc_now)
    release_state_dir: Optional[Path] = None
    release_delegation_path: Optional[Path] = None   # None: release_delegation.DEFAULT_PATH (host, outside the repo)

    # crontab
    def crontab_read(self) -> str:
        rc, out, err = self.runner(["crontab", "-l"], None)
        if rc != 0:
            raise OpsError("CRONTAB_UNREADABLE", (err or f"rc {rc}").strip()[:200], 503)
        return out

    def crontab_write(self, text: str) -> None:
        rc, _out, err = self.runner(["crontab", "-"], text)
        if rc != 0:
            raise OpsError("CRONTAB_WRITE_FAILED", (err or f"rc {rc}").strip()[:200], 500)

    # n8n live list
    @property
    def live_list_path(self) -> Path:
        return expand(self.cfg["live_list"]["file"])

    def restart_units(self) -> list[dict]:
        out = []
        for unit in self.cfg["live_list"].get("restart_units") or []:
            rc, _o, err = self.runner(["systemctl", "--user", "restart", unit], None)
            rc2, o2, _e2 = self.runner(["systemctl", "--user", "is-active", unit], None)
            out.append({"unit": unit, "restart_rc": rc, "active": o2.strip() or None, "error": (err or "")[:200]})
        return out

    # guard
    @property
    def guard_bin(self) -> Path:
        return expand(self.cfg["guard"]["bin"])

    def guard(self, *args: str) -> tuple[int, str, str]:
        return self.runner([str(self.guard_bin), *args], None)

    def guard_tiers(self) -> list[str]:
        try:
            text = self.guard_bin.read_text(encoding="utf-8")
        except OSError as exc:
            raise OpsError("GUARD_UNREADABLE", type(exc).__name__, 503) from exc
        m = re.search(r'^ALL_TIERS="([^"]+)"', text, re.M)
        if not m:
            raise OpsError("GUARD_UNREADABLE", "ALL_TIERS not found", 503)
        return m.group(1).split()

    def guard_id(self, tier: str) -> Optional[str]:
        rc, out, _err = self.guard("id", tier)
        gid = out.strip()
        return gid if rc == 0 and GRANT_ID_RE.fullmatch(gid or "") else None

    # release train
    @property
    def release_dir(self) -> Path:
        return self.release_state_dir or expand(self.cfg["release_train"]["state_dir"])

    # kill switch (existing operator CLI; never modified here)
    def kill_switch(self, *args: str) -> tuple[int, str, str]:
        py = sys.executable or "python3"
        return self.runner([py, str(self.code_root / self.cfg["kill_switch"]["cli"]), *args], None)

    def lane_registry(self) -> dict:
        return json.loads((self.code_root / LANE_REGISTRY_REL).read_text(encoding="utf-8"))

    def backup_dir(self) -> Path:
        d = expand(self.cfg["applier"]["backup_dir"])
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
        return d


def write_private(path: Path, text: str) -> None:
    """Atomic 0600 write (tmp + rename in the same directory)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
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


# ── crontab helpers ─────────────────────────────────────────────────────────────────────────────────────────────────


def _is_active_cron(line: str) -> bool:
    s = line.strip()
    if not s or s.startswith("#"):
        return False
    head = s.split(None, 1)[0]
    if "=" in head and not head[0].isdigit() and head[0] not in "*@":
        return False
    return bool(CRON_LINE_RE.match(s))


def redact(line: str) -> str:
    return SECRETISH_RE.sub(lambda m: f"{m.group(1)}=***", line)


def broker_tokens(line: str) -> list[str]:
    try:
        from scripts.pipelines.pipeline_manifest import forbidden_command_tokens  # type: ignore

        return sorted(set(forbidden_command_tokens(line)))
    except Exception:  # noqa: BLE001 — display only; never a gate
        return []


def cron_schedule(line: str) -> str:
    s = line.strip()
    if s.startswith("@"):
        return s.split(None, 1)[0]
    return " ".join(s.split()[:5])


def _find_line(text: str, sha: str, *, paused: bool) -> tuple[list[str], int]:
    lines = text.split("\n")
    hits = []
    for i, ln in enumerate(lines):
        if sha256_text(ln) != sha:
            continue
        if paused and PAUSED_RE.match(ln.strip()):
            hits.append(i)
        elif not paused and _is_active_cron(ln):
            hits.append(i)
    if not hits:
        raise OpsError("LINE_NOT_FOUND", "no " + ("paused" if paused else "active") +
                       " crontab line has that exact text (sha256); re-read the page", 409)
    if len(hits) > 1:
        raise OpsError("LINE_AMBIGUOUS", f"{len(hits)} identical lines; edit at the host terminal", 409)
    return lines, hits[0]


# ── plans ───────────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass
class Plan:
    kind: str
    params: dict
    summary: str
    before: Any
    after: Any
    digest: str
    diff: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    undo: Optional[dict] = None          # {"kind": ..., "params": {...}} or None
    undo_reason: Optional[str] = None
    phrase: Optional[str] = None         # overrides phrase_for() when the target names its own (release epochs)
    payload: dict = field(default_factory=dict)  # private to apply(); never sent to the browser

    def public(self) -> dict:
        return {"summary": self.summary, "before": self.before, "after": self.after, "diff": self.diff,
                "warnings": self.warnings, "undo": self.undo, "undo_reason": self.undo_reason}


def _req_str(params: Mapping[str, Any], key: str, rx: re.Pattern, code: str = "PARAMS_INVALID") -> str:
    v = params.get(key)
    if not isinstance(v, str) or not rx.fullmatch(v):
        raise OpsError(code, f"{key} invalid", 400)
    return v


def _parse_duration(v: Any, max_s: int) -> int:
    m = DURATION_RE.fullmatch(str(v or "").strip())
    if not m:
        raise OpsError("PARAMS_INVALID", "for must look like 30m, 2h or 900s", 400)
    n = int(m.group(1)) * {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)]
    if n < 60 or n > max_s:
        raise OpsError("PARAMS_INVALID", f"for must be between 60s and {max_s}s", 400)
    return n


def catalog_entry(cfg: dict, key: str) -> dict:
    for row in cfg.get("settings_catalog") or []:
        if row.get("key") == key:
            return row
    raise OpsError("SETTING_UNKNOWN", f"{key} is not in config/ops_controls.json settings_catalog", 400)


def coerce_setting(entry: Mapping[str, Any], value: Any) -> Any:
    t = entry.get("type")
    try:
        if t == "bool":
            if not isinstance(value, bool):
                raise ValueError
            v: Any = value
        elif t == "int":
            if isinstance(value, bool):
                raise ValueError
            v = int(value)
            if float(v) != float(value):
                raise ValueError
        elif t == "float":
            if isinstance(value, bool):
                raise ValueError
            v = float(value)
        elif t == "enum":
            v = str(value)
            if v not in (entry.get("choices") or []):
                raise ValueError
        elif t == "string":
            v = str(value)
            if len(v) > 500:
                raise ValueError
        else:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise OpsError("SETTING_VALUE_INVALID", f"{entry.get('key')} expects {t}", 400) from exc
    if t in ("int", "float"):
        lo, hi = entry.get("min"), entry.get("max")
        if (lo is not None and v < lo) or (hi is not None and v > hi):
            raise OpsError("SETTING_VALUE_INVALID", f"{entry.get('key')} must be within [{lo}, {hi}]", 400)
    return v


def plan_change(kind: str, params: Mapping[str, Any], hosts: Hosts, store: Any, *, request_id: str,
                actor: str = "") -> Plan:
    """Validate ``params`` and compute the dry run. Read-only: never writes host state or the store."""
    spec = kind_spec(kind)
    if not spec.supported:
        raise OpsError("KIND_NOT_SUPPORTED", spec.reason or "", 409)
    if not isinstance(params, Mapping):
        raise OpsError("PARAMS_INVALID", "params must be an object", 400)
    p = dict(params)
    today = hosts.clock().astimezone(timezone.utc).strftime("%Y-%m-%d")

    if kind in ("crontab.pause", "crontab.resume"):
        sha = _req_str(p, "line_sha256", SHA_RE)
        lane = p.get("lane_id")
        if lane is not None and (not isinstance(lane, str) or not LANE_ID_RE.fullmatch(lane)):
            raise OpsError("PARAMS_INVALID", "lane_id invalid", 400)
        text = hosts.crontab_read()
        lines, i = _find_line(text, sha, paused=(kind == "crontab.resume"))
        old = lines[i]
        if kind == "crontab.pause":
            new = f"# PAUSED {today} ops-controls:{request_id} {old}"
            undo = {"kind": "crontab.resume", "params": {"line_sha256": sha256_text(new), "lane_id": lane}}
            cmd = old
            summary = f"comment out the cron line for {lane or sha[:8]} (exact text)"
        else:
            m = PAUSED_RE.match(old.strip())
            assert m is not None
            new = m.group(3)
            if not CRON_LINE_RE.match(new.strip()):
                raise OpsError("LINE_NOT_CRON", "the paused text is not a cron line; edit at the host terminal", 409)
            if any(ln == new for ln in lines):
                raise OpsError("LINE_DUPLICATE_ACTIVE", "that exact line is already active", 409)
            undo = {"kind": "crontab.pause", "params": {"line_sha256": sha256_text(new), "lane_id": lane}}
            cmd = new
            summary = f"uncomment the cron line for {lane or sha[:8]} (paused {m.group(1)}, note {m.group(2)})"
        warnings = []
        tokens = broker_tokens(cmd)
        if tokens:
            warnings.append(("resuming a broker-class job: " if kind == "crontab.resume" else
                             "pausing a broker-class job: ") + ", ".join(tokens))
        new_lines = list(lines)
        new_lines[i] = new
        return Plan(kind, {"line_sha256": sha, "lane_id": lane}, summary, redact(old), redact(new), sha256_text(text),
                    diff=[f"- {redact(old)}", f"+ {redact(new)}"], warnings=warnings, undo=undo,
                    payload={"before_text": text, "after_text": "\n".join(new_lines)})

    if kind in ("n8n_live_list.add", "n8n_live_list.remove"):
        lane = _req_str(p, "lane_id", LANE_ID_RE)
        path = hosts.live_list_path
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise OpsError("LIVE_LIST_UNREADABLE", f"{path}: {type(exc).__name__}", 503) from exc
        key_lines = [i for i, ln in enumerate(text.split("\n")) if ln.strip().startswith(LIVE_LANES_KEY + "=")]
        if len(key_lines) != 1:
            raise OpsError("LIVE_LIST_INVALID", f"expected exactly one {LIVE_LANES_KEY}= line, found "
                                                f"{len(key_lines)}; edit at the host terminal", 409)
        from scripts.check_registry_runtime_truth import parse_live_lanes  # reuse, never clone

        current = parse_live_lanes(text)
        rows = {r.get("lane_id"): r for r in (hosts.lane_registry().get("lanes") or [])}
        warnings = []
        if kind == "n8n_live_list.add":
            if lane not in rows:
                raise OpsError("LANE_UNKNOWN", f"{lane} is not in config/lane_registry.json", 400)
            if lane in current:
                raise OpsError("NO_CHANGE", f"{lane} is already on the live list", 409)
            if not rows[lane].get("dispatch"):
                warnings.append("the registry row has no dispatch block; the dispatcher will not fire it")
            new_list = current + [lane]
            undo = {"kind": "n8n_live_list.remove", "params": {"lane_id": lane}}
        else:
            if lane not in current:
                raise OpsError("NO_CHANGE", f"{lane} is not on the live list", 409)
            new_list = [x for x in current if x != lane]
            undo = {"kind": "n8n_live_list.add", "params": {"lane_id": lane}}
        lines = text.split("\n")
        lines[key_lines[0]] = f"{LIVE_LANES_KEY}={' '.join(new_list)}"
        units = hosts.cfg["live_list"].get("restart_units") or []
        warnings.append("restarts " + ", ".join(units) if units else "no unit restart configured")
        verb = "add" if kind.endswith("add") else "remove"
        return Plan(kind, {"lane_id": lane}, f"{verb} {lane} {'to' if verb == 'add' else 'from'} the relay live list "
                    f"({len(current)} → {len(new_list)} lanes)", current, new_list, sha256_text(text),
                    diff=[("+ " if verb == "add" else "- ") + lane], warnings=warnings, undo=undo,
                    payload={"before_text": text, "after_text": "\n".join(lines), "path": str(path)})

    if kind in ("setting.set", "setting.unset"):
        key = _req_str(p, "key", SETTING_KEY_RE)
        entry = catalog_entry(hosts.cfg, key)
        cur = store.setting_get(key)  # None or {"value", "active", ...}
        cur_active = bool(cur and cur.get("active"))
        cur_val = cur.get("value") if cur_active else None
        digest = sha256_text(canonical({"key": key, "active": cur_active, "value": cur_val}))
        warnings = [] if entry.get("wired") else [
            f"no consumer reads {key} from operator_settings yet (wired: false); the value is stored, not used"]
        if kind == "setting.set":
            val = coerce_setting(entry, p.get("value"))
            if cur_active and cur_val == val:
                raise OpsError("NO_CHANGE", f"{key} is already {val!r}", 409)
            undo = ({"kind": "setting.set", "params": {"key": key, "value": cur_val}} if cur_active
                    else {"kind": "setting.unset", "params": {"key": key}})
            return Plan(kind, {"key": key, "value": val}, f"set {key} = {val!r} (default {entry.get('default')!r})",
                        cur_val if cur_active else None, val, digest, diff=[f"- {cur_val!r}", f"+ {val!r}"],
                        warnings=warnings, undo=undo,
                        payload={"value": val, "active": True, "expect": {"active": cur_active, "value": cur_val}})
        if not cur_active:
            raise OpsError("NO_CHANGE", f"{key} is not set (the repository default applies)", 409)
        return Plan(kind, {"key": key}, f"unset {key} (back to the repository default {entry.get('default')!r})",
                    cur_val, None, digest, diff=[f"- {cur_val!r}", f"+ (default {entry.get('default')!r})"],
                    warnings=warnings, undo={"kind": "setting.set", "params": {"key": key, "value": cur_val}},
                    payload={"value": None, "active": False, "expect": {"active": True, "value": cur_val}})

    if kind == "grant.issue":
        tier = _req_str(p, "tier", TIER_RE)
        if tier not in hosts.guard_tiers():
            raise OpsError("TIER_UNKNOWN", f"{tier} is not a grantable guard tier", 400)
        secs = _parse_duration(p.get("for"), int(hosts.cfg["guard"].get("max_for_s", 21600)))
        try:
            uses = int(p.get("uses"))
        except (TypeError, ValueError) as exc:
            raise OpsError("PARAMS_INVALID", "uses must be an integer", 400) from exc
        if uses < 1 or uses > int(hosts.cfg["guard"].get("max_uses", 50)):
            raise OpsError("PARAMS_INVALID", "uses must be 1..max_uses (unlimited grants are host-terminal only)", 400)
        reason = str(p.get("reason") or "").strip()
        if len(reason) < 8 or len(reason) > 300 or any(ord(c) < 32 for c in reason):
            raise OpsError("PARAMS_INVALID", "reason must be 8-300 printable characters", 400)
        existing = hosts.guard_id(tier)
        if existing:
            raise OpsError("GRANT_EXISTS", f"an active {tier} grant exists ({existing[:8]}); revoke it first", 409)
        return Plan(kind, {"tier": tier, "for": f"{secs}s", "uses": uses, "reason": reason},
                    f"issue a {tier} grant for {secs // 60} min, {uses} uses", None,
                    {"tier": tier, "seconds": secs, "uses": uses}, sha256_text(canonical({"tier": tier, "id": None})),
                    diff=[f"+ {tier} ({secs // 60} min, {uses} uses): {reason}"],
                    warnings=["every command in this scope runs without prompting until it expires (bin/guard)"],
                    undo=None, undo_reason="filled in after apply (revoke the issued grant id)",
                    payload={"argv": ["grant", tier, "--for", f"{secs}s", "--uses", str(uses), "--reason",
                                      f"{reason} (ops-controls {request_id})", "--yes"]})

    if kind == "grant.revoke":
        tier = _req_str(p, "tier", TIER_RE)
        cur = hosts.guard_id(tier)
        if not p.get("grant_id") and isinstance(p.get("grant_id8"), str) and cur and cur.startswith(p["grant_id8"]):
            p["grant_id"] = cur  # the page may only know the 8-char prefix that `guard show` prints
        gid = _req_str(p, "grant_id", GRANT_ID_RE)
        if not cur:
            raise OpsError("NO_CHANGE", f"no active {tier} grant", 409)
        if cur != gid:
            raise OpsError("GRANT_MISMATCH", f"the active {tier} grant is {cur[:8]}, not {gid[:8]}", 409)
        return Plan(kind, {"tier": tier, "grant_id": gid}, f"revoke the {tier} grant {gid[:8]}", gid, None,
                    sha256_text(canonical({"tier": tier, "id": gid})), diff=[f"- {tier} {gid[:8]}"],
                    undo=None, undo_reason="a revoked grant cannot be restored; issue a new one",
                    payload={"argv": ["revoke", tier, "--grant-id", gid]})

    if kind in ("release_train.stop", "release_train.pause"):
        given = str(p.get("reason") or "").strip()
        if len(given) > 240 or any(ord(c) < 32 for c in given):
            raise OpsError("PARAMS_INVALID", "reason invalid", 400)
        reason = "Ops Controls (operator)" + (f": {given}" if given else "")
        what = "STOP: latch the release STOP and stop every capability" if kind.endswith("stop") else \
            "pause after the current train"
        return Plan(kind, {"reason": reason}, f"release train: {what}", None, None, "n/a",
                    undo=None, undo_reason=_NS_RELEASE)

    if kind in ("release_train.resume", "release_train.arm"):
        return _plan_release(kind, p, hosts)

    if kind == "kill_switch.engage":
        reason = str(p.get("reason") or "").strip() or "operator, Ops Controls"
        if len(reason) > 300 or any(ord(c) < 32 for c in reason):
            raise OpsError("PARAMS_INVALID", "reason invalid", 400)
        level = hosts.cfg["kill_switch"].get("level", "global")
        return Plan(kind, {"reason": reason}, f"engage the {level} trading kill switch (existing operator CLI)",
                    None, None, "n/a", undo=None, undo_reason=_NS_CLEAR,
                    payload={"argv": ["--enable", level, "--reason", f"{reason} (ops-controls {request_id})"]})

    if kind == "passkey.register":
        name = _req_str(p, "name", NAME_RE)
        return Plan(kind, {"name": name.strip()}, f"register a new passkey named {name!r}", None, name, "n/a",
                    undo=None, undo_reason="revoke the new passkey (passkey.revoke)")
    if kind == "passkey.revoke":
        if not p.get("credential_id") and isinstance(p.get("credential_id8"), str) and len(p["credential_id8"]) >= 8:
            hits = [c["credential_id"] for c in store.credentials_list()
                    if c["credential_id"].startswith(p["credential_id8"]) and not c.get("revoked_at")]
            if len(hits) == 1:
                p["credential_id"] = hits[0]
        cid = _req_str(p, "credential_id", re.compile(r"^[A-Za-z0-9_-]{8,1400}$"))
        cred = store.credential_get(cid)
        if not cred or cred.get("revoked_at"):
            raise OpsError("NO_CHANGE", "no such active passkey", 409)
        return Plan(kind, {"credential_id": cid, "name": cred.get("name")}, f"revoke passkey {cred.get('name')!r}",
                    cred.get("name"), None, "n/a", undo=None, undo_reason="register a new passkey instead")
    raise OpsError("KIND_NOT_SUPPORTED", kind, 409)


# ── apply (host applier only, plus the two CC-executed safe kinds) ─────────────────────────────────────────────────


def _backup(hosts: Hosts, name: str, text: str) -> str:
    stamp = hosts.clock().strftime("%Y%m%dT%H%M%SZ")
    path = hosts.backup_dir() / f"{stamp}-{name}"
    write_private(path, text)
    return str(path)


def apply_change(kind: str, params: Mapping[str, Any], expected_digest: Optional[str], hosts: Hosts, store: Any, *,
                 request_id: str, actor: str, approval: Optional[dict] = None,
                 hmac_key: Optional[bytes] = None) -> dict:
    """Re-plan, refuse if the target changed since the preview, back up, apply, verify. Returns the result record.

    Raises OpsError on refusal before any write; a failure after the write is returned with outcome FAILED and the
    backup reference (the operator restores from it; nothing auto-remediates, §0 rule 5). ``approval`` (the signed
    request row) and ``hmac_key`` are needed only by the release-train operator kinds, whose proof is that approval.
    """
    plan = plan_change(kind, params, hosts, store, request_id=request_id, actor=actor)
    if expected_digest and plan.digest != "n/a" and plan.digest != expected_digest:
        raise OpsError("STATE_CHANGED", "the target changed since the preview; preview again", 409)
    res: dict[str, Any] = {"kind": kind, "summary": plan.summary, "undo": plan.undo, "undo_reason": plan.undo_reason}

    if kind in ("crontab.pause", "crontab.resume"):
        res["backup_ref"] = _backup(hosts, f"crontab-{request_id}.txt", plan.payload["before_text"])
        hosts.crontab_write(plan.payload["after_text"])
        after = hosts.crontab_read()
        ok = after.rstrip("\n") == plan.payload["after_text"].rstrip("\n")
        res["verify"] = {"read_back_matches": ok}
        res["outcome"] = "APPLIED" if ok else "FAILED"
        return res

    if kind in ("n8n_live_list.add", "n8n_live_list.remove"):
        path = Path(plan.payload["path"])
        bak = path.with_name(f"{path.name}.bak-{hosts.clock().strftime('%Y%m%dT%H%M%SZ')}-ops-{request_id}")
        shutil.copy2(path, bak)
        os.chmod(bak, 0o600)
        res["backup_ref"] = str(bak)
        write_private(path, plan.payload["after_text"])
        ok = path.read_text(encoding="utf-8") == plan.payload["after_text"]
        units = hosts.restart_units()
        res["verify"] = {"read_back_matches": ok, "units": units}
        res["outcome"] = "APPLIED" if ok and all(u.get("active") == "active" for u in units) else "FAILED"
        return res

    if kind in ("setting.set", "setting.unset"):
        key = plan.params["key"]
        row = store.setting_apply(key, plan.payload["value"], plan.payload["active"], actor=actor,
                                  request_id=request_id, expect=plan.payload["expect"])
        cur = store.setting_get(key) or {}
        ok = bool(cur.get("active")) == plan.payload["active"] and (
            not plan.payload["active"] or cur.get("value") == plan.payload["value"])
        res["backup_ref"] = f"operator_settings_history#{row.get('seq')}"
        res["verify"] = {"read_back_matches": ok}
        res["outcome"] = "APPLIED" if ok else "FAILED"
        return res

    if kind in ("grant.issue", "grant.revoke"):
        tier = plan.params["tier"]
        ledger = expand(os.environ.get("GUARD_APPROVALS_DIR", "~/.cursor/approvals")) / "grants.json"
        try:
            res["backup_ref"] = _backup(hosts, f"guard-grants-{request_id}.json", ledger.read_text(encoding="utf-8"))
        except OSError:
            res["backup_ref"] = None
        rc, out, err = hosts.guard(*plan.payload["argv"])
        now_id = hosts.guard_id(tier)
        if kind == "grant.issue":
            ok = rc == 0 and bool(now_id)
            res["grant_id"] = now_id
            res["undo"] = {"kind": "grant.revoke", "params": {"tier": tier, "grant_id": now_id}} if ok else None
            res["undo_reason"] = None if ok else "issue failed"
        else:
            ok = rc == 0 and now_id != plan.params["grant_id"]
        res["verify"] = {"guard_rc": rc, "active_grant_id8": (now_id or "")[:8] or None,
                         "output": (out or err or "")[-300:]}
        res["outcome"] = "APPLIED" if ok else "FAILED"
        return res

    if kind == "kill_switch.engage":
        rc, out, err = hosts.kill_switch(*plan.payload["argv"])
        rc2, status, _e = hosts.kill_switch("--status")
        res["verify"] = {"enable_rc": rc, "status_rc": rc2, "status_tail": (status or "")[-600:],
                         "note": "status captured as evidence; its shape is owned by broker-execution code"}
        res["outcome"] = "APPLIED" if rc == 0 and rc2 == 0 else "FAILED"
        res["detail"] = (out or err or "")[-300:]
        return res

    if kind == "release_train.stop":
        from scripts.lib import release_train_stop as rts

        http, body = rts.request_stop(actor=actor, reason=plan.params["reason"], idempotency_key=request_id,
                                      csrf_ok=True, body={"ops_controls_request": request_id},
                                      root=hosts.release_state_dir)
        res["verify"] = {"http": http, "outcome": body.get("outcome")}
        res["outcome"] = "APPLIED" if http < 300 else "FAILED"
        res["detail"] = body.get("outcome") or body.get("error") or body.get("code")
        res["code"] = None if http < 300 else str(body.get("code") or body.get("error") or http)
        return res

    if kind in ("release_train.resume", "release_train.arm"):
        return _apply_release(kind, plan, hosts, request_id=request_id, actor=actor, approval=approval,
                              hmac_key=hmac_key, res=res)

    if kind == "release_train.pause":
        from scripts.lib import release_control as RC

        ctl = RC.ReleaseControl(hosts.release_dir)
        try:
            out = ctl.request_pause(RC.Actor("cc", actor or "ops-controls"), plan.params["reason"],
                                    idempotency_key=request_id)
        except RC.ControlRefused as exc:
            raise OpsError(getattr(exc, "code", "CONTROL_REFUSED"), str(exc)[:200], 409) from exc
        res["verify"] = {"mode": out.get("mode"), "outcome": out.get("outcome")}
        res["outcome"] = "APPLIED"
        return res

    raise OpsError("KIND_NOT_SUPPORTED", f"{kind} is not applied by this path", 409)


# ── release train: resume / arm with a passkey proof (AGENTS.md 19.0.0 §25.4, §27.3) ─────────────────────────────


def _release_view(hosts: Hosts):
    from scripts.lib import release_control as RC

    ctl = RC.ReleaseControl(hosts.release_dir)
    return RC, ctl, ctl.view()


def _release_digest(v: Any, delegation_digest: Optional[str] = None) -> str:
    return sha256_text(canonical({"mode": v.mode, "epoch": v.epoch, "version": v.version, "latch": v.latch_state,
                                  "delegation": delegation_digest}))


def _delegation(hosts: Hosts) -> Any:
    from scripts.lib import release_delegation as RD

    dv = RD.load(hosts.release_delegation_path)
    if not dv.authorized:
        raise OpsError(f"DELEGATION_{dv.code}", (dv.detail or "the standing release delegation is not authorized; "
                                                 "create or fix it at the host first")[:200], 409)
    return dv


def _plan_release(kind: str, p: Mapping[str, Any], hosts: Hosts) -> Plan:
    reason = " ".join(str(p.get("reason") or "").split())
    if len(reason) < 4 or len(reason) > 400 or any(ord(c) < 32 for c in reason):
        raise OpsError("PARAMS_INVALID", "reason must be 4-400 printable characters (it is recorded)", 400)
    RC, ctl, v = _release_view(hosts)
    command = kind.split(".", 1)[1]
    before = {"mode": v.mode, "epoch": v.epoch, "latch": v.latch_state,
              "stop_reason": (v.stop or {}).get("reason") if isinstance(v.stop, dict) else None}
    if kind == "release_train.resume":
        if v.mode in (RC.UNARMED, RC.CORRUPT, RC.REVOKED):
            raise OpsError("RESUME_NOT_APPLICABLE", f"release train is {v.mode}: arm it instead", 409)
        if v.mode in (RC.STOP_REQUESTED, RC.STOP_ACKNOWLEDGED, RC.SETTLING):
            raise OpsError("STOP_NOT_SETTLED", f"{v.mode}: the controller has not reached stopped; wait", 409)
        if v.mode == RC.RUNNING and v.latch_state == RC.LATCH_ABSENT:
            raise OpsError("NO_CHANGE", "the release train is running; nothing to resume", 409)
        dd = None
        summary = (f"resume the release train: {v.mode} → RUNNING, epoch {v.epoch} → {int(v.epoch or 0) + 1}"
                   + (", STOP latch archived by rename" if v.latch_state != RC.LATCH_ABSENT else ""))
        warnings = ["every capability issued before the stop stays invalid; the train waits for its next window"]
    else:
        if v.mode not in (RC.UNARMED, RC.REVOKED):
            raise OpsError("ALREADY_ARMED", f"release train is {v.mode}", 409)
        if v.latch_state != RC.LATCH_ABSENT:
            raise OpsError("STOP_LATCH_PRESENT", "a STOP latch is present; resume clears it", 409)
        dd = _delegation(hosts).digest
        summary = (f"arm the release train under delegation {str(dd)[:12]}: {v.mode} → RUNNING, epoch "
                   f"{int(v.epoch or 0)} → {int(v.epoch or 0) + 1}")
        warnings = ["the scheduled train may merge and release under the standing delegation once armed"]
    after = {"mode": RC.RUNNING, "epoch": int(v.epoch or 0) + 1, "latch": RC.LATCH_ABSENT}
    return Plan(kind, {"reason": reason}, summary, before, after, _release_digest(v, dd),
                diff=[f"- mode {v.mode} epoch {v.epoch}", f"+ mode RUNNING epoch {after['epoch']}"],
                warnings=warnings, undo=None, undo_reason=_UNDO_RELEASE, phrase=ctl.expected_phrase(command),
                payload={"command": command, "delegation_digest": dd})


class ApprovalPasskeyHook:
    """Vouches for a ``release_control.PasskeyProof`` only when it matches the one approval being applied.

    The approval must carry a valid HMAC signature (the key is a 0600 file only the Command Center and the applier
    read), be for this exact command, have been stepped up with a FRESH passkey assertion (factor ``passkey``: a
    sudo-window step-up or TOTP is refused), name the same credential and request, and carry the phrase the library
    expects now (it names the next epoch, so a stale approval cannot resume a later stop)."""

    def __init__(self, approval: Mapping[str, Any], hmac_key: Optional[bytes], kind: str) -> None:
        self.approval = dict(approval)
        self.hmac_key = hmac_key
        self.kind = kind

    def verify(self, proof: Any, *, command: str, expected_phrase: str) -> bool:
        from scripts.lib import ops_controls_auth as A

        a = self.approval
        return bool(
            A.verify_approval(self.hmac_key, a)
            and a.get("kind") == self.kind == f"release_train.{command}"
            and a.get("direction") == RISKY and a.get("executor") == EXEC_APPLIER
            and a.get("stepup_factor") == "passkey" and a.get("stepup_credential_id")
            and proof.credential_id == a.get("stepup_credential_id")
            and proof.request_id == a.get("request_id")
            and phrase_matches(proof.confirmation, a.get("phrase"))
            and proof.confirmation == expected_phrase)


def _apply_release(kind: str, plan: Plan, hosts: Hosts, *, request_id: str, actor: str, approval: Optional[dict],
                   hmac_key: Optional[bytes], res: dict) -> dict:
    from scripts.lib import release_control as RC

    if not approval or approval.get("request_id") != request_id:
        raise OpsError("PROOF_MISSING", "release-train operator kinds are applied only from a signed approval", 409)
    hook = ApprovalPasskeyHook(approval, hmac_key, kind)
    ctl = RC.ReleaseControl(hosts.release_dir, passkey_hook=hook)
    who = RC.Actor("passkey", actor or str(approval.get("actor") or ""))
    proof = RC.PasskeyProof(request_id=request_id, credential_id=str(approval.get("stepup_credential_id") or ""),
                            approved_at=str(approval.get("approved_at") or ""),
                            confirmation=" ".join(str(approval.get("phrase") or "").split()))
    reason = f"{plan.params['reason']} (ops-controls {request_id})"
    try:
        if kind == "release_train.resume":
            v = ctl.view()
            readiness = {"checked_at": RC.utc_iso(ctl.clock()), "source": "ops_controls_applier",
                         "shown": {"mode": v.mode, "epoch": v.epoch, "latch": v.latch_state, "stop": v.stop}}
            out = ctl.resume(who, proof, reason=reason, readiness=readiness)
        else:
            dd = _delegation(hosts).digest
            if dd != plan.payload.get("delegation_digest"):
                raise OpsError("STATE_CHANGED", "the delegation changed since the preview; preview again", 409)
            out = ctl.arm(who, proof, policy_digest=dd, reason=reason)
    except RC.ControlRefused as exc:
        raise OpsError(exc.code, str(exc.detail)[:200], 409) from exc
    after = ctl.view()
    ok = after.mode == RC.RUNNING and after.epoch == out.get("epoch")
    res["verify"] = {"mode": after.mode, "epoch": after.epoch, "outcome": out.get("outcome"),
                     "latch_archived": out.get("latch_archived")}
    res["backup_ref"] = out.get("latch_archived")
    res["outcome"] = "APPLIED" if ok else "FAILED"
    return res
