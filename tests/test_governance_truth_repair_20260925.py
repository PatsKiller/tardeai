"""Governance truth repair (2026-09-25).

Pins three repairs:
* AGENTS.md policy state — PROPOSED on main only while a separate operator
  ratification is pending; one version-history row per version.
* Agent gate status is read from the measurement store at render time and is
  NOT_YET_MEASURED / STALE when that store is absent or old — never a count
  frozen into the maturity catalog.
* The maturity catalog loader refuses a static gate count in catalog prose.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from scripts import check_agents_policy_state as ps  # noqa: E402
from agent_runtime import gate_status as gs  # noqa: E402
from agent_runtime.monitoring import (  # noqa: E402
    MonitoringContractError,
    load_maturity_catalog,
)

HEADER = """# AGENTS.md
```
Policy-Version:      {v}
Status:              {status}
Effective-Date:      {eff}
```
"""


def _doc(v: str, status: str, eff: str, rows: list[str]) -> str:
    table = "| Version | Date | Status | Class | Change | Approval |\n|---|---|---|---|---|---|\n"
    return HEADER.format(v=v, status=status, eff=eff) + "\n" + table + "\n".join(rows) + "\n"


RIDES_ROW = "| 1.2.7 | 2026-09-24 | PROPOSED (ACTIVE on merge) | PATCH | fix | Rides `APPROVE_AGENTS_POLICY_1_2_0` |"
ACTIVE_ROW = "| 1.2.7 | 2026-09-24 | ACTIVE — merged PR #1227 | PATCH | fix | Rides `APPROVE_AGENTS_POLICY_1_2_0` |"
NEW_TOKEN_ROW = (
    "| 1.3.0 | 2026-09-25 | PROPOSED | MINOR | authority change | "
    "**PENDING** — `APPROVE_AGENTS_POLICY_1_3_0 <pr> <sha>` |"
)


def test_proposed_patch_that_rides_prior_approval_fails_on_main():
    errs = ps.check(_doc("1.2.7", "PROPOSED", "PENDING", [RIDES_ROW]), on_main=True)
    assert any("PROPOSED on main" in e for e in errs)


def test_proposed_patch_is_fine_on_a_branch():
    assert ps.check(_doc("1.2.7", "PROPOSED", "PENDING", [RIDES_ROW]), on_main=False) == []


def test_active_with_merge_date_passes_on_main():
    assert ps.check(_doc("1.2.7", "ACTIVE", "2026-09-24T21:31:15-04:00", [ACTIVE_ROW]), on_main=True) == []


def test_proposed_awaiting_new_operator_token_is_allowed_on_main():
    assert ps.check(_doc("1.3.0", "PROPOSED", "PENDING", [NEW_TOKEN_ROW]), on_main=True) == []


def test_duplicate_version_rows_fail():
    errs = ps.check(_doc("1.2.7", "ACTIVE", "2026-09-24", [ACTIVE_ROW, ACTIVE_ROW]), on_main=True)
    assert any("2 history rows" in e for e in errs)


def test_header_and_row_status_must_agree():
    errs = ps.check(_doc("1.2.7", "ACTIVE", "2026-09-24", [RIDES_ROW]), on_main=True)
    assert any("header says ACTIVE" in e for e in errs)


def test_active_without_effective_date_fails():
    errs = ps.check(_doc("1.2.7", "ACTIVE", "PENDING", [ACTIVE_ROW]), on_main=False)
    assert any("Effective-Date PENDING" in e for e in errs)


# ── gate status: read from the store, never frozen ────────────────────────────


def _store(tmp_path: Path, measured_at: datetime, statuses: list[str]) -> Path:
    p = tmp_path / "data" / "cio" / "agent_gate_measurements.json"
    p.parent.mkdir(parents=True)
    gates = {f"g{i}": {"status": s} for i, s in enumerate(statuses)}
    p.write_text(
        json.dumps(
            {
                "schema": "AgentGateMeasurement@v1",
                "measured_at": measured_at.isoformat(),
                "agents": {"alex": {"gates": gates}},
            }
        )
    )
    return p


NOW = datetime(2026, 9, 25, 13, 0, tzinfo=timezone.utc)


def test_absent_store_is_not_yet_measured(tmp_path):
    out = gs.gate_status(tmp_path, "alex", now=NOW, served_sha="abc1234")
    assert out["status"] == "NOT_YET_MEASURED" and out["passing"] is None and out["promotable"] is False


def test_fresh_store_reports_counts_with_provenance(tmp_path):
    _store(tmp_path, NOW - timedelta(hours=1), ["FAIL"] * 4 + ["NOT_YET_MEASURED"] * 8)
    out = gs.gate_status(tmp_path, "alex", now=NOW, served_sha="1c60ecb42")
    assert out["status"] == "MEASURED"
    assert (out["passing"], out["failing"], out["not_measured"], out["denominator"]) == (0, 4, 8, 12)
    assert (
        out["served_release_sha"] == "1c60ecb42"
        and out["as_of"]
        and out["source"].endswith("agent_gate_measurements.json")
    )
    assert out["promotable"] is False


def test_old_store_is_stale_not_current(tmp_path):
    _store(tmp_path, NOW - timedelta(hours=30), ["PASS"] * 12)
    out = gs.gate_status(tmp_path, "alex", now=NOW, served_sha="x", max_age_hours=6)
    assert out["status"] == "STALE" and out["promotable"] is False


def test_agent_without_rows_is_not_yet_measured(tmp_path):
    _store(tmp_path, NOW, ["PASS"])
    assert gs.gate_status(tmp_path, "maria", now=NOW, served_sha="x")["status"] == "NOT_YET_MEASURED"


def test_served_release_sha_from_release_dir_name(tmp_path):
    rel = tmp_path / "1c60ecb42-main-exact-phase2-20260925-081649"
    rel.mkdir()
    link = tmp_path / "CURRENT"
    link.symlink_to(rel)
    assert gs.served_release_sha(link) == "1c60ecb42"


# ── catalog drift gate ────────────────────────────────────────────────────────


def test_repo_catalog_carries_no_static_gate_count():
    text = (ROOT / "config" / "agent_maturity_catalog.json").read_text(encoding="utf-8")
    assert "gates passing" not in text and "11/12" not in text
    load_maturity_catalog(ROOT / "config" / "agent_maturity_catalog.json")


def test_loader_refuses_a_static_gate_count(tmp_path):
    doc = json.loads((ROOT / "config" / "agent_maturity_catalog.json").read_text(encoding="utf-8"))
    doc["agents"]["alex"]["acceptance_evidence"].append("11/12 gates passing (0 not yet measured)")
    p = tmp_path / "cat.json"
    p.write_text(json.dumps(doc))
    with pytest.raises(MonitoringContractError, match="static gate count"):
        load_maturity_catalog(p)
