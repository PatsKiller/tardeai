#!/usr/bin/env bash
# rollback.sh — OPERATOR ONLY. Undoes install.sh --apply of the release-train host trigger.
#
#   bash rollback.sh --preview                  # default: what would be disabled, archived and restored; writes nothing
#   bash rollback.sh --apply [--archive DIR]    # asks you to type ACK-TRAIN-TRIGGER-ROLLBACK
#
# --apply: disables (and stops) the 8 timers; moves the packet's installed units into
# ~/.config/systemd/user/archived-release-train-host-trigger-rollback-<stamp>/ (never deleted, §0 rule 6); restores
# every unit the install archived (default: the archive named in .release-train-host-trigger.last-install) and
# re-enables a restored timer that was enabled before the install; daemon-reload. Spool requests and receipts
# already written stay where they are (they are the record).
set -euo pipefail

UNIT_DIR="${HOME}/.config/systemd/user"
ACK_WORD="ACK-TRAIN-TRIGGER-ROLLBACK"
LAST_ARCHIVE_MARKER="${UNIT_DIR}/.release-train-host-trigger.last-install"
SLOTS=(1800 0000 0600 0800)
MODE="${1:---preview}"
ARCHIVE=""
if [[ "${2:-}" == "--archive" ]]; then ARCHIVE="${3:-}"; fi
if [[ -z "$ARCHIVE" && -f "$LAST_ARCHIVE_MARKER" ]]; then ARCHIVE="$(cat "$LAST_ARCHIVE_MARKER")"; fi

units() {
  echo "tradeai-release-train-request@.service"
  echo "tradeai-pr-census@.service"
  local s
  for s in "${SLOTS[@]}"; do echo "tradeai-release-train-request@${s}.timer"; done
  for s in "${SLOTS[@]}"; do echo "tradeai-pr-census@${s}.timer"; done
}
timers() { units | grep '\.timer$'; }

preview() {
  echo "== PREVIEW: nothing is written =="
  echo "would run: systemctl --user disable --now $(timers | tr '\n' ' ')"
  local u
  while read -r u; do
    if [[ -e "${UNIT_DIR}/${u}" ]]; then echo "would archive installed ${UNIT_DIR}/${u}"; fi
  done < <(units)
  if [[ -n "$ARCHIVE" && -f "${ARCHIVE}/MANIFEST" ]]; then
    echo "restore source: ${ARCHIVE}"
    grep '^archived ' "${ARCHIVE}/MANIFEST" | while read -r _ u was; do echo "would restore ${u} (${was} before the install)"; done
    grep -q '^archived ' "${ARCHIVE}/MANIFEST" || echo "nothing to restore: the install found no prior copies"
  else
    echo "restore source: none found (no ${LAST_ARCHIVE_MARKER}); --apply would only disable and archive"
  fi
}

apply() {
  if [[ -n "$ARCHIVE" && ! -f "${ARCHIVE}/MANIFEST" ]]; then
    echo "refused: ${ARCHIVE} has no MANIFEST (not an install archive); nothing changed"; exit 2
  fi
  printf 'Type %s to disable the release-train host-trigger timers and restore the archived units: ' "$ACK_WORD"
  local typed=""
  read -r typed || true
  [[ "$typed" == "$ACK_WORD" ]] || { echo; echo "refused: acknowledgement not typed; nothing changed"; exit 2; }
  # shellcheck disable=SC2046
  systemctl --user disable --now $(timers) || true
  local stamp out u
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  out="${UNIT_DIR}/archived-release-train-host-trigger-rollback-${stamp}"
  mkdir -p "$out"
  while read -r u; do
    if [[ -e "${UNIT_DIR}/${u}" ]]; then mv "${UNIT_DIR}/${u}" "${out}/${u}"; echo "archived ${u} -> ${out}/"; fi
  done < <(units)
  local reenable=()
  if [[ -n "$ARCHIVE" ]]; then
    while read -r _ u was; do
      cp -p "${ARCHIVE}/${u}" "${UNIT_DIR}/${u}"
      echo "restored ${u} from ${ARCHIVE}"
      if [[ "$u" == *.timer && "$was" == "enabled" ]]; then reenable+=("$u"); fi
    done < <(grep '^archived ' "${ARCHIVE}/MANIFEST" || true)
  fi
  systemctl --user daemon-reload
  if [[ ${#reenable[@]} -gt 0 ]]; then systemctl --user enable --now "${reenable[@]}"; fi
  systemctl --user list-timers --all 'tradeai-release-train-request@*' 'tradeai-pr-census@*' --no-pager || true
  echo "rolled back. Removed units are archived (never deleted) in ${out}"
}

case "$MODE" in
  --preview) preview ;;
  --apply) apply ;;
  *) echo "usage: $0 [--preview|--apply [--archive DIR]]"; exit 2 ;;
esac
