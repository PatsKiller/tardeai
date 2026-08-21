"""I.0 tree-pin audit — classification only, no unit rewrites."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.ops_tree_pin_audit import build_report, classify_text, main


def test_classify_hybrid_current_script_rebuild_venv():
    blob = (
        "WorkingDirectory=/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT\n"
        "ExecStart=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python scripts/x.py\n"
    )
    assert classify_text(blob) == "hybrid"


def test_classify_rebuild_and_current():
    assert classify_text("WorkingDirectory=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild") == "rebuild"
    assert classify_text("WorkingDirectory=/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT") == "current"
    assert classify_text("WorkingDirectory=/home/johnclaw/tradeai-wt-foo") == "worktree"
    assert classify_text("Description=unrelated") == "other"


def test_scan_units_and_strict(tmp_path: Path):
    (tmp_path / "tradeai-cio-telegram.service").write_text(
        "WorkingDirectory=/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT\n"
        "ExecStart=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python x.py\n"
    )
    (tmp_path / "openclaw-gateway.service").write_text(
        "WorkingDirectory=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild\n"
    )
    cron = tmp_path / "cron.txt"
    cron.write_text("0 2 * * * cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild && true\n")
    report = build_report(unit_dir=tmp_path, crontab_text=cron.read_text(), current=tmp_path)
    assert report["units"]["by_class"]["hybrid"] == 1
    # openclaw is not a TradeAI-prefixed name
    assert report["schema"] == "OpsTreePinAudit@v1"
    rc = main(["--unit-dir", str(tmp_path), "--crontab", str(cron), "--json", "--strict"])
    assert rc == 1
