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

ARGS=( -login_account="$ACCOUNT" -lang=en )
if [[ -n "$PWD_MD5" ]]; then
  ARGS+=( -login_pwd_md5="$PWD_MD5" )
  log "starting OpenD as ${ACCOUNT:0:2}*** (md5 credential, api 127.0.0.1:11111)"
else
  ARGS+=( -login_pwd="$PWD_RAW" )
  log "starting OpenD as ${ACCOUNT:0:2}*** (PLAINTEXT credential — prefer MD5)"
fi

cd "$OPEND_HOME"
exec ./OpenD "${ARGS[@]}"
