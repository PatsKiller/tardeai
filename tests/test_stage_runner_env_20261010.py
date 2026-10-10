"""Stage runner per-step environment (2026-10-10, operator "Yes" ~19:45 ET, before C1 flips 3-4).

The manifest runner used to source $PROJ/.env wholesale (`set -a`) and hand that to every step, so a step whose
cron line never sourced .env (most of the 75 C1 steps) would have received every .env name, broker credential
names included. Now:

  * each step runs under `env -i` with exactly the names its cron line had: the Debian cron base (HOME, LANG,
    LOGNAME, PATH, SHELL) plus the crontab NAME=value lines that precede its own line (positional, vixie cron);
  * anything else (inline VAR=..., `set -a; . ./.env`, wrappers) stays inside the verbatim command;
  * the runner reads only its six safety flags from .env, unexported; a corrupted .env still fails loudly (78).

Hermetic: a scratch project root, a FAKE .env written by the test, `env | cut -d= -f1` commands. Names only.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PIPELINES = ROOT / "scripts" / "pipelines"
RUNNER = PIPELINES / "run_after_close_pipeline.sh"
MANIFESTS = ("premarket", "after_close", "hermes_learning", "hermes_overnight")
sys.path.insert(0, str(PIPELINES))
import derive_step_env as dse  # noqa: E402
import pipeline_manifest as pm  # noqa: E402

#: the crontab's NAME=value lines by position in the C1 snapshot (sha 1e3ccb09… / 9bbaeb74…, same numbering)
SNAPSHOT_ASSIGNMENTS = [(2, "SHELL"), (3, "PROJ"), (4, "PY"), (9, "LLM_DEFER_OFFPEAK"), (11, "TRADEAI_ENV"),
                        (13, "BLIND_REVIEW_LANES"), (506, "CIO_DUAL_CHATGPT_CAP")]
SNAPSHOT = Path.home() / "n8n-maturity-verification" / "packets" / "c1-manifest-flips" / "hermes_learning" / "crontab.before.txt"


def _m(name: str) -> dict:
    return json.loads((ROOT / "config" / "pipelines" / f"{name}.json").read_text(encoding="utf-8"))


def _steps():
    for name in MANIFESTS:
        for stage, spec in _m(name)["stages"].items():
            for st in spec["steps"]:
                yield name, stage, st


def _line(st) -> int:
    return int(st["inv_id"].split("L")[1])


def test_every_c1_step_has_an_env_spec_equal_to_its_cron_line():
    n = 0
    for name, stage, st in _steps():
        n += 1
        assert pm.validate_env_spec(st.get("env")) == [], (name, stage, st["id"])
        want = dse.cron_env_names(_line(st), SNAPSHOT_ASSIGNMENTS)
        assert pm.step_env_names(st) == want, (name, stage, st["id"])
    assert n == 75


@pytest.mark.skipif(not SNAPSHOT.exists(), reason="host-only: the C1 packet snapshot")
def test_fixture_matches_the_packet_snapshot():
    assert dse.crontab_assignments(SNAPSHOT.read_text(encoding="utf-8")) == SNAPSHOT_ASSIGNMENTS


def test_sources_and_inline_are_recorded_from_the_command_text():
    by_id = {st["id"]: st["env"] for _, _, st in _steps()}
    assert by_id["earnings_enrich"]["sources"] == ["./.env"]
    assert by_id["cio_draft_plan_hygiene"]["inline"] == ["TRADEAI_ROOT"]
    assert by_id["price_db_sync"]["sources"] == [] and by_id["price_db_sync"]["inline"] == []
    # CIO_DUAL_CHATGPT_CAP is set at crontab L506: lines above it never had it
    assert "CIO_DUAL_CHATGPT_CAP" not in by_id["price_db_sync"]["crontab_vars"]          # L183
    assert "CIO_DUAL_CHATGPT_CAP" in by_id["earnings_enrich"]["crontab_vars"]            # L551


def test_runner_never_hands_a_broker_name_to_a_step():
    for _, _, st in _steps():
        for n in pm.step_env_names(st):
            assert not n.upper().startswith(pm.BROKER_ENV_PREFIXES), (st["id"], n)
    bad = {"inherit": "cron", "cron_base": ["HOME"], "crontab_vars": ["ALPACA_KEY_ID"]}
    assert pm.validate_env_spec(bad)


def test_runner_source_no_longer_calls_load_env():
    src = (PIPELINES / "_manifest_runner.sh").read_text(encoding="utf-8")
    code = "\n".join(ln.split("#", 1)[0] for ln in src.splitlines())
    assert "load_env" not in code
    assert 'env -i "${stepenv[@]}"' in code


# ── runtime: the real runner, a fake .env, 75 env-printing steps ───────────────────────────────────────────────

def _project(tmp_path: Path, env_text: str) -> Path:
    root = tmp_path / "proj"
    (root / "logs").mkdir(parents=True)
    (root / ".env").write_text(env_text, encoding="utf-8")
    return root


def _runner_env(root: Path) -> dict:
    env = {"HOME": os.environ.get("HOME", "/tmp"), "LANG": "C.UTF-8", "LOGNAME": "tester", "PATH": "/usr/bin:/bin",
           "SHELL": "/bin/bash", "PROJ": str(root), "PY": sys.executable, "LLM_DEFER_OFFPEAK": "1",
           "TRADEAI_ENV": "/nonexistent/env", "BLIND_REVIEW_LANES": "x", "CIO_DUAL_CHATGPT_CAP": "1",
           # present in the runner's own environment, must never reach a step
           "NOISE_FROM_RUNNER": "1", "ALPACA_API_KEY_ID": "fake-runner-side", "PIPELINE_TODAY_DOW": "3"}
    return env


def _run(root: Path, manifest: Path, stage: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(RUNNER), "--manifest", str(manifest), "--project-root", str(root),
                           "--stage", stage, *args], cwd=str(ROOT), env=_runner_env(root),
                          capture_output=True, text=True, timeout=300)


FAKE_ENV = "CANARY_SHOULD_NOT_LEAK=1\nALPACA_KEY_ID=fake\nSCHWAB_APP_KEY=fake\nALPACA_MODE=paper\n"


def test_each_c1_step_gets_exactly_its_cron_env_names(tmp_path):
    root = _project(tmp_path, FAKE_ENV)
    steps = []
    for name, stage, st in _steps():
        sid = f"{name}__{stage}__{st['id']}".replace("-", "_")
        steps.append({"id": sid, "cron_line": st["cron_line"], "timeout": "30s", "env": st["env"],
                      "command": f'env | cut -d= -f1 | sort > "$PROJ/out_{sid}.txt"'})
    man = tmp_path / "c1envprobe.json"
    man.write_text(json.dumps({"schema": pm.MANIFEST_SCHEMA, "pipeline": "c1envprobe", "stages": {"all": {"steps": steps}}}))
    r = _run(root, man, "all", "--apply")
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    by_sid = {f"{n}__{s}__{st['id']}".replace("-", "_"): st for n, s, st in _steps()}
    for sid, st in by_sid.items():
        got = set((root / f"out_{sid}.txt").read_text().split()) - set(pm.SHELL_ADDED_ENV)
        want = set(dse.cron_env_names(_line(st), SNAPSHOT_ASSIGNMENTS))
        assert got == want, (sid, sorted(got ^ want))
        assert not any(n.startswith(("CANARY", "NOISE")) or n.upper().startswith(pm.BROKER_ENV_PREFIXES) for n in got), sid


def test_a_step_that_sources_env_itself_still_does(tmp_path):
    root = _project(tmp_path, FAKE_ENV)
    st = next(s for _, _, s in _steps() if s["id"] == "earnings_enrich")
    steps = [{"id": "own_source", "cron_line": 1, "timeout": "30s", "env": st["env"],
              "command": 'bash -c "set -a; . ./.env; set +a; env | cut -d= -f1 | sort > out_own.txt"'},
             {"id": "no_source", "cron_line": 2, "timeout": "30s", "env": st["env"],
              "command": "env | cut -d= -f1 | sort > out_none.txt"}]
    man = tmp_path / "own.json"
    man.write_text(json.dumps({"schema": pm.MANIFEST_SCHEMA, "pipeline": "ownsrc", "stages": {"s": {"steps": steps}}}))
    r = _run(root, man, "s", "--apply")
    assert r.returncode == 0, r.stdout + r.stderr
    own = set((root / "out_own.txt").read_text().split())
    none = set((root / "out_none.txt").read_text().split())
    assert {"CANARY_SHOULD_NOT_LEAK", "ALPACA_KEY_ID"} <= own      # as cron: the line sources it itself
    assert not none & {"CANARY_SHOULD_NOT_LEAK", "ALPACA_KEY_ID", "SCHWAB_APP_KEY"}


def test_safety_flags_still_read_from_env_file(tmp_path):
    root = _project(tmp_path, "ALPACA_MODE=live\n")
    man = tmp_path / "s.json"
    man.write_text(json.dumps({"schema": pm.MANIFEST_SCHEMA, "pipeline": "safety",
                               "stages": {"s": {"steps": [{"id": "t", "cron_line": 1, "timeout": "5s", "command": "true"}]}}}))
    r = _run(root, man, "s", "--dry-run")
    assert r.returncode == 2 and "SAFETY-FAIL" in r.stderr + r.stdout


def test_corrupted_env_still_fails_loudly(tmp_path):
    root = _project(tmp_path, "BROKEN='unterminated\n")
    man = tmp_path / "s.json"
    man.write_text(json.dumps({"schema": pm.MANIFEST_SCHEMA, "pipeline": "corrupt",
                               "stages": {"s": {"steps": [{"id": "t", "cron_line": 1, "timeout": "5s", "command": "true"}]}}}))
    r = _run(root, man, "s", "--dry-run")
    assert r.returncode == 78 and "FATAL" in r.stderr + r.stdout
