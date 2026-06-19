#!/bin/bash
# verify_hermes_daily_commit_cron.sh — READ-ONLY verifier for the Hermes daily auto-commit cron path
# (operator 2026-06-19). Confirms the cron + script + safety patterns + observability are installed.
# It NEVER stages, commits, pushes, syncs Drive, edits crontab, or runs the auto-commit job. Read-only.
# Exit: 0 = all required pass (warnings allowed), 1 = blocker, 2 = verifier error.
set -uo pipefail

PROJ="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
SCRIPT="scripts/commit_hermes_daily.sh"
LOGFILE="logs/commit_hermes_daily.log"
JSON=0; [ "${1:-}" = "--json" ] && JSON=1

ROWS=()   # each: "name<TAB>STATUS<TAB>detail"
add() { ROWS+=("$1	$2	$3"); }

# Verifier-error guard: project root must exist and be enterable
if [ ! -d "$PROJ" ] || ! cd "$PROJ" 2>/dev/null; then
  echo "verifier_error: cannot enter project root $PROJ" >&2
  exit 2
fi

# 1. project root
add project_root PASS "$PROJ"

# 2. commit script exists
if [ -f "$SCRIPT" ]; then add commit_script_exists PASS "$SCRIPT"
else add commit_script_exists FAIL "missing $SCRIPT"; fi

# 3. executable (cron uses 'bash', so absence is a WARN not a blocker)
if [ -x "$SCRIPT" ]; then add commit_script_executable PASS "+x set"
elif [ -f "$SCRIPT" ]; then add commit_script_executable WARN "not +x (cron invokes via 'bash', so not required)"
else add commit_script_executable FAIL "script missing"; fi

# 4/5/6/cron-safety: read the cron line once
CRONLINE="$(crontab -l 2>/dev/null | grep -F 'commit_hermes_daily.sh' | grep -v '^[[:space:]]*#' | head -1)"
if [ -n "$CRONLINE" ]; then add cron_installed PASS "entry present"
else add cron_installed FAIL "no crontab entry for commit_hermes_daily.sh"; fi

if printf '%s' "$CRONLINE" | grep -q '13 23 \* \* \*'; then add cron_schedule PASS "13 23 * * *"
else add cron_schedule FAIL "schedule != '13 23 * * *' (line: ${CRONLINE:-none})"; fi

if printf '%s' "$CRONLINE" | grep -qF 'logs/commit_hermes_daily.log'; then add cron_log_path PASS "logs to $LOGFILE"
else add cron_log_path FAIL "cron line does not redirect to $LOGFILE"; fi

# cron must not contain broad/dangerous staging or commit-all
if printf '%s' "$CRONLINE" | grep -qE 'git add -A|git add --all|git add \.|git commit -a|rm -rf'; then
  add cron_no_dangerous_staging FAIL "cron line contains broad staging / dangerous op"
else add cron_no_dangerous_staging PASS "no broad staging in cron line"; fi

# 6/7/8/9. script safety patterns (read-only grep of the committed script)
sp() { [ -f "$SCRIPT" ] && grep -qF "$1" "$SCRIPT"; }
if sp 'git add docs/hermes/'; then add script_scope_docs_hermes_only PASS "stages only docs/hermes/"
else add script_scope_docs_hermes_only FAIL "missing 'git add docs/hermes/'"; fi

if sp 'portfolio_totals' && sp 'total_value' && sp '1000000'; then add script_iron_guard PASS "IRON holdings guard present"
else add script_iron_guard FAIL "IRON guard (portfolio_totals/total_value/1000000) incomplete"; fi

if grep -qF "grep -v '^docs/hermes/'" "$SCRIPT" 2>/dev/null && sp 'git reset -q'; then
  add script_outside_stage_refusal PASS "refuses paths outside docs/hermes/ (+git reset -q)"
else add script_outside_stage_refusal FAIL "outside-path refusal pattern missing"; fi

if sp 'git push origin main'; then add script_push_origin PASS "pushes origin/main"
else add script_push_origin FAIL "missing 'git push origin main'"; fi

# 13. drive sync script exists + referenced
if [ -f scripts/sync-docs-to-drive.sh ] && sp 'scripts/sync-docs-to-drive.sh'; then
  add drive_sync_script_exists PASS "sync-docs-to-drive.sh present + referenced"
elif [ ! -f scripts/sync-docs-to-drive.sh ]; then add drive_sync_script_exists FAIL "scripts/sync-docs-to-drive.sh missing"
else add drive_sync_script_exists WARN "sync script present but not referenced by commit script"; fi

# 7/8. logs dir + log file
if [ -d logs ] && [ -w logs ]; then
  if [ -f "$LOGFILE" ]; then add log_path PASS "logs/ writable; $LOGFILE exists"
  else add log_path WARN "$LOGFILE not created yet; expected after first scheduled run"; fi
else add log_path FAIL "logs/ missing or not writable"; fi

# 9. git remote origin -> github
ORIGIN="$(git remote get-url origin 2>/dev/null || true)"
if printf '%s' "$ORIGIN" | grep -qiE 'github'; then add git_remote_origin PASS "$ORIGIN"
else add git_remote_origin FAIL "origin not a GitHub URL (${ORIGIN:-none})"; fi

# 10. staged files safe — any staged path outside docs/hermes/ is a blocker (do NOT unstage)
STAGED="$(git diff --cached --name-only 2>/dev/null || true)"
OUTSIDE="$(printf '%s\n' "$STAGED" | grep -v '^$' | grep -v '^docs/hermes/' || true)"
if [ -z "$STAGED" ]; then add staged_files_safe PASS "nothing staged"
elif [ -z "$OUTSIDE" ]; then add staged_files_safe PASS "staged files all under docs/hermes/"
else add staged_files_safe FAIL "unexpected staged files: $(printf '%s' "$OUTSIDE" | tr '\n' ',' )"; fi

# 11. docs/hermes exists
if [ -d docs/hermes ]; then add docs_hermes_exists PASS "docs/hermes/ present"
else add docs_hermes_exists FAIL "docs/hermes/ missing"; fi

# 12. recent hermes reports under at least one subdir
CNT=0
for sub in backlog_health embedding_promotion_reviews librarian_loop_dryruns observations; do
  n=$(find "docs/hermes/$sub" -maxdepth 1 -name '*.md' 2>/dev/null | wc -l | tr -d ' ')
  CNT=$((CNT + n))
done
if [ "$CNT" -gt 0 ]; then add recent_hermes_reports PASS "$CNT report file(s) across subdirs"
else add recent_hermes_reports WARN "no report files found yet under docs/hermes/ subdirs"; fi

# 14. informational: latest commits touching the script + docs/hermes
LAST_SCRIPT="$(git log -1 --oneline -- "$SCRIPT" 2>/dev/null || true)"
LAST_HERMES="$(git log -1 --oneline -- docs/hermes/ 2>/dev/null || true)"

# ── compute result ──
BLOCKERS=0; WARNINGS=0
for r in "${ROWS[@]}"; do
  s="$(printf '%s' "$r" | cut -f2)"
  [ "$s" = "FAIL" ] && BLOCKERS=$((BLOCKERS + 1))
  [ "$s" = "WARN" ] && WARNINGS=$((WARNINGS + 1))
done
RESULT=PASS; [ "$BLOCKERS" -gt 0 ] && RESULT=FAIL

if [ "$JSON" = 1 ]; then
  printf '%s\n' "${ROWS[@]}" | python3 -c '
import sys, json
checks = []
for line in sys.stdin:
    line = line.rstrip("\n")
    if not line:
        continue
    parts = line.split("\t", 2)
    while len(parts) < 3:
        parts.append("")
    checks.append({"name": parts[0], "status": parts[1], "detail": parts[2]})
warn = [c["name"] + ": " + c["detail"] for c in checks if c["status"] == "WARN"]
block = [c["name"] + ": " + c["detail"] for c in checks if c["status"] == "FAIL"]
print(json.dumps({"ok": len(block) == 0, "warnings": warn, "blockers": block, "checks": checks}, indent=2))
'
else
  echo "=== Hermes Daily Commit Cron Verification ==="
  for r in "${ROWS[@]}"; do
    name="$(printf '%s' "$r" | cut -f1)"; st="$(printf '%s' "$r" | cut -f2)"; det="$(printf '%s' "$r" | cut -f3)"
    printf '%s: %s%s\n' "$name" "$st" "$( [ -n "$det" ] && printf '  (%s)' "$det" )"
  done
  echo ""
  [ -n "$LAST_SCRIPT" ] && echo "info_last_commit_script: $LAST_SCRIPT"
  [ -n "$LAST_HERMES" ] && echo "info_last_commit_hermes: $LAST_HERMES"
  echo ""
  echo "WARNINGS: $WARNINGS · BLOCKERS: $BLOCKERS"
  echo "RESULT: $RESULT"
fi

[ "$BLOCKERS" -gt 0 ] && exit 1
exit 0
