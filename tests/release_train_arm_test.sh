#!/usr/bin/env bash
# Bash tests for scripts/ops/release_train_arm.sh (ANCHOR RELEASE_TRAIN_ARMING_20261021). Hermetic: one sandbox under
# $TMPDIR with stub psql/systemctl/docker/curl; HOME and every path are rebased into it. Run:
#   TMPDIR=~/.cache/rtarm bash tests/release_train_arm_test.sh
# Also run by tests/test_release_train_arming_20261021.py::test_bash_suite_passes (the CI gate).
set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYBIN="${RTARM_TEST_PY:-$(command -v python3)}"
ARM="$REPO/scripts/ops/release_train_arm.sh"
ROOT="$(mktemp -d "${TMPDIR:-/tmp}/rtarm-bash.XXXXXX")"
PASS=0; FAIL=0
ok() { PASS=$((PASS+1)); echo "ok   $1"; }
bad() { FAIL=$((FAIL+1)); echo "FAIL $1"; [[ -n "${2:-}" ]] && printf '%s\n' "$2" | tail -15 | sed 's/^/     /'; }

new_sandbox() {   # new_sandbox <name>  -> sets SB and exports the sandbox env
  SB="$ROOT/$1"
  local line
  while IFS= read -r line; do export "${line?}"; done < <(bash "$REPO/tests/fixtures/release_train_arm/make_sandbox.sh" "$SB" "$REPO" "$PYBIN")
}

# The sandbox tree minus the stubs' own bookkeeping (calls.log, fake/): what the arming script itself wrote.
tree_list() { (cd "$1" && find . \( -path ./calls.log -o -path ./fake \) -prune -o -print0 | sort -z | xargs -0 stat -c '%n %s %Y %a' 2>/dev/null); }
tree_digest() { tree_list "$1" | sha256sum; }

# 1. plan is a dry run of A..G that prints each step and writes nothing
new_sandbox plan
before="$(tree_list "$SB")"
out="$(bash "$ARM" plan 2>&1)"; rc=$?
after="$(tree_list "$SB")"
if [[ $rc == 0 ]] && grep -q "== A" <<<"$out" && grep -q "== G" <<<"$out" && grep -q "WOULD" <<<"$out"; then ok "plan exits 0 and prints A..G"; else bad "plan exits 0 and prints A..G" "$out"; fi
[[ "$before" == "$after" ]] && ok "plan writes nothing" || bad "plan writes nothing" "$(diff <(echo "$before") <(echo "$after"))"

# 2. --apply without the acknowledgement is refused, and a wrong letter is refused
for step in A B C D E F; do
  out="$(TRADEAI_RELEASE_TRAIN_ARM_ACK= bash "$ARM" "$step" --apply 2>&1)"; rc=$?
  [[ $rc == 2 ]] && grep -q "REFUSED" <<<"$out" && ok "$step --apply refused without ack" || bad "$step --apply refused without ack" "$out"
done
out="$(TRADEAI_RELEASE_TRAIN_ARM_ACK=B bash "$ARM" C --apply 2>&1)"; rc=$?
[[ $rc == 2 && ! -e "$SB/home/.config/tradeai/release_train/delegation.json" ]] && ok "ack for B does not arm C" || bad "ack for B does not arm C" "$out"
[[ ! -e "$SB/home/.config/tradeai/release_train/capability.key" ]] && ok "no key created by refused runs" || bad "no key created by refused runs"
grep -q '"REFUSED_NO_ACK"' "$SB/home/trade-ai-releases/persistent-state/data/runtime/release_train_arm/receipts.jsonl" \
  && ok "refusals are receipted" || bad "refusals are receipted"

# 3. B and C apply, then re-apply is NOOP and changes nothing
for step in B C; do
  out1="$(TRADEAI_RELEASE_TRAIN_ARM_ACK=$step bash "$ARM" "$step" --apply 2>&1)"; rc1=$?
  d1="$(tree_digest "$SB/home/.config")"
  out2="$(TRADEAI_RELEASE_TRAIN_ARM_ACK=$step bash "$ARM" "$step" --apply 2>&1)"; rc2=$?
  d2="$(tree_digest "$SB/home/.config")"
  if [[ $rc1 == 0 && $rc2 == 0 ]] && grep -q APPLIED <<<"$out1" && grep -q NOOP <<<"$out2" && [[ "$d1" == "$d2" ]]; then
    ok "$step apply then NOOP"; else bad "$step apply then NOOP" "$out1"$'\n'"$out2"; fi
done
[[ "$(stat -c %a "$SB/home/.config/tradeai/release_train/capability.key")" == 600 ]] && ok "key mode 600" || bad "key mode 600"

# 4. outside the sandbox contract: a sandbox whose docker is the real one is refused
SB2="$ROOT/realdocker"; mkdir -p "$SB2/home"; touch "$SB2/.rtarm-sandbox"
if command -v docker >/dev/null 2>&1 || [[ -x /usr/bin/docker ]]; then
  out="$(PATH="/usr/bin:/bin" RTARM_SANDBOX="$SB2" bash "$ARM" plan 2>&1)"; rc=$?
  [[ $rc == 2 ]] && grep -q "outside the sandbox" <<<"$out" && ok "real docker in a sandbox is refused" || bad "real docker in a sandbox is refused" "$out"
else
  ok "real docker in a sandbox is refused (skipped: no docker on this host)"
fi

echo "bash suite: $PASS passed, $FAIL failed"
[[ $FAIL == 0 ]]
