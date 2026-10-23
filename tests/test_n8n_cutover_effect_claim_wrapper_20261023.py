"""The cutover factory reads the §23.25 effect-claim wrapper (T-20261023-f7771f, 2026-10-23).

Before this fix `n8n_cutover_wave.parse_lane_argv` reported `unmapped_wrapper:env`,
`unmapped_wrapper:env:TRADEAI_EFFECT_CLAIM`, `unmapped_wrapper:scripts/effect_claim_cron.sh` and
`unmapped_wrapper:<lane>` for every cron line carrying the wrapper that AGENTS §23.25 REQUIRES on a sender, so `plan`
printed SKIP for every canary lane that carried it and held six shadow lanes (PR #1972 finding 3).

Hermetic: a scratch code root (the 2026-10-15 factory test fixture) and an in-memory crontab; nothing reads the host
crontab, a secret, the ledger or the network.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import n8n_cutover_wave as W  # noqa: E402
from test_n8n_cutover_wave_20261015 import code_root  # noqa: E402,F401  (pytest fixture)

CMD = ["$PY", "scripts/demo_lane.py"]
WRAP = "env TRADEAI_EFFECT_CLAIM=demo-lane bash scripts/effect_claim_cron.sh demo-lane"


def _p(body: str, lane: str | None = "demo-lane", cmd=CMD):
    return W.parse_lane_argv(W.command_of("0 10 * * 1-5 " + body), list(cmd), lane)


# ── parse_lane_argv ────────────────────────────────────────────────────────────────────────────

def test_unwrapped_line_unchanged():
    p = _p("cd $PROJ && flock -n /tmp/demo.lock $PY scripts/demo_lane.py --apply >> logs/d.log 2>&1")
    assert p["problems"] == [] and p["live_arg"] == ["--apply"] and p["effect_claim"] is None


def test_wrapped_line_with_flock_is_clean():
    p = _p(f"cd $PROJ && flock -n /tmp/demo.lock {WRAP} $PY scripts/demo_lane.py --apply >> logs/d.log 2>&1")
    assert p["problems"] == [], p["problems"]
    assert p["live_arg"] == ["--apply"] and p["effect_claim"] == "demo-lane"


def test_wrapped_line_with_timeout_after_wrapper():
    # live shape: aegis-social-sentiment / signal-fusion-full (`... effect_claim_cron.sh <lane> timeout 10m $PY ...`)
    p = _p(f"cd $PROJ && flock -n /tmp/demo.lock {WRAP} timeout 10m $PY scripts/demo_lane.py >> l 2>&1")
    assert p["problems"] == [] and p["live_arg"] == [] and p["effect_claim"] == "demo-lane"
    p = _p(f"cd $PROJ && flock -n /tmp/demo.lock {WRAP} timeout -k 30 600 $PY scripts/demo_lane.py --x >> l 2>&1")
    assert p["problems"] == [] and p["live_arg"] == ["--x"]


def test_wrapped_line_absolute_paths():
    p = _p("cd /opt/tradeai/CURRENT && /usr/bin/flock -n /tmp/demo.lock "
           "env TRADEAI_EFFECT_CLAIM=demo-lane /bin/bash $PROJ/scripts/effect_claim_cron.sh demo-lane "
           "$PY scripts/demo_lane.py --apply >> l 2>&1")
    assert p["problems"] == [] and p["effect_claim"] == "demo-lane"


def test_bare_assignment_without_env_word():
    p = _p("cd $PROJ && flock -n /tmp/demo.lock TRADEAI_EFFECT_CLAIM=demo-lane bash scripts/effect_claim_cron.sh "
           "demo-lane $PY scripts/demo_lane.py >> l 2>&1")
    assert p["problems"] == [] and p["effect_claim"] == "demo-lane"


def test_other_env_prefix_stays_unmapped_next_to_wrapper():
    # live shape: resolve-due-checkpoints (TRADEAI_PENDING_DATA_APPLY) — the executor does not reproduce it.
    p = _p("cd $PROJ && flock -n /tmp/demo.lock env TRADEAI_PENDING_DATA_APPLY=1 TRADEAI_EFFECT_CLAIM=demo-lane "
           "bash scripts/effect_claim_cron.sh demo-lane $PY scripts/demo_lane.py >> l 2>&1")
    assert p["problems"] == ["unmapped_wrapper:env:TRADEAI_PENDING_DATA_APPLY"]
    assert p["effect_claim"] == "demo-lane"


def test_env_prefix_without_wrapper_unchanged():
    # No wrapper: the old verdicts stand byte for byte (`env` itself and every assignment are unmapped).
    p = _p("cd $PROJ && flock -n /tmp/demo.lock env PYTHONPATH=. $PY scripts/demo_lane.py >> l 2>&1")
    assert p["problems"] == ["unmapped_wrapper:env", "unmapped_wrapper:env:PYTHONPATH"]
    p = _p("cd $PROJ && flock -n /tmp/demo.lock env TRADEAI_EFFECT_CLAIM=demo-lane $PY scripts/demo_lane.py")
    assert "unmapped_wrapper:env:TRADEAI_EFFECT_CLAIM" in p["problems"] and p["effect_claim"] is None


@pytest.mark.parametrize("body,needle", [
    # wrapper present but switched OFF (no env) -> it execs the command unclaimed
    ("flock -n /tmp/demo.lock bash scripts/effect_claim_cron.sh demo-lane $PY scripts/demo_lane.py",
     "effect_claim_wrapper_off"),
    # env names a different lane than the wrapper argument -> OFF
    ("flock -n /tmp/demo.lock env TRADEAI_EFFECT_CLAIM=other bash scripts/effect_claim_cron.sh demo-lane "
     "$PY scripts/demo_lane.py", "effect_claim_wrapper_off"),
    # wrapper switched on, but for another lane than the registry row
    ("flock -n /tmp/demo.lock env TRADEAI_EFFECT_CLAIM=other bash scripts/effect_claim_cron.sh other "
     "$PY scripts/demo_lane.py", "effect_claim_wrapper_lane_mismatch:other"),
    # wrapper without its LANE_ID argument
    ("flock -n /tmp/demo.lock env TRADEAI_EFFECT_CLAIM=demo-lane bash scripts/effect_claim_cron.sh "
     "$PY scripts/demo_lane.py", "effect_claim_wrapper_no_lane_arg"),
])
def test_wrapper_misuse_is_a_problem_never_a_pass(body, needle):
    p = _p("cd $PROJ && " + body + " >> l 2>&1")
    assert any(x.startswith(needle) for x in p["problems"]), p["problems"]
    assert p["effect_claim"] is None


def test_lane_id_optional_for_old_callers():
    p = W.parse_lane_argv(f"cd $PROJ && flock -n /tmp/demo.lock {WRAP} $PY scripts/demo_lane.py", CMD)
    assert p["problems"] == [] and p["effect_claim"] == "demo-lane"


def test_live_crontab_shapes_parse_clean():
    """Verbatim shapes from `crontab -l` 2026-10-23 (read-only), one per wrapper variant on the host."""
    lines = {
        "finviz-screener-runner": (
            "0 10 * * 1-5 cd $PROJ && flock -n /tmp/finviz_screener.lock env TRADEAI_EFFECT_CLAIM="
            "finviz-screener-runner bash scripts/effect_claim_cron.sh finviz-screener-runner $PY "
            "scripts/finviz_screener_runner.py --run >> logs/finviz_screener.log 2>&1",
            ["$PY", "scripts/finviz_screener_runner.py"], ["--run"]),
        "aegis-social-sentiment": (
            "0 11,15 * * 1-5 cd $PROJ && flock -n /tmp/aegis_social_sentiment.lock env TRADEAI_EFFECT_CLAIM="
            "aegis-social-sentiment bash scripts/effect_claim_cron.sh aegis-social-sentiment timeout 10m $PY "
            "scripts/aegis_social_sentiment.py >> logs/aegis_social.log 2>&1",
            ["$PY", "scripts/aegis_social_sentiment.py"], []),
        "data-gap-resolver-pre": (
            "0 18 * * 1-5 cd /opt/tradeai/CURRENT && flock -n "
            "/tmp/data_gap_resolver.lock env TRADEAI_EFFECT_CLAIM=data-gap-resolver-pre bash "
            "scripts/effect_claim_cron.sh data-gap-resolver-pre $PY scripts/data_gap_resolver.py --pre-overnight "
            ">> logs/data_gap_resolver_pre_overnight.log 2>&1",
            ["$PY", "scripts/data_gap_resolver.py"], ["--pre-overnight"]),
    }
    for lane, (line, cmd, live) in lines.items():
        p = W.parse_lane_argv(W.command_of(line), cmd, lane)
        assert p["problems"] == [] and p["live_arg"] == live and p["effect_claim"] == lane, (lane, p)


# ── plan: a wrapped sender lane is plannable ───────────────────────────────────────────────────

def _crontab(sender_line: str) -> str:
    return "\n".join(["SHELL=/bin/bash", "PROJ=/x",
                      "0 10 * * 1-5 cd $PROJ && flock -n /tmp/demo.lock $PY scripts/demo_lane.py --apply >> l 2>&1",
                      "5 * * * * cd $PROJ && $PY scripts/nolock_lane.py --apply >> logs/n.log 2>&1",
                      sender_line, ""])


def test_plan_wrapped_sender_not_held_by_wrapper_unwrapped_is_held(code_root):  # noqa: F811
    unwrapped = "*/5 * * * * cd $PROJ && flock -n /tmp/s.lock $PY scripts/sender_lane.py --send >> l 2>&1"
    wrapped = ("*/5 * * * * cd $PROJ && flock -n /tmp/s.lock env TRADEAI_EFFECT_CLAIM=sender-lane bash "
               "scripts/effect_claim_cron.sh sender-lane $PY scripts/sender_lane.py --send >> l 2>&1")
    v = W.build_plan(code_root, _crontab(unwrapped), ["sender-lane"], "CWT")["lanes"][0]
    assert v["status"] == "SKIP" and any(r.startswith("sender_cron_not_effect_claimed") for r in v["reasons"])
    v = W.build_plan(code_root, _crontab(wrapped), ["sender-lane"], "CWT")["lanes"][0]
    # The wrapper no longer holds the lane: no sender/wrapper reason, argv and lock derived. What remains is the
    # platform's own dispatch gate on the fixture's lane id ("send" is a forbidden live token) - never widened here.
    assert not any(r.startswith(("sender_cron_not_effect_claimed", "unmapped_wrapper", "effect_claim_wrapper"))
                   for r in v["reasons"]), v["reasons"]
    assert v["live_arg"] == ["--send"] and v["lock"] == "/tmp/s.lock"
    assert all("forbidden_token:send@lane_id" in r for r in v["reasons"]), v["reasons"]


def test_plan_wrapper_for_wrong_lane_is_held(code_root):  # noqa: F811
    wrong = ("*/5 * * * * cd $PROJ && flock -n /tmp/s.lock env TRADEAI_EFFECT_CLAIM=demo-lane bash "
             "scripts/effect_claim_cron.sh demo-lane $PY scripts/sender_lane.py --send >> l 2>&1")
    v = W.build_plan(code_root, _crontab(wrong), ["sender-lane"], "CWT")["lanes"][0]
    assert v["status"] == "SKIP"
    assert any(r.startswith("effect_claim_wrapper_lane_mismatch:demo-lane") for r in v["reasons"]), v["reasons"]
