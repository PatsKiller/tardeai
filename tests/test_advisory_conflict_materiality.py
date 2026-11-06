"""Advisory desk payload: conflict_materiality_pct comes from config (Intel consolidation, intel/v001)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import api_v3_advisory as adv  # noqa: E402


def test_reads_repo_config_value():
    import yaml

    cfg = yaml.safe_load((ROOT / "config" / "advisory_desk.yaml").read_text(encoding="utf-8"))
    want = float(cfg["routing"]["cache"]["mv_bucket_pct"])
    assert adv._conflict_materiality_pct() == want


def test_reads_given_file(tmp_path):
    p = tmp_path / "desk.yaml"
    p.write_text("routing:\n  cache:\n    mv_bucket_pct: 1.25\n", encoding="utf-8")
    assert adv._conflict_materiality_pct(p) == 1.25


def test_missing_or_bad_config_fails_closed(tmp_path):
    assert adv._conflict_materiality_pct(tmp_path / "absent.yaml") is None
    bad = tmp_path / "bad.yaml"
    bad.write_text("routing:\n  cache:\n    mv_bucket_pct: nope\n", encoding="utf-8")
    assert adv._conflict_materiality_pct(bad) is None
    neg = tmp_path / "neg.yaml"
    neg.write_text("routing:\n  cache:\n    mv_bucket_pct: -1\n", encoding="utf-8")
    assert adv._conflict_materiality_pct(neg) is None
    empty = tmp_path / "empty.yaml"
    empty.write_text("", encoding="utf-8")
    assert adv._conflict_materiality_pct(empty) is None


def test_payload_carries_key():
    src = (ROOT / "scripts" / "api_v3_advisory.py").read_text(encoding="utf-8")
    assert '"conflict_materiality_pct": _conflict_materiality_pct()' in src
