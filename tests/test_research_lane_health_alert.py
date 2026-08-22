"""Alert-state unwrap + per-lane hints. Dedup must survive a 15-min timer."""
from __future__ import annotations

import json
import time

import research_lane_health as hl


def test_unwrap_heals_nested_lanes_wrapper():
    nested = {"as_of": "t0", "lanes": {"as_of": "t1", "lanes": {
        "deepseek": {"last_alert": 111, "ok": False},
        "overnight-deep": {"last_alert": 222, "ok": False},
    }}}
    m = hl.unwrap_lane_map(nested)
    assert m["deepseek"]["last_alert"] == 111
    assert m["overnight-deep"]["last_alert"] == 222
    assert "as_of" not in m


def test_unwrap_flat_map_passthrough():
    m = hl.unwrap_lane_map({
        "as_of": "t",
        "lanes": {"deepseek": {"last_alert": 9}},
        "schema": "x",
    })
    assert m == {"deepseek": {"last_alert": 9}}


def test_fix_hint_is_not_stale_import():
    h = hl.fix_hint({"lane": "deepseek", "firing": ["error_streak:50>=5"]})
    assert "lib.llm_lane" not in h or "already" in h.lower()
    assert "COST_CONFIGURATION_INVALID" in h
    o = hl.fix_hint({"lane": "overnight-deep", "firing": ["zero_non_error_24h"]})
    assert "ChatGPT" in o and "gemma" in o
    d = hl.fix_hint({"lane": "drive-sync", "firing": ["exit_code:1", "zero_uploaded_with_failures:1230"]})
    assert "404" in d


def test_alert_dedup_does_not_send_twice(tmp_path, monkeypatch):
    path = tmp_path / "health.json"
    monkeypatch.setattr(hl, "STATUS_PATH", path)
    monkeypatch.setattr(hl, "ALERT_DEDUP_SEC", 6 * 3600)
    sent = []
    monkeypatch.setattr(hl, "_deliver_telegram", lambda msg: sent.append(msg))

    report = {
        "as_of": "now",
        "ok": False,
        "lanes": [
            {"lane": "deepseek", "ok": False, "firing": ["error_streak:50>=5"],
             "error_streak": 50, "non_error_24h": 1, "attempts_24h": 275},
        ],
    }
    n1 = hl._alert(report)
    n2 = hl._alert(report)
    assert n1 == 1
    assert n2 == 0
    assert len(sent) == 1
    assert "COST_CONFIGURATION_INVALID" in sent[0]
    assert "lib.llm_lane" not in sent[0] or "already" in sent[0]
    raw = json.loads(path.read_text())
    assert raw["lanes"]["deepseek"]["last_alert"] > 0
    assert "as_of" not in raw.get("lanes", {})
    assert time.time() - int(raw["lanes"]["deepseek"]["last_alert"]) < 5
