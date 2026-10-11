"""Wave C heavy-jobs helpers (TRADE_AI_CI=1 hermetic)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

os.environ.setdefault("TRADE_AI_CI", "1")

from scripts.lib import n8n_cc_wave_c as W  # noqa: E402


def test_wave_c_mode_aliases(monkeypatch):
    assert W.wave_c_mode({W.WAVE_C_MODE_ENV: "off"}) == "off"
    assert W.wave_c_mode({W.WAVE_C_MODE_ENV: "0"}) == "off"
    assert W.wave_c_mode({W.WAVE_C_MODE_ENV: "dry_run"}) == "dry_run"
    assert W.wave_c_mode({W.WAVE_C_MODE_ENV: "1"}) == "apply"
    assert W.wave_c_mode({}) == "off"


def test_mint_run_id_shape():
    from scripts.lib.n8n_coordination_gateway import RUN_ID_RE

    rid = W.mint_run_id("advisory-desk-run-now")
    assert RUN_ID_RE.fullmatch(rid)
    assert not rid.lower().startswith(("d:", "e:", "g:"))


def test_request_payload_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    path = W.write_request_payload(W.LANE_ANALYST, {"symbol": "RKLB", "mode": "single"}, root=tmp_path)
    assert path.is_file()
    got = W.read_request_payload(W.LANE_ANALYST, root=tmp_path)
    assert got["symbol"] == "RKLB"


def test_enqueue_for_wave_c_mode_off_skips(monkeypatch):
    monkeypatch.setenv(W.WAVE_C_MODE_ENV, "off")
    out = W.enqueue_for_wave_c_mode(lane_id=W.LANE_ADVISORY)
    assert out["skipped"] is True
    assert out["accepted"] is False


def test_enqueue_host_run_dry_run(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    ledger = tmp_path / "ledger.sqlite"
    monkeypatch.setenv("TRADEAI_N8N_COORDINATION_LEDGER", str(ledger))

    class FakeStore:
        def __init__(self):
            self.rows = {}

        def get(self, run_id):
            return self.rows.get(run_id)

        def request(self, **kw):
            row = {
                "run_id": kw["run_id"],
                "lane_id": kw["lane_id"],
                "mode": kw["mode"],
                "state": "REQUESTED",
                "requested_by": kw["requested_by"],
            }
            self.rows[kw["run_id"]] = row
            return row, False

    allow = {
        W.LANE_ADVISORY: {
            "lane_id": W.LANE_ADVISORY,
            "dry_run_arg": ["--dry-run"],
            "live_arg": [],
            "command": ["$PY", "scripts/advisory_desk_run_now.py"],
        }
    }
    store = FakeStore()
    monkeypatch.setattr(W, "_rw_store", lambda _p: store)
    # host_run_request uses real gateway validation against FakeStore.request
    out = W.enqueue_host_run(
        lane_id=W.LANE_ADVISORY,
        mode="dry_run",
        run_id="wc:advisory-desk-run-now:20261011T000000:abcdef12",
        allowlist=allow,
        ledger=ledger,
        store=store,
        now=1_700_000_000.0,
    )
    assert out["accepted"] is True
    assert out["state"] == "REQUESTED"
    assert out["run_id"].startswith("wc:")


def test_legacy_run_refuse_all_mapped_paths():
    allow = {}  # none of the mapped lanes are runnable
    for path in W.LEGACY_RUN_DISPOSITION:
        status, body = W.legacy_run_refuse(path, allowlist=allow)
        assert status in (409, 410)
        assert body["ok"] is False
        assert body["disposition"] == "refuse_until_allowlisted"
        assert "Thread/subprocess" in body["message"]


def test_allowlist_and_registry_have_wave_c_lanes():
    al = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text(encoding="utf-8"))
    lanes = {e["lane_id"]: e for e in al["lanes"]}
    for lid in (W.LANE_ADVISORY, W.LANE_ANALYST, W.LANE_BRIEF):
        assert lid in lanes
        assert lanes[lid]["dry_run_arg"] == ["--dry-run"]
        assert lanes[lid]["live_arg"] == []
        assert (ROOT / lanes[lid]["command"][1]).is_file()
    reg = json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))
    rows = {r["lane_id"]: r for r in reg["lanes"]}
    for lid in (W.LANE_ADVISORY, W.LANE_ANALYST, W.LANE_BRIEF):
        assert rows[lid]["scheduler"]["stage"] == "shadow"
        assert rows[lid]["scheduler"]["wave"] == "WAVE_C"


def test_health_contracts_reviewed():
    from scripts.lib import n8n_health_contracts as H

    doc = json.loads((ROOT / "config" / "n8n_health_contracts.json").read_text(encoding="utf-8"))
    by = {c["id"]: c for c in doc["contracts"]}
    for lid in (W.LANE_ADVISORY, W.LANE_ANALYST, W.LANE_BRIEF):
        c = by[lid]
        assert c["status"] == "REVIEWED"
        assert not H.unknown_fields(c)
        assert not H.validate_contract(c)


def test_cli_scripts_declare_dry_run():
    for rel in (
        "scripts/advisory_desk_run_now.py",
        "scripts/analyst_prospectus_generate.py",
        "scripts/aegis_brief_regenerate.py",
    ):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert '"--dry-run"' in src


def test_portfolio_server_no_longer_spawns_run_threads():
    src = (ROOT / "scripts" / "portfolio_server.py").read_text(encoding="utf-8")
    assert "legacy_run_refuse" in src
    # The six Run button paths must not start Threads for bash launchers anymore.
    assert 'path == "/api/run-portfolio"' not in src
    assert "run_portfolio.sh triggered" not in src


def test_advisory_start_run_now_wave_c_dry_run(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_ADVISORY_RUN_STATUS", str(tmp_path / "advisory_run_now.json"))
    monkeypatch.setenv("TRADEAI_ADVISORY_RUN_LOCK", str(tmp_path / "advisory_run_now.lock"))
    monkeypatch.setenv(W.WAVE_C_MODE_ENV, "dry_run")
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))

    import importlib
    import lib.advisory_desk_schedule as m

    m = importlib.reload(m)
    monkeypatch.setattr(m, "_systemd_next_iso", lambda: None)

    def fake_enqueue(**kw):
        return {
            "ok": True,
            "accepted": True,
            "state": "REQUESTED",
            "run_id": "wc:advisory-desk-run-now:20261011T120000:deadbeef01",
            "lane_id": W.LANE_ADVISORY,
            "mode": "dry_run",
            "wave_c_mode": "dry_run",
            "ledger": str(tmp_path / "ledger.sqlite"),
        }

    monkeypatch.setattr("lib.n8n_cc_wave_c.enqueue_for_wave_c_mode", fake_enqueue)
    out = m.start_run_now(live_llm=True)
    assert out["accepted"] is True
    assert out["run_id"].startswith("wc:")
    assert out["wave_c_mode"] == "dry_run"
    assert out["enqueue_mode"] == "dry_run"


def test_wave_b_spotlights_still_projected(tmp_path, monkeypatch):
    """Wave B polish: research-intake + watch-refresh spotlights remain on the projection."""
    from scripts.lib import n8n_coordination_projection as P

    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    spot = tmp_path / "data" / "runtime" / "n8n_cc_wave_b" / "spotlights.json"
    spot.parent.mkdir(parents=True, exist_ok=True)
    spot.write_text(
        json.dumps(
            {
                "schema": "N8nCcWaveBSpotlights@v1",
                "lanes": {
                    "research-intake": {
                        "as_of": "2026-10-11T20:00:00+00:00",
                        "mode": "dry_run",
                        "gateway_state": "DRY_RUN",
                        "request_type": "topic",
                        "subject": "TEST",
                        "idempotency_key": "ri-test",
                    },
                    "watch-refresh": {
                        "as_of": "2026-10-11T20:01:00+00:00",
                        "mode": "dry_run",
                        "gateway_state": "DRY_RUN",
                        "phase": "start",
                        "run_id": 1,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    items = P.lane_spotlights(env={"TRADEAI_STATE_ROOT": str(tmp_path)})
    ids = {x["lane_id"] for x in items}
    assert "research-intake" in ids
    assert "watch-refresh" in ids
    proj = P.project(path=tmp_path / "missing.sqlite")
    assert "spotlights" in proj
    assert any(s["lane_id"] == "research-intake" for s in proj["spotlights"])
