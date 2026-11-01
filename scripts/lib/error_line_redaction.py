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
from urllib.parse import unquote

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
    r"|\b(?:AKIA|ASIA|AGPA|AIDA|AROA|AIPA|ANPA|ANVA|APKA)[0-9A-Z]{12,}"
    r"|\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}(?:\.[A-Za-z0-9_\-]+)?"
    r"|\b\d{6,12}:AA[A-Za-z0-9_\-]{6,}"
    r")"
)
_BEARER = re.compile(r"(?i)\b(bearer|basic|token)\s+[A-Za-z0-9._~+/=\-]{6,}")
#: 2026-11-01 (review round 2): the whole value of an Authorization header, whatever its scheme
#: ("Token <v>", "Bearer <v>", "Basic <v>", a bare value), up to the closing quote or the line end.
_AUTH_HEADER = re.compile(r"""(?i)\b((?:proxy-)?authorization["']?\s*[:=]\s*["']?)[^"'\n,;}]+""")
#: High-entropy runs: a bare secret has no key word to anchor on. Base64-alphabet runs of >= 20 that mix
#: upper case, lower case and digits, and hex runs of >= 20 that mix digits and letters. Ordinary words,
#: identifiers (underscores split them) and lower-case paths never have all three classes.
_B64_RUN = re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{20,}={0,2}(?![A-Za-z0-9+/=])")
_HEX_RUN = re.compile(r"(?<![0-9A-Za-z])[0-9a-fA-F]{20,}(?![0-9A-Za-z])")
_SECRET_KEY_WORD = re.compile(
    r"(?i)(token|secret|passw(?:or)?d|pwd|api[_\-]?key|apikey|auth(?:orization)?(?![a-z])|credential|private[_\-]?key|"
    r"session|cookie|dsn|access[_\-]?key|signature|sig\b|key|client[_\-]?id|app[_\-]?key|key[_\-]?id)"
)
#: A quoted value runs to its closing quote (it may hold spaces); an unquoted one stops at a delimiter.
_KEY_VALUE = re.compile(
    r"""(?P<key>["']?[A-Za-z_][\w.\-]*["']?)(?P<sep>\s*[:=]\s*)"""
    r"""(?:(?P<q>["'])(?P<qval>[^"'\n]*)|(?P<val>[^\s"',;)}\]&]+))"""
)
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
        group = "qval" if match.group("q") else "val"
        value = match.group(group) or ""
        secret = not _NOT_A_KEY.search(key) and _SECRET_KEY_WORD.search(key) and value and R[:-1] not in value
        if secret:
            out.append(text[pos:match.start(group)] + R)
            pos = match.end(group)
        else:
            out.append(text[pos:match.end("sep")])
            pos = match.end("sep")


def _mixed(run: str) -> bool:
    return any(c.islower() for c in run) and any(c.isupper() for c in run) and any(c.isdigit() for c in run)


def _high_entropy(match: re.Match) -> str:
    """Redact a mixed-class base64 run. A run with '/' (a URL path) loses only its qualifying segments,
    so ``wss://host/ws/<token>`` keeps its host and path; a secret whose '/'-separated pieces are each
    short (an AWS secret key) is redacted whole."""
    run = match.group(0)
    if "/" in run:
        parts = run.split("/")
        if any(len(part) >= 20 and _mixed(part) for part in parts):
            return "/".join(R if len(part) >= 20 and _mixed(part) else part for part in parts)
    return R if _mixed(run) else run


def _hex_secret(match: re.Match) -> str:
    run = match.group(0)
    return R if any(c.isdigit() for c in run) and any(c.isalpha() for c in run) else run


def _percent_decode(text: str) -> str:
    """Decode %XX escapes (twice, for double-encoded bodies) so encoded keys and values are matched."""
    for _ in range(2):
        if "%" not in text:
            break
        decoded = unquote(text)
        if decoded == text:
            break
        text = decoded
    return text


def redact_error_line(text: str, *, home: str | None = None) -> str:
    """Return ``text`` with credentials, tokens, query strings and home paths removed."""
    if not text:
        return text
    out = _percent_decode(str(text))
    out = _SECRETS_PATH.sub("~/.config/tradeai/secrets/" + R, out)
    out = _TELEGRAM_PATH.sub("/bot" + R, out)
    out = _URL_USERINFO.sub(r"\1" + R + "@", out)
    out = _URL_QUERY.sub(r"\1?" + R, out)
    out = _AUTH_HEADER.sub(lambda m: m.group(1) + R, out)
    out = _BEARER.sub(lambda m: f"{m.group(1)} {R}", out)
    out = _TOKEN_SHAPES.sub(R, out)
    out = _redact_pairs(out)
    out = _B64_RUN.sub(_high_entropy, out)
    out = _HEX_RUN.sub(_hex_secret, out)
    home = home if home is not None else str(Path.home())
    if home and home != "/":
        out = out.replace(home, "~")
    out = _HOME_PATH.sub("~", out)
    return out
