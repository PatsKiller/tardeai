"""The overnight lane's schedule and its guard were mutually exclusive.

`hermes-deep-research-local.timer` runs OnCalendar 22:00-05:35 ET. The DeepSeek
peak guard permits 10:00-21:00 ET. Those windows never overlap, so every timer
fire logged

    SKIPPED_DEEPSEEK_PEAK: window=as-needed-only bulk Flash/Pro is 10:00-21:00
    America/New_York; outside that is as-needed only.

and exited 0. Result=success on every run, attempts_24h=0, and the lane had
never once executed.

The guard keyed on `flash`, computed from primary_provider() BEFORE the
overnight branch rewrites args.model to "chatgpt". So a DeepSeek COST control
was refusing a free OAuth lane, protecting against spend that could not occur.

Verified after the fix by running the exact systemd command:
    model=chatgpt apply=True targets=['SPRC','IVF','AXTI']
    3 rows COMMITTED, RESULT {"applied": 3}
    lane health: overnight-deep ok=True attempts_24h=3
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "scripts" / "hermes_deep_research_local.py"


def _guard_condition() -> str:
    text = SRC.read_text(encoding="utf-8")
    m = re.search(r"^\s*if flash and .*?is_deepseek_offpeak is not None:", text, re.M)
    assert m, "the DeepSeek peak guard condition was not found"
    return m.group(0)


def test_the_peak_guard_keys_on_the_effective_model():
    """`flash` reflects the configured provider, not what this run will call."""
    assert "uses_deepseek" in _guard_condition(), (
        "the guard still fires on `flash` alone, so an overnight chatgpt run is "
        "blocked by a DeepSeek cost control")


def test_the_effective_model_is_read_after_the_overnight_override():
    """Order matters: args.model is rewritten to chatgpt by the overnight branch,
    so uses_deepseek must be computed after that, not from the initial default."""
    text = SRC.read_text(encoding="utf-8")
    override = text.index('args.model = "chatgpt"')
    computed = text.index("uses_deepseek = ")
    assert computed > override, (
        "uses_deepseek is computed before the overnight override and will be stale")


def test_the_guard_still_protects_real_deepseek_runs():
    """The spend ceiling is the point of this guard. It must survive."""
    cond = _guard_condition()
    assert "flash" in cond, "the provider check was dropped entirely"
    assert "is_deepseek_offpeak" in cond, "the off-peak window check was dropped"


def test_a_deepseek_model_still_matches_the_guard():
    """The default model is deepseek-v4-flash; the predicate must catch it."""
    text = SRC.read_text(encoding="utf-8")
    assert 'startswith("deepseek")' in text
    assert '--model", default="deepseek-v4-flash"' in text.replace("'", '"'), (
        "the default model changed; re-check that the guard predicate still matches it")
