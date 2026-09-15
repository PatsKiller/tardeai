"""2026-09-15: cron_dead_script_ref resolves each script the way cron runs the line."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_cron_sanity as ccs  # noqa: E402


def _tree(tmp_path):
    proj = tmp_path / "proj"; (proj / "scripts").mkdir(parents=True)
    (proj / "scripts" / "live.py").write_text("")
    other = tmp_path / "other"; (other / "scripts").mkdir(parents=True)
    (other / "scripts" / "run_pipeline.py").write_text("")
    skills = tmp_path / "skills" / "scripts"; skills.mkdir(parents=True)
    (skills / "ops_daily_digest.py").write_text("")
    return proj, other, skills


def test_lines_that_cd_elsewhere_or_use_absolute_paths_resolve_where_cron_runs_them(tmp_path):
    proj, other, skills = _tree(tmp_path)
    crontab = "\n".join([
        f"PROJ={proj}",
        "PY=/usr/bin/python3",
        "0 5 * * * cd $PROJ && $PY scripts/live.py >> logs/x.log 2>&1",
        f"0 6 * * * cd {other} && .venv/bin/python3 scripts/run_pipeline.py >> logs/p.log 2>&1",
        f"0 7 * * * /usr/bin/python3 {skills}/ops_daily_digest.py",
        "0 8 * * * cd $PROJ && $PY scripts/never_merged.py",
        "# 0 9 * * * cd $PROJ && $PY scripts/commented_out.py",
    ])
    refs = {ref: path for ref, path, _ in ccs.resolve_script_refs(crontab, proj)}
    assert refs["scripts/live.py"].is_file()
    assert refs["scripts/run_pipeline.py"].is_file()
    assert refs["scripts/ops_daily_digest.py"].is_file()
    assert not refs["scripts/never_merged.py"].is_file()
    assert "scripts/commented_out.py" not in refs


def test_a_line_without_cd_resolves_against_the_repo(tmp_path):
    proj, _, _ = _tree(tmp_path)
    refs = ccs.resolve_script_refs("*/5 * * * * python3 scripts/live.py", proj)
    assert refs[0][1] == proj / "scripts" / "live.py"
