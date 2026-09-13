"""A pinned TRADEAI_STATE_ROOT must actually isolate.

CL-64-ci. `_canonical_paths` appended PROJECT_ROOT/<fallback> whenever the
resolved root differed from PROJECT_ROOT, "to preserve the historical
PROJECT_ROOT fixture behavior when monkeypatched". The effect was that pinning a
state root isolated nothing: a caller pointing at an empty directory still read
files out of the checkout.

test_whole_site_truth::test_an_empty_state_root_is_never_reported_live therefore
passed only because those repo paths happened not to exist. Creating one file --

    data/cio/cio_workflow_lineage.jsonl

-- made /v3/control-plane/workflows answer LIVE against an empty root. That is
what a fresh CI clone hit once a test suite wrote into data/cio, and it is why
two rounds of test-hygiene fixes did not close the gate: the leak was real but
the gate was failing on the path contract, not on the leak.

Production never exercised the branch -- none of TRADEAI_STATE_ROOT,
TRADEAI_ROOT or TRADEAI_PERSISTENT_STATE_ROOT is set on the host, so
_state_root() returns PROJECT_ROOT.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import control_plane_api as cpa  # noqa: E402


def test_pinned_root_does_not_leak_project_root(monkeypatch, tmp_path):
    """NEGATIVE CONTROL: before the fix, PROJECT_ROOT paths were appended too."""
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    paths = cpa._domain_paths("workflows")
    assert paths, "the domain must still resolve somewhere"
    for p in paths:
        assert cpa.PROJECT_ROOT not in Path(p).parents, (
            f"{p} escapes the pinned state root into the checkout"
        )


def test_pinned_root_is_where_the_domain_looks(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    assert any(tmp_path in Path(p).parents or Path(p).parent == tmp_path
               for p in cpa._domain_paths("workflows"))


def test_a_repo_file_cannot_make_a_pinned_empty_root_look_live(monkeypatch, tmp_path):
    """The exact defect, end to end: a file in the checkout must not satisfy a
    domain whose state root was pinned elsewhere and is empty."""
    lineage = cpa.PROJECT_ROOT / "data" / "cio" / "cio_workflow_lineage.jsonl"
    created = not lineage.exists()
    if created:
        lineage.parent.mkdir(parents=True, exist_ok=True)
        lineage.write_text('{"workflow_id": "probe"}\n', encoding="utf-8")
    try:
        monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
        status, body = cpa.handle("/api/v3/control-plane/workflows")
        assert status == 200
        assert body.get("data_quality") != "AVAILABLE", (
            "a file inside the checkout satisfied a pinned, empty state root"
        )
    finally:
        if created:
            lineage.unlink()


def test_unpinned_root_is_unchanged(monkeypatch):
    """Production path: with nothing pinned the root IS PROJECT_ROOT, so the
    repo-relative fallbacks still resolve exactly as before."""
    for key in ("TRADEAI_STATE_ROOT", "TRADEAI_ROOT", "TRADEAI_PERSISTENT_STATE_ROOT"):
        monkeypatch.delenv(key, raising=False)
    assert cpa._state_root() == cpa.PROJECT_ROOT
    assert any(cpa.PROJECT_ROOT in Path(p).parents or Path(p).parent == cpa.PROJECT_ROOT
               for p in cpa._domain_paths("workflows"))


@pytest.mark.parametrize("domain", ["workflows", "research"])
def test_no_domain_escapes_a_pinned_root(monkeypatch, tmp_path, domain):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    for p in cpa._domain_paths(domain):
        assert cpa.PROJECT_ROOT not in Path(p).parents, f"{domain}: {p} escapes"
