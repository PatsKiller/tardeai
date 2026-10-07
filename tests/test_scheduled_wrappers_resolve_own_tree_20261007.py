"""2026-10-07 (cron tranche B step 1): three cron wrappers hardcoded the dev tree as PROJ, so a cron line that
`cd`s into the served CURRENT tree still executed dev-tree code (study §6, DEV_TREE_WRAPPER). They now default
to the tree they live in; an explicit PROJ env still wins. Hermetic: copies the wrapper into a tmp tree."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WRAPPERS = [
    "scripts/run_scheduled_atp2_research_cycle.sh",
    "scripts/run_scheduled_stale_proposal_sweeper.sh",
    "scripts/run_scheduled_strategy_audits.sh",
]


def test_no_wrapper_hardcodes_the_dev_tree():
    for w in WRAPPERS:
        text = (ROOT / w).read_text()
        assert "trade-ai-v12-rebuild" not in text, w
        assert re.search(r'^PROJ="\$\{PROJ:-\$\(cd "\$\(dirname "\$\{BASH_SOURCE\[0\]\}"\)/\.\." && pwd\)\}"$', text, re.M), w


def test_proj_defaults_to_the_wrappers_own_tree_and_env_wins(tmp_path):
    tree = tmp_path / "served"
    (tree / "scripts").mkdir(parents=True)
    for w in WRAPPERS:
        shutil.copy(ROOT / w, tree / w)
        line = next(l for l in (tree / w).read_text().splitlines() if l.startswith("PROJ="))
        probe = tree / "scripts" / ("probe_" + Path(w).name)
        probe.write_text("#!/usr/bin/env bash\n" + line + "\necho \"$PROJ\"\n")
        got = subprocess.run(["bash", str(probe)], capture_output=True, text=True, check=True).stdout.strip()
        assert got == str(tree), (w, got)
        forced = subprocess.run(["bash", str(probe)], capture_output=True, text=True, check=True,
                                env={"PROJ": "/elsewhere", "PATH": "/usr/bin:/bin"}).stdout.strip()
        assert forced == "/elsewhere", w


def test_py_comes_from_the_environment_and_a_missing_interpreter_fails_loudly(tmp_path):
    """The served tree has no .venv; the crontab exports PY. Without it the wrapper must stop with exit 78,
    not run system python3 against the project."""
    for w in WRAPPERS:
        text = (ROOT / w).read_text()
        assert 'PY="${PY:-$PROJ/.venv/bin/python}"' in text, w
        assert 'exit 78' in text, w
        head = "\n".join(l for l in text.splitlines() if l.startswith(("PROJ=", "PY=", "[ -x \"$PY\" ]")))
        probe = tmp_path / ("probe_" + Path(w).name)
        probe.write_text("#!/usr/bin/env bash\n" + head + "\necho \"$PY\"\n")
        missing = subprocess.run(["bash", str(probe)], capture_output=True, text=True,
                                 env={"PATH": "/usr/bin:/bin"})
        assert missing.returncode == 78 and "PY not executable" in missing.stderr, w
        ok = subprocess.run(["bash", str(probe)], capture_output=True, text=True,
                            env={"PATH": "/usr/bin:/bin", "PY": "/bin/true"})
        assert ok.returncode == 0 and ok.stdout.strip() == "/bin/true", w
