"""ANCHOR: CATALYST_ROUTER_ENV_20261107 — LQ-20261107-49, catalyst_momentum_engine starved of search.

Defect (proved read-only 2026-11-07): the engine ran every slot from cron, found 2-8 candidates, and staged nothing
since 2026-10-29 08:00 ET. Without ``SEARCH_ROUTING_ENGINE`` the engine's ``search_catalyst`` takes the legacy SearXNG
call (categories=news, time_range=day, google news/bing news/duckduckgo); those engines answer CAPTCHA / parsing
error, so every search is empty and ``hermes_research_intelligence`` gets no momentum_catalyst row, which leaves
``hermes_news_bridge`` with nothing to bridge into ``news_articles``. The n8n executor env has the flag; cron has not.

These tests fail on the old behaviour:
  * the B8 family's proposal modes (the engine's scheduled cron home once the approved packet is installed) carry the
    router flag, and under exactly that env the engine's search takes the routing engine, not the legacy call;
  * the operator packet refuses a served release whose family modes lack the flag.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import catalyst_momentum_engine as cme  # noqa: E402
from scripts.lib import family_slot_jobs as FSJ  # noqa: E402

PACKET = ROOT / "docs" / "ops" / "packets" / "catalyst-consolidation-20261022" / "apply-operator.sh"
FAM = FSJ.family("catalyst-momentum-engine")


def _env_prefix(cmd: str) -> dict[str, str]:
    """The NAME=value assignments an `env ...` prefix sets before the command word."""
    words = shlex.split(cmd)
    if not words or words[0] != "env":
        return {}
    out = {}
    for w in words[1:]:
        if "=" not in w:
            break
        k, v = w.split("=", 1)
        out[k] = v
    return out


@pytest.mark.parametrize("mode", ["premarket_scalp", "market_swing"])
def test_proposal_modes_keep_the_paper_guard_and_turn_the_router_on(mode):
    env = _env_prefix(FSJ.render(FAM.mode(mode), "/srv"))
    assert env.get("ALPACA_MODE") == "paper"
    assert env.get("SEARCH_ROUTING_ENGINE") == "1"


def _search_path(monkeypatch, env: dict[str, str]) -> dict:
    for k in ("SEARCH_ROUTING_ENGINE", "SCALP_HOT_TIER"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    seen: dict = {}

    def fake_search(sym, suffix, **kw):
        seen.update(sym=sym, suffix=suffix, kw=kw)
        return []

    cme._catalyst_search(fake_search, "ABC", cme.BANDS["market_swing"], {"symbol": "ABC", "rvol": 4.0}, dry_run=True)
    return seen


@pytest.mark.parametrize("mode", ["premarket_scalp", "market_swing"])
def test_the_family_env_routes_the_engine_search(monkeypatch, mode):
    seen = _search_path(monkeypatch, _env_prefix(FSJ.render(FAM.mode(mode), "/srv")))
    assert seen["kw"].get("caller") == "catalyst_momentum_engine", seen


def test_the_old_cron_env_took_the_legacy_call(monkeypatch):
    # The legacy crontab line's env (paper guard only): the two-argument SearXNG call — the starved path.
    seen = _search_path(monkeypatch, {"ALPACA_MODE": "paper"})
    assert seen["kw"] == {}, seen


def test_packet_refuses_a_served_release_without_the_router_flag(tmp_path):
    cur = tmp_path / "current"
    (cur / "scripts").mkdir(parents=True)
    old_cmd = FSJ.render(FAM.mode("market_swing"), str(cur)).replace(FSJ.CATALYST_ROUTER_ENV, "")
    assert "SEARCH_ROUTING_ENGINE" not in old_cmd and "env ALPACA_MODE=paper" in old_cmd
    (cur / "scripts" / "run_family_slot.py").write_text(
        "import sys\n"
        f"lines = {FSJ.crontab_lines(FAM)!r}\n"
        "if '--print-crontab' in sys.argv:\n"
        "    print('\\n'.join(lines))\n"
        "else:\n"
        f"    print({old_cmd!r}.__repr__())\n")
    crontab_store = tmp_path / "crontab.txt"
    crontab_store.write_text("# empty\n")
    shim = tmp_path / "bin"
    shim.mkdir()
    (shim / "crontab").write_text(
        "#!/usr/bin/env bash\n"
        f'S="{crontab_store}"\n'
        'if [[ "$1" == "-l" ]]; then cat "$S"; elif [[ "$1" == "-" ]]; then cat > "$S"; else cp "$1" "$S"; fi\n')
    (shim / "crontab").chmod(0o755)
    env = dict(os.environ, PATH=f"{shim}:{os.environ['PATH']}", HOME=str(tmp_path), TRADEAI_CURRENT=str(cur),
               TRADEAI_PY=sys.executable, TRADEAI_PACKET_WORK=str(tmp_path / "work"))
    r = subprocess.run(["bash", str(PACKET), "--preview"], env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 3, r.stdout + r.stderr
    assert "lacks SEARCH_ROUTING_ENGINE=1" in r.stdout
    assert crontab_store.read_text() == "# empty\n"
