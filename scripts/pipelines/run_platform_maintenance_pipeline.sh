#!/usr/bin/env bash
# run_platform_maintenance_pipeline.sh — cron consolidation RANK 4: the platform maintenance pipeline.
#
# Absorbs the nightly / weekly / monthly platform-maintenance crontab lines (log rotation, performance
# context, conformance report, integrity sweep, strategy sync, retention purges, n8n lab backup,
# db_retention, mention pruning, docs retention, restore drill, version check, backup verify,
# transcript purge) into ONE serial runner per cadence. Each step keeps the args, env vars, lock file
# and timeout its crontab line carried, in the order the clock times implied.
#
#   --cadence {nightly|weekly|monthly}   (required)
#   --dry-run (default) | --apply
#   --manifest FILE   override the built-in step table (tests; also PLATFORM_MAINT_MANIFEST=FILE)
#
# Step table line format (built-in or manifest): name|timeout|lock|guard|log|env|cmd
#   timeout  GNU `timeout` duration (e.g. 30m); empty = PLATFORM_MAINT_DEFAULT_TIMEOUT (60m)
#   lock     absolute flock path; the SAME /tmp path the cron line used, so a leftover cron line and
#            this runner cannot double-run the step (flock -n -E 75 -> recorded as skipped_lock)
#   guard    file relative to PROJ that must exist or the step is recorded skipped_missing
#   log      the cron line's own log file (relative to PROJ or absolute); step output is appended there
#            AND tailed into the pipeline log, so nothing that read the old log goes dark
#   env      space-separated K=V pairs prepended with `env` (the cron line's inline variables)
#   cmd      the command, run as `bash -c "cd $PROJ && <cmd>"`
#
# Continue-on-error: a failing step is recorded (rc, duration_s, timed_out) and the next step runs.
# Summary (the lane's output_signal): data/runtime/platform_maintenance_<cadence>_last.json
# schema PlatformMaintenanceRun@v1. --dry-run prints the plan and writes NOTHING (no log, no summary).
#
# Kept OUT on purpose (see docs/implementation/n8n-parallel/proposals/cron-rank4-maintenance-pipeline.md):
#   ~/.claude/sync-memory-to-drive.sh (different tree), sweep_schwab_instruments.py (broker-adjacent),
#   hourly Drive syncs (rank 18), portfolio-maintenance cadences (their own runner).
# NEVER: broker/order/proposal/protection/trading, live, Level 7. db_retention keeps its own internal
# disk-floor guard — this runner does not bypass it.
set -euo pipefail
PROJ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=/dev/null
source "$PROJ/scripts/pipelines/_pipeline_common.sh"   # load_env, assert_*, _ts, DRY_RUN parse (--apply/--dry-run)

usage() {
  sed -n '2,25p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

CADENCE=""
MANIFEST="${PLATFORM_MAINT_MANIFEST:-}"
while [ $# -gt 0 ]; do
  case "$1" in
    --cadence)  CADENCE="${2:-}"; shift 2 ;;
    --manifest) MANIFEST="${2:-}"; shift 2 ;;
    --apply|--dry-run) shift ;;            # consumed by _pipeline_common.sh
    -h|--help) usage; exit 0 ;;
    *) echo "[ERROR] unknown argument: $1" >&2; usage >&2; exit 64 ;;
  esac
done
VALID_CADENCES="nightly weekly monthly"
if [ -z "$CADENCE" ]; then
  echo "[ERROR] --cadence required (one of: $VALID_CADENCES)" >&2; exit 64
fi
if ! printf '%s\n' $VALID_CADENCES | grep -qx "$CADENCE"; then
  echo "[ERROR] invalid --cadence '$CADENCE' (one of: $VALID_CADENCES)" >&2; exit 64
fi
if [ -n "$MANIFEST" ] && [ ! -f "$MANIFEST" ]; then
  echo "[ERROR] --manifest '$MANIFEST' not found" >&2; exit 64
fi

# --- interpreter: the crontab sets PY to the dev-tree venv; CURRENT carries no .venv of its own ---
resolve_py() {
  if [ -n "${TRADEAI_PY:-}" ]; then echo "$TRADEAI_PY"; return; fi
  if [ -x "$PROJ/.venv/bin/python" ]; then echo "$PROJ/.venv/bin/python"; return; fi
  local cron_py="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python"
  if [ -x "$cron_py" ]; then echo "$cron_py"; return; fi
  command -v python3
}
PY="$(resolve_py)"
STATE_ROOT="${TRADEAI_STATE_ROOT:-$HOME/trade-ai-releases/persistent-state}"
DEFAULT_TIMEOUT="${PLATFORM_MAINT_DEFAULT_TIMEOUT:-60m}"
LOCK_DIR="${PLATFORM_MAINT_LOCK_DIR:-/tmp}"

served_sha() {
  if [ -f "$PROJ/GIT_SHA" ]; then tr -d '[:space:]' < "$PROJ/GIT_SHA"; return; fi
  git -C "$PROJ" rev-parse HEAD 2>/dev/null || echo unknown
}
SERVED_SHA="$(served_sha)"

# --- step table ---
declare -a STEP_NAME STEP_TIMEOUT STEP_LOCK STEP_GUARD STEP_LOG STEP_ENV STEP_CMD
add_step() {  # name timeout lock guard log env cmd
  STEP_NAME+=("$1"); STEP_TIMEOUT+=("${2:-$DEFAULT_TIMEOUT}"); STEP_LOCK+=("$3"); STEP_GUARD+=("$4")
  STEP_LOG+=("$5"); STEP_ENV+=("$6"); STEP_CMD+=("$7")
}
load_manifest() {
  local line name tmo lock guard log env cmd n=0
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|'#'*) continue ;; esac
    IFS='|' read -r name tmo lock guard log env cmd <<< "$line"
    if [ -z "$name" ] || [ -z "$cmd" ]; then
      echo "[ERROR] manifest line needs name and cmd: $line" >&2; exit 65
    fi
    add_step "$name" "$tmo" "$lock" "$guard" "$log" "$env" "$cmd"; n=$((n+1))
  done < "$MANIFEST"
  [ "$n" -gt 0 ] || { echo "[ERROR] manifest has no steps: $MANIFEST" >&2; exit 65; }
}

# Built-in tables. Each line cites the crontab line (crontab -l of 2026-10-07) it absorbs VERBATIM:
# args, inline env, lock path and timeout preserved; order = the clock order of the lines.
build_nightly() {
  # 713: 15 1 * * * cd $PROJ && flock -n /tmp/tradeai_rotate_logs.lock bash scripts/rotate_runtime_logs.sh >> logs/rotate_runtime_logs.log
  add_step rotate_runtime_logs "" /tmp/tradeai_rotate_logs.lock "" logs/rotate_runtime_logs.log "" \
    "bash scripts/rotate_runtime_logs.sh"
  # 207: 30 2 * * * cd CURRENT && $PY scripts/populate_performance_context.py --apply >> logs/perf_context.log
  add_step populate_performance_context "" "" "" logs/perf_context.log "" \
    "$PY scripts/populate_performance_context.py --apply"
  # 1045: 30 2 * * * cd $PROJ && TRADEAI_STATE_ROOT=$HOME/trade-ai-releases/persistent-state TRADEAI_RELEASE_SHA=$(cat $PROJ/GIT_SHA)
  #       flock -n /tmp/tradeai_platform_conformance.lock $PY scripts/report_platform_conformance.py --write >> $HOME/trade-ai-releases/persistent-state/logs/platform_conformance.log
  add_step report_platform_conformance "" /tmp/tradeai_platform_conformance.lock "" "$STATE_ROOT/logs/platform_conformance.log" \
    "TRADEAI_STATE_ROOT=$STATE_ROOT TRADEAI_RELEASE_SHA=$SERVED_SHA" \
    "$PY scripts/report_platform_conformance.py --write"
  # 495: 45 2 * * * cd $PROJ && $PY scripts/nightly_integrity_sweep.py --telegram >> logs/integrity_sweep.log
  add_step nightly_integrity_sweep "" "" "" logs/integrity_sweep.log "" \
    "$PY scripts/nightly_integrity_sweep.py --telegram"
  # 162: 0 3 * * * cd CURRENT && $PY scripts/strategy_config_loader.py --sync-db >> logs/strategy_config_sync.log
  add_step strategy_config_sync "" "" "" logs/strategy_config_sync.log "" \
    "$PY scripts/strategy_config_loader.py --sync-db"
  # 417: 10 3 * * * cd $PROJ && $PY scripts/siem_retention_purge.py >> logs/siem_retention_purge.log
  add_step siem_retention_purge "" "" "" logs/siem_retention_purge.log "" \
    "$PY scripts/siem_retention_purge.py"
  # 1023: 25 3 * * * cd $PROJ && flock -n /tmp/hermes_universe_history_retention.lock $PY scripts/hermes_universe_history_retention.py --apply >> logs/hermes_universe_history_retention.log
  add_step hermes_universe_history_retention "" /tmp/hermes_universe_history_retention.lock "" logs/hermes_universe_history_retention.log "" \
    "$PY scripts/hermes_universe_history_retention.py --apply"
  # 1076: 30 3 * * * cd $PROJ && bash scripts/n8n_lab_backup.sh --apply >> /home/johnclaw/trade-ai-releases/persistent-state/logs/n8n_lab_backup.log
  add_step n8n_lab_backup "" "" "" "$STATE_ROOT/logs/n8n_lab_backup.log" "" \
    "bash scripts/n8n_lab_backup.sh --apply"
  # 961: 10 4 * * * cd CURRENT && flock -n /tmp/db_retention.lock timeout 30m $PY scripts/db_retention.py >> CURRENT/logs/db_retention.log
  #      (db_retention keeps its internal disk-floor guard; the runner adds nothing and bypasses nothing)
  add_step db_retention 30m /tmp/db_retention.lock "" logs/db_retention.log "" \
    "$PY scripts/db_retention.py"
  # 957: 40 4 * * * cd CURRENT && flock -n /tmp/document_mentions_prune.lock timeout 20m $PY scripts/prune_document_mentions.py --apply >> CURRENT/logs/document_mentions_prune.log
  add_step prune_document_mentions 20m /tmp/document_mentions_prune.lock "" logs/document_mentions_prune.log "" \
    "$PY scripts/prune_document_mentions.py --apply"
  # NEW (04:50): report_db_hygiene.py --write lands with wt/db-retention-durable-20261007; guarded until it is on the served tree.
  add_step report_db_hygiene "" "" scripts/report_db_hygiene.py logs/db_hygiene.log "" \
    "$PY scripts/report_db_hygiene.py --write"
}
build_weekly() {
  # 494: 0 3 * * 0 cd $PROJ && bash scripts/docs_retention.sh >> logs/docs_retention.log
  add_step docs_retention "" "" "" logs/docs_retention.log "" \
    "bash scripts/docs_retention.sh"
  # 1077: 0 4 * * 0 cd $PROJ && bash scripts/n8n_lab_restore_drill.sh --apply >> /home/johnclaw/trade-ai-releases/persistent-state/logs/n8n_lab_restore_drill.log
  add_step n8n_lab_restore_drill "" "" "" "$STATE_ROOT/logs/n8n_lab_restore_drill.log" "" \
    "bash scripts/n8n_lab_restore_drill.sh --apply"
  # 372: 0 6 * * 0 /bin/bash CURRENT/scripts/check_system_versions.sh >> /home/johnclaw/logs/version_check.log
  add_step check_system_versions "" "" "" "$HOME/logs/version_check.log" "" \
    "/bin/bash scripts/check_system_versions.sh"
}
build_monthly() {
  # 166: 0 6 1 * * cd $PROJ && flock -n /tmp/backup_verify.lock $PY scripts/backup_verify.py >> logs/backup_verify.log
  add_step backup_verify "" /tmp/backup_verify.lock "" logs/backup_verify.log "" \
    "$PY scripts/backup_verify.py"
  # 163: 0 3 1 * * cd $PROJ && $PY -c "...set_purge_dates()" && $PY -c "...DELETE FROM youtube_transcripts WHERE purge_after < CURRENT_DATE..." >> logs/transcript_purge.log
  #      The two inline -c programs are now scripts/purge_youtube_transcripts.py (--apply = the cron's behaviour).
  add_step youtube_transcript_purge "" "" "" logs/transcript_purge.log "" \
    "$PY scripts/purge_youtube_transcripts.py --apply"
}

if [ -n "$MANIFEST" ]; then
  load_manifest
else
  case "$CADENCE" in
    nightly) build_nightly ;;
    weekly)  build_weekly ;;
    monthly) build_monthly ;;
  esac
fi

# --- dry run: print the plan, write nothing, touch no lock ---
if [ "$DRY_RUN" = "1" ]; then
  echo "[$(_ts)] DRY_RUN platform-maintenance cadence=$CADENCE served_sha=$SERVED_SHA proj=$PROJ py=$PY"
  echo "[plan] pipeline lock: $LOCK_DIR/pipeline_platform-maintenance-$CADENCE.lock (not taken in dry-run)"
  echo "[plan] summary would be: $PROJ/data/runtime/platform_maintenance_${CADENCE}_last.json (not written in dry-run)"
  for i in "${!STEP_NAME[@]}"; do
    g=""
    if [ -n "${STEP_GUARD[$i]}" ] && [ ! -f "$PROJ/${STEP_GUARD[$i]}" ]; then g=" GUARD_MISSING(${STEP_GUARD[$i]})->would skip"; fi
    echo "  [$((i+1))] step=${STEP_NAME[$i]} timeout=${STEP_TIMEOUT[$i]} lock=${STEP_LOCK[$i]:-none} env=${STEP_ENV[$i]:-none} log=${STEP_LOG[$i]:-none}$g"
    echo "       would run: cd $PROJ && ${STEP_CMD[$i]}"
  done
  echo "[$(_ts)] DRY_RUN END steps=${#STEP_NAME[@]} (nothing executed, nothing written)"
  exit 0
fi

# --- apply: log, env, safety, pipeline lock ---
LOG_DIR="$PROJ/logs/pipelines/platform-maintenance/$CADENCE"; mkdir -p "$LOG_DIR"
RUN_TS="$(date -u +%Y%m%d_%H%M%S)"
RUN_LOG="$LOG_DIR/platform_${CADENCE}_${RUN_TS}.log"
RUN_DIR="$LOG_DIR/run_${RUN_TS}"; mkdir -p "$RUN_DIR"
SUMMARY="$PROJ/data/runtime/platform_maintenance_${CADENCE}_last.json"; mkdir -p "$(dirname "$SUMMARY")"

exec > >(tee -a "$RUN_LOG") 2>&1
echo "=================================================================="
echo "[$(_ts)] START platform-maintenance cadence=$CADENCE served_sha=$SERVED_SHA log=$RUN_LOG"
load_env
assert_no_live_trading || exit $?
assert_no_level7 || exit $?
echo "[safety] platform maintenance only — no broker/order/proposal/protection/trading ✓"

PIPELINE_LOCK="$LOCK_DIR/pipeline_platform-maintenance-$CADENCE.lock"
exec {PIPELINE_LOCK_FD}>"$PIPELINE_LOCK"
if ! flock -n "$PIPELINE_LOCK_FD"; then
  echo "[lock] platform-maintenance-$CADENCE already running ($PIPELINE_LOCK held) — skipping this invocation" >&2
  exit 0   # already-running is a clean skip, not a failure (same contract as acquire_lock)
fi
echo "[lock] acquired $PIPELINE_LOCK"
cd "$PROJ"

declare -a R_NAME R_RC R_DUR R_TMO R_TIMED_OUT R_SKIP_LOCK R_SKIP_MISSING
FAILED=()
SKIPPED=()

run_step() {
  local i="$1"
  local name="${STEP_NAME[$i]}" tmo="${STEP_TIMEOUT[$i]}" lock="${STEP_LOCK[$i]}" guard="${STEP_GUARD[$i]}"
  local slog="${STEP_LOG[$i]}" senv="${STEP_ENV[$i]}" cmd="${STEP_CMD[$i]}"
  local rc=0 start end dur timed_out=false skipped_lock=false skipped_missing=false
  local out="$RUN_DIR/${name}.out"
  echo "  ---- step START [$((i+1))/${#STEP_NAME[@]}]: $name timeout=$tmo lock=${lock:-none} ($(_ts)) ----"
  if [ -n "$guard" ] && [ ! -f "$PROJ/$guard" ]; then
    echo "  ---- step SKIP: $name (guard missing: $guard) ----"
    R_NAME+=("$name"); R_RC+=("null"); R_DUR+=("0"); R_TMO+=("$tmo")
    R_TIMED_OUT+=(false); R_SKIP_LOCK+=(false); R_SKIP_MISSING+=(true); SKIPPED+=("$name")
    return 0
  fi
  local -a envarr=()
  if [ -n "$senv" ]; then read -r -a envarr <<< "$senv"; fi
  start=$(date +%s)
  set +e
  if [ -n "$lock" ]; then
    flock -n -E 75 "$lock" timeout --kill-after=30s "$tmo" \
      env ${envarr[@]+"${envarr[@]}"} bash -c "cd \"$PROJ\" && $cmd" >"$out" 2>&1
  else
    timeout --kill-after=30s "$tmo" \
      env ${envarr[@]+"${envarr[@]}"} bash -c "cd \"$PROJ\" && $cmd" >"$out" 2>&1
  fi
  rc=$?
  set -e
  end=$(date +%s); dur=$((end - start))
  if [ -n "$slog" ]; then
    case "$slog" in /*) ;; *) slog="$PROJ/$slog" ;; esac
    mkdir -p "$(dirname "$slog")" 2>/dev/null || true
    { echo "[$(_ts)] platform-maintenance/$CADENCE step=$name rc=$rc"; cat "$out"; } >> "$slog" 2>/dev/null || \
      echo "  [warn] could not append step output to $slog"
  fi
  if [ "$rc" = "75" ] && [ -n "$lock" ]; then
    skipped_lock=true; SKIPPED+=("$name")
    echo "  ---- step SKIP: $name (lock held: $lock) ----"
  else
    if [ "$rc" = "124" ] || [ "$rc" = "137" ]; then timed_out=true; fi
    if [ "$rc" != "0" ]; then FAILED+=("$name"); fi
    echo "  ---- step output tail ($name, last 40 lines of $out) ----"
    tail -n 40 "$out" | sed 's/^/    | /'
    echo "  ---- step END: $name rc=$rc duration_s=$dur timed_out=$timed_out ----"
  fi
  R_NAME+=("$name"); R_RC+=("$rc"); R_DUR+=("$dur"); R_TMO+=("$tmo")
  R_TIMED_OUT+=("$timed_out"); R_SKIP_LOCK+=("$skipped_lock"); R_SKIP_MISSING+=("$skipped_missing")
  return 0
}

for i in "${!STEP_NAME[@]}"; do
  run_step "$i"
done

_jesc() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'; }
_jlist() { local out="" x; for x in "$@"; do out="$out$([ -n "$out" ] && echo ", ")\"$(_jesc "$x")\""; done; printf '[%s]' "$out"; }
OK=true; [ "${#FAILED[@]}" -eq 0 ] || OK=false
{
  echo "{"
  echo "  \"schema\": \"PlatformMaintenanceRun@v1\","
  echo "  \"as_of\": \"$(_ts)\","
  echo "  \"served_sha\": \"$(_jesc "$SERVED_SHA")\","
  echo "  \"cadence\": \"$CADENCE\","
  echo "  \"dry_run\": false,"
  echo "  \"pipeline_log\": \"$(_jesc "$RUN_LOG")\","
  echo "  \"run_dir\": \"$(_jesc "$RUN_DIR")\","
  echo "  \"steps\": ["
  for i in "${!R_NAME[@]}"; do
    sep=$([ "$i" -lt $((${#R_NAME[@]}-1)) ] && echo "," || echo "")
    echo "    {\"step\": \"$(_jesc "${R_NAME[$i]}")\", \"rc\": ${R_RC[$i]}, \"duration_s\": ${R_DUR[$i]}, \"timeout\": \"${R_TMO[$i]}\", \"timed_out\": ${R_TIMED_OUT[$i]}, \"skipped_lock\": ${R_SKIP_LOCK[$i]}, \"skipped_missing\": ${R_SKIP_MISSING[$i]}, \"lock\": \"$(_jesc "${STEP_LOCK[$i]}")\", \"cmd\": \"$(_jesc "${STEP_CMD[$i]}")\"}$sep"
  done
  echo "  ],"
  echo "  \"ok\": $OK,"
  echo "  \"failed_steps\": $(_jlist ${FAILED[@]+"${FAILED[@]}"}),"
  echo "  \"skipped_steps\": $(_jlist ${SKIPPED[@]+"${SKIPPED[@]}"})"
  echo "}"
} > "$SUMMARY.tmp"
mv -f "$SUMMARY.tmp" "$SUMMARY"
echo "[summary] wrote $SUMMARY ok=$OK failed=${#FAILED[@]} skipped=${#SKIPPED[@]}"
echo "[$(_ts)] END platform-maintenance cadence=$CADENCE ok=$OK"
# The summary is the signal (AGENTS.md §0.8); exit 0 keeps a degraded night from churning the timer
# into a failed unit. Set PLATFORM_MAINT_EXIT_ON_FAIL=1 to surface failures as a nonzero exit.
if [ "$OK" = "false" ] && [ "${PLATFORM_MAINT_EXIT_ON_FAIL:-0}" = "1" ]; then exit 1; fi
exit 0
