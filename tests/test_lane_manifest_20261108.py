"""LQ-20261107-1003 — one lane manifest (LaneManifest@v1), its generator, and the lane_registry.json shim.

Synthetic fixtures only (public repo): lane ids are made up, no holdings, no keys, no host paths.
The real-tree tests build the manifest from this tree's own config/ and prove the existing readers get identical
answers from the registry rendered out of the manifest.
"""
from __future__ import annotations

import copy
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import lane_manifest as lm  # noqa: E402

# ── synthetic sources ────────────────────────────────────────────────────────────────────────────────────────────


def _registry() -> dict:
    return {
        "schema": "LaneRegistry@v1",
        "authority": "READ_ONLY_ADVISORY",
        "note": "fixture",
        "lanes": [
            {"lane_id": "alpha-agenda", "owner": "research", "state": "ACTIVE",
             "scheduler": {"kind": "cron", "expression": "45 7 * * *",
                           "match": "scripts/alpha_agenda.py --apply --json >> logs/alpha.log 2>&1  # Phase 2"},
             "dispatch": {"mode": "live", "cron": ["45 7 * * *"], "tz": "America/New_York"},
             "expected_cadence_hours": 24, "output_signal": {"kind": "file_mtime", "path": "data/runtime/alpha.json"}},
            {"lane_id": "beta-collector", "owner": "platform", "state": "ACTIVE",
             "scheduler": {"kind": "cron", "expression": "5 16 * * 1-5", "match": "scripts/beta_collector.py"},
             "expected_cadence_hours": 24, "output_signal": {"kind": "db_max", "table": "beta", "column": "ts"},
             "note": "kept for the shim"},
            {"lane_id": "beta-classifier", "owner": "platform", "state": "RETIRED",
             "scheduler": {"kind": "cron", "expression": "35 6 * * 1-5",
                           "match": "$PROJ && $PY scripts/beta_classifier.py"},
             "expected_cadence_hours": 24, "output_signal": {"kind": "none"}, "retire_batch": "R9"},
            {"lane_id": "gamma-orphan", "owner": "platform", "state": "ACTIVE",
             "scheduler": {"kind": "cron", "expression": "0 3 * * *", "match": "scripts/gamma_orphan.py --apply"},
             "expected_cadence_hours": 24, "output_signal": {"kind": "json_key", "path": "data/runtime/g.json",
                                                              "key": "ts"}},
        ],
        "freshness_contracts": [],
    }


def _allowlist() -> dict:
    return {"schema": "N8nRunAllowlist@v1", "lanes": [
        {"lane_id": "alpha-agenda", "command": ["$PY", "scripts/alpha_agenda.py"], "market_gate": True,
         "output_signal": "data/runtime/alpha.json"},
        {"lane_id": "delta-unregistered", "command": ["$PY", "scripts/delta.py"], "market_gate": False,
         "output_signal": "data/runtime/delta.json"},
    ]}


def _contracts() -> dict:
    return {"contracts": [
        {"id": "alpha-agenda", "kind": "lane", "expected_output": {"rule": "empty_allowed"}},
        {"id": "beta-classifier", "kind": "lane", "expected_output": {"rule": "min_produced"}},
    ]}


ALPHA_LINE = ("45 7 * * * cd $PROJ && flock -n /tmp/a.lock env TRADEAI_EFFECT_CLAIM=alpha-agenda bash "
              "scripts/effect_claim_cron.sh alpha-agenda $PY scripts/alpha_agenda.py --apply --json >> logs/alpha.log 2>&1")
CHAINED_LINE = ("5 16 * * 1-5 cd $PROJ && flock -n /tmp/b.lock $PY scripts/beta_collector.py --apply && "
                "flock -n /tmp/c.lock $PY scripts/beta_classifier.py --apply")
UNDECLARED_LINE = "*/5 * * * * cd $PROJ && $PY scripts/nobody_owns_this.py"


def _manifest() -> dict:
    return lm.build_manifest(_registry(), _allowlist(), _contracts(), generated_at="2026-11-08T00:00:00+00:00",
                             sources={})


def _codes(findings, code):
    return [f for f in findings if f["code"] == code]


# ── schema ───────────────────────────────────────────────────────────────────────────────────────────────────────


def test_built_manifest_validates_and_carries_the_canonical_fields():
    man = _manifest()
    assert lm.validate(man) == []
    alpha = next(l for l in man["lanes"] if l["id"] == "alpha-agenda")
    assert alpha["command"] == {"root": "CURRENT", "argv": [lm.PY_TOKEN, "scripts/alpha_agenda.py"],
                                "source": "allowlist"}
    assert alpha["schedule"]["runner"] == "n8n" and alpha["schedule"]["cron"] == ["45 7 * * *"]
    assert alpha["market_hours_only"] is True
    assert alpha["output"]["empty_allowed"] is True and alpha["output"]["upstream_count_field"] is None
    assert alpha["identity"]["match"] == ["scripts/alpha_agenda.py --apply --json >> logs/alpha.log 2>&1"]


def test_retired_lane_must_be_disarmed():
    man = _manifest()
    retired = next(l for l in man["lanes"] if l["id"] == "beta-classifier")
    assert retired["armed"] is False and not lm.dispatchable(retired)
    retired["armed"] = True
    errs = lm.validate(man)
    assert any("armed" in e and "False" in e for e in errs), errs


def test_command_may_not_name_the_dev_tree_interpreter():
    man = _manifest()
    man["lanes"][0]["command"]["argv"][0] = "$PY"
    assert any("argv[0]" in e for e in lm.validate(man))


def test_duplicate_ids_and_unknown_keys_are_refused():
    man = _manifest()
    man["lanes"].append(copy.deepcopy(man["lanes"][0]))
    man["lanes"][1]["c1_flip"] = True
    errs = lm.validate(man)
    assert any("duplicate id" in e for e in errs)
    assert any("unexpected key 'c1_flip'" in e for e in errs)


# ── shim ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_registry_view_round_trips_with_key_order():
    reg = _registry()
    view = lm.registry_view(_manifest())
    assert view == reg
    assert json.dumps(view) == json.dumps(reg)  # order-sensitive


# ── attribution (both directions) ────────────────────────────────────────────────────────────────────────────────


def test_effect_claim_key_wins_without_any_substring():
    idx = lm.build_index(_manifest()["lanes"])
    assert lm.attribute_cron_line(ALPHA_LINE, idx)["lanes"] == ["alpha-agenda"]
    assert lm.attribute_cron_line(ALPHA_LINE, idx)["method"] == "effect_claim"


def test_old_free_text_marker_could_not_match_the_wrapper_line():
    """REBUILD-SPEC root defect 2: the registry marker carries a trailing comment no crontab line has."""
    raw = _registry()["lanes"][0]["scheduler"]["match"]
    assert raw not in ALPHA_LINE
    assert lm.strip_comment(raw) in ALPHA_LINE.replace("$PY scripts/alpha_agenda.py", "scripts/alpha_agenda.py") \
        or lm.attribute_cron_line(ALPHA_LINE, lm.build_index(_manifest()["lanes"]))["lanes"]


def test_chained_script_is_attributed_to_its_own_lane():
    idx = lm.build_index(_manifest()["lanes"])
    att = lm.attribute_cron_line(CHAINED_LINE, idx)
    assert att["lanes"] == ["beta-collector"]
    assert att["chained"] == [{"script": "scripts/beta_classifier.py", "lanes": ["beta-classifier"]}]


def test_reverse_enumeration_reports_a_line_no_lane_claims():
    f = lm.disagreements(_manifest(), allowlist=_allowlist(), contracts=_contracts(),
                         cron_lines=[ALPHA_LINE, CHAINED_LINE, UNDECLARED_LINE])
    und = _codes(f, "UNDECLARED_CRON_LINE")
    assert len(und) == 1 and und[0]["evidence"]["scripts"] == ["scripts/nobody_owns_this.py"]
    assert und[0]["evidence"]["line"].startswith("cron:") and "nobody" not in und[0]["evidence"]["line"]


def test_ambiguous_line_is_reported_not_guessed():
    reg = _registry()
    twin = copy.deepcopy(reg["lanes"][3])
    twin["lane_id"] = "gamma-orphan-2"
    reg["lanes"].append(twin)
    man = lm.build_manifest(reg, _allowlist(), _contracts(), generated_at="x", sources={})
    line = "0 3 * * * cd $PROJ && $PY scripts/gamma_orphan.py --apply"
    f = lm.disagreements(man, allowlist=_allowlist(), contracts=_contracts(), cron_lines=[line])
    amb = _codes(f, "AMBIGUOUS_CRON_LINE")
    assert len(amb) == 1 and amb[0]["evidence"]["lanes"] == ["gamma-orphan", "gamma-orphan-2"]


# ── disagreements ────────────────────────────────────────────────────────────────────────────────────────────────


def test_disagreement_classes_on_synthetic_sources():
    f = lm.disagreements(_manifest(), allowlist=_allowlist(), contracts=_contracts(),
                         cron_lines=[ALPHA_LINE, CHAINED_LINE],
                         n8n_active=[{"id": "w1", "name": "tradeai-dispatcher"}, {"id": "w2", "name": "stray"}],
                         ledger={"live_runs": {"beta-classifier": {"count": 2, "last": "2026-11-07"},
                                               "ghost": {"count": 1, "last": "2026-11-07"}}})
    by = lm.counts_by_code(f)
    assert [x["lane_id"] for x in _codes(f, "N8N_LIVE_WITH_CRON_TWIN")] == ["alpha-agenda"]
    assert [x["lane_id"] for x in _codes(f, "RETIRED_STILL_ARMED")] == ["beta-classifier"]
    assert [x["lane_id"] for x in _codes(f, "ACTIVE_CRON_NO_LINE")] == ["gamma-orphan"]
    assert [x["lane_id"] for x in _codes(f, "ALLOWLIST_NOT_IN_REGISTRY")] == ["delta-unregistered"]
    assert [x["lane_id"] for x in _codes(f, "RETIRED_BUT_CONTRACT")] == ["beta-classifier"]
    assert [x["lane_id"] for x in _codes(f, "LIVE_RUNS_FOR_UNARMED_LANE")] == ["beta-classifier"]
    assert [x["lane_id"] for x in _codes(f, "LEDGER_LANE_UNDECLARED")] == ["ghost"]
    assert [x["lane_id"] for x in _codes(f, "N8N_LIVE_NO_RECENT_RUN")] == ["alpha-agenda"]
    assert [x["evidence"]["workflow_name"] for x in _codes(f, "N8N_ACTIVE_WORKFLOW_UNDECLARED")] == ["stray"]
    assert by.get("DEV_TREE_INTERPRETER") == 2
    assert "N8N_WORKFLOW_NOT_ACTIVE" not in by  # the dispatcher is up


def test_dispatcher_down_marks_every_live_lane():
    f = lm.disagreements(_manifest(), allowlist=_allowlist(), contracts=_contracts(),
                         n8n_active=[{"id": "w2", "name": "stray"}])
    assert [x["lane_id"] for x in _codes(f, "N8N_WORKFLOW_NOT_ACTIVE")] == ["alpha-agenda"]


def test_a_source_not_given_is_not_measured_not_clean():
    f = lm.disagreements(_manifest(), allowlist=_allowlist(), contracts=_contracts())
    assert not _codes(f, "ACTIVE_CRON_NO_LINE") and not _codes(f, "UNDECLARED_CRON_LINE")


# ── real tree: readers get identical answers ─────────────────────────────────────────────────────────────────────


def _real():
    load = lambda rel: json.loads((ROOT / rel).read_text(encoding="utf-8"))  # noqa: E731
    return (load("config/lane_registry.json"), load("config/n8n_run_allowlist.json"),
            load("config/n8n_health_contracts.json"))


@pytest.fixture(scope="module")
def real_manifest():
    reg, allow, con = _real()
    return reg, lm.build_manifest(reg, allow, con, generated_at="t", sources={})


def test_real_manifest_validates(real_manifest):
    _, man = real_manifest
    assert lm.validate(man) == []
    assert all(not l["armed"] for l in man["lanes"] if l["state"] != "ACTIVE")


def test_real_registry_view_is_identical(real_manifest):
    reg, man = real_manifest
    assert json.dumps(lm.registry_view(man)) == json.dumps(reg)


def test_existing_readers_get_identical_answers(real_manifest, tmp_path):
    from scripts.lib import lane_registry as lr
    import scripts.check_registry_runtime_truth as rrt

    reg, man = real_manifest
    rendered = tmp_path / "config" / "lane_registry.json"
    rendered.parent.mkdir(parents=True)
    rendered.write_text(lm.render_registry(man), encoding="utf-8")
    for name in ("n8n_run_allowlist.json", "n8n_health_contracts.json", "n8n_fabric_processes.json"):
        src = ROOT / "config" / name
        if src.exists():
            shutil.copy(src, tmp_path / "config" / name)

    a, b = lr.load_registry(), lr.load_registry(rendered)
    assert json.dumps(a) == json.dumps(b)
    assert lr.validate_registry(a) == lr.validate_registry(b)
    for ra, rb in zip(a["lanes"], b["lanes"]):
        assert lr.scheduler_label(ra.get("scheduler")) == lr.scheduler_label(rb.get("scheduler"))
        assert lr.lane_scheduler_text(ra) == lr.lane_scheduler_text(rb)
        assert lr.format_lane_line(ra) == lr.format_lane_line(rb)
    assert lr.render_lane_table(a["lanes"]) == lr.render_lane_table(b["lanes"])
    da, db = rrt.declared(ROOT), rrt.declared(tmp_path)
    assert json.dumps(da["rows"]) == json.dumps(db["rows"])


def test_generator_cli_dry_run_writes_nothing(tmp_path, capsys):
    from scripts.ops import build_lane_manifest as blm

    rc = blm.main(["--no-crontab", "--no-n8n", "--now", "2026-11-08T00:00:00+00:00"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["mode"].startswith("dry-run") and out["wrote"] == []
    assert out["registry_view_identical"] is True and out["schema_errors"] == 0
    assert out["not_measured"] == ["crontab", "n8n_db"]


def test_generator_check_detects_drift(tmp_path, capsys):
    from scripts.ops import build_lane_manifest as blm

    path = tmp_path / "m.json"
    assert blm.main(["--no-crontab", "--no-n8n", "--out", str(path)]) == 0
    assert blm.main(["--check", str(path)]) == 0
    man = json.loads(path.read_text())
    man["lanes"][0]["owner"] = "someone-else"
    path.write_text(json.dumps(man))
    capsys.readouterr()
    assert blm.main(["--check", str(path)]) == 1
    assert man["lanes"][0]["id"] in json.loads(capsys.readouterr().out)["rows_changed"]
