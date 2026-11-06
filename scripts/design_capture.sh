#!/usr/bin/env bash
# Design capture runner (design/README.md, AGENTS.md §28.8, §28.13): read-only screenshots of every registered page
# and tab at 1440 / 412 / 390 into the PRIVATE design store, then fingerprints only into design/ via
# scripts/design_capture_ingest.py.
#
#   scripts/design_capture.sh                         # production http://127.0.0.1:7777, all pages, v000
#   DESIGN_CAPTURE_PAGES=home,watch scripts/design_capture.sh
#   DESIGN_CAPTURE_BASE_URL=http://127.0.0.1:4173 scripts/design_capture.sh   # non-production: no window/memory gate
#
# Output: ~/trade-ai-releases/persistent-state/data/design/pages/<page>/<version>/capture/*.png (0600; never committed —
# the repo is public and these show real holdings) and a manifest under $TMPDIR. Refuses production 04:00-16:15 ET
# Mon-Fri; checks portfolio-server memory before every page (scripts/lib/design_capture_guard.py). Never POSTs.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${HERE}/.." && pwd)"
APP="${REPO}/apps/command-center-v3"
GUARD="${REPO}/scripts/lib/design_capture_guard.py"
BASE="${DESIGN_CAPTURE_BASE_URL:-http://127.0.0.1:7777}"
VERSION="${DESIGN_CAPTURE_VERSION:-v000}"
STORE="${DESIGN_CAPTURE_STORE:-${HOME}/trade-ai-releases/persistent-state/data/design}"
TS="$(date -u +%Y%m%dT%H%M%SZ)"

# TMPDIR on disk, never /tmp (tmpfs shared with cron locks; 2026-10-25 ENOSPC).
export TMPDIR="${DESIGN_CAPTURE_TMPDIR:-${HOME}/.cache/agent-tmp/design-capture}"
mkdir -p "${TMPDIR}"
MANIFEST="${DESIGN_CAPTURE_MANIFEST:-${TMPDIR}/design-capture-${VERSION}-${TS}.json}"

python3 "${GUARD}" window --base "${BASE}" >/dev/null || { python3 "${GUARD}" window --base "${BASE}" >&2 || true; exit 3; }

avail_kb="$(df -Pk "${HOME}" | awk 'NR==2{print $4}')"
if [ "${avail_kb}" -lt 5242880 ]; then echo "design_capture: < 5 GB free on ${HOME}; refusing." >&2; exit 4; fi

# Node modules: this checkout's own, else DESIGN_CAPTURE_NODE_MODULES (read-only; worktrees have none).
NODE_MODULES="${APP}/node_modules"
if [ ! -d "${NODE_MODULES}/@playwright/test" ]; then
  NODE_MODULES="${DESIGN_CAPTURE_NODE_MODULES:-}"
  if [ -z "${NODE_MODULES}" ] || [ ! -d "${NODE_MODULES}/@playwright/test" ]; then
    echo "design_capture: no @playwright/test — run 'npm ci' in apps/command-center-v3 or set DESIGN_CAPTURE_NODE_MODULES." >&2
    exit 5
  fi
  # ESM ignores NODE_PATH: link the supplied modules into this checkout (node_modules is gitignored, never committed).
  ln -s "${NODE_MODULES}" "${APP}/node_modules"
fi

mkdir -p "${STORE}/pages"
chmod 700 "${STORE}" "${STORE}/pages"
echo "design_capture: ${BASE} → ${STORE}/pages/<page>/${VERSION}/capture (manifest ${MANIFEST})"
cd "${APP}"
rc=0
DESIGN_CAPTURE_BASE_URL="${BASE}" DESIGN_CAPTURE_STORE="${STORE}" \
  DESIGN_CAPTURE_MANIFEST="${MANIFEST}" DESIGN_CAPTURE_VERSION="${VERSION}" DESIGN_CAPTURE_GUARD="${GUARD}" \
  node --experimental-strip-types --no-warnings e2e-live/design-capture.ts || rc=$?
echo "design_capture: manifest ${MANIFEST} (rc=${rc}); ingest with: python3 scripts/design_capture_ingest.py ${MANIFEST}"
exit "${rc}"
