"""ANCHOR: CONFLICT_RULEBOOK_VIEW_20261025 — GET /api/v3/conflicts/rulebook (the resolution matrix on the Command Center).

Thresholds come only from the rulebook and the IPS; plain words come from config/conflict_rules_explained.json; coverage is
re-checked against this tree on every read; the read writes nothing and never accepts a POST.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from scripts.lib.conflicts.api import handle
from scripts.lib.conflicts import rulebook_view
from tests.test_conflict_ledger import NOW, SUBJECT, conflict, ledger

REPO = Path(__file__).resolve().parent.parent
RULEBOOK = json.loads((REPO / "config/conflict_rulebook.json").read_text())
EXPLAINED = json.loads((REPO / "config/conflict_rules_explained.json").read_text())
IPS = json.loads((REPO / "config/investment_policy_statement.json").read_text())["constraints"]["concentration_policy"]


def _tree(tmp_path):
    files = sorted(
        {ref["path"] for rule in EXPLAINED["rules"] for ref in rule["code"] + rule["tests"]}
        | {
            "config/conflict_rulebook.json",
            "config/conflict_rules_explained.json",
            "config/investment_policy_statement.json",
        }
    )
    for rel in files:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / rel, tmp_path / rel)
    return tmp_path


def test_read_only_route_shape_and_no_writes(tmp_path):
    status, view = handle("/api/v3/conflicts/rulebook", "GET", root=tmp_path)
    assert status == 200 and view["schema"] == "ConflictRulebookView@v1"
    assert list(tmp_path.iterdir()) == []  # the read never creates a ledger
    assert view["live"]["gap"] == {"reason": "conflict ledger not yet produced"} and view["live"]["open_total"] is None
    for method in ("POST", "PUT", "DELETE"):
        assert handle("/api/v3/conflicts/rulebook", method, {}, root=tmp_path) == (405, {"error": "METHOD_NOT_ALLOWED"})


def test_status_banner_is_the_rulebook_not_a_copy():
    view = rulebook_view.build(root=Path("/nonexistent-conflict-root"))
    book = view["rulebook"]
    assert (book["status"], book["approval"], book["live_enabled"], book["matrix_sha256"]) == (
        RULEBOOK["status"],
        RULEBOOK["approval"],
        bool(RULEBOOK["live_enabled"]),
        RULEBOOK["matrix_sha256"],
    )
    assert EXPLAINED["matrix_sha256"] == RULEBOOK["matrix_sha256"] and view["text_gap"] is None


def test_matrix_rules_are_all_present_and_implemented_in_this_tree():
    view = rulebook_view.build(root=Path("/nonexistent-conflict-root"))
    ids = [rule["id"] for rule in view["rules"]]
    required = ["R1"] + [f"R{n}" for n in range(3, 17)] + ["R7b", "EXPIRED", "TIMESTAMPS"]
    assert set(required) <= set(ids) and len(ids) == len(set(ids))
    for rule in view["rules"]:
        assert rule["means"] and rule["example"] and rule["clears"] and rule["owner"] and rule["exact_text"]
        assert rule["coverage"]["status"] == "IMPLEMENTED", rule["id"]
        assert all(ref["found"] for ref in rule["coverage"]["code"]), rule["id"]
        assert all(ref["found"] for ref in rule["coverage"]["tests"]), rule["id"]
    assert view["coverage_summary"] == {"implemented": len(ids), "missing": 0, "total": len(ids)}


def test_removed_test_or_code_marker_shows_missing_not_a_stale_claim(tmp_path):
    root = _tree(tmp_path)
    target = root / "tests/test_conflict_rulebook.py"
    target.write_text(target.read_text().replace("def test_wash_loss_window_applies", "def renamed_wash"))
    security = root / "scripts/lib/conflicts/profiles/security.py"
    security.write_text(security.read_text().replace('"Identity unresolved — every action is blocked"', '"renamed"'))
    rules = {rule["id"]: rule for rule in rulebook_view.build(root, root=tmp_path / "ledger")["rules"]}
    assert rules["R9"]["coverage"]["status"] == "MISSING"
    assert rules["R16"]["coverage"]["status"] == "MISSING"
    assert rules["R1"]["coverage"]["status"] == "IMPLEMENTED"


def test_thresholds_and_limits_are_read_from_their_one_source():
    view = rulebook_view.build(root=Path("/nonexistent-conflict-root"))
    rows = {row["key"]: row for row in view["concentration"]["rows"]}
    assert set(rows) == set(IPS["limits_pct"])
    for key, limit in IPS["limits_pct"].items():
        assert rows[key]["limit_pct"] == limit
        assert rows[key]["near_limit_pct"] == round(limit * IPS["near_limit_fraction"], 4)
        assert key in EXPLAINED["concentration_labels"]
    assert view["thresholds"]["hysteresis"] == RULEBOOK["hysteresis"]
    assert view["thresholds"]["supersede_days"] == RULEBOOK["security_stance"]["supersede_days"]
    held = view["action_scale"]["held"]
    assert [step["primary"] for step in held] == sorted(
        RULEBOOK["security_stance"]["ordinal"], key=RULEBOOK["security_stance"]["ordinal"].get
    )
    # The explanation file carries words only: no IPS percentage appears as a config value there.
    assert "limits_pct" not in json.dumps(EXPLAINED) and "near_limit_fraction" not in json.dumps(EXPLAINED)


def test_every_never_auto_id_has_plain_words():
    view = rulebook_view.build(root=Path("/nonexistent-conflict-root"))
    assert [row["id"] for row in view["never_auto"]] == RULEBOOK["never_auto"]
    assert all(row["label"] for row in view["never_auto"])


def test_live_counts_are_active_records_by_kind(tmp_path):
    st = ledger(tmp_path)
    st.reconcile(SUBJECT, [conflict(kind="NEEDS_OPERATOR", never_auto=True)], at=NOW, apply=True)
    live = rulebook_view.build(root=tmp_path)["live"]
    assert live["gap"] is None and live["by_kind"] == {"NEEDS_OPERATOR": 1} and live["open_total"] == 1
