from __future__ import annotations

from datetime import datetime, timezone

from scripts import refresh_advisory_maturity_evidence as evidence


NOW = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)


def test_ollama_inventory_classification():
    rows = evidence.parse_ollama_list(
        "NAME ID SIZE MODIFIED\n"
        "nomic-embed-text:latest abc 274 MB now\n"
        "gemma3:12b def 8 GB now\n"
        "qwen3-embedding:8b ghi 5 GB now\n"
    )
    assert [(r["name"], r["kind"]) for r in rows] == [
        ("nomic-embed-text:latest", "EMBEDDING"),
        ("gemma3:12b", "GENERATIVE"),
        ("qwen3-embedding:8b", "EMBEDDING"),
    ]


def test_gpu_policy_fails_closed_with_installed_generation(monkeypatch, tmp_path):
    monkeypatch.setattr(evidence, "ROOT", tmp_path)
    monkeypatch.setattr(evidence, "routing_audit", lambda: {"violation_count": 0})
    outputs = iter([
        (0, "NAME ID SIZE MODIFIED\nnomic-embed-text:latest abc 1 now\ngemma3:4b def 1 now\n"),
        (0, "NAME ID SIZE PROCESSOR UNTIL\n"),
    ])
    monkeypatch.setattr(evidence, "_run", lambda *_args, **_kwargs: next(outputs))
    row = evidence.collect_gpu_policy(now=NOW)
    assert row["gpu_mode"] == "NONCOMPLIANT"
    assert row["compliance_score"] == 0.0
    assert row["installed_generative_count"] == 1


def test_gpu_policy_disabled_only_when_inventory_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(evidence, "ROOT", tmp_path)
    monkeypatch.setattr(evidence, "routing_audit", lambda: {"violation_count": 0})
    outputs = iter([(0, "NAME ID SIZE MODIFIED\n"), (0, "NAME ID SIZE PROCESSOR UNTIL\n")])
    monkeypatch.setattr(evidence, "_run", lambda *_args, **_kwargs: next(outputs))
    row = evidence.collect_gpu_policy(now=NOW)
    assert row["gpu_mode"] == "DISABLED"
    assert row["compliance_score"] == 1.0
