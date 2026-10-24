"""WP-21: shared projection reads do not give a shadow lane broker capabilities.

All sessions, rows and clocks are fixtures. Static analysis parses source only.
"""

from __future__ import annotations

import builtins
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for path in (str(ROOT), str(ROOT / "scripts")):
    if path not in sys.path:
        sys.path.insert(0, path)

from scripts import audit_lane_transitive_capabilities as cap  # noqa: E402
from scripts.lib.data_broker import catalyst_record as facade  # noqa: E402
from scripts.lib.data_broker import catalyst_record_readonly as core  # noqa: E402
from scripts.lib.data_broker import watch_directives_readonly as directives  # noqa: E402
from scripts.lib.data_broker import watch_intelligence as watch  # noqa: E402

LANE = "cio-prospect-shadow"
NOW = datetime(2026, 10, 23, 14, 0, tzinfo=timezone.utc)


def _row(path, key, value):
    return next(r for r in json.loads((ROOT / path).read_text())[key] if r.get("lane_id", r.get("id")) == value)


def test_actual_shadow_lane_has_no_forbidden_transitive_capability(tmp_path):
    lane = _row("config/n8n_run_allowlist.json", "lanes", LANE)
    allowlist = tmp_path / "allowlist.json"
    allowlist.write_text(json.dumps({"lanes": [lane]}))
    result = cap.audit(allowlist)[LANE]
    assert not result.get("error")
    assert not set(result["capabilities"]).intersection(cap.FORBIDDEN), result
    assert LANE not in cap.load_baseline(), "the refactor must not widen the DD01 exception baseline"


def test_registered_catalyst_facade_reexports_one_implementation():
    assert facade.get_catalyst_records_bulk is core.get_catalyst_records_bulk
    assert facade.normalize_catalyst_row is core.normalize_catalyst_row
    assert facade.not_news_sql is core.not_news_sql


def test_bulk_query_preserves_identity_deduplication_and_factual_verification(monkeypatch):
    original = builtins.__import__

    def no_owned_connection(name, *args, **kwargs):
        if name.split(".")[0] in {"db_adapter", "psycopg2", "psycopg", "schwab", "alpaca", "moomoo"}:
            pytest.fail(f"read core tried to own a connection or broker: {name}")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_owned_connection)
    row = {
        "id": 8,
        "symbol": "READ",
        "subject_guid": "fixture-guid",
        "catalyst_type": "earnings",
        "headline": "Fixture earnings beat",
        "confidence": Decimal("0.7"),
        "source": "fixture",
        "source_url": "https://example.invalid/fixture",
        "at": NOW,
    }
    seen = []

    def query(sql, params):
        seen.append((sql, params))
        return [dict(row), dict(row)]

    result = core.get_catalyst_records_bulk(query, days=5, per_symbol=2)
    assert len(result["READ"]) == 1
    assert result["READ"][0]["id"] == 8
    assert result["READ"][0]["subject_guid"] == "fixture-guid"
    assert result["READ"][0]["verification_basis"] == "LEGACY_CONFIDENCE_THRESHOLD"
    assert result["READ"][0]["factual_verification_status"] == "UNKNOWN"
    assert seen[0][1] == (5, 6)
    assert "FROM catalyst_events" in seen[0][0]
    json.dumps(result)


def test_directive_facade_and_core_share_sql_and_results():
    assert watch.ACTIVE_TICKER_DIRECTIVES_SQL == directives.ACTIVE_TICKER_DIRECTIVES_SQL
    seen = []

    def query(sql):
        seen.append(sql)
        return [{"symbol": "OLD", "created_at": 1}, {"symbol": "NEW", "created_at": 2}]

    assert directives.active_ticker_directives(db_query=query) == watch.active_ticker_directives(db_query=query)
    assert all(sql == directives.ACTIVE_TICKER_DIRECTIVES_SQL for sql in seen)


def test_directive_core_preserves_strict_and_fail_soft_boundaries():
    def unavailable(sql):
        raise RuntimeError("fixture unavailable")

    assert directives.active_ticker_directives(db_query=unavailable) == []
    with pytest.raises(RuntimeError, match="fixture unavailable"):
        directives.active_ticker_directives(db_query=unavailable, strict=True)
    with pytest.raises(TypeError, match="injected read-only"):
        directives.active_ticker_directives(db_query=None)


def test_restored_lane_is_shadow_only_and_preserves_historical_owner_review():
    lane = _row("config/lane_registry.json", "lanes", LANE)
    run = _row("config/n8n_run_allowlist.json", "lanes", LANE)
    contract = _row("config/n8n_health_contracts.json", "contracts", LANE)
    assert lane["scheduler"]["kind"] == "n8n" and lane["scheduler"]["stage"] == "shadow"
    assert lane["dispatch"]["mode"] == "dry_run"
    assert run["live_arg"] is None and run["dry_run_arg"] == ["--dry-run"]
    assert run["command"] == ["$PY", "scripts/cio_prospect_shadow_build.py", "--with-db"]
    assert contract["status"] == contract["review"]["status"] == "REVIEWED"
    assert contract["review"]["reviewed_on"] == "2026-10-22"
    assert "#1953" in contract["review"]["reference"]


def test_new_regression_is_in_a_canonical_ci_gate():
    from scripts.lib.ci_gates import render

    path = ROOT / "config/ci_gates/cio_prospect_shadow_readonly_20261023.json"
    record = json.loads(path.read_text())
    assert record["files"] == ["tests/test_cio_prospect_shadow_readonly_20261023.py"]
    assert path.read_text() == render(record)
