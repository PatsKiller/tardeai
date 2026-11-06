"""n8n 0.1h: the upgrade rehearsal's decisions and the version pin, hermetic (no docker)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from scripts import n8n_upgrade_rehearsal as r

PIN = {"n8n_image": "n8nio/n8n:2.43.0", "postgres_image": "postgres:16.15-alpine"}
MAN = {"dump_workflow_count": 3, "credentials_count": 1}
GOOD = {"healthy": True, "log_errors": 0, "workflow_count": 3, "key_word": "KEY_OK", "cleaned": True}


def _v(image="n8nio/n8n:2.43.0", target=False, **over):
    return r.verdict(pin=PIN, image=image, target=target, facts={**GOOD, **over}, manifest=MAN, expect_credentials=True)


def test_good_rehearsal_passes():
    v = _v()
    assert v["state"] == "PASSED" and v["kind"] == "pin_rehearsal"


@pytest.mark.parametrize("over,failed", [
    ({"healthy": False}, "boots"), ({"log_errors": 2}, "no_migration_error"), ({"log_errors": None}, "no_migration_error"),
    ({"workflow_count": 2}, "workflows_intact"), ({"workflow_count": None}, "workflows_intact"),
    ({"key_word": "KEY_BAD"}, "key_decrypts"), ({"key_word": "NO_CIPHERTEXT"}, "key_decrypts"),
    ({"cleaned": False}, "cleaned_up"),
])
def test_each_failure_is_named(over, failed):
    v = _v(**over)
    assert v["state"] == "FAILED" and failed in v["failures"]


def test_other_image_needs_to_be_a_named_target():
    assert "image_matches_pin" in _v(image="n8nio/n8n:2.99.0")["failures"]
    v = _v(image="n8nio/n8n:2.99.0", target=True)
    assert v["state"] == "PASSED" and v["kind"] == "upgrade_to_target"


def test_missing_facts_never_pass():
    v = r.verdict(pin=PIN, image=PIN["n8n_image"], target=False, facts={}, manifest=MAN, expect_credentials=True)
    assert v["state"] == "FAILED"


def test_no_bundle_writes_a_failed_receipt(tmp_path):
    doc = r.apply(PIN["n8n_image"], False, tmp_path)
    assert doc["failures"] == ["no_bundle_found"]
    assert json.loads((tmp_path / r.RECEIPT_NAME).read_text(encoding="utf-8"))["state"] == "FAILED"


def test_rehearsal_network_is_internal_and_pin_is_exact():
    src = Path(r.__file__).read_text(encoding="utf-8")
    assert '"--internal"' in src
    pin = r.load_pin()
    assert re.fullmatch(r"n8nio/n8n:\d+\.\d+\.\d+", pin["n8n_image"]) and "latest" not in pin["postgres_image"]


def test_pin_matches_the_live_compose_when_present():
    compose = Path.home() / "m8m-bakeoff-lab/docker-compose.n8n.yml"
    if not compose.is_file():
        pytest.skip("compose file not on this host")
    text = compose.read_text(encoding="utf-8")
    pin = r.load_pin()
    assert f"image: {pin['n8n_image']}" in text and f"image: {pin['postgres_image']}" in text
