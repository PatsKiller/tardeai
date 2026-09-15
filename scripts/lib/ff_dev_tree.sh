# shellcheck shell=bash
# ff_dev_tree <repo> <target-ref>
#
# Fast-forward a checkout to <target-ref>. Returns 0 only when HEAD is at, or already contains, the target.
# Sourced by scripts/cio_phase2_exact_main_deploy.sh after promote; safe to source from any bash script.
#
# Why (2026-09-14): the release and the dev tree are two execution trees. Cron and the user units run from
# the dev tree, so a promote that leaves it on the old commit runs old code. A wrapper doing
# `git merge --ff-only && git log` swallowed a refused fast-forward (`set -e` ignores `&&` lists) and
# reported success. Git refused because the promoted commit untracked files that sit behind symlinks
# (data/runtime, data/audit -> persistent-state) whose live content had moved on.
#
# Automatic handling is limited to that proven-safe case, path by path:
#   - the target commit no longer tracks the path, and
#   - some leading directory of the path is a symlink, and
#   - the resolved live file exists.
# For those paths only: hash the live files, `git rm --cached` (index only, never touches files),
# retry, re-hash. Any other blocker stops with the index untouched.
ff_dev_tree() {
  local repo="$1" target="$2"
  local want head
  want=$(git -C "$repo" rev-parse --verify --quiet "${target}^{commit}") || { echo "STOP: cannot resolve $target in $repo"; return 1; }
  head=$(git -C "$repo" rev-parse HEAD) || { echo "STOP: $repo has no HEAD"; return 1; }
  if [ "$head" = "$want" ]; then
    echo "dev tree already at ${want:0:9}"; return 0
  fi
  if git -C "$repo" merge-base --is-ancestor "$want" "$head"; then
    echo "dev tree at ${head:0:9} already contains ${want:0:9}"; return 0
  fi
  git -C "$repo" merge-base --is-ancestor "$head" "$want" || { echo "STOP: dev tree HEAD ${head:0:9} is not an ancestor of ${want:0:9} (not a fast-forward)"; return 1; }

  local err rc
  err=$(git -C "$repo" merge --ff-only -q "$want" 2>&1); rc=$?
  if [ "$rc" -eq 0 ] && [ "$(git -C "$repo" rev-parse HEAD)" = "$want" ]; then
    echo "dev tree fast-forwarded to ${want:0:9}"; return 0
  fi
  echo "first fast-forward refused:"; printf '%s\n' "$err" | sed 's/^/  | /' | head -12

  local blocked
  blocked=$(printf '%s\n' "$err" | awk '/would be overwritten by merge:/{f=1;next} /^Please|^Aborting/{f=0} f && /^[[:space:]]+[^[:space:]]/{sub(/^[[:space:]]+/,""); print}')
  [ -n "$blocked" ] || { echo "STOP: fast-forward failed for a reason other than blocked local paths"; return 1; }

  local safe=() p d real has_link
  while IFS= read -r p; do
    [ -n "$p" ] || continue
    if git -C "$repo" cat-file -e "$want:$p" 2>/dev/null; then
      echo "STOP: $p is still tracked in ${want:0:9}; a local change would be overwritten (not auto-handled)"; return 1
    fi
    has_link=""; d=$(dirname "$p")
    while [ "$d" != "." ] && [ "$d" != "/" ]; do
      if [ -L "$repo/$d" ]; then has_link=1; break; fi
      d=$(dirname "$d")
    done
    [ -n "$has_link" ] || { echo "STOP: $p has no symlinked parent (not auto-handled)"; return 1; }
    real=$(readlink -f "$repo/$p")
    [ -f "$real" ] || { echo "STOP: live copy of $p not found at $real"; return 1; }
    safe+=("$p")
  done <<< "$blocked"

  local before after
  before=$(for p in "${safe[@]}"; do sha256sum < "$(readlink -f "$repo/$p")"; done)
  echo "untracking in index only (live copies behind symlinks): ${safe[*]}"
  git -C "$repo" rm -q --cached -- "${safe[@]}" || { echo "STOP: git rm --cached failed"; return 1; }
  if ! git -C "$repo" merge --ff-only -q "$want"; then
    git -C "$repo" reset -q HEAD -- "${safe[@]}"
    echo "STOP: fast-forward still refused; index entries restored"; return 1
  fi
  after=$(for p in "${safe[@]}"; do sha256sum < "$(readlink -f "$repo/$p")"; done)
  [ "$before" = "$after" ] || { echo "STOP: live copies changed during the fast-forward"; return 1; }
  [ "$(git -C "$repo" rev-parse HEAD)" = "$want" ] || { echo "STOP: HEAD is not ${want:0:9} after the retry"; return 1; }
  echo "dev tree fast-forwarded to ${want:0:9}; live copies unchanged"
  return 0
}
