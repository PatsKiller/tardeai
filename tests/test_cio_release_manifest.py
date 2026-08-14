"""Phase 10 — release manifest generate/validate (stale fails)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from cio_release_manifest import (  # noqa: E402
    REQUIRED_FIELDS,
    FORBIDDEN_STALE_SHAS,
    build_manifest,
    validate,
    write_manifest,
    parse_md_pins,
    render_markdown,
)


def test_build_manifest_has_required_fields():
    m = build_manifest()
    for f in REQUIRED_FIELDS:
        assert f in m and m[f], f
    assert m["canonical_source_sha"]
    assert len(m["canonical_source_sha"]) >= 12
    assert m["report_version"]
    assert m["manifest_hash"]
    assert m["financial_authority"] == "READ_ONLY_ADVISORY"


def test_manifest_forbids_phase0_stale_shas_as_canonical():
    m = build_manifest()
    # live head must not be the Phase 0 preliminary pins
    assert not m["canonical_source_sha"].startswith("0a9b6c41")
    assert not m["canonical_source_sha"].startswith("d9b63ed6")
    assert m["canonical_source_sha"] not in FORBIDDEN_STALE_SHAS


def test_write_and_validate_roundtrip(tmp_path, monkeypatch):
    import cio_release_manifest as mod

    monkeypatch.setattr(mod, "MANIFEST_MD", tmp_path / "RELEASE_MANIFEST.md")
    monkeypatch.setattr(mod, "MANIFEST_JSON", tmp_path / "RELEASE_MANIFEST.json")
    m = mod.build_manifest()
    mod.write_manifest(m)
    assert mod.MANIFEST_MD.is_file()
    assert mod.MANIFEST_JSON.is_file()
    disk = json.loads(mod.MANIFEST_JSON.read_text())
    assert disk["canonical_source_sha"] == m["canonical_source_sha"]
    pins = parse_md_pins(mod.MANIFEST_MD.read_text())
    assert pins["canonical_source_sha"] == m["canonical_source_sha"]
    assert pins["report_version"] == m["report_version"]
    result = mod.validate(m)
    assert result["ok"] is True, result


def test_stale_disk_manifest_fails_validate(tmp_path, monkeypatch):
    import cio_release_manifest as mod

    monkeypatch.setattr(mod, "MANIFEST_MD", tmp_path / "RELEASE_MANIFEST.md")
    monkeypatch.setattr(mod, "MANIFEST_JSON", tmp_path / "RELEASE_MANIFEST.json")
    m = mod.build_manifest()
    m["canonical_source_sha"] = "0a9b6c415e02dc23d150a020327689044d0aa72b"
    m["docs_pin"] = "0a9b6c415e02dc23d150a020327689044d0aa72b"
    mod.write_manifest(m)
    result = mod.validate()  # live HEAD differs
    assert result["ok"] is False
    assert result["stale_manifest"] is True
    assert any("mismatch" in e or "stale" in e for e in result["errors"])


def test_render_markdown_contains_pin_table():
    m = build_manifest()
    md = render_markdown(m)
    assert "canonical_source_sha" in md
    assert m["canonical_source_sha"] in md
    assert "READ_ONLY_ADVISORY" in md
    # pin table value must be current head, not Phase 0 preliminary
    pins = parse_md_pins(md)
    assert pins["canonical_source_sha"] == m["canonical_source_sha"]
    assert not pins["canonical_source_sha"].startswith("0a9b6c41")
