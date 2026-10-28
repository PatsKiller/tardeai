#!/usr/bin/env bash
# install.sh — OPERATOR ONLY (AGENTS §17: a new production systemd entry; cron/scheduler freeze).
#
# Installs the release-train host trigger: 8 user timers + 2 templated oneshot services from this packet's *.proposed
# files (docs/ops/packets/release-train-host-trigger-20261023/README.md).
#
#   bash install.sh --preview        # default: diff against the installed units + read-only preflight; writes nothing
#   bash install.sh --apply          # asks you to type ACK-TRAIN-TRIGGER; archives, installs, enables, verifies
#
# --apply: refuses unless the served release (CURRENT) carries scripts/release_train_window_request.py with
# --shadow-only and scripts/pr_hygiene_audit.py; archives every existing copy of a unit it is about to write (never
# deletes, §0 rule 6) into ~/.config/systemd/user/archived-release-train-host-trigger-<stamp>/; copies; daemon-reload;
# enables the 8 timers; verifies with list-timers (exit 1 if any timer is not enabled and active).
# Rollback: bash rollback.sh --preview, then bash rollback.sh --apply.
#
# The timers only START the writer (shadow-only requests) and the read-only PR census. Nothing merges, pushes,
# promotes, reads a credential or sends. MBI_BEHAVIOR = 0.
set -euo pipefail

PACKET_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_DIR="${HOME}/.config/systemd/user"
CURRENT="${TRADEAI_CURRENT:-${HOME}/trade-ai-releases/portfolio-server/CURRENT}"
ACK_WORD="ACK-TRAIN-TRIGGER"
ARCHIVE_PREFIX="archived-release-train-host-trigger"
LAST_ARCHIVE_MARKER="${UNIT_DIR}/.release-train-host-trigger.last-install"
SLOTS=(1800 0000 0600 0800)
MODE="${1:---preview}"

units() {
  echo "tradeai-release-train-request@.service"
  echo "tradeai-pr-census@.service"
  local s
  for s in "${SLOTS[@]}"; do echo "tradeai-release-train-request@${s}.timer"; done
  for s in "${SLOTS[@]}"; do echo "tradeai-pr-census@${s}.timer"; done
}

timers() { units | grep '\.timer$'; }

preflight() {
  local ok=1 writer="${CURRENT}/scripts/release_train_window_request.py"
  [[ -x "${CURRENT}/.venv/bin/python" ]] || { echo "PREFLIGHT: missing interpreter ${CURRENT}/.venv/bin/python"; ok=0; }
  if [[ ! -f "$writer" ]]; then
    echo "PREFLIGHT: CURRENT has no scripts/release_train_window_request.py ($writer)"; ok=0
  elif ! grep -q -- '--shadow-only' "$writer"; then
    echo "PREFLIGHT: $writer has no --shadow-only flag (release the request-lane code first)"; ok=0
  fi
  [[ -f "${CURRENT}/scripts/pr_hygiene_audit.py" ]] || { echo "PREFLIGHT: CURRENT has no scripts/pr_hygiene_audit.py"; ok=0; }
  local u
  while read -r u; do
    [[ -f "${PACKET_DIR}/${u}.proposed" ]] || { echo "PREFLIGHT: packet file missing: ${u}.proposed"; ok=0; }
  done < <(units)
  if [[ "$ok" == 1 ]]; then
    echo "PREFLIGHT: OK (CURRENT -> $(readlink -f "$CURRENT" 2>/dev/null || echo "$CURRENT"); writer has --shadow-only)"
  fi
  [[ "$ok" == 1 ]]
}

preview() {
  echo "== PREVIEW: nothing is written. Diff of each unit against ${UNIT_DIR} =="
  local u
  while read -r u; do
    if [[ -f "${UNIT_DIR}/${u}" ]]; then
      if diff -q "${UNIT_DIR}/${u}" "${PACKET_DIR}/${u}.proposed" >/dev/null; then
        echo "-- ${u}: UNCHANGED (installed copy is identical)"
      else
        echo "-- ${u}: CHANGED (installed copy would be archived, then replaced)"
        diff -u "${UNIT_DIR}/${u}" "${PACKET_DIR}/${u}.proposed" || true
      fi
    else
      echo "-- ${u}: NEW"
      diff -u /dev/null "${PACKET_DIR}/${u}.proposed" --label /dev/null --label "${UNIT_DIR}/${u}" || true
    fi
  done < <(units)
  echo "== --apply would run (after you type ${ACK_WORD}) =="
  echo "  mkdir ${UNIT_DIR}/${ARCHIVE_PREFIX}-<stamp>; mv any installed copy of the 10 units there (never deleted)"
  echo "  install -m 0644 <packet>/<unit>.proposed ${UNIT_DIR}/<unit>   (x10)"
  echo "  systemctl --user daemon-reload"
  echo "  systemctl --user enable --now $(timers | tr '\n' ' ')"
  echo "  systemctl --user list-timers --all 'tradeai-release-train-request@*' 'tradeai-pr-census@*' --no-pager"
  echo "== read-only preflight =="
  preflight || echo "(preview: the preflight failures above would refuse --apply)"
}

apply() {
  preflight || { echo "refused: preflight failed; nothing written"; exit 2; }
  printf 'Type %s to install and enable the 8 release-train host-trigger timers: ' "$ACK_WORD"
  local typed=""
  read -r typed || true
  [[ "$typed" == "$ACK_WORD" ]] || { echo; echo "refused: acknowledgement not typed; nothing written"; exit 2; }
  mkdir -p "$UNIT_DIR"
  local stamp archive u
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  archive="${UNIT_DIR}/${ARCHIVE_PREFIX}-${stamp}"
  mkdir -p "$archive"
  {
    echo "# release-train host trigger install ${stamp} (packet ${PACKET_DIR})"
    echo "# archived = an installed copy was moved here; new = no prior copy existed"
  } > "${archive}/MANIFEST"
  while read -r u; do
    if [[ -e "${UNIT_DIR}/${u}" ]]; then
      local was="disabled"
      if [[ "$u" == *.timer ]] && systemctl --user is-enabled "$u" >/dev/null 2>&1; then was="enabled"; fi
      mv "${UNIT_DIR}/${u}" "${archive}/${u}"
      echo "archived ${u} ${was}" >> "${archive}/MANIFEST"
    else
      echo "new ${u}" >> "${archive}/MANIFEST"
    fi
  done < <(units)
  while read -r u; do
    install -m 0644 "${PACKET_DIR}/${u}.proposed" "${UNIT_DIR}/${u}"
  done < <(units)
  echo "$archive" > "$LAST_ARCHIVE_MARKER"
  systemctl --user daemon-reload
  # shellcheck disable=SC2046
  systemctl --user enable --now $(timers)
  echo "== verify =="
  systemctl --user list-timers --all 'tradeai-release-train-request@*' 'tradeai-pr-census@*' --no-pager || true
  local bad=0 t
  while read -r t; do
    if systemctl --user is-enabled "$t" >/dev/null 2>&1 && systemctl --user is-active "$t" >/dev/null 2>&1; then
      echo "VERIFY ${t}: enabled, active"
    else
      echo "VERIFY ${t}: NOT enabled+active"; bad=1
    fi
  done < <(timers)
  echo "archive (rollback source): ${archive}"
  if [[ "$bad" == 1 ]]; then echo "VERIFY FAILED: see above; rollback with bash ${PACKET_DIR}/rollback.sh --apply"; exit 1; fi
  echo "installed. Proof at the next window: README §5 (a -win request id, its report, and the journal line)."
}

case "$MODE" in
  --preview) preview ;;
  --apply) apply ;;
  *) echo "usage: $0 [--preview|--apply]"; exit 2 ;;
esac
