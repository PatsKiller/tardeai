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
# Phase-0 2026-07-21: refuse backup sprawl — historical keys must never re-enter git or linger staged
ENV_BAK_FILE_RE = re.compile(
    r"(^|/)\.env\.bak|"
    r"(^|/)\.env\.backup|"
    r"\.env\.bak[-_.]|"
    r"\.env\.old|"
    r"\.env\.alert.*\.bak|"
    r"(^|/)dot_env$"
)
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


# ── HARD RULE: no hardcoded values — chat IDs + broker-name fallbacks (use a config source) ──
CHAT_ID_KEYS = ("TRADEAI_PROPOSAL_ALERT_CHAT_ID", "TELEGRAM_CHAT_ID")
# a broker name used as a FALLBACK/DEFAULT at end of expression: or "alpaca_paper"  /  or 'schwab_x')
# (excludes membership tests like  or "fidelity" in source  by requiring an expression terminator)
BROKER_FALLBACK_RE = re.compile(
    r"""\bor\s+(['"])(alpaca|schwab|fidelity|tos|etrade|ibkr|tradier)[a-z0-9_]*\1\s*(?:\)|,|;|\]|$)""", re.I)


def _chat_id_values():
    vals = set()
    env = ROOT / ".env"
    if env.exists():
        for l in env.read_text().splitlines():
            if "=" in l and not l.lstrip().startswith("#"):
                k, _, v = l.partition("=")
                if k.strip() in CHAT_ID_KEYS:
                    for c in v.strip().strip('"').strip("'").split(","):
                        c = c.strip()
                        if re.fullmatch(r"-?\d{5,}", c):
                            vals.add(c)
    return sorted(vals)


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
    chat_vals = _chat_id_values()
    secrets, hardcodes = [], []
    for f in files:
        if ALLOW_FILE_RE.search(f):
            continue
        if ENV_BAK_FILE_RE.search(f):
            secrets.append((f, "env BACKUP file (*.env.bak* / *.env.old* / dot_env) must never be committed — shred, do not stage"))
            continue
        if SECRET_FILE_RE.search(f):
            secrets.append((f, "secret FILE must never be committed"))
            continue
        txt = _content(f, staged)
        if not txt:
            continue
        for pat, label in PATTERNS:
            if pat.search(txt):
                secrets.append((f, f"{label} pattern"))
        for k, v in env_vals:
            if v in txt:
                secrets.append((f, f"value of {k} from .env"))
        # no-hardcoded-values (chat IDs + broker fallbacks) — .py only, line-aware, '# hardcode-ok' opt-out
        if f.endswith(".py") and "tg_chat_ids.py" not in f:
            for cv in chat_vals:
                if cv in txt:
                    hardcodes.append((f, f"hardcoded chat ID {cv} — use tg_chat_ids.chat_ids()"))
            for i, line in enumerate(txt.splitlines(), 1):
                if "# hardcode-ok" in line or line.lstrip().startswith("#"):
                    continue
                if BROKER_FALLBACK_RE.search(line):
                    hardcodes.append((f, f"hardcoded broker fallback (line {i}) — derive from the record's account/config, or add '# hardcode-ok' if intentional"))
    if secrets:
        print("\n  ✋ BLOCKED — credentials must never reach git (hard rule):", file=sys.stderr)
        for f, why in secrets:
            print(f"     • {f}: {why}", file=sys.stderr)
        print("  Put it in .env (gitignored) and reference via os.environ.", file=sys.stderr)
    if hardcodes:
        print("\n  ✋ BLOCKED — no hardcoded values (hard rule: config comes from a source):", file=sys.stderr)
        for f, why in hardcodes:
            print(f"     • {f}: {why}", file=sys.stderr)
        print("  Chat IDs -> tg_chat_ids.chat_ids(); broker/account -> the record's own account / env / DB.\n", file=sys.stderr)
    if secrets or hardcodes:
        sys.exit(1)
    print(f"  ✓ no secrets or hardcoded values in {'staged change' if staged else 'tree'} ({len(files)} files scanned)")
    sys.exit(0)


if __name__ == "__main__":
    main()
