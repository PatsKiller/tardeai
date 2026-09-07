"""Two always-on findings that were never about the system they measured.

RELEASE PIN
    [P0] Release pin mismatch: expected .../20260807-124637, live <today>

`expected_release_pin.txt` was created 2026-08-07 and no code ever wrote it
again — the deploy script contained zero references to it. Every promote for a
month left it stale, so the health inspector reported P0 on every run.

A P0 that is always on is not a control. The one time the pin genuinely
disagrees it reads exactly like the previous thirty.

PORTFOLIO VALIDATOR
    [P2] Portfolio validation failed: PortfolioValidator.__init__() got an
         unexpected keyword argument 'live_dir'

The health inspector has always called `PortfolioValidator(live_dir=live_dir)`;
`__init__` accepted nothing. So the P2 reported a TypeError instead of a
portfolio check, and portfolio validation has never actually run from that path.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

DEPLOY = ROOT / "scripts" / "cio_phase2_exact_main_deploy.sh"


# ── the deploy must maintain the pin it is measured against ─────────────────

def test_promote_writes_the_expected_release_pin():
    src = DEPLOY.read_text(encoding="utf-8")
    assert "write_expected_release_pin" in src
    promote = src.split("cmd_promote()", 1)[1].split("\n}", 1)[0]
    assert "write_expected_release_pin" in promote, (
        "promote does not update the pin — it goes stale again on the next deploy")


def test_the_pin_is_written_where_the_reader_actually_looks():
    """The health-inspect skill checks the dev tree FIRST (its TRADEAI_ROOT).
    Writing only the releases-dir copy would fix nothing, because the stale
    dev-tree file shadows it."""
    src = DEPLOY.read_text(encoding="utf-8")
    fn = src.split("write_expected_release_pin() {", 1)[1].split("\n}", 1)[0]
    assert "data/runtime/expected_release_pin.txt" in fn
    assert "EXPECTED_RELEASE" in fn


def test_an_unwritable_pin_is_reported_not_swallowed():
    """A silent failure here restores the exact defect: the inspector keeps
    comparing against a stale value and nobody knows why."""
    src = DEPLOY.read_text(encoding="utf-8")
    fn = src.split("write_expected_release_pin() {", 1)[1].split("\n}", 1)[0]
    assert "WARN" in fn, "a pin that cannot be written leaves no trace"


def test_the_pin_writer_actually_writes_both_files(tmp_path):
    """Behaviour, not just shape — run the function against a sandbox HOME."""
    fn = DEPLOY.read_text(encoding="utf-8")
    body = "write_expected_release_pin() {" + \
        fn.split("write_expected_release_pin() {", 1)[1].split("\n}", 1)[0] + "\n}"
    script = (
        f'HOME="{tmp_path}"\n'
        f'RELEASES_BASE="$HOME/trade-ai-releases/portfolio-server"\n'
        'log(){ :; }\n'
        f"{body}\n"
        'write_expected_release_pin "/rel/TESTREL-1"\n'
    )
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr

    dev = tmp_path / "trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/runtime/expected_release_pin.txt"
    rel = tmp_path / "trade-ai-releases/portfolio-server/EXPECTED_RELEASE"
    assert dev.is_file() and dev.read_text().strip() == "/rel/TESTREL-1"
    assert rel.is_file() and rel.read_text().strip() == "/rel/TESTREL-1"


def test_the_deploy_script_still_parses():
    r = subprocess.run(["bash", "-n", str(DEPLOY)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


# ── the validator must accept the argument its only caller passes ───────────

def test_portfolio_validator_accepts_live_dir():
    """The exact call the health inspector makes."""
    from scripts.lib.portfolio_validator import PortfolioValidator

    v = PortfolioValidator(live_dir="/rel/abc")
    assert v.live_dir == "/rel/abc"


def test_it_still_constructs_without_one():
    from scripts.lib.portfolio_validator import PortfolioValidator

    assert PortfolioValidator().live_dir is None


def test_live_dir_is_recorded_not_swallowed():
    """Accepting a parameter only to discard it would fix the traceback and keep
    the silence. A finding that cannot name its subject is the weaker finding."""
    from scripts.lib.portfolio_validator import PortfolioValidator

    v = PortfolioValidator(live_dir="/rel/abc")
    v.findings = [{"severity": "P1", "type": "x"}]
    assert v._tagged()[0]["live_dir"] == "/rel/abc"


def test_findings_are_tagged_at_every_exit():
    """Three return points, not every append site: a finding added later cannot
    forget to be tagged."""
    src = (ROOT / "scripts" / "lib" / "portfolio_validator.py").read_text(encoding="utf-8")
    assert "return self.findings" not in src, (
        "a raw return bypasses tagging — findings would leave unattributed")
    assert src.count("return self._tagged()") >= 3


def test_an_untagged_validator_does_not_invent_a_subject():
    """No live_dir means no live_dir claim, not a guessed one."""
    from scripts.lib.portfolio_validator import PortfolioValidator

    v = PortfolioValidator()
    v.findings = [{"severity": "P1", "type": "x"}]
    assert "live_dir" not in v._tagged()[0]


def test_the_health_inspector_call_shape_is_satisfied():
    """Guard against a future signature change breaking the only caller again."""
    import inspect

    from scripts.lib.portfolio_validator import PortfolioValidator

    sig = inspect.signature(PortfolioValidator.__init__)
    assert "live_dir" in sig.parameters
    assert sig.parameters["live_dir"].default is None
