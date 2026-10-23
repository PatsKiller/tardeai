#!/usr/bin/env bash
# resume-operator.sh — OPERATOR-RUN (prepared 2026-10-22 by an agent; the agent never ran it).
# INC-20261014-SPCX: resume the read/report cron lines paused on 2026-10-14/15, in the approved order.
# Operator approval 2026-10-22 ("yes" to the 4-item proposal; Grok: "switch on after your fix").
# Modeled on ~/n8n-maturity-verification/resume_schwab_journal_cron.sh (prefix strip, exact diff, backup, read-back).
#
# Order (each step un-pauses exactly its own line(s), matched by EXACT TEXT, never by line number):
#   a  L501 schwab_position_sync + L1036 positions_sync --diff + L1038 positions_proof_daily (proof restarts at day 1)
#   b  L468 sync_basis_from_broker + L469 audit_position_basis
#   c  L794 broker_stop_reconcile
#   d  L652 stop_drift_alert
#   e  L784 schwab_econfirm_reconcile (dry run is the --days 10 --dry-run backfill check)
#   f  L772 + L778 options_chain_snapshot
#   g  L896 sweep_schwab_instruments
#   h  L497 grok_stop_review — resumed by default ONLY when the served release carries the spend-gate fix
#      (PROCESS_ID = "grok_stop_review" in CURRENT/scripts/grok_stop_review.py); otherwise skipped with the command
#      to run later (bash resume-operator.sh --only h)
#   i  L462 schwab_stream_daemon — last; takes effect today only if resumed before 09:31 ET, else the next session
# Kept paused (not touched): L774 defense fills, L781/L782 options lifecycle, L558 coder_dispatch.
# L214 sync-docs-to-drive: stays commented; annotated "# RETIRED 2026-10-22 ..." in front (archive note, not deleted).
#
# Usage:
#   bash resume-operator.sh                 # preconditions, backup, every step's own dry run, ONE "RESUME" prompt, apply
#   bash resume-operator.sh --preview       # preconditions + dry runs + crontab diff preview; changes nothing
#   bash resume-operator.sh --only h        # one step (e.g. Grok later, once the fix is served)
#
# Preconditions (refuses otherwise): host ms01-openclaw, user johnclaw, Schwab access mode read_only, trading lock
# LOCKED for schwab. The global kill switch being ON is expected and does not block reads (not checked).
# This script never edits .env, the access-mode switch, the unlock file, a flag or a broker order. It sources .env
# only inside each dry run's own shell, exactly like the cron line does, and never prints it.
# Rollback at any point: crontab "$BACKUP"   (the backup is never deleted)
set -euo pipefail
set -f

PREVIEW=0; ONLY=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --preview) PREVIEW=1; shift ;;
    --only) ONLY="${2:-}"; shift 2 ;;
    *) echo "usage: $0 [--preview] [--only a|b|c|d|e|f|g|h|i|retire214]"; exit 2 ;;
  esac
done

EXPECT_HOST="ms01-openclaw"; EXPECT_USER="johnclaw"
CUR="/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$HOME/.cache"
BACKUP="$HOME/.cache/crontab.bak-$STAMP"
WORK="$HOME/.cache/resume-operator-$STAMP"; mkdir -p "$WORK"
GROK_MARKER='PROCESS_ID = "grok_stop_review"'

die() { echo "REFUSED: $*" >&2; exit 3; }
rollback_hint() { echo "ROLLBACK: crontab \"$BACKUP\"   (then: crontab -l | cmp - \"$BACKUP\" && echo restored)" >&2; }

# ── 0. preconditions ────────────────────────────────────────────────────────────────────────────────────
echo "== preconditions"
[[ "$(hostname)" == "$EXPECT_HOST" ]] || die "host is $(hostname), expected $EXPECT_HOST"
[[ "$(id -un)" == "$EXPECT_USER" ]] || die "user is $(id -un), expected $EXPECT_USER"
[[ -d "$CUR/scripts" ]] || die "served release $CUR not found"
crontab -l > "$WORK/crontab.live"
# crontab variables the cron lines use ($PROJ, $PY, TRADEAI_ENV ...). Only these names, read from the live crontab.
for v in PROJ PY TRADEAI_ENV TRADEAI_BROKER_ENV_AUDIT LLM_DEFER_OFFPEAK; do
  val="$(grep -E "^${v}=" "$WORK/crontab.live" | tail -1 | cut -d= -f2- || true)"
  [[ -n "$val" ]] && export "$v=$val"
done
[[ -n "${PY:-}" && -x "$PY" ]] || die "crontab PY not found or not executable"
[[ "${PROJ:-}" == "$CUR" ]] || die "crontab PROJ ($PROJ) is not $CUR"
mode_line="$(grep -E '^mode:' "$CUR/config/schwab_access_mode.yaml" | head -1 | awk '{print $2}')"
[[ "$mode_line" == "read_only" ]] || die "config/schwab_access_mode.yaml mode is '$mode_line', expected read_only"
mode_py="$(cd "$CUR" && "$PY" -c 'import sys; sys.path.insert(0,"scripts"); from lib import schwab_access_mode as m; print(m.mode())')"
[[ "$mode_py" == "read_only" ]] || die "schwab_access_mode.mode() resolves to '$mode_py', expected read_only"
lock_json="$(cd "$CUR" && "$PY" -c 'import sys,json; sys.path.insert(0,"scripts"); from lib.trading_lock import lock_state; print(json.dumps(lock_state(broker="schwab")))')"
echo "$lock_json" | "$PY" -c 'import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get("locked") is True else 1)' \
  || die "trading lock is NOT locked for schwab: $lock_json"
echo "   host $EXPECT_HOST, user $EXPECT_USER, access mode read_only, trading lock LOCKED ($(echo "$lock_json" | cut -c1-90))"
echo "   global kill switch: expected ON (operator decision); it blocks trading automation only, not these reads"

# ── 1. one backup, taken once, never deleted ────────────────────────────────────────────────────────────
cp -p "$WORK/crontab.live" "$BACKUP"
echo "== backup: $BACKUP ($(wc -l < "$BACKUP") lines, sha256 $(sha256sum "$BACKUP" | cut -c1-16))"

# ── 2. the exact paused lines (quoted heredoc: no expansion; TAB separates step id and line) ────────────
cat > "$WORK/targets.tsv" <<'TARGETS'
a	# PAUSED 2026-10-15 schwab-app-deactivated (incident SPCX, grant 0f9de907) 7,22,37,52 9-16 * * 1-5 cd $PROJ && flock -n /tmp/schwab_pos_sync.lock bash -c "sleep $((RANDOM \% 20)); set -a; . ./.env; set +a; $PY scripts/schwab_position_sync.py --apply" >> logs/schwab_position_sync.log 2>&1
a	# PAUSED 2026-10-14 schwab-app-deactivated (incident SPCX) 20 17 * * 1-5 cd $PROJ && flock -n /tmp/positions_sync.lock timeout 120 bash -c "set -a; . ./.env; set +a; $PY scripts/positions_sync.py --diff" >> logs/positions_sync.log 2>&1
a	# PAUSED 2026-10-14 schwab-app-deactivated (incident SPCX) 25 17 * * 1-5 cd $PROJ && flock -n /tmp/positions_proof.lock timeout 180 bash -c "set -a; . ./.env; set +a; $PY scripts/positions_proof_daily.py --send" >> logs/positions_proof.log 2>&1
b	# PAUSED 2026-10-14 schwab-app-deactivated (incident SPCX) 33 16 * * 1-5 cd $PROJ && flock -n /tmp/basis_sync.lock bash -c "set -a; . ./.env; set +a; $PY scripts/sync_basis_from_broker.py --apply" >> logs/basis_sync.log 2>&1  # daily basis self-heal (repricer reverts SSOT values — root fix pending)
b	# PAUSED 2026-10-14 schwab-app-deactivated (incident SPCX) 35 16 * * 1-5 cd $PROJ && flock -n /tmp/basis_audit.lock bash -c "set -a; . ./.env; set +a; $PY scripts/audit_position_basis.py --alert" >> logs/position_basis_audit.log 2>&1  # basis drift alarm (holdings vs broker)
c	# PAUSED 2026-10-14 schwab-app-deactivated (incident SPCX) 12 6 * * 1-5 cd /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT && flock -n /tmp/broker_stop_reconcile.lock bash -c "set -a; . ./.env; set +a; $PY scripts/broker_stop_reconcile.py --apply" >> logs/broker_stop_reconcile.log 2>&1
d	# PAUSED 2026-10-14 schwab-app-deactivated (incident SPCX) 35 17 * * 1-5 cd $PROJ && bash scripts/market_day_gate.sh flock -n /tmp/stop_drift_alert.lock $PY scripts/stop_drift_alert.py --send >> logs/stop_drift_alert.log 2>&1  # daily raise-stop + lock-in-profits drift alert (advisory, Telegram)
e	# PAUSED 2026-10-15 schwab-app-deactivated (incident SPCX, grant 0f9de907) 35 18 * * 1-5 cd /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT && flock -n /tmp/econfirm.lock bash -c "set -a; . ./.env; set +a; $PY scripts/schwab_econfirm_reconcile.py --days 7" >> logs/econfirm.log 2>&1
f	# PAUSED 2026-10-14 schwab-app-deactivated (incident SPCX) 35 17 * * 1-5 cd /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT && flock -n /tmp/chain_snapshot.lock bash -c "set -a; . ./.env; set +a; $PY scripts/options_chain_snapshot.py" >> logs/chain_snapshot.log 2>&1  # Defense v3 R1: nightly chain snapshots (read-only, coverage-stated)
f	# PAUSED 2026-10-14 schwab-app-deactivated (incident SPCX) 0 10 * * 1-5 cd /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT && flock -n /tmp/chain_snapshot.lock bash -c "set -a; . ./.env; set +a; $PY scripts/options_chain_snapshot.py" >> logs/chain_snapshot.log 2>&1
g	# PAUSED 2026-10-15 schwab-app-deactivated (incident SPCX, grant 0f9de907) 30 3 * * 6 cd /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT && $PY scripts/sweep_schwab_instruments.py --apply >> logs/sweep_schwab_instruments.log 2>&1
h	# PAUSED 2026-10-14 schwab-app-deactivated (incident SPCX) 5 10,15 * * 1-5 cd $PROJ && bash scripts/market_day_gate.sh $PY scripts/grok_stop_review.py --apply >> logs/grok_stop_review_cron.log 2>&1
i	# PAUSED 2026-10-14 schwab-app-deactivated (incident SPCX) 31 9 * * 1-5 cd $PROJ && flock -n /tmp/schwab_stream.lock bash -c "set -a; . ./.env; set +a; $PY scripts/schwab_stream_daemon.py" >> logs/schwab_stream.log 2>&1
retire214	# PAUSED_MASTER_REWRITE 5 * * * * cd /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT && $PY scripts/sync-docs-to-drive.py >> /home/johnclaw/logs/drive-docs-sync.log 2>&1
TARGETS

# Lines that must stay paused: asserted present before and after, never edited.
cat > "$WORK/keep.txt" <<'KEEP'
/tmp/defense_fills.lock
/tmp/options_lifecycle.lock
/tmp/options_lc_digest.lock
/tmp/tradeai_coder_dispatch.lock
KEEP

# edit.py LIVE TARGETS STEP OUT : write OUT = LIVE with exactly STEP's paused line(s) un-paused (or L214 annotated).
cat > "$WORK/edit.py" <<'PYEOF'
import re, sys
live, targets, step, out = sys.argv[1:5]
lines = open(live, newline="").read().split("\n")
want = [l.split("\t", 1)[1] for l in open(targets).read().split("\n") if l.startswith(step + "\t")]
assert want, f"no target lines for step {step}"
PFX = re.compile(r"^# PAUSED 2026-10-1[45] schwab-app-deactivated \(incident SPCX(, grant 0f9de907)?\) ")
RETIRE = "# RETIRED 2026-10-22 superseded-by drive-syncs-hourly (crontab L1048; archive note, not deleted) | "
for w in want:
    hits = [i for i, l in enumerate(lines) if l == w]
    if len(hits) != 1:
        sys.exit(f"REFUSED: step {step}: expected exactly 1 line equal to the paused text, found {len(hits)}:\n  {w}")
    i = hits[0]
    if step == "retire214":
        lines[i] = RETIRE + w
    else:
        m = PFX.match(w)
        assert m, f"unexpected prefix: {w[:80]}"
        new = w[m.end():]
        for bad in ("place_order", "cancel_order", "replace_order", "defense_execution", "options_lifecycle",
                    "coder_dispatch", "trading_unlock"):
            assert bad not in new, f"refusing: {bad} in {new[:80]}"
        lines[i] = new
open(out, "w", newline="").write("\n".join(lines))
print(len(want))
PYEOF

check_keep() {  # every kept-paused line is still present and still commented
  local f="$1"
  while read -r lock; do
    [[ -z "$lock" ]] && continue
    n_paused="$(grep -F "$lock" "$f" | grep -c '^# PAUSED' || true)"
    n_active="$(grep -F "$lock" "$f" | grep -vc '^#' || true)"
    [[ "$n_paused" -ge 1 && "$n_active" -eq 0 ]] || { echo "REFUSED: kept-paused line for $lock changed (paused=$n_paused active=$n_active)"; return 1; }
  done < "$WORK/keep.txt"
}
check_keep "$WORK/crontab.live" || { rollback_hint; exit 3; }

# ── 3. each step's own dry run (output shown; nothing written to the crontab yet) ───────────────────────
in_cur() {  # run like the cron line: from the served release, .env sourced only inside this shell, never printed
  ( cd "$CUR" && TRADEAI_SCHWAB_ACCESS_MODE=read_only bash --noprofile --norc -c 'set -a; . ./.env; set +a; exec "$@"' _ "$@" )
}
grok_fix_served() { grep -qxF "$GROK_MARKER" "$CUR/scripts/grok_stop_review.py"; }
STEPS=(a b c d e f g h i retire214)
[[ -n "$ONLY" ]] && STEPS=("$ONLY")
RUN_STEPS=()
dry() {  # dry STEP LABEL ALLOWED_RCS... -- CMD...
  local step="$1" label="$2"; shift 2
  local ok_rcs=()
  while [[ "$1" != "--" ]]; do ok_rcs+=("$1"); shift; done; shift
  echo "-- [$step] dry run: $label"
  set +e; in_cur "$@" 2>&1 | tail -40; local rc="${PIPESTATUS[0]}"; set -e
  for r in "${ok_rcs[@]}"; do [[ "$rc" == "$r" ]] && { echo "   rc=$rc (ok)"; return 0; }; done
  echo "DRY RUN FAILED: [$step] $label rc=$rc — stopping before any crontab change."; rollback_hint; exit 4
}

echo "== dry runs (each script's own dry-run mode)"
for s in "${STEPS[@]}"; do
  case "$s" in
    a) dry a "schwab_position_sync (no --apply = dry-run diff; reads Schwab positions)" 0 -- "$PY" scripts/schwab_position_sync.py
       dry a "positions_sync --check-fresh (read-only; rc 2 = stale, expected while L501 is paused)" 0 2 -- "$PY" scripts/positions_sync.py --check-fresh
       echo "-- [a] positions_proof_daily: NO dry-run mode (it writes today's ledger row, replaced per date); not run here."
       echo "   The 17:25 cron run grades the day; the 10-day proof restarts at day 1 (ledger stops at 2026-10-13)." ;;
    b) dry b "sync_basis_from_broker (no --apply = DRY-RUN)" 0 -- "$PY" scripts/sync_basis_from_broker.py
       dry b "audit_position_basis --json (no --alert = no send)" 0 1 -- "$PY" scripts/audit_position_basis.py --json ;;
    c) dry c "broker_stop_reconcile --json (no --apply = report only; reads Schwab working orders, never writes one)" 0 1 -- "$PY" scripts/broker_stop_reconcile.py --json ;;
    d) dry d "stop_drift_alert (no --send = print only)" 0 -- "$PY" scripts/stop_drift_alert.py ;;
    e) dry e "schwab_econfirm_reconcile --days 10 --dry-run (backfill check: do the 10-14/10-15 SPCX confirms appear?)" 0 -- "$PY" scripts/schwab_econfirm_reconcile.py --days 10 --dry-run
       echo "   If the dry run lists missing 10-14/10-15 confirms, after the resume run once by hand:"
       echo "   cd $CUR && bash -c 'set -a; . ./.env; set +a; $PY scripts/schwab_econfirm_reconcile.py --days 10' >> logs/econfirm.log 2>&1" ;;
    f) dry f "options_chain_snapshot --dry-run --limit 3" 0 -- "$PY" scripts/options_chain_snapshot.py --dry-run --limit 3 ;;
    g) dry g "sweep_schwab_instruments --limit 5 --json (no --apply = dry run)" 0 1 -- "$PY" scripts/sweep_schwab_instruments.py --limit 5 --json ;;
    h) if grok_fix_served; then
         dry h "grok_stop_review --plan (spend-gate fix served; no model call, no write)" 0 -- "$PY" scripts/grok_stop_review.py --plan
       else
         echo "-- [h] SKIPPED: the served release does not carry the Grok spend-gate fix"
         echo "   (no line '$GROK_MARKER' in $CUR/scripts/grok_stop_review.py)."
         echo "   Once the release with the fix is served, resume it with:  bash $0 --only h"
         continue
       fi ;;
    i) echo "-- [i] schwab_stream_daemon: NO dry-run mode (any run streams and writes quote rows); not run here."
       hhmm="$(TZ=America/New_York date +%H%M)"; dow="$(TZ=America/New_York date +%u)"
       if [[ "$dow" -le 5 && $((10#$hhmm)) -lt 931 ]]; then echo "   Resumed before 09:31 ET: takes effect TODAY at 09:31."
       else echo "   Resumed at $hhmm ET (day $dow): takes effect at the NEXT session's 09:31 start."; fi
       [[ -e "$CUR/data/state/STREAM_DISABLED" ]] && echo "   NOTE: data/state/STREAM_DISABLED exists; the daemon will exit at start until it is removed." ;;
    retire214) echo "-- [retire214] L214 stays commented; '# RETIRED 2026-10-22 superseded-by drive-syncs-hourly ...' is put in front." ;;
    *) die "unknown step $s" ;;
  esac
  RUN_STEPS+=("$s")
done

[[ ${#RUN_STEPS[@]} -gt 0 ]] || { echo "Nothing to apply (every requested step was skipped). Crontab unchanged."; exit 0; }

# ── 4. preview the full diff, then ONE confirmation ─────────────────────────────────────────────────────
cp -p "$WORK/crontab.live" "$WORK/preview"
total=0
for s in "${RUN_STEPS[@]}"; do
  n="$("$PY" "$WORK/edit.py" "$WORK/preview" "$WORK/targets.tsv" "$s" "$WORK/preview.next")" || { rollback_hint; exit 3; }
  mv "$WORK/preview.next" "$WORK/preview"; total=$((total + n))
done
echo "== crontab diff that will be applied ($total line(s), steps: ${RUN_STEPS[*]})"
diff "$WORK/crontab.live" "$WORK/preview" || true
[[ "$(diff "$WORK/crontab.live" "$WORK/preview" | grep -c '^[<>]')" == "$((total * 2))" ]] || { echo "REFUSED: diff is not exactly $total line(s)"; rollback_hint; exit 3; }
check_keep "$WORK/preview" || { rollback_hint; exit 3; }
if [[ $PREVIEW == 1 ]]; then echo "PREVIEW ONLY — crontab unchanged. Backup kept at $BACKUP"; exit 0; fi
read -r -p "Type RESUME to apply these ${#RUN_STEPS[@]} step(s) in order: " answer
[[ "$answer" == "RESUME" ]] || { echo "Not confirmed — crontab unchanged. Backup kept at $BACKUP"; exit 0; }

# ── 5. apply step by step; stop at the first failure ───────────────────────────────────────────────────
for s in "${RUN_STEPS[@]}"; do
  crontab -l > "$WORK/before.$s"
  "$PY" "$WORK/edit.py" "$WORK/before.$s" "$WORK/targets.tsv" "$s" "$WORK/after.$s" >/dev/null || { echo "FAILED at step $s (match)"; rollback_hint; exit 5; }
  crontab - < "$WORK/after.$s" || { echo "FAILED at step $s (install)"; rollback_hint; exit 5; }
  # Read back ONCE into a file and verify against the file. Never `crontab -l | grep -q`: grep -q exits at the
  # first match, crontab -l takes SIGPIPE writing the rest of a large crontab, and pipefail turns that 141 into a
  # false FAILED (2026-10-22 operator run: every step applied, every verify printed FAILED).
  crontab -l > "$WORK/after-installed.$s" || { echo "FAILED at step $s (read-back)"; rollback_hint; exit 5; }
  cmp -s "$WORK/after-installed.$s" "$WORK/after.$s" || { echo "FAILED at step $s (read-back differs)"; rollback_hint; exit 5; }
  # verify: each un-paused line is now present as an ACTIVE line
  while IFS=$'\t' read -r st line; do
    [[ "$st" == "$s" ]] || continue
    if [[ "$s" == "retire214" ]]; then
      grep -qF "# RETIRED 2026-10-22 superseded-by drive-syncs-hourly" "$WORK/after-installed.$s" || { echo "FAILED: L214 annotation missing"; rollback_hint; exit 5; }
    else
      active="$(printf '%s' "$line" | sed -E 's/^# PAUSED 2026-10-1[45] schwab-app-deactivated \(incident SPCX(, grant 0f9de907)?\) //')"
      grep -qxF -- "$active" "$WORK/after-installed.$s" || { echo "FAILED at step $s: line not active after install"; rollback_hint; exit 5; }
    fi
  done < "$WORK/targets.tsv"
  check_keep "$WORK/after-installed.$s" || { echo "FAILED at step $s: kept-paused lines changed"; rollback_hint; exit 5; }
  echo "   [$s] active and verified (crontab -l)"
done
echo "DONE. Backup: $BACKUP   Rollback: crontab \"$BACKUP\""
echo "Next (agent PR): flip the resumed rows in config/lane_registry.json back to ACTIVE with state_since $(date +%F)."
echo "Grok (if resumed): python3 $CUR/scripts/sync_cio_process_caps.py, then restart cio-governed-bridge (AGENTS.md §9.2)."
