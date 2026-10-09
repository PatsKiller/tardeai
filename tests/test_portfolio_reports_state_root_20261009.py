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


# ── review round 1 (2026-10-09) ──────────────────────────────────────────────

def test_tradeai_root_naming_a_release_follows_its_state_link(tmp_path, monkeypatch):
    """Units/launchers export TRADEAI_ROOT=<release>; reports must still land in persistent-state."""
    monkeypatch.delenv(prr.ENV_OVERRIDE, raising=False)
    monkeypatch.delenv("TRADEAI_STATE_ROOT", raising=False)
    monkeypatch.delenv("TRADEAI_PERSISTENT_STATE_ROOT", raising=False)
    ps = tmp_path / "persistent-state"
    (ps / "data" / "portfolios" / "state").mkdir(parents=True)
    release = tmp_path / "portfolio-server" / "abc-release"
    (release / "data" / "portfolios").mkdir(parents=True)
    (release / "data" / "portfolios" / "state").symlink_to(ps / "data" / "portfolios" / "state")
    monkeypatch.setenv("TRADEAI_ROOT", str(release))
    assert prr.portfolio_reports_root() == ps / "data" / "portfolios" / "reports"


def test_report_url_skips_paths_and_symlinks_outside_the_root(reports_root, tmp_path):
    reports_root.mkdir(parents=True)
    outside = tmp_path / "outside.html"
    outside.write_text("x")
    link = reports_root / "escape.html"
    link.symlink_to(outside)
    assert prr.report_url(outside) is None
    assert prr.report_url(link) == "/data/portfolios/reports/escape.html"  # the link's own name
    assert prr.report_url(link.resolve()) is None  # resolved target is outside: skipped, no raise
    assert prr.served_url(link.resolve(), tmp_path / "proj") == str(link.resolve())


@pytest.fixture
def two_roots(reports_root, tmp_path):
    proj = tmp_path / "release"
    legacy = proj / "data" / "portfolios" / "reports"
    (legacy / "weekly").mkdir(parents=True)
    (reports_root / "weekly").mkdir(parents=True)
    (legacy / "weekly" / "weekly_old.html").write_text("legacy-only")
    (legacy / "weekly" / "weekly_both.html").write_text("legacy")
    (reports_root / "weekly" / "weekly_both.html").write_text("new")
    (reports_root / "weekly" / "weekly_new.html").write_text("new-only")
    return proj, legacy


def test_read_fallback_during_the_migration_window(two_roots, reports_root):
    proj, legacy = two_roots
    assert prr.resolve_report_file("weekly/weekly_both.html", proj).read_text() == "new"
    assert prr.resolve_report_file("weekly/weekly_old.html", proj) == (legacy / "weekly" / "weekly_old.html").resolve()
    assert prr.resolve_report_file("weekly/nope.html", proj) is None


def test_read_fallback_is_contained(two_roots, reports_root, tmp_path):
    proj, legacy = two_roots
    (tmp_path / "secret.txt").write_text("s")
    for rel in ("../../secret.txt", "../../../secret.txt", "weekly/../../../../secret.txt", "/etc/passwd"):
        assert prr.resolve_report_file(rel, proj) is None, rel
    (reports_root / "out.txt").symlink_to(tmp_path / "secret.txt")
    assert prr.resolve_report_file("out.txt", proj) is None


def test_catalog_union_new_root_wins_on_name(two_roots, reports_root):
    proj, legacy = two_roots
    got = {p.name: p for p in prr.union_glob("weekly/*.html", proj)}
    assert set(got) == {"weekly_old.html", "weekly_both.html", "weekly_new.html"}
    assert got["weekly_both.html"].read_text() == "new"
    assert prr.url_for_report_file(got["weekly_old.html"], proj) == "/data/portfolios/reports/weekly/weekly_old.html"


class _FakeHandler:
    def __init__(self):
        self.status = None
        self.body = b""

    def send_error(self, code, msg=None):
        self.status = code

    def send_response(self, code):
        self.status = code

    def send_header(self, *a):
        pass

    def end_headers(self):
        pass

    @property
    def wfile(self):
        h = self

        class _W:
            def write(self, b):
                h.body += b
        return _W()


def test_serve_file_contains_the_resolved_path(tmp_path):
    import portfolio_server as ps

    base = tmp_path / "mount"
    base.mkdir()
    (base / "ok.txt").write_text("ok")
    (tmp_path / "secret.txt").write_text("secret")
    (base / "link.txt").symlink_to(tmp_path / "secret.txt")
    h = _FakeHandler()
    ps.serve_file(h, base / "ok.txt", root=base)
    assert (h.status, h.body) == (200, b"ok")
    for bad in (base / ".." / "secret.txt", base / "link.txt"):
        h = _FakeHandler()
        ps.serve_file(h, bad, root=base)
        assert h.status == 404 and h.body == b"", bad


def test_launchers_no_longer_copy_the_release_local_live_dashboard():
    for name in ("run_portfolio.sh", "run_portfolio_weekly.sh", "run_portfolio_monthly.sh"):
        body = (ROOT / "linux_launchers" / name).read_text(encoding="utf-8")
        assert "cp data/portfolios/reports/portfolio_live.html" not in body, name
    reprice = (ROOT / "linux_launchers" / "run_reprice_only.sh").read_text(encoding="utf-8")
    assert "src = portfolio_reports_root() / 'portfolio_live.html'" in reprice
    assert "'data' / 'portfolios' / 'reports'" not in reprice


def test_dead_js_brief_is_marked():
    body = (SCRIPTS / "portfolio_brief_v2.js").read_text(encoding="utf-8")
    assert "DEAD PATH (2026-10-09)" in body
    assert "process.env.TRADEAI_PORTFOLIO_REPORTS_ROOT" in body


def test_migration_apply_never_overwrites_a_racing_writer(releases, tmp_path, monkeypatch):
    sys.path.insert(0, str(SCRIPTS))
    import migrate_portfolio_reports_to_state_root as mig

    base, _, _ = releases
    dest = tmp_path / "dest"
    plan = mig.plan_copy(mig.release_sources(base, dest), dest)
    # A writer lands one planned name between plan and apply.
    racer = Path(plan["actions"][0]["dest"])
    racer.parent.mkdir(parents=True, exist_ok=True)
    racer.write_bytes(b"RACER")
    res = mig.apply_plan(plan)
    assert res == {"copied": len(plan["actions"]) - 1, "skipped_exists": 1}
    assert racer.read_bytes() == b"RACER"


def test_extra_source_label_handles_short_paths(tmp_path):
    sys.path.insert(0, str(SCRIPTS))
    import migrate_portfolio_reports_to_state_root as mig

    tree = tmp_path / "devtree" / "data" / "portfolios" / "reports"
    tree.mkdir(parents=True)
    assert mig.extra_source_label(tree) == "extra-devtree"
    assert mig.extra_source_label(tmp_path / "x") == "extra-x"
    assert mig.extra_source_label(Path("/")) == "extra-root"
    assert mig.extra_source_label(Path("/a")) == "extra-a"  # parents[2] raised IndexError here
