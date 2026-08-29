"""A deleted Bitwarden secret must not silently empty the rendered env.

`render_env.py` guarded against SM returning *zero* secrets. It did not guard
against SM returning *one fewer*: a key deleted in the SM UI comes back as a
perfectly successful render that is one key short, and the atomic write takes
the credential with it. Every consumer loses it at once, with no error
anywhere — which is how `deepseek_tradeai` could vanish from a live system
without a single failing job until the next call site needed it.

Same posture as a transport failure: keep last-known-good and shout. A stale
cache costs nothing; a silently missing key takes the system down later, further
from the cause.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MODULE = REPO / "scripts" / "secrets" / "render_env.py"


@pytest.fixture()
def mod(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("render_env_under_test", MODULE)
    m = importlib.util.module_from_spec(spec)
    sys.modules["render_env_under_test"] = m
    spec.loader.exec_module(m)
    monkeypatch.setattr(m, "RENDER_PATH", tmp_path / "env")
    monkeypatch.setattr(m, "MANIFEST_PATH", tmp_path / "manifest.json")
    monkeypatch.setattr(m, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(m, "DISK_ENV", tmp_path / ".env")
    monkeypatch.setattr(m, "_telegram", lambda msg: None)
    return m


def _manifest(mod, keys):
    mod.MANIFEST_PATH.write_text(json.dumps({"shell_keys": sorted(keys)}),
                                 encoding="utf-8")


def test_previous_keys_read_from_manifest(mod):
    _manifest(mod, ["A", "B", "deepseek_tradeai"])
    assert set(mod._previous_render_keys()) == {"A", "B", "deepseek_tradeai"}


def test_previous_keys_fall_back_to_the_cache_file(mod):
    """Works even on a host whose manifest was cleared."""
    mod.RENDER_PATH.write_text("# c\nA='1'\nexport B='2'\n", encoding="utf-8")
    assert set(mod._previous_render_keys()) == {"A", "B"}


def test_no_previous_render_means_no_guard(mod):
    """First ever render must not be blocked by an empty baseline."""
    assert mod._previous_render_keys() == []


def test_a_dropped_key_is_refused(mod, monkeypatch):
    _manifest(mod, ["A", "B", "deepseek_tradeai"])
    monkeypatch.setattr(mod, "_token", lambda: "t")
    monkeypatch.setattr(mod, "_fetch_secrets",
                        lambda tok: {"A": "1", "B": "2"})   # deepseek deleted
    monkeypatch.setattr(mod, "_shell_exportable",
                        lambda s: ({"A": "1", "B": "2"}, []))
    out = mod.render()
    assert out["ok"] is False
    assert "SM_KEYS_DISAPPEARED" in str(out.get("error"))
    assert "deepseek_tradeai" in str(out.get("error"))


def test_the_cache_is_kept_when_a_key_disappears(mod, monkeypatch):
    """The whole point: last-known-good survives the refusal."""
    mod.RENDER_PATH.write_text("A='1'\ndeepseek_tradeai='keepme'\n", encoding="utf-8")
    _manifest(mod, ["A", "deepseek_tradeai"])
    monkeypatch.setattr(mod, "_token", lambda: "t")
    monkeypatch.setattr(mod, "_fetch_secrets", lambda tok: {"A": "1"})
    monkeypatch.setattr(mod, "_shell_exportable", lambda s: ({"A": "1"}, []))
    mod.render()
    kept = mod.RENDER_PATH.read_text(encoding="utf-8")
    assert "deepseek_tradeai" in kept, "cache was overwritten despite the drop"


def test_a_deliberate_removal_is_allowed_with_the_flag(mod, monkeypatch):
    _manifest(mod, ["A", "B"])
    monkeypatch.setattr(mod, "_token", lambda: "t")
    monkeypatch.setattr(mod, "_fetch_secrets", lambda tok: {"A": "1"})
    monkeypatch.setattr(mod, "_shell_exportable", lambda s: ({"A": "1"}, []))
    monkeypatch.setattr(mod, "mirror_rendered_keys_to_disk", lambda *a, **k: 0,
                        raising=False)
    out = mod.render(force_shrink=True)
    assert "SM_KEYS_DISAPPEARED" not in str(out.get("error"))


def test_added_keys_are_not_treated_as_a_drop(mod, monkeypatch):
    """Growth is fine; only disappearance is refused."""
    _manifest(mod, ["A"])
    monkeypatch.setattr(mod, "_token", lambda: "t")
    monkeypatch.setattr(mod, "_fetch_secrets", lambda tok: {"A": "1", "NEW": "2"})
    monkeypatch.setattr(mod, "_shell_exportable",
                        lambda s: ({"A": "1", "NEW": "2"}, []))
    monkeypatch.setattr(mod, "mirror_rendered_keys_to_disk", lambda *a, **k: 0,
                        raising=False)
    out = mod.render()
    assert "SM_KEYS_DISAPPEARED" not in str(out.get("error"))


def test_the_manifest_records_key_names_only_never_values(mod, monkeypatch):
    monkeypatch.setattr(mod, "_token", lambda: "t")
    monkeypatch.setattr(mod, "_fetch_secrets", lambda tok: {"A": "s3cret"})
    monkeypatch.setattr(mod, "_shell_exportable", lambda s: ({"A": "s3cret"}, []))
    monkeypatch.setattr(mod, "mirror_rendered_keys_to_disk", lambda *a, **k: 0,
                        raising=False)
    mod.render()
    man = mod.MANIFEST_PATH.read_text(encoding="utf-8")
    assert "shell_keys" in man
    assert "s3cret" not in man, "manifest must never contain a secret value"


def test_zero_secret_guard_still_fires(mod, monkeypatch):
    monkeypatch.setattr(mod, "_token", lambda: "t")
    monkeypatch.setattr(mod, "_fetch_secrets", lambda tok: {})
    out = mod.render()
    assert out["ok"] is False
    assert "zero secrets" in str(out.get("error"))
