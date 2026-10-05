"""Firing test (2026-10-05) for the send_telegram site in scripts/options_intent_matcher.py.

The matcher's digest goes through the real telegram_alert.send_telegram chokepoint (comms editor
included) only in send mode and only on a material change; this injects that condition and asserts
the message reaches the transport.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import options_intent_matcher as cli  # noqa: E402
from lib.options_intent import matcher as mt  # noqa: E402

COVERS = ["scripts/options_intent_matcher.py"]

CHAIN = {"status": "ok", "underlying_price": 20.0, "underlying_quote_time": "2026-10-05T17:00:00+00:00",
         "expirations": [{"exp": "2026-10-30", "strikes": [
             {"side": "put", "strike": 18.0, "dte": 25, "exp": "2026-10-30", "bid": 0.50, "ask": 0.52, "mark": 0.51,
              "iv": 50.0, "delta": -0.25, "oi": 900, "volume": 50, "two_sided": True, "spread_pct": 3.9,
              "symbol": "ZZTST 261030P18"}]}]}
INTENT = {"symbol": "ZZTST", "thesis_target": 30, "plays": {"cash_secured_put": {"dte": [20, 40], "delta": [0.1, 0.4]}},
          "directive_id": 1}


def test_options_intent_digest_reaches_the_transport(alarm_capture, tmp_path, monkeypatch):
    monkeypatch.setenv("OPTIONS_INTENT_DIR", str(tmp_path))
    res = cli.run([INTENT], cfg={**mt.DEFAULT_CONFIG, "mode": "send"}, apply=True,
                  chain_fn=lambda s, side: CHAIN, earnings_fn=lambda s: {}, holdings_list=[], out=lambda t: None)
    assert res["digests_sent"] == 1
    alarm_capture.assert_fired(contains="OPTIONS INTENT · ZZTST")
