"""First assert_fence wave (operator OK 2026-10-16): aegis-social-sentiment, hermes-social-sentiment,
finviz-screener-runner (effect-keyed, late_write_fenced), and finviz-market-movers (fence wired; it has no effect key,
because the lane is shadow with no live_arg).

Per lane, these tests pin that:
1. the fence is called before the lane's first target write (behaviour for the two persist paths; source order for
   the screener and market-movers write blocks);
2. a failure BEFORE the fence is a proven pre-effect FAILED, which a slot-bound retry re-claims (attempt 2);
3. a failure AFTER the fence passed is held (unproven), so the retry is refused (effect_already_claimed);
4. without the effect-claim env the fence is a no-op and the write happens, so cron behaviour is unchanged;
5. a refused fence writes nothing.

Hermetic: tmp sqlite ledger; DB writes are stubbed; no network, no .env, no broker, no send.
"""
from __future__ import annotations

import importlib
import inspect
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from scripts import n8n_run_executor as X  # noqa: E402
from scripts.lib import effect_claim as E  # noqa: E402
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerRunStore  # noqa: E402

import lib.effect_claim as LE  # noqa: E402  (the import path the lane scripts use)

T0 = 1_760_616_000.0
SLOT = "20261016T1100"
FENCED = ("aegis-social-sentiment", "hermes-social-sentiment", "finviz-screener-runner")
CFG = ROOT / "config" / "n8n_effect_keys.json"


@pytest.fixture
def led(tmp_path):
    ledger = CoordinationLedger(tmp_path / "ledger.sqlite")
    yield ledger, E.EffectClaimStore(ledger), LedgerRunStore(ledger), tmp_path / "ledger.sqlite"
    ledger.close()


# ---------------------------------------------------------------- config + catalogue


def test_wave_lanes_are_keyed_fenced_and_in_the_catalogue():
    fenced = E.load_fenced_lanes(CFG)
    keyed = E.load_effect_lanes(CFG)
    cat = {e["lane_id"]: e for e in json.loads((ROOT / "config" / "n8n_remediation_catalogue.json").read_text())["lanes"]}
    for lane in FENCED:
        assert lane in keyed and lane in fenced, lane
        assert any(a["action_id"] == "rerun_live_once" for a in cat[lane]["actions"]), lane
    assert "finviz-market-movers" not in keyed          # shadow, no live_arg: no key until it is staged (decision)


# ---------------------------------------------------------------- 4. no env = unchanged


def test_without_the_effect_claim_env_the_fence_is_a_noop(monkeypatch):
    monkeypatch.delenv(E.FENCE_ENV, raising=False)
    assert LE.fence_before_write() is None
    assert E.fence_before_write() is None


# ---------------------------------------------------------------- 1 + 5. aegis / hermes persist paths


def _lane_module(name, monkeypatch):
    mod = importlib.import_module(name)
    monkeypatch.setattr(mod, "_FENCE_PASSED", False)
    return mod


SENT = {"mention_count": 3, "bullish_count": 2, "bearish_count": 0, "neutral_count": 1, "sentiment_score": 0.5,
        "volume_zscore": None, "unusual_spike": False, "theme_tags": [], "top_posts_summary": "x", "confidence": 0.5}


@pytest.mark.parametrize("modname,call", [
    ("aegis_social_sentiment", lambda m: m.persist_sentiment("AAA", SENT, "social")),
    ("hermes_social_sentiment", lambda m: m.persist("AAA", SENT)),
])
def test_persist_calls_the_fence_before_the_write(modname, call, monkeypatch):
    mod = _lane_module(modname, monkeypatch)
    order: list[str] = []
    # patch the module object the lane's lazy import resolves NOW (other suites may reload lib.effect_claim)
    monkeypatch.setattr(importlib.import_module("lib.effect_claim"), "fence_before_write",
                        lambda **kw: order.append("fence"))
    monkeypatch.setattr(mod, "_db_write", lambda *a, **k: order.append("write") or True)
    assert call(mod) is True
    assert call(mod) is True
    assert order == ["fence", "write", "write"]           # once per run, before the first write


@pytest.mark.parametrize("modname,call", [
    ("aegis_social_sentiment", lambda m: m.persist_sentiment("AAA", SENT, "social")),
    ("hermes_social_sentiment", lambda m: m.persist("AAA", SENT)),
])
def test_cron_run_without_token_still_writes(modname, call, monkeypatch):
    mod = _lane_module(modname, monkeypatch)
    monkeypatch.delenv(E.FENCE_ENV, raising=False)
    writes = []
    monkeypatch.setattr(mod, "_db_write", lambda *a, **k: writes.append(1) or True)
    assert call(mod) is True and writes == [1]


@pytest.mark.parametrize("modname,call", [
    ("aegis_social_sentiment", lambda m: m.persist_sentiment("AAA", SENT, "social")),
    ("hermes_social_sentiment", lambda m: m.persist("AAA", SENT)),
])
def test_refused_fence_writes_nothing(modname, call, monkeypatch, led, tmp_path):
    mod = _lane_module(modname, monkeypatch)
    _, fx, _, path = led
    fx.set_owner(modname.replace("_", "-"), "n8n", expect_epoch=None, by="op", now=T0)
    key = E.effect_key(modname.replace("_", "-"), SLOT, "v1")
    # a token for a claim that does not exist (released / never claimed)
    monkeypatch.setenv(E.FENCE_ENV, E.fence_token(key, 1, 1))
    monkeypatch.setenv(E.FENCE_LEDGER_ENV, str(path))
    writes = []
    monkeypatch.setattr(mod, "_db_write", lambda *a, **k: writes.append(1) or True)
    with pytest.raises(Exception) as exc:
        call(mod)
    assert type(exc.value).__name__ == "EffectFenceError"
    assert writes == []


# ---------------------------------------------------------------- 1. screener + market movers: source order


def _src(fn) -> str:
    return inspect.getsource(fn)


def test_screener_fences_before_its_first_db_write():
    import finviz_screener_runner as S

    src = _src(S.run_screener)
    fence = src.index("_fence_before_first_write()")
    assert fence < src.index('cur.execute(f"SAVEPOINT {sp}")')
    assert fence < src.index("_update_screener_membership(cur")
    assert fence < src.index("INSERT INTO ticker_strategy_classifications")
    assert fence > src.index("_fetch_screener_tickers(url")          # the fetch (a failure there) is pre-fence


def test_market_movers_fences_before_its_first_insert_and_snapshot():
    import finviz_market_movers as M

    src = _src(M._execute)
    fence = src.index("_fence_before_first_write()")
    assert src.index("_fetch_signal(param") < fence < src.index("INSERT INTO market_movers")
    assert fence < src.index("tmp.write_text(")
    assert 'type(e).__name__ == "EffectFenceError"' in src             # a refusal is re-raised, not swallowed


# ---------------------------------------------------------------- 2 + 3. executor: before vs after the fence


def _gate(fx, lane):
    spec = E.load_effect_config(CFG)[lane]
    return X.EffectGate(fx, {lane: spec}, clock=lambda: T0 + 100, fenced=E.load_fenced_lanes(CFG))


def _begin(fx, runs, lane, run_id, *, parent=None):
    runs.request(run_id=run_id, lane_id=lane, mode="live", requested_by="t", caller_id="n8n-relay", now=T0 + 10,
                 **({"parent_run_id": parent} if parent else {}))
    row = runs.get(run_id)
    return _gate(fx, lane).begin(row, lane, "live")


@pytest.mark.parametrize("lane", FENCED)
def test_failure_before_the_fence_is_retryable(lane, led):
    _, fx, runs, _ = led
    process = E.load_effect_config(CFG)[lane]["process"]
    fx.set_owner(process, "n8n", expect_epoch=None, by="op", now=T0)
    parent = f"d:{lane}:live:{SLOT}"
    block, refusal = _begin(fx, runs, lane, parent)
    assert refusal is None and block["claimed"]
    # the lane exits 1 before reaching assert_fence (e.g. the fetch failed)
    _gate(fx, lane).end(block, {"state": "RUN_FAILED", "lane_id": lane, "run_id": parent, "reason": "exit_1"})
    assert block["pre_effect_proof"] == "exited_before_fence" and not block["held_for_reconciliation"]
    retry, refusal = _begin(fx, runs, lane, f"rem-siem1-{lane}-live"[:60], parent=parent)
    assert refusal is None and retry["attempt"] == 2 and retry["key"] == block["key"]


@pytest.mark.parametrize("lane", FENCED)
def test_failure_after_the_fence_is_refused(lane, led):
    _, fx, runs, _ = led
    process = E.load_effect_config(CFG)[lane]["process"]
    fx.set_owner(process, "n8n", expect_epoch=None, by="op", now=T0)
    parent = f"d:{lane}:live:{SLOT}"
    block, _ = _begin(fx, runs, lane, parent)
    fx.assert_fence(E.fence_token(block["key"], block["epoch"], block["attempt"]), now=T0 + 20)  # lane passed it
    _gate(fx, lane).end(block, {"state": "RUN_FAILED", "lane_id": lane, "run_id": parent, "reason": "exit_1"})
    assert block["held_for_reconciliation"] is True
    _, refusal = _begin(fx, runs, lane, f"rem-siem2-{lane}-live"[:60], parent=parent)
    assert refusal == "effect:effect_already_claimed"
