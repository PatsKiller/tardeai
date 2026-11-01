#!/usr/bin/env python3
"""guard_tokens -- classify ``gh`` and ``git`` invocations by shell tokens, not by regex over the raw text.

Why (security reviews of #2450, #2451 and #2459, 2026-11-01): three rounds of regex patches in guard-lib.sh were
each evaded by another spelling the shell accepts -- flags before the verb (``gh issue -R o/r reopen``), flags
before the noun (``gh -R o/r issue comment``, ``gh --hostname h auth token``) and quoting (``"gh" issue comment``,
``gh issue "comment"``, ``com\\ment``, ``git "push"``). The shell removes quotes and backslashes before running a
command, so the guard must look at the words the shell will run.

Usage: ``python3 -I guard_tokens.py '<command>'`` prints the tiers that apply, space separated, in priority order
(``secret``, ``gh-write``, ``git-push``), or ``none``. guard-lib.sh checks membership at the position each tier had
in its classifier, so precedence against other tiers is unchanged. Exit 0 always; any internal error prints the
fail-closed answer for the raw text.

Rules
-----
* The command is split into simple commands at ``;`` ``&&`` ``||`` ``|`` ``&`` ``(`` ``)`` ``<`` ``>`` and newlines;
  backticks and ``$(`` open a nested command. ``bash|sh|zsh|dash -c '<s>'`` and ``eval <s>`` are classified
  recursively.
* argv[0] loses leading ``VAR=value`` assignments, ``env [-i] [-u NAME] [VAR=value]``, ``command``, ``exec``,
  ``nohup``, ``time``, ``xargs`` and any directory prefix (``/usr/bin/gh`` -> ``gh``).
* gh: global flags (and one value for a flag that takes one: -R/--repo/--hostname/-h) are skipped; the noun is the
  first word that is a known gh command; an unknown first word may be an alias and is treated as a write. The verb
  is the first word after the noun that is a known subcommand of that noun (so ``gh issue list --search comment``
  stays a read and ``gh issue -R o/r comment`` is a write).
* git: global options (-C <dir>, -c <k=v>, --git-dir=..., --no-pager, ...) are skipped; ``push``, ``rebase``,
  ``filter-branch`` and ``reset --hard`` are git-push; ``-c alias.*`` is git-push (an alias can hide a push).
* Fail closed: an unparseable command (unbalanced quotes; the shell would refuse it anyway), or an argv[0] that is a
  variable or command substitution, gets the strictest tier its remaining words could mean as gh or as git.
stdlib only.
"""

from __future__ import annotations

import os
import re
import shlex
import sys

PRIORITY = ("secret", "gh-write", "git-push")

GH_GLOBAL_VALUE_FLAGS = {"-R", "--repo", "--hostname", "-h"}
GH_COMMANDS = {
    "alias", "api", "attestation", "auth", "browse", "cache", "co", "codespace", "completion", "config",
    "extension", "extensions", "ext", "gist", "gpg-key", "help", "issue", "label", "org", "pr", "project",
    "release", "repo", "ruleset", "run", "search", "secret", "ssh-key", "status", "variable", "workflow",
    "version", "copilot", "agent-task", "preview",
}
GH_SUB = {
    "issue": {"create", "new", "list", "ls", "status", "view", "comment", "close", "reopen", "edit", "delete",
              "transfer", "pin", "unpin", "lock", "unlock", "develop"},
    "pr": {"create", "new", "list", "ls", "status", "view", "checkout", "co", "checks", "close", "comment", "diff",
           "edit", "lock", "merge", "ready", "reopen", "review", "revert", "unlock", "update-branch"},
    "auth": {"login", "logout", "refresh", "setup-git", "status", "switch", "token", "git-credential"},
    "alias": {"set", "import", "list", "ls", "delete", "remove", "rm"},
}
GH_WRITE = {
    "issue": {"comment", "create", "new", "edit", "reopen", "close", "delete", "transfer", "pin", "unpin", "lock",
              "unlock", "develop"},
    "pr": {"comment", "review"},
    "alias": {"set", "import"},
}
GIT_VALUE_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env",
                  "--super-prefix", "--list-cmds"}
GIT_PUSH_VERBS = {"push", "rebase", "filter-branch"}
WRAPPERS = {"command", "exec", "nohup", "time", "xargs", "builtin", "nice", "stdbuf", "timeout"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_SEPARATORS = {";", "&&", "||", "|", "&", "(", ")", "<", ">", ">>", "<<", "|&", ";;", "\n", "<<<", ">&", "<&", "&>"}


def _is_dynamic(word: str) -> bool:
    return word.startswith("$") or "$(" in word or "`" in word or "${" in word


def _strip_prefix(argv: list[str]) -> list[str]:
    i = 0
    while i < len(argv):
        w = argv[i]
        if _ASSIGN.match(w):
            i += 1
            continue
        base = os.path.basename(w)
        if base == "env":
            i += 1
            while i < len(argv) and (argv[i].startswith("-") or _ASSIGN.match(argv[i])):
                if argv[i] in ("-u", "--unset", "-C", "--chdir", "-S", "--split-string") and i + 1 < len(argv):
                    i += 1
                i += 1
            continue
        if base in WRAPPERS:
            i += 1
            while i < len(argv) and argv[i].startswith("-"):
                i += 1
            if base == "timeout" and i < len(argv):  # the duration
                i += 1
            continue
        break
    return argv[i:]


def _gh(args: list[str], unknown_is_write: bool = True) -> set[str]:
    out: set[str] = set()
    i, noun = 0, None
    while i < len(args):
        w = args[i]
        if w.startswith("-"):
            if w in GH_GLOBAL_VALUE_FLAGS and i + 1 < len(args):
                i += 1
            i += 1
            continue
        if w in GH_COMMANDS:
            noun = w
            i += 1
            break
        # an unknown first word may be a user alias wrapping any write: fail closed
        return {"gh-write"} if unknown_is_write else out
    if noun is None:
        return out
    rest = args[i:]
    if noun == "api":
        for j, w in enumerate(rest):
            if re.match(r"^(-f|-F|--field|--raw-field|--input)(=|$)", w) or re.match(r"^-[fF].", w):
                out.add("gh-write")
            m = re.match(r"^(?:-X|--method)(?:=)?(.*)$", w)
            if m:
                val = m.group(1) or (rest[j + 1] if j + 1 < len(rest) else "")
                if val.upper() in ("POST", "PATCH", "PUT", "DELETE"):
                    out.add("gh-write")
        return out
    subs = GH_SUB.get(noun)
    if subs is None:
        return out
    verb = next((w for w in rest if not w.startswith("-") and w in subs), None)
    if verb is None:
        return out
    if noun == "auth":
        if verb == "token":
            out.add("secret")
        elif verb == "status" and any(w in ("-t", "--show-token") or w.startswith("--show-token=") for w in rest):
            out.add("secret")
        return out
    if verb in GH_WRITE.get(noun, set()):
        out.add("gh-write")
    return out


def _git(args: list[str]) -> set[str]:
    i = 0
    while i < len(args):
        w = args[i]
        if not w.startswith("-"):
            break
        if w in ("-c",) and i + 1 < len(args) and args[i + 1].lower().startswith("alias."):
            return {"git-push"}
        if w.lower().startswith("-calias.") or w.lower().startswith("--config-env=alias."):
            return {"git-push"}
        if w in GIT_VALUE_OPTS and "=" not in w:
            i += 1
        i += 1
    if i >= len(args):
        return set()
    verb, rest = args[i], args[i + 1:]
    if verb in GIT_PUSH_VERBS or (verb == "reset" and "--hard" in rest):
        return {"git-push"}
    return set()


def _simple(argv: list[str], depth: int) -> set[str]:
    argv = _strip_prefix(argv)
    if not argv:
        return set()
    head = argv[0]
    if _is_dynamic(head):  # $x issue comment / $(which gh) ...: assume the worst it could be
        return _gh(argv[1:], unknown_is_write=False) | _git(argv[1:])
    base = os.path.basename(head)
    if base == "gh":
        return _gh(argv[1:])
    if base == "git":
        return _git(argv[1:])
    if base in SHELLS and depth < 4:
        for j, w in enumerate(argv[1:], 1):
            if w == "-c" or (w.startswith("-") and not w.startswith("--") and "c" in w[1:]):
                if j + 1 < len(argv):
                    return classify(argv[j + 1], depth + 1)
        return set()
    if base == "eval" and depth < 4:
        return classify(" ".join(argv[1:]), depth + 1)
    return set()


def _fail_closed(text: str) -> set[str]:
    flat = re.sub(r"[\"'\\]", "", text)
    words = set(re.findall(r"[A-Za-z][A-Za-z0-9._-]*", flat))
    out: set[str] = set()
    if "gh" in words:
        out.add("gh-write")
        if "token" in words or "--show-token" in flat or re.search(r"(^|\s)-t(\s|$)", flat):
            out.add("secret")
    if "git" in words:
        out.add("git-push")
    if not out and re.search(r"\$|`", flat):
        out |= _gh(flat.split()[1:], unknown_is_write=False) | _git(flat.split()[1:])
    return out


def classify(text: str, depth: int = 0) -> set[str]:
    parts = text.split("`")  # `cmd` opens and closes a nested command, alternately
    text = "".join(part + ((" ( " if k % 2 == 0 else " ) ") if k < len(parts) - 1 else "") for k, part in enumerate(parts))
    text = text.replace("$(", " ( ")
    try:
        lex = shlex.shlex(text, posix=True, punctuation_chars="();<>|&\n")
        lex.whitespace = " \t\r"  # an unquoted newline separates commands, like ;
        lex.whitespace_split = True
        lex.commenters = ""
        tokens = list(lex)
    except ValueError:
        return _fail_closed(text)
    out: set[str] = set()
    cur: list[str] = []
    after_close = False  # words right after ")" are run with the substitution's output as argv[0]
    for t in tokens + [";"]:
        if t in _SEPARATORS or (t and set(t) <= set("();<>|&\n")):
            if cur:
                out |= _simple(["$(...)"] + cur if after_close else cur, depth)
            cur = []
            after_close = ")" in t
        else:
            cur.append(t)
    return out


def main(argv: list[str]) -> int:
    text = argv[1] if len(argv) > 1 else sys.stdin.read()
    try:
        tiers = classify(text)
    except Exception:  # noqa: BLE001 - a guard reports the strictest answer, never crashes into a pass
        tiers = _fail_closed(text) or {"gh-write"}
    print(" ".join(t for t in PRIORITY if t in tiers) or "none")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
