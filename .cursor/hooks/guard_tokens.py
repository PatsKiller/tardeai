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
    "pr": {"comment", "review", "merge"},
    "alias": {"set", "import"},
}
GIT_VALUE_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env",
                  "--super-prefix", "--list-cmds"}
GIT_PUSH_VERBS = {"push", "rebase", "filter-branch"}
WRAPPERS = {"command", "exec", "nohup", "time", "xargs", "builtin", "nice", "stdbuf", "timeout", "ionice", "taskset", "setsid"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_SEPARATORS = {";", "&&", "||", "|", "&", "(", ")", "<", ">", ">>", "<<", "|&", ";;", "\n", "<<<", ">&", "<&", "&>"}


def _is_dynamic(word: str) -> bool:
    return word.startswith("$") or "$(" in word or "`" in word or "${" in word


# Each wrapper has its own option grammar. Skipping only words beginning with
# "-" leaves a value (nice -n 5) in argv[0] and hides the command behind it.
_WRAPPER_VALUE = {
    "exec": {"a"}, "time": {"f", "o"}, "nice": {"n"},
    "stdbuf": {"i", "o", "e"}, "timeout": {"k", "s"},
    "ionice": {"c", "n", "p", "P", "u"},
    "xargs": {"a", "d", "E", "I", "L", "n", "P", "s"},
}
_WRAPPER_LONG_VALUE = {
    "time": {"format", "output"}, "nice": {"adjustment"},
    "stdbuf": {"input", "output", "error"}, "timeout": {"kill-after", "signal"},
    "ionice": {"class", "classdata", "pid", "pgid", "uid"},
    "xargs": {"arg-file", "delimiter", "eof", "replace", "max-lines", "max-args",
              "max-procs", "max-chars", "process-slot-var"},
}
_WRAPPER_FLAGS = {
    "command": set("pVv"), "exec": set("cl"), "nohup": set(),
    "time": set("apqv"), "nice": set(), "stdbuf": set(),
    "timeout": set("v"), "ionice": set("t"), "taskset": set("apc"),
    "setsid": set("cfw"), "builtin": set(), "xargs": set("0prtx"),
}
_WRAPPER_LONG_FLAGS = {
    "time": {"append", "portability", "quiet", "verbose"},
    "timeout": {"foreground", "preserve-status", "verbose"},
    "ionice": {"ignore"}, "taskset": {"all-tasks", "pid", "cpu-list"},
    "setsid": {"ctty", "fork", "wait"},
    "xargs": {"null", "interactive", "no-run-if-empty", "verbose", "exit", "show-limits"},
}
_WRAPPER_NUMERIC = {
    "nice": {"n", "adjustment"}, "ionice": {"c", "n", "p", "P", "u", "class", "classdata", "pid", "pgid", "uid"},
    "xargs": {"L", "n", "P", "s", "max-lines", "max-args", "max-procs", "max-chars"},
}


def _wrapper_value(base: str, option: str, value: str) -> None:
    if not value or value == "--" or _is_dynamic(value):
        raise ValueError("missing or dynamic wrapper option value")
    if option in _WRAPPER_NUMERIC.get(base, set()) and not re.fullmatch(r"[+-]?\d+", value):
        raise ValueError("invalid numeric wrapper option value")


def _wrapper_end(argv: list[str], start: int, base: str) -> int:
    i = start
    taskset_mask_attached = False
    while i < len(argv):
        word = argv[i]
        if word == "--":
            i += 1
            break
        if not word.startswith("-") or word == "-":
            break
        if base == "nice" and re.fullmatch(r"-\d+", word):
            i += 1  # Historical nice -5 COMMAND spelling.
            continue
        if base == "taskset" and (word.startswith("-c") and len(word) > 2
                                  or word.startswith("--cpu-list=")):
            value = word.split("=", 1)[1] if word.startswith("--") else word[2:]
            if not re.fullmatch(r"\d+(?:[-,:]\d+)*", value):
                raise ValueError("invalid attached taskset mask")
            taskset_mask_attached = True
            i += 1
            continue
        if word.startswith("--"):
            option, equal, value = word[2:].partition("=")
            if base == "xargs" and option in {"eof", "replace", "max-lines"}:
                if equal:
                    _wrapper_value(base, option, value)
            elif option in _WRAPPER_LONG_VALUE.get(base, set()):
                if not equal:
                    i += 1
                    if i >= len(argv):
                        raise ValueError("missing wrapper option value")
                    value = argv[i]
                _wrapper_value(base, option, value)
            elif option not in _WRAPPER_LONG_FLAGS.get(base, set()) or equal:
                raise ValueError("unknown wrapper option")
        else:
            j = 1
            while j < len(word):
                option = word[j]
                # GNU xargs optional values are attached only: bare -i/-e/-l
                # must not swallow a following command called gh or git.
                if base == "xargs" and option in {"i", "e", "l"}:
                    if j + 1 < len(word):
                        _wrapper_value(base, option, word[j + 1:])
                    break
                if option in _WRAPPER_VALUE.get(base, set()):
                    value = word[j + 1:]
                    if not value:
                        i += 1
                        if i >= len(argv):
                            raise ValueError("missing wrapper option value")
                        value = argv[i]
                    _wrapper_value(base, option, value)
                    break
                if option not in _WRAPPER_FLAGS.get(base, set()):
                    raise ValueError("unknown wrapper option")
                j += 1
        i += 1
    if base == "timeout":
        if i >= len(argv) or not re.fullmatch(r"(?:\d+(?:\.\d*)?|\.\d+)[smhd]?", argv[i]):
            raise ValueError("missing or invalid timeout duration")
        i += 1
    elif base == "taskset" and not taskset_mask_attached:
        if i >= len(argv) or not re.fullmatch(r"(?:0x)?[0-9a-fA-F]+(?:[-,:][0-9a-fA-F]+)*", argv[i]):
            raise ValueError("missing or invalid taskset mask")
        i += 1
    return i


def _env_prefix(argv: list[str], start: int) -> tuple[list[str], int]:
    i = start
    while i < len(argv):
        word = argv[i]
        if _ASSIGN.match(word):
            i += 1
            continue
        if word == "--":
            return argv, i + 1
        if word in {"-", "-i", "--ignore-environment", "-0", "--null", "--debug", "--list-signal-handling"}:
            i += 1
            continue
        if not word.startswith("-"):
            break
        if word.startswith("--"):
            option, equal, value = word[2:].partition("=")
            if option in {"default-signal", "ignore-signal", "block-signal"}:
                i += 1  # Optional value is attached with "="; it never eats the command.
                continue
            if option not in {"unset", "chdir", "split-string", "argv0"}:
                raise ValueError("unknown env option")
            consumed = 1 if equal else 2
            if not equal:
                if i + 1 >= len(argv):
                    raise ValueError("missing env option value")
                value = argv[i + 1]
        else:
            # -iuNAME and -iS'COMMAND ...' are legal short-option clusters.
            rest = word[1:]
            while rest.startswith(("i", "0")):
                rest = rest[1:]
            if not rest:
                i += 1
                continue
            option, value = rest[0], rest[1:]
            option = {"u": "unset", "C": "chdir", "S": "split-string", "a": "argv0"}.get(option, "")
            if not option:
                raise ValueError("unknown env option")
            consumed = 1 if value else 2
            if not value:
                if i + 1 >= len(argv):
                    raise ValueError("missing env option value")
                value = argv[i + 1]
        _wrapper_value("env", option, value)
        if option == "split-string":
            # GNU env has extra escape/expansion rules. Ambiguous spellings
            # refuse rather than interpreting them as an empty/benign command.
            if "\\" in value or "$" in value:
                raise ValueError("ambiguous env split-string")
            words = shlex.split(value)
            if not words:
                raise ValueError("empty env split-string")
            argv = argv[:i] + words + argv[i + consumed:]
        else:
            i += consumed
    return argv, i


def _strip_prefix(argv: list[str]) -> list[str]:
    i = 0
    while i < len(argv):
        w = argv[i]
        if _ASSIGN.match(w):
            i += 1
            continue
        base = os.path.basename(w)
        if base == "env":
            argv, i = _env_prefix(argv, i + 1)
            continue
        if base in WRAPPERS:
            i = _wrapper_end(argv, i + 1, base)
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
    if verb == "config" and _git_config_writes_an_alias(rest):
        # Review 2 of #2459 (2026-11-02): a PERSISTENT alias defeated this classifier.
        # `git config alias.p push` followed by `git p origin <branch>` showed as `none` for both
        # commands, and on this host .git/hooks/pre-push runs only the secrets scan, so those two
        # agent-typed commands would reach GitHub with no approval, no grant and no budget.
        # The guarantee is "no alias can be CREATED", not "an existing alias is caught": `git p`
        # cannot be resolved without reading config, which this classifier never does.
        return {"git-push"}
    return set()


#: `git config` sub-commands that only read. Everything else is a write.
_GIT_CONFIG_READS = frozenset({"get", "get-all", "list", "show", "show-origin", "show-scope", "--get",
                               "--get-all", "--list", "--show", "--show-origin", "--show-scope", "-l"})
#: `git config` options that consume the following argument as their value.
_GIT_CONFIG_VALUE_OPTS = frozenset({"--file", "-f", "--type", "--blob", "--default", "--comment"})


def _git_config_writes_an_alias(rest: list[str]) -> bool:
    """True when a `git config` invocation writes an `alias.*` key.

    Handles `alias.x y`, `--local/--global/--system`, `--add`, `-f`/`--file <path>`, and the
    `key=value` form. A bare read (`--list`, `--get user.name`) stays unguarded.
    """
    args = list(rest)
    j = 0
    while j < len(args):
        w = args[j]
        if w in _GIT_CONFIG_VALUE_OPTS:
            j += 2
            continue
        if w.startswith("--file="):
            j += 1
            continue
        if w.startswith("-"):
            j += 1
            continue
        break
    if j >= len(args):
        return False
    first = args[j]
    if first in _GIT_CONFIG_READS or first.split("=", 1)[0] in _GIT_CONFIG_READS:
        return False
    key = first.split("=", 1)[0].strip().lower()
    return key == "alias" or key.startswith("alias.")


def _simple(argv: list[str], depth: int) -> set[str]:
    try:
        argv = _strip_prefix(argv)
    except ValueError:
        return _fail_closed(" ".join(argv)) or {"gh-write"}
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
