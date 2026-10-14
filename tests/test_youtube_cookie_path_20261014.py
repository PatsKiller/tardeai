"""YouTube cookie jar survives a release (2026-10-14).

Bug: every reader/writer used ``PROJECT_ROOT / "config" / "youtube_cookies.txt"``; PROJECT_ROOT is
the served release dir, a new one per promote, so the operator's 2026-10-13 refresh vanished at
the 2026-10-14 promote (CC "YouTube cookies RED — no cookie file").

Fix: ``scripts/lib/youtube_cookie_path.py`` — canonical ``~/.config/tradeai/youtube_cookies.txt``
(``TRADEAI_YOUTUBE_COOKIE_FILE`` override), legacy release path as a read-only fallback that
health checks flag amber. Hermetic: tmp HOME / tmp project roots / synthetic cookie rows only.
"""

from __future__ import annotations

import importlib.util
import os
import re
import stat
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from scripts.lib import youtube_cookie_path as ycp  # noqa: E402

ENV = ycp.ENV_OVERRIDE
# Synthetic, never a real cookie: a far-future SID row on .youtube.com.
SYNTH = "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t9999999999\tSID\tsynthetic-fixture\n"
SYNTH_LOGGED_OUT = "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t9999999999\tVISITOR_INFO1_LIVE\tx\n"


@pytest.fixture
def home(monkeypatch, tmp_path):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.delenv(ENV, raising=False)
    return h


@pytest.fixture
def proj(tmp_path):
    p = tmp_path / "release" / "abc123-portfolio-server"
    (p / "config").mkdir(parents=True)
    return p


def _put(path: Path, text: str = SYNTH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


# ── resolver ────────────────────────────────────────────────────────────────


def test_canonical_default_is_under_home_config_tradeai(home):
    assert ycp.canonical_cookie_path() == home / ".config" / "tradeai" / "youtube_cookies.txt"


def test_env_override_replaces_canonical(home, tmp_path, monkeypatch):
    target = tmp_path / "elsewhere" / "jar.txt"
    monkeypatch.setenv(ENV, str(target))
    assert ycp.canonical_cookie_path() == target


def test_order_canonical_wins_over_legacy(home, proj):
    canon = _put(home / ".config" / "tradeai" / "youtube_cookies.txt")
    _put(proj / "config" / "youtube_cookies.txt")
    res = ycp.resolve_cookie_path(proj)
    assert (res.path, res.location) == (canon, "canonical")
    assert not res.is_legacy and res.legacy_warning() is None


def test_order_legacy_fallback_when_canonical_absent(home, proj):
    legacy = _put(proj / "config" / "youtube_cookies.txt")
    res = ycp.resolve_cookie_path(proj)
    assert (res.path, res.location) == (legacy, "legacy")
    warn = res.legacy_warning()
    assert "will be lost on next release" in warn and str(res.canonical) in warn


def test_missing_resolves_to_canonical_path(home, proj):
    res = ycp.resolve_cookie_path(proj)
    assert res.location == "missing" and not res.exists
    assert res.path == res.canonical == home / ".config" / "tradeai" / "youtube_cookies.txt"
    assert ycp.youtube_cookie_path(proj) == res.canonical


def test_directory_at_canonical_is_not_a_cookie_file(home, proj):
    (home / ".config" / "tradeai" / "youtube_cookies.txt").mkdir(parents=True)
    legacy = _put(proj / "config" / "youtube_cookies.txt")
    assert ycp.resolve_cookie_path(proj).path == legacy


# ── source guards ───────────────────────────────────────────────────────────

_CALLERS = [
    "scripts/youtube_transcript_ingest.py",
    "scripts/topic_ingestion.py",
    "scripts/youtube_cookie_health_check.py",
    "scripts/api_v2.py",
    "scripts/credential_monitor.py",
    "scripts/portfolio_server.py",
]


@pytest.mark.parametrize("rel", _CALLERS)
def test_no_caller_builds_the_release_dir_cookie_path(rel):
    src = (ROOT / rel).read_text()
    assert not re.search(r'["\']config["\']\s*/\s*["\']youtube_cookies\.txt["\']', src), rel
    assert "youtube_cookie_path" in src, rel


def test_resolver_and_setup_have_no_hardcoded_home():
    for rel in ("scripts/lib/youtube_cookie_path.py", "scripts/setup_youtube_cookies.sh"):
        assert "/home/" not in (ROOT / rel).read_text(), rel


def test_setup_script_writes_canonical_path_mode_600():
    src = (ROOT / "scripts/setup_youtube_cookies.sh").read_text()
    assert 'COOKIE_FILE="${TRADEAI_YOUTUBE_COOKIE_FILE:-$HOME/.config/tradeai/youtube_cookies.txt}"' in src
    assert 'install -m 600 "$TEMP_COOKIE" "$COOKIE_FILE"' in src
    assert 'cp "$TEMP_COOKIE"' not in src


# ── youtube_cookie_health_check ─────────────────────────────────────────────


def _load_health(monkeypatch, proj: Path):
    spec = importlib.util.spec_from_file_location(
        "_yt_cookie_hc_20261014", ROOT / "scripts/youtube_cookie_health_check.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "PROJECT_ROOT", proj)
    monkeypatch.setattr(mod, "_transcript_age_h", lambda: 1.0)
    monkeypatch.setattr(mod, "_send_telegram", lambda *a, **k: pytest.fail("no send in test"))
    monkeypatch.setattr(sys, "argv", ["youtube_cookie_health_check.py", "--no-send"])
    return mod


def test_health_green_reports_canonical_path(home, proj, monkeypatch, capsys):
    canon = _put(home / ".config" / "tradeai" / "youtube_cookies.txt")
    mod = _load_health(monkeypatch, proj)
    assert mod.main() == 0
    s = mod._summary()
    assert s["status"] == "green" and s["cookie_location"] == "canonical" and s["cookie_path"] == str(canon)
    assert f"cookie path: {canon} (canonical)" in capsys.readouterr().out


def test_health_legacy_location_is_amber_with_lost_warning(home, proj, monkeypatch, capsys):
    legacy = _put(proj / "config" / "youtube_cookies.txt")
    mod = _load_health(monkeypatch, proj)
    assert mod.main() == 0
    s = mod._summary()
    assert s["status"] == "amber" and s["cookie_location"] == "legacy" and s["cookie_path"] == str(legacy)
    assert "will be lost on next release" in s["detail"]
    assert "(legacy)" in capsys.readouterr().out


def test_health_missing_is_red_and_names_canonical(home, proj, monkeypatch):
    mod = _load_health(monkeypatch, proj)
    mod.main()
    s = mod._summary()
    assert s["status"] == "red" and s["cookie_location"] == "missing"
    assert s["cookie_path"] == str(home / ".config" / "tradeai" / "youtube_cookies.txt")


def test_health_classify_red_beats_legacy_and_legacy_beats_stale():
    spec = importlib.util.spec_from_file_location("_yt_cookie_hc_cls", ROOT / "scripts/youtube_cookie_health_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.classify(0, 1.0, "legacy")[0] == "red"
    assert mod.classify(None, 1.0, "missing")[0] == "red"
    st, det = mod.classify(3, 500.0, "legacy")
    assert st == "amber" and "legacy" in det
    assert mod.classify(3, 500.0, "canonical") == ("amber", "authenticated but ingestion 500h stale")
    assert mod.classify(3, 1.0, "canonical")[0] == "green"


def test_refresh_steps_name_canonical_path():
    spec = importlib.util.spec_from_file_location("_yt_cookie_hc_txt", ROOT / "scripts/youtube_cookie_health_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert "~/.config/tradeai/youtube_cookies.txt" in mod.REFRESH_STEPS
    assert "config/youtube_cookies.txt:" not in mod.REFRESH_STEPS.replace("tradeai/youtube_cookies.txt", "")


# ── api_v2: pipeline-health stoplight + Ops UI writer ───────────────────────


@pytest.fixture
def api(monkeypatch, proj):
    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_execute=lambda *a, **k: None, USE_DB=False))
    import api_v2

    monkeypatch.setattr(api_v2, "PROJECT_ROOT", proj)
    monkeypatch.setattr(api_v2, "_db_query", lambda *a, **k: None)
    return api_v2


def test_pipeline_health_canonical_green(home, api):
    canon = _put(home / ".config" / "tradeai" / "youtube_cookies.txt")
    yt = api._system_pipeline_health()["ingestion"]["youtube_cookies"]
    assert yt["status"] == "green" and yt["location"] == "canonical" and yt["path"] == str(canon)


def test_pipeline_health_legacy_amber(home, proj, api):
    _put(proj / "config" / "youtube_cookies.txt")
    yt = api._system_pipeline_health()["ingestion"]["youtube_cookies"]
    assert yt["status"] == "amber" and yt["location"] == "legacy"
    assert "will be lost on next release" in yt["detail"]


def test_pipeline_health_missing_red_names_canonical(home, api):
    yt = api._system_pipeline_health()["ingestion"]["youtube_cookies"]
    assert yt["status"] == "red" and yt["location"] == "missing"
    assert "~/.config/tradeai/youtube_cookies.txt" in yt["detail"]


def test_pipeline_health_logged_out_canonical_is_red(home, api):
    _put(home / ".config" / "tradeai" / "youtube_cookies.txt", SYNTH_LOGGED_OUT)
    assert api._system_pipeline_health()["ingestion"]["youtube_cookies"]["status"] == "red"


def test_ops_writer_writes_canonical_mode_600_never_release_dir(home, proj, api):
    legacy = _put(proj / "config" / "youtube_cookies.txt", SYNTH_LOGGED_OUT)
    code, body = api._system_youtube_cookies_write({"cookies": SYNTH})
    canon = home / ".config" / "tradeai" / "youtube_cookies.txt"
    assert code == 200 and body["ok"] and body["location"] == "canonical" and body["path"] == str(canon)
    assert canon.read_text() == SYNTH
    assert stat.S_IMODE(canon.stat().st_mode) == 0o600
    # The legacy release-dir copy is untouched (never deleted, never written).
    assert legacy.read_text() == SYNTH_LOGGED_OUT
    # Backup of what was in use (the legacy jar) lands next to the canonical file, 0600.
    bak = Path(body["backup"])
    assert bak.parent == canon.parent and stat.S_IMODE(bak.stat().st_mode) == 0o600
    assert ycp.resolve_cookie_path(proj).location == "canonical"


def test_ops_writer_honours_env_override(home, tmp_path, monkeypatch, api):
    target = tmp_path / "ovr" / "jar.txt"
    monkeypatch.setenv(ENV, str(target))
    code, body = api._system_youtube_cookies_write({"cookies": SYNTH})
    assert code == 200 and body["path"] == str(target) and target.read_text() == SYNTH
    assert not (home / ".config" / "tradeai" / "youtube_cookies.txt").exists()


# ── ingesters read through the resolver ─────────────────────────────────────


def test_transcript_ingest_cookie_path_follows_resolver(home, monkeypatch):
    canon = _put(home / ".config" / "tradeai" / "youtube_cookies.txt")
    monkeypatch.setitem(sys.modules, "psycopg2", types.SimpleNamespace(connect=lambda *a, **k: None))
    spec = importlib.util.spec_from_file_location("_yt_ingest_20261014", ROOT / "scripts/youtube_transcript_ingest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.COOKIE_PATH == canon


def test_credential_monitor_flags_legacy(home, proj, monkeypatch):
    import credential_monitor

    monkeypatch.setattr(credential_monitor, "PROJECT_ROOT", proj)
    assert credential_monitor.check_youtube_cookie()["status"] == "missing"
    _put(proj / "config" / "youtube_cookies.txt")
    r = credential_monitor.check_youtube_cookie()
    assert r["status"] == "warning" and "will be lost on next release" in r["error"]
    os.replace(proj / "config" / "youtube_cookies.txt", home / "moved.txt")
    _put(home / ".config" / "tradeai" / "youtube_cookies.txt")
    assert credential_monitor.check_youtube_cookie()["status"] == "ok"
