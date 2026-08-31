"""WAVE G1 — checkout-relative remediation at the resolution layer.

Five instances (AGENTS.md §9.4 / overnight brief):
  1. release-local logs/
  2. two holdings copies
  3. risk state
  4. evening packet
  5. cron → dev tree

Invariants:
  * Fix path resolution in lib helpers, never the cron's cwd.
  * Dual-write from one in-memory object when collapsing is not additive.
  * Never auto-remediate divergence between two authoritative copies —
    report both (auto_remediate=False).
  * DATA_DIRS_TO_LINK / OVERLAY_RELS includes logs.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.persistent_overlay import (  # noqa: E402
    DATA_DIRS_TO_LINK,
    OVERLAY_RELS,
    SENTINELS,
    apply_overlay_symlinks,
    overlay_is_safe,
)
from scripts.lib.persistent_state_root import (  # noqa: E402
    durable_write_targets,
    evening_packet_path,
    evening_packet_write_targets,
    logs_root,
    portfolio_state_write_targets,
    report_authoritative_divergence,
    resolve_durable_dir,
)


# ── 1. logs / DATA_DIRS_TO_LINK ──────────────────────────────────────────────

def test_g1_overlay_rels_include_logs_and_match_data_dirs_alias():
    assert "logs" in OVERLAY_RELS
    assert "data/portfolios/state" in OVERLAY_RELS
    assert "data/runtime" in OVERLAY_RELS
    assert "state/data_broker" in OVERLAY_RELS
    assert DATA_DIRS_TO_LINK is OVERLAY_RELS or tuple(DATA_DIRS_TO_LINK) == tuple(OVERLAY_RELS)
    assert "logs" in SENTINELS


def test_g1_logs_overlay_symlink_is_safe_and_additive(tmp_path: Path):
    """Release-local logs/ must symlink to the persistent source, not start empty."""
    src = tmp_path / "persistent"
    dst = tmp_path / "release"
    (src / "logs").mkdir(parents=True)
    (src / "logs" / "pipeline_liveness.log").write_text("a\nb\n")
    (src / "logs" / "claude_escalation_queue.json").write_text("[]")
    # Other overlay dirs present so apply doesn't skip the whole set awkwardly
    for rel in ("data/cio", "data/runtime", "data/health", "data/portfolios/state", "state/data_broker"):
        (src / rel).mkdir(parents=True, exist_ok=True)
    (src / "data/portfolios/state" / "holdings.json").write_text("{}")
    (src / "data/cio" / "cio_investment_brief.json").write_text("{}")
    (src / "data/cio" / "outcome_checkpoints.jsonl").write_text("")
    (src / "data/cio" / "aif_memory.json").write_text("{}")
    (src / "data/runtime" / "advisory_desk_latest.json").write_text("{}")

    (dst / "logs").mkdir(parents=True)
    (dst / "logs" / "orphan.txt").write_text("release-local fork — must not leak into source")

    guard = overlay_is_safe(canonical_source=src, dest=dst, rels=("logs",))
    assert guard["ok"] is True

    # apply_overlay_symlinks refuses to rm -rf a real directory; mimic deploy:
    # rm -rf target then ln -sfn (the real deploy semantics under test).
    import shutil

    shutil.rmtree(dst / "logs")
    applied = apply_overlay_symlinks(canonical_source=src, dest=dst, rels=("logs",))
    assert applied["applied"] is True
    assert (dst / "logs").is_symlink()
    assert (dst / "logs" / "pipeline_liveness.log").read_text() == "a\nb\n"
    # Release-local orphan must NOT appear in the persistent source.
    assert not (src / "logs" / "orphan.txt").exists()


def test_g1_logs_root_prefers_persistent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    persistent = tmp_path / "persistent-state"
    (persistent / "logs").mkdir(parents=True)
    (persistent / "PERSISTENT_STATE_ROOT.json").write_text("{}")
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(persistent))
    checkout = tmp_path / "checkout"
    (checkout / "logs").mkdir(parents=True)

    assert logs_root(checkout) == persistent / "logs"
    assert resolve_durable_dir("logs", checkout) == persistent / "logs"


# ── 2. holdings copies — report, never merge ─────────────────────────────────

def test_g1_holdings_write_targets_served_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    persistent = tmp_path / "persistent-state"
    (persistent / "data" / "portfolios" / "state").mkdir(parents=True)
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(persistent))
    checkout = tmp_path / "checkout"
    (checkout / "data" / "portfolios" / "state").mkdir(parents=True)

    targets = portfolio_state_write_targets(checkout)
    assert targets[0] == persistent / "data" / "portfolios" / "state"
    assert targets[1] == checkout / "data" / "portfolios" / "state"


def test_g1_divergence_report_never_auto_remediates(tmp_path: Path):
    a = tmp_path / "a" / "holdings.json"
    b = tmp_path / "b" / "holdings.json"
    a.parent.mkdir(parents=True)
    b.parent.mkdir(parents=True)
    a.write_text('{"copy":"hub","n":1}')
    b.write_text('{"copy":"persistent","n":2}')

    before_a, before_b = a.read_bytes(), b.read_bytes()
    report = report_authoritative_divergence(a, b, label="holdings")

    assert report["diverged"] is True
    assert report["identical"] is False
    assert report["auto_remediate"] is False
    assert report["action"] == "REPORT_BOTH_ESCALATE"
    assert len(report["copies"]) == 2
    # Must not mutate either file.
    assert a.read_bytes() == before_a
    assert b.read_bytes() == before_b


def test_g1_identical_copies_are_not_escalated(tmp_path: Path):
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    payload = '{"ok":true}'
    a.write_text(payload)
    b.write_text(payload)
    report = report_authoritative_divergence(a, b, label="holdings")
    assert report["identical"] is True
    assert report["diverged"] is False
    assert report["auto_remediate"] is False
    assert report["action"] == "NONE"


def test_g1_holdings_gate_source_mirrors_via_write_targets():
    """protected_holdings_write must call portfolio_state_write_targets (G1 wiring)."""
    src = (ROOT / "scripts" / "schwab_position_sync.py").read_text(encoding="utf-8")
    assert "portfolio_state_write_targets" in src
    assert "secondary write failed" in src or "secondary mirror" in src


# ── 3. risk state ────────────────────────────────────────────────────────────

def test_g1_risk_canonical_resolves_via_persistent_helper():
    src = (ROOT / "scripts" / "portfolio_stops.py").read_text(encoding="utf-8")
    assert "good_persistent_root" in src
    assert "report_authoritative_divergence" in src or "G1" in src


def test_g1_risk_dual_write_still_byte_identical(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from scripts.portfolio_stops import save_risk_state

    caller = tmp_path / "checkout" / "data" / "portfolios" / "state"
    canon = tmp_path / "persistent" / "data" / "portfolios" / "state"
    caller.mkdir(parents=True)
    monkeypatch.setattr("scripts.portfolio_stops._canonical_state_dir", lambda: canon)

    save_risk_state({"stop_count": 26, "total_unprotected_mv": 650158.77}, caller)
    assert (caller / "risk_management.json").read_bytes() == (
        canon / "risk_management.json"
    ).read_bytes()


# ── 4. evening packet ────────────────────────────────────────────────────────

def test_g1_evening_packet_targets_prefer_persistent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    persistent = tmp_path / "persistent-state"
    (persistent / "data" / "runtime").mkdir(parents=True)
    (persistent / "PERSISTENT_STATE_ROOT.json").write_text("{}")
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(persistent))
    checkout = tmp_path / "checkout"

    targets = evening_packet_write_targets(checkout)
    assert targets[0] == persistent / "data" / "runtime" / "aegis_evening_packet.json"
    assert targets[-1] == checkout / "data" / "runtime" / "aegis_evening_packet.json"
    assert evening_packet_path(checkout) == targets[0]


def test_g1_evening_packet_script_uses_resolution_helper():
    src = (ROOT / "scripts" / "aegis_evening_packet.py").read_text(encoding="utf-8")
    assert "evening_packet_write_targets" in src
    assert "evening_packet_targets" in src


def test_g1_evening_packet_dual_write_from_one_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import aegis_evening_packet as pkt

    persistent = tmp_path / "persistent-state"
    (persistent / "data" / "runtime").mkdir(parents=True)
    (persistent / "PERSISTENT_STATE_ROOT.json").write_text("{}")
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(persistent))

    checkout = tmp_path / "checkout"
    monkeypatch.setattr(pkt, "ROOT", checkout)
    monkeypatch.setattr(
        pkt, "PACKET_PATH", checkout / "data" / "runtime" / "aegis_evening_packet.json"
    )

    # Avoid live product reads — stub build_packet.
    monkeypatch.setattr(
        pkt,
        "build_packet",
        lambda: {
            "schema": "aegis_evening_packet@v1",
            "packet_chars": 12,
            "canonical_cio_source": "cio.product.current",
        },
    )
    monkeypatch.setattr(sys, "argv", ["aegis_evening_packet.py"])
    rc = pkt.main()
    assert rc == 0

    served = persistent / "data" / "runtime" / "aegis_evening_packet.json"
    hub = checkout / "data" / "runtime" / "aegis_evening_packet.json"
    assert served.is_file() and hub.is_file()
    assert served.read_bytes() == hub.read_bytes()


# ── 5. cron → dev tree (cwd-independent resolution) ──────────────────────────

def test_g1_resolve_durable_dir_ignores_process_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    persistent = tmp_path / "persistent-state"
    (persistent / "data" / "runtime").mkdir(parents=True)
    (persistent / "PERSISTENT_STATE_ROOT.json").write_text("{}")
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(persistent))

    alien = tmp_path / "alien_cwd"
    alien.mkdir()
    monkeypatch.chdir(alien)

    resolved = resolve_durable_dir("data/runtime", tmp_path / "checkout")
    assert resolved == persistent / "data" / "runtime"
    assert Path.cwd() == alien  # cwd unchanged and unused


def test_g1_durable_write_targets_generic_rel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    persistent = tmp_path / "persistent-state"
    (persistent / "data" / "cio").mkdir(parents=True)
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(persistent))
    checkout = tmp_path / "hub"

    targets = durable_write_targets("data/cio", checkout)
    assert targets[0] == persistent / "data" / "cio"
    assert targets[1] == checkout / "data" / "cio"


# ── deploy script parity (prefer lib; deploy already links logs) ─────────────

def test_g1_deploy_script_already_links_logs():
    """Prefer lib resolution; deploy.sh only needed if logs were absent — they are not."""
    src = (ROOT / "scripts" / "cio_phase2_exact_main_deploy.sh").read_text(encoding="utf-8")
    assert '"logs"' in src
    # Lib is the source of truth for the named list.
    assert "logs" in OVERLAY_RELS
