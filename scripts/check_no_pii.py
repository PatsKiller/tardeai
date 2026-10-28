#!/usr/bin/env python3
"""check_no_pii.py -- no personal or identifying data in the repository.

Operator request, 2026-10-27, verbatim: "would need some validates or checks that I don't have any type of
secrets or codes or anything identifiable in the codes and GitHub that should also be in the agents.md".
Credentials are gitleaks' job (.gitleaks.toml, .github/workflows/secret-scan.yml) and
scripts/check_no_secrets.py's. This script covers what those do not look for: data that identifies a
person, an account or a machine.

    python3 scripts/check_no_pii.py --range origin/main...HEAD   # ADDED lines only; any finding fails
    python3 scripts/check_no_pii.py --tree                       # whole tree vs the ratchet baseline
    python3 scripts/check_no_pii.py --tree --write-baseline      # after REMOVING findings only

CATEGORIES
  email             an email address outside the example allow-list (example.com/.org/.net, *.example,
                    *.test, *.invalid, noreply@anthropic.com, *.users.noreply.github.com, git@ remotes)
  deny_pattern      a pattern from the operator's private deny file (TRADEAI_PII_DENY_FILE; see below)
  date_of_birth     dob / date_of_birth / birth_date with a real-looking date
  account_number    a run of 6+ digits next to account / acct / IRA / routing
  telegram_chat_id  a numeric Telegram chat id next to chat_id
  private_ip        an RFC1918 or Tailscale (CGNAT 100.64.0.0/10) host address; CIDR ranges are not hosts
  home_path         an absolute /home/<user>/ path for a non-generic user
  blocked_path      a file that must never be committed: .env* (not .env.example), *.pem, *.key, *.p12,
                    *.db, *.sqlite*, *.har, cookies*, **/sessions/**, **/persistent-state/**, **/.next/**,
                    *.tsbuildinfo, **/holdings*.json. In --range mode it fails only when the file is ADDED.

RATCHET. The tree already holds findings committed before this check existed. config/pii_baseline.json
records their COUNT per category (no values, no paths). --tree fails if any category grows; a category that
shrank is reported so the baseline can be lowered. --write-baseline refuses to raise a count: raising one is
a hand edit in a reviewed PR. --range has no baseline: new lines must be clean.

PRIVATE DENY FILE. The operator's real names, domains and handles must not be written into this repository,
not even as a deny list. Put one case-insensitive regex per line in a file OUTSIDE the repository and point
TRADEAI_PII_DENY_FILE at it (CI writes it from an Actions secret). A deny file inside the repository is
refused. Deny findings fail --range; in --tree they are reported but not ratcheted, because the count depends
on a file CI and the host may hold differently.

ESCAPE HATCH. A line carrying the marker ``pii-ok`` is skipped for the content categories (not for
deny_pattern, not for blocked_path). It is per line and visible in review, like check_no_secrets.py's
``# hardcode-ok``. There are no directory exemptions: tests/ and docs/ are scanned like everything else.
.gz files are decompressed and scanned.

OUTPUT never prints a found value: first 3 characters plus the length, with path:line and category.
Exit 0 clean, 1 findings (or a ratchet grew), 2 usage or git error (fail closed).
Stdlib only. AUTHORITY: READ_ONLY_ADVISORY (CI tooling; no broker, no Telegram, no DB, no network).
"""

from __future__ import annotations

import argparse
import bisect
import datetime as _dt
import fnmatch
import gzip
import io
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
BASELINE_REL = "config/pii_baseline.json"
SCHEMA = "PiiBaseline@v1"
DENY_ENV = "TRADEAI_PII_DENY_FILE"
MARKER = "pii-ok"
GZ_MAX_BYTES = 64 * 1024 * 1024

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
UNMARKABLE = frozenset({"deny_pattern", "blocked_path"})

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
DOB_RE = re.compile(
    r"(?i)\b(?:dob|date[_-]?of[_-]?birth|birth[_-]?date)\b[\"']?\s*[:=]\s*[\"']?"
    r"(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})"
)
# The keyword may carry a number label (account_number, acct_no, routing#) but not other words, so
# ids like ROUTING_DECISION_20261027 or ACCOUNT_LABELS_20261023 are not account numbers.
ACCOUNT_RE = re.compile(
    r"(?i)(?:\b(?:account|acct|ira|routing)(?:[_ -]?(?:no|num|number|id|#))?s?(?![A-Za-z0-9])"
    r"[\s\"'#:=]{0,6}(\d[\d-]{4,}\d)(?![\w-])"
    r"|(?<![\w-])(\d{6,})[\s\"'#:,]{0,3}(?:account|acct|ira)\b)"
)
# Fast path (same semantics, run on the lowercased text): find the keyword, then match around it.
_ACCT_KW_RE = re.compile(r"account|acct|ira|routing")
_ACCT_FWD_RE = re.compile(
    r"(?:account|acct|ira|routing)(?:[_ -]?(?:no|num|number|id|#))?s?(?![a-z0-9])[\s\"'#:=]{0,6}(\d[\d-]{4,}\d)(?![\w-])"
)
_ACCT_BACK_KW_RE = re.compile(r"(?:account|acct|ira)\b")
_ACCT_BACK_NUM_RE = re.compile(r"(?<![\w-])(\d{6,})[\s\"'#:,]{0,3}$")
DATE_LIKE_RE = re.compile(r"^(?:19|20)\d{2}-?(?:0[1-9]|1[0-2])-?(?:0[1-9]|[12]\d|3[01])(?:\d{4,6})?$")
CHAT_ID_RE = re.compile(r"(?i)\bchat[_-]?id\b[\"']?\s*(?:==|[:=])\s*[\"']?(-?\d{6,})(?!\d)")
IPV4_RE = re.compile(r"(?<![\d.])(10|172|192|100)\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?!\d|\.\d|/\d)")
HOME_RE = re.compile(r"/home/([A-Za-z0-9._-]+)/")
GENERIC_USERS = frozenset(
    "user username runner ubuntu you me example someone alice bob ci test tester dev app node nobody "
    "claude your-user youruser your_user".split()
)

# ── blocked paths ───────────────────────────────────────────────────────────────────────────────────
_BLOCKED_BASENAME_GLOBS = ("*.pem", "*.key", "*.p12", "*.db", "*.sqlite*", "*.har", "cookies*", "*.tsbuildinfo")
_BLOCKED_DIRS = ("sessions", "persistent-state", ".next")


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    category: str
    masked: str


class ScanError(RuntimeError):
    """Git or configuration failure. Never a pass."""


def mask(value: str) -> str:
    return f"{value[:3]}…(len={len(value)})"


def blocked_reason(path: str) -> str | None:
    p = PurePosixPath(path)
    name = p.name
    if name.startswith(".env") and name != ".env.example":
        return ".env file"
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
        return out
    found: dict[int, str] = {}
    for kw in _ACCT_KW_RE.finditer(low):
        s = kw.start()
        fwd = _ACCT_FWD_RE.match(low, s) if s == 0 or not (low[s - 1].isalnum() or low[s - 1] == "_") else None
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
    raw_lines = text.split("\n")

    def where(pos: int) -> int:
        return bisect.bisect_right(starts, pos)

    out: list[Finding] = []

    def add(pos: int, category: str, value: str) -> None:
        ln = where(pos)
        if lines is not None and ln not in lines:
            return
        if category not in UNMARKABLE and MARKER in raw_lines[ln - 1]:
            return
        out.append(Finding(path, ln, category, mask(value)))

    if "@" in text:
        for m in EMAIL_RE.finditer(text):
            if not _email_allowed(m.group(1), m.group(2), m.group(3)):
                add(m.start(), "email", m.group(0))
    for pat in deny:
        for m in pat.finditer(text):
            if m.group(0):
                add(m.start(), "deny_pattern", m.group(0))
    low = text.lower()
    if "dob" in low or "birth" in low:
        for m in DOB_RE.finditer(text):
            if _real_date(m.group(1)):
                add(m.start(1), "date_of_birth", m.group(1))
    for pos, digits in _account_numbers(text, low):
        if sum(ch.isdigit() for ch in digits) >= 6 and not DATE_LIKE_RE.match(digits):
            add(pos, "account_number", digits)
    if "chat" in low:
        for m in CHAT_ID_RE.finditer(text):
            add(m.start(1), "telegram_chat_id", m.group(1))
    for m in IPV4_RE.finditer(text):
        if _private_ip(*(int(x) for x in m.groups())):
            add(m.start(), "private_ip", m.group(0))
    if "/home/" in text:
        for m in HOME_RE.finditer(text):
            if m.group(1).lower() not in GENERIC_USERS and not m.group(1).startswith("$"):
                add(m.start(), "home_path", m.group(0))
    return out


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
def scan_tree(repo: Path, deny: list[re.Pattern[str]]) -> list[Finding]:
    out: list[Finding] = []
    for entry in _git(repo, "ls-files", "-s", "-z").split(b"\0"):
        if not entry:
            continue
        meta, _, name_b = entry.partition(b"\t")
        path = name_b.decode("utf-8", errors="replace")
        reason = blocked_reason(path)
        if reason:
            out.append(Finding(path, 0, "blocked_path", reason))
        if meta.startswith(b"120000") or meta.startswith(b"160000"):  # symlink, submodule
            continue
        try:
            data = (repo / path).read_bytes()
        except OSError:
            continue
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


def scan_range(repo: Path, rng: str, deny: list[re.Pattern[str]]) -> list[Finding]:
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
    for path in sorted(statuses):
        lines = added.get(path)
        whole = path.endswith(".gz") and statuses[path] in ("A", "M", "R", "C")
        if not lines and not whole:
            continue
        r = subprocess.run(["git", "show", f"{target}:{path}"], cwd=repo, capture_output=True)
        if r.returncode != 0:
            raise ScanError(f"git show {target}:{path} failed")
        text = _decode(r.stdout, path)
        if text:
            out.extend(scan_text(path, text, deny, None if whole else lines))
    return out


# ── baseline ────────────────────────────────────────────────────────────────────────────────────────
def counts(findings: list[Finding]) -> dict[str, int]:
    c = {k: 0 for k in RATCHETED}
    for f in findings:
        if f.category in c:
            c[f.category] += 1
    return c


def load_baseline(path: Path) -> dict[str, int]:
    if not path.is_file():
        raise ScanError(f"baseline missing: {path}")
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("schema") != SCHEMA:
        raise ScanError(f"{path}: schema must be {SCHEMA!r}")
    got = doc.get("counts") or {}
    return {k: int(got.get(k, 0)) for k in RATCHETED}


def compare(
    current: dict[str, int], baseline: dict[str, int]
) -> tuple[dict[str, tuple[int, int]], dict[str, tuple[int, int]]]:
    grew = {k: (baseline.get(k, 0), v) for k, v in current.items() if v > baseline.get(k, 0)}
    shrank = {k: (baseline.get(k, 0), v) for k, v in current.items() if v < baseline.get(k, 0)}
    return grew, shrank


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
            "never values or paths. May only shrink; --write-baseline refuses to raise a count."
        ),
        "counts": {k: current[k] for k in RATCHETED},
    }
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return []


def _print(findings: list[Finding], limit: int) -> None:
    for f in findings[:limit]:
        loc = f"{f.path}:{f.line}" if f.line else f.path
        print(f"  {loc}  {f.category}  {f.masked}")
    if len(findings) > limit:
        print(f"  ... {len(findings) - limit} more")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Fail on personal or identifying data in the repository")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--range", dest="rng", help="git range, e.g. origin/main...HEAD; ADDED lines only")
    mode.add_argument("--tree", action="store_true", help="every tracked file, against the ratchet baseline")
    ap.add_argument("--repo", default=str(ROOT))
    ap.add_argument("--baseline", default=None, help=f"default: <repo>/{BASELINE_REL}")
    ap.add_argument("--write-baseline", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--verbose", action="store_true", help="--tree: list every finding (masked)")
    args = ap.parse_args(argv)
    repo = Path(args.repo).resolve()
    baseline_path = Path(args.baseline) if args.baseline else repo / BASELINE_REL

    try:
        deny = load_deny_patterns(repo)
        findings = scan_range(repo, args.rng, deny) if args.rng else scan_tree(repo, deny)
    except ScanError as exc:
        print(f"check_no_pii: ERROR (fail closed): {exc}", file=sys.stderr)
        return 2
    findings.sort(key=lambda f: (f.path, f.line, f.category))

    if args.rng:
        by_cat = {k: sum(1 for f in findings if f.category == k) for k in CATEGORIES}
        if args.json:
            print(
                json.dumps(
                    {
                        "mode": "range",
                        "range": args.rng,
                        "ok": not findings,
                        "counts": by_cat,
                        "findings": [asdict(f) for f in findings],
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        elif findings:
            print(f"check_no_pii: {len(findings)} new finding(s) in {args.rng} (values masked):")
            _print(findings, args.limit)
            print(
                "Remove the data, move it to a config source outside git, or mark a deliberate synthetic "
                f"fixture line with '{MARKER}'."
            )
        else:
            print(f"check_no_pii: OK -- no personal or identifying data added in {args.rng}")
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
    except (ScanError, ValueError) as exc:
        print(f"check_no_pii: ERROR (fail closed): {exc}", file=sys.stderr)
        return 2
    grew, shrank = compare(current, base)
    if args.json:
        print(
            json.dumps(
                {
                    "mode": "tree",
                    "ok": not grew,
                    "counts": current,
                    "baseline": base,
                    "grew": grew,
                    "shrank": shrank,
                    "deny_pattern_advisory": deny_n,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1 if grew else 0
    print("check_no_pii --tree (counts per category; values never printed)")
    print(f"  {'category':18} {'baseline':>8} {'now':>6}")
    for k in RATCHETED:
        flag = "  GREW" if k in grew else ("  shrank" if k in shrank else "")
        print(f"  {k:18} {base[k]:>8} {current[k]:>6}{flag}")
    if deny_n or deny:
        print(f"  {'deny_pattern':18} {'n/a':>8} {deny_n:>6}  (advisory; private deny file, not ratcheted)")
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
