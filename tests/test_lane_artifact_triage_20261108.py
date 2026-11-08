"""LQ-20261107-1009 — scripts/ops/lane_artifact_triage.py: every remediation-catalogue, migration-tranche and
writer-restoration item maps to a manifest lane or is moved (never deleted) to config/archive/.

Synthetic lanes only (no holdings, no keys, no host paths), plus two guards on the real repo: every item left in the
three live files maps to a manifest lane, and nothing under scripts/ reads config/archive/ (the archive tripwire).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ops import lane_artifact_triage as T  # noqa: E402

NOW = "2026-11-08T18:00:00+00:00"
STATES = {"run-a": "ACTIVE", "held-b": "PAUSED", "dead-c": "RETIRED", "never-d": "NEVER_SCHEDULED"}


def _registry() -> dict:
    return {"schema": "LaneRegistry@v1", "lanes": [
        {"lane_id": k, "owner": "platform", "state": v, "expected_cadence_hours": 24,
         "scheduler": {"kind": "cron", "expression": "0 1 * * *", "match": f"scripts/{k.replace('-', '_')}.py"},
         "output_signal": {"kind": "none"}} for k, v in STATES.items()],
            "pending_changes": {"draft-x": {"operative": False, "lane_ids": ["pending-f"]},
                                "live-y": {"operative": True, "lane_ids": ["ghost-e"]}}}


def _entry(lane: str, sev: str = "Low", auto: bool = False) -> dict:
    return {"lane_id": lane, "severity": sev, "default_action": "suggest_only",
            "actions": [{"action_id": "rerun_dry_then_live", "auto": auto}]}


CATALOGUE = {"schema": "N8nRemediationCatalogue@v1", "approvals": [{"scope": "x"}],
             "summary": {"lanes": 5},
             "lanes": [_entry("run-a", "High", True), _entry("held-b"), _entry("dead-c", "Critical", True),
                       _entry("never-d"), _entry("ghost-e")]}
TRANCHES = {"schema": "N8nMigrationTranches@v1", "lane_count": 5, "in_scope_lane_count": 4, "retained_lane_count": 1,
            "tranches": {"N1": {"title": "t1", "lanes": [{"lane_id": "run-a"}, {"lane_id": "dead-c"},
                                                          {"lane_id": "ghost-e"}]},
                         "N6": {"title": "kept", "status": "RETAINED_BY_POLICY",
                                "lanes": [{"lane_id": "held-b"}, {"lane_id": "never-d"}]}}}
WRITERS = {"schema": "N8nWriterRestoration@v1", "writers": [
    {"key": "w-run", "lane_id": "run-a"}, {"key": "w-dead", "lane_id": "dead-c"},
    {"key": "w-never", "lane_id": "never-d"}, {"key": "w-ghost", "lane_id": "ghost-e"},
    {"key": "w-pending", "lane_id": "pending-f"}]}


def _tree(tmp: Path) -> Path:
    root = tmp / "tree"
    (root / "config").mkdir(parents=True)
    docs = {"lane_registry.json": _registry(), "n8n_run_allowlist.json": {"lanes": []},
            "n8n_health_contracts.json": {"contracts": []}}
    for name, doc in docs.items():
        (root / "config" / name).write_text(json.dumps(doc), encoding="utf-8")
    for rel, doc in ((T.CATALOGUE, CATALOGUE), (T.TRANCHES, TRANCHES), (T.WRITERS, WRITERS)):
        (root / rel).write_text(T.render(doc, T.FILES[rel][2]), encoding="utf-8")
    return root


def _run(root: Path, capsys, *extra: str) -> dict:
    assert T.main(["--root", str(root), "--now", NOW, "--stamp", "t1", *extra]) == 0
    return json.loads(capsys.readouterr().out)


def _verdicts(rep: dict, kind: str) -> dict:
    return {r["item"]: r["verdict"] for r in rep["rows"] if r["kind"] == kind}


def test_catalogue_maps_only_lanes_that_can_run(tmp_path, capsys):
    rep = _run(_tree(tmp_path), capsys)
    assert _verdicts(rep, "remediation_catalogue") == {
        "run-a": "MAPPED", "held-b": "MAPPED", "dead-c": "ARCHIVE", "never-d": "ARCHIVE", "ghost-e": "ARCHIVE"}
    assert _verdicts(rep, "migration_tranche") == {
        "N1/run-a": "MAPPED", "N1/dead-c": "ARCHIVE", "N1/ghost-e": "ARCHIVE", "N6/held-b": "MAPPED",
        "N6/never-d": "ARCHIVE"}


def test_writer_restoration_keeps_a_retired_lane_and_archives_only_a_lane_the_manifest_lacks(tmp_path, capsys):
    rep = _run(_tree(tmp_path), capsys)
    # pending-f has no manifest lane but a NON-operative pending proposal names it: HELD (kept), never archived alone.
    # ghost-e is named only by an operative proposal, which is not a draft holding it: archived.
    assert _verdicts(rep, "writer_restoration") == {
        "w-run": "MAPPED", "w-dead": "MAPPED", "w-never": "MAPPED", "w-ghost": "ARCHIVE", "w-pending": "HELD"}


def test_a_held_writer_stays_in_the_live_file_after_apply(tmp_path, capsys):
    root = _tree(tmp_path)
    _run(root, capsys, "--apply")
    keys = [w["key"] for w in json.loads((root / T.WRITERS).read_text())["writers"]]
    assert keys == ["w-run", "w-dead", "w-never", "w-pending"]


def test_dry_run_writes_nothing(tmp_path, capsys):
    root = _tree(tmp_path)
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    rep = _run(root, capsys)
    assert rep["mode"] == "dry-run" and rep["wrote"] == []
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before
    assert not (root / "config" / "archive").exists()


def test_apply_moves_never_deletes(tmp_path, capsys):
    root = _tree(tmp_path)
    rep = _run(root, capsys, "--apply")
    arch = root / "config" / "archive" / "t1"
    assert (arch / "README.md").is_file() and "Nothing may read this directory" in (arch / "README.md").read_text()
    for rel, original, key in ((T.CATALOGUE, CATALOGUE["lanes"], "lanes"), (T.WRITERS, WRITERS["writers"], "writers")):
        live = json.loads((root / rel).read_text())[key]
        moved = [m["entry"] for m in json.loads((arch / f"{rel.stem}.archived.json").read_text())["items"]]
        assert sorted(map(json.dumps, live + moved)) == sorted(map(json.dumps, original))  # a partition, no loss
    assert sorted(rep["wrote"]) == sorted([
        "config/archive/t1/n8n_remediation_catalogue.archived.json", str(T.CATALOGUE),
        "config/archive/t1/n8n_migration_tranches.archived.json", str(T.TRANCHES),
        "config/archive/t1/n8n_writer_restoration.archived.json", str(T.WRITERS), "config/archive/t1/README.md"])


def test_apply_recomputes_catalogue_summary_and_tranche_counts(tmp_path, capsys):
    root = _tree(tmp_path)
    _run(root, capsys, "--apply")
    cat = json.loads((root / T.CATALOGUE).read_text())
    assert cat["summary"] == {"lanes": 2, "actions": 2, "lanes_with_auto_rerun": 1, "lanes_suggest_only": 1,
                              "by_severity": {"High": 1, "Low": 1}}
    assert cat["approvals"] == CATALOGUE["approvals"]
    tr = json.loads((root / T.TRANCHES).read_text())
    assert (tr["lane_count"], tr["in_scope_lane_count"], tr["retained_lane_count"]) == (2, 1, 1)


def test_a_second_apply_finds_nothing_left_to_archive(tmp_path, capsys):
    root = _tree(tmp_path)
    _run(root, capsys, "--apply")
    rep = _run(root, capsys, "--stamp", "t2", "--apply")
    assert all(r["verdict"] in {"MAPPED", "HELD"} for r in rep["rows"]) and rep["wrote"] == []


def test_apply_keeps_each_file_in_its_own_format(tmp_path, capsys):
    root = _tree(tmp_path)
    _run(root, capsys, "--apply")
    assert (root / T.WRITERS).read_text().startswith('{\n  "schema"')
    assert (root / T.CATALOGUE).read_text().startswith('{\n "schema"')


# ── guards on the real repo ──────────────────────────────────────────────────────────────────────────────────────


def test_every_live_item_in_the_repo_maps_to_a_manifest_lane(capsys):
    """Fails before LQ-1009's --apply (20 catalogue + 11 tranche items with no lane they can act on); passes after.
    The only items left without a manifest lane are the four W8 writer drafts the non-operative
    w8-writer-restoration-20261024 proposal still names (HELD for the operator, never archived alone)."""
    rep = _run(ROOT, capsys)
    archive = [(r["kind"], r["item"], r["manifest_state"]) for r in rep["rows"] if r["verdict"] == "ARCHIVE"]
    assert archive == []
    held = sorted(r["item"] for r in rep["rows"] if r["verdict"] == "HELD")
    assert held == ["advisory-opinion-session", "generate-dual-opinion-advisory", "portfolio-correlation",
                    "risk-management-refresh"]


def test_archive_tripwire_nothing_under_scripts_reads_config_archive():
    pat = re.compile(r"config[/\\\"' ,()]+archive")
    offenders = [str(p.relative_to(ROOT)) for p in (ROOT / "scripts").rglob("*")
                 if p.is_file() and p.suffix in {".py", ".sh", ".mjs", ".js", ".json"}
                 and p.name != "lane_artifact_triage.py"
                 and pat.search(p.read_text(encoding="utf-8", errors="replace"))]
    assert offenders == []


def test_self_heal_fixer_installs_disarmed():
    """LQ-1009 part 1 (operator decision): the fixer is installed DISARMED. The host lane that could --apply is not
    armed in the manifest, the n8n lane runs the dry cycle only (no live_arg), and --apply needs a guard grant."""
    manifest = T.build_manifest(ROOT, NOW)
    rows = {lane["id"]: lane for lane in manifest["lanes"]}
    live, shadow = rows["self-heal-fixer"], rows["self-heal-fixer-shadow"]
    assert live["armed"] is False and live["state"] != "ACTIVE"
    assert shadow["state"] == "ACTIVE" and shadow["schedule"]["mode"] == "dry_run"
    allow = {e["lane_id"]: e for e in json.loads((ROOT / "config/n8n_run_allowlist.json").read_text())["lanes"]}
    assert allow["self-heal-fixer-shadow"]["live_arg"] is None and "--apply" not in allow["self-heal-fixer-shadow"]["command"]
    arming = json.loads((ROOT / "config/self_heal_fixer.json").read_text())["arming"]
    assert arming["grant_tier"] == "git-push" and arming["grant_reason_token"] == "self-heal-fixer"
