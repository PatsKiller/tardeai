#!/usr/bin/env bash
# Governed CIO TIS Telegram digest (Phase B coverage SLA + thesis debt).
#
# Cron-safe (no % chars):
#
#   15 12,17 * * 1-5 /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/scripts/run_governed_cio_tis_digest.sh >> /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/logs/cio_tis_digest.log 2>&1 # TRADEAI_GOVERNED_WORKER cio-tis-digest
#
# Authority: READ_ONLY_ADVISORY. CIO bot only. Fail-closed without live auth.
#
set -euo pipefail

SRC="${TRADEAI_SRC:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PROJ="${TRADEAI_PROJ:-/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild}"
PY="${PY:-$PROJ/.venv/bin/python}"
LOG="${TRADEAI_TIS_DIGEST_LOG:-$PROJ/logs/cio_tis_digest.log}"
LOCK="${TRADEAI_TIS_DIGEST_LOCK:-/tmp/tradeai_cio_tis_digest.lock}"
DRY_RUN="${TRADEAI_TIS_DIGEST_DRY_RUN:-0}"
FORCE="${TRADEAI_TIS_DIGEST_FORCE:-0}"
MARKER_HINT="TRADEAI_GOVERNED_WORKER cio-tis-digest"

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { echo "$(ts) $*" >>"$LOG"; }

mkdir -p "$(dirname "$LOG")" "$PROJ/logs" 2>/dev/null || true

log "=== start pid=$$ marker=${MARKER_HINT} dry_run=${DRY_RUN} src=${SRC} ==="

if [[ ! -x "$PY" ]]; then
  log "failure: python missing path=${PY}"
  log "exit=2"
  exit 2
fi

# Load CIO Telegram + live-delivery env (never print secrets)
# Runtime SM render (/run/user/$UID/tradeai/env) holds TELEGRAM_CIO_BOT_TOKEN;
# ~/.config/tradeai/cio-telegram.env often has chats only.
set -a
for envf in \
  "/run/user/${UID}/tradeai/env" \
  "${HOME}/.config/tradeai/cio-telegram.env"
do
  if [[ -f "$envf" ]]; then
    # shellcheck disable=SC1090
    . "$envf" || true
    log "env_loaded path=${envf}"
  fi
done
# systemd drop-in Environment= lines (AUTH / INTERDICT / ENABLE_TELEGRAM)
for conf in \
  "${HOME}/.config/systemd/user/portfolio-server.service.d/25-cio-only-live.conf" \
  "${HOME}/.config/systemd/user/tradeai-cio-telegram.service.d/"*.conf
do
  [[ -f "$conf" ]] || continue
  while IFS= read -r line; do
    case "$line" in
      Environment=*)
        kv="${line#Environment=}"
        kv="${kv%\"}"
        kv="${kv#\"}"
        # shellcheck disable=SC2163
        export "$kv" 2>/dev/null || true
        ;;
    esac
  done <"$conf"
done
export AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY="${AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY:-1}"
export ENABLE_TELEGRAM="${ENABLE_TELEGRAM:-1}"
export CIO_TELEGRAM_INTERDICT="${CIO_TELEGRAM_INTERDICT:-0}"
set +a

if [[ -z "${TELEGRAM_CIO_BOT_TOKEN:-}" ]]; then
  log "failure: TELEGRAM_CIO_BOT_TOKEN unset after env load (check /run/user/${UID}/tradeai/env)"
  log "exit=2"
  exit 2
fi
if [[ -z "${TELEGRAM_CIO_CHAT_IDS:-}${TELEGRAM_CIO_ALLOWLIST:-}" ]]; then
  log "failure: TELEGRAM_CIO_CHAT_IDS/ALLOWLIST unset"
  log "exit=2"
  exit 2
fi
# Never log token; only presence
log "cio_token_set=yes chat_ids_set=yes"

if [[ "${CIO_TELEGRAM_INTERDICT}" == "1" ]]; then
  log "failure: CIO_TELEGRAM_INTERDICT=1"
  log "exit=79"
  exit 79
fi

ARGS=(scripts/cio_tis_telegram_digest.py --root "$PROJ")
if [[ "$DRY_RUN" == "1" ]]; then
  :
else
  ARGS+=(--apply)
fi
if [[ "$FORCE" == "1" ]]; then
  ARGS+=(--force)
fi

(
  flock -n 9 || { log "skip: lock held"; exit 0; }
  cd "$SRC"
  set +e
  out=$("$PY" "${ARGS[@]}" 2>&1)
  rc=$?
  set -e
  # Log without dumping full token-bearing env; body is advisory text only
  echo "$out" | head -c 8000 >>"$LOG"
  echo >>"$LOG"
  log "exit=${rc}"
  exit "$rc"
) 9>"$LOCK"
