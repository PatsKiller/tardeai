#!/usr/bin/env bash
# _manifest_runner.sh — shared manifest-driven stage runner for cron tranche B (ranks 5-7).
#
# Sourced by run_after_close_pipeline.sh, run_premarket_data_pipeline.sh and run_hermes_pipeline.sh.
# A manifest (config/pipelines/<name>.json, PipelineManifest@v1) lists per stage the crontab lines
# the stage absorbs; each step's `command` is the VERBATIM cron command with its own lock, timeout,
# env and LLM wrapper (run_with_deepseek_offpeak.sh / llm_priority_guard.sh) kept inside the step.
#
# Safety contract (AGENTS.md §0 rail 7 — dry-run before any live run):
#   * --dry-run is the default: the plan is printed, NOTHING is executed.
#   * --apply executes the stage's steps ONLY when the manifest has at least one step for the
#     stage; an empty plan writes an `overall_status: "empty"` summary and runs nothing.
#   * one flock per stage (/tmp/pipeline_<pipeline>-<stage>.lock); an already-running stage is a
#     clean skip, not a failure.
#   * every step: its own flock, `timeout -k 30 <timeout>`, stdout/stderr appended to the SAME log
#     file the cron line used, a PipelineStepReceipt@v1 line, and continue-on-error (a failed step
#     never aborts the stage; it is recorded).
#   * the stage never wraps itself in an LLM guard or off-peak wrapper (cap accounting stays per step).
#   * summary JSON (PipelineRun@v1) at data/runtime/pipeline_<pipeline>_<stage>_last.json is the
#     lane's output_signal: it is written on every invocation, dry-run included.
#
# Usage (from a runner):   manifest_pipeline_main <default-manifest-relpath> "$@"
#   --stage NAME          stage to run (required unless the manifest has exactly one stage)
#   --manifest PATH       override the manifest path
#   --dry-run | --apply   default --dry-run
#   --project-root DIR    tests only: run against DIR instead of the checkout (logs, data, cwd)
#   --list-stages         print the manifest's stages and exit
set -euo pipefail

_MR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$_MR_DIR/_pipeline_common.sh"      # PROJ, load_env, assert_*, _ts, acquire_lock, DRY_RUN parse
MANIFEST_PY="$_MR_DIR/pipeline_manifest.py"

_mr_resolve_py() {
  local cand
  for cand in "${PY:-}" "$PROJ/.venv/bin/python" "$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python"; do
    [ -n "$cand" ] && [ -x "$cand" ] && { echo "$cand"; return 0; }
  done
  command -v python3
}

# The environment cron gave THIS runner, captured before anything here touches it. A step receives only the
# names its manifest `env` block lists (cron base + the crontab NAME=value lines that precede its own line), with
# the values cron gave the runner; PROJ and PY are the runner's resolved values (equal under cron).
declare -A _MR_CRON_ENV=()
for _mr_n in $(compgen -e); do _MR_CRON_ENV[$_mr_n]="${!_mr_n}"; done
unset _mr_n

_mr_step_env() {
  local names="$1" n
  [ -n "$names" ] || names="HOME,LANG,LOGNAME,PATH,SHELL,PROJ"
  stepenv=()
  for n in ${names//,/ }; do
    case "$n" in
      PROJ) stepenv+=("PROJ=$PROJ") ;;
      PY) stepenv+=("PY=$PY") ;;
      *) [ -n "${_MR_CRON_ENV[$n]+x}" ] && stepenv+=("$n=${_MR_CRON_ENV[$n]}") ;;
    esac
  done
  return 0
}

# Safety flags only. The corrupted-.env pre-flight is kept (fail loudly, EX_CONFIG); the values of these six
# names are read in a throwaway process and set as NON-exported shell variables; nothing else leaves .env.
_mr_load_safety_env() {
  [ -f "$PROJ/.env" ] || return 0
  if ! bash -c 'set -euo pipefail; set -a; . "$1"; set +a' _ "$PROJ/.env" >/dev/null 2>"$PROJ/logs/env_source_error.txt"; then
    echo "[FATAL] $PROJ/.env failed to source — file is corrupted (see logs/env_source_error.txt). Refusing to run." >&2
    return 78
  fi
  rm -f "$PROJ/logs/env_source_error.txt"
  local flags
  flags="$(bash -c 'set -a; . "$1" >/dev/null 2>&1; set +a
    for n in ALPACA_MODE LIVE_TRADING_ENABLED LIVE_TRADING LEVEL7 LEVEL_7 ENABLE_LEVEL7; do
      [ -n "${!n+x}" ] && printf "%s=%q\n" "$n" "${!n}"; done' _ "$PROJ/.env")" || true
  eval "$flags"
  return 0
}

manifest_pipeline_main() {
  local default_manifest="$1"; shift
  local STAGE="" MANIFEST="" APPLY_REQUESTED=0 LIST=0
  while [ $# -gt 0 ]; do
    case "$1" in
      --stage) STAGE="${2:-}"; shift 2 ;;
      --stage=*) STAGE="${1#--stage=}"; shift ;;
      --manifest) MANIFEST="${2:-}"; shift 2 ;;
      --manifest=*) MANIFEST="${1#--manifest=}"; shift ;;
      --project-root) PROJ="$(cd "${2:?--project-root needs a directory}" && pwd)"; shift 2 ;;
      --apply) APPLY_REQUESTED=1; DRY_RUN=0; shift ;;
      --dry-run) DRY_RUN=1; shift ;;
      --list-stages) LIST=1; shift ;;
      -h|--help) sed -n '2,30p' "${BASH_SOURCE[0]}"; return 0 ;;
      *) echo "[ERROR] unknown argument: $1" >&2; return 64 ;;
    esac
  done
  [ -n "$MANIFEST" ] || MANIFEST="$PROJ/$default_manifest"
  [ -f "$MANIFEST" ] || { echo "[ERROR] manifest not found: $MANIFEST" >&2; return 66; }

  local PY3; PY3="$(command -v python3)"
  if ! "$PY3" "$MANIFEST_PY" "$MANIFEST" --validate >/dev/null; then
    "$PY3" "$MANIFEST_PY" "$MANIFEST" --validate >&2 || true
    echo "[ERROR] manifest invalid — refusing to plan or run" >&2; return 65
  fi
  local PIPELINE; PIPELINE="$("$PY3" -c 'import json,sys; print(json.load(open(sys.argv[1]))["pipeline"])' "$MANIFEST")"
  local STAGES; STAGES="$("$PY3" -c 'import json,sys; print(" ".join(json.load(open(sys.argv[1]))["stages"]))' "$MANIFEST")"
  if [ "$LIST" = 1 ]; then
    echo "pipeline=$PIPELINE stages: $STAGES"; return 0
  fi
  if [ -z "$STAGE" ]; then
    if [ "$(wc -w <<<"$STAGES")" = 1 ]; then STAGE="$STAGES"; else
      echo "[ERROR] --stage required (one of: $STAGES)" >&2; return 64; fi
  fi
  local known=0 s
  for s in $STAGES; do [ "$s" = "$STAGE" ] && known=1; done
  if [ "$known" = 0 ]; then
    echo "[ERROR] unknown stage '$STAGE' (one of: $STAGES)" >&2; return 64
  fi

  local NAME="${PIPELINE}-${STAGE}"
  LOG_DIR="$PROJ/logs/pipelines/$PIPELINE"; mkdir -p "$LOG_DIR" "$PROJ/data/runtime"
  local RUN_TS; RUN_TS="$(date -u +%Y%m%d_%H%M%S)"
  local RUN_LOG="$LOG_DIR/${STAGE}_${RUN_TS}.log"
  local STEPS_JSONL="$LOG_DIR/${STAGE}_steps.jsonl"
  local SUMMARY="$PROJ/data/runtime/pipeline_${PIPELINE}_${STAGE}_last.json"
  local RESULTS; RESULTS="$(mktemp "${TMPDIR:-/tmp}/pipeline_${NAME}_results.XXXXXX")"
  local STARTED_AT; STARTED_AT="$(_ts)"

  exec > >(tee -a "$RUN_LOG") 2>&1
  echo "=================================================================="
  echo "[$STARTED_AT] START pipeline=$PIPELINE stage=$STAGE DRY_RUN=$DRY_RUN manifest=$MANIFEST log=$RUN_LOG"
  # 2026-10-10: the runner no longer sources $PROJ/.env into itself or its steps. It reads ONLY the safety
  # flags below from it (never exported); each step runs under `env -i` with exactly its cron line's env.
  _mr_load_safety_env || return $?
  assert_no_live_trading || return $?
  assert_no_level7 || return $?
  echo "[safety] manifest steps run VERBATIM with their own locks/timeouts/wrappers; no broker, stop, order or market_day_gate line is admissible (pipeline_manifest.FORBIDDEN_COMMAND_TOKENS) ✓"
  acquire_lock "$NAME" || return 0

  export PROJ HOME
  local PY_RESOLVED; PY_RESOLVED="$(_mr_resolve_py)"; export PY="$PY_RESOLVED"
  echo "[env] PROJ=$PROJ PY=$PY"
  local TODAY_DOW="${PIPELINE_TODAY_DOW:-$(date +%w)}"   # cron convention: 0=Sunday

  local plan; plan="$("$PY3" "$MANIFEST_PY" "$MANIFEST" --plan "$STAGE")"
  local n_steps=0
  [ -n "$plan" ] && n_steps="$(printf '%s\n' "$plan" | wc -l)"
  echo "[plan] $n_steps step(s) for stage=$STAGE dow=$TODAY_DOW"

  if [ "$n_steps" = 0 ]; then
    echo "[plan] manifest has no steps for stage=$STAGE — nothing to execute (apply_requested=$APPLY_REQUESTED)"
  fi

  local line id cron_line tmo dow logrel envnames cmd
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    IFS=$'\x1f' read -r id cron_line tmo dow logrel envnames cmd <<<"$line"
    local status rc ms start end
    start=${EPOCHREALTIME/./}
    if [ "$dow" != "*" ] && ! grep -qw -- "$TODAY_DOW" <<<"${dow//,/ }"; then
      status="skipped_dow"; rc=0
      echo "  ---- step $id (L$cron_line) SKIP dow=$TODAY_DOW not in [$dow]"
    elif [ "$DRY_RUN" = "1" ]; then
      status="dry_run"; rc=0
      echo "  ---- step $id (L$cron_line, timeout ${tmo}s, dow=$dow) [DRY_RUN] would run: $cmd"
      echo "       env (env -i, names only): ${envnames}"
    else
      echo "  ---- step $id (L$cron_line, timeout ${tmo}s) START $(_ts) ----"
      local steplog="$RUN_LOG"
      if [ -n "$logrel" ]; then
        case "$logrel" in /*) steplog="$logrel" ;; *) steplog="$PROJ/$logrel" ;; esac
        steplog="${steplog//\$HOME/$HOME}"; steplog="${steplog//\$PROJ/$PROJ}"
        mkdir -p "$(dirname "$steplog")" 2>/dev/null || steplog="$RUN_LOG"
      fi
      set +e
      local -a stepenv=()
      _mr_step_env "$envnames"
      env -i "${stepenv[@]}" flock -n "/tmp/pipeline_step_${PIPELINE}_${id}.lock" \
        timeout -k 30 "${tmo}s" bash -c "cd \"\$PROJ\" && $cmd" < /dev/null >> "$steplog" 2>&1
      rc=$?
      set -e
      case "$rc" in
        0) status="ok" ;;
        124|137) status="timeout" ;;
        *) status="failed" ;;
      esac
      echo "  ---- step $id END status=$status rc=$rc log=$steplog ----"
    fi
    end=${EPOCHREALTIME/./}; ms=$(( (end - start) / 1000 ))
    "$PY3" - "$RESULTS" "$STEPS_JSONL" "$PIPELINE" "$STAGE" "$id" "$cron_line" "$status" "$rc" "$ms" "$tmo" "$DRY_RUN" <<'PY'
import json, sys, datetime
res, jsonl, pipeline, stage, sid, cron_line, status, rc, ms, tmo, dry = sys.argv[1:]
rec = {"schema": "PipelineStepReceipt@v1", "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
       "pipeline": pipeline, "stage": stage, "id": sid, "cron_line": int(cron_line), "status": status,
       "rc": int(rc), "ms": int(ms), "timeout_s": int(tmo), "dry_run": dry == "1"}
line = json.dumps(rec) + "\n"
open(res, "a").write(line)
open(jsonl, "a").write(line)
PY
  done <<<"$plan"

  local -a sumflags=()
  [ "$DRY_RUN" = 1 ] && sumflags+=(--dry-run)
  [ "$APPLY_REQUESTED" = 1 ] && sumflags+=(--apply-requested)
  "$PY3" "$MANIFEST_PY" "$MANIFEST" --summary "$STAGE" --results "$RESULTS" --out "$SUMMARY" \
      --started-at "$STARTED_AT" --log "$RUN_LOG" "${sumflags[@]}"
  rm -f "$RESULTS"
  echo "[summary] wrote $SUMMARY"
  echo "[$(_ts)] END pipeline=$PIPELINE stage=$STAGE DRY_RUN=$DRY_RUN steps=$n_steps"
  return 0
}
