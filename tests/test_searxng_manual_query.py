"""Focused safety tests for the Phase 17 SearXNG manual wrapper."""

from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import searxng_manual_query as wrapper  # noqa: E402


def test_sanitize_results_removes_secrets_and_ips():
    secret = "sk-" + "a" * 24
    raw = {
        "results": [{
            "title": f"Result {secret}",
            "url": f"https://example.test/article?token={secret}&host=10.20.30.40",
            "content": f"Useful text from 192.168.1.10 {secret}",
            "engine": "ddg",
            "category": "general",
        }]
    }

    result = wrapper.sanitize_results(raw, 15)[0]
    serialized = json.dumps(result)
    assert secret not in serialized
    assert "10.20.30.40" not in serialized
    assert "192.168.1.10" not in serialized
    assert "[REDACTED]" in serialized
    assert "[IP]" in serialized


def test_write_outputs_sanitizes_query_and_is_deterministic(tmp_path):
    secret = "sk-" + "b" * 24
    results = [{
        "title": "A result",
        "url": "https://example.test/a",
        "snippet": "A short snippet",
        "engine": "zeta",
        "category": "general",
    }, {
        "title": "B result",
        "url": "https://example.test/b",
        "snippet": "Another snippet",
        "engine": "alpha",
        "category": "general",
    }]

    wrapper.write_outputs(f"research {secret}", results, {"number_of_results": 2}, tmp_path)

    metadata = json.loads((tmp_path / "query_metadata.json").read_text(encoding="utf-8"))
    summary = (tmp_path / "query_summary.md").read_text(encoding="utf-8")
    assert metadata["query"] == "research [REDACTED]"
    assert metadata["engines_used"] == ["alpha", "zeta"]
    assert secret not in summary
    assert "DB writes: 0" not in summary  # safety statement is prose, not a mutable counter
    assert "No DB writes" in summary


def test_max_results_is_capped():
    assert wrapper.MAX_RESULTS == 25
    assert len(wrapper.sanitize_results({"results": [{}] * 30}, wrapper.MAX_RESULTS)) == 25
