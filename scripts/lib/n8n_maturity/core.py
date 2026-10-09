"""Shared probe + result helpers for the n8n platform maturity scorer (N8nPlatformMaturity@v1).

Every collector reads evidence through a ``Probe``. The probe is READ-ONLY by construction:

* files are opened for reading only (``text``/``json``/``rows``/``sqlite_ro``);
* external commands go through ``Probe.run``, which refuses any argv that is not on the
  read-only allowlist below (crontab -l, systemctl --user show/list-*, docker exec ... psql
  with a single SELECT, gh api GET / gh run|pr list|view, journalctl --user, guard log/show,
  git log/rev-parse);
* SQLite is opened with ``mode=ro`` URIs.

Tests inject a fake ``runner`` and a tmp ``root``/``proj`` so nothing touches the host.

A dimension result is a dict built with ``dim_result``. Missing evidence scores 0 and is
marked UNVERIFIED (``unverified``); a collector never assumes a value it did not read.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import sqlite3
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

Runner = Callable[[list[str], float], "tuple[int, str, str]"]

VERIFIED = "VERIFIED"
PARTIAL = "PARTIAL"
UNVERIFIED = "UNVERIFIED"

# Read-only command allowlist: (argv prefix, extra predicate on the full argv).
_SELECT_RE = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)
_WRITE_SQL_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|COPY|VACUUM|CALL|DO)\b", re.IGNORECASE)


def _psql_select_only(argv: list[str]) -> bool:
    """Exactly one SQL argument after ``-c`` (or a combined short flag ending in c, e.g. ``-tAc``), SELECT/WITH only."""
    idx = next((i for i, a in enumerate(argv) if a == "-c" or re.fullmatch(r"-[A-Za-z]*c", a)), None)
    if idx is None or idx + 1 >= len(argv):
        return False
    sql = argv[idx + 1]
    return bool(_SELECT_RE.match(sql)) and not _WRITE_SQL_RE.search(sql) and ";" not in sql.strip().rstrip(";")


# docker inspect may read container env only through templates that cannot emit a secret VALUE:
# the names-only template, or a single-key template for a key that does not look secret.
_ENV_NAMES_ONLY = '{{range .Config.Env}}{{index (split . "=") 0}}{{"\\n"}}{{end}}'
_ENV_ONE_KEY_RE = re.compile(r'^\{\{range \.Config\.Env\}\}\{\{if eq \(index \(split \. "="\) 0\) "([A-Z0-9_]+)"\}\}'
                             r'\{\{\.\}\}\{\{end\}\}\{\{end\}\}$')
_SECRETISH = re.compile(r"PASS|SECRET|TOKEN|KEY|CRED|AUTH", re.IGNORECASE)


def _docker_inspect_safe(argv: list[str]) -> bool:
    if "--format" not in argv or argv.index("--format") + 1 >= len(argv):
        return False  # a bare inspect dumps the whole env, values included
    fmt = argv[argv.index("--format") + 1]
    if "Env" not in fmt and "Secret" not in fmt and "{{json ." not in fmt and fmt.strip() != "{{.}}":
        return True
    if fmt == _ENV_NAMES_ONLY:
        return True
    m = _ENV_ONE_KEY_RE.match(fmt)
    return bool(m) and not _SECRETISH.search(m.group(1))


def _gh_read_only(argv: list[str]) -> bool:
    if argv[1:2] == ["api"]:
        bad = {"-X", "--method", "-f", "-F", "--field", "--raw-field", "--input"}
        return not any(a in bad or a.startswith("--method=") or a.startswith("-X") for a in argv[2:])
    return argv[1:3] in (["run", "list"], ["run", "view"], ["pr", "list"], ["pr", "view"], ["workflow", "list"])


def is_read_only(argv: list[str]) -> bool:
    """True only for argv the scorer is allowed to execute (read-only by inspection)."""
    if not argv:
        return False
    exe = os.path.basename(argv[0])
    if exe == "crontab":
        return argv[1:] == ["-l"]
    if exe == "systemctl":
        return len(argv) >= 3 and argv[1] == "--user" and argv[2] in (
            "show", "list-units", "list-timers", "list-unit-files", "is-active", "is-enabled", "status")
    if exe == "journalctl":
        return "--user" in argv and not any(a in ("--rotate", "--vacuum-size", "--vacuum-time", "--flush") or
                                             a.startswith("--vacuum") for a in argv)
    if exe == "docker":
        if argv[1:2] == ["ps"]:
            return True
        if argv[1:2] == ["inspect"]:
            return _docker_inspect_safe(argv)
        return argv[1:2] == ["exec"] and "psql" in argv and _psql_select_only(argv)
    if exe == "gh":
        return _gh_read_only(argv)
    if exe == "git":
        rest = argv[3:] if argv[1:2] == ["-C"] else argv[1:]
        return rest[:1] in (["log"], ["rev-parse"], ["show"], ["ls-files"])
    if exe == "guard":
        return argv[1:2] in (["log"], ["show"], ["list"], ["status"])
    return False


def _default_runner(argv: list[str], timeout: float) -> "tuple[int, str, str]":
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)  # noqa: S603
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError as exc:
        return 127, "", f"not found: {exc}"
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"
    except OSError as exc:
        return 126, "", f"{type(exc).__name__}: {exc}"


@dataclass
class Probe:
    """Read-only evidence access. ``root`` = persistent state root, ``proj`` = repo checkout."""
    root: Path
    proj: Path
    now: _dt.datetime
    env: dict = field(default_factory=dict)
    config: dict = field(default_factory=dict)
    runner: Optional[Runner] = None
    timeout: float = 30.0
    commands: list = field(default_factory=list)  # audit trail of argv executed (rc only, never output)

    # ---- time -----------------------------------------------------------
    def since(self, hours: float) -> _dt.datetime:
        return self.now - _dt.timedelta(hours=hours)

    # ---- commands -------------------------------------------------------
    def run(self, argv: list[str], timeout: Optional[float] = None) -> "tuple[int, str, str]":
        if not is_read_only(argv):
            raise PermissionError(f"n8n maturity scorer refuses non-read-only command: {argv[:3]}")
        rc, out, err = (self.runner or _default_runner)(list(argv), timeout or self.timeout)
        self.commands.append({"argv": " ".join(argv[:4]) + (" …" if len(argv) > 4 else ""), "rc": rc})
        return rc, out, err

    def crontab(self) -> Optional[str]:
        rc, out, _ = self.run(["crontab", "-l"])
        return out if rc == 0 else None

    # ---- files ----------------------------------------------------------
    def text(self, path: Path) -> Optional[str]:
        try:
            return Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    def json(self, path: Path) -> Optional[Any]:
        t = self.text(path)
        if t is None:
            return None
        try:
            return json.loads(t)
        except json.JSONDecodeError:
            return None

    def rows(self, path: Path, *, since: Optional[_dt.datetime] = None, ts_keys: Iterable[str] = (
            "ts", "as_of", "at", "sent_at", "observed_at", "written_at", "finished_at", "created_at", "recorded_at"),
            limit: int = 500_000) -> Optional[list[dict]]:
        """JSONL rows (None when the file is absent). ``since`` filters on the first ts key present."""
        out: list[dict] = []
        cut = since.isoformat() if since else None
        try:
            with Path(path).open(encoding="utf-8", errors="replace") as fh:
                for i, line in enumerate(fh):
                    if i >= limit:
                        break
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(r, dict):
                        continue
                    if cut:
                        ts = next((str(r[k]) for k in ts_keys if r.get(k)), None)
                        if ts and _norm_ts(ts) < cut:
                            continue
                    out.append(r)
        except OSError:
            return None
        return out

    def mtime(self, path: Path) -> Optional[_dt.datetime]:
        try:
            return _dt.datetime.fromtimestamp(Path(path).stat().st_mtime, tz=_dt.timezone.utc)
        except OSError:
            return None

    def sqlite_ro(self, path: Path) -> Optional[sqlite3.Connection]:
        p = Path(path)
        if not p.exists():
            return None
        try:
            return sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=5)
        except sqlite3.Error:
            return None

    def gov(self) -> Path:
        return self.root / "data" / "governance"

    def runtime(self) -> Path:
        return self.root / "data" / "runtime"

    def cfg(self, dim_id: str) -> dict:
        return dict((self.config.get("dimensions") or {}).get(dim_id) or {})


def _norm_ts(ts: str) -> str:
    """Comparable ISO string (``Z`` → ``+00:00``; epoch numbers → ISO)."""
    s = str(ts).strip()
    try:
        f = float(s)
        if f > 1e9:
            return _dt.datetime.fromtimestamp(f, tz=_dt.timezone.utc).isoformat()
    except ValueError:
        pass
    return s.replace("Z", "+00:00")


def parse_ts(v: Any) -> Optional[_dt.datetime]:
    if v in (None, ""):
        return None
    try:
        d = _dt.datetime.fromisoformat(_norm_ts(str(v)))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=_dt.timezone.utc)


def evidence(source: str, **detail: Any) -> dict:
    """One typed evidence pointer: ``source`` is a path, a command or a table; detail is counts/timestamps."""
    return {"source": source, **{k: v for k, v in detail.items() if v is not None}}


def clamp(x: float, lo: float = 0.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, x))


def ratio_score(value: Optional[float], gate: float, *, gate_score: float = 8.0, top: Optional[float] = None) -> float:
    """Linear 0→gate maps to 0→gate_score; gate→top maps gate_score→10. Without ``top`` the gate scores
    gate_score and anything above it scores 10 (pass ``top`` = the gate to make the gate itself score 10)."""
    if value is None or gate <= 0:
        return 0.0
    if value <= gate:
        return clamp(gate_score * value / gate)
    if top is None or top <= gate:
        return 10.0
    return clamp(gate_score + (10.0 - gate_score) * (value - gate) / (top - gate))


def dim_result(dim_id: str, *, score: float, gate_rule: str, gate_pass: bool, metrics: dict,
               evidence_list: list[dict], status: str = VERIFIED, notes: Optional[list[str]] = None) -> dict:
    s = round(clamp(float(score)), 2)
    if status == UNVERIFIED:
        s = 0.0
        gate_pass = False
    return {"id": dim_id, "score": s, "status": status,
            "gate": {"rule": gate_rule, "pass": bool(gate_pass)},
            "metrics": metrics, "evidence": evidence_list, "notes": list(notes or [])}


def unverified(dim_id: str, gate_rule: str, reason: str, *, metrics: Optional[dict] = None,
               evidence_list: Optional[list[dict]] = None) -> dict:
    return dim_result(dim_id, score=0.0, gate_rule=gate_rule, gate_pass=False, metrics=metrics or {},
                      evidence_list=evidence_list or [], status=UNVERIFIED, notes=[f"UNVERIFIED: {reason}"])


def mean_score(parts: list[tuple[str, Optional[float]]]) -> "tuple[float, str, list[str]]":
    """Average sub-criterion scores. A None sub-score (missing evidence) counts 0 and makes the dimension PARTIAL;
    all None → UNVERIFIED."""
    if not parts:
        return 0.0, UNVERIFIED, ["no sub-criteria"]
    missing = [n for n, v in parts if v is None]
    total = sum(v for _, v in parts if v is not None) / len(parts)
    if len(missing) == len(parts):
        return 0.0, UNVERIFIED, [f"UNVERIFIED sub-criteria: {', '.join(missing)}"]
    return total, (PARTIAL if missing else VERIFIED), ([f"UNVERIFIED sub-criteria (scored 0): {', '.join(missing)}"] if missing else [])
