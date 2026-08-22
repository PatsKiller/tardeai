"""DeepSeek scheduler path must load .env and not store empty recommendations."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_llm_lane_loads_repo_env():
    src = (ROOT / "scripts" / "llm_lane.py").read_text(encoding="utf-8")
    assert "def _load_repo_env" in src
    assert "LLM_GLOBAL_DAILY_USD_CAP" in src
    assert "_load_repo_env()" in src


def test_researcher_keeps_raw_when_json_parse_fails():
    src = (ROOT / "scripts" / "hermes_external_researcher.py").read_text(encoding="utf-8")
    assert 'parsed["recommendation"] = str(raw).strip()[:4000]' in src
    assert "from llm_lane import generate" in src
    assert "from lib.llm_lane import" not in src
