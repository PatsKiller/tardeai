from pathlib import Path

from scripts.audit_local_model_decommission import (
    active_cron_callers,
    classify_model,
    config_callers,
    parse_ollama_list,
    parse_ollama_ps,
)


def test_model_classification_is_explicit():
    assert classify_model("gemma3:12b") == "GENERATIVE"
    assert classify_model("qwen3:8b") == "GENERATIVE"
    assert classify_model("qwen3-embedding:8b") == "EMBEDDING"
    assert classify_model("nomic-embed-text:latest") == "EMBEDDING"
    assert classify_model("mystery-model:latest") == "UNKNOWN_UNUSED"


def test_ollama_inventory_and_process_parsers():
    listing = "NAME ID SIZE MODIFIED\ngemma3:4b abc 3 GB today\nnomic-embed-text:latest def 274 MB today\n"
    running = "NAME ID SIZE PROCESSOR CONTEXT UNTIL\ngemma3:12b xyz 9 GB 100% GPU 4096 4m\n"
    assert [row["class"] for row in parse_ollama_list(listing)] == ["GENERATIVE", "EMBEDDING"]
    assert parse_ollama_ps(running)[0]["class"] == "GENERATIVE"


def test_cron_intersection_ignores_comments_and_finds_indirect_callers():
    cron = """# 0 1 * * * scripts/legacy.py\n0 2 * * * python scripts/live.py\n0 3 * * * job --lane local\n"""
    callers = [{"file": "scripts/live.py", "line": 4, "kind": "local_helper", "text": "x"}]
    hits = active_cron_callers(cron, callers)
    assert len(hits) == 2
    assert all(not str(row["command"]).startswith("#") for row in hits)


def test_decommission_audit_is_read_only_source():
    source = (Path(__file__).resolve().parents[1] / "scripts" / "audit_local_model_decommission.py").read_text()
    assert "ollama rm" not in source
    assert "systemctl disable" not in source
    assert "crontab -r" not in source


def test_openclaw_scan_excludes_backups_and_history(tmp_path):
    (tmp_path / "openclaw.json").write_text('{"model":"gemma3:12b"}')
    (tmp_path / "openclaw.json.bak").write_text('{"model":"qwen3:8b"}')
    (tmp_path / "session_archive").mkdir()
    (tmp_path / "session_archive" / "old.json").write_text('{"model":"gemma3:27b"}')
    hits = config_callers(tmp_path)
    assert len(hits) == 1
    assert hits[0]["file"].endswith("openclaw.json")
