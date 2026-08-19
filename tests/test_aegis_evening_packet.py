"""Evening Surveillance packet stays bounded and uses the canonical CIO product."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import aegis_evening_packet as pkt  # noqa: E402


def test_packet_sys_path_includes_repo_root():
    """CLI `python scripts/aegis_evening_packet.py` must be able to import scripts.lib.*."""
    src = Path(pkt.__file__).read_text()
    assert "sys.path.insert(0, str(ROOT))" in src
    assert "cio_investment_brief.json" in src


def test_packet_bounded_and_canonical(tmp_path, monkeypatch):
    # Intentionally huge "alert history" must not land in the packet.
    huge = tmp_path / "alerts.json"
    huge.write_text(json.dumps([{"n": i, "txt": "x" * 200} for i in range(5000)]))
    monkeypatch.chdir(tmp_path)
    packet = pkt.build_packet()
    raw = json.dumps(packet)
    assert packet["canonical_cio_source"] == "cio_investment_product"
    assert "cio_decisions" in packet["retired_artifacts_forbidden"]
    assert "telegram history" not in raw.lower()
    assert len(raw) < 80_000
    prompt = pkt.isolated_prompt()
    assert "FRESH SESSION" in prompt
    assert "cio_decisions" in prompt
