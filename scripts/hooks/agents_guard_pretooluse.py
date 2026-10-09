#!/usr/bin/env python3
"""Claude Code PreToolUse hook that enforces the AGENTS.md hard rails.

Installed per user in ~/.claude/settings.json (docs/ops/AGENTS_GUARD_HOOK.md); it is never
imported by Trade AI code. Claude Code pipes one JSON object to stdin (session_id, cwd,
tool_name, tool_input, ...). The hook:

  * allows silently (exit 0, no output) when no rule matches;
  * in ``log`` mode (the default; operator approval 2026-10-09: log-only for the first week)
    never denies, and appends one ``AgentsGuardDecision@v1`` line per matched rule to
    ``$TRADEAI_STATE_ROOT/data/runtime/agents_guard_hook.jsonl``;
  * in ``deny`` mode prints
    ``{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
    "permissionDecisionReason": ...}}`` and exits 0 when a rule whose action is ``deny`` matches.

Mode: ``TRADEAI_AGENTS_GUARD_MODE`` (log|deny) > ``mode`` in the rules file > ``log``.
Rules: ``TRADEAI_AGENTS_GUARD_RULES`` or ``config/agents_guard_hook_rules.json`` beside this
release. Every pattern, path, unit and tier is data there; this file holds only matching logic.

FAIL OPEN: any error inside the hook (bad JSON, unreadable rules, a parser bug, a 2 s
self-timeout) is logged as ``rule_id = "hook.error"`` and the tool call is ALLOWED, so a hook
bug never bricks a session. The grant ledger is read, never written or consumed.

Never logged: the raw command. A log line carries a SHA-256 of the command and a redacted
preview of at most 200 characters with secret-looking tokens masked.

stdlib only; runs under the system python3.

AUTHORITY: READ_ONLY_ADVISORY (reads stdin, the rules file and the grant ledger; appends its
own log). AGENTS.md §0, §2, §2A, §7A, §9.3, §10, §17, §22.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import signal
import sys
import time

SCHEMA = "AgentsGuardDecision@v1"
SCHEDULED_ENTRYPOINT = (
    "Claude Code PreToolUse hook: ~/.claude/settings.json hooks.PreToolUse runs this file from "
    "the served CURRENT release on every Bash/Edit/Write/MultiEdit/NotebookEdit/Read/Grep/mcp call; "
    "its log is consumed by scripts/report_agents_guard_hook.py"
)
HOOK_EVENT = "PreToolUse"
PREVIEW_MAX = 200
SELF_TIMEOUT_S = 2

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_RULES_PATH = os.path.normpath(os.path.join(_HERE, "..", "..", "config", "agents_guard_hook_rules.json"))


# --------------------------------------------------------------------------- helpers


def _home() -> str:
    return os.path.expanduser("~")


def _expand(p: str, home: str) -> str:
    if p == "~" or p.startswith("~/"):
        return home + p[1:]
    return p


def glob_to_regex(glob: str, home: str) -> re.Pattern[str]:
    g = _expand(glob, home)
    out, i = [], 0
    while i < len(g):
        if g.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif g.startswith("**", i):
            out.append(".*")
            i += 2
        elif g[i] == "*":
            out.append("[^/]*")
            i += 1
        elif g[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(g[i]))
            i += 1
    return re.compile("".join(out))


def resolve_path(p: str, cwd: str, home: str, shell_vars: dict[str, str] | None = None) -> str | None:
    """Absolute normalised path, or None when it depends on an unknown variable."""
    if not p:
        return None
    if shell_vars and "$" in p:
        p = re.sub(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?", lambda m: shell_vars.get(m.group(1), m.group(0)), p)
    p = _expand(p, home)
    p = re.sub(r"^\$\{?HOME\}?(?=/|$)", lambda _m: home, p)
    if "$" in p or "`" in p:
        return None
    if not p.startswith("/"):
        if not cwd:
            return None  # an earlier `cd` went somewhere unresolvable
        p = os.path.join(cwd, p)
    return os.path.normpath(p)


def _ancestors(p: str):
    while True:
        yield p
        parent = os.path.dirname(p)
        if parent == p:
            return
        p = parent


def _tails(p: str):
    parts = p.strip("/").split("/")
    for i in range(len(parts)):
        yield "/".join(parts[i:])


_SECRET_NAME = (
    r"[A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|API_?KEY|PRIVATE_KEY|COOKIE|CREDENTIAL|ACCESS_KEY|DSN|AUTH)[A-Z0-9_]*"
)
_REDACTIONS = [
    (re.compile(r"(?i)\b(" + _SECRET_NAME + r")(\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|\S+)"), r"\1\2***"),
    (re.compile(r"(?i)(authorization\s*:\s*)[^'\"\n]+"), r"\1***"),
    (re.compile(r"(?i)\b(bearer|basic|token)(\s+)[A-Za-z0-9._~+/=-]{8,}"), r"\1\2***"),
    (re.compile(r"(?i)(--?(?:password|passwd|token|api-key|apikey|secret|key|cookie)(?:=|\s+))\S+"), r"\1***"),
    (re.compile(r"(://[^/\s:@]+:)[^@\s/]+@"), r"\1***@"),
    (
        re.compile(
            r"\b(?:sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9]{10,}|github_pat_\w+|xox[abpr]-[\w-]+|AKIA[0-9A-Z]{12,}|eyJ[\w-]{8,}\.[\w-]+\.[\w-]+|0\.[A-Za-z0-9_-]{20,})"
        ),
        "***",
    ),
]
_OPAQUE = re.compile(r"[A-Za-z0-9+=_]{24,}")


def _mask_opaque(m: re.Match[str]) -> str:
    s = m.group(0)
    if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", s):
        return s  # git / sha256 digests are not secrets
    if re.search(r"\d", s) and re.search(r"[A-Za-z]", s):
        return "***"
    return s


def redact(text: str, limit: int = PREVIEW_MAX) -> str:
    out = text or ""
    for rx, repl in _REDACTIONS:
        out = rx.sub(repl, out)
    out = _OPAQUE.sub(_mask_opaque, out)
    out = out.replace("\n", " \\n ")
    return out[:limit]


# --------------------------------------------------------------------------- rules


class Rules:
    def __init__(self, doc: dict, home: str):
        self.doc = doc
        self.home = home
        self.by_id = {r["id"]: r for r in doc.get("rules", []) if r.get("enabled", True)}
        self.version = str(doc.get("version", "?"))
        self.temp_res = [glob_to_regex(g, home) for g in doc.get("temp_allowlist", [])]
        arch = doc.get("archive_expiry_exception") or {}
        self.archive_res = (
            [glob_to_regex(g, home) for g in arch.get("paths", [])] if arch.get("enabled") is True else []
        )
        self.wrappers = set(doc.get("shell_wrappers", []))
        self.shells = set(doc.get("shells", []))
        self._cache: dict = {}

    def get(self, rid: str) -> dict | None:
        return self.by_id.get(rid)

    def res(self, rid: str, key: str) -> list[re.Pattern[str]]:
        ck = (rid, key)
        if ck not in self._cache:
            r = self.by_id.get(rid) or {}
            self._cache[ck] = [glob_to_regex(g, self.home) for g in r.get(key, [])]
        return self._cache[ck]

    def rx(self, rid: str, key: str, flags: int = 0) -> re.Pattern[str] | None:
        ck = (rid, key, flags)
        if ck not in self._cache:
            r = self.by_id.get(rid) or {}
            v = r.get(key)
            self._cache[ck] = re.compile(v, flags) if v else None
        return self._cache[ck]

    def temp_allowed(self, path: str | None) -> bool:
        if not path:
            return False
        for a in _ancestors(path):
            if any(r.fullmatch(a) for r in self.temp_res) or any(r.fullmatch(a) for r in self.archive_res):
                return True
        return False


def path_matches(path: str | None, regs: list[re.Pattern[str]], *, as_dir: bool = True) -> bool:
    if not path:
        return False
    if any(r.fullmatch(path) for r in regs):
        return True
    return as_dir and any(r.fullmatch(path.rstrip("/") + "/_") for r in regs)


# --------------------------------------------------------------------------- grants


def grant_active(rules: Rules, tier: str, now: float) -> tuple[bool, str]:
    gl = rules.doc.get("grant_ledger") or {}
    gdir = os.environ.get(gl.get("dir_env", "GUARD_APPROVALS_DIR")) or _expand(
        gl.get("default_dir", "~/.cursor/approvals"), rules.home
    )
    path = os.path.join(gdir, gl.get("file", "grants.json"))
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except FileNotFoundError:
        return False, "ledger_missing"
    except (OSError, ValueError):
        return False, "ledger_unreadable"
    rec = doc.get(tier) if isinstance(doc, dict) else None
    if not isinstance(rec, dict):
        return False, "no_grant"
    try:
        if int(rec.get("expires") or 0) > now and int(rec.get("uses") or 0) != 0:
            return True, "active"
    except (TypeError, ValueError):
        return False, "ledger_unreadable"
    return False, "expired_or_used"


# --------------------------------------------------------------------------- shell parsing

_HEREDOC = re.compile(r"(?<!<)<<(-?)[ \t]*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")


def extract_heredocs(text: str) -> tuple[str, dict[str, str]]:
    bodies: dict[str, str] = {}
    pos = 0
    while True:
        m = _HEREDOC.search(text, pos)
        if not m:
            return text, bodies
        nl = text.find("\n", m.end())
        key = f"__AGH_HEREDOC_{len(bodies)}__"
        if nl < 0:
            bodies[key] = ""
            text = text[: m.start()] + "<<" + key + text[m.end() :]
            return text, bodies
        delim, strip_tabs = m.group(3), m.group(1) == "-"
        lines = text[nl + 1 :].split("\n")
        body, end_idx = [], None
        for idx, line in enumerate(lines):
            if (line.lstrip("\t") if strip_tabs else line).rstrip() == delim:
                end_idx = idx
                break
            body.append(line)
        bodies[key] = "\n".join(body)
        rest = "\n".join(lines[end_idx + 1 :]) if end_idx is not None else ""
        head = text[: m.start()] + "<<" + key + text[m.end() : nl]
        text = head + "\n" + rest
        pos = len(head)


def _take_group(text: str, i: int, open_c: str = "(", close_c: str = ")") -> tuple[str, int]:
    depth, q, j = 1, None, i
    while j < len(text):
        c = text[j]
        if q:
            if c == q:
                q = None
            elif c == "\\" and q == '"':
                j += 1
        elif c in "'\"":
            q = c
        elif c == "\\":
            j += 1
        elif c == open_c:
            depth += 1
        elif c == close_c:
            depth -= 1
            if depth == 0:
                return text[i:j], j + 1
        j += 1
    return text[i:], len(text)


SUBST_PLACEHOLDER = "$__AGH_SUBST__"  # contains "$": a path built from it stays unresolvable
MKTEMP_PLACEHOLDER = "/tmp/claude-mktemp-subst"  # $(mktemp ...) is a fresh temp path the caller owns


def _subst_placeholder(inner: str) -> str:
    """Replace a command substitution in the parent text so its words do not leak into argv."""
    return MKTEMP_PLACEHOLDER if re.match(r"\s*mktemp\b", inner) else SUBST_PLACEHOLDER


def split_shell(text: str) -> tuple[list[str], list[str]]:
    """Split on unquoted ; newline && || | &; collect $( ), backtick and <( ) bodies."""
    segs: list[str] = []
    subs: list[str] = []
    buf: list[str] = []
    q = None
    i, n = 0, len(text)

    def flush():
        s = "".join(buf).strip()
        if s:
            segs.append(s)
        buf.clear()

    while i < n:
        c = text[i]
        if q == "'":
            buf.append(c)
            if c == "'":
                q = None
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            buf.append(" " if text[i + 1] == "\n" else text[i : i + 2])
            i += 2
            continue
        if c == "$" and text.startswith("$(", i):
            inner, j = _take_group(text, i + 2)
            subs.append(inner)
            buf.append(_subst_placeholder(inner))
            i = j
            continue
        if c == "`":
            j = text.find("`", i + 1)
            j = n if j < 0 else j
            subs.append(text[i + 1 : j])
            buf.append(_subst_placeholder(text[i + 1 : j]))
            i = j + 1
            continue
        if q == '"':
            buf.append(c)
            if c == '"':
                q = None
            i += 1
            continue
        if c in "'\"":
            q = c
            buf.append(c)
            i += 1
            continue
        if c == "#" and (not buf or buf[-1] in " \t"):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if c in "<>" and text.startswith("(", i + 1):
            inner, j = _take_group(text, i + 2)
            subs.append(inner)
            buf.append(_subst_placeholder(inner))
            i = j
            continue
        if c in ";\n":
            flush()
            i += 1
            continue
        if c == "&":
            if text.startswith("&&", i):
                flush()
                i += 2
                continue
            if (buf and buf[-1] in "<>") or text.startswith("&>", i):
                buf.append(c)
                i += 1
                continue
            flush()
            i += 1
            continue
        if c == "|":
            if text.startswith("||", i):
                flush()
                i += 2
                continue
            if buf and buf[-1] == ">":
                buf.append(c)
                i += 1
                continue
            flush()
            i += 2 if text.startswith("|&", i) else 1
            continue
        buf.append(c)
        i += 1
    flush()
    return segs, subs


_KEYWORDS = {"then", "do", "else", "elif", "if", "while", "until", "!", "{", "(", "time"}
_REDIR = re.compile(r"^(\d*|&)(>>|>\||>|<<<|<<|<)(.*)$")
_ASSIGN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.S)
_PY = re.compile(r"^python[0-9.]*$")
_DEVNULL = {"/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty"}


class Segment:
    __slots__ = (
        "raw",
        "prog_path",
        "program",
        "argv",
        "env",
        "writes",
        "reads",
        "heredocs",
        "sudo",
        "stdin_args",
        "nested",
        "inline",
    )

    def __init__(self, raw: str):
        self.raw = raw
        self.prog_path = ""
        self.program = ""
        self.argv: list[str] = []
        self.env: dict[str, str] = {}
        self.writes: list[str] = []
        self.reads: list[str] = []
        self.heredocs: list[str] = []
        self.sudo = False
        self.stdin_args = False
        self.nested: list[str] = []
        self.inline: list[str] = []

    @property
    def text(self) -> str:
        return " ".join([self.program] + self.argv)


def _opts_then_rest(argv: list[str], with_arg: set[str]) -> list[str]:
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--":
            return argv[i + 1 :]
        if not a.startswith("-") or a == "-":
            return argv[i:]
        if a in with_arg:
            i += 2
            continue
        i += 1
    return []


def _strip_wrappers(toks: list[str], seg: Segment, rules: Rules) -> list[str]:
    for _ in range(12):
        while toks and _ASSIGN.match(toks[0]):
            k, v = _ASSIGN.match(toks[0]).groups()
            seg.env[k] = v
            toks = toks[1:]
        while toks and toks[0] in _KEYWORDS:
            toks = toks[1:]
        if not toks:
            return toks
        prog = os.path.basename(toks[0])
        if prog not in rules.wrappers:
            return toks
        rest = toks[1:]
        if not rest:
            return toks  # a bare wrapper (`env`, `time`) is itself the program
        if prog in ("sudo", "doas", "runuser"):
            seg.sudo = True
            rest = _opts_then_rest(rest, {"-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-U", "-T"})
        elif prog == "env":
            out, i = [], 0
            while i < len(rest):
                a = rest[i]
                if a in ("-u", "--unset", "-C", "--chdir"):
                    i += 2
                    continue
                if a == "-S" or a.startswith("--split-string"):
                    out = shlex.split(rest[i + 1]) + rest[i + 2 :] if i + 1 < len(rest) else []
                    break
                if a.startswith("-") and a != "-":
                    i += 1
                    continue
                out = rest[i:]
                break
            rest = out
        elif prog == "nice":
            rest = _opts_then_rest(rest, {"-n", "--adjustment"})
        elif prog == "ionice":
            rest = _opts_then_rest(rest, {"-c", "-n", "-p", "-P", "-u"})
        elif prog == "timeout":
            rest = _opts_then_rest(rest, {"-s", "-k", "--signal", "--kill-after"})
            rest = rest[1:]  # the duration
        elif prog == "stdbuf":
            rest = _opts_then_rest(rest, {"-i", "-o", "-e"})
        elif prog == "flock":
            rest = _opts_then_rest(rest, {"-w", "-E", "--timeout", "--conflict-exit-code"})
            rest = rest[1:]  # the lock file
            if rest[:1] in (["-c"], ["--command"]) and len(rest) > 1:
                seg.nested.append(rest[1])
                return []
        elif prog == "xargs":
            seg.stdin_args = True
            rest = _opts_then_rest(
                rest,
                {
                    "-n",
                    "-I",
                    "-P",
                    "-L",
                    "-d",
                    "-E",
                    "-s",
                    "-a",
                    "--max-args",
                    "--max-procs",
                    "--delimiter",
                    "--arg-file",
                },
            )
        elif prog == "systemd-run":
            rest = _opts_then_rest(
                rest,
                {
                    "-p",
                    "-u",
                    "-E",
                    "--unit",
                    "--property",
                    "--setenv",
                    "-M",
                    "-H",
                    "--slice",
                    "--uid",
                    "--gid",
                    "--description",
                },
            )
        else:
            rest = _opts_then_rest(rest, set())
        toks = rest
    return toks


def parse_segment(raw: str, heredocs: dict[str, str], rules: Rules) -> Segment | None:
    s = raw.strip()
    while s[:1] in ("(", "{", "!"):
        s = s[1:].lstrip()
    while (s.endswith(")") and s.count(")") > s.count("(")) or (s.endswith("}") and s.count("}") > s.count("{")):
        s = s[:-1].rstrip()
    if not s:
        return None
    seg = Segment(s)
    try:
        toks = shlex.split(s, posix=True)
    except ValueError:
        toks = s.split()
    clean: list[str] = []
    i = 0
    while i < len(toks):
        t = toks[i]
        m = _REDIR.match(t)
        if m and not t.startswith("-"):
            op, rest = m.group(2), m.group(3)
            if not rest and i + 1 < len(toks):
                rest = toks[i + 1]
                i += 1
            if op in ("<<",):
                if rest in heredocs:
                    seg.heredocs.append(heredocs[rest])
            elif op == "<<<":
                seg.heredocs.append(rest)
            elif op == "<":
                seg.reads.append(rest)
            elif not rest.startswith("&") and rest not in _DEVNULL:
                seg.writes.append(rest)
            i += 1
            continue
        clean.append(t)
        i += 1
    toks = _strip_wrappers(clean, seg, rules)
    if not toks:
        return seg if (seg.nested or seg.env) else None
    seg.prog_path = toks[0]
    seg.program = os.path.basename(toks[0])
    seg.argv = toks[1:]
    p, a = seg.program, seg.argv
    # nested shells / eval / ssh / su
    if p in rules.shells or p == "su":
        for k, t in enumerate(a):
            if re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", t) and k + 1 < len(a):
                seg.nested.append(a[k + 1])
                break
        else:
            if p in rules.shells:
                seg.nested.extend(seg.heredocs)
    elif p == "eval":
        seg.nested.append(" ".join(a))
    elif p == "ssh":
        rest = _opts_then_rest(
            a,
            {
                "-i",
                "-p",
                "-o",
                "-l",
                "-F",
                "-J",
                "-L",
                "-R",
                "-D",
                "-W",
                "-b",
                "-c",
                "-E",
                "-e",
                "-m",
                "-O",
                "-Q",
                "-S",
                "-w",
            },
        )
        if len(rest) > 1:
            seg.nested.append(" ".join(rest[1:]))
    # inline code
    if _PY.match(p) or p in ("node", "deno", "ruby", "perl", "php"):
        for k, t in enumerate(a):
            if t in ("-c", "-e", "--eval", "-p", "-E") and k + 1 < len(a):
                seg.inline.append(a[k + 1])
                break
        seg.inline.extend(seg.heredocs)
    # write targets
    if p == "tee":
        seg.writes.extend(x for x in a if not x.startswith("-"))
    elif p == "sed" and any(
        x == "-i" or x.startswith("-i") or x.startswith("--in-place") or (re.fullmatch(r"-[A-Za-z]+", x) and "i" in x)
        for x in a
    ):
        nonopt = [x for x in a if not x.startswith("-")]
        has_e = any(x in ("-e", "-f") or x.startswith("--expression") for x in a)
        seg.writes.extend(nonopt if has_e else nonopt[1:])
    elif p in ("cp", "mv", "install", "rsync", "ln", "scp"):
        nonopt = [x for x in a if not x.startswith("-")]
        tdir = [a[k + 1] for k, x in enumerate(a) if x in ("-t", "--target-directory") and k + 1 < len(a)]
        if tdir:
            seg.writes.extend(tdir)
        elif nonopt:
            seg.writes.append(nonopt[-1])
    elif p == "dd":
        seg.writes.extend(x[3:] for x in a if x.startswith("of="))
        seg.reads.extend(x[3:] for x in a if x.startswith("if="))
    elif p in ("truncate", "touch", "chmod", "chown"):
        seg.writes.extend(
            x for x in a if not x.startswith("-") and not re.fullmatch(r"[0-7]{3,4}|[ugoa]*[+=-][rwxXst]*|\d+[KMG]?", x)
        )
    return seg


# --------------------------------------------------------------------------- evaluation


class Ctx:
    def __init__(self, rules: Rules, now: float):
        self.rules = rules
        self.home = rules.home
        self.now = now
        self.findings: list[dict] = []
        self._seen: set = set()
        self._grants: dict = {}
        self.vars: dict[str, str] = {}

    def grant(self, tier: str) -> tuple[bool, str]:
        if tier not in self._grants:
            self._grants[tier] = grant_active(self.rules, tier, self.now)
        return self._grants[tier]

    def add(self, rid: str, detail: str, *, tier: str | None = None) -> None:
        rule = self.rules.get(rid)
        if not rule:
            return
        key = (rid, detail)
        if key in self._seen:
            return
        self._seen.add(key)
        f = {
            "rule_id": rid,
            "section": rule.get("section", ""),
            "action": rule.get("action", "deny"),
            "reason": rule.get("reason", ""),
            "detail": detail[:300],
            "grant_tier": None,
            "grant_state": None,
        }
        tier = tier or rule.get("grant_tier")
        if tier:
            ok, state = self.grant(tier)
            f["grant_tier"], f["grant_state"] = tier, state
            if ok:
                f["action"] = "allowed_by_grant"
        self.findings.append(f)


def _nonopts(argv: list[str]) -> list[str]:
    out, after = [], False
    for a in argv:
        if after or not a.startswith("-") or a == "-":
            out.append(a)
        elif a == "--":
            after = True
    return out


def _has_short(argv: list[str], ch: str, longs: tuple[str, ...] = ()) -> bool:
    for a in argv:
        if a in longs:
            return True
        if re.fullmatch(r"-[A-Za-z0-9]+", a) and ch in a[1:]:
            return True
    return False


def _git_sub(argv: list[str]) -> tuple[str, list[str], list[str], str | None]:
    cfg, cdir, i = [], None, 0
    while i < len(argv):
        a = argv[i]
        if a in ("-C",) and i + 1 < len(argv):
            cdir = argv[i + 1]
            i += 2
            continue
        if a == "-c" and i + 1 < len(argv):
            cfg.append(argv[i + 1])
            i += 2
            continue
        if a.startswith("-"):
            i += 1
            continue
        return a, argv[i + 1 :], cfg, cdir
    return "", [], cfg, cdir


def check_paths_for_writes(ctx: Ctx, paths: list[str | None], label: str) -> None:
    r = ctx.rules
    for p in paths:
        if not p:
            continue
        if path_matches(p, r.res("broker.execution_code_edit", "path_globs"), as_dir=False):
            ctx.add("broker.execution_code_edit", f"{label} {p}")
        if path_matches(p, r.res("broker.live_credential", "path_globs"), as_dir=False):
            ctx.add("broker.live_credential", f"{label} {p}")
        # A symlink to .env (worktree setup) exposes nothing, and a copy into the session's temp area is
        # caught as a read of its source; neither is a credential write.
        if (
            label != "bash:ln"
            and not r.temp_allowed(p)
            and path_matches(p, r.res("secrets.read", "path_globs"), as_dir=False)
            and not path_matches(p, r.res("secrets.read", "path_allow_globs"), as_dir=False)
        ):
            ctx.add("secrets.write", f"{label} {p}")
        lrx = r.rx("liveops.self_grant", "ledger_dir_regex")
        if lrx and lrx.search(p):
            ctx.add("liveops.self_grant", f"{label} {p}")
        if path_matches(p, r.res("governed.hook_config", "path_globs"), as_dir=False):
            ctx.add("governed.hook_config", f"{label} {p}")
        gov = r.get("governed.served_edit")
        if gov:
            for root in gov.get("served_roots", []):
                root = _expand(root, ctx.home).rstrip("/")
                if p == root or p.startswith(root + "/"):
                    tail = p[len(root) + 1 :]
                    gre = r.res("governed.served_edit", "governed_globs")
                    if any(g.fullmatch(t) for t in _tails(tail) for g in gre):
                        ctx.add("governed.served_edit", f"{label} {p}")
        hb = r.get("remote.hook_bypass")
        if (
            hb
            and label.startswith("bash:")
            and ("/" + hb.get("hooks_dir", ".githooks") + "/") in (p + "/")
            and label.split()[0] in ("bash:chmod", "bash:mv", "bash:ln", "bash:truncate")
        ):
            ctx.add("remote.hook_bypass", f"{label} {p}")


def check_segment(seg: Segment, ctx: Ctx, cwd: str) -> None:
    r, p, a, home = ctx.rules, seg.program, seg.argv, ctx.home
    res = lambda x: resolve_path(x, cwd, home, ctx.vars)  # noqa: E731

    # ---- env assignments (prefix or export)
    assigns = dict(seg.env)
    if p in ("export", "declare", "typeset", "setenv") or (p == "systemctl" and "set-environment" in a):
        for t in a:
            m = _ASSIGN.match(t)
            if m:
                assigns[m.group(1)] = m.group(2)
    lf = r.get("broker.live_flag")
    frx = r.rx("broker.live_flag", "flag_regex")
    for k, v in assigns.items():
        if lf and frx and frx.match(k) and v.strip("'\"") not in lf.get("safe_values", []):
            ctx.add("broker.live_flag", f"{k}=<set>")
        brx = r.rx("remote.hook_bypass", "bypass_env_regex")
        if brx and brx.match(k) and v.strip("'\"").lower() not in ("", "0", "false", "no", "off"):
            ctx.add("remote.hook_bypass", f"{k} set")

    # ---- broker
    lh = r.get("broker.live_host_call")
    hrx = r.rx("broker.live_host_call", "live_hosts_regex")
    is_inline_prog = bool(_PY.match(p)) or p in (lh or {}).get("inline_code_programs", [])
    if lh and hrx:
        if p in lh.get("network_clients", []) and hrx.search(seg.raw):
            ctx.add("broker.live_host_call", f"{p} -> live broker host")
        elif is_inline_prog and (hrx.search(" ".join(a)) or any(hrx.search(c) for c in seg.inline)):
            ctx.add("broker.live_host_call", f"{p} inline -> live broker host")
    orx = r.rx("broker.order_invoke", "inline_code_regex")
    irx = r.rx("broker.order_invoke", "inline_broker_import_regex")
    if orx and any(orx.search(c) and (irx is None or irx.search(c)) for c in seg.inline):
        ctx.add("broker.order_invoke", f"{p} inline order call")
    oi = r.get("broker.order_invoke")
    if oi:
        entries = oi.get("execution_entrypoints", [])
        script = None
        if _PY.match(p) or p in r.shells:
            if "-m" in a:
                k = a.index("-m")
                if k + 1 < len(a):
                    script = a[k + 1].replace(".", "/") + ".py"
            else:
                rest = _nonopts(a)
                script = rest[0] if rest else None
        elif "/" in seg.prog_path:
            script = seg.prog_path
        if script:
            sp = res(script) or script
            if any(sp.endswith("/" + e) or sp == e for e in entries):
                ctx.add("broker.order_invoke", f"runs {os.path.basename(sp)}")
    cred = r.res("broker.live_credential", "path_globs")
    if cred and (p in (r.get("secrets.read") or {}).get("read_programs", []) or _PY.match(p)):
        for t in _nonopts(a) + seg.reads:
            rp = res(t)
            if path_matches(rp, cred, as_dir=False):
                ctx.add("broker.live_credential", f"{p} {rp}")

    # ---- delete
    allowed = r.temp_allowed
    if p == "rm" and (_has_short(a, "r", ("--recursive",)) or _has_short(a, "R")):
        targets = _nonopts(a)
        if not targets and seg.stdin_args:
            ctx.add("delete.recursive_rm", "rm -r with targets from stdin (xargs)")
        for t in targets:
            rp = res(t)
            if not allowed(rp):
                ctx.add("delete.recursive_rm", f"rm -r {rp or t}")
    if p == "find":
        destructive = "-delete" in a
        for k, t in enumerate(a):
            if (
                t in ("-exec", "-execdir", "-ok", "-okdir")
                and k + 1 < len(a)
                and os.path.basename(a[k + 1]) in ("rm", "shred", "unlink", "truncate")
            ):
                destructive = True
        names = [a[k + 1] for k, t in enumerate(a) if t in ("-name", "-iname") and k + 1 < len(a)]
        safe = set((r.get("delete.find_delete") or {}).get("safe_name_patterns", []))
        if destructive and names and all(n in safe for n in names):
            destructive = False  # bytecode / cache cleanup only
        if destructive:
            starts = []
            for t in a:
                if t.startswith("-") or t in ("(", "!", ")"):
                    break
                starts.append(t)
            for t in starts or ["."]:
                rp = res(t)
                if not allowed(rp):
                    ctx.add("delete.find_delete", f"find {rp or t} -delete")
    if p == "git":
        sub, rest, cfg, cdir = _git_sub(a)
        gcwd = res(cdir) if cdir else cwd
        if sub == "clean" and (_has_short(rest, "f", ("--force",))) and not _has_short(rest, "n", ("--dry-run",)):
            if not allowed(gcwd):
                ctx.add("delete.git_clean", f"git clean in {gcwd}")
        hb = r.get("remote.hook_bypass")
        if hb:
            for c in cfg:
                if c.lower().startswith("core.hookspath=") and c.split("=", 1)[1].rstrip("/").split("/")[-1] != hb.get(
                    "hooks_dir", ".githooks"
                ):
                    ctx.add("remote.hook_bypass", f"git -c {c.split('=')[0]}")
            if sub in hb.get("commit_like", []) and (
                "--no-verify" in rest or (sub == "commit" and _has_short(rest, "n"))
            ):
                ctx.add("remote.hook_bypass", f"git {sub} --no-verify")
            if sub == "config" and any(x.lower() == "core.hookspath" for x in rest):
                vals = [x for x in rest if not x.startswith("-") and x.lower() != "core.hookspath"]
                if vals and vals[0] != hb.get("hooks_dir", ".githooks") and "--get" not in rest:
                    ctx.add("remote.hook_bypass", "git config core.hooksPath")
        if sub == "push" and not _push_exempt(ctx, gcwd):
            _check_push(ctx, rest)
        if sub == "remote" and rest[:1] and rest[0] in ("set-url", "rename"):
            ctx.add("remote.non_origin_push", f"git remote {rest[0]}")
        if sub == "branch" and any(x in ("-m", "-M", "--move") for x in rest):
            ctx.add("remote.branch_rename", "git branch -m")
    st = r.get("delete.shred_truncate")
    if st and p in st.get("programs", []):
        opts_with = {"-s", "--size", "-r", "--reference", "-n", "--iterations", "--random-source"}
        targets, k = [], 0
        while k < len(a):
            if a[k] in opts_with:
                k += 2
                continue
            if not a[k].startswith("-"):
                targets.append(a[k])
            k += 1
        for t in targets:
            rp = res(t)
            if not allowed(rp):
                ctx.add("delete.shred_truncate", f"{p} {rp or t}")
    drx = r.rx("delete.docker_volume", "regex")
    if drx and p in ("docker", "docker-compose") and drx.search(seg.text):
        ctx.add("delete.docker_volume", seg.text[:80])

    # ---- remote: gh
    if p == "gh":
        if a[:2] == ["pr", "merge"]:
            ctx.add("remote.pr_merge", "gh pr merge")
        if a[:1] == ["api"]:
            _check_gh_api(ctx, a[1:])
    if p in ((lh or {}).get("network_clients", [])):
        gx = r.rx("broker.live_host_call", "github_api_regex")
        prx = r.rx("remote.gh_api_ref_write", "path_regex")
        if (
            gx
            and prx
            and gx.search(seg.raw)
            and prx.search(seg.raw)
            and re.search(r"(-X|--request)\s*(PUT|POST|PATCH|DELETE)", seg.raw)
        ):
            ctx.add("remote.gh_api_ref_write", f"{p} api.github.com ref write")

    # ---- secrets
    sr = r.get("secrets.read")
    if sr:
        sglobs, sallow = r.res("secrets.read", "path_globs"), r.res("secrets.read", "path_allow_globs")
        if p in sr.get("read_programs", []) and not _names_only(p, a):
            for t in _path_args(p, a) + [x.split("=", 1)[1] for x in a if x.startswith("--") and "=" in x] + seg.reads:
                rp = res(t)
                if path_matches(rp, sglobs, as_dir=False) and not path_matches(rp, sallow, as_dir=False):
                    ctx.add("secrets.read", f"{p} {rp}")
        elif seg.reads and p not in ("source", "."):
            for t in seg.reads:
                rp = res(t)
                if (
                    path_matches(rp, sglobs, as_dir=False)
                    and not path_matches(rp, sallow, as_dir=False)
                    and p in sr.get("read_programs", []) + ["while", "read", "cat"]
                ):
                    ctx.add("secrets.read", f"< {rp}")
        vrx = r.rx("secrets.read", "secret_var_regex")
        if vrx and p in sr.get("echo_programs", []):
            names = re.findall(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)", seg.raw) + (
                [x for x in a if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", x)] if p == "printenv" else []
            )
            for nm in names:
                if vrx.match(nm):
                    ctx.add("secrets.read", f"{p} ${nm}")
        brx = r.rx("secrets.read", "bws_regex")
        if brx and p == "bws" and brx.search(seg.text):
            ctx.add("secrets.read", "bws secret access")
    if (p in ("env", "printenv") and not a) or (
        p in ("set", "export", "declare", "typeset") and (not a or a in (["-p"], ["-x"], ["-px"]))
    ):
        ctx.add("secrets.env_dump", f"{p} {' '.join(a)}".strip())

    # ---- liveops
    sv = r.get("liveops.service")
    if sv:
        prx = r.rx("liveops.service", "prod_unit_regex")
        if p in ("systemctl", "service"):
            if p == "systemctl":
                rest = _opts_then_rest(
                    a,
                    {
                        "-M",
                        "-H",
                        "-t",
                        "-p",
                        "-s",
                        "--type",
                        "--property",
                        "--signal",
                        "--host",
                        "--machine",
                        "-n",
                        "--lines",
                        "-o",
                        "--output",
                    },
                )
                verb, units = (rest[0], rest[1:]) if rest else ("", [])
            else:
                units, verb = a[:1], (a[1] if len(a) > 1 else "")
            units = [u for u in units if not u.startswith("-")]
            if verb in sv.get("verbs", []):
                if verb in sv.get("no_unit_verbs", []) or not units:
                    ctx.add("liveops.service", f"{p} {verb}")
                for u in units:
                    if (prx and prx.match(u)) or "*" in u:
                        ctx.add("liveops.service", f"{p} {verb} {u}")
        if p in ("docker", "docker-compose", "podman"):
            crx = r.rx("liveops.service", "docker_prod_container_regex")
            sub = a[0] if a else ""
            rest = a[1:]
            if sub == "container" and rest:
                sub, rest = rest[0], rest[1:]
            if p == "docker-compose" or sub == "compose":
                crest = _opts_then_rest(
                    rest if sub == "compose" else a,
                    {"-f", "--file", "-p", "--project-name", "--env-file", "--profile", "--project-directory"},
                )
                if crest and crest[0] in sv.get("compose_verbs", []):
                    ctx.add("liveops.service", f"docker compose {crest[0]}")
            elif sub in sv.get("docker_verbs", []):
                for name in _nonopts(rest):
                    if crx and crx.match(name):
                        ctx.add("liveops.service", f"docker {sub} {name}")
    if p == "crontab" and "-l" not in a:
        ctx.add("liveops.cron", "crontab " + (" ".join(x if x.startswith("-") else "<arg>" for x in a) or "<stdin>"))
    dp = r.get("liveops.deploy")
    if dp:
        entries = set(dp.get("entrypoints", []))
        script, rest = None, []
        if p in entries:
            script, rest = p, a
        elif p in r.shells:
            no = _nonopts(a)
            if no and os.path.basename(no[0]) in entries:
                script, rest = os.path.basename(no[0]), no[1:]
        if script and any(x in dp.get("actions", []) for x in rest):
            ctx.add("liveops.deploy", f"{script} {' '.join(x for x in rest if x in dp.get('actions', []))}")
    if p == "guard" and a[:1] and a[0] in ("grant", "plan") and len(a) > 1 and not {"-h", "--help", "help"} & set(a):
        ctx.add("liveops.self_grant", f"guard {a[0]}")
    if any(x.endswith("guard_ledger.py") for x in [seg.program] + a[:2]):
        sub = next((x for x in a if not x.startswith("-") and not x.endswith(".py")), "")
        if sub in ("grant", "create", "recover", "init", "recover-empty"):
            ctx.add("liveops.self_grant", f"guard_ledger {sub}")

    # ---- write targets
    check_paths_for_writes(ctx, [res(w) for w in seg.writes], f"bash:{p}")


# Linear-time: the alternation branches are disjoint and nothing nests a quantifier. The first
# version, (...|[A-Za-z0-9_]+)+, backtracked catastrophically (1.5 s on a 500-char grep pattern).
_NAMES_ONLY_PATTERN = re.compile(r"\^?(?:\[[A-Za-z0-9_\-]+\][*+]?|[A-Za-z0-9_])*\\?=?")


def _path_args(p: str, a: list[str]) -> list[str]:
    """Non-option args that name files: grep/rg's pattern and sed/awk's script are not paths."""
    no = _nonopts(a)
    if p in ("grep", "egrep", "fgrep", "rg", "ag") and not any(
        x in ("-e", "-f", "--regexp", "--file") or x.startswith(("--regexp=", "--file=")) for x in a
    ):
        return no[1:]
    if p == "sed" and not any(
        x in ("-e", "-f", "--expression", "--file") or x.startswith(("--expression=", "--file=")) for x in a
    ):
        return no[1:]
    if p in ("awk", "gawk") and not any(x in ("-f", "--file") for x in a):
        return no[1:]
    if p in ("cp", "scp", "rsync") and not any(x in ("-t", "--target-directory") for x in a):
        return no[:-1]  # the last operand is the destination (a write, checked separately)
    return no


def _names_only(p: str, a: list[str]) -> bool:
    if p in ("grep", "egrep", "fgrep", "rg"):
        if (
            _has_short(a, "l")
            or _has_short(a, "L")
            or _has_short(a, "c")
            or _has_short(a, "q")
            or any(x in ("--files-with-matches", "--count", "--quiet", "--files-without-match") for x in a)
        ):
            return True
        if _has_short(a, "o", ("--only-matching",)):
            pats = [a[k + 1] for k, x in enumerate(a) if x in ("-e", "--regexp") and k + 1 < len(a)]
            if not pats:
                no = _nonopts(a)
                pats = no[:1]
            return bool(pats) and all(len(x) <= 120 and _NAMES_ONLY_PATTERN.fullmatch(x) for x in pats)
        return False
    if p == "cut":
        return (
            any(x in ("-d=", "-d", "--delimiter==") or x.startswith("-d=") for x in a)
            and any(x in ("-f1", "-f", "1") for x in a)
            and "-f1-" not in a
        )
    if p in ("awk", "gawk"):
        return any(x in ("-F=", "-F") for x in a) and any(re.fullmatch(r"\{\s*print\s+\$1\s*\}", x) for x in a)
    if p == "sed":
        return any(re.fullmatch(r"s([/|#])=\.\*\1\1g?", x) for x in a)
    return False


def _push_exempt(ctx: Ctx, cwd: str | None) -> bool:
    """A push from a repo that is not Trade AI (agent memory repo, DOF project) is out of scope."""
    if not cwd:
        return False  # unknown repo: the rules apply
    inside = ctx.rules.res("remote.push_to_main", "applies_to_cwd_globs")
    return not any(r.fullmatch(a) for a in _ancestors(cwd) for r in inside)


def _check_push(ctx: Ctx, rest: list[str]) -> None:
    nr = ctx.rules.get("remote.non_origin_push") or {}
    pm = ctx.rules.get("remote.push_to_main") or {}
    allowed = set(nr.get("allowed_remotes", ["origin"]))
    protected = set(pm.get("protected_branches", ["main", "master"]))
    pos, k = [], 0
    while k < len(rest):
        x = rest[k]
        if x in ("-o", "--push-option", "--receive-pack", "--exec"):
            k += 2
            continue
        if x.startswith("--repo="):
            if x.split("=", 1)[1] not in allowed:
                ctx.add("remote.non_origin_push", "git push --repo=<other>")
        elif x in ("--all", "--mirror"):
            ctx.add("remote.push_to_main", f"git push {x}")
        elif x == "--no-verify":
            pass  # handled by hook_bypass
        elif not x.startswith("-"):
            pos.append(x)
        k += 1
    if pos:
        remote = pos[0]
        if remote not in allowed:
            ctx.add(
                "remote.non_origin_push",
                "git push to non-origin remote"
                if "://" not in remote and "@" not in remote
                else "git push to a raw URL",
            )
        for spec in pos[1:]:
            dst = spec.lstrip("+").split(":")[-1]
            dst = dst[len("refs/heads/") :] if dst.startswith("refs/heads/") else dst
            if dst in protected:
                ctx.add("remote.push_to_main", f"git push {remote} -> {dst}")


def _check_gh_api(ctx: Ctx, a: list[str]) -> None:
    prx = ctx.rules.rx("remote.gh_api_ref_write", "path_regex")
    grx = ctx.rules.rx("remote.gh_api_ref_write", "graphql_regex")
    method, fields, endpoint, k = None, False, None, 0
    with_arg = {
        "-X",
        "--method",
        "-f",
        "-F",
        "--field",
        "--raw-field",
        "-H",
        "--header",
        "--input",
        "-q",
        "--jq",
        "-t",
        "--template",
        "--hostname",
        "-p",
        "--preview",
        "--cache",
    }
    while k < len(a):
        x = a[k]
        if x in ("-X", "--method") and k + 1 < len(a):
            method = a[k + 1].upper()
        elif x.startswith("--method="):
            method = x.split("=", 1)[1].upper()
        if (
            x in ("-f", "-F", "--field", "--raw-field", "--input")
            or x.startswith(("--field=", "--raw-field=", "--input="))
            or (len(x) > 2 and x[:2] in ("-f", "-F") and "=" in x)
        ):
            fields = True
        if x in with_arg:
            k += 2
            continue
        if not x.startswith("-") and endpoint is None:
            endpoint = x
        k += 1
    if not endpoint:
        return
    if endpoint == "graphql":
        if grx and grx.search(" ".join(a)):
            ctx.add("remote.gh_api_ref_write", "gh api graphql mutation")
        return
    writes = (method in ("PUT", "POST", "PATCH", "DELETE")) or (method is None and fields)
    if prx and prx.search(endpoint) and writes:
        ctx.add("remote.gh_api_ref_write", f"gh api {method or 'POST'} {endpoint}")


def analyze_shell(text: str, ctx: Ctx, cwd: str, depth: int = 0) -> str:
    if depth > 5 or not text:
        return cwd
    text2, heredocs = extract_heredocs(text)
    segs, subs = split_shell(text2)
    for s in subs:
        analyze_shell(s, ctx, cwd, depth + 1)
    for raw in segs:
        seg = parse_segment(raw, heredocs, ctx.rules)
        if seg is None:
            continue
        if seg.program in ("cd", "pushd"):
            target = _nonopts(seg.argv)
            cwd = (resolve_path(target[0], cwd, ctx.home, ctx.vars) if target else ctx.home) or ""
            continue
        assigns = dict(seg.env) if not seg.program else {}
        if seg.program in ("export", "declare", "typeset"):
            assigns.update(m.groups() for m in map(_ASSIGN.match, seg.argv) if m)
        for k, v in assigns.items():
            v = re.sub(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?", lambda m: ctx.vars.get(m.group(1), m.group(0)), v)
            if "$" in v:
                ctx.vars.pop(k, None)
            else:
                ctx.vars[k] = _expand(v, ctx.home)
        check_segment(seg, ctx, cwd)
        check_sql(seg, ctx)
        for nested in seg.nested:
            analyze_shell(nested, ctx, cwd, depth + 1)
    return cwd


def check_sql(seg: Segment, ctx: Ctx) -> None:
    """SQL reaching a database: a DB client's argv + heredocs, or inline code that executes SQL.
    Heredocs written to files (cat > x <<EOF) and PR bodies are text, not SQL, and are not scanned."""
    sq = ctx.rules.get("delete.sql_destructive")
    if not sq:
        return
    texts = []
    if seg.program in sq.get("db_programs", []):
        texts.append(seg.raw + "\n" + "\n".join(seg.heredocs))
    dctx = ctx.rules.rx("delete.sql_destructive", "db_context_regex", re.I)
    texts.extend(c for c in seg.inline if dctx and dctx.search(c))
    for text in texts:
        for pat in sq.get("statement_regexes", []):
            m = re.search(pat, text, re.I | re.M)
            if m:
                ctx.add("delete.sql_destructive", m.group(0).strip()[:60])
        crx = ctx.rules.rx("broker.live_credential", "sql_regex", re.I)
        if crx and crx.search(text):
            ctx.add("broker.live_credential", "SQL on a broker token table")


def evaluate(payload: dict, rules: Rules, now: float) -> tuple[Ctx, str, str]:
    """Return (ctx, subject_for_hash, preview_source)."""
    ctx = Ctx(rules, now)
    tool = str(payload.get("tool_name") or "")
    ti = payload.get("tool_input") or {}
    if not isinstance(ti, dict):
        ti = {}
    cwd = str(payload.get("cwd") or os.getcwd())
    home = rules.home
    if tool == "Bash" or (
        tool.startswith("mcp__")
        and isinstance(ti.get("command"), str)
        and re.search(rules.doc.get("mcp_shell_tool_regex") or "(?!)", tool)
    ):
        cmd = str(ti.get("command") or "")
        analyze_shell(cmd, ctx, cwd)
        return ctx, cmd, cmd
    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        paths = [ti.get("file_path") or ti.get("notebook_path") or ""]
        for e in ti.get("edits") or []:
            if isinstance(e, dict) and e.get("file_path"):
                paths.append(e["file_path"])
        rps = [resolve_path(str(x), cwd, home) for x in paths if x]
        check_paths_for_writes(ctx, rps, tool)
        subj = " ".join(str(x) for x in paths if x)
        return ctx, f"{tool} {subj}", f"{tool} {subj}"
    if tool in ("Read", "Grep", "Glob"):
        raw = str(ti.get("file_path") or ti.get("path") or "")
        rp = resolve_path(raw, cwd, home) if raw else None
        content = tool == "Read" or (tool == "Grep" and ti.get("output_mode") == "content")
        sr = rules.get("secrets.read")
        if (
            sr
            and rp
            and content
            and path_matches(rp, rules.res("secrets.read", "path_globs"), as_dir=False)
            and not path_matches(rp, rules.res("secrets.read", "path_allow_globs"), as_dir=False)
        ):
            ctx.add("secrets.read", f"{tool} {rp}")
        if rp and content and path_matches(rp, rules.res("broker.live_credential", "path_globs"), as_dir=False):
            ctx.add("broker.live_credential", f"{tool} {rp}")
        return ctx, f"{tool} {raw}", f"{tool} {raw}"
    if tool.startswith("mcp__"):
        blob = json.dumps(ti, sort_keys=True)[:20000]
        pm = rules.rx("remote.pr_merge", "mcp_tool_regex")
        if pm and pm.search(tool):
            ctx.add("remote.pr_merge", tool)
        lt = rules.rx("broker.live_host_call", "mcp_tool_regex")
        hrx = rules.rx("broker.live_host_call", "live_hosts_regex")
        if lt and hrx and lt.search(tool) and hrx.search(blob):
            ctx.add("broker.live_host_call", f"{tool} -> live broker host")
        return ctx, f"{tool} {blob}", f"{tool} {blob}"
    return ctx, tool, tool


# --------------------------------------------------------------------------- I/O


def load_rules(home: str) -> Rules:
    path = os.environ.get("TRADEAI_AGENTS_GUARD_RULES") or DEFAULT_RULES_PATH
    with open(path, encoding="utf-8") as fh:
        return Rules(json.load(fh), home)


def resolve_mode(rules_doc: dict | None) -> str:
    m = (os.environ.get("TRADEAI_AGENTS_GUARD_MODE") or (rules_doc or {}).get("mode") or "log").strip().lower()
    return m if m in ("log", "deny") else "log"


def log_path(rules_doc: dict | None, home: str) -> str:
    doc = rules_doc or {}
    root = os.environ.get("TRADEAI_STATE_ROOT") or _expand(
        doc.get("default_state_root", "~/trade-ai-releases/persistent-state"), home
    )
    return os.path.join(root, doc.get("log_relpath", "data/runtime/agents_guard_hook.jsonl"))


def append_log(path: str, records: list[dict]) -> None:
    if not records:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = "".join(json.dumps(r, sort_keys=True, ensure_ascii=True) + "\n" for r in records).encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def _base_record(payload: dict, mode: str, version: str, subject: str, preview: str, now: float) -> dict:
    return {
        "schema": SCHEMA,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "session_id": str(payload.get("session_id") or "")[:80],
        "tool_use_id": str(payload.get("tool_use_id") or "")[:80],
        "tool": str(payload.get("tool_name") or "")[:120],
        "cwd": str(payload.get("cwd") or "")[:300],
        "mode": mode,
        "rules_version": version,
        "command_sha256": hashlib.sha256(subject.encode("utf-8", "replace")).hexdigest(),
        "command_preview": redact(preview),
    }


def deny_output(reason: str) -> str:
    return json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": HOOK_EVENT,
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
    )


def run(stdin_text: str, now: float | None = None) -> tuple[str, list[dict], str | None]:
    """Pure-ish core: returns (stdout_text, log_records, log_path). Raises on hook errors."""
    now = time.time() if now is None else now
    t0 = time.perf_counter()
    home = _home()
    payload = json.loads(stdin_text)
    if not isinstance(payload, dict):
        raise ValueError("payload is not a JSON object")
    rules = load_rules(home)
    mode = resolve_mode(rules.doc)
    ctx, subject, preview = evaluate(payload, rules, now)
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
    records, deny_reasons = [], []
    for f in ctx.findings:
        would_deny = f["action"] == "deny"
        denied = would_deny and mode == "deny"
        rec = _base_record(payload, mode, rules.version, subject, preview, now)
        rec.update(
            {
                "rule_id": f["rule_id"],
                "section": f["section"],
                "would_deny": would_deny,
                "denied": denied,
                "rule_action": f["action"],
                "reason": f["reason"],
                "detail": redact(f["detail"], 300),
                "grant_tier": f["grant_tier"],
                "grant_state": f["grant_state"],
                "elapsed_ms": elapsed_ms,
            }
        )
        records.append(rec)
        if denied:
            g = (
                f" No active '{f['grant_tier']}' grant ({f['grant_state']}); ask with: bin/guard request {f['grant_tier']}."
                if f["grant_tier"]
                else ""
            )
            deny_reasons.append(
                f"[{f['rule_id']}] {f['reason']} ({f['section']}){g} Matched: {redact(f['detail'], 160)}"
            )
    out = ""
    if deny_reasons:
        out = deny_output(
            "AGENTS.md guard hook: "
            + " | ".join(deny_reasons)[:1800]
            + " Do not rephrase the command to route around this; stop and report (AGENTS.md §0 rule 3)."
        )
    return out, records, log_path(rules.doc, home)


def _on_alarm(_sig, _frm):
    raise TimeoutError(f"hook exceeded {SELF_TIMEOUT_S}s")


def main() -> int:
    raw = ""
    try:
        if hasattr(signal, "SIGALRM"):
            signal.signal(signal.SIGALRM, _on_alarm)
            signal.alarm(SELF_TIMEOUT_S)
        raw = sys.stdin.read()
        out, records, lpath = run(raw)
        if hasattr(signal, "SIGALRM"):
            signal.alarm(0)
        try:
            append_log(lpath, records)
        except OSError:
            pass
        if out:
            sys.stdout.write(out + "\n")
        return 0
    except BaseException as exc:  # noqa: BLE001 — FAIL OPEN on any hook error, including the self-timeout
        try:
            if hasattr(signal, "SIGALRM"):
                signal.alarm(0)
            home = _home()
            doc = None
            try:
                with open(os.environ.get("TRADEAI_AGENTS_GUARD_RULES") or DEFAULT_RULES_PATH, encoding="utf-8") as fh:
                    doc = json.load(fh)
            except Exception:  # noqa: BLE001
                doc = None
            rec = _base_record({}, resolve_mode(doc), str((doc or {}).get("version", "?")), raw, raw, time.time())
            rec.update(
                {
                    "rule_id": "hook.error",
                    "section": "",
                    "would_deny": False,
                    "denied": False,
                    "rule_action": "fail_open",
                    "reason": redact(f"{type(exc).__name__}: {exc}", 300),
                    "detail": "",
                    "grant_tier": None,
                    "grant_state": None,
                }
            )
            append_log(log_path(doc, home), [rec])
        except BaseException:  # noqa: BLE001
            pass
        return 0


if __name__ == "__main__":
    sys.exit(main())
