"""The cutover factory reads the `bash -c "set -a; . ./.env; set +a; <command>"` wrapper (LQ-20261107-22).

Most cron lines wrap the lane in a shell so the line can source the reviewable env file. `parse_lane_argv` split the
line with shlex, so the whole inner command was ONE token; the script therefore never appeared on the line and the
gate answered `script_not_on_cron_line` for a line that plainly carries it. The two lanes blocked by that answer were
`finviz-market-movers` and `fee-efficiency-analyzer` (both shadow, both allowlisted, both with a REVIEWED contract).

The fix flattens `bash -c '<cmd>'` into the tokens of `<cmd>` before the argv search. It does not widen what is
accepted: the script must still appear, the argv after it must still equal the allowlist command tail, the env
prologue is mapped because the executor reproduces it from `env_names` (never by sourcing the file), and a `-c`
string carrying two script commands is refused rather than guessed at.

Hermetic: an in-memory crontab, a hard-coded allowlist command; nothing reads the host crontab, a secret or the
network.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import n8n_cutover_wave as W  # noqa: E402

CMD = ["$PY", "scripts/demo_lane.py"]


def _p(body: str, cmd=CMD):
    return W.parse_lane_argv(W.command_of("0 10 * * 1-5 " + body), list(cmd))


# ── the wrapper is mapped ─────────────────────────────────────────────────────────────────────


def test_env_sourcing_wrapper_is_mapped_and_the_argv_survives():
    p = _p('cd $PROJ && flock -n /tmp/demo.lock bash -c "set -a; . ./.env; set +a; '
           '$PY scripts/demo_lane.py --emit" >> logs/demo.log 2>&1')
    assert p["problems"] == []
    assert p["live_arg"] == ["--emit"]


def test_wrapper_with_args_already_in_the_allowlist_command():
    p = _p('cd $PROJ && flock -n /tmp/demo.lock bash -c "set -a; . ./.env; set +a; '
           '$PY scripts/demo_lane.py" >> logs/demo.log 2>&1')
    assert p["problems"] == []
    assert p["live_arg"] == []


def test_an_absolute_interpreter_inside_the_wrapper_still_locates_the_script():
    """What this fix owes is the script (and its argv), not the interpreter whitelist in _PREFIX_OK."""
    line = ('cd $PROJ && flock -n /tmp/demo.lock bash -c "set -a; . ./.env; set +a; '
            '/opt/venv/bin/python scripts/demo_lane.py" >> logs/demo.log 2>&1')
    p = _p(line)
    assert "script_not_on_cron_line:scripts/demo_lane.py" not in p["problems"]
    assert p["live_arg"] == []


# ── the fix does not widen what the gate accepts ─────────────────────────────────────────────


def test_the_script_must_still_be_on_the_line():
    p = _p('cd $PROJ && flock -n /tmp/demo.lock bash -c "set -a; . ./.env; set +a; $PY scripts/other_lane.py"')
    assert p["problems"] == ["script_not_on_cron_line:scripts/demo_lane.py"]
    assert p["live_arg"] is None


def test_args_that_contradict_the_allowlist_command_are_still_refused():
    p = _p('cd $PROJ && flock -n /tmp/demo.lock bash -c "set -a; . ./.env; set +a; '
           '$PY scripts/demo_lane.py --apply"', cmd=["$PY", "scripts/demo_lane.py", "--emit"])
    assert any(x.startswith("allowlist_command_args_not_on_cron_line:") for x in p["problems"])
    assert p["live_arg"] is None


def test_two_script_commands_in_one_c_string_are_refused_not_guessed():
    p = _p('cd $PROJ && bash -c "set -a; . ./.env; $PY scripts/demo_lane.py && $PY scripts/other_lane.py"')
    assert any(x.startswith("bash_c_wrapper_multiple_scripts:") for x in p["problems"])


def test_an_unparseable_c_string_is_named():
    p = _p('cd $PROJ && bash -c "set -a; . ./.env; $PY scripts/demo_lane.py \'unclosed"')
    assert any(x.startswith("bash_c_wrapper_unparseable:") for x in p["problems"])


# ── an env assignment is still unmapped inside or outside the wrapper ────────────────────────


def test_an_unmapped_env_assignment_inside_the_wrapper_is_still_reported():
    p = _p('cd $PROJ && FOO=bar bash -c "set -a; . ./.env; set +a; $PY scripts/demo_lane.py"')
    assert "unmapped_wrapper:env:FOO" in p["problems"]


def test_the_untouched_tokens_are_unchanged_outside_a_wrapper():
    toks, inner_seps, problems = W._expand_bash_c(W._tokens("cd $PROJ && flock -n /tmp/x.lock $PY scripts/demo_lane.py"))
    assert problems == [] and inner_seps == set()
    assert toks[-2:] == ["$PY", "scripts/demo_lane.py"]
