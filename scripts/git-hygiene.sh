#!/usr/bin/env bash
# git-hygiene.sh — source this in interactive shells to guard the live primary working tree.
#   Add to ~/.bashrc:   source /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/scripts/git-hygiene.sh
# (scripts/install-git-hygiene.sh does this for you.)
#
# Defines a `git` wrapper that BLOCKS branch switches / hard resets / rebase / cherry-pick in the primary
# tree while the server is live (git has no pre-checkout hook, so a wrapper is the only way to block these).
# Everything else — including `git checkout -- <files>`, `git checkout main`, and ALL git in linked
# worktrees — passes straight through. Bypass any single call with ALLOW_MAINTREE_GIT=1.

# shellcheck source=/dev/null
source "/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/scripts/git_hygiene_guard.sh" 2>/dev/null || return 0

_gh_is_branch() { git show-ref --verify --quiet "refs/heads/$1" 2>/dev/null; }
_gh_is_protected() { case " $GIT_HYGIENE_PROTECTED_BRANCHES " in *" $1 "*) return 0;; *) return 1;; esac; }

git() {
  local sub="$1"
  case "$sub" in
    switch|checkout|reset|rebase|cherry-pick)
      if _gh_guard_active; then
        case "$sub" in
          rebase|cherry-pick)
            _gh_block_msg "$sub"; return 1 ;;
          reset)
            # only hard/merge resets rewrite the working tree dangerously
            case " $* " in *" --hard "*|*" --merge "*) _gh_block_msg "reset --hard/--merge"; return 1;; esac ;;
          switch)
            # `git switch <branch>` and `-c` (create) both leave the current branch
            case " $* " in *" -"*) : ;; esac
            local a; for a in "${@:2}"; do case "$a" in -*) continue;; *) if ! _gh_is_protected "$a"; then _gh_block_msg "switch to '$a'"; return 1; fi; break;; esac; done ;;
          checkout)
            # block: -b/-B (create branch), or checking out an existing non-protected BRANCH.
            # allow: file-path checkouts ("-- <files>", "checkout ."), and checkout of main/master.
            case " $* " in *" -b "*|*" -B "*) _gh_block_msg "create+switch branch"; return 1;; esac
            case " $* " in *" -- "*) : ;; # explicit file checkout → allow
              *)
                local a; for a in "${@:2}"; do
                  case "$a" in
                    -*) continue ;;
                    .) break ;;                       # `checkout .` → file restore, allow
                    *) if _gh_is_branch "$a" && ! _gh_is_protected "$a"; then _gh_block_msg "checkout branch '$a'"; return 1; fi; break ;;
                  esac
                done ;;
            esac ;;
        esac
      fi ;;
  esac
  command git "$@"
}
