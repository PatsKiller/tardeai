#!/usr/bin/env bash
# opend_launch.sh — start moomoo OpenD with credentials resolved from Bitwarden.
#
# Credentials NEVER live in OpenD.xml. They come from the Bitwarden Secrets Manager
# render on tmpfs ($XDG_RUNTIME_DIR/tradeai/env), same path resolve_secret.py uses:
#   MOOMOO_OPEND_LOGIN_ACCOUNT   moomoo user id or email
#   MOOMOO_OPEND_LOGIN_PWD_MD5   32-hex MD5 of the login password (preferred)
#   MOOMOO_OPEND_LOGIN_PWD       plaintext fallback, only if no MD5 is set
#
# Fails closed: no credentials → exit non-zero without invoking OpenD, so systemd
# reports the real reason instead of OpenD burning a login attempt. moomoo locks
# accounts after repeated failures, so never retry a bad credential in a tight loop.
#
# Data plane only. No trade unlock, no order path.
set -Eeuo pipefail

OPEND_HOME="${OPEND_HOME:-$HOME/.local/opt/trade-ai-lab/moomoo/opend/current}"
BIN="$OPEND_HOME/OpenD"
RENDER="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/tradeai/env"

log() { printf '[opend_launch] %s\n' "$*" >&2; }

[[ -x "$BIN" ]] || { log "FATAL: OpenD binary not executable at $BIN"; exit 78; }

# Pull only the keys we need; never echo values, never export the whole file.
_get() {
  [[ -r "$RENDER" ]] || return 0
  sed -n "s/^$1=//p" "$RENDER" | tail -1 | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//"
}

ACCOUNT="${MOOMOO_OPEND_LOGIN_ACCOUNT:-$(_get MOOMOO_OPEND_LOGIN_ACCOUNT)}"
PWD_MD5="${MOOMOO_OPEND_LOGIN_PWD_MD5:-$(_get MOOMOO_OPEND_LOGIN_PWD_MD5)}"
PWD_RAW="${MOOMOO_OPEND_LOGIN_PWD:-$(_get MOOMOO_OPEND_LOGIN_PWD)}"

if [[ -z "$ACCOUNT" ]]; then
  log "FATAL: MOOMOO_OPEND_LOGIN_ACCOUNT not in Bitwarden render ($RENDER)."
  log "       Add it with: .venv/bin/python scripts/moomoo/opend_credentials.py --set"
  exit 78
fi
if [[ -z "$PWD_MD5" && -z "$PWD_RAW" ]]; then
  log "FATAL: no MOOMOO_OPEND_LOGIN_PWD_MD5 (or _PWD) in Bitwarden render."
  log "       Add it with: .venv/bin/python scripts/moomoo/opend_credentials.py --set"
  exit 78
fi

# Render a PRIVATE config on tmpfs and pass -cfg_file, rather than putting the
# credential in argv. Anything on the command line is world-readable via
# /proc/<pid>/cmdline to every process running as this user, so `-login_pwd_md5=...`
# leaked the credential to any `ps`. The rendered file is 0600 on a RAM-backed
# filesystem, never touches disk, and is removed when the unit stops.
RUNDIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/tradeai"
CFG="$RUNDIR/opend.rendered.xml"
mkdir -p "$RUNDIR"
chmod 700 "$RUNDIR" 2>/dev/null || true

: > "$CFG"
chmod 600 "$CFG"          # tighten BEFORE the secret goes in, not after

BASE_CFG="$OPEND_HOME/OpenD.xml"
[[ -r "$BASE_CFG" ]] || { log "FATAL: base config unreadable at $BASE_CFG"; exit 78; }

if [[ -n "$PWD_MD5" ]]; then
  CRED_TAG="login_pwd_md5"; CRED_VAL="$PWD_MD5"
  log "starting OpenD as ${ACCOUNT:0:2}*** (md5 credential via private cfg, api 127.0.0.1:11111)"
else
  CRED_TAG="login_pwd"; CRED_VAL="$PWD_RAW"
  log "starting OpenD as ${ACCOUNT:0:2}*** (PLAINTEXT credential — prefer MD5)"
fi

# Fill the scrubbed on-disk template: set <login_account> and inject the credential.
ACCOUNT="$ACCOUNT" CRED_TAG="$CRED_TAG" CRED_VAL="$CRED_VAL" \
python3 - "$BASE_CFG" "$CFG" <<'PY'
import os, re, sys
src, dst = sys.argv[1], sys.argv[2]
s = open(src, encoding="utf-8", errors="replace").read()
acct, tag, val = os.environ["ACCOUNT"], os.environ["CRED_TAG"], os.environ["CRED_VAL"]

# Detect on a comment-MASKED copy. The vendor template ships a commented-out
# "<login_pwd_md5>6e55...</login_pwd_md5>" example; searching the raw text matched
# that, so the credential got written INSIDE the comment and OpenD saw no password
# (exit 14, same as a wrong password). Mask comments to equal-length filler so the
# offsets we compute against `masked` stay valid for `s`.
masked = re.sub(r"<!--.*?-->", lambda m: " " * len(m.group(0)), s, flags=re.S)

def live_sub(pattern, repl_val, text, mask):
    m = re.search(pattern, mask)
    if not m:
        return text, False
    inner = re.match(r"(<[^>]+>)([^<]*)(</[^>]+>)", text[m.start():m.end()])
    if not inner:
        return text, False
    new = inner.group(1) + repl_val + inner.group(3)
    return text[:m.start()] + new + text[m.end():], True

s, _ = live_sub(r"<login_account>[^<]*</login_account>", acct, s, masked)
masked = re.sub(r"<!--.*?-->", lambda m: " " * len(m.group(0)), s, flags=re.S)
s, done = live_sub(rf"<{tag}>[^<]*</{tag}>", val, s, masked)
if not done:  # no LIVE element — add one right after the account
    s = s.replace("</login_account>", f"</login_account>\n\t\t<{tag}>{val}</{tag}>", 1)
open(dst, "w", encoding="utf-8").write(s)
PY

cd "$OPEND_HOME"
exec ./OpenD -cfg_file="$CFG" -lang=en
