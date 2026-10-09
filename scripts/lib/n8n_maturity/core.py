"""Shared probe + result helpers for the n8n platform maturity scorer (N8nPlatformMaturity@v1).

Every collector reads evidence through a ``Probe``. The probe is READ-ONLY by construction:

* files are opened for reading only (``text``/``json``/``rows``/``sqlite_ro``);
* external commands go through ``Probe.run``, which refuses any argv that is not one of the
  PINNED read-only shapes below: ``crontab -l``; ``systemctl --user`` show/list-*;
  ``journalctl --user`` with read flags only; ``gh run list``; ``docker ps``/``docker inspect``
  with the exact templates the collectors use (none can print an env value); and psql built by
  ``psql_argv`` only (``-X -At -U u -d db -c <one SELECT>``, docker exec with
  PGOPTIONS default_transaction_read_only=on; the runner sets the same for host psql);
* the runner resolves the program's real path to a trusted system bin dir and the probe
  redacts secret-shaped output before any collector sees it;
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
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

Runner = Callable[[list[str], float], "tuple[int, str, str]"]

VERIFIED = "VERIFIED"
PARTIAL = "PARTIAL"
UNVERIFIED = "UNVERIFIED"

# ---- read-only command allowlist ---------------------------------------------------------------
# Every argv the scorer may execute has an EXACT, pinned shape. Anything else is refused before it runs.
# The runner additionally resolves the program to its real path and requires a system bin directory,
# runs psql with PGOPTIONS default_transaction_read_only=on, and redacts secret-shaped output.

PG_READ_ONLY_OPTIONS = "-c default_transaction_read_only=on"
TRUSTED_BIN_DIRS = ("/usr/bin", "/bin", "/usr/sbin", "/sbin", "/usr/local/bin", "/usr/share/postgresql-common")
_IDENT = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]{0,127}$")
_SELECT_RE = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)
_FORBIDDEN_SQL = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|COPY|VACUUM|CALL|DO|INTO|LOCK|"
    r"SET|RESET|LISTEN|NOTIFY|PREPARE|EXECUTE|DECLARE|IMPORT|REFRESH|CLUSTER|REINDEX|COMMENT|SECURITY|MERGE|"
    r"credentials_entity|dblink\w*|lo_\w+|set_config|current_setting|query_to_xml\w*|nextval|setval|"
    r"txid_current\w*|"
    # catalog / app tables holding password hashes, API keys or instance secrets — never read by the scorer
    r"pg_authid|pg_shadow|pg_user_mapping\w*|user_api_keys|user_entity|settings)\b"
    r"|\bpg_\w+\s*\(|\bFOR\s+(NO\s+KEY\s+|KEY\s+)?SHARE\b", re.IGNORECASE)
# Unicode-escaped identifiers (U&"..." / UESCAPE) can spell any forbidden name without matching it.
_UNICODE_IDENT = re.compile(r"U&|\bUESCAPE\b", re.IGNORECASE)

# The exact docker templates the collectors use. Nothing that can print an env VALUE (no {{.}}, no
# {{.Config}}, no printf/json); the single-key template is pinned to a non-secret key.
DOCKER_PS_FORMATS = frozenset({"{{.Names}}\t{{.Image}}", "{{.Names}} {{.Image}}"})
DOCKER_INSPECT_TEMPLATES = frozenset({
    '{{range .Config.Env}}{{index (split . "=") 0}}{{"\\n"}}{{end}}',
    '{{range .Config.Env}}{{if eq (index (split . "=") 0) "DB_POSTGRESDB_USER"}}{{.}}{{end}}{{end}}',
    '{{index .Config.Labels "com.docker.compose.project.config_files"}}',
})
_SYSTEMCTL_VERBS = ("show", "list-units", "list-timers", "list-unit-files", "is-active", "is-enabled")
_SYSTEMCTL_FLAGS = frozenset({"--all", "--no-pager", "--no-legend", "--plain", "--failed"})
# ``systemctl --user show`` must name its properties (-p), and only these: none of them can print an
# Environment= value (a unit's env file paths and argv are read; values are never requested).
SYSTEMCTL_SHOW_PROPERTIES = frozenset({
    "ActiveState", "SubState", "LoadState", "UnitFileState", "Result", "NRestarts", "Restart", "ExecStart",
    "EnvironmentFiles", "FragmentPath", "DropInPaths", "ActiveEnterTimestamp", "InactiveEnterTimestamp",
    "ExecMainStatus", "ExecMainCode", "NextElapseUSecRealtime", "LastTriggerUSec", "Triggers", "Unit",
})
_JOURNAL_VALUE_FLAGS = frozenset({"-u", "--since", "--until", "-o", "-n"})
_JOURNAL_BARE_FLAGS = frozenset({"--user", "--no-pager", "-q", "--quiet", "--utc"})
_JOURNAL_OUTPUTS = frozenset({"short-iso", "short-iso-precise", "cat", "short", "json"})
_GH_RUN_VALUE_FLAGS = frozenset({"-R", "--workflow", "--branch", "--json", "-L", "--event", "--status"})


def is_safe_sql(sql: str) -> bool:
    """A single SELECT/WITH read: no DML/DDL words, no INTO, no pg_* function calls, no credential / password /
    API-key tables, no sequence writes, no row locks, no psql meta-commands, at most one trailing semicolon.

    Quoted identifiers are scanned with their double quotes removed (``"pg_read_file"(`` is ``pg_read_file(``)
    and Unicode-escaped identifiers (``U&"..."`` / ``UESCAPE``) are refused outright, so a forbidden name
    cannot be smuggled past the word scan. Legitimate quoted columns (``"startedAt"``) still pass."""
    s = str(sql)
    body = s.strip().rstrip(";")
    if not _SELECT_RE.match(s) or ";" in body or "\\" in s or _UNICODE_IDENT.search(s):
        return False
    return not _FORBIDDEN_SQL.search(body.replace('"', ""))


def _psql_tail_ok(tail: list[str]) -> bool:
    """psql -X -At [-h HOST] -U USER -d DB -c SQL — exactly this shape."""
    if tail[:3] != ["psql", "-X", "-At"]:
        return False
    rest = tail[3:]
    if rest[:1] == ["-h"]:
        if len(rest) < 2 or not _IDENT.match(rest[1]):
            return False
        rest = rest[2:]
    return (len(rest) == 6 and rest[0] == "-U" and _IDENT.match(rest[1]) is not None and rest[2] == "-d"
            and _IDENT.match(rest[3]) is not None and rest[4] == "-c" and is_safe_sql(rest[5]))


def psql_argv(sql: str, *, user: str, db: str, container: Optional[str] = None, host: Optional[str] = None) -> list[str]:
    """Build the only psql argv shape the allowlist accepts (docker exec with PGOPTIONS read-only, or host)."""
    tail = ["psql", "-X", "-At"] + (["-h", host] if host else []) + ["-U", user, "-d", db, "-c", sql]
    if container:
        return ["docker", "exec", "-e", f"PGOPTIONS={PG_READ_ONLY_OPTIONS}", container] + tail
    return tail


def _flags_ok(args: list[str], value_flags: frozenset, bare_flags: frozenset, check=None) -> bool:
    i = 0
    while i < len(args):
        a = args[i]
        if a in value_flags:
            if i + 1 >= len(args) or (check and not check(a, args[i + 1])):
                return False
            i += 2
        elif a in bare_flags:
            i += 1
        else:
            return False
    return True


def _systemctl_ok(argv: list[str]) -> bool:
    if len(argv) < 3 or argv[1] != "--user" or argv[2] not in _SYSTEMCTL_VERBS:
        return False
    rest = argv[3:]
    if argv[2] == "show" and "-p" not in rest:
        return False  # a bare `show` dumps every property, Environment= values included
    i = 0
    while i < len(rest):
        a = rest[i]
        if a == "-p":
            if i + 1 >= len(rest):
                return False
            props = rest[i + 1].split(",")
            if argv[2] != "show" or not all(p in SYSTEMCTL_SHOW_PROPERTIES for p in props):
                return False
            i += 2
        elif a in _SYSTEMCTL_FLAGS or re.fullmatch(r"--type=(service|timer)", a) or _IDENT.match(a):
            i += 1
        else:
            return False
    return True


def _journal_ok(argv: list[str]) -> bool:
    def check(flag: str, val: str) -> bool:
        if flag == "-u":
            return _IDENT.match(val) is not None
        if flag == "-o":
            return val in _JOURNAL_OUTPUTS
        if flag == "-n":
            return val.isdigit()
        return re.fullmatch(r"[0-9: \-+TZUCa-z]{1,40}", val) is not None
    return "--user" in argv and _flags_ok(argv[1:], _JOURNAL_VALUE_FLAGS, _JOURNAL_BARE_FLAGS, check)


def _gh_ok(argv: list[str]) -> bool:
    if argv[1:3] != ["run", "list"]:
        return False

    def check(flag: str, val: str) -> bool:
        # a value must start alnum so it can never be read as another flag (``-R --hostname``)
        return re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.,/\-]{0,199}", val) is not None
    return _flags_ok(argv[3:], _GH_RUN_VALUE_FLAGS, frozenset(), check)


def _docker_ok(argv: list[str]) -> bool:
    if argv[1:2] == ["ps"]:
        return len(argv) == 4 and argv[2] == "--format" and argv[3] in DOCKER_PS_FORMATS
    if argv[1:2] == ["inspect"]:
        return (len(argv) == 5 and _IDENT.match(argv[2]) is not None and argv[3] == "--format"
                and argv[4] in DOCKER_INSPECT_TEMPLATES)
    if argv[1:2] == ["exec"]:
        return (len(argv) >= 6 and argv[2:4] == ["-e", f"PGOPTIONS={PG_READ_ONLY_OPTIONS}"]
                and _IDENT.match(argv[4]) is not None and _psql_tail_ok(argv[5:]))
    return False


def is_read_only(argv: list[str]) -> bool:
    """True only for argv in one of the pinned read-only shapes."""
    if not argv or not isinstance(argv[0], str):
        return False
    prog = argv[0]
    if "/" in prog and os.path.dirname(os.path.realpath(prog)) not in TRUSTED_BIN_DIRS:
        return False
    exe = os.path.basename(prog)
    if exe == "crontab":
        return argv[1:] == ["-l"]
    if exe == "systemctl":
        return _systemctl_ok(argv)
    if exe == "journalctl":
        return _journal_ok(argv)
    if exe == "docker":
        return _docker_ok(argv)
    if exe == "gh":
        return _gh_ok(argv)
    if exe == "psql":
        return _psql_tail_ok(["psql"] + argv[1:])
    return False


_PG_REDIRECT_ENV = ("PGSERVICE", "PGSERVICEFILE", "PGSYSCONFDIR")

_SECRET_NAME = r"[A-Z0-9_.\-]*(?:PASS|PASSWD|PASSWORD|PWD|SECRET|TOKEN|KEY|CREDENTIAL|AUTH)[A-Z0-9_.\-]*"
_REDACTIONS = (
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=\-]{8,}"), r"\1 <redacted>"),
    # "NAME": "value" / 'NAME': 'value' (JSON / YAML / dict reprs), value may contain spaces
    (re.compile(r"""(?i)(["'])(""" + _SECRET_NAME + r""")\1(\s*[:=]\s*)(["'])(?:(?!\4).)*\4"""),
     r"\1\2\1\3\4<redacted>\4"),
    # NAME = "quoted value with spaces" / NAME: 'x y'
    (re.compile(r"""(?i)\b(""" + _SECRET_NAME + r""")(\s*[:=]\s*)(["'])(?:(?!\3).)*\3"""), r"\1\2\3<redacted>\3"),
    # NAME: value (colon form)
    (re.compile(r"(?i)\b(" + _SECRET_NAME + r")\s*:\s*(?!<redacted>)[^\s,;}\]]+"), r"\1: <redacted>"),
    # NAME value (space-separated: `password abc`, `N8N_ENCRYPTION_KEY deadbeef`). Only the bare words
    # password/passwd/secret or an UPPER_CASE env-style name, and never a flag/redirect value, so crontab and
    # journal prose ("refresh_token.py --apply", "token refreshed") is left alone.
    (re.compile(r"\b((?i:password|passwd|secret)|[A-Z0-9_]*(?:PASS|PASSWORD|SECRET|TOKEN|KEY|CREDENTIAL)[A-Z0-9_]*)"
                r"[ \t]+(?![:=<\-])(?!<redacted>)[^\s,;}\]'\"]{3,}"), r"\1 <redacted>"),
    (re.compile(r"(?i)\b(" + _SECRET_NAME + r")\s*=\s*(?!<redacted>)\S+"), r"\1=<redacted>"),
    (re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://[^:/\s@]+):[^@\s]+@"), r"\1:<redacted>@"),
    (re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,}|xox[abpr]-[A-Za-z0-9\-]{10,}|sk-[A-Za-z0-9\-_]{20,}|"
                r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}|n8n_api_[A-Za-z0-9_\-]{8,}|"
                r"(?:AKIA|ASIA)[A-Z0-9]{16})\b"), "<redacted>"),
)


def redact(text: str) -> str:
    """Mask secret-shaped substrings (KEY=value for secret-named keys, bearer tokens, URL passwords, known
    token formats). Collectors never need a secret; this is a second line behind the template allowlist."""
    out = text or ""
    for pat, rep in _REDACTIONS:
        out = pat.sub(rep, out)
    return out


def resolve_program(prog: str) -> Optional[str]:
    """Real path of ``prog`` if it lives in a trusted system bin directory, else None."""
    found = prog if "/" in prog else shutil.which(prog)
    if not found:
        return None
    real = os.path.realpath(found)
    return found if os.path.dirname(real) in TRUSTED_BIN_DIRS else None


def _default_runner(argv: list[str], timeout: float) -> "tuple[int, str, str]":
    path = resolve_program(argv[0])
    if path is None:
        return 127, "", f"program not found in a trusted bin dir: {os.path.basename(argv[0])}"
    env = dict(os.environ)
    env["PGOPTIONS"] = PG_READ_ONLY_OPTIONS
    for k in _PG_REDIRECT_ENV:  # a service file could point psql at another host/db/options
        env.pop(k, None)
    try:
        p = subprocess.run([path] + list(argv[1:]), capture_output=True, text=True, timeout=timeout,  # noqa: S603
                           check=False, env=env)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"
    except OSError as exc:
        return 126, "", f"{type(exc).__name__}"


class ConfigError(KeyError):
    """A threshold the scorer needs is missing from config/n8n_platform_maturity.json."""


def need(config: dict, dim_id: str, key: str) -> Any:
    """A required per-dimension threshold — no in-code fallback; missing → ConfigError (dimension UNVERIFIED)."""
    d = (config.get("dimensions") or {}).get(dim_id) or {}
    if key not in d:
        raise ConfigError(f"config dimensions.{dim_id}.{key} missing")
    return d[key]


def need_top(config: dict, key: str) -> Any:
    if key not in config:
        raise ConfigError(f"config {key} missing")
    return config[key]


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
        out, err = redact(out), redact(err)
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

    def need(self, dim_id: str, key: str) -> Any:
        return need(self.config, dim_id, key)

    def window_hours(self, dim_id: str) -> float:
        """Per-dimension ``window_hours`` if set, else the top-level ``window_hours`` (required)."""
        d = (self.config.get("dimensions") or {}).get(dim_id) or {}
        return float(d["window_hours"]) if "window_hours" in d else float(need_top(self.config, "window_hours"))

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


def cap_on_fail(probe_or_config: Any, score: float, gate_pass: bool) -> float:
    """The one gate cap every dimension applies: a failed gate scores at most the top-level ``gate_cap``
    (required config), so "gate met" ⇔ score ≥ gate_score holds for every dimension."""
    cfg = probe_or_config.config if isinstance(probe_or_config, Probe) else probe_or_config
    return float(score) if gate_pass else min(float(score), float(need_top(cfg, "gate_cap")))


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
