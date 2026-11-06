"""Effective policy-file resolver (operator 2026-11-06): private overlay → template.

Synthetic values only — the real ratified files are private and never committed.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from scripts.lib import policy_files as pf  # noqa: E402

MP, IPS = pf.MODEL_PORTFOLIO, pf.IPS


def _write(path: Path, doc) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc if isinstance(doc, str) else json.dumps(doc), encoding="utf-8")
    return path


def _ips(limit: float, version: str) -> dict:
    return {
        "_meta": {"version": version, "next_review": "2099-01-01"},
        "constraints": {"concentration_policy": {
            "approval_ref": "synthetic", "near_limit_fraction": 0.5,
            "limits_pct": {"broad_diversified_fund": 50.0, "narrow_thematic_fund": 20.0,
                           "single_stock": limit, "leveraged_inverse_fund": 5.0,
                           "lookthrough_company": 30.0, "lookthrough_sector": 40.0}}},
    }


def _root(tmp_path: Path, *, private=None, template=None, name=MP) -> Path:
    if template is not None:
        _write(tmp_path / "config" / name, template)
    if private is not None:
        _write(tmp_path / "data" / "cio" / "policy" / name, private)
    return tmp_path


def test_private_wins_when_valid(tmp_path):
    root = _root(tmp_path, private={"_meta": {"version": "p"}}, template={"_meta": {"version": "t"}})
    assert pf.policy_path(MP, root) == root / "data/cio/policy" / MP
    assert pf.policy_source(MP, root) == "private"
    assert pf.policy_label(pf.policy_path(MP, root), root) == f"data/cio/policy/{MP}"


def test_missing_private_falls_back_to_template(tmp_path):
    root = _root(tmp_path, template={"_meta": {"version": "t"}})
    assert pf.policy_path(MP, root) == root / "config" / MP
    assert pf.policy_source(MP, root) == "template"


def test_invalid_private_json_falls_back_to_template(tmp_path):
    root = _root(tmp_path, private="{not json", template={"x": 1})
    assert pf.policy_source(MP, root) == "template"


def test_non_object_private_falls_back_to_template(tmp_path):
    root = _root(tmp_path, private=[1, 2, 3], template={"x": 1})
    assert pf.policy_source(MP, root) == "template"


def test_source_for_path_explicit(tmp_path):
    assert pf.source_for_path(tmp_path / "elsewhere" / IPS, tmp_path) == "explicit"


def test_ips_policy_default_reads_private_but_explicit_arg_wins(tmp_path, monkeypatch):
    from scripts.lib import ips_policy

    root = _root(tmp_path, private=_ips(11.0, "p"), template=_ips(22.0, "t"), name=IPS)
    monkeypatch.setattr(ips_policy, "PROJECT_ROOT", root)
    monkeypatch.setattr(ips_policy, "CONFIG_DIR", root / "config")
    assert ips_policy.ips_max_position_pct() == 11.0
    pol = ips_policy.concentration_policy()
    assert pol["source"].startswith(f"data/cio/policy/{IPS}") and pol["policy_source"] == "private"
    # explicit config_dir / file path always wins over the private overlay
    assert ips_policy.ips_max_position_pct(root / "config") == 22.0
    other = _write(tmp_path / "x" / IPS, _ips(33.0, "x"))
    assert ips_policy.ips_max_position_pct(other) == 33.0
    assert ips_policy.concentration_policy(other)["source"].startswith(f"config/{IPS}")


def test_sector_targets_follow_private_model(tmp_path):
    from scripts.lib.cio_sector_opportunity import load_sector_target_map

    root = _root(tmp_path, private={"sector_targets": {"energy": {"target_pct": 7.0}}},
                 template={"sector_targets": {"energy": {"target_pct": 3.0}}})
    loaded = load_sector_target_map(project_root=root)
    assert loaded["targets"]["Energy"] == 7.0
    assert f"data/cio/policy/{MP}" in loaded["configs_loaded"]


def test_review_overdue():
    assert pf.review_overdue({"_meta": {"next_review": "2026-01-01"}}, today=date(2026, 11, 6))
    assert not pf.review_overdue({"_meta": {"next_review": "2026-12-01"}}, today=date(2026, 11, 6))
    assert not pf.review_overdue({"_meta": {}}, today=date(2026, 11, 6))
    assert not pf.review_overdue({"_meta": {"next_review": "someday"}})


def _holdings():
    return {"holdings": [
        {"symbol": "AAA", "market_value": 900.0, "account": "A1", "bucket": "Core"},
        {"symbol": "CASH", "market_value": 100.0, "account": "A1", "is_cash": True},
    ]}


def _model(next_review: str) -> dict:
    return {"_meta": {"version": "syn", "next_review": next_review},
            "strategic_allocation": {"equity": {"target_pct": 50.0}, "cash_and_equivalents": {"target_pct": 50.0}}}


def test_allocation_rows_flag_stale_when_review_past(tmp_path, monkeypatch):
    from lib.data_broker import advisory_desk as ad

    _write(tmp_path / MP, _model("2000-01-01"))
    monkeypatch.setattr(ad, "CONFIG_DIR", tmp_path)
    rows = [r for r in ad._derive_allocation_rows(_holdings(), 1000.0) if r["symbol"] == "ALLOC:equity"]
    assert rows and rows[0]["policy_stale"] is True
    assert rows[0]["policy_next_review"] == "2000-01-01"
    assert rows[0]["rationale"].startswith("STALE TARGETS")


def test_allocation_rows_current_when_review_future(tmp_path, monkeypatch):
    from lib.data_broker import advisory_desk as ad

    _write(tmp_path / MP, _model("2999-01-01"))
    monkeypatch.setattr(ad, "CONFIG_DIR", tmp_path)
    rows = [r for r in ad._derive_allocation_rows(_holdings(), 1000.0) if r["symbol"] == "ALLOC:equity"]
    assert rows and rows[0]["policy_stale"] is False
    assert not rows[0]["rationale"].startswith("STALE")
