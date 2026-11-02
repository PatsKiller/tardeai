"""guard_tokens.py: gh/git tiers by shell tokens (security reviews of #2450, #2451, #2459; 2026-11-01).

Three rounds of regex patches were each evaded by another spelling the shell accepts: flags before the verb, flags
before the noun, quoting and backslashes. These tests drive the tokenizer directly, through guard-lib.sh's
classify_cmd, and through the real guard-shell.sh hook; mutants prove each tokenizer rule is load-bearing.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from tests.test_guard_item8_grant_free_push_20261025 import HOOKS, Env, _classify, agents_md, pytestmark  # noqa: F401

TOK = HOOKS / "guard_tokens.py"


def tiers(cmd: str, path: Path = TOK) -> str:
    return subprocess.run(["/usr/bin/python3", "-I", str(path), cmd], capture_output=True, text=True,
                          check=True).stdout.strip()


@pytest.fixture
def E(tmp_path: Path) -> Env:
    e = Env(tmp_path)
    e.build(agents=agents_md("29.4.0"))
    return e


ROOT_FLAG = [  # reviewer r3: global flags before the noun
    "gh -R PatsKiller/tardeai issue comment 50 --body 'APPROVE_PUSH_STANDING wt/* until 2026-12-15'",
    "gh --repo PatsKiller/tardeai issue reopen 50",
    "gh -R PatsKiller/tardeai pr review 12 --approve",
]
QUOTING = [  # reviewer r3: quoting and backslash evasions
    "gh issue -R o/r \"comment\" 50 -b y", "\"gh\" issue comment 50 -b y", "gh issue com\\ment 50 -b y",
    "g\\h issue comment 5 -b y", "'gh' 'issue' 'reopen' 50",
]
EARLIER = [  # rounds 1-2
    "gh issue -R PatsKiller/tardeai reopen 50",
    "gh issue --repo PatsKiller/tardeai comment 50 --body 'APPROVE_PUSH_STANDING wt/* until 2026-12-15'",
    "gh issue -R PatsKiller/tardeai edit 7 --title 'Standing push approvals'",
    "gh api repos/PatsKiller/tardeai/issues/50/comments -fbody='APPROVE_PUSH_STANDING wt/* until 2026-12-15'",
    "gh api repos/PatsKiller/tardeai/issues/50/comments -Fbody=@/tmp/approve.txt",
    "gh api -fbody='x' repos/PatsKiller/tardeai/issues/comments/123 -XPATCH",
    "gh api repos/o/r/issues/50/comments --input body.json", "gh api repos/o/r/issues/50/comments --input=body.json",
    "gh api --method=PATCH repos/o/r/issues/comments/9 -f body=x", "gh api -XDELETE repos/o/r/issues/comments/9",
    "gh api --method POST repos/o/r/pulls/1/reviews",
    "gh issue reopen 50", "gh issue close 50", "gh issue new --title x", "gh issue create --title t --body b",
    "gh issue delete 50 --yes", "gh issue transfer 50 o/r", "gh issue pin 5", "gh issue lock 5", "gh issue develop 5",
    "gh pr comment 2175 --body go", "gh pr review 2175 --approve", "gh alias set ic 'issue comment'",
    "gh alias import aliases.yml",
]
PREFIXED = [
    "/usr/bin/gh issue comment 5 -b x", "env GH_TOKEN=x gh issue comment 5 -b x", "FOO=1 command gh issue close 5",
    "bash -c 'gh issue reopen 50'", "sh -lc \"gh issue comment 5 -b x\"", "eval gh issue reopen 5",
    "echo x | xargs gh issue comment 5 -b", "cd /x && gh issue reopen 5", "true; gh issue reopen 5",
    "true\ngh issue reopen 5", "(gh issue reopen 5)", "$X issue comment 5 -b x", "$(which gh) issue comment 5 -b x",
    "`which gh` issue reopen 5", "timeout 30 gh issue reopen 5", "nohup gh issue reopen 5 &",
]
SECRET = ["gh auth token", "gh --hostname github.com auth token", "gh auth -h github.com token",
          "gh auth status -t", "gh auth status --show-token", "\"gh\" auth token", "env -u X gh auth token"]
GIT_PUSH = ["git \"push\" origin main", "git push origin main", "git -C . push origin x", "g\\it push",
            "git -c alias.p=push p", "git reset --hard HEAD~1", "git rebase main", "git filter-branch x",
            "/usr/bin/git push", "$(which git) push origin main", "bash -c 'git push -f origin main'",
            "git --no-pager -c core.x=y push"]
READS = ["gh issue view 50", "gh issue list --search comment", "gh pr create --title x --body y", "gh pr view 5",
         "gh issue -R o/r view 50", "gh api repos/o/r/issues/50/comments", "gh auth status", "gh alias list",
         "gh run list", "gh pr checks 5", "git status", "git log --oneline -5",
         "git reset HEAD f.txt", "\"$PYTHON\" -m pytest -q", "pytest -q tests/x.py", "ls -la", "echo $(date) ok",
         "gh --version", "gh"]


@pytest.mark.parametrize("cmd", ROOT_FLAG + QUOTING + EARLIER + PREFIXED)
def test_gh_writes_tokenize_to_gh_write(cmd):
    assert "gh-write" in tiers(cmd).split(), cmd
    assert _classify(cmd) == "gh-write", cmd


@pytest.mark.parametrize("cmd", SECRET)
def test_gh_auth_token_is_secret(cmd):
    assert tiers(cmd).split()[0] == "secret", cmd
    assert _classify(cmd) == "secret", cmd


@pytest.mark.parametrize("cmd", GIT_PUSH)
def test_git_push_forms_are_git_push(cmd):
    assert "git-push" in tiers(cmd).split(), cmd
    assert _classify(cmd) == "git-push", cmd


@pytest.mark.parametrize("cmd", READS)
def test_reads_stay_none(cmd):
    assert tiers(cmd) == "none", cmd
    assert _classify(cmd) == "none", cmd


def test_quoted_text_is_not_a_command():
    """The tokenizer reads a quoted message as one word (the older regex backstop may still over-classify it)."""
    assert tiers("git commit -m 'fix; git push later'") == "none"
    assert tiers("gh pr create --title x --body 'please gh issue comment 5'") == "none"


@pytest.mark.parametrize("cmd", ["gh issue \"comment", "gh issue 'reopen 5", "git 'push", "gh auth 'token"])
def test_unparseable_fails_closed(cmd):
    got = tiers(cmd).split()
    assert got != ["none"] and ("gh-write" in got or "git-push" in got or "secret" in got), (cmd, got)


def test_unknown_gh_word_may_be_an_alias_and_is_a_write():
    assert tiers("gh ic 5 --body x") == "gh-write"


# ------------------------------------------------------------------ through the real hook (guard-shell.sh)


@pytest.mark.parametrize("cmd", ROOT_FLAG + ["gh --hostname github.com auth token"] + QUOTING[:2]
                         + ["git \"push\" origin main"])
def test_r3_root_flag_and_quoting_denied_by_the_hook(E, cmd):
    assert E.hook(cmd).get("permission") != "allow", cmd


@pytest.mark.parametrize("cmd", ["gh issue view 50", "gh issue list --search comment", "git status"])
def test_reads_allowed_by_the_hook(E, cmd):
    assert E.hook(cmd).get("permission") == "allow", cmd


def test_helper_missing_fails_closed(tmp_path):
    lib = tmp_path / "hooks"
    shutil.copytree(HOOKS, lib, ignore=shutil.ignore_patterns("__pycache__", "guard_tokens.py"))
    def cls(cmd: str) -> str:
        return subprocess.run(["bash", "-c", 'source "$1"; classify_cmd "$2"', "_", str(lib / "guard-lib.sh"), cmd],
                              capture_output=True, text=True, check=True).stdout.strip()
    assert cls("\"gh\" issue view 5") == "gh-write"
    assert cls("git \"status\"") == "git-push"
    assert cls("ls") == "none"


# ------------------------------------------------------------------ mutants: each tokenizer rule is load-bearing


MUTANTS = {
    "shlex-unquote": ('        tokens = list(lex)\n', '        tokens = text.split()\n', "\"gh\" issue comment 5 -b y", "gh-write"),
    "global-flag-value": ('            if w in GH_GLOBAL_VALUE_FLAGS and i + 1 < len(args):\n                i += 1\n', '',
                          "gh -R o/r issue view 5", None),
    "noun-skip-flags": ('        if w.startswith("-"):\n            if w in GH_GLOBAL_VALUE_FLAGS', '        if False:\n            if w in GH_GLOBAL_VALUE_FLAGS',
                        "gh --repo o/r issue view 50", None),
    "verb-known-sub": ('    verb = next((w for w in rest if not w.startswith("-") and w in subs), None)',
                       '    verb = next((w for w in rest if not w.startswith("-")), None)',
                       "gh issue -R o/r comment 5 -b x", "gh-write"),
    "strip-path": ('    base = os.path.basename(head)\n    if base == "gh":', '    base = head\n    if base == "gh":',
                   "/usr/bin/gh issue comment 5", "gh-write"),
    "strip-env": ('        if _ASSIGN.match(w):\n            i += 1\n            continue\n', '',
                  "FOO=1 gh issue reopen 5", "gh-write"),
    "shell-c": ('                    return classify(argv[j + 1], depth + 1)', '                    return set()',
                "bash -c 'gh issue reopen 50'", "gh-write"),
    "dynamic-head": ('        return _gh(argv[1:], unknown_is_write=False) | _git(argv[1:])\n    base', '        return set()\n    base',
                     "$X issue comment 5", "gh-write"),
    "substitution-head": ('                out |= _simple(["$(...)"] + cur if after_close else cur, depth)',
                          '                out |= _simple(cur, depth)', "$(which gh) issue comment 5", "gh-write"),
    "newline-split": ('        lex.whitespace = " \\t\\r"  # an unquoted newline separates commands, like ;\n', '',
                      "true\ngh issue reopen 5", "gh-write"),
    "auth-token": ('        if verb == "token":\n            out.add("secret")', '        if verb == "token":\n            pass',
                   "gh --hostname github.com auth token", "secret"),
    "git-verb": ('    if verb in GIT_PUSH_VERBS or (verb == "reset" and "--hard" in rest):', '    if False:',
                 "git \"push\" origin main", "git-push"),
    "git-alias": ('        if w in ("-c",) and i + 1 < len(args) and args[i + 1].lower().startswith("alias."):\n            return {"git-push"}\n', '',
                  "git -c alias.p=push p", "git-push"),
    "api-write": ('                out.add("gh-write")\n            m = re.match', '                pass\n            m = re.match',
                  "gh api x -fbody=y", "gh-write"),
    "fail-closed": ('    except ValueError:\n        return _fail_closed(text)', '    except ValueError:\n        return set()',
                    "gh issue \"comment", "gh-write"),
    "unknown-alias": ('        return {"gh-write"} if unknown_is_write else out', '        return out', "gh ic 5", "gh-write"),
}


@pytest.mark.parametrize("name", sorted(MUTANTS))
def test_tokenizer_mutant_is_killed(tmp_path, name):
    old, new, cmd, want = MUTANTS[name]
    src = TOK.read_text()
    assert src.count(old) == 1, name
    mut = tmp_path / "guard_tokens.py"
    mut.write_text(src.replace(old, new))
    real, mutated = tiers(cmd).split(), tiers(cmd, mut).split()
    if want is None:  # global-flag-value: dropping the value skip must change the answer
        assert real != mutated, (name, real, mutated)
    else:
        assert want in real and want not in mutated, (name, real, mutated)
