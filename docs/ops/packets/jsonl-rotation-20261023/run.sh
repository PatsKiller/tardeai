#!/usr/bin/env bash
# JSONL archive rotation — OPERATOR packet (2026-10-23). Agents never run --apply: it writes to
# ~/trade-ai-releases/persistent-state, which needs the operator (no agent holds a state grant for it).
#
# Operator 2026-10-23 ~11:05 ET, "approved": rotate (archive, never delete) the oversized append-only JSONL stores.
#
#   bash docs/ops/packets/jsonl-rotation-20261023/run.sh --preview   # reads only: the plan + the retention selection
#   bash docs/ops/packets/jsonl-rotation-20261023/run.sh --apply     # after 16:15 ET; asks you to type APPLY
#
# --apply: refuses Mon-Fri before 16:15 ET (and the script itself refuses 04:00-16:15 ET); checks the sha256 of the
# rotation script and rules it runs; prints the plan; asks for typed APPLY; runs
# scripts/ops/jsonl_archive_rotate.py --apply --confirm APPLY (writer-safe rename + renameat2; archives under
# <state>/archive/file_prune/<store>/ with sha256/line-count manifests and tripwire records); prints the report.
# It DELETES NO ARCHIVE. The retention selection (--retention-preview) is printed for your decision only.
set -euo pipefail

MODE="${1:-}"
CODE="${CODE:-$HOME/wt-jsonl-retention-20261023}"
PY="${PY:-$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python}"
[ -x "$PY" ] || PY=python3
STATE="${TRADEAI_STATE_ROOT:-$HOME/trade-ai-releases/persistent-state}"
OUT="$HOME/.cache/rtc/jsonl-rotation-20261023"
mkdir -p "$OUT"
export TMPDIR="${TMPDIR:-$HOME/.cache/rtc}"

case "$MODE" in --preview|--apply) ;; *) echo "usage: run.sh --preview | --apply"; exit 2 ;; esac
cd "$CODE"

echo "== code and rules (pinned)"
sha256sum -c - <<EOF2
f6d66bfc5b2071beffd6c64414afee2731101975cb7c0d055a5087deba24d084  scripts/ops/jsonl_archive_rotate.py
02e7296490c1094e5589121b3f3ea15042c6abdd4b36c58d5ce8189e459c1836  config/disk_hygiene_rules.json
EOF2
echo "code root $CODE @ $(git rev-parse --short HEAD); state root $STATE"

echo "== plan (read-only; writes nothing)"
"$PY" scripts/ops/jsonl_archive_rotate.py --dry-run --state-root "$STATE" | tee "$OUT/plan_$(date -u +%Y%m%dT%H%M%SZ).json" \
  | "$PY" -c 'import json,sys; d=json.load(sys.stdin)
for s in d["stores"]:
    print("  %-30s %-7s lines=%-9s archive=%s lines / %s bytes  keep=%s lines / %s bytes  %s" % (s["id"], s["action"],
          s.get("lines"), s.get("archive_lines"), s.get("archive_bytes"), s.get("keep_lines"), s.get("keep_bytes"),
          s.get("reason") or ""))
print("  TOTAL archive %(archive_lines)s lines / %(archive_bytes)s bytes, keep %(keep_bytes)s bytes" % d["totals"])'

echo "== archive segments the retention rules would select (read-only; nothing is removed)"
"$PY" scripts/ops/jsonl_archive_rotate.py --retention-preview --state-root "$STATE" \
  | "$PY" -c 'import json,sys; d=json.load(sys.stdin)
for s in d["stores"]:
    for g in s["segments"]:
        print("  %-26s %-5s %14s bytes  age %6.2f d  %s  %s" % (s["id"], "SEL" if g["would_select"] else "keep",
              g["bytes"], g["age_days"], ",".join(g["why"]) or "-", g["path"]))
print("  would select %s bytes (enabled=%s; removal is not automated)" % (d["would_select_bytes"], d["enabled"]))'

if [ "$MODE" = --preview ]; then echo "preview only: nothing written"; exit 0; fi

DOW=$(TZ=America/New_York date +%u); HM=$(TZ=America/New_York date +%H%M)
if [ "$DOW" -le 5 ] && [ "$HM" -ge 0400 ] && [ "$HM" -lt 1615 ]; then
  echo "refused: $(TZ=America/New_York date '+%a %H:%M ET') is inside the Mon-Fri 04:00-16:15 ET window; run after 16:15 ET"
  exit 1
fi

read -r -p "Type APPLY to rotate the stores listed above: " ANSWER
[ "$ANSWER" = APPLY ] || { echo "not APPLY: nothing done"; exit 1; }
"$PY" scripts/ops/jsonl_archive_rotate.py --apply --confirm APPLY --state-root "$STATE" | tee "$OUT/apply_$(date -u +%Y%m%dT%H%M%SZ).json"
echo "== after"
ls -la "$STATE"/archive/file_prune/*/ 2>/dev/null | grep -E "jsonl.gz|TRIPWIRE|^/" || true
echo "receipt: $STATE/data/runtime/jsonl-archive-rotate_last.json"
echo "If a store reports failed: python3 scripts/ops/jsonl_archive_rotate.py --recover --confirm APPLY (merges back)."
