"""LQ-20261107-1259: the workbook pages cannot drift from the catalog and the replay snapshot.

The workbook is generated (`scripts/lib/self_heal_runbook_docs.py`, CLI
`scripts/gen_self_heal_runbook_docs.py`). This module is the drift gate:

* regenerating at the committed catalog + snapshot + corpus index reproduces the committed pages **byte for byte**;
* every catalog entry has exactly one page, and no page is orphaned (a page for an entry that no longer exists);
* every page carries its ten sections, and the index links every entry;
* the snapshot is consistent with itself and with the catalog (hits add up, every signature resolves to an existing
  entry, no catch-all signature lacks a written reason, the snapshot names this catalog version);
* a generated page carries no forbidden pattern (public repository: no address, e-mail, token or long hex);
* the renderer is deterministic (two renders of the same inputs are identical) and takes no clock.

No DB, no network, no live coordination store, no command executed by the test but the generator's own render.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "runbooks" / "self_heal"
CATALOG = ROOT / "config" / "self_heal_runbook_catalog.json"
SNAPSHOT = DOCS / "COVERAGE.json"
FIXTURES = ROOT / "tests" / "fixtures" / "self_heal_runbooks"
GENERATOR = ROOT / "scripts" / "gen_self_heal_runbook_docs.py"
RENDERER = ROOT / "scripts" / "lib" / "self_heal_runbook_docs.py"
CATCH_ALL = "K05-unclassified-catch-all"
# Public repository: no IPv4 address, e-mail address, token-shaped string or long hex digest in a page.
FORBIDDEN = re.compile(r"(\b\d{1,3}(\.\d{1,3}){3}\b|[\w.+-]+@[\w-]+\.[\w.]+|\b(sk|ghp|xox[bp])[-_][A-Za-z0-9]{8,}"
                       r"|\b[0-9a-f]{32,}\b)")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def catalog() -> dict:
    return _load(CATALOG)


@pytest.fixture(scope="module")
def snapshot() -> dict:
    return _load(SNAPSHOT)


@pytest.fixture(scope="module")
def renderer():
    return _module("self_heal_runbook_docs", RENDERER)


def _fixture_index() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for path in sorted(FIXTURES.glob("*.json")):
        doc = _load(path)
        entry = str(((doc or {}).get("expect") or {}).get("entry_id") or "")
        if entry:
            out.setdefault(entry, []).append(path.stem)
    return out


def _rendered(renderer, catalog: dict, snapshot: dict) -> dict[str, str]:
    return renderer.render_all(catalog, snapshot, fixtures_by_entry=_fixture_index())


# ---------------------------------------------------------------- inputs exist


def test_the_workbook_and_its_inputs_exist():
    assert DOCS.is_dir()
    assert SNAPSHOT.is_file(), "COVERAGE.json is missing: run scripts/ops/self_heal_runbook_replay.py"
    assert RENDERER.is_file() and GENERATOR.is_file()
    for name in ("README.md", "RULINGS.md"):
        page = DOCS / name
        assert page.is_file(), name
        assert len(page.read_text(encoding="utf-8").strip()) > 500, f"{name} is a stub"


# ---------------------------------------------------------------- regeneration == committed


def test_regenerating_reproduces_every_committed_page(renderer, catalog, snapshot):
    rendered = _rendered(renderer, catalog, snapshot)
    on_disk = {p.name for p in DOCS.glob("*.md") if p.name not in renderer.STATIC_FILES}
    assert set(rendered) == on_disk, (
        "run scripts/gen_self_heal_runbook_docs.py --write; "
        f"missing={sorted(set(rendered) - on_disk)} orphaned={sorted(on_disk - set(rendered))}")
    stale = [name for name, text in sorted(rendered.items())
             if (DOCS / name).read_text(encoding="utf-8") != text]
    assert not stale, f"page(s) differ from the catalog + snapshot: {stale}"


def test_every_catalog_entry_has_a_page_and_no_page_is_orphaned(renderer, catalog):
    ids = [e["id"] for e in catalog["runbooks"]]
    generated_pages = {"INDEX", "COVERAGE"}      # the workbook's own two pages
    pages = {p.stem for p in DOCS.glob("*.md")
             if p.name not in renderer.STATIC_FILES and p.stem not in generated_pages}
    assert pages == set(ids), {"missing": sorted(set(ids) - pages), "orphaned": sorted(pages - set(ids))}


def test_the_generator_check_mode_agrees(renderer):
    """The CLI a maintainer runs and the test assert the same thing."""
    generator = _module("gen_self_heal_runbook_docs", GENERATOR)
    assert generator.main(["--check"]) == 0


def test_the_renderer_is_deterministic(renderer, catalog, snapshot):
    assert _rendered(renderer, catalog, snapshot) == _rendered(renderer, catalog, snapshot)


# ---------------------------------------------------------------- page structure


def test_every_entry_page_carries_each_required_section(renderer, catalog):
    for entry in catalog["runbooks"]:
        text = (DOCS / f"{entry['id']}.md").read_text(encoding="utf-8")
        missing = [heading for heading in renderer.SECTIONS if heading not in text]
        assert not missing, f"{entry['id']}: missing {missing}"
        assert text.startswith(f"# {entry['id']} — {entry['title']}"), entry["id"]
        assert f"`{entry['action']}`" in text, f"{entry['id']}: the action is not stated"
        assert f"`{entry['tier']}`" in text, f"{entry['id']}: the tier is not stated"
        for link in ("INDEX.md", "COVERAGE.md", "RULINGS.md"):
            assert link in text, f"{entry['id']}: no link to {link}"


def test_the_index_links_every_entry_and_states_the_counts(catalog, snapshot):
    text = (DOCS / "INDEX.md").read_text(encoding="utf-8")
    for entry in catalog["runbooks"]:
        assert f"[{entry['id']}]({entry['id']}.md)" in text, entry["id"]
    totals = snapshot["totals"]
    assert f"**{totals['window_failures']} failures**" in text
    assert f"**{len(snapshot['signatures'])} signatures**" in text


def test_no_generated_page_carries_a_forbidden_pattern(renderer):
    for path in sorted(DOCS.glob("*.md")):
        if path.name in renderer.STATIC_FILES:
            continue
        hit = FORBIDDEN.search(path.read_text(encoding="utf-8"))
        assert hit is None, f"{path.name}: forbidden pattern {hit.group(0)!r}"


# ---------------------------------------------------------------- snapshot consistency


def test_the_snapshot_names_the_catalog_it_was_replayed_against(catalog, snapshot):
    assert snapshot["schema"] == "SelfHealRunbookCoverage@v1"
    assert snapshot["catalog"]["version"] == catalog["version"], (
        "re-run scripts/ops/self_heal_runbook_replay.py: the snapshot is for another catalog version")
    assert snapshot["catalog"]["entries"] == len(catalog["runbooks"])


def test_every_signature_resolves_to_a_catalog_entry(catalog, snapshot):
    ids = {e["id"] for e in catalog["runbooks"]}
    assert snapshot["signatures"], "the replay found no failures; an empty window proves nothing"
    for row in snapshot["signatures"]:
        for plan in row["plans"]:
            assert plan["entry"] in ids, (row["signature"], plan["entry"])
            assert plan["action"] in ("none",) or plan["action"] in {
                "noop_wait_recheck", "rerun_once_via_gateway", "defer_until", "release_stale_flock",
                "release_stale_sqlite_wal_lock", "open_breaker_cooldown", "mark_weekend_expected",
                "escalate_finding"}, (row["signature"], plan["action"])


def test_no_catch_all_signature_lacks_a_written_reason(snapshot):
    catch_all = snapshot["catch_all"]
    assert catch_all["missing_reason"] == [], (
        "a signature reaches the catch-all with no written reason: add an entry, or a GATE_REASONS reason with "
        f"evidence: {catch_all['missing_reason']}")
    for row in catch_all["signatures"]:
        assert row["reason_written"], row["signature"]


def test_the_counts_add_up(snapshot):
    total = snapshot["totals"]["window_failures"]
    assert sum(row["hits"] for row in snapshot["signatures"]) == total
    for row in snapshot["signatures"]:
        assert sum(plan["hits"] for plan in row["plans"]) == row["hits"], row["signature"]
        assert sum(row["sources"].values()) == row["hits"], row["signature"]
    assert sum(row["hits"] for row in snapshot["entries"].values()) == total


def test_every_entry_hit_in_the_snapshot_has_a_page(catalog, snapshot):
    ids = {e["id"] for e in catalog["runbooks"]}
    for eid, row in snapshot["entries"].items():
        assert eid in ids, eid
        assert row["hits"] > 0 and row["lanes"], eid
        assert CATCH_ALL not in snapshot["entries"] or not snapshot["entries"][CATCH_ALL]["hits"], (
            "the catch-all received a signature; see test_no_catch_all_signature_lacks_a_written_reason")


def test_the_coverage_page_reports_the_snapshot_it_was_rendered_from(snapshot):
    text = (DOCS / "COVERAGE.md").read_text(encoding="utf-8")
    assert snapshot["as_of"] in text
    assert str(snapshot["totals"]["window_failures"]) in text
    if not snapshot["catch_all"]["hits"]:
        assert "**Zero.**" in text
