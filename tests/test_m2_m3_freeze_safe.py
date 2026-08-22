"""M2 CLI defaults stay production; M3 sweep excludes _archive and does not fall back to root."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_researcher_max_output_tokens_defaults_unset():
    src = (ROOT / "scripts/hermes_external_researcher.py").read_text()
    assert '--max-output-tokens", type=int, default=None' in src
    assert "--no-store" in src
    assert "--prompt-file" in src
    # cron path still 1024
    reg = (ROOT / "config/llm_process_registry.json").read_text()
    assert '"id": "hermes_external_research"' in reg
    assert '"max_output_tokens": 1024' in reg
    gate = (ROOT / "scripts/lib/llm_consumption.py").read_text()
    assert "HERMES_SANDBOX_OUTPUT_CEILING" in gate
    assert "min(req_out, int(proc_out))" in gate


def test_drive_sweep_excludes_archive_and_does_not_fallback_root():
    src = (ROOT / "scripts/sync-docs-to-drive.sh").read_text()
    assert '! -path "*/_archive/*"' in src
    assert "docs/*_20[0-9][0-9][0-9][0-9][0-9][0-9]_*" in src
    assert "docs/*20[0-9][0-9]*/*" in src
    assert "docs/_findings/*" in src
    assert "DEGRADED_STALE_SOURCE" in src
    assert "targeted_replace_until" in src
    assert "docs/ui_review/*" in src
    assert "do not fall back to root" in src
    assert 'current_parent="$DRIVE_FOLDER_ID"' in src
    # mkdir-fail must echo empty, not root
    assert "could not create folder $built_path — skip" in src
    assert 'echo "$DRIVE_FOLDER_ID"\n        return' not in src
    py = (ROOT / "scripts/sync-docs-to-drive.py").read_text()
    assert r"/_archive/" in py
