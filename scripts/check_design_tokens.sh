#!/usr/bin/env bash
# Defense v3 D3.2 — the design regression guard. Three sweeps, three regressions:
# this ends by machine, not vigilance. Runs in the CC-v3 build (npm run build) and
# is safe standalone: scripts/check_design_tokens.sh [--update-baseline]
#
# Rules per CC-v3 source file (pages/ + components/):
#   1. raw hex colors (#abc / #aabbcc) — allowed ONLY in lib/watchTokens.ts
#   2. sub-10px fonts: fontSize: 7|8|9 (any decimal like 8.5 included)
# Legacy debt is frozen in config/design_token_baseline.json — a file may never
# EXCEED its baseline count; new files start at 0. Ratchet down by re-running
# with --update-baseline after cleanups.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/apps/command-center-v3/src"
BASELINE="$ROOT/config/design_token_baseline.json"

count_hex()  { { grep -oE '#[0-9a-fA-F]{3,8}\b' "$1" 2>/dev/null || true; } | wc -l | tr -d ' '; }
count_font() { { grep -oE 'fontSize: *['\''"]?[789](\.[0-9]+)?\b' "$1" 2>/dev/null || true; } | wc -l | tr -d ' '; }

declare -A CUR
FILES=$(find "$SRC/pages" "$SRC/components" -name '*.tsx' -o -name '*.ts' | sort)
for f in $FILES; do
  rel="${f#"$SRC"/}"
  n=$(( $(count_hex "$f") + $(count_font "$f") ))
  CUR["$rel"]=$n
done

if [[ "${1:-}" == "--update-baseline" ]]; then
  { echo "{"; first=1
    for rel in "${!CUR[@]}"; do
      [[ ${CUR[$rel]} -eq 0 ]] && continue
      [[ $first -eq 0 ]] && echo ","
      first=0; printf '  "%s": %d' "$rel" "${CUR[$rel]}"
    done; echo; echo "}"; } > "$BASELINE"
  echo "[design-guard] baseline updated: $(grep -c ':' "$BASELINE") files with frozen debt"
  exit 0
fi

if [[ ! -f "$BASELINE" ]]; then
  echo "[design-guard] FAIL: baseline missing — run scripts/check_design_tokens.sh --update-baseline once"
  exit 1
fi

fail=0
for rel in "${!CUR[@]}"; do
  base=$(python3 -c "import json,sys; print(json.load(open('$BASELINE')).get('$rel', 0))")
  if [[ ${CUR[$rel]} -gt $base ]]; then
    echo "[design-guard] FAIL $rel: ${CUR[$rel]} raw-hex/sub-10px violations (baseline $base) — use watchTokens (BB/T/DASH), no fonts below 10"
    fail=1
  fi
done
if [[ $fail -eq 1 ]]; then
  echo "[design-guard] blocked. Fix the file or (only for deliberate legacy freezes) --update-baseline."
  exit 1
fi
echo "[design-guard] pass ($(echo "$FILES" | wc -l | tr -d ' ') files checked against baseline)"
