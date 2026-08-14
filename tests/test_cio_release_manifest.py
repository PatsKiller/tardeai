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


def test_validate_committed_is_read_only_and_does_not_require_head_pin():
    from cio_release_manifest import validate_committed, MANIFEST_JSON
    before = MANIFEST_JSON.read_bytes() if MANIFEST_JSON.is_file() else b""
    r = validate_committed()
    after = MANIFEST_JSON.read_bytes() if MANIFEST_JSON.is_file() else b""
    assert after == before
    assert r["mutated"] is False
    assert r["mode"] == "committed_integrity"
    # Current main pin may be RC/stale vs HEAD; integrity can still pass.
    assert "ok" in r


def test_candidate_does_not_mutate_committed(tmp_path):
    from cio_release_manifest import MANIFEST_JSON, main as manifest_main
    before = MANIFEST_JSON.read_bytes() if MANIFEST_JSON.is_file() else b""
    dest = tmp_path / "cand"
    rc = manifest_main(["candidate", "--out-dir", str(dest)])
    assert rc == 0
    after = MANIFEST_JSON.read_bytes() if MANIFEST_JSON.is_file() else b""
    assert after == before
    assert (dest / "RELEASE_MANIFEST.json").is_file()
    assert (dest / "RELEASE_MANIFEST.md").is_file()


def test_ci_runner_does_not_regenerate_committed_manifest():
    text = (ROOT / "scripts" / "run_cio_hardening_ci.py").read_text()
    assert "check-committed" in text
    assert "generate_candidate_manifest" in text
    # Forbidden: generate --write of the committed docs pin before check
    assert 'generate", "--write"' not in text
    assert "regenerated RELEASE_MANIFEST for CI HEAD" not in text


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


def test_parent_pin_only_manifest_commit_is_ok(tmp_path, monkeypatch):
    """Pin commit may trail one step when only RELEASE_MANIFEST* changed."""
    import cio_release_manifest as mod

    monkeypatch.setattr(mod, "MANIFEST_MD", tmp_path / "RELEASE_MANIFEST.md")
    monkeypatch.setattr(mod, "MANIFEST_JSON", tmp_path / "RELEASE_MANIFEST.json")
    parent = mod._run(["git", "rev-parse", "HEAD^"])
    head = mod.git_head()
    if not parent or not head or parent == head:
        pytest.skip("need at least two commits")
    # Simulate disk pin = parent (content), live HEAD = tip
    m = mod.build_manifest()
    m["canonical_source_sha"] = parent
    mod.write_manifest(m)
    # Only allow if git says tip vs parent is pin-only — if tip has more changes, expect fail
    changed = {
        ln.strip()
        for ln in mod._run(["git", "diff", "--name-only", f"{parent}..{head}"]).splitlines()
        if ln.strip()
    }
    allowed = {
        "docs/investment-office/RELEASE_MANIFEST.md",
        "docs/investment-office/RELEASE_MANIFEST.json",
    }
    result = mod.validate()
    if changed and changed <= allowed:
        assert result["ok"] is True, result
        assert any("pin-only" in w for w in result["warnings"])
    else:
        # Current tip is not a pin-only commit — mismatch must still fail
        assert result["ok"] is False
        assert any("mismatch" in e for e in result["errors"])
