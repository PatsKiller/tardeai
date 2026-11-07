"""`PYTHONPATH=<the tree the line cd's into>` is mapped; any other value stays unmapped (LQ-20261107-22).

One shadow lane (`aegis-evening-packet`, cron L907) is held only by `unmapped_wrapper:env:PYTHONPATH`:

    cd <served code root> && PYTHONPATH=<served code root> flock -n /tmp/aegis_evening_packet.lock $PY ...

The value names the directory the line already changes into, so it is the lane's own tree, not a hidden
import root — and in that lane it is redundant: scripts/aegis_evening_packet.py:25 puts ROOT on sys.path
itself, with the comment recording that the PYTHONPATH wrapper was the workaround for a script that no
longer needs it. The executor runs from the code root and does not set PYTHONPATH, which is exactly why
the script was fixed rather than the wrapper reproduced.

This does not widen what the gate accepts: the value must equal a `cd` target on the same line. A value
pointing anywhere else is still an unmapped wrapper, and a line with no `cd` at all keeps the old answer.

Hermetic: in-memory cron lines, a synthetic tree path; nothing reads the host crontab, a secret or the
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
TREE = "/srv/lane-tree"


def _parse(line: str, cmd=CMD):
    return W.parse_lane_argv("0 10 * * 1-5 " + line, list(cmd))


def test_pythonpath_naming_the_cd_tree_is_mapped():
    p = _parse(f"cd {TREE} && PYTHONPATH={TREE} flock -n /tmp/demo.lock $PY scripts/demo_lane.py >> l 2>&1")
    assert p["problems"] == []
    assert p["live_arg"] == []


def test_the_cd_tree_may_be_a_shell_variable():
    for var in ("$PROJ", "${PROJ}"):
        p = _parse(f"cd {var} && PYTHONPATH={var} flock -n /tmp/demo.lock $PY scripts/demo_lane.py")
        assert p["problems"] == [], var


def test_pythonpath_pointing_elsewhere_is_still_unmapped():
    p = _parse(f"cd {TREE} && PYTHONPATH=/somewhere/else $PY scripts/demo_lane.py")
    assert "unmapped_wrapper:env:PYTHONPATH" in p["problems"]


def test_pythonpath_with_no_cd_on_the_line_is_still_unmapped():
    p = _parse(f"PYTHONPATH={TREE} $PY scripts/demo_lane.py")
    assert "unmapped_wrapper:env:PYTHONPATH" in p["problems"]


def test_pythonpath_naming_a_different_cd_tree_is_still_unmapped():
    p = _parse(f"cd {TREE} && PYTHONPATH=/srv/other $PY scripts/demo_lane.py")
    assert "unmapped_wrapper:env:PYTHONPATH" in p["problems"]


def test_every_other_env_assignment_keeps_its_answer():
    p = _parse(f"cd {TREE} && PYTHONPATH={TREE} FOO=bar $PY scripts/demo_lane.py")
    assert p["problems"] == ["unmapped_wrapper:env:FOO"]
