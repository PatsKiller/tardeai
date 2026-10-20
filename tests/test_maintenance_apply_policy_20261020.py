"""Unsupported destructive entry points cannot turn caller strings into authority.

All reads/writes are scratch-only and removal leaves are fake. These tests never
use a real grant, run a deletion, or inspect the host's maintenance candidates.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import disk_hygiene as DH
from scripts import tmp_hygiene as TH

ROOT = Path(__file__).resolve().parents[1]
REASON = "destructive_apply_unsupported_by_active_policy"
NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)


def invoke(module, manifest, rules, *, grant, run_id=None):
    if module is TH:
        return module.apply(
            manifest,
            rules,
            {"_root": manifest.parent, "apply": rules.get("apply", {})},
            NOW,
            grant=grant,
            run_id=run_id,
        )
    return module.apply(manifest, rules, NOW, grant=grant, run_id=run_id)


@pytest.mark.parametrize("module", [DH, TH], ids=["disk", "tmp"])
def test_invented_token_cannot_admit_a_public_removal(module, tmp_path, monkeypatch):
    target = tmp_path / "retained.txt"
    target.write_text("retained bytes")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": DH.MANIFEST_SCHEMA,
                "scope": "tmp",
                "home": str(tmp_path),
                "tmp_root": str(tmp_path),
                "generated_at": NOW.isoformat(),
                "items": [{"path": str(target), "kind": "fixture", "size_bytes": 1, "file_count": 1}],
            }
        )
    )
    calls = []
    monkeypatch.setattr(module, "build_context", lambda *a: {})
    monkeypatch.setattr(module, "revalidate", lambda item, *a: (True, "", item) if module is TH else (True, ""))
    monkeypatch.setattr(module, "remove_item", lambda item: (calls.append(item["path"]) or True, "FAKE"))
    caps = {"manifest_max_age_hours": 24, "max_items_per_run": 10, "max_bytes_per_run": 100, "max_files_per_run": 100}
    result = invoke(module, manifest, {"_home": tmp_path, "apply": caps}, grant="invented-not-a-grant")
    assert result["refused"] == REASON, f"unverified caller token admitted fake effects: {calls}"
    assert calls == [] and target.read_text() == "retained bytes"
    assert result["removed"] == [] and "grant" not in result


@pytest.mark.parametrize("module", [DH, TH], ids=["disk", "tmp"])
@pytest.mark.parametrize("grant", [None, "", "f" * 32])
def test_policy_hold_precedes_even_manifest_validation(module, grant, tmp_path):
    missing = tmp_path / "no-manifest.json"
    result = invoke(module, missing, {}, grant=grant)
    assert result["refused"] == REASON
    assert not missing.exists() and result["removed"] == []


@pytest.mark.parametrize("module", [DH, TH], ids=["disk", "tmp"])
def test_cli_hold_precedes_rule_reads_and_state_writes(module, tmp_path, monkeypatch, capsys):
    calls = []

    def unexpected_rules(*args, **kwargs):
        calls.append("rules")
        raise AssertionError("unsupported --apply reached rule loading")

    monkeypatch.setattr(DH, "load_rules", unexpected_rules)
    monkeypatch.setenv(DH.GRANT_ENV, "invented-not-a-grant")
    monkeypatch.delenv(DH.RUN_ID_ENV, raising=False)
    code = module.main(
        [
            "--apply",
            "--rules",
            str(tmp_path / "missing-rules"),
            "--state-root",
            str(tmp_path / "state"),
            "--now",
            "not-a-clock",
        ]
    )
    assert code == 1
    assert json.loads(capsys.readouterr().out)["refused"] == REASON
    assert calls == [] and not (tmp_path / "state").exists()


@pytest.mark.parametrize("step", ["hygiene-apply", "tmp-apply"])
@pytest.mark.parametrize("has_manifest", [False, True], ids=["missing-manifest", "present-manifest"])
def test_packet_policy_hold_precedes_manifest_or_served_code(step, has_manifest, tmp_path):
    state = tmp_path / "state"
    served = tmp_path / "served"
    served.mkdir()
    marker = tmp_path / "python-was-invoked"
    fake_py = tmp_path / "fake-python"
    fake_py.write_text(f"#!/bin/sh\nprintf invoked >> '{marker}'\nexit 0\n")
    fake_py.chmod(0o700)
    if has_manifest:
        directory = state / "data/runtime/disk_hygiene"
        directory.mkdir(parents=True)
        name = "tmp_hygiene_manifest_latest.json" if step == "tmp-apply" else "disk_hygiene_manifest_latest.json"
        (directory / name).write_text(
            json.dumps(
                {
                    "generated_at": NOW.isoformat(),
                    "totals": {"candidates": 1, "reclaimable_gb": 1, "reclaimable_files": 1, "by_kind": {}},
                }
            )
        )
    before = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path / "home"),
        "PY": str(fake_py),
        "REPO": str(ROOT),
        "CODE": str(ROOT),
        "SERVED": str(served),
        "STATE": str(state),
        "TRADEAI_DISK_HYGIENE_GRANT": "invented-not-a-grant",
    }
    result = subprocess.run(
        ["bash", str(ROOT / "docs/ops/packets/disk-hygiene-n8n-20261018/cutover.sh"), step, "--apply"],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1 and REASON in result.stdout
    assert not marker.exists()
    assert {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


def test_existing_executor_refusal_still_has_no_effects(tmp_path):
    for module in (DH, TH):
        result = invoke(
            module,
            tmp_path / "never-created.json",
            {},
            grant="invented-not-a-grant",
            run_id="d:maintenance:live:fixture",
        )
        assert result["refused"] and result["removed"] == []
    assert list(tmp_path.iterdir()) == []
