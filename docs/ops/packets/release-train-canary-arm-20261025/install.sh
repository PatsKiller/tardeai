#!/usr/bin/env bash
# install.sh — run once after PR #2099 is released (CURRENT carries the schedule code). Host systemd user units only.
#
# Installs the 2026-10-25 release-train schedule on the host trigger (packet release-train-host-trigger-20261023 is
# already installed: the request@.service template, census@.service template, and the 1800/0000/0600/0800 timers):
#   * drop-ins removing --shadow-only for the request@ instances 1800, 1200, 0000, 0300, 0600, 0900, 1500, 2100
#     (0800 keeps the template's --shadow-only). The policy still decides live vs shadow for each day;
#   * new timers: request@1200 (every day 12:00), request@0300 (Sun), request@0900/1500/2100 (Sat,Sun), and their
#     census timers 20 minutes before (census@1200 every day 11:40; census@0300 Sun 02:40; census@0900/1500/2100
#     Sat,Sun). The existing daily 0000/0600 timers keep firing every day; on days the policy does not schedule
#     them (0000: only Sunday; 0600: only Sat/Sun) the request stays shadow.
#
#   bash install.sh --preview   # default: diff against what is installed; writes nothing
#   bash install.sh --apply     # type ACK-TRAIN-SCHEDULE; archives any copy it replaces (never deletes), installs,
#                               # daemon-reload, enables the new timers, verifies
# Rollback: bash install.sh --rollback (moves this packet's installed files into an archive dir, daemon-reload,
# disables the new timers; the 2026-10-23 host trigger keeps running shadow-only).
#
# The timers only START the request writer and the read-only PR census. Nothing merges, pushes, promotes, reads a
# credential or sends. MBI_BEHAVIOR = 0.
set -euo pipefail

PACKET_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_DIR="${HOME}/.config/systemd/user"
CURRENT="${TRADEAI_CURRENT:-${HOME}/trade-ai-releases/portfolio-server/CURRENT}"
ACK_WORD="ACK-TRAIN-SCHEDULE"
LIVE_SLOTS=(1800 1200 0000 0300 0600 0900 1500 2100)
NEW_SLOTS=(1200 0300 0900 1500 2100)
MODE="${1:---preview}"

# packet file -> installed path
pairs() {
  local s
  echo "tradeai-release-train-request@1800.service.d--canary-live.conf.proposed tradeai-release-train-request@1800.service.d/canary-live.conf"
  for s in "${LIVE_SLOTS[@]}"; do
    [[ "$s" == 1800 ]] && continue
    echo "tradeai-release-train-request@${s}.service.d--schedule-live.conf.proposed tradeai-release-train-request@${s}.service.d/schedule-live.conf"
  done
  for s in "${NEW_SLOTS[@]}"; do
    echo "tradeai-release-train-request@${s}.timer.proposed tradeai-release-train-request@${s}.timer"
    echo "tradeai-pr-census@${s}.timer.proposed tradeai-pr-census@${s}.timer"
  done
}
new_timers() { local s; for s in "${NEW_SLOTS[@]}"; do echo "tradeai-release-train-request@${s}.timer tradeai-pr-census@${s}.timer"; done; }

preflight() {
  local ok=1
  [[ -x "${CURRENT}/.venv/bin/python" ]] || { echo "PREFLIGHT: missing ${CURRENT}/.venv/bin/python"; ok=0; }
  if ! ( cd "$CURRENT" && .venv/bin/python -c 'import sys; sys.path[:0]=[".","scripts"]
from scripts.lib import release_train_window_view as V; assert "1200" in V.SLOTS and "2100" in V.SLOTS' ) 2>/dev/null; then
    echo "PREFLIGHT: CURRENT does not carry the 2026-10-25 schedule slots (release PR #2099 first)"; ok=0
  fi
  [[ -f "${UNIT_DIR}/tradeai-release-train-request@.service" ]] || { echo "PREFLIGHT: host trigger template not installed (packet release-train-host-trigger-20261023)"; ok=0; }
  [[ -f "${UNIT_DIR}/tradeai-pr-census@.service" ]] || { echo "PREFLIGHT: census template not installed (packet release-train-host-trigger-20261023)"; ok=0; }
  local src dst
  while read -r src dst; do [[ -f "${PACKET_DIR}/${src}" ]] || { echo "PREFLIGHT: missing ${src}"; ok=0; }; done < <(pairs)
  [[ "$ok" == 1 ]] && echo "PREFLIGHT: OK (CURRENT -> $(readlink -f "$CURRENT" 2>/dev/null || echo "$CURRENT"))"
  [[ "$ok" == 1 ]]
}

preview() {
  echo "== PREVIEW: nothing is written =="
  local src dst
  while read -r src dst; do
    if [[ -f "${UNIT_DIR}/${dst}" ]]; then
      diff -q "${UNIT_DIR}/${dst}" "${PACKET_DIR}/${src}" >/dev/null && echo "-- ${dst}: UNCHANGED" \
        || { echo "-- ${dst}: CHANGED (archived, then replaced)"; diff -u "${UNIT_DIR}/${dst}" "${PACKET_DIR}/${src}" || true; }
    else
      echo "-- ${dst}: NEW"
    fi
  done < <(pairs)
  echo "== --apply would: archive replaced copies, install, daemon-reload, enable --now: $(new_timers | tr '\n' ' ')"
  preflight || echo "(preview: the preflight failures above would refuse --apply)"
}

apply() {
  preflight || { echo "refused: preflight failed; nothing written"; exit 2; }
  printf 'Type %s to install the release-train schedule units: ' "$ACK_WORD"
  local typed=""; read -r typed || true
  [[ "$typed" == "$ACK_WORD" ]] || { echo; echo "refused: acknowledgement not typed; nothing written"; exit 2; }
  local stamp archive src dst
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  archive="${UNIT_DIR}/archived-release-train-schedule-${stamp}"
  mkdir -p "$archive"
  while read -r src dst; do
    mkdir -p "$(dirname "${UNIT_DIR}/${dst}")"
    if [[ -e "${UNIT_DIR}/${dst}" ]]; then
      mkdir -p "$(dirname "${archive}/${dst}")"; mv "${UNIT_DIR}/${dst}" "${archive}/${dst}"
      echo "archived ${dst}" >> "${archive}/MANIFEST"
    else
      echo "new ${dst}" >> "${archive}/MANIFEST"
    fi
    install -m 0644 "${PACKET_DIR}/${src}" "${UNIT_DIR}/${dst}"
  done < <(pairs)
  systemctl --user daemon-reload
  # shellcheck disable=SC2046
  systemctl --user enable --now $(new_timers)
  local bad=0 t s
  for t in $(new_timers); do
    systemctl --user is-active "$t" >/dev/null 2>&1 && echo "VERIFY ${t}: active" || { echo "VERIFY ${t}: NOT active"; bad=1; }
  done
  for s in "${LIVE_SLOTS[@]}"; do
    if systemctl --user cat "tradeai-release-train-request@${s}.service" | grep '^ExecStart=.' | tail -1 | grep -q -- '--shadow-only'; then
      echo "VERIFY request@${s}: still --shadow-only"; bad=1
    else
      echo "VERIFY request@${s}: live-capable"
    fi
  done
  echo "archive (rollback source): ${archive}"
  [[ "$bad" == 0 ]] || { echo "VERIFY FAILED; bash $0 --rollback"; exit 1; }
}

rollback() {
  local stamp archive src dst
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  archive="${UNIT_DIR}/archived-release-train-schedule-rollback-${stamp}"
  mkdir -p "$archive"
  # shellcheck disable=SC2046
  systemctl --user disable --now $(new_timers) || true
  while read -r src dst; do
    if [[ -e "${UNIT_DIR}/${dst}" ]]; then
      mkdir -p "$(dirname "${archive}/${dst}")"; mv "${UNIT_DIR}/${dst}" "${archive}/${dst}"
    fi
  done < <(pairs)
  systemctl --user daemon-reload
  echo "rolled back into ${archive}; the 2026-10-23 host trigger runs shadow-only again"
}

case "$MODE" in
  --preview) preview ;;
  --apply) apply ;;
  --rollback) rollback ;;
  *) echo "usage: $0 [--preview|--apply|--rollback]"; exit 2 ;;
esac
