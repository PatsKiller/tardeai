"""LQ-20261107-229: the tracemalloc replay harness ranks growth correctly and can never reach live state.

Synthetic data only: allocations made by this test, a fabricated build tree under tmp_path.
"""

from __future__ import annotations

import importlib.util
import tracemalloc
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("tm_replay", ROOT / "scripts" / "ops" / "portfolio_server_tracemalloc_replay.py")
tm = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tm)

_HELD: list = []


def _grow(n: int) -> None:
    _HELD.append(bytearray(n))  # the growing line


def _snapshots(passes: int, step: int) -> list[tuple[str, tracemalloc.Snapshot]]:
    _HELD.clear()
    tracemalloc.start(tm.FRAMES)
    try:
        snaps = [("boot", tracemalloc.take_snapshot())]
        for n in range(1, passes + 1):
            _grow(step)
            snaps.append((f"pass{n}", tracemalloc.take_snapshot()))
        return snaps
    finally:
        tracemalloc.stop()


def test_top_growers_ranks_the_growing_line_first():
    snaps = _snapshots(2, 2_000_000)
    rows = tm.top_growers(snaps[1][1], snaps[2][1])
    assert rows, "a 2 MB allocation must show up"
    assert rows[0]["site"].endswith("test_portfolio_server_tracemalloc_replay_20261107.py:" + str(_grow.__code__.co_firstlineno + 1))
    assert rows[0]["size_diff"] >= 2_000_000
    assert all(r["size_diff"] > 0 for r in rows), "shrinking lines are not growth"
    assert len(tm.top_growers(snaps[0][1], snaps[2][1], n=3)) <= 3


def test_report_names_persistent_growers_and_callers():
    snaps = _snapshots(3, 1_000_000)
    rep = tm.build_report(snaps)
    assert [(p["from"], p["to"]) for p in rep["pairs"]] == [("boot", "pass1"), ("pass1", "pass2"), ("pass2", "pass3")]
    grow_site = rep["pairs"][1]["top"][0]["site"]
    assert any(r["site"] == grow_site and len(r["per_pass"]) == 2 for r in rep["persistent"]), rep["persistent"][:3]
    assert rep["pairs"][1]["top"][0]["callers"][-1] == grow_site, "the traceback ends at the growing line"
    md = tm.render_md(rep, [{"label": "boot", "rss_kb": 1024, "hwm_kb": 2048, "traced": 0}])
    assert "leak candidates" in md and grow_site in md


def test_report_dir_round_trips_dumped_snapshots(tmp_path):
    for label, snap in _snapshots(2, 500_000):
        snap.dump(str(tmp_path / f"snap-{label}.tmsnap"))
    rep = tm.report_dir(tmp_path)
    assert len(rep["pairs"]) == 2
    assert (tmp_path / "report.md").read_text().startswith("# portfolio-server tracemalloc replay")


def test_routes_skip_broker_pages_and_reject_non_paths(tmp_path):
    f = tmp_path / "routes.txt"
    f.write_text("/v3/a\n\n# c\n/v3/system/broker-access\n/v3/system/schwab-reauth\n/v3/b\n")
    routes, skipped = tm.load_routes(f)
    assert routes == ["/v3/a", "/v3/b"] and len(skipped) == 2
    assert len(tm.load_routes(f, include_broker=True)[0]) == 4
    f.write_text("http://127.0.0.1:7777/v3/a\n")
    with pytest.raises(ValueError):
        tm.load_routes(f)


def test_server_env_is_built_not_inherited_and_read_only():
    base = {"PATH": "/bin", "HOME": "/h", "ANTHROPIC_API_KEY": "x", "DB_PASSWORD": "x", "ENABLE_TELEGRAM": "1"}
    env = tm.server_env(scripts_dir="/s", runtime_dir="/r", boot_stamp="/b", db_user="u", base=base)
    assert "ANTHROPIC_API_KEY" not in env and "DB_PASSWORD" not in env
    assert env["PGOPTIONS"] == "-c default_transaction_read_only=on"
    assert env["ENABLE_TELEGRAM"] == "0" and env["PERSISTENT_WAKE_ENABLED"] == "0"
    assert env["PYTHONMALLOC"] == "malloc" and env["MALLOC_ARENA_MAX"] == "2", "allocator as live"
    assert env["DB_HOST"].startswith("/"), "unix socket, peer auth: no password needed"


def test_server_env_refuses_a_secret_shaped_flag(monkeypatch):
    monkeypatch.setitem(tm.LIVE_FLAGS, "BROKER_API_KEY", "x")
    with pytest.raises(RuntimeError):
        tm.server_env(scripts_dir="/s", runtime_dir="/r", boot_stamp="/b", db_user="u", base={})


def _fake_build(tmp_path: Path) -> Path:
    b = tmp_path / "build"
    (b / "config").mkdir(parents=True)
    (b / "scripts").mkdir()
    (b / "scripts" / "portfolio_server.py").write_text("")
    real_env = tmp_path / "elsewhere.env"
    real_env.write_text("SYNTHETIC=1\n")
    (b / ".env").symlink_to(real_env)
    (b / "config" / "broker_credentials.env").write_text("")
    (b / "config" / "design_token_baseline.json").write_text("{}")
    (b / "config" / "cc_auth.yaml").write_text("listeners:\n  service:\n    host: 127.0.0.1\n    port: 7777\n")
    return b


def test_sandbox_masks_secrets_isolates_network_and_binds_only_out(tmp_path):
    b = _fake_build(tmp_path)
    out = tmp_path / "out"
    argv = tm.bwrap_argv(build=b, out_dir=out, home=tmp_path, uid=1000, inner=["python", "x"])
    masked = {argv[i + 2] for i, a in enumerate(argv) if a == "--ro-bind" and argv[i + 1] == "/dev/null"}
    assert str((tmp_path / "elsewhere.env").resolve()) in masked, "the .env symlink target is masked"
    assert str(b / "config" / "broker_credentials.env") in masked
    assert str(b / "config" / "design_token_baseline.json") not in masked, "UI tokens are not secrets"
    assert "--unshare-net" in argv and "--tmp-overlay" in argv
    assert argv[argv.index("--ro-bind") + 1:argv.index("--ro-bind") + 3] == ["/", "/"], "root is read-only first"
    rw = [argv[i + 1] for i, a in enumerate(argv) if a == "--bind"]
    assert rw == ["/run/postgresql", str(out)], "only the DB socket dir and the report dir are writable"
    assert "/run/user/1000" in argv, "the live serve-proxy socket dir is replaced by a tmpfs"
    assert argv[argv.index("--") + 1:] == ["python", "x"]


def test_port_rewrite_touches_only_the_copy_and_refuses_live(tmp_path):
    y = _fake_build(tmp_path) / "config" / "cc_auth.yaml"
    tm.set_service_port(y, 7787)
    assert "port: 7787" in y.read_text() and "7777" not in y.read_text()
    with pytest.raises(ValueError):
        tm.set_service_port(y, 7777)
    with pytest.raises(SystemExit):
        tm.main(["--build", str(tmp_path / "build"), "--routes", str(y), "--out", str(tmp_path), "--port", "7777"])


def test_dry_run_starts_nothing(tmp_path, capsys):
    b = _fake_build(tmp_path)
    r = tmp_path / "routes.txt"
    r.write_text("/v3/a\n")
    out = tmp_path / "out"
    assert tm.main(["--build", str(b), "--routes", str(r), "--out", str(out), "--dry-run"]) == 0
    assert '"dry_run": true' in capsys.readouterr().out
    assert not out.exists(), "a dry run writes nothing"
