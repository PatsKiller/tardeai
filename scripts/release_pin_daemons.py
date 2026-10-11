#!/usr/bin/env python3
"""Keep every release-pinned user daemon on the release portfolio-server serves.

    python3 scripts/release_pin_daemons.py plan     --target <release-dir>             # DRY RUN, writes nothing
    python3 scripts/release_pin_daemons.py apply    --target <release-dir> [--deploy-restarted "u1 u2"]
    python3 scripts/release_pin_daemons.py rollback --target <release-dir> --from <release-dir>
    python3 scripts/release_pin_daemons.py restore  --receipt <apply-receipt.json>
    python3 scripts/release_pin_daemons.py tripwire

Why (2026-10-10, packets/unit-code-roots): chatgpt-oauth-proxy, grok-oauth-proxy, heartbeat-receiver and
tradeai-active-trader-motion each carried a one-off exact-SHA drop-in written 2026-10-06
(``20-exact-sha-release.conf`` / ``10-user-exact-sha.conf``, ``WorkingDirectory=<release dir>``). The deploy
rewrote that drop-in only for portfolio-server, so the four ran a032116e7 for four days while CURRENT moved.

What it does, per user unit with a ``<unit>.d/`` directory under the systemd user dir:

* Computes the EFFECTIVE ``WorkingDirectory``, ``ExecStart*`` and ``Environment`` (fragment, then drop-ins in
  filename order: last WorkingDirectory wins, an empty ``ExecStart=`` resets the list).
* A reference to ``<releases>/portfolio-server/<name>`` with ``<name>`` != CURRENT is a PIN. A pin to a release
  other than ``--target`` is STALE.
* STALE and broker-adjacent (code path matches the AGENTS.md section 0 rule 2 broker execution file set in
  ``config/agents_guard_hook_rules.json``, or the unit is named in ``config/release_pin_daemons.json``):
  listed as ``pinned-broker-adjacent: operator action``. Never modified.
* STALE otherwise: the effective pinned directives are rewritten to ``--target`` in ONE managed drop-in
  (``90-release-pin.conf``). One-off drop-ins that hold nothing but pins are ARCHIVED (moved under
  ``<user dir>/.release-pin-archive/<ts>/``, where systemd never reads, next to a TRIPWIRE note). A drop-in
  that also carries other directives is kept; the managed file overrides it. A stale pin the managed file
  cannot override (a non-archivable drop-in sorting after it) is ``blocked: operator action``.
* Restart: a unit the deploy already restarts (``--deploy-restarted``) or one on ``restart_allowlist`` is
  restarted; every other running unit is reported ``restart pending``. ``daemon-reload`` runs once.

Every apply writes a receipt (``ReleasePinReceipt@v1``) naming each archived file with its sha256; ``restore``
moves them back (archiving the managed file it replaces), which is what ``rollback`` does when the promote
being undone is the one recorded in ``last_apply.json``. Nothing is ever deleted (AGENTS.md section 0 rule 6).

Refuses apply/restore against the real ``~/.config/systemd/user`` when ``TRADE_AI_CI=1`` (agents run with it
set; the operator's deploy does not). With a non-default unit dir (tests) the real ``systemctl`` is never
called. Exit: 0 ok (broker-adjacent listings included); 3 stale pins remain that need an operator (blocked);
2 refused or misconfigured.

AUTHORITY: READ_ONLY_ADVISORY. No broker. Writes only systemd user drop-ins + its own receipts.
"""
from __future__ import annotations

NO_CONSUMER_REASON = (
    "deploy step: scripts/cio_phase2_exact_main_deploy.sh (promote, rollback, pins) invokes it as a CLI; "
    "ReleasePinReceipt@v1 is read back only by its own restore/rollback and by the operator."
)

import argparse
import fnmatch
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_PLAN = "ReleasePinPlan@v1"
SCHEMA_RECEIPT = "ReleasePinReceipt@v1"
REPO = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO / "config" / "release_pin_daemons.json"
REAL_UNIT_DIR = Path.home() / ".config" / "systemd" / "user"
EXIT_OK, EXIT_REFUSED, EXIT_BLOCKED = 0, 2, 3

PIN_KEYS = ("WorkingDirectory", "ExecStart", "ExecStartPre", "ExecStartPost", "Environment")
EXEC_KEYS = ("ExecStart", "ExecStartPre", "ExecStartPost")
NOT_A_RELEASE = {"CURRENT", "EXPECTED_RELEASE", "ACTIVE_RELEASE"}

TRIPWIRE_TEXT = (
    "TRIPWIRE (AGENTS.md section 0 rule 6). These systemd drop-ins were ARCHIVED, not deleted, by\n"
    "scripts/release_pin_daemons.py during a portfolio-server promote/rollback. systemd does not read this\n"
    "directory. Nothing may read, include or copy a file from here back into a unit: "
    "`release_pin_daemons.py tripwire` fails if any live unit file references this path.\n"
    "To undo: release_pin_daemons.py restore --receipt <the apply receipt that archived them>.\n"
)


class Refused(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# --------------------------------------------------------------------------- config


@dataclass
class Config:
    managed_name: str = "90-release-pin.conf"
    archive_dirname: str = ".release-pin-archive"
    exclude_units: tuple[str, ...] = ("portfolio-server.service",)
    restart_allowlist: tuple[str, ...] = ()
    broker_globs: tuple[str, ...] = ()
    broker_units: tuple[str, ...] = ()
    broker_markers: tuple[str, ...] = ()


def load_config(path: Path = DEFAULT_CONFIG, repo: Path = REPO) -> Config:
    """Fail closed: no broker file set means no apply (a unit could not be classified)."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Refused(f"config unreadable: {path}: {exc}") from exc
    rules_path = repo / raw.get("broker_rules_path", "config/agents_guard_hook_rules.json")
    rule_id = raw.get("broker_rule_id", "broker.execution_code_edit")
    try:
        rules = json.loads(rules_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Refused(f"broker rules unreadable: {rules_path}: {exc}") from exc
    globs: list[str] = []
    for rule in rules.get("rules", []):
        if rule.get("id") == rule_id:
            globs = list(rule.get("path_globs") or [])
    if not globs:
        raise Refused(f"broker rule {rule_id!r} has no path_globs in {rules_path} — refusing to classify units")
    return Config(
        managed_name=raw.get("managed_dropin_name", "90-release-pin.conf"),
        archive_dirname=raw.get("archive_dirname", ".release-pin-archive"),
        exclude_units=tuple(raw.get("exclude_units", ["portfolio-server.service"])),
        restart_allowlist=tuple(raw.get("restart_allowlist", [])),
        broker_globs=tuple(globs),
        broker_units=tuple(raw.get("broker_adjacent_units", [])),
        broker_markers=tuple(raw.get("broker_adjacent_name_markers", [])),
    )


# --------------------------------------------------------------------------- parsing


@dataclass(eq=False)
class Directive:
    key: str
    value: str
    source: Path


def parse_service_directives(path: Path) -> tuple[list[Directive], bool]:
    """[Service] directives of one unit file (continuations joined, comments dropped).

    Returns (directives, only_service_section). The flag is False when the file has any other section.
    """
    out: list[Directive] = []
    section = ""
    only_service = True
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out, False
    logical: list[str] = []
    buf = ""
    for line in text.splitlines():
        stripped = line.strip()
        if not buf and (not stripped or stripped[0] in "#;"):
            continue
        if stripped.endswith("\\"):
            buf += stripped[:-1] + " "
            continue
        logical.append(buf + stripped)
        buf = ""
    if buf:
        logical.append(buf)
    for line in logical:
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            if section != "Service":
                only_service = False
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if section == "Service":
            out.append(Directive(key, value.strip(), path))
        else:
            only_service = False
    return out, only_service


def release_ref_regex(releases_base: Path) -> re.Pattern[str]:
    home = str(Path.home())
    base = str(releases_base)
    alts = [re.escape(base)]
    if base.startswith(home + "/"):
        alts.append(re.escape("%h" + base[len(home):]))
    return re.compile(r"(?P<base>" + "|".join(alts) + r")/(?P<name>[A-Za-z0-9][A-Za-z0-9._+-]*)")


def pinned_names(value: str, rx: re.Pattern[str]) -> set[str]:
    return {m.group("name") for m in rx.finditer(value) if m.group("name") not in NOT_A_RELEASE}


def rewrite_value(value: str, rx: re.Pattern[str], target_name: str) -> str:
    def sub(m: re.Match[str]) -> str:
        if m.group("name") in NOT_A_RELEASE:
            return m.group(0)
        return f"{m.group('base')}/{target_name}"

    return rx.sub(sub, value)


# --------------------------------------------------------------------------- unit model


@dataclass
class UnitPlan:
    unit: str
    status: str  # current | stale | rewrite | broker_adjacent | blocked | shadowed | no_pin
    pinned: list[str] = field(default_factory=list)
    effective: dict[str, Any] = field(default_factory=dict)
    managed_content: str | None = None
    archive: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    reason: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "unit": self.unit,
            "status": self.status,
            "pinned_releases": sorted(self.pinned),
            "effective": self.effective,
            "archive": self.archive,
            "kept_overridden": self.kept,
            "managed_dropin": None if self.managed_content is None else "written",
            "reason": self.reason,
        }


def _effective(directives: list[Directive]) -> dict[str, Any]:
    eff: dict[str, Any] = {"WorkingDirectory": None, "Environment": []}
    env: dict[str, Directive] = {}
    for k in EXEC_KEYS:
        eff[k] = []
    for d in directives:
        if d.key == "WorkingDirectory":
            eff["WorkingDirectory"] = d
        elif d.key in EXEC_KEYS:
            if d.value == "":
                eff[d.key] = []
            else:
                eff[d.key].append(d)
        elif d.key == "Environment":
            # Per-variable, last assignment wins (Environment= is additive across files).
            if d.value == "":
                env = {}
            for assign in _tokens(d.value):
                var = assign.split("=", 1)[0]
                if var:
                    env[var] = Directive("Environment", assign, d.source)
    eff["Environment"] = list(env.values())
    return eff


def _effective_pinned(eff: dict[str, Any], rx: re.Pattern[str]) -> tuple[set[str], list[Directive]]:
    names: set[str] = set()
    sources: list[Directive] = []
    wd = eff["WorkingDirectory"]
    if wd is not None and pinned_names(wd.value, rx):
        names |= pinned_names(wd.value, rx)
        sources.append(wd)
    for k in EXEC_KEYS + ("Environment",):
        for d in eff[k]:
            n = pinned_names(d.value, rx)
            if n:
                names |= n
                sources.append(d)
    return names, sources


def _tokens(value: str) -> list[str]:
    try:
        return shlex.split(value)
    except ValueError:
        return value.split()


def broker_adjacent(unit: str, directives: list[Directive], cfg: Config) -> str:
    """Non-empty reason when the unit touches the broker execution file set (conservative)."""
    if unit in cfg.broker_units:
        return f"named in broker_adjacent_units ({unit})"
    low = unit.lower()
    for marker in cfg.broker_markers:
        if marker.lower() in low:
            return f"unit name contains broker marker {marker!r}"
    home = str(Path.home())
    pats = [g.replace("**/", "*/").replace("/**", "/*") for g in cfg.broker_globs]
    for d in directives:
        for tok in _tokens(d.value):
            tok = tok.lstrip("-@+!:").replace("%h", home)
            if "/" not in tok:
                continue
            tok = tok.split("=", 1)[-1] if "=" in tok and d.key == "Environment" else tok
            cands = (tok, tok.rstrip("/") + "/", "/" + tok.lstrip("/"))
            for pat, glob in zip(pats, cfg.broker_globs):
                if any(fnmatch.fnmatch(c, pat) for c in cands):
                    return f"{d.source.name}: {d.key} path {tok} matches broker execution glob {glob}"
    return ""


def _archivable(path: Path, rx: re.Pattern[str], cfg: Config) -> bool:
    """A drop-in is pin-only (safe to archive) when every [Service] directive is a pin or an Exec reset."""
    if path.name == cfg.managed_name:
        return True
    directives, only_service = parse_service_directives(path)
    if not only_service or not directives:
        return False
    for d in directives:
        if d.key not in PIN_KEYS:
            return False
        if d.value == "" and d.key in EXEC_KEYS:
            continue
        if d.key == "WorkingDirectory" or d.key in EXEC_KEYS:
            if not pinned_names(d.value, rx):
                return False
        elif d.key == "Environment":
            if not pinned_names(d.value, rx):
                return False
    return True


def _render_managed(unit: str, target: Path, sources: list[Directive], eff: dict[str, Any],
                    rx: re.Pattern[str], archived: list[str]) -> str:
    tname = target.name
    lines = [
        "# MANAGED by scripts/release_pin_daemons.py (cio_phase2_exact_main_deploy.sh promote/rollback).",
        f"# Pins {unit} to the release portfolio-server serves: {tname}.",
        "# Rewritten on every promote and rollback; hand edits are archived on the next run.",
    ]
    if archived:
        lines.append("# Replaced pin-only drop-ins (archived, never deleted): " + ", ".join(archived))
    lines.append("[Service]")
    wd = eff["WorkingDirectory"]
    if wd is not None and wd in sources:
        lines.append(f"WorkingDirectory={rewrite_value(wd.value, rx, tname)}")
    for k in EXEC_KEYS:
        if any(d in sources for d in eff[k]):
            lines.append(f"{k}=")
            for d in eff[k]:
                lines.append(f"{k}={rewrite_value(d.value, rx, tname)}")
    for d in eff["Environment"]:
        if d in sources:
            assign = rewrite_value(d.value, rx, tname)
            lines.append(f'Environment="{assign}"' if any(c.isspace() for c in assign) else f"Environment={assign}")
    return "\n".join(lines) + "\n"


def _unit_dirs(unit_dir: Path) -> list[tuple[str, Path]]:
    out = []
    if not unit_dir.is_dir():
        return out
    for d in sorted(unit_dir.iterdir()):
        if d.is_dir() and d.name.endswith(".service.d"):
            out.append((d.name[:-2], d))
    return out


def plan_unit(unit: str, ddir: Path, unit_dir: Path, target: Path, rx: re.Pattern[str], cfg: Config) -> UnitPlan:
    frag = unit_dir / unit
    files = [frag] if frag.is_file() else []
    dropins = sorted(p for p in ddir.glob("*.conf") if p.is_file())
    files += dropins
    directives: list[Directive] = []
    for f in files:
        directives += parse_service_directives(f)[0]
    eff = _effective(directives)
    names, sources = _effective_pinned(eff, rx)
    eff_view = {
        "WorkingDirectory": eff["WorkingDirectory"].value if eff["WorkingDirectory"] else None,
        "ExecStart": [d.value for d in eff["ExecStart"]],
    }
    any_pin_files = [p for p in dropins if any(pinned_names(d.value, rx) for d in parse_service_directives(p)[0]
                                               if d.key in PIN_KEYS)]
    stale_names = {n for n in names if n != target.name}
    if not names:
        if any_pin_files:
            return UnitPlan(unit, "shadowed", pinned=[], effective=eff_view,
                            kept=[p.name for p in any_pin_files],
                            reason="pin drop-ins exist but a later drop-in overrides every pinned directive")
        return UnitPlan(unit, "no_pin", effective=eff_view)
    if not stale_names:
        return UnitPlan(unit, "current", pinned=sorted(names), effective=eff_view)
    why = broker_adjacent(unit, directives, cfg)
    if why:
        return UnitPlan(unit, "broker_adjacent", pinned=sorted(names), effective=eff_view,
                        reason=f"pinned-broker-adjacent: operator action ({why})")
    source_files = sorted({d.source for d in sources if d.source != frag})
    archive = [p for p in any_pin_files if _archivable(p, rx, cfg)]
    managed_path = ddir / cfg.managed_name
    if managed_path.is_file() and managed_path not in archive:
        archive.append(managed_path)
    kept = [p for p in source_files if p not in archive]
    blocked = [p for p in kept if p.name > cfg.managed_name]
    if blocked:
        return UnitPlan(unit, "blocked", pinned=sorted(names), effective=eff_view,
                        kept=[p.name for p in kept],
                        reason="stale pin in a drop-in that sorts after "
                               f"{cfg.managed_name} and carries other directives: "
                               + ", ".join(p.name for p in blocked) + " — operator action")
    content = _render_managed(unit, target, sources, eff, rx, [p.name for p in archive if p != managed_path])
    return UnitPlan(unit, "rewrite", pinned=sorted(names), effective=eff_view, managed_content=content,
                    archive=[p.name for p in archive if not (p == managed_path and _read_text(p) == content)],
                    kept=[p.name for p in kept])


def _read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


def build_plan(unit_dir: Path, target: Path, releases_base: Path, cfg: Config) -> list[UnitPlan]:
    if target.parent.resolve() != releases_base.resolve():
        raise Refused(f"target {target} is not a release under {releases_base}")
    if target.name in NOT_A_RELEASE:
        raise Refused(f"target must be a concrete release dir, not {target.name}")
    rx = release_ref_regex(releases_base)
    plans = []
    for unit, ddir in _unit_dirs(unit_dir):
        if unit in cfg.exclude_units:
            continue
        p = plan_unit(unit, ddir, unit_dir, target, rx, cfg)
        if p.status != "no_pin":
            plans.append(p)
    return plans


# --------------------------------------------------------------------------- systemctl


class Systemctl:
    def __init__(self, cmd: str | None, unit_dir: Path):
        self.cmd = cmd or os.environ.get("TRADEAI_SYSTEMCTL") or "systemctl"
        # A fake unit tree must never drive the real user manager.
        self.enabled = not (unit_dir.resolve() != REAL_UNIT_DIR.resolve() and self.cmd == "systemctl")
        self.calls: list[list[str]] = []

    def run(self, *args: str) -> int:
        argv = [*shlex.split(self.cmd), "--user", *args]
        self.calls.append(argv)
        if not self.enabled:
            return 0
        try:
            return subprocess.run(argv, capture_output=True, timeout=120, check=False).returncode
        except (OSError, subprocess.TimeoutExpired):
            return 1

    def is_active(self, unit: str) -> bool:
        return self.enabled and self.run("is-active", "--quiet", unit) == 0


# --------------------------------------------------------------------------- apply / restore


def _guard_live(unit_dir: Path) -> None:
    if os.environ.get("TRADE_AI_CI") == "1" and unit_dir.resolve() == REAL_UNIT_DIR.resolve():
        raise Refused("TRADE_AI_CI=1: refusing to write the real systemd user dir (the operator's deploy applies)")


def _archive_root(unit_dir: Path, cfg: Config, ts: str) -> Path:
    root = unit_dir / cfg.archive_dirname / ts
    root.mkdir(parents=True, exist_ok=True)
    (root / "TRIPWIRE.README").write_text(TRIPWIRE_TEXT, encoding="utf-8")
    return root


def _move_to_archive(src: Path, root: Path, unit_d: str) -> dict[str, str]:
    dest = root / unit_d / src.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    digest = _sha(src)
    shutil.move(str(src), str(dest))
    return {"from": str(src), "to": str(dest), "sha256": digest}


def apply_plan(plans: list[UnitPlan], *, unit_dir: Path, target: Path, cfg: Config, receipt_dir: Path,
               systemctl: Systemctl, deploy_restarted: set[str], mode: str = "apply",
               from_release: str = "") -> dict[str, Any]:
    _guard_live(unit_dir)
    ts = _now()
    root: Path | None = None
    units_out = []
    changed = False
    for p in plans:
        row = p.to_json()
        row["archived"] = []
        row["managed_path"] = None
        if p.status == "rewrite":
            ddir = unit_dir / f"{p.unit}.d"
            managed = ddir / cfg.managed_name
            if managed.is_file() and _read_text(managed) == p.managed_content and not [
                a for a in p.archive if a != cfg.managed_name
            ]:
                row["status"] = "current"
            else:
                for name in p.archive:
                    src = ddir / name
                    if src.is_file():
                        root = root or _archive_root(unit_dir, cfg, ts)
                        row["archived"].append(_move_to_archive(src, root, ddir.name))
                managed.write_text(p.managed_content or "", encoding="utf-8")
                os.chmod(managed, 0o600)
                row["managed_path"] = str(managed)
                row["managed_sha256"] = _sha(managed)
                changed = True
        units_out.append(row)
    reload_rc = systemctl.run("daemon-reload") if changed else None
    for row in units_out:
        if row["status"] != "rewrite" or not row["managed_path"]:
            continue
        u = row["unit"]
        if u in deploy_restarted:
            row["restart"] = "restarted by deploy (bound unit)"
        elif u in cfg.restart_allowlist:
            rc = systemctl.run("restart", u)
            row["restart"] = "restarted" if rc == 0 else f"restart FAILED rc={rc}"
        elif systemctl.is_active(u):
            row["restart"] = "restart pending"
        else:
            row["restart"] = "restart pending (not running or not checked: applies on next start)"
    receipt = {
        "schema": SCHEMA_RECEIPT,
        "mode": mode,
        "at": datetime.now(timezone.utc).isoformat(),
        "target_release": str(target),
        "from_release": from_release,
        "unit_dir": str(unit_dir),
        "archive_root": str(root) if root else None,
        "daemon_reload_rc": reload_rc,
        "systemctl_live": systemctl.enabled,
        "units": units_out,
        "summary": _summary(units_out),
        "authority": "READ_ONLY_ADVISORY",
    }
    receipt_dir.mkdir(parents=True, exist_ok=True)
    path = receipt_dir / f"{mode}-{ts}.json"
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    receipt["receipt_path"] = str(path)
    if changed:
        (receipt_dir / "last_apply.json").write_text(
            json.dumps({"receipt": str(path), "target_release": str(target), "at": receipt["at"]}, indent=2) + "\n",
            encoding="utf-8")
    return receipt


def _summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        out[r["status"]] = out.get(r["status"], 0) + 1
    return out


def restore(receipt_path: Path, *, cfg: Config, receipt_dir: Path, systemctl: Systemctl) -> dict[str, Any]:
    rec = json.loads(receipt_path.read_text(encoding="utf-8"))
    unit_dir = Path(rec["unit_dir"])
    _guard_live(unit_dir)
    ts = _now()
    root: Path | None = None
    rows = []
    changed = False
    for u in rec.get("units", []):
        if not u.get("managed_path"):
            continue
        row: dict[str, Any] = {"unit": u["unit"], "restored": [], "archived": [], "status": "restored"}
        managed = Path(u["managed_path"])
        if managed.is_file():
            if u.get("managed_sha256") and _sha(managed) != u["managed_sha256"]:
                row["status"] = "drift: managed drop-in changed since apply — not restored (operator action)"
                rows.append(row)
                continue
            root = root or _archive_root(unit_dir, cfg, ts)
            row["archived"].append(_move_to_archive(managed, root, managed.parent.name))
        for a in u.get("archived", []):
            src, dest = Path(a["to"]), Path(a["from"])
            if dest.exists():
                row["status"] = f"conflict: {dest} exists — left archived copy at {src}"
                continue
            if not src.is_file() or _sha(src) != a["sha256"]:
                row["status"] = f"drift: archived copy {src} missing or changed"
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
            row["restored"].append(str(dest))
        changed = True
        rows.append(row)
    rc = systemctl.run("daemon-reload") if changed else None
    out = {
        "schema": SCHEMA_RECEIPT,
        "mode": "restore",
        "at": datetime.now(timezone.utc).isoformat(),
        "restored_from_receipt": str(receipt_path),
        "unit_dir": str(unit_dir),
        "archive_root": str(root) if root else None,
        "daemon_reload_rc": rc,
        "units": rows,
        "authority": "READ_ONLY_ADVISORY",
    }
    receipt_dir.mkdir(parents=True, exist_ok=True)
    path = receipt_dir / f"restore-{ts}.json"
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    out["receipt_path"] = str(path)
    last = receipt_dir / "last_apply.json"
    if last.is_file():
        try:
            if json.loads(last.read_text(encoding="utf-8")).get("receipt") == str(receipt_path):
                # Rename, never delete: the pointer would otherwise invite a second restore.
                last.rename(receipt_dir / f"last_apply.restored-{ts}.json")
        except ValueError:
            pass
    return out


def tripwire(unit_dir: Path, cfg: Config) -> list[str]:
    """Live unit files that reference the archive directory (AGENTS.md section 0 rule 6)."""
    hits = []
    needle = cfg.archive_dirname
    if not unit_dir.is_dir():
        return hits
    for p in sorted(unit_dir.rglob("*")):
        if cfg.archive_dirname in p.parts or not p.is_file():
            continue
        if not (p.suffix in (".service", ".timer", ".conf", ".socket", ".path")):
            continue
        try:
            if needle in p.read_text(encoding="utf-8", errors="replace"):
                hits.append(str(p))
        except OSError:
            continue
    return hits


# --------------------------------------------------------------------------- CLI


def _print_plan(plans: list[UnitPlan], target: Path) -> None:
    print(f"release pin plan → target {target.name}")
    if not plans:
        print("  no user unit pins a portfolio-server release")
    for p in plans:
        line = f"  {p.status.upper():16} {p.unit}  pinned={','.join(p.pinned) or '-'}"
        if p.archive:
            line += f"  archive={','.join(p.archive)}"
        if p.kept:
            line += f"  kept={','.join(p.kept)}"
        print(line)
        if p.reason:
            print(f"      {p.reason}")
    stale = [p for p in plans if p.status in ("rewrite", "broker_adjacent", "blocked")]
    if stale:
        print(f"  STALE PINS: {len(stale)} unit(s) not on {target.name}: " + ", ".join(p.unit for p in stale))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("cmd", choices=["plan", "apply", "rollback", "restore", "tripwire"])
    ap.add_argument("--target", help="release dir being activated (default: CURRENT resolved)")
    ap.add_argument("--from", dest="from_release", default="", help="rollback: the release being rolled away from")
    ap.add_argument("--receipt", help="restore: the apply receipt to undo")
    ap.add_argument("--unit-dir", default=os.environ.get("TRADEAI_SYSTEMD_USER_DIR") or str(REAL_UNIT_DIR))
    ap.add_argument("--releases-base", default=os.environ.get("TRADEAI_RELEASES_BASE")
                    or str(Path.home() / "trade-ai-releases" / "portfolio-server"))
    ap.add_argument("--receipt-dir", default=os.environ.get("TRADEAI_RELEASE_PIN_RECEIPT_DIR")
                    or str(Path.home() / ".local/state/cio-phase2-exact-main/release_pins"))
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--systemctl", default=None, help="systemctl command (tests pass a fake)")
    ap.add_argument("--deploy-restarted", default="", help="space-separated units the deploy restarts itself")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    unit_dir = Path(a.unit_dir)
    base = Path(a.releases_base)
    receipt_dir = Path(a.receipt_dir)
    try:
        cfg = load_config(Path(a.config))
        if a.cmd == "tripwire":
            hits = tripwire(unit_dir, cfg)
            for h in hits:
                print(f"TRIPWIRE: {h} references {cfg.archive_dirname}")
            return EXIT_BLOCKED if hits else EXIT_OK
        sysctl = Systemctl(a.systemctl, unit_dir)
        if a.cmd == "restore":
            if not a.receipt:
                raise Refused("restore needs --receipt")
            out = restore(Path(a.receipt), cfg=cfg, receipt_dir=receipt_dir, systemctl=sysctl)
            print(json.dumps(out, indent=2) if a.json else f"restore receipt → {out['receipt_path']}")
            bad = [u for u in out["units"] if u["status"] != "restored"]
            for u in bad:
                print(f"  RESTORE {u['unit']}: {u['status']}")
            return EXIT_BLOCKED if bad else EXIT_OK
        target = Path(a.target) if a.target else (base / "CURRENT").resolve()
        if a.cmd == "rollback":
            last = receipt_dir / "last_apply.json"
            if a.from_release and last.is_file():
                ptr = json.loads(last.read_text(encoding="utf-8"))
                if Path(ptr.get("target_release", "")).name == Path(a.from_release).name:
                    out = restore(Path(ptr["receipt"]), cfg=cfg, receipt_dir=receipt_dir, systemctl=sysctl)
                    print(f"rollback: restored drop-ins archived by the promote of {Path(a.from_release).name} "
                          f"→ {out['receipt_path']}")
                    bad = [u for u in out["units"] if u["status"] != "restored"]
                    for u in out["units"]:
                        print(f"  {u['unit']}: {u['status']} {','.join(u['restored'])}")
                    plans = build_plan(unit_dir, target, base, cfg)
                    _print_plan(plans, target)
                    stale = [p for p in plans if p.status in ("rewrite", "blocked")]
                    if stale:
                        print("  WARN pins restored to their pre-promote state are not on the rollback target; "
                              "run `release_pin_daemons.py apply --target <dir>` if they should follow it")
                    return EXIT_BLOCKED if bad else EXIT_OK
            print("rollback: no matching promote receipt — rewriting pins to the rollback target")
        plans = build_plan(unit_dir, target, base, cfg)
        if a.cmd == "plan":
            if a.json:
                print(json.dumps({"schema": SCHEMA_PLAN, "target_release": str(target), "dry_run": True,
                                  "units": [p.to_json() for p in plans]}, indent=2))
            else:
                _print_plan(plans, target)
                print("  DRY RUN — nothing written")
            return EXIT_BLOCKED if any(p.status == "blocked" for p in plans) else EXIT_OK
        _print_plan(plans, target)
        rec = apply_plan(plans, unit_dir=unit_dir, target=target, cfg=cfg, receipt_dir=receipt_dir,
                         systemctl=sysctl, deploy_restarted=set(a.deploy_restarted.split()),
                         mode="apply" if a.cmd == "apply" else "rollback", from_release=a.from_release)
        for u in rec["units"]:
            if u.get("managed_path"):
                print(f"  REWROTE {u['unit']} → {u['managed_path']} ({u.get('restart')}); "
                      f"archived {len(u['archived'])} drop-in(s)")
            elif u["status"] == "broker_adjacent":
                print(f"  {u['unit']}: {u['reason']}")
        print(f"receipt → {rec['receipt_path']}")
        if a.json:
            print(json.dumps(rec, indent=2))
        hits = tripwire(unit_dir, cfg)
        for h in hits:
            print(f"TRIPWIRE: {h} references {cfg.archive_dirname}")
        return EXIT_BLOCKED if hits or any(u["status"] == "blocked" for u in rec["units"]) else EXIT_OK
    except Refused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
