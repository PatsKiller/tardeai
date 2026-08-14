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
    V2_EXPLICIT_FIELDS,
    FORBIDDEN_STALE_SHAS,
    SCHEMA_V2,
    ATTESTATION_ONLY_NOTE,
    CLASS_ATTESTATION,
    CLASS_RUNTIME,
    build_manifest,
    validate,
    write_manifest,
    parse_md_pins,
    render_markdown,
    classify_release_commit,
    resolve_release_identity,
    notes_claim_same_full_sha,
    git_head,
)


def test_build_manifest_has_required_fields():
    m = build_manifest()
    for f in REQUIRED_FIELDS:
        assert f in m and m[f], f
    for f in V2_EXPLICIT_FIELDS:
        assert f in m and m[f], f
    assert m["manifest_schema"] == SCHEMA_V2
    assert m["canonical_source_sha"]
    assert len(m["canonical_source_sha"]) >= 12
    assert m["canonical_source_sha"] == m["release_content_sha"]
    assert m["origin_main_sha"] == m["remote_main_sha_at_manifest"]
    assert m["created_at"] == m["manifest_created_at"]
    assert m["report_source_sha"] == m["release_content_sha"]
    assert m["report_version"]
    assert m["manifest_hash"]
    assert m["financial_authority"] == "READ_ONLY_ADVISORY"
    assert m["manifest_generated_from_sha"] == git_head()


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
    m["release_content_sha"] = "0a9b6c415e02dc23d150a020327689044d0aa72b"
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
    m["release_content_sha"] = parent
    m["report_source_sha"] = parent
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


# Known production identity on this tree (do not rewrite the committed v1 pin).
_CONTENT = "7986e923bc29c863a27bf41a40bf1aefca3b1da8"
_ATTESTATION = "faff6ac153c6ac2ea0e59385c26c7368270374f7"


def test_classify_attestation_merge_uses_content_7986e923():
    ident = classify_release_commit(_ATTESTATION)
    assert ident["class"] == CLASS_ATTESTATION
    assert ident["attestation_only"] is True
    assert ident["release_content_sha"] == _CONTENT
    assert ident["release_attestation_sha"] == _ATTESTATION


def test_classify_runtime_content_commit():
    ident = classify_release_commit(_CONTENT)
    assert ident["class"] == CLASS_RUNTIME
    assert ident["attestation_only"] is False
    assert ident["release_content_sha"] == _CONTENT


def test_attestation_head_notes_do_not_claim_same_full_sha(monkeypatch):
    import cio_release_manifest as mod

    monkeypatch.setattr(mod, "git_head", lambda: _ATTESTATION)
    monkeypatch.setattr(mod, "git_origin_main", lambda: _ATTESTATION)
    m = mod.build_manifest()
    assert m["manifest_schema"] == SCHEMA_V2
    assert m["release_content_sha"] == _CONTENT
    assert m["release_attestation_sha"] == _ATTESTATION
    assert m["canonical_source_sha"] == _CONTENT
    assert m["origin_main_sha"] == _ATTESTATION
    assert m["remote_main_sha_at_manifest"] == _ATTESTATION
    assert m["report_source_sha"] == _CONTENT
    assert m["manifest_generated_from_sha"] == _ATTESTATION
    assert m["financial_authority"] == "READ_ONLY_ADVISORY"
    assert ATTESTATION_ONLY_NOTE in m["notes"]
    assert notes_claim_same_full_sha(m["notes"]) is False
    assert "pin the same full SHA" not in m["notes"]
    md = render_markdown(m)
    assert "release_content_sha" in md
    assert _CONTENT in md
    assert _ATTESTATION in md
    assert ATTESTATION_ONLY_NOTE in md


def test_operator_note_cannot_force_same_sha_claim_when_attestation(monkeypatch):
    import cio_release_manifest as mod

    monkeypatch.setattr(mod, "git_head", lambda: _ATTESTATION)
    monkeypatch.setattr(mod, "git_origin_main", lambda: _ATTESTATION)
    m = mod.build_manifest(note=(
        "Production investment-office release: Git main, CURRENT, and this "
        "manifest pin the same full SHA."
    ))
    assert notes_claim_same_full_sha(m["notes"]) is False
    assert ATTESTATION_ONLY_NOTE in m["notes"]


def test_generate_does_not_rewrite_historical_committed_pin():
    """This branch HEAD is not the attestation merge — do not pretend it is 7986e923."""
    from cio_release_manifest import load_json_manifest

    head = git_head()
    ident = resolve_release_identity()
    m = build_manifest()
    if ident["attestation_only"]:
        assert m["release_content_sha"] == _CONTENT
        assert m["release_attestation_sha"] == _ATTESTATION
    else:
        assert m["release_content_sha"] == head
        assert m["canonical_source_sha"] == head
        assert m["release_content_sha"] != _CONTENT or head == _CONTENT
    disk = load_json_manifest()
    assert disk is not None
    # Committed production pin stays the historical content SHA.
    assert disk["canonical_source_sha"] == _CONTENT
    assert disk.get("manifest_schema") == "investment_office_release_manifest_v1"
    assert "release_content_sha" not in disk


def test_validate_committed_accepts_historical_v1_pin():
    from cio_release_manifest import validate_committed

    r = validate_committed()
    assert r["ok"] is True, r
    assert r["disk_canonical_source_sha"] == _CONTENT
    assert r.get("disk_schema") == "investment_office_release_manifest_v1"


def test_render_markdown_includes_v2_identity_rows():
    m = build_manifest()
    md = render_markdown(m)
    pins = parse_md_pins(md)
    assert pins["canonical_source_sha"] == m["canonical_source_sha"]
    assert pins["release_content_sha"] == m["release_content_sha"]
    assert pins["release_attestation_sha"] == m["release_attestation_sha"]
    assert pins["remote_main_sha_at_manifest"] == m["remote_main_sha_at_manifest"]
    assert pins["report_source_sha"] == m["report_source_sha"]
    assert pins["rollback_content_sha"] == m["rollback_content_sha"]
    assert pins["financial_authority"] == "READ_ONLY_ADVISORY"
    assert pins["manifest_generated_from_sha"] == m["manifest_generated_from_sha"]
