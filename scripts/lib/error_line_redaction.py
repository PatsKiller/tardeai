"""Strict redaction for one error line shown on an operator page.

2026-10-31: the Jobs page began quoting the last exception line of a job's own log. An exception
line can carry a URL with an API key in its query string, a Telegram bot token in the path, a DSN
with a password, a refresh token in ``key: value`` form or a secrets-file path. The cron-command
redactor (``scheduler_operations.redact_command``) only knows ``NAME=value`` shell pairs, so all of
those reached the page. Patterns follow ``maturity_control/redaction.py`` and go wider.

Pure function, no I/O. Over-redaction is the accepted failure mode.
"""
from __future__ import annotations

import re
from pathlib import Path

R = "[REDACTED]"

_SECRETS_PATH = re.compile(r"(?:~|/home/[^/\s'\"]+|/root)/\.config/tradeai/secrets/[^\s'\"]*")
_HOME_PATH = re.compile(r"/home/[^/\s'\"]+")
_TELEGRAM_PATH = re.compile(r"/bot\d+:[A-Za-z0-9_\-]+")
_URL_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^\s/@'\"]+@")
_URL_QUERY = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://[^\s?#'\"]+)\?[^\s#'\"]*")
_TOKEN_SHAPES = re.compile(
    r"(?:"
    r"\bsk-[A-Za-z0-9_\-]{8,}"
    r"|\bxox[abposr]-[A-Za-z0-9\-]{8,}"
    r"|\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{8,}"
    r"|\bgithub_pat_[A-Za-z0-9_]{8,}"
    r"|\bAIza[A-Za-z0-9_\-]{8,}"
    r"|\bAKIA[0-9A-Z]{12,}"
    r"|\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}(?:\.[A-Za-z0-9_\-]+)?"
    r"|\b\d{6,12}:AA[A-Za-z0-9_\-]{6,}"
    r")"
)
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=\-]{6,}")
_SECRET_KEY_WORD = re.compile(
    r"(?i)(token|secret|passw(?:or)?d|pwd|api[_\-]?key|apikey|auth(?:orization)?(?![a-z])|credential|private[_\-]?key|"
    r"session|cookie|dsn|access[_\-]?key|signature|sig\b)"
)
_KEY_VALUE = re.compile(r"""(?P<key>["']?[A-Za-z_][\w.\-]*["']?)(?P<sep>\s*[:=]\s*)(?P<q>["']?)(?P<val>[^\s"',;)}\]]+)""")
_NOT_A_KEY = re.compile(r"(?:Error|Exception|Warning|Exit|Interrupt)$")


def _redact_pairs(text: str) -> str:
    """Redact the value of every ``key: value`` / ``key=value`` pair whose key looks secret.

    A non-secret pair consumes only its key, so ``failed: refresh_token: abc`` still finds
    ``refresh_token: abc``.
    """
    out, pos = [], 0
    while True:
        match = _KEY_VALUE.search(text, pos)
        if not match:
            out.append(text[pos:])
            return "".join(out)
        key = match.group("key").strip("\"'")
        secret = not _NOT_A_KEY.search(key) and _SECRET_KEY_WORD.search(key) and R[:-1] not in match.group("val")
        if secret:
            out.append(text[pos:match.start("val")] + R)
            pos = match.end("val")
        else:
            out.append(text[pos:match.end("sep")])
            pos = match.end("sep")


def redact_error_line(text: str, *, home: str | None = None) -> str:
    """Return ``text`` with credentials, tokens, query strings and home paths removed."""
    if not text:
        return text
    out = str(text)
    out = _SECRETS_PATH.sub("~/.config/tradeai/secrets/" + R, out)
    out = _TELEGRAM_PATH.sub("/bot" + R, out)
    out = _URL_USERINFO.sub(r"\1" + R + "@", out)
    out = _URL_QUERY.sub(r"\1?" + R, out)
    out = _BEARER.sub(lambda m: f"{m.group(1)} {R}", out)
    out = _TOKEN_SHAPES.sub(R, out)
    out = _redact_pairs(out)
    home = home if home is not None else str(Path.home())
    if home and home != "/":
        out = out.replace(home, "~")
    out = _HOME_PATH.sub("~", out)
    return out
