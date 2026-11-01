"""Strict redaction for one error line shown on an operator page.

2026-10-31: the Jobs page began quoting the last exception line of a job's own log. An exception
line can carry a URL with an API key in its query string, a Telegram bot token in the path, a DSN
with a password, a refresh token in ``key: value`` form or a secrets-file path. The cron-command
redactor (``scheduler_operations.redact_command``) only knows ``NAME=value`` shell pairs, so all of
those reached the page. Patterns follow ``maturity_control/redaction.py`` and go wider.

Pure function, no I/O. Over-redaction is the accepted failure mode.

Deliberate choices (review round 3, 2026-11-01):
* Hex and alphanumeric runs of 20+ characters that mix letters and digits are redacted, git SHAs
  included. A 40-hex SHA is indistinguishable from a hex API key (Finnhub, Polygon, signatures), and a
  page line loses little without it; short SHAs (7-12 characters) stay readable.
* A bare UUID is redacted (the Finviz token shape), run ids that are UUIDs included.
* Runs are bounded and every pattern is anchored so the whole pass is linear in the line length.
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

R = "[REDACTED]"

_SECRETS_PATH = re.compile(r"(?:~|/home/[^/\s'\"]+|/root)/\.config/tradeai/secrets/[^\s'\"]*")
_HOME_PATH = re.compile(r"/home/[^/\s'\"]+")
_TELEGRAM_PATH = re.compile(r"/bot\d+:[A-Za-z0-9_\-]+")
#: Discord webhook: the id stays, the token tail goes.
_DISCORD_WEBHOOK = re.compile(r"(?i)(discord(?:app)?\.com/api/webhooks/\d+/)[A-Za-z0-9_\-.]+")
#: mysql-family client password flag: "-p <pw>" or "-p<pw>" (psql's -p is a port, so only these clients).
_MYSQL_PW = re.compile(r"(?i)(\b(?:mysql|mysqladmin|mysqldump|mariadb)\b[^\n]*?\s-p)\s*(?!-)\S+")
#: A secret key word followed by a SPACE and a token-like value ("rejected key c1a2b3...").
_SPACE_KEY_VALUE = re.compile(
    r"(?i)(?<![\w\-])((?:api[_\-]?key|app[_\-]?key|key|token|secret|passphrase|password|passwd|pwd|pw)\s+)"
    r"([A-Za-z0-9._~+/=\-]{8,})"
)
#: Bare UUID (Finviz API tokens have this shape).
_UUID = re.compile(r"(?i)(?<![0-9a-z])[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?![0-9a-z])")
#: 20+ alphanumerics in one run mixing letters and digits, any case ("c1a2b3...", "PKA1B2..."). This also covers
#: every hex secret, so the separate hex rule of round 2 was removed (2026-11-01, round 3).
_ALNUM_RUN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9]{20,}(?![A-Za-z0-9])")
#: Alphanumeric segments joined by '-', '_' or '.', 24+ characters long, mixing upper, lower and digits.
_JOINED_RUN = re.compile(r"(?<![A-Za-z0-9_.\-])[A-Za-z0-9]+(?:[-_.][A-Za-z0-9]+)+")
#: Userinfo runs to the LAST '@' before the path (round 4: "user:p@ssw0rd@host" leaked "ssw0rd").
_URL_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^\s/'\"]*@")
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
    r"|\bya29\.[A-Za-z0-9_\-.]+"
    r")"
)
#: Round 4: the bare word "token" is no longer a scheme here ("token expired", "token refresh failed" stayed
#: unreadable); "Authorization: Token <v>" is still covered by _AUTH_HEADER, a token-like value by the key rules.
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=\-]{6,}")
#: 2026-11-01 (review round 2): the whole value of an Authorization header, whatever its scheme
#: ("Token <v>", "Bearer <v>", "Basic <v>", a bare value), up to the closing quote or the line end.
_AUTH_HEADER = re.compile(r"""(?i)\b((?:proxy-)?authorization["']?\s*[:=]\s*["']?)[^"'\n,;}]+""")
#: High-entropy runs: a bare secret has no key word to anchor on. Base64-alphabet runs of >= 20 that mix
#: upper case, lower case and digits, and hex runs of >= 20 that mix digits and letters. Ordinary words,
#: identifiers (underscores split them) and lower-case paths never have all three classes.
_B64_RUN = re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{20,}={0,2}(?![A-Za-z0-9+/=])")
_SECRET_KEY_WORD = re.compile(
    r"(?i)(token|secret|passw(?:or)?d|pwd|api[_\-]?key|apikey|auth(?:orization)?(?![a-z])|credential|private[_\-]?key|"
    r"session|cookie|dsn|access[_\-]?key|signature|sig\b|key|client[_\-]?id|app[_\-]?key|key[_\-]?id|"
    r"passphrase|(?<![a-z])(?:pw|pass)(?![a-z]))"
)
#: The key and separator only. A key starts at a word start (the lookbehind), so a long run without a
#: separator is tried once, not from every character: the scan is linear (round 3: 3.2 s at 60 KB before).
_KEY_SEP = re.compile(
    r"""(?<![\w.\-"'\\])(?P<key>\\?["']?[A-Za-z_][\w.\-]*\\?["']?)(?P<sep>\s*[:=]\s*)"""
)
#: The value, matched only after a secret-looking key. A quoted value runs to ITS closing quote (it may
#: hold spaces and the other quote); an unquoted one stops at a delimiter.
#: Round 4: a value may sit in backslash-escaped quotes (JSON quoted inside a string: {\"password\": \"x\"}).
_VALUE = re.compile(
    r"""(?:\\?"(?P<dq>(?:[^"\\\n]|\\(?!"))*)(?:\\?")?"""
    r"""|\\?'(?P<sq>(?:[^'\\\n]|\\(?!'))*)(?:\\?')?"""
    r"""|(?P<val>[^\s"',;)}\]&\\]+))"""
)
#: Exception class names, dotted or not (psycopg2.errors.ForeignKeyViolation). Round 5: ONLY these suffixes; a
#: general "dotted CamelCase" exclusion leaked settings.ApiKey= and cfg.Password: values.
_NOT_A_KEY = re.compile(r"(?:Error|Exception|Warning|Exit|Interrupt|Violation)$")
#: Token-count keys (max_tokens, input_tokens, token_count). Round 5: excluded ONLY when the value is an integer, so
#: {'access_tokens': '<secret>'} is still redacted.
_TOKEN_COUNT_KEY = re.compile(r"(?i)(?:tokens|token_?(?:count|limit|budget|usage|used))$")
_INTEGER = re.compile(r"[+-]?\d+")
#: A brokerage account number in prose ("account <digits>", "acct #<digits>", "account number: <digits>").
_ACCOUNT_NUMBER = re.compile(r"(?i)\b(acc(?:oun)?t(?:\s+(?:number|no\.?))?\s*[:#]?\s*)\d{6,12}\b")


def _redact_pairs(text: str) -> str:
    """Redact the value of every ``key: value`` / ``key=value`` pair whose key looks secret.

    A non-secret pair consumes only its key and separator, so ``failed: refresh_token: abc`` still finds
    ``refresh_token: abc``; the value is only scanned for a secret key, and the scan then jumps past it.
    """
    out, pos = [], 0
    while True:
        match = _KEY_SEP.search(text, pos)
        if not match:
            out.append(text[pos:])
            return "".join(out)
        key = match.group("key").strip("\"'\\")
        sep_end = match.end("sep")
        if _NOT_A_KEY.search(key) or not _SECRET_KEY_WORD.search(key):
            out.append(text[pos:sep_end])
            pos = sep_end
            continue
        value = _VALUE.match(text, sep_end)
        group = next((g for g in ("dq", "sq", "val") if value and value.group(g) is not None), None)
        if group and _TOKEN_COUNT_KEY.search(key) and _INTEGER.fullmatch(value.group(group) or ""):
            group = None  # a token count, not a token
        if not group or not value.group(group) or R[:-1] in value.group(group):
            out.append(text[pos:sep_end])
            pos = sep_end
            continue
        out.append(text[pos:value.start(group)] + R)
        pos = value.end(group)


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


_CASE_FLIP = re.compile(r"[a-z][A-Z]")


def _letters_digits(value: str) -> bool:
    """A token-like value after a space-separated key word: letters AND digits, or (round 4) letters only but
    12+ long with an inner lower-to-upper flip ("aBcDeFgH..."). Plain words ("expired", "refresh") stay."""
    if R[:-1] in value:
        return False
    if any(c.isdigit() for c in value) and any(c.isalpha() for c in value):
        return True
    return len(value) >= 12 and value.isalpha() and bool(_CASE_FLIP.search(value))


#: Percent-decoding repeats until the text stops changing (triple-encoded bodies were seen in review), capped.
MAX_PERCENT_DECODES = 6


def _letters_and_digits(match: re.Match) -> str:
    run = match.group(0)
    return R if any(c.isdigit() for c in run) and any(c.isalpha() for c in run) else run


_DIGIT_THEN_LETTER = re.compile(r"[0-9][A-Za-z]")


def _joined_secret(match: re.Match) -> str:
    """A joined token: 24+ characters, upper + lower + digits, and a digit followed by a letter inside a segment
    (token material). Dotted Python names ("psycopg2.OperationalError") put digits only at a segment's end."""
    run = match.group(0)
    return R if len(run) >= 24 and _mixed(run) and _DIGIT_THEN_LETTER.search(run) else run


def _percent_decode(text: str) -> str:
    """Decode %XX escapes until stable (capped) so encoded keys and values are matched."""
    for _ in range(MAX_PERCENT_DECODES):
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
    out = _DISCORD_WEBHOOK.sub(lambda m: m.group(1) + R, out)
    out = _URL_USERINFO.sub(r"\1" + R + "@", out)
    out = _URL_QUERY.sub(r"\1?" + R, out)
    out = _AUTH_HEADER.sub(lambda m: m.group(1) + R, out)
    out = _BEARER.sub(lambda m: f"{m.group(1)} {R}", out)
    out = _TOKEN_SHAPES.sub(R, out)
    out = _UUID.sub(R, out)
    out = _MYSQL_PW.sub(lambda m: m.group(1) + " " + R, out)
    out = _redact_pairs(out)
    out = _ACCOUNT_NUMBER.sub(lambda m: m.group(1) + R, out)
    out = _SPACE_KEY_VALUE.sub(lambda m: m.group(1) + R if _letters_digits(m.group(2)) else m.group(0), out)
    out = _B64_RUN.sub(_high_entropy, out)
    out = _ALNUM_RUN.sub(_letters_and_digits, out)
    out = _JOINED_RUN.sub(_joined_secret, out)
    home = home if home is not None else str(Path.home())
    if home and home != "/":
        out = out.replace(home, "~")
    out = _HOME_PATH.sub("~", out)
    return out
