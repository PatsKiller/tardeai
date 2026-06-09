#!/usr/bin/env python3
"""check_no_secrets.py — HARD RULE enforcement: no credentials hardcoded anywhere, ever synced to git.

Used as a git pre-commit/pre-push hook (and runnable manually). Blocks (exit 1) if the staged change —
or the whole tree with --tree — contains an API-key pattern, a secret FILE, or any actual value from
.env. This makes "no secret reaches git" automatic, not a hope.

  python3 scripts/check_no_secrets.py            # scan staged changes (pre-commit)
  python3 scripts/check_no_secrets.py --tree     # scan all tracked files
"""
from __future__ import annotations
import re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# live-secret patterns (avoid matching docs that describe the shape — require real-length payloads)
PATTERNS = [
    (re.compile(r"sk-ant-api03-[A-Za-z0-9_\-]{30,}"), "Anthropic API key"),
    (re.compile(r"sk-(proj-)?[A-Za-z0-9]{40,}"), "OpenAI API key"),
    (re.compile(r"xai-[A-Za-z0-9]{40,}"), "xAI API key"),
    (re.compile(r"AKIA[A-Z0-9]{16}"), "AWS access key"),
    (re.compile(r"ghp_[A-Za-z0-9]{36}"), "GitHub token"),
    (re.compile(r"xoxb-[A-Za-z0-9\-]{20,}"), "Slack token"),
    (re.compile(r"-----BEGIN (RSA |OPENSSH |EC |DSA |)PRIVATE KEY-----"), "private key"),
]
# files that must NEVER be committed
SECRET_FILE_RE = re.compile(r"(^|/)\.env(\.[^x]|$)|(^|/)\.env$|\.key$|\.pem$|broker_credentials\.env|"
                            r"secrets_admin_audit\.jsonl|gog_keyring_password|/credentials/")
ALLOW_FILE_RE = re.compile(r"\.env\.example$|check_no_secrets\.py$")  # the scanner itself names patterns


def _env_values():
    vals = []
    env = ROOT / ".env"
    if env.exists():
        for l in env.read_text().splitlines():
            if "=" in l and not l.lstrip().startswith("#"):
                k, _, v = l.partition("=")
                v = v.strip().strip('"').strip("'")
                if k.strip().endswith(("_KEY", "_TOKEN", "_SECRET", "_PASSWORD", "_PASSWD")) and len(v) >= 12:
                    vals.append((k.strip(), v))
    return vals


def _staged_files():
    out = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
                         cwd=ROOT, capture_output=True, text=True).stdout
    return [f for f in out.splitlines() if f.strip()]


def _tree_files():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout
    return [f for f in out.splitlines() if f.strip()]


def _content(f, staged):
    try:
        if staged:
            return subprocess.run(["git", "show", f":{f}"], cwd=ROOT, capture_output=True, text=True).stdout
        return (ROOT / f).read_text(errors="ignore")
    except Exception:
        return ""


def main():
    staged = "--tree" not in sys.argv
    files = _staged_files() if staged else _tree_files()
    env_vals = _env_values()
    violations = []
    for f in files:
        if ALLOW_FILE_RE.search(f):
            continue
        if SECRET_FILE_RE.search(f):
            violations.append((f, "secret FILE must never be committed"))
            continue
        txt = _content(f, staged)
        if not txt:
            continue
        for pat, label in PATTERNS:
            if pat.search(txt):
                violations.append((f, f"{label} pattern"))
        for k, v in env_vals:
            if v in txt:
                violations.append((f, f"value of {k} from .env"))
    if violations:
        print("\n  ✋ COMMIT BLOCKED — credentials must never reach git (hard rule):", file=sys.stderr)
        for f, why in violations:
            print(f"     • {f}: {why}", file=sys.stderr)
        print("  Remove the secret, put it in .env (gitignored), and reference it via os.environ.\n", file=sys.stderr)
        sys.exit(1)
    print(f"  ✓ no secrets in {'staged change' if staged else 'tree'} ({len(files)} files scanned)")
    sys.exit(0)


if __name__ == "__main__":
    main()
