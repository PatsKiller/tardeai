"""Operator packet docs/ops/packets/catalyst-consolidation-20261022/apply-operator.sh — hermetic rehearsal.

A fake `crontab` on PATH holds a >200 KB crontab (so a `crontab -l | grep -q` verify would hit SIGPIPE under
pipefail, the 2026-10-22 false-FAILED bug); the packet must preview without writing, install exactly the planned
crontab on APPLY, verify against a captured file, and refuse when the legacy lines are not in the expected state.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "docs" / "ops" / "packets" / "catalyst-consolidation-20261022" / "apply-operator.sh"
PRE = ("*/30 4-9 * * 1-5 cd $PROJ && env ALPACA_MODE=paper bash $PROJ/scripts/safe_flock.sh /tmp/catalyst_premarket.lock "
       "$PY scripts/catalyst_momentum_engine.py --band premarket_scalp --apply --generate-proposals "
       ">> logs/catalyst_momentum_engine.log 2>&1")
MKT = ("30 9-15 * * 1-5 cd $PROJ && env ALPACA_MODE=paper bash $PROJ/scripts/safe_flock.sh /tmp/catalyst_swing.lock "
       "$PY scripts/catalyst_momentum_engine.py --band market_swing --apply --generate-proposals "
       ">> logs/catalyst_momentum_engine.log 2>&1")
OVERNIGHT = ("0 18,22 * * * cd $PROJ && flock -n /tmp/catalyst_overnight.lock bash $PROJ/scripts/safe_flock.sh "
             "/tmp/catalyst_overnight.lock $PY scripts/catalyst_momentum_engine.py --band overnight --apply")


def _env(tmp: Path, crontab_text: str) -> dict:
    store = tmp / "crontab.txt"
    store.write_text(crontab_text)
    shim = tmp / "bin"
    shim.mkdir()
    (shim / "crontab").write_text(
        "#!/usr/bin/env bash\n"
        f'S="{store}"\n'
        'if [[ "$1" == "-l" ]]; then cat "$S"; elif [[ "$1" == "-" ]]; then cat > "$S"; else cp "$1" "$S"; fi\n')
    (shim / "crontab").chmod(0o755)
    env = dict(os.environ, PATH=f"{shim}:{os.environ['PATH']}", HOME=str(tmp), TRADEAI_CURRENT=str(ROOT),
               TRADEAI_PY=sys.executable, TRADEAI_PACKET_WORK=str(tmp / "work"))
    return env


def _big(lines: list[str]) -> str:
    filler = [f"# filler {i} " + "x" * 200 for i in range(1200)]
    return "\n".join(filler[:600] + lines + filler[600:]) + "\n"


def test_preview_changes_nothing(tmp_path):
    text = _big([PRE, MKT, OVERNIGHT])
    env = _env(tmp_path, text)
    r = subprocess.run(["bash", str(PACKET), "--preview"], env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PREVIEW ONLY" in r.stdout and (tmp_path / "crontab.txt").read_text() == text


def test_apply_installs_exactly_the_plan_and_verifies_without_false_failure(tmp_path):
    env = _env(tmp_path, _big([PRE, MKT, OVERNIGHT]))
    r = subprocess.run(["bash", str(PACKET)], env=env, input="APPLY\n", capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and "APPLIED and verified" in r.stdout, r.stdout + r.stderr
    out = (tmp_path / "crontab.txt").read_text().split("\n")
    assert "# RETIRED 2026-10-22 b-family B8/catalyst-momentum-engine " + PRE in out
    assert "# RETIRED 2026-10-22 b-family B8/catalyst-momentum-engine " + MKT in out
    assert PRE not in out and MKT not in out and OVERNIGHT in out
    fam = [ln for ln in out if "run_family_slot.py --family catalyst-momentum-engine" in ln and not ln.startswith("#")]
    assert [ln.split(" cd ")[0] for ln in fam] == ["0 4-9 * * 1-5", "30 4-15 * * 1-5"]


def test_refuses_when_the_legacy_lines_are_not_in_the_expected_state(tmp_path):
    text = _big([MKT, OVERNIGHT])  # premarket already gone
    env = _env(tmp_path, text)
    r = subprocess.run(["bash", str(PACKET)], env=env, input="APPLY\n", capture_output=True, text=True, timeout=120)
    assert r.returncode != 0 and "REFUSED" in (r.stdout + r.stderr)
    assert (tmp_path / "crontab.txt").read_text() == text


def test_not_confirmed_leaves_the_crontab(tmp_path):
    text = _big([PRE, MKT])
    env = _env(tmp_path, text)
    r = subprocess.run(["bash", str(PACKET)], env=env, input="apply\n", capture_output=True, text=True, timeout=120)
    assert r.returncode == 1 and "Not confirmed" in r.stdout and (tmp_path / "crontab.txt").read_text() == text
