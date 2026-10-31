#!/usr/bin/env bash
# Site sweep runner — read-only Playwright defect finder for Command Center v3.
#
#   scripts/site_sweep.sh                      # production http://127.0.0.1:7777, all routes/viewports
#   SWEEP_ROUTES=/v3/watch,/v3/cio scripts/site_sweep.sh
#   SWEEP_BASE_URL=http://127.0.0.1:5173 scripts/site_sweep.sh   # non-production: no time window
#
# Writes ~/trade-ai-releases/persistent-state/data/site_sweep/<UTC ts>/{findings.json,summary.md,shots/}.
# Refuses production 04:00–16:15 ET Mon–Fri (§28.8). Never POSTs: every non-GET request is aborted in-browser.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="${HERE}/../apps/command-center-v3"
BASE="${SWEEP_BASE_URL:-http://127.0.0.1:7777}"
ROOT="${SWEEP_OUT_ROOT:-${HOME}/trade-ai-releases/persistent-state/data/site_sweep}"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${ROOT}/${TS}"

# §28.8 market-hours refusal for production (also enforced inside site-sweep.ts).
case "${BASE}" in
  *127.0.0.1:7777*|*localhost:7777*|*ms01-openclaw.*)
    dow="$(TZ=America/New_York date +%u)"; hm="$(TZ=America/New_York date +%H%M)"
    if [ "${dow}" -le 5 ] && [ "10#${hm}" -ge 400 ] && [ "10#${hm}" -lt 1615 ]; then
      echo "site_sweep: refusing production sweep ${hm} ET weekday (§28.8 04:00–16:15 ET Mon–Fri)." >&2
      echo "site_sweep: point SWEEP_BASE_URL at a non-production host instead." >&2
      exit 3
    fi ;;
esac

# Disk: refuse below 5 GB free; never use /tmp (tmpfs shared with cron locks).
avail_kb="$(df -Pk "${HOME}" | awk 'NR==2{print $4}')"
if [ "${avail_kb}" -lt 5242880 ]; then echo "site_sweep: < 5 GB free on ${HOME}; refusing." >&2; exit 4; fi
export TMPDIR="${SWEEP_TMPDIR:-${HOME}/.cache/agent-tmp/site-sweep}"
mkdir -p "${TMPDIR}" "${OUT}"

if [ ! -d "${APP}/node_modules/@playwright/test" ]; then
  echo "site_sweep: ${APP}/node_modules missing @playwright/test — run 'npm ci' in apps/command-center-v3." >&2
  exit 5
fi

# Read-only agent identity (config/cc_auth.yaml agent_reader): header name + token FILE path only; the token value is
# read by site-sweep.ts and only sent with same-origin GET/HEAD. SWEEP_READER=0 sweeps unauthenticated.
READER_HEADER=""; READER_FILE=""
if [ "${SWEEP_READER:-1}" != "0" ]; then
  mapfile -t rs < <(python3 "${HERE}/lib/cc_auth.py" --reader-settings 2>/dev/null || true)
  if [ "${#rs[@]}" -ge 4 ] && [ "${rs[3]}" = "enabled" ] && [ -f "${rs[1]}" ]; then
    READER_HEADER="${rs[0]}"; READER_FILE="${rs[1]}"
    echo "site_sweep: authenticated as read-only agent reader (${READER_HEADER})"
  else
    echo "site_sweep: agent reader not available (disabled or token not minted) — sweeping unauthenticated" >&2
  fi
fi

echo "site_sweep: ${BASE} → ${OUT}"
cd "${APP}"
SWEEP_READER_HEADER="${READER_HEADER}" SWEEP_READER_TOKEN_FILE="${READER_FILE}" \
SWEEP_BASE_URL="${BASE}" SWEEP_OUT_DIR="${OUT}" \
  node --experimental-strip-types --no-warnings e2e-live/site-sweep.ts 2>&1 | tee "${OUT}/sweep.log"
rc="${PIPESTATUS[0]}"
echo "site_sweep: summary ${OUT}/summary.md (rc=${rc})"
exit "${rc}"
