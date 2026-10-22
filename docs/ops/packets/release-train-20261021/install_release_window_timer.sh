#!/usr/bin/env bash
# install_release_window_timer.sh — OPERATOR ONLY (AGENTS §17: any new production systemd entry).
#
# Schedules scripts/release_window.py run at 12:00 and 17:30 America/New_York as a user systemd timer + oneshot
# service. DRY RUN BY DEFAULT: prints the two unit files and the commands it would run, writes nothing.
#
#   bash install_release_window_timer.sh                       # dry run (default)
#   TRADEAI_OPERATOR_INSTALL=1 bash install_release_window_timer.sh --apply
#   TRADEAI_OPERATOR_INSTALL=1 bash install_release_window_timer.sh --disable   # stop + archive units (never delete)
#
# Why a host timer and not n8n: AGENTS §23.3 / §23.14 and tests/test_n8n_run_allowlist_20261008.py forbid
# release-deploy commands (deploy, promote, cio_phase2_exact_main_deploy) on the n8n allowlist, and promote restarts
# tradeai-n8n-run-executor / -coordination-gateway / -run-relay, so an executor child would be killed mid-promote.
#
# The timer only STARTS the runner. Nothing releases without an operator release-write grant naming the window
# (RELEASE_WINDOW release-window-<YYYYMMDD>-<HHMM> or RELEASE_WINDOW <date> <window>); without one every window
# exits DISARMED (exit 2) and leaves only last.json. No broker, no credential read.
#
# SUPERSEDED 2026-10-21 (release-train arming finding 7). The Release Train v2 windows are 18:00, 00:00, 06:00 and
# 08:00 ET, answered by the claimer units (docs/ops/packets/release-train-arming-20261021/README.md step D). Installing
# this 12:00/17:30 timer beside them would create a second release path, so --apply is REFUSED. The dry run still
# prints what it used to install (for review), and --disable still archives an already-installed copy.
set -euo pipefail

SUPERSEDED_BY="docs/ops/packets/release-train-arming-20261021/README.md (step D: tradeai-release-train-claim.{service,path,timer})"
MODE="${1:---dry-run}"
UNIT_DIR="${HOME}/.config/systemd/user"
NAME="tradeai-release-window"
CANONICAL="${CANONICAL_SOURCE:-/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild}"
CHECKOUT="${TRADEAI_RELEASE_CHECKOUT:-${HOME}/tradeai-exact-main-20260827}"
PY="${CANONICAL}/.venv/bin/python"
RUNNER="${CHECKOUT}/scripts/release_window.py"

service_unit() {
  cat <<EOF
# ${UNIT_DIR}/${NAME}.service — release train window run (docs/ops/packets/release-train-20261021/)
[Unit]
Description=Trade AI release window (12:00 / 17:30 ET): release main's newest green SHA under a window grant
After=network-online.target

[Service]
Type=oneshot
# The runner is read from the RELEASE checkout (reviewed origin/main code with a git remote), never the dev tree.
WorkingDirectory=${CHECKOUT}
ExecStart=${PY} ${RUNNER} run
# prepare (frontend build + venv) + promote + verify + a possible rollback.
TimeoutStartSec=5400
# A non-zero exit (2 disarmed/refused, 3 stopped, 4 rolled back, 5 rollback failed) is a receipt, not a crash
# loop: the unit is oneshot and the timer fires again only at the next window.
SuccessExitStatus=2 3
EOF
}

timer_unit() {
  cat <<EOF
# ${UNIT_DIR}/${NAME}.timer
[Unit]
Description=Trade AI release windows 12:00 and 17:30 America/New_York

[Timer]
OnCalendar=*-*-* 12:00:00 America/New_York
OnCalendar=*-*-* 17:30:00 America/New_York
# A missed window is skipped, never replayed late (the runner also refuses off-window: REFUSED_OFF_WINDOW).
Persistent=false
AccuracySec=30s
Unit=${NAME}.service

[Install]
WantedBy=timers.target
EOF
}

preflight() {
  local ok=1
  [[ -x "$PY" ]] || { echo "PREFLIGHT: missing interpreter $PY"; ok=0; }
  [[ -f "$RUNNER" ]] || { echo "PREFLIGHT: missing runner $RUNNER"; ok=0; }
  if [[ -f "$RUNNER" ]] && ! grep -q "REQUIRED_TRAIN_WORKFLOWS" "$RUNNER"; then
    echo "PREFLIGHT: $RUNNER predates the release train (merge + release the release-train PR first)"; ok=0
  fi
  if [[ -f "${CHECKOUT}/scripts/cio_phase2_exact_main_deploy.sh" ]] \
      && ! grep -q "TRADEAI_RELEASE_TRAIN_SHA" "${CHECKOUT}/scripts/cio_phase2_exact_main_deploy.sh"; then
    echo "PREFLIGHT: the release checkout's deploy script predates the release train"; ok=0
  fi
  [[ "$ok" == 1 ]] && echo "PREFLIGHT: OK (runner + deploy script carry the release-train code)"
  [[ "$ok" == 1 ]]
}

case "$MODE" in
  --dry-run)
    echo "== SUPERSEDED: --apply is refused; the release train is installed by ${SUPERSEDED_BY} =="
    echo "== DRY RUN: nothing is written. Units that --apply would have installed =="
    service_unit; echo; timer_unit; echo
    echo "== --apply would run =="
    echo "  install -m 0644 <service> ${UNIT_DIR}/${NAME}.service"
    echo "  install -m 0644 <timer>   ${UNIT_DIR}/${NAME}.timer"
    echo "  systemctl --user daemon-reload"
    echo "  systemctl --user enable --now ${NAME}.timer"
    echo "  systemctl --user list-timers ${NAME}.timer"
    echo "== read-only preflight =="
    preflight || echo "(dry run: preflight failures above would refuse --apply)"
    echo "== read-only plan of the next window =="
    if [[ -x "$PY" && -f "$RUNNER" ]]; then
      (cd "$CHECKOUT" && "$PY" "$RUNNER" plan --window 1730 || true) | head -40
    fi
    ;;
  --apply)
    echo "refused: SUPERSEDED. The 12:00/17:30 release_window timer must not run beside the release train"
    echo "  (two release paths). Install the train claimer instead: ${SUPERSEDED_BY}"
    exit 2
    # Unreachable below: kept so the reviewed history of what this used to do stays readable.
    # shellcheck disable=SC2317
    [[ "${TRADEAI_OPERATOR_INSTALL:-}" == "1" ]] || { echo "refused: set TRADEAI_OPERATOR_INSTALL=1 (operator only, AGENTS §17)"; exit 2; }
    preflight || { echo "refused: preflight failed"; exit 2; }
    mkdir -p "$UNIT_DIR"
    service_unit | sed '1d' > "${UNIT_DIR}/${NAME}.service"
    timer_unit | sed '1d' > "${UNIT_DIR}/${NAME}.timer"
    systemctl --user daemon-reload
    systemctl --user enable --now "${NAME}.timer"
    systemctl --user list-timers "${NAME}.timer" --no-pager
    echo "installed. Arm a window with a release-write grant (README §5); unarmed windows exit DISARMED."
    ;;
  --disable)
    [[ "${TRADEAI_OPERATOR_INSTALL:-}" == "1" ]] || { echo "refused: set TRADEAI_OPERATOR_INSTALL=1"; exit 2; }
    systemctl --user disable --now "${NAME}.timer" || true
    stamp="$(date -u +%Y%m%dT%H%M%SZ)"
    archive="${UNIT_DIR}/archived-${NAME}-${stamp}"
    mkdir -p "$archive"
    for f in "${UNIT_DIR}/${NAME}.service" "${UNIT_DIR}/${NAME}.timer"; do
      [[ -f "$f" ]] && mv "$f" "$archive/"
    done
    systemctl --user daemon-reload
    echo "disabled; units archived (never deleted) in $archive"
    ;;
  *)
    echo "usage: $0 [--dry-run|--apply|--disable]"; exit 2 ;;
esac
