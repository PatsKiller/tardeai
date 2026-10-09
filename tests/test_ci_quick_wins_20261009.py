"""CI quick wins Q1-Q11 (CI design audit 2026-10-09, operator-approved the same day).

Each test pins one change so a later edit cannot quietly undo it: workflow concurrency
and checkout (Q1, Q2, Q6), the smokes moved to the nightly job (Q5), the deploy order
CI-before-grant (Q9), the fail-closed frontend build (Q10), the secrets range scan and
its CI/pre-push wiring (Q11), the duration-hints receipt (Q3), and release-readiness in
the promote preflight. Q4/Q8 live in test_cio_ci_profiles_20260925.py and Q7 in
test_ci_pr_selection_20260925.py, next to the code they hold.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows"
DEPLOY = ROOT / "scripts" / "cio_phase2_exact_main_deploy.sh"
SHA = "a" * 40


def _module(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _wf(name: str) -> dict:
    return yaml.safe_load((WF / name).read_text(encoding="utf-8"))


def _steps(doc: dict, job: str) -> list[dict]:
    return doc["jobs"][job]["steps"]


def _step_names(doc: dict, job: str) -> list[str]:
    return [s.get("name", "") for s in _steps(doc, job)]


# ── Q1 / Q2: concurrency ──────────────────────────────────────────────────────────

def test_q1_agent_governance_cancels_only_superseded_pr_runs():
    doc = _wf("agent-governance.yml")
    assert doc["concurrency"]["cancel-in-progress"] == "${{ github.event_name == 'pull_request' }}"


def test_q2_cio_hardening_cancels_superseded_runs_on_main_too():
    doc = _wf("cio-production-hardening-ci.yml")
    assert doc["concurrency"]["cancel-in-progress"] is True
    assert "${{ github.ref }}" in doc["concurrency"]["group"]  # per ref: a PR never cancels main


def test_q2_premise_prepare_only_promotes_the_origin_main_tip():
    src = DEPLOY.read_text(encoding="utf-8")
    body = src[src.index("require_head_is_origin_main() {"):src.index("current_release() {")]
    assert 'die "ROOT HEAD $head != origin/main $origin_main' in body
    prepare = src[src.index("cmd_prepare() {"):src.index("conformance_gate() {")]
    assert prepare.index("require_head_is_origin_main") < prepare.index('CONTENT_SHA="$(git_sha)"')


# ── Q5 / Q6: required job slimmed ─────────────────────────────────────────────────

def test_q5_pdf_and_docx_smokes_run_nightly_not_in_the_required_job():
    doc = _wf("cio-production-hardening-ci.yml")
    required = _step_names(doc, "cio-hardening")
    nightly = _step_names(doc, "cio-hardening-full")
    assert not any("PDF smoke" in n or "DOCX smoke" in n for n in required)
    assert any("PDF smoke" in n for n in nightly) and any("DOCX smoke" in n for n in nightly)
    assert "Report HTML export smoke" in required  # the blocking regression smoke stays
    for s in _steps(doc, "cio-hardening-full"):
        if "smoke" in s.get("name", ""):
            assert s.get("continue-on-error") is True and s.get("if") == "${{ !cancelled() }}"


def test_q6_shallow_pr_checkout_with_base_fetch_and_pip_cache():
    doc = _wf("cio-production-hardening-ci.yml")
    steps = _steps(doc, "cio-hardening")
    checkout = next(s for s in steps if str(s.get("uses", "")).startswith("actions/checkout"))
    assert checkout["with"]["fetch-depth"] == "${{ github.event_name == 'pull_request' && 2 || 0 }}"
    base = next(s for s in steps if s.get("name") == "Fetch PR base for the selector merge-base")
    assert base["if"] == "github.event_name == 'pull_request'"
    assert "--unshallow" in base["run"] and "git merge-base" in base["run"]
    py = next(s for s in steps if s.get("name") == "Set up Python")
    assert py["with"]["cache"] == "pip"
    names = [s.get("name", "") for s in steps]
    assert names.index("Fetch PR base for the selector merge-base") < names.index("CIO hardening gates (unit + manifest)")
    # the nightly isolation run keeps full history
    full = next(s for s in _steps(doc, "cio-hardening-full") if str(s.get("uses", "")).startswith("actions/checkout"))
    assert full["with"]["fetch-depth"] == 0


# ── Q11: secrets scan of the pushed range, in CI and pre-push ─────────────────────

def test_q11_agent_governance_scans_every_pr_commit_and_nightly_scans_the_tree():
    ag = _wf("agent-governance.yml")
    step = next(s for s in _steps(ag, "agent-governance") if s.get("name") == "Secrets scan (PR commits / pushed range)")
    assert "continue-on-error" not in step  # blocking: agent-governance is a required context
    assert 'check_no_secrets.py --range "${PR_BASE_SHA}..${PR_HEAD_SHA}"' in step["run"]
    assert "--tree" in step["run"]  # fallback when a push range cannot be resolved
    cio = _wf("cio-production-hardening-ci.yml")
    nightly = next(s for s in _steps(cio, "cio-hardening-full") if s.get("name") == "Secrets tree scan")
    assert nightly["run"] == "python3 scripts/check_no_secrets.py --tree"


def test_q11_pre_push_scans_the_pushed_range_and_falls_back_to_the_tree():
    hook = (ROOT / ".githooks" / "pre-push").read_text(encoding="utf-8")
    assert 'check_no_secrets.py" --range "${range[@]}"' in hook
    assert 'range=("${rsha}..${lsha}")' in hook and 'range=("$lsha" --not --remotes)' in hook
    assert 'check_no_secrets.py" --tree' in hook
    assert 'TRADEAI_SKIP_SECRETS_SCAN' in hook


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture()
def scan_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(ROOT / "scripts" / "check_no_secrets.py", repo / "scripts" / "check_no_secrets.py")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@test.local")
    _git(repo, "config", "user.name", "t")
    (repo / "a.txt").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


def _scan(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "scripts/check_no_secrets.py", *args], cwd=repo,
                          capture_output=True, text=True)


def test_q11_range_scan_catches_a_secret_added_then_deleted_inside_the_range(scan_repo):
    base = _git(scan_repo, "rev-parse", "HEAD")
    fake_key = "AKIA" + "Q" * 16  # built at runtime: no key-shaped literal in this file
    (scan_repo / "b.txt").write_text(f"k={fake_key}\n", encoding="utf-8")
    _git(scan_repo, "add", "b.txt")
    _git(scan_repo, "commit", "-q", "-m", "oops")
    (scan_repo / "b.txt").write_text("k=redacted\n", encoding="utf-8")
    _git(scan_repo, "commit", "-q", "-am", "remove")
    head = _git(scan_repo, "rev-parse", "HEAD")
    assert _scan(scan_repo, "--tree").returncode == 0  # the tip tree is clean...
    r = _scan(scan_repo, "--range", f"{base}..{head}")
    assert r.returncode == 1, r.stdout + r.stderr  # ...but the pushed history is not
    assert "AWS access key" in r.stderr


def test_q11_range_scan_passes_a_clean_range_and_refuses_an_unresolvable_one(scan_repo):
    base = _git(scan_repo, "rev-parse", "HEAD")
    (scan_repo / "c.txt").write_text("fine\n", encoding="utf-8")
    _git(scan_repo, "add", "c.txt")
    _git(scan_repo, "commit", "-q", "-m", "clean")
    ok = _scan(scan_repo, "--range", f"{base}..HEAD")
    assert ok.returncode == 0 and "(1 files scanned)" in ok.stdout
    bad = _scan(scan_repo, "--range", "0123456789abcdef0123456789abcdef01234567..HEAD")
    assert bad.returncode == 2  # never "clean" on a range git cannot resolve


def test_q11_range_scan_blocks_a_secret_file_name(scan_repo):
    base = _git(scan_repo, "rev-parse", "HEAD")
    (scan_repo / "id.pem").write_text("x\n", encoding="utf-8")
    _git(scan_repo, "add", "id.pem")
    _git(scan_repo, "commit", "-q", "-m", "pem")
    r = _scan(scan_repo, "--range", f"{base}..HEAD")
    assert r.returncode == 1 and "secret FILE" in r.stderr


# ── release-readiness is required for promote ─────────────────────────────────────

def test_promote_preflight_requires_release_readiness():
    gate = _module("quickwins_release_preflight", "scripts/release_grant_preflight.py")
    assert ".github/workflows/release-readiness.yml" in gate.REQUIRED_PUSH_WORKFLOWS
    assert (WF / "release-readiness.yml").is_file()
    on = _wf("release-readiness.yml")[True]  # YAML 1.1 reads the key `on` as True
    assert "main" in on["push"]["branches"]  # it produces exact-SHA push/main evidence

    def run(i, path, **kw):
        return dict(id=i, workflow_id=i + 10, path=path, name=path, run_number=1, head_sha=SHA,
                    event="push", head_branch="main", status="completed", conclusion="success",
                    run_attempt=1, **kw)

    others = [p for p in sorted(gate.REQUIRED_PUSH_WORKFLOWS) if not p.endswith("release-readiness.yml")]
    rows = [run(i, p) for i, p in enumerate(others, 1)]
    report = gate.evaluate_push_checks(SHA, rows)
    assert not report["ok"]
    assert "missing:.github/workflows/release-readiness.yml" in report["errors"]
    rows.append(run(9, ".github/workflows/release-readiness.yml", ))
    assert gate.evaluate_push_checks(SHA, rows)["ok"]
    rows[-1].update(conclusion="failure")
    assert "not_successful:.github/workflows/release-readiness.yml" in gate.evaluate_push_checks(SHA, rows)["errors"]


# ── Q9: exact-SHA CI before the grant is consumed ─────────────────────────────────

def _promote_harness(tmp_path: Path, ci_ok: bool) -> subprocess.CompletedProcess:
    source = DEPLOY.read_text(encoding="utf-8")
    source = source[:source.rindex('case "$MODE" in')]
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "BUILD_SHA").write_text(SHA)
    fake_py = tmp_path / "fake_python"
    log = tmp_path / "events"
    # The CI check is the only VENV_PYTHON call in cmd_promote; record each one.
    fake_py.write_text(f"#!/bin/sh\necho CI_CHECK >> '{log}'\nexit {0 if ci_ok else 2}\n")
    fake_py.chmod(0o700)
    script = tmp_path / "harness.sh"
    script.write_text(source + '\nROOT="' + str(ROOT) + '"\nEMERGENCY_SHA=""\n' + f'''
load_state() {{ :; }}
current_release() {{ echo previous; }}
release_grant_preflight() {{ echo GRANT_CONSUMED >> '{log}'; }}
conformance_gate() {{ :; }}
write_deploy_receipt() {{ echo "RECEIPT:$*"; }}
write_state() {{ :; }}
activate_release() {{ echo ACTIVATE >> '{log}'; }}
health_check() {{ return 0; }}
restart_root_frozen_units() {{ :; }}
write_expected_release_pin() {{ :; }}
worker_pin_check() {{ :; }}
ff_dev_tree_after_promote() {{ :; }}
VENV_PYTHON='{fake_py}'
cmd_promote "$1"
''')
    r = subprocess.run(["bash", str(script), str(candidate)], capture_output=True, text=True)
    r.events = log.read_text().split() if log.is_file() else []
    return r


def test_q9_ci_refusal_consumes_no_release_grant_use(tmp_path):
    r = _promote_harness(tmp_path, ci_ok=False)
    assert r.returncode == 1
    assert "post_merge_ci_refused" in r.stdout
    assert "no release grant use consumed" in r.stderr
    assert r.events == ["CI_CHECK"]  # no GRANT_CONSUMED, no ACTIVATE


def test_q9_green_ci_then_grant_then_recheck_then_activate(tmp_path):
    r = _promote_harness(tmp_path, ci_ok=True)
    assert r.returncode == 0, r.stderr
    assert r.events == ["CI_CHECK", "GRANT_CONSUMED", "CI_CHECK", "ACTIVATE"]


# ── Q10: frontend build fails closed ──────────────────────────────────────────────

def test_q10_prepare_build_has_no_vite_only_fallback(tmp_path):
    src = DEPLOY.read_text(encoding="utf-8")
    body = src[src.index("build_frontend() {"):src.index("\n}\n", src.index("build_frontend() {"))]
    code = [ln for ln in body.splitlines() if not ln.lstrip().startswith("#")]
    assert not any("vite build" in ln for ln in code)
    assert "npm run build || die" in body

    # Real shell: a failing `npm run build` stops prepare before anything is copied.
    src_tree = tmp_path / "src"
    (src_tree / "apps" / "command-center-v3" / "node_modules").mkdir(parents=True)
    dest = tmp_path / "dest"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "npm").write_text("#!/bin/sh\necho npm \"$@\" >> \"$NPM_LOG\"\nexit 1\n")
    (bin_dir / "npx").write_text("#!/bin/sh\necho npx \"$@\" >> \"$NPM_LOG\"\nexit 0\n")
    for b in ("npm", "npx"):
        (bin_dir / b).chmod(0o700)
    funcs = src[:src.rindex('case "$MODE" in')]
    script = tmp_path / "harness.sh"
    script.write_text(funcs + f'\nbuild_frontend "{src_tree}" "{dest}"\necho BUILD_RETURNED\n')
    env = {**os.environ, "HOME": str(tmp_path), "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
           "NPM_LOG": str(tmp_path / "npm.log")}
    r = subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env)
    assert r.returncode != 0
    assert "BUILD_RETURNED" not in r.stdout
    assert "npm run build failed" in r.stderr
    assert (tmp_path / "npm.log").read_text().split("\n")[0] == "npm run build"
    assert "npx" not in (tmp_path / "npm.log").read_text()
    assert not (dest / "apps" / "command-center-v3" / "dist").exists()


# ── Q3: duration hints carry a measurement receipt and a refresh cadence ──────────

def test_q3_duration_hints_receipt():
    doc = json.loads((ROOT / "config" / "ci_test_duration_hints.json").read_text(encoding="utf-8"))
    assert doc["schema"] == "CiTestDurationHints@v1"
    receipt = doc["receipt"]
    assert receipt["jobs"] == 4  # the CI runner's worker count
    assert receipt["refresh"].startswith("weekly")
    assert receipt["measured_at"][:4] == "2026"
    assert len(doc["files"]) > 48  # was 48 files from one 2026-09-25 local run
    assert all(isinstance(v, (int, float)) and v > 0 for v in doc["files"].values())
