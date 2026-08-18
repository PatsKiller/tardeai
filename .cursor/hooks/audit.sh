#!/usr/bin/env bash
# After-hook audit. Serialized via guard_ledger.audit_append.
# Never rewrite historical evidence. One complete JSON line per event.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$HERE/guard-lib.sh"
ev=$(timeout 5 cat || true)
[[ -n "${ev:-}" ]] || exit 0
payload=$(jq -nc --argjson ev "$ev" --arg ts "$(date -Is)" '{ts:$ts} + $ev' 2>/dev/null) || exit 0
_ledger audit --payload "$payload" >/dev/null 2>&1 || true
exit 0
