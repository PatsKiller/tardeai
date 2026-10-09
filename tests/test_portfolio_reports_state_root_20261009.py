"""Generated reports resolve to persistent-state, not the release dir (2026-10-09).

Cron runs from portfolio-server/CURRENT, where data/portfolios/reports was a real
per-release directory: reports were stranded per release and the lane registry's
output_signal (read from persistent-state) saw the generate-weekly-docx lane SILENT.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

from lib import portfolio_reports_root as prr  # noqa: E402


@pytest.fixture
def reports_root(tmp_path, monkeypatch):
    root = tmp_path / "state" / "data" / "portfolios" / "reports"
    monkeypatch.setenv(prr.ENV_OVERRIDE, str(root))
    return root


def test_default_resolves_under_production_state_root(tmp_path, monkeypatch):
    monkeypatch.delenv(prr.ENV_OVERRIDE, raising=False)
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "ps"))
    assert prr.portfolio_reports_root() == tmp_path / "ps" / "data" / "portfolios" / "reports"


def test_env_override_wins(reports_root):
    assert prr.portfolio_reports_root() == reports_root


def test_served_url_and_inverse(reports_root, tmp_path):
    proj = tmp_path / "release"
    (reports_root / "weekly").mkdir(parents=True)
    f = reports_root / "weekly" / "weekly_2026-10-04.html"
    f.write_text("x")
    url = prr.served_url(f, proj)
    assert url == "/data/portfolios/reports/weekly/weekly_2026-10-04.html"
    assert prr.resolve_served_path(url, proj) == f
    # Non-report project paths keep their old /<rel> form.
    other = proj / "reports" / "hub.html"
    assert prr.served_url(other, proj) == "/reports/hub.html"
    assert prr.resolve_served_path("/reports/hub.html", proj) == other
    # Outside both roots: unchanged, exactly as the old helpers behaved on ValueError.
    assert prr.served_url("/elsewhere/x.png", proj) == "/elsewhere/x.png"


def test_glob_reports_rejects_non_report_patterns(reports_root):
    with pytest.raises(ValueError):
        prr.glob_reports("reports/2026-*/*.docx")


def test_writers_use_the_persistent_root():
    import analyst_report_builder
    import report_export
    import report_lineage
    import report_render
    import report_visuals
    import reporting_engine

    base = prr.portfolio_reports_root()
    for mod in (analyst_report_builder, report_export, report_lineage, report_render, reporting_engine):
        assert mod.REPORT_OUT == base / "analyst", mod.__name__
    assert report_visuals.REPORT_CHARTS == base / "analyst" / "charts"
    assert report_visuals.chart_url(base / "analyst" / "charts" / "a.png") == \
        "/data/portfolios/reports/analyst/charts/a.png"


_STRANDED = re.compile(r'(PROJECT_ROOT|ROOT|root)\s*/\s*"data"\s*/\s*"portfolios"\s*/\s*"reports"')


def test_no_live_script_rebuilds_the_release_local_path():
    offenders = []
    for path in sorted(SCRIPTS.glob("*.py")):
        if _STRANDED.search(path.read_text(encoding="utf-8", errors="replace")):
            offenders.append(path.name)
    assert offenders == [], f"resolve via lib.portfolio_reports_root instead: {offenders}"


def test_report_catalog_reads_persistent_root(reports_root, tmp_path):
    import generate_reports_hub as hub

    proj = tmp_path / "release"
    (proj / "data" / "runtime").mkdir(parents=True)
    (reports_root / "weekly").mkdir(parents=True)
    (reports_root / "weekly" / "weekly_2026-10-04.docx").write_bytes(b"d")
    # A stale release-local copy must not be what the catalog serves.
    (proj / "data" / "portfolios" / "reports" / "weekly").mkdir(parents=True)
    (proj / "data" / "portfolios" / "reports" / "weekly" / "weekly_2026-09-27.docx").write_bytes(b"old")
    cat = hub.build_report_catalog(str(proj))
    weekly = next(r for r in cat["types"] if r["artifacts"].get("docx", "").startswith(
        "/data/portfolios/reports/weekly/"))
    assert weekly["artifacts"]["docx"] == "/data/portfolios/reports/weekly/weekly_2026-10-04.docx"


# ── one-shot migration ───────────────────────────────────────────────────────

def _mk_release(base: Path, name: str, files: dict[str, bytes], mtime: float) -> Path:
    rel = base / name
    rep = rel / "data" / "portfolios" / "reports"
    for k, v in files.items():
        p = rep / k
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(v)
    os.utime(rel, (mtime, mtime))
    return rel


def _run(args, cwd):
    return subprocess.run([sys.executable, str(SCRIPTS / "migrate_portfolio_reports_to_state_root.py"), *args],
                          cwd=str(cwd), capture_output=True, text=True, timeout=120)


@pytest.fixture
def releases(tmp_path):
    base = tmp_path / "portfolio-server"
    base.mkdir()
    old = _mk_release(base, "aaa-old", {"analyst/registry.json": b"OLD", "weekly/w1.html": b"same",
                                       "only_old.md": b"o"}, 1_000)
    cur = _mk_release(base, "bbb-current", {"analyst/registry.json": b"NEW", "weekly/w1.html": b"same",
                                           "analyst/charts/c.png": b"png"}, 500)
    (base / "CURRENT").symlink_to(cur)
    return base, old, cur


def test_migration_dry_run_writes_nothing(releases, tmp_path):
    base, _, _ = releases
    dest = tmp_path / "dest"
    r = _run(["--releases-root", str(base), "--dest", str(dest)], cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["mode"] == "dry-run"
    assert out["releases"] == ["bbb-current", "aaa-old"]  # CURRENT claims first despite older mtime
    assert out["counts"] == {"files_seen": 6, "copy_new": 4, "copy_conflict": 1, "skip_identical": 1,
                             "skip_symlink": 0, "bytes_to_copy": 3 + 4 + 3 + 1 + 3}
    assert not dest.exists()


def test_migration_apply_copies_never_deletes_and_is_idempotent(releases, tmp_path):
    base, old, cur = releases
    dest = tmp_path / "dest"
    r = _run(["--releases-root", str(base), "--dest", str(dest), "--apply"], cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["copied"] == 5
    assert (dest / "analyst" / "registry.json").read_bytes() == b"NEW"  # served copy wins the name
    assert (dest / "analyst" / "registry.release-aaa-old.json").read_bytes() == b"OLD"
    assert (dest / "only_old.md").read_bytes() == b"o"
    # sources untouched
    assert (old / "data/portfolios/reports/analyst/registry.json").read_bytes() == b"OLD"
    assert (cur / "data/portfolios/reports/weekly/w1.html").read_bytes() == b"same"
    again = json.loads(_run(["--releases-root", str(base), "--dest", str(dest), "--apply"],
                            cwd=tmp_path).stdout)
    assert again["copied"] == 0
    assert again["counts"]["skip_identical"] == 6


def test_migration_never_overwrites_an_existing_dest_file(releases, tmp_path):
    base, _, _ = releases
    dest = tmp_path / "dest"
    (dest / "analyst").mkdir(parents=True)
    (dest / "analyst" / "registry.json").write_bytes(b"LIVE")
    out = json.loads(_run(["--releases-root", str(base), "--dest", str(dest), "--apply"],
                          cwd=tmp_path).stdout)
    assert (dest / "analyst" / "registry.json").read_bytes() == b"LIVE"
    assert (dest / "analyst" / "registry.release-bbb-current.json").read_bytes() == b"NEW"
    assert (dest / "analyst" / "registry.release-aaa-old.json").read_bytes() == b"OLD"
    assert out["counts"]["copy_conflict"] == 2


def test_migration_skips_a_release_already_linked_to_dest(tmp_path):
    base = tmp_path / "portfolio-server"
    dest = tmp_path / "dest"
    (dest / "x").mkdir(parents=True)
    rel = base / "ccc-linked" / "data" / "portfolios"
    rel.mkdir(parents=True)
    (rel / "reports").symlink_to(dest)
    out = json.loads(_run(["--releases-root", str(base), "--dest", str(dest)], cwd=tmp_path).stdout)
    assert out["releases"] == []
