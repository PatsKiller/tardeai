#!/usr/bin/env python3
"""check_no_pii.py -- no personal or identifying data in the repository.

Operator request, 2026-10-27, verbatim: "would need some validates or checks that I don't have any type of
secrets or codes or anything identifiable in the codes and GitHub that should also be in the agents.md".
Credentials are gitleaks' job (.gitleaks.toml, .github/workflows/secret-scan.yml) and
scripts/check_no_secrets.py's. This script covers what those do not look for: data that identifies a
person, an account or a machine.

    python3 scripts/check_no_pii.py --range origin/main...HEAD       # ADDED lines only; any finding fails
    python3 scripts/check_no_pii.py --tree                           # whole tree vs the ratchet baseline
    python3 scripts/check_no_pii.py --tree --write-baseline          # after REMOVING findings only
    python3 scripts/check_no_pii.py --baseline-guard origin/main     # the baseline file may only shrink

CATEGORIES
  email             an email address outside the example allow-list (example.com/.org/.net, *.example,
                    *.test, *.invalid, noreply@anthropic.com, *.users.noreply.github.com, git@ remotes)
  deny_pattern      a pattern from the operator's private deny file (TRADEAI_PII_DENY_FILE; see below)
  date_of_birth     dob / date_of_birth / birth_date (also inside names such as user_dob) with a real date
  account_number    6+ digits next to account / acct / IRA / routing (also broker_account,
                    bank_routing_number), or a broker-style id: U or Z followed by 7-8 digits
  telegram_chat_id  a numeric Telegram chat id next to chat_id (also TELEGRAM_CHAT_ID, OPERATOR_CHAT_ID)
  private_ip        an RFC1918 or Tailscale (CGNAT 100.64.0.0/10) host address; CIDR ranges are not hosts
  home_path         /home/<user>/, /Users/<user>/ or a Windows drive Users folder, for a non-generic user
  blocked_path      a file that must never be committed: .env* (not .env.example), *.pem, *.key, *.p12,
                    *.pfx, *.jks, id_rsa* / id_dsa* / id_ecdsa* / id_ed25519*, .netrc, .npmrc,
                    credentials.json, token.json, *.db, *.sqlite*, *.har, cookies*, **/sessions/**,
                    **/persistent-state/**, **/.next/**, *.tsbuildinfo, **/holdings*.json.
                    In --range mode it fails only when the file is ADDED (or renamed or copied in).

RATCHET. The tree already holds findings committed before this check existed. config/pii_baseline.json
records their COUNT per category (no values, no paths). --tree fails if any category grows; a category that
shrank is reported so the baseline can be lowered. --write-baseline refuses to raise a count, and
--baseline-guard <ref> (run on every pull request) fails if the change raises any count in the file itself.
--range has no baseline: new lines must be clean.

PRIVATE DENY FILE. The operator's real names, domains and handles must not be written into this repository,
not even as a deny list. Put one case-insensitive regex per line in a file OUTSIDE the repository and point
TRADEAI_PII_DENY_FILE at it (CI writes it from an Actions secret). A deny file inside the repository is
refused. Deny findings fail --range; in --tree they are reported but not ratcheted, because the count depends
on a file CI and the host may hold differently.

NO INLINE ESCAPE HATCH. No marker on a line silences a finding. --range reports how many added lines carry
an inline allow marker (this scanner's old "pii" "-ok" or gitleaks' allow comment) so a reviewer sees them;
CI runs gitleaks with --ignore-gitleaks-allow. Synthetic test values are assembled at runtime instead.

ONE CONTENT EXCLUSION, verified by bytes: tests/fixtures/agents_pre_*/** holds verbatim, hash-pinned snapshots
of the policy files (AGENTS.md, its adapters, docs/governance) taken before a major AGENTS.md version. A file
there is skipped ONLY when its exact bytes, hashed as a git blob, equal a past version of one of
POLICY_SOURCES in the history of the base ref (--range: the range's left side; --tree: HEAD), AND its file name
is that policy file's basename (a leading dot may be dropped: goosehints). Such a file adds
nothing that main's own history did not already hold, and re-flagging it would block every snapshot PR. Any
other file in those folders (an extra notes.md, an edited copy, a new agents_pre_x/ folder) is scanned like
everything else. In CI a pull request runs main's copy of this script, so a PR cannot widen the rule.
Blocked-path rules always apply there, and gitleaks has no path exemption at all.
.gz files are decompressed and scanned.

OUTPUT never prints any part of a found value: path:line and category only (for blocked_path, the rule).
Exit 0 clean, 1 findings (or a ratchet grew), 2 usage or git error (fail closed).
Stdlib only. AUTHORITY: READ_ONLY_ADVISORY (CI tooling; no broker, no Telegram, no DB, no network).
"""

from __future__ import annotations

import argparse
import bisect
import datetime as _dt
import fnmatch
import gzip
import hashlib
import io
import json
import os
import re
import string
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
BASELINE_REL = "config/pii_baseline.json"
SCHEMA = "PiiBaseline@v1"
DENY_ENV = "TRADEAI_PII_DENY_FILE"
GZ_MAX_BYTES = 64 * 1024 * 1024
# Assembled so this file does not itself carry the markers it counts.
ALLOW_MARKERS = ("pii" + "-ok", "gitleaks" + ":allow")
ASCII_ALNUM = frozenset(string.ascii_letters + string.digits)

CATEGORIES = (
    "email",
    "deny_pattern",
    "date_of_birth",
    "account_number",
    "telegram_chat_id",
    "private_ip",
    "home_path",
    "blocked_path",
)
RATCHETED = tuple(c for c in CATEGORIES if c != "deny_pattern")

# ── email ────────────────────────────────────────────────────────────────────────────────────────────
EMAIL_RE = re.compile(
    r"(?<![A-Za-z0-9._%+-])([A-Za-z0-9][A-Za-z0-9._%+-]{0,63})@"
    r"((?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+([A-Za-z]{2,24}))(?![A-Za-z0-9-])"
)
ALLOWED_EMAIL_DOMAINS = frozenset({"example.com", "example.org", "example.net"})
ALLOWED_EMAIL_SUFFIXES = (".example", ".test", ".invalid", ".localhost", ".users.noreply.github.com")
ALLOWED_EMAILS = frozenset(
    {
        "noreply@anthropic.com",
        "noreply@github.com",
        "git@github.com",
        "git@gitlab.com",
        "git@bitbucket.org",
    }
)
# "icon@2x.png" and "pkg@scope.js" are file names, not addresses.
FILE_TLDS = frozenset(
    "png jpg jpeg gif svg webp ico bmp js mjs cjs ts tsx jsx py json css scss md txt yml yaml html htm "
    "toml lock map sh pdf zip gz csv xml".split()
)
# An address needs an internet TLD: any two-letter country code, or one of these. Without this,
# systemd template units ("unit@instance.timer") and dotted code paths ("row@field.proposed") read as email.
REAL_TLDS = frozenset(
    "com net org edu gov mil int io ai dev app co me info biz xyz tech cloud email online site pro name mail "
    "live life family work inc llc ltd company solutions services systems consulting digital studio agency "
    "group team money finance financial capital fund trade trading investments law legal network global".split()
)

# ── content categories ──────────────────────────────────────────────────────────────────────────────
# Keyword boundaries use (?<![A-Za-z0-9]) / (?![A-Za-z0-9]), not \b: \b treats "_" as a word character, which
# hid TELEGRAM_CHAT_ID=, user_dob, broker_account and bank_routing_number.
DOB_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:dob|date[_-]?of[_-]?birth|birth[_-]?date)(?![A-Za-z0-9])[\"']?\s*[:=]\s*[\"']?"
    r"(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})"
)
# The keyword may carry a number label (account_number, acct_no, routing#) but not other words, so
# ids like ROUTING_DECISION_20261027 or ACCOUNT_LABELS_20261023 are not account numbers.
_ACCT_LABEL = r"(?:[_ -]?(?:no|num|number|id|#))?s?"
ACCOUNT_RE = re.compile(
    r"(?i)(?:(?<![A-Za-z0-9])(?:account|acct|ira|routing)" + _ACCT_LABEL + r"(?![A-Za-z0-9])"
    r"[\s\"'#:=_]{0,6}(\d[\d-]{4,}\d)(?![\w-])"
    r"|(?<![\w-])(\d{6,})[\s\"'#:,_]{0,3}(?:account|acct|ira)(?![A-Za-z0-9]))"
)
# Fast path (same matches, run on the lowercased text): find the keyword, then match around it.
_ACCT_KW_RE = re.compile(r"account|acct|ira|routing")
_ACCT_FWD_RE = re.compile(
    r"(?:account|acct|ira|routing)" + _ACCT_LABEL + r"(?![a-z0-9])[\s\"'#:=_]{0,6}(\d[\d-]{4,}\d)(?![\w-])"
)
_ACCT_BACK_KW_RE = re.compile(r"(?:account|acct|ira)(?![a-z0-9])")
_ACCT_BACK_NUM_RE = re.compile(r"(?<![\w-])(\d{6,})[\s\"'#:,_]{0,3}$")
# Broker-style account ids: U + 7-8 digits (IBKR), Z + 8 digits (Fidelity). Case-sensitive.
LETTER_ACCT_RE = re.compile(r"(?<![A-Za-z0-9])([UZ]\d{7,8})(?![A-Za-z0-9])")
DATE_LIKE_RE = re.compile(r"^(?:19|20)\d{2}-?(?:0[1-9]|1[0-2])-?(?:0[1-9]|[12]\d|3[01])(?:\d{4,6})?$")
CHAT_ID_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])chat[_-]?ids?(?![A-Za-z0-9])[\"']?\s*(?:==|[:=])\s*[\[(]?\s*[\"']?(-?\d{6,})(?!\d)"
)
IPV4_RE = re.compile(r"(?<![\d.])(10|172|192|100)\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?!\d|\.\d|/\d)")
HOME_RES = (
    re.compile(r"/home/([A-Za-z0-9._-]+)/"),
    re.compile(r"(?<![\w.:-])/Users/([A-Za-z0-9._-]+)/"),  # not after "C:" (the Windows form below)
    re.compile(r"(?i)(?<![A-Za-z0-9])[a-z]:(?:\\{1,2}|/)users(?:\\{1,2}|/)([^\\/\s\"':*?<>|]+)(?:\\|/)"),
)
GENERIC_USERS = frozenset(
    "user username runner ubuntu you me example someone alice bob ci test tester dev app node nobody "
    "claude your-user youruser your_user shared public default administrator admin guest all".split()
)

# ── paths ───────────────────────────────────────────────────────────────────────────────────────────
_BLOCKED_BASENAME_GLOBS = (
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.jks",
    "id_rsa*",
    "id_dsa*",
    "id_ecdsa*",
    "id_ed25519*",
    "*.db",
    "*.sqlite*",
    "*.har",
    "cookies*",
    "*.tsbuildinfo",
)
_BLOCKED_BASENAMES = frozenset({".netrc", "_netrc", ".npmrc", "credentials.json", "token.json"})
_BLOCKED_DIRS = ("sessions", "persistent-state", ".next")


# The live policy files a snapshot may be a verbatim copy of (any past version, on the base ref).
POLICY_SOURCES = (
    "AGENTS.md",
    "AI_WORK_POLICY.md",
    "CLAUDE.md",
    "GEMINI.md",
    ".goosehints",
    ".github/copilot-instructions.md",
    ".cursor/rules/00-tradeai-work-policy.mdc",
    "docs/governance/",
)


def snapshot_candidate(path: str) -> bool:
    """A path under tests/fixtures/agents_pre_*/. Being here is NOT enough to be skipped; see SnapshotVerifier."""
    parts = PurePosixPath(path).parts
    return len(parts) > 3 and parts[0] == "tests" and parts[1] == "fixtures" and parts[2].startswith("agents_pre_")


class SnapshotVerifier:
    """Skip a snapshot candidate only when (1) its bytes are a verbatim past version of a POLICY_SOURCES file in
    the history of ``ref`` -- the git blob id of the bytes appears in ``git log --raw <ref> -- POLICY_SOURCES`` --
    and (2) its file name is the basename that blob had there, or that basename without a leading dot
    (".goosehints" is frozen as "goosehints"). So a copy of AGENTS.md must be named AGENTS.md."""

    def __init__(self, repo: Path, ref: str) -> None:
        self.repo, self.ref = repo, ref
        self.skipped = 0
        self._names: dict[str, frozenset[str]] | None = None
        self._algo = "sha1"

    def _load(self) -> dict[str, frozenset[str]]:
        """blob id -> the file names a snapshot of it may carry."""
        fmt = subprocess.run(["git", "rev-parse", "--show-object-format"], cwd=self.repo, capture_output=True)
        if fmt.returncode == 0 and fmt.stdout.strip():
            self._algo = fmt.stdout.decode().strip()
        raw = _git(
            self.repo, "log", "--format=", "--raw", "--no-abbrev", "--no-renames", self.ref, "--", *POLICY_SOURCES
        )
        names: dict[str, set[str]] = {}
        for line in raw.decode("utf-8", errors="replace").splitlines():
            if line.startswith(":") and "\t" in line:
                meta, path = line.split("\t", 1)
                base = PurePosixPath(path).name
                for b in meta.split()[2:4]:
                    if b.strip("0"):
                        names.setdefault(b, set()).update({base, base.lstrip(".")})
        return {b: frozenset(n) for b, n in names.items()}

    def blob_id(self, data: bytes) -> str:
        return hashlib.new(self._algo, b"blob %d\0" % len(data) + data).hexdigest()

    def skip(self, path: str, data: bytes) -> bool:
        if not snapshot_candidate(path):
            return False
        if self._names is None:
            self._names = self._load()
        if PurePosixPath(path).name in self._names.get(self.blob_id(data), ()):
            self.skipped += 1
            return True
        return False


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    category: str
    detail: str = ""  # blocked_path: the rule that matched. Never any part of a found value.


class ScanError(RuntimeError):
    """Git or configuration failure. Never a pass."""


def blocked_reason(path: str) -> str | None:
    p = PurePosixPath(path)
    name = p.name
    if name.startswith(".env") and name != ".env.example":
        return ".env file"
    if name in _BLOCKED_BASENAMES:
        return name
    for g in _BLOCKED_BASENAME_GLOBS:
        if fnmatch.fnmatchcase(name, g):
            return g
    if fnmatch.fnmatchcase(name, "holdings*.json"):
        return "**/holdings*.json"
    for d in p.parts[:-1]:
        if d in _BLOCKED_DIRS:
            return f"**/{d}/**"
    return None


def _email_allowed(local: str, domain: str, tld: str) -> bool:
    addr = f"{local}@{domain}".lower()
    dom = domain.lower()
    t = tld.lower()
    if t in FILE_TLDS or not (t in REAL_TLDS or len(t) == 2):
        return True
    if addr in ALLOWED_EMAILS or dom in ALLOWED_EMAIL_DOMAINS:
        return True
    if any(dom.endswith("." + d) for d in ALLOWED_EMAIL_DOMAINS):
        return True
    return dom.endswith(ALLOWED_EMAIL_SUFFIXES) or f".{dom}" in ALLOWED_EMAIL_SUFFIXES


def _real_date(s: str) -> bool:
    try:
        if "-" in s:
            y, m, d = (int(x) for x in s.split("-"))
        else:
            m, d, y = (int(x) for x in s.split("/"))
        dt = _dt.date(y, m, d)
    except ValueError:
        return False
    if (m, d) == (1, 1):  # 1990-01-01 style placeholders
        return False
    return 1900 <= dt.year <= _dt.date.today().year


def _private_ip(a: int, b: int, c: int, d: int) -> bool:
    if max(a, b, c, d) > 255:
        return False
    return a == 10 or (a == 172 and 16 <= b <= 31) or (a == 192 and b == 168) or (a == 100 and 64 <= b <= 127)


def load_deny_patterns(repo: Path, env: dict[str, str] | None = None) -> list[re.Pattern[str]]:
    env = os.environ if env is None else env
    raw = (env.get(DENY_ENV) or "").strip()
    if not raw:
        return []
    path = Path(raw).expanduser().resolve()
    try:
        path.relative_to(Path(repo).resolve())
    except ValueError:
        pass
    else:
        raise ScanError(f"{DENY_ENV} points inside the repository; the deny file must live outside it")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ScanError(f"{DENY_ENV} is set but unreadable: {type(exc).__name__}") from exc
    out = []
    for n, line in enumerate(lines, 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        try:
            out.append(re.compile(s, re.IGNORECASE))
        except re.error as exc:
            raise ScanError(f"{DENY_ENV} line {n}: invalid regex ({exc.msg})") from exc
    return out


def _account_numbers(text: str, low: str) -> list[tuple[int, str]]:
    """(position, digits) for ACCOUNT_RE matches. Keyword-anchored on the lowercased text, which is ~10x
    faster than ACCOUNT_RE over every digit; falls back to ACCOUNT_RE when lowercasing changed the length
    (a few non-ASCII characters do), so positions always refer to ``text``."""
    if len(low) != len(text):
        out = []
        for m in ACCOUNT_RE.finditer(text):
            g = 1 if m.group(1) else 2
            out.append((m.start(g), m.group(g)))
        return sorted(set(out))
    found: dict[int, str] = {}
    for kw in _ACCT_KW_RE.finditer(low):
        s = kw.start()
        fwd = _ACCT_FWD_RE.match(low, s) if s == 0 or low[s - 1] not in ASCII_ALNUM else None
        if fwd:
            found[fwd.start(1)] = text[fwd.start(1) : fwd.end(1)]
        if _ACCT_BACK_KW_RE.match(low, s):
            back = _ACCT_BACK_NUM_RE.search(low, max(0, s - 32), s)
            if back:
                found[back.start(1)] = text[back.start(1) : back.end(1)]
    return sorted(found.items())


def scan_text(path: str, text: str, deny: list[re.Pattern[str]], lines: set[int] | None = None) -> list[Finding]:
    """Findings in ``text``. With ``lines`` given, only matches on those 1-based line numbers count."""
    starts = [0]
    for m in re.finditer("\n", text):
        starts.append(m.end())
    out: list[Finding] = []

    def add(pos: int, category: str) -> None:
        ln = bisect.bisect_right(starts, pos)
        if lines is None or ln in lines:
            out.append(Finding(path, ln, category))

    if "@" in text:
        for m in EMAIL_RE.finditer(text):
            if not _email_allowed(m.group(1), m.group(2), m.group(3)):
                add(m.start(), "email")
    for pat in deny:
        for m in pat.finditer(text):
            if m.group(0):
                add(m.start(), "deny_pattern")
    low = text.lower()
    if "dob" in low or "birth" in low:
        for m in DOB_RE.finditer(text):
            if _real_date(m.group(1)):
                add(m.start(1), "date_of_birth")
    for pos, digits in _account_numbers(text, low):
        if sum(ch.isdigit() for ch in digits) >= 6 and not DATE_LIKE_RE.match(digits):
            add(pos, "account_number")
    for m in LETTER_ACCT_RE.finditer(text):
        add(m.start(1), "account_number")
    if "chat" in low:
        for m in CHAT_ID_RE.finditer(text):
            add(m.start(1), "telegram_chat_id")
    for m in IPV4_RE.finditer(text):
        if _private_ip(*(int(x) for x in m.groups())):
            add(m.start(), "private_ip")
    if "/home/" in text or "users" in low:
        for rx in HOME_RES:
            for m in rx.finditer(text):
                if m.group(1).lower() not in GENERIC_USERS:
                    add(m.start(), "home_path")
    return out


def count_markers(text: str, lines: set[int]) -> int:
    return sum(1 for n, ln in enumerate(text.split("\n"), 1) if n in lines and any(k in ln for k in ALLOW_MARKERS))


def _decode(data: bytes, path: str) -> str | None:
    if path.endswith(".gz"):
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as fh:
                data = fh.read(GZ_MAX_BYTES + 1)
        except (OSError, EOFError):
            return None
        if len(data) > GZ_MAX_BYTES:
            raise ScanError(f"{path}: decompresses past {GZ_MAX_BYTES} bytes; refusing to skip it silently")
    if b"\0" in data[:8192]:
        return None
    return data.decode("utf-8", errors="replace")


def _git(repo: Path, *args: str) -> bytes:
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True)
    if r.returncode != 0:
        raise ScanError(f"git {' '.join(args[:2])} failed: {r.stderr.decode(errors='replace').strip()[:300]}")
    return r.stdout


# ── modes ───────────────────────────────────────────────────────────────────────────────────────────
def scan_tree(repo: Path, deny: list[re.Pattern[str]], verifier: SnapshotVerifier | None = None) -> list[Finding]:
    verifier = verifier or SnapshotVerifier(repo, "HEAD")
    out: list[Finding] = []
    for entry in _git(repo, "ls-files", "-s", "-z").split(b"\0"):
        if not entry:
            continue
        meta, _, name_b = entry.partition(b"\t")
        path = name_b.decode("utf-8", errors="replace")
        reason = blocked_reason(path)
        if reason:
            out.append(Finding(path, 0, "blocked_path", reason))
        if meta.startswith(b"120000") or meta.startswith(b"160000"):
            continue  # symlink, submodule
        try:
            data = (repo / path).read_bytes()
        except OSError:
            continue
        if verifier.skip(path, data):
            continue  # verbatim past version of a live policy file (see SnapshotVerifier)
        text = _decode(data, path)
        if text:
            out.extend(scan_text(path, text, deny))
    return out


_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _target(rng: str) -> str:
    """The new side of a range, for reading added blobs (A..B, A...B, or a single rev meaning rev..HEAD)."""
    for sep in ("...", ".."):
        if sep in rng:
            return rng.split(sep, 1)[1] or "HEAD"
    return "HEAD"


def _base(rng: str) -> str:
    """The old side of a range (A..B, A...B, or a single rev meaning rev..HEAD): whose history vouches for snapshots."""
    for sep in ("...", ".."):
        if sep in rng:
            return rng.split(sep, 1)[0] or "HEAD"
    return rng


def scan_range(
    repo: Path, rng: str, deny: list[re.Pattern[str]], verifier: SnapshotVerifier | None = None
) -> tuple[list[Finding], int]:
    """(findings on added lines, number of added lines carrying an inline allow marker)."""
    verifier = verifier or SnapshotVerifier(repo, _base(rng))
    out: list[Finding] = []
    status_raw = _git(repo, "diff", "--name-status", "-z", "-M", "--diff-filter=ACMR", rng)
    parts = [p.decode("utf-8", errors="replace") for p in status_raw.split(b"\0") if p]
    i, statuses = 0, {}
    while i < len(parts):
        st = parts[i]
        if st[:1] in ("R", "C"):
            statuses[parts[i + 2]] = st[:1]
            i += 3
        else:
            statuses[parts[i + 1]] = st[:1]
            i += 2
    for path, st in sorted(statuses.items()):
        if st in ("A", "R", "C"):
            reason = blocked_reason(path)
            if reason:
                out.append(Finding(path, 0, "blocked_path", reason))

    added: dict[str, set[int]] = {}
    current = None
    diff = _git(repo, "diff", "--no-color", "--no-ext-diff", "-U0", "-M", "--diff-filter=ACMR", rng)
    for raw in diff.decode("utf-8", errors="replace").split("\n"):
        if raw.startswith("+++ "):
            current = raw[6:] if raw.startswith("+++ b/") else None
            if current is not None:
                added.setdefault(current, set())
            continue
        m = _HUNK_RE.match(raw)
        if m and current is not None:
            start, count = int(m.group(1)), int(m.group(2) if m.group(2) is not None else 1)
            added[current].update(range(start, start + count))

    target = _target(rng)
    markers = 0
    for path in sorted(statuses):
        lines = added.get(path)
        whole = path.endswith(".gz") and statuses[path] in ("A", "M", "R", "C")
        if not lines and not whole:
            continue
        r = subprocess.run(["git", "show", f"{target}:{path}"], cwd=repo, capture_output=True)
        if r.returncode != 0:
            raise ScanError(f"git show {target}:{path} failed")
        if verifier.skip(path, r.stdout):
            continue  # verbatim past version of a live policy file on the base ref (see SnapshotVerifier)
        text = _decode(r.stdout, path)
        if text:
            out.extend(scan_text(path, text, deny, None if whole else lines))
            if lines:
                markers += count_markers(text, lines)
    return out, markers


# ── baseline ────────────────────────────────────────────────────────────────────────────────────────
def counts(findings: list[Finding]) -> dict[str, int]:
    c = {k: 0 for k in RATCHETED}
    for f in findings:
        if f.category in c:
            c[f.category] += 1
    return c


def _parse_baseline(text: str, where: str) -> dict[str, int]:
    try:
        doc = json.loads(text)
    except ValueError as exc:
        raise ScanError(f"{where}: not JSON ({exc.msg})") from exc
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise ScanError(f"{where}: schema must be {SCHEMA!r}")
    got = doc.get("counts") or {}
    return {k: int(got.get(k, 0)) for k in RATCHETED}


def load_baseline(path: Path) -> dict[str, int]:
    if not path.is_file():
        raise ScanError(f"baseline missing: {path}")
    return _parse_baseline(path.read_text(encoding="utf-8"), str(path))


def compare(
    current: dict[str, int], baseline: dict[str, int]
) -> tuple[dict[str, tuple[int, int]], dict[str, tuple[int, int]]]:
    grew = {k: (baseline.get(k, 0), v) for k, v in current.items() if v > baseline.get(k, 0)}
    shrank = {k: (baseline.get(k, 0), v) for k, v in current.items() if v < baseline.get(k, 0)}
    return grew, shrank


def baseline_guard(repo: Path, ref: str, baseline_path: Path) -> tuple[dict[str, tuple[int, int]], str]:
    """Compare the working baseline file with ``ref``'s copy. Returns (raised categories, note)."""
    _git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    rel = baseline_path.resolve().relative_to(repo.resolve()).as_posix()
    r = subprocess.run(["git", "show", f"{ref}:{rel}"], cwd=repo, capture_output=True)
    if r.returncode != 0:
        return {}, f"{ref} has no {rel}: first introduction, nothing to compare"
    old = _parse_baseline(r.stdout.decode("utf-8", errors="replace"), f"{ref}:{rel}")
    new = load_baseline(baseline_path)
    raised = {k: (old[k], new[k]) for k in RATCHETED if new[k] > old[k]}
    return raised, f"compared {rel} with {ref}"


def write_baseline(path: Path, current: dict[str, int]) -> list[str]:
    """Write ``current``; refuse (return the categories) if any count would rise above the existing file."""
    if path.is_file():
        old = load_baseline(path)
        rising = sorted(k for k, v in current.items() if v > old.get(k, 0))
        if rising:
            return rising
    doc = {
        "schema": SCHEMA,
        "_note": (
            "Ratchet: findings per category already in the tree when scripts/check_no_pii.py landed. Counts only, "
            "never values or paths. May only shrink; --write-baseline refuses to raise a count and CI's "
            "--baseline-guard fails a pull request that raises one."
        ),
        "counts": {k: current[k] for k in RATCHETED},
    }
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return []


def _print(findings: list[Finding], limit: int) -> None:
    for f in findings[:limit]:
        loc = f"{f.path}:{f.line}" if f.line else f.path
        print(f"  {loc}  {f.category}" + (f"  ({f.detail})" if f.detail else ""))
    if len(findings) > limit:
        print(f"  ... {len(findings) - limit} more")


def _dump(doc: dict) -> None:
    print(json.dumps(doc, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Fail on personal or identifying data in the repository")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--range", dest="rng", help="git range, e.g. origin/main...HEAD; ADDED lines only")
    mode.add_argument("--tree", action="store_true", help="every tracked file, against the ratchet baseline")
    mode.add_argument("--baseline-guard", metavar="REF", help="fail if the baseline file raises a count vs REF")
    ap.add_argument("--repo", default=str(ROOT))
    ap.add_argument("--baseline", default=None, help=f"default: <repo>/{BASELINE_REL}")
    ap.add_argument("--write-baseline", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--verbose", action="store_true", help="--tree: list every finding (path:line, category)")
    args = ap.parse_args(argv)
    repo = Path(args.repo).resolve()
    baseline_path = Path(args.baseline) if args.baseline else repo / BASELINE_REL

    if args.baseline_guard:
        try:
            raised, note = baseline_guard(repo, args.baseline_guard, baseline_path)
        except ScanError as exc:
            print(f"check_no_pii: ERROR (fail closed): {exc}", file=sys.stderr)
            return 2
        if args.json:
            _dump({"mode": "baseline_guard", "ok": not raised, "raised": raised, "note": note})
        elif raised:
            print(f"check_no_pii: FAIL -- {BASELINE_REL} may only shrink ({note}):")
            for k, (old, new) in sorted(raised.items()):
                print(f"  {k:18} {old:>8} -> {new}")
        else:
            print(f"check_no_pii: OK -- no baseline count raised ({note})")
        return 1 if raised else 0

    markers = 0
    verifier = SnapshotVerifier(repo, _base(args.rng) if args.rng else "HEAD")
    try:
        deny = load_deny_patterns(repo)
        if args.rng:
            findings, markers = scan_range(repo, args.rng, deny, verifier)
        else:
            findings = scan_tree(repo, deny, verifier)
    except ScanError as exc:
        print(f"check_no_pii: ERROR (fail closed): {exc}", file=sys.stderr)
        return 2
    findings.sort(key=lambda f: (f.path, f.line, f.category))

    if args.rng:
        by_cat = {k: sum(1 for f in findings if f.category == k) for k in CATEGORIES}
        if args.json:
            _dump(
                {
                    "mode": "range",
                    "range": args.rng,
                    "ok": not findings,
                    "counts": by_cat,
                    "allow_markers_added": markers,
                    "snapshot_files_skipped": verifier.skipped,
                    "findings": [asdict(f) for f in findings],
                }
            )
            return 1 if findings else 0
        if verifier.skipped:
            print(
                f"check_no_pii: {verifier.skipped} policy snapshot file(s) skipped: byte-identical to a past version "
                f"of a live policy file on {verifier.ref}"
            )
        if findings:
            print(f"check_no_pii: {len(findings)} new finding(s) in {args.rng} (values never printed):")
            _print(findings, args.limit)
            print(
                "Remove the data or move it to a config source outside git. For a synthetic test value, assemble "
                "it at runtime; no inline marker silences a finding."
            )
        else:
            print(f"check_no_pii: OK -- no personal or identifying data added in {args.rng}")
        if markers:
            print(f"check_no_pii: NOTE -- {markers} added line(s) carry an inline allow marker; none is honoured.")
        return 1 if findings else 0

    current = counts(findings)
    deny_n = sum(1 for f in findings if f.category == "deny_pattern")
    if args.write_baseline:
        rising = write_baseline(baseline_path, current)
        if rising:
            print(f"check_no_pii: REFUSED -- baseline may only shrink; would raise {rising}", file=sys.stderr)
            return 1
        print(f"check_no_pii: wrote {baseline_path.name}: {json.dumps(current, sort_keys=True)}")
        return 0
    try:
        base = load_baseline(baseline_path)
    except ScanError as exc:
        print(f"check_no_pii: ERROR (fail closed): {exc}", file=sys.stderr)
        return 2
    grew, shrank = compare(current, base)
    if args.json:
        _dump(
            {
                "mode": "tree",
                "ok": not grew,
                "counts": current,
                "baseline": base,
                "grew": grew,
                "shrank": shrank,
                "deny_pattern_advisory": deny_n,
                "snapshot_files_skipped": verifier.skipped,
            }
        )
        return 1 if grew else 0
    print("check_no_pii --tree (counts per category; values never printed)")
    print(f"  {'category':18} {'baseline':>8} {'now':>6}")
    for k in RATCHETED:
        flag = "  GREW" if k in grew else ("  shrank" if k in shrank else "")
        print(f"  {k:18} {base[k]:>8} {current[k]:>6}{flag}")
    if deny_n or deny:
        print(f"  {'deny_pattern':18} {'n/a':>8} {deny_n:>6}  (advisory; private deny file, not ratcheted)")
    if verifier.skipped:
        print(f"  {verifier.skipped} policy snapshot file(s) skipped: byte-identical to a past policy file on HEAD")
    if args.verbose:
        _print(findings, args.limit)
    if grew:
        print(
            "FAIL: the tree gained personal or identifying data. Run --range origin/main...HEAD to see the new lines."
        )
        _print([f for f in findings if f.category in grew], min(args.limit, 50))
        return 1
    if shrank:
        print(f"OK, and {sorted(shrank)} shrank: lower the baseline with --tree --write-baseline in this PR.")
    else:
        print("OK: no category grew.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
