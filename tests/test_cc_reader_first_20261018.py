"""Actual old/current TS readers, real frozen producer fixtures, fake external effects."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "cc_client_compat_20261018"
ROOT = Path(os.environ.get("CC_READER_ROOT", Path(__file__).resolve().parents[1]))


@pytest.fixture(scope="module")
def model():
    result = subprocess.run(
        ["node", str(FIXTURES / "probe.cjs")],
        cwd=ROOT,
        env={**os.environ, "CC_READER_ROOT": str(ROOT)},
        capture_output=True,
        text=True,
        timeout=45,
        check=True,
    )
    return json.loads(result.stdout)


def test_actual_v2_unknown_daily_totals_never_render_as_zero_or_empty_success(model):
    assert "live runs 0" not in model["unavailable"]
    assert "None today" not in model["unavailable"]
    assert "UNAVAILABLE" in model["unavailable"]


def test_actual_full_aggregate_is_not_the_detail_sample(model):
    assert model["coordination"]["counts"]["waiting"] == 600
    assert "200 details shown" in model["coordination"]["coverageLabel"]


def test_actual_retained_outbox_error_cannot_stay_green(model):
    assert model["outbox"]["status"] == "STALE"
    assert "OK · 601 in window" not in model["retainedPage"]


def test_every_new_projection_read_explicitly_opts_in(model):
    paths = {
        p
        for p in model["requests"]
        if p.split("?")[0]
        in {"/api/v2/coordination/events", "/api/v2/coordination/outbox", "/api/v2/coordination/n8n-today"}
    }
    assert len(paths) >= 4
    assert all("projection_version=2" in path for path in paths)


def test_actual_v1_producers_remain_conservatively_readable(model):
    assert "live runs 0" not in model["legacyToday"]
    assert "Legacy receipt response" in model["legacyToday"]
    assert "Legacy sample: 200 returned rows only" in model["legacyCoordination"]["coverageLabel"]
    assert model["legacyOutbox"]["status"] == "PARTIAL"
    assert "LEGACY SAMPLE" in model["legacyOutbox"]["statusLabel"]


def test_no_claim_that_an_unchanged_old_client_was_fixed(model):
    assert "live runs 0" in model["old"]["unavailable"]
    assert "None today" in model["old"]["rejected"]
    assert model["old"]["coordination"]["counts"]["waiting"] == 200
    assert "OK · 601 in window" in model["old"]["retainedPage"]


def test_frozen_old_reader_and_actual_producer_fixture_integrity():
    identity = json.loads((FIXTURES / "identity.json").read_text())
    for path, expected in identity["files_sha256"].items():
        assert hashlib.sha256((FIXTURES / "old" / path).read_bytes()).hexdigest() == expected
    raw = gzip.decompress((FIXTURES / "observations.json.gz").read_bytes())
    assert hashlib.sha256(raw).hexdigest() == identity["observations_original_sha256"]
    assert len(raw) == identity["observations_original_bytes"]
