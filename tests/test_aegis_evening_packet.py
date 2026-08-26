"""Evening Surveillance packet stays bounded and uses the canonical CIO product."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import aegis_evening_packet as pkt  # noqa: E402


def test_packet_bounded_and_canonical(tmp_path, monkeypatch):
    # Intentionally huge "alert history" must not land in the packet.
    huge = tmp_path / "alerts.json"
    huge.write_text(json.dumps([{"n": i, "txt": "x" * 200} for i in range(5000)]))
    monkeypatch.chdir(tmp_path)
    packet = pkt.build_packet()
    raw = json.dumps(packet)
    assert packet["canonical_cio_source"] == "cio.product.current"
    cio = packet.get("cio") or {}
    if cio.get("available") is False:
        assert cio.get("reason") == "PRODUCER_NOT_RUN"
        assert "CIO_PRODUCT_UNAVAILABLE" in str(cio.get("note") or "")
    assert "cio_decisions" in packet["retired_artifacts_forbidden"]
    assert "telegram history" not in raw.lower()
    assert len(raw) < 80_000
    prompt = pkt.isolated_prompt()
    assert "FRESH SESSION" in prompt
    assert "cio_decisions" in prompt
