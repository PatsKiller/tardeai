"""n8n platform maturity — dimensions 7 governance, 8 security, 11 CI signal, 12 docs synced.

Hermetic: tmp_path for the state root / repo / HOME, a fake runner for every command, a fixed ``now``.
Nothing here touches docker, systemd, gh, crontab or the live guard ledger.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "lib"))

from n8n_maturity import core  # noqa: E402
from n8n_maturity import dims_governance as g  # noqa: E402

NOW = dt.datetime(2026, 10, 9, 20, 0, tzinfo=dt.timezone.utc)
SECRET_VALUE = "s3cr3t-value-never-shown"


def _iso(hours_ago: float) -> str:
    return (NOW - dt.timedelta(hours=hours_ago)).isoformat()


class FakeRunner:
    """Dispatch on argv; record every argv. ``fail`` = set of exe names that return rc 1."""

    def __init__(self, handlers: dict, fail: set | None = None):
        self.handlers = handlers
        self.fail = fail or set()
        self.calls: list[list[str]] = []

    def __call__(self, argv, timeout):
        self.calls.append(list(argv))
        exe = argv[0]
        if exe in self.fail:
            return 1, "", "boom"
        for key, fn in self.handlers.items():
            if key(argv):
                out = fn(argv)
                return (0, out, "") if isinstance(out, str) else out
        return 1, "", f"unhandled {argv[:3]}"


REAL_CONFIG = json.loads((REPO / "config" / "n8n_platform_maturity.json").read_text(encoding="utf-8"))
GATE_CAP = float(REAL_CONFIG["gate_cap"])
GOV = REAL_CONFIG["dimensions"]["governance"]
SEC = REAL_CONFIG["dimensions"]["security"]
APP, DBC = GOV["n8n_container"], GOV["n8n_db_container"]


def _config(dims: dict | None = None) -> dict:
    """The REAL config/n8n_platform_maturity.json with per-dimension overrides merged in."""
    cfg = copy.deepcopy(REAL_CONFIG)
    for k, v in (dims or {}).items():
        cfg["dimensions"][k].update(v)
    return cfg


def _probe(tmp_path: Path, runner, dims: dict | None = None, env: dict | None = None,
           config: dict | None = None) -> core.Probe:
    root = tmp_path / "state"
    proj = tmp_path / "repo"
    root.mkdir(exist_ok=True)
    proj.mkdir(exist_ok=True)
    cfg = config if config is not None else _config(dims)
    base_env = {"HOME": str(tmp_path / "home")}
    base_env.update(env or {})
    return core.Probe(root=root, proj=proj, now=NOW, env=base_env, config=cfg, runner=runner)


# ================================================================================================
# governance fixtures
# ================================================================================================

WF_A, WF_B = "aaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbb"


def _n8n_sql(workflows, published):
    def handler(argv):
        sql = argv[argv.index("-c") + 1]
        if "from workflow_entity" in sql:
            return json.dumps(workflows)
        if "from workflow_publish_history" in sql:
            return "[]"
        if "from workflow_published_version" in sql:
            return json.dumps(published)
        if "from workflow_history" in sql:
            return "[]"
        if "pg_roles" in sql:
            return "[]"
        return 1, "", "bad sql"
    return handler


def _is_psql(argv):
    return argv[0] == "docker" and argv[1] == "exec" and "psql" in argv


def _gov_world(tmp_path: Path, *, grant_both=True, hook=True, schedule=True, receipts=True):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    (home / "logs").mkdir(parents=True, exist_ok=True)
    workflows = [
        {"id": WF_A, "name": "lane-a", "active": True, "versionId": "va", "activeVersionId": "va"},
        {"id": WF_B, "name": "lane-b", "active": True, "versionId": "vb", "activeVersionId": "vb"},
        {"id": "cccccccccccccccc", "name": "lane-c", "active": False, "versionId": "vc", "activeVersionId": None},
    ]
    published = [{"workflow_id": WF_A, "version_id": "va", "at": _iso(5)},
                 {"workflow_id": WF_B, "version_id": "vb", "at": _iso(4)}]
    grants = [{"event": "grant-issued", "tier": "config-write", "seconds": 3600, "ts": _iso(5.1),
               "reason": f"activate {WF_A}" + (f" and {WF_B}" if grant_both else "")}]
    if grant_both:
        grants.append({"event": "grant-issued", "tier": "config-write", "seconds": 3600, "ts": _iso(4.1),
                       "reason": f"activate {WF_B}"})
    else:
        grants.append({"event": "grant-issued", "tier": "release-write", "seconds": 3600, "ts": _iso(4.1),
                       "reason": "release unrelated"})
    (home / "logs" / "cursor-agent-audit.jsonl").write_text(
        "\n".join(json.dumps(x) for x in grants) + "\n{torn line\n", encoding="utf-8")
    if hook:
        (home / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
            {"type": "command", "command": "TRADEAI_AGENTS_GUARD_MODE=log /usr/bin/python3 x/agents_guard_pretooluse.py"}]}]}}))
    else:
        (home / ".claude" / "settings.json").write_text(json.dumps({"hooks": {}}))
    cron = ("# comment check_n8n_activation_grants\n"
            "5 6 * * * $PY scripts/check_n8n_activation_grants.py --write\n") if schedule else "0 1 * * * true\n"
    timers = "NEXT LEFT UNIT\nx y tradeai-n8n-workflow-drift-check.timer\n" if schedule else "NEXT LEFT UNIT\n"
    handlers = {
        _is_psql: _n8n_sql(workflows, published),
        lambda a: a[0] == "crontab": lambda a: cron,
        lambda a: a[:3] == ["systemctl", "--user", "list-timers"]: lambda a: timers,
    }
    return handlers, receipts


def _write_gov_receipts(probe: core.Probe, age_h: float = 2.0, fanin: bool = True):
    for rel in (GOV["p16"]["receipt"], GOV["p18"]["receipt"]):
        p = probe.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"as_of": _iso(age_h), "fanin_wired": fanin}))


def test_governance_all_gates_met_scores_10(tmp_path):
    handlers, _ = _gov_world(tmp_path)
    probe = _probe(tmp_path, FakeRunner(handlers))
    _write_gov_receipts(probe)
    r = g.collect_governance(probe)
    assert r["status"] == core.VERIFIED
    assert r["gate"]["pass"] is True
    assert r["score"] == 10.0
    m = r["metrics"]
    assert m["active_workflows"] == 2 and m["active_granted"] == 2
    assert m["p16"]["scheduled_by"] == ["crontab"]
    assert m["p18"]["scheduled_by"] == ["systemd-timer"]
    assert m["guard_hook"]["mode"] == "log"


def test_governance_partial_grants_and_no_hook_are_capped(tmp_path):
    handlers, _ = _gov_world(tmp_path, grant_both=False, hook=False)
    probe = _probe(tmp_path, FakeRunner(handlers))
    _write_gov_receipts(probe)
    r = g.collect_governance(probe)
    subs = r["metrics"]["sub_scores"]
    assert subs["grants"] == pytest.approx(4.0)            # 1/2 granted → ratio_score(0.5, 1) = 4.0
    assert subs["guard_hook_installed"] == 0.0
    assert r["gate"]["pass"] is False
    assert r["score"] == pytest.approx((4.0 + 10 + 10 + 0) / 4)
    assert r["metrics"]["ungranted_ids"] == [WF_B]


def test_governance_stale_receipt_and_unscheduled_halves(tmp_path):
    handlers, _ = _gov_world(tmp_path, schedule=False)
    probe = _probe(tmp_path, FakeRunner(handlers))
    _write_gov_receipts(probe, age_h=40)                    # > 26 h → neither fresh nor alerting
    r = g.collect_governance(probe)
    assert r["metrics"]["sub_scores"]["p16_scheduled_alerting"] == 0.0
    assert r["metrics"]["p16"]["alerting"] is False
    probe2 = _probe(tmp_path, FakeRunner(handlers))
    _write_gov_receipts(probe2, age_h=1)
    r2 = g.collect_governance(probe2)
    w = GOV["check_weights"]
    frac = (w["receipt_fresh"] + w["alerting"]) / sum(w.values())  # fresh + alerting, unscheduled
    assert r2["metrics"]["sub_scores"]["p16_scheduled_alerting"] == pytest.approx(core.ratio_score(frac, 1.0))
    assert r2["score"] < 8.0 and r2["gate"]["pass"] is False


def test_governance_unwired_receipt_is_not_alerting(tmp_path):
    handlers, _ = _gov_world(tmp_path)
    probe = _probe(tmp_path, FakeRunner(handlers))
    _write_gov_receipts(probe, age_h=1, fanin=False)        # scheduled + fresh, but nothing alerts
    r = g.collect_governance(probe)
    w = GOV["check_weights"]
    frac = (w["scheduled"] + w["receipt_fresh"]) / sum(w.values())
    assert r["metrics"]["p16"]["alerting"] is False
    assert r["metrics"]["sub_scores"]["p16_scheduled_alerting"] == pytest.approx(core.ratio_score(frac, 1.0))
    assert r["gate"]["pass"] is False


def test_governance_future_dated_receipt_is_not_fresh(tmp_path):
    handlers, _ = _gov_world(tmp_path)
    probe = _probe(tmp_path, FakeRunner(handlers))
    _write_gov_receipts(probe, age_h=-5)                    # written "in the future" → not proof of a run
    r = g.collect_governance(probe)
    assert r["metrics"]["p16"]["receipt_fresh"] is False and r["metrics"]["p16"]["alerting"] is False
    assert r["gate"]["pass"] is False


def test_governance_zero_active_workflows_is_not_full_coverage(tmp_path):
    handlers, _ = _gov_world(tmp_path)
    handlers[_is_psql] = _n8n_sql([{"id": "x", "name": "n", "active": False, "versionId": "v"}], [])
    probe = _probe(tmp_path, FakeRunner(handlers))
    _write_gov_receipts(probe)
    r = g.collect_governance(probe)
    assert r["metrics"]["sub_scores"]["grants"] is None
    assert r["status"] == core.PARTIAL and r["gate"]["pass"] is False and r["score"] <= GATE_CAP


def test_governance_db_down_marks_grants_unverified_partial(tmp_path):
    handlers, _ = _gov_world(tmp_path)
    probe = _probe(tmp_path, FakeRunner(handlers, fail={"docker"}))
    _write_gov_receipts(probe)
    r = g.collect_governance(probe)
    assert r["status"] == core.PARTIAL
    assert r["metrics"]["sub_scores"]["grants"] is None
    assert r["gate"]["pass"] is False and r["score"] <= GATE_CAP


def test_governance_no_evidence_is_unverified_zero(tmp_path):
    probe = _probe(tmp_path, FakeRunner({}, fail={"docker", "crontab", "systemctl"}))
    r = g.collect_governance(probe)
    assert r["status"] == core.UNVERIFIED
    assert r["score"] == 0.0 and r["gate"]["pass"] is False


# ================================================================================================
# security fixtures
# ================================================================================================

def _served(tmp_path: Path, *, p7_code=True, relay_code=True, lane_modes=("enforce", "enforce")) -> Path:
    s = tmp_path / "served"
    (s / "scripts" / "lib").mkdir(parents=True, exist_ok=True)
    (s / "config").mkdir(parents=True, exist_ok=True)
    if relay_code:
        (s / "scripts" / "lib" / "n8n_relay_env.py").write_text("RELAY_SECRET_NAMES = ()\n")
    (s / "scripts" / "n8n_run_executor.py").write_text(
        ('ENV_ALLOWLIST_MODE_ENV = "TRADEAI_EXECUTOR_ENV_ALLOWLIST"\n' if p7_code else "x = 1\n"))
    lanes = [{"lane_id": f"l{i}", "env_names": [], **({"env_allowlist_mode": m} if m else {})}
             for i, m in enumerate(lane_modes)]
    (s / "config" / "n8n_run_allowlist.json").write_text(json.dumps({"lanes": lanes}))
    return s


def _sec_handlers(*, relay_files="/run/user/1/tradeai/n8n-relay-secrets.env (ignore_errors=yes)",
                  exec_mode="enforce", roles=None, db_user="n8n_app", app_env=("DB_POSTGRESDB_PASSWORD_FILE", "N8N_X"),
                  db_env=("POSTGRES_PASSWORD_FILE",), compose_path="/nonexistent/compose.yml"):
    unit_file = Path(tempfile.mkdtemp(prefix="n8nmat-unit-")) / "executor.service"
    roles = roles if roles is not None else [{"rolname": "n8n", "super": True, "createrole": True},
                                             {"rolname": "n8n_app", "super": False, "createrole": False}]

    def inspect(a):
        fmt = a[-1]
        name = a[2]
        if "config_files" in fmt:
            return compose_path
        if g.DB_USER_ENV in fmt:
            return f"{g.DB_USER_ENV}={db_user}"
        if 'split . "="' in fmt:
            return "\n".join(app_env if name == APP else db_env) + "\n"
        return 1, "", "?"

    def show(a):
        unit = a[3]
        if unit == SEC["relay_unit"]:
            return "\n".join(f"EnvironmentFiles={f}" for f in relay_files.split("|") if f) + "\nLoadState=loaded\n"
        if unit == SEC["executor_unit"]:
            assert "Environment" not in a, "the scorer must never request a unit's Environment= values"
            mode = f" TRADEAI_EXECUTOR_ENV_ALLOWLIST={exec_mode}" if exec_mode else ""
            unit_file.write_text(f"[Service]\nEnvironment=PROJ=/p SOME_TOKEN={SECRET_VALUE}{mode}\n")
            return f"FragmentPath={unit_file}\nDropInPaths=\n"
        return 1, "", "?"

    return {
        _is_psql: lambda a: json.dumps(roles),
        lambda a: a[:2] == ["docker", "inspect"]: inspect,
        lambda a: a[:3] == ["systemctl", "--user", "show"]: show,
    }


def _clean_compose(tmp_path: Path) -> str:
    c = tmp_path / "compose.clean.yml"
    c.write_text("environment:\n  - DB_POSTGRESDB_PASSWORD_FILE=/run/secrets/pg\n  - N8N_X=1\n")
    return str(c)


def test_security_all_four_done_scores_10(tmp_path):
    served = _served(tmp_path)
    probe = _probe(tmp_path, FakeRunner(_sec_handlers(compose_path=_clean_compose(tmp_path))),
                   dims={"security": {"served_code_root": str(served)}})
    r = g.collect_security(probe)
    assert r["status"] == core.VERIFIED, r["notes"]
    assert r["gate"]["pass"] is True and r["score"] == 10.0
    assert r["metrics"]["p7"] == {"code_served": True, "global_mode": "enforce", "lanes": 2, "lanes_enforced": 2}


def test_security_baseline_shape_scores_low_and_fails(tmp_path):
    served = _served(tmp_path, p7_code=False, relay_code=False)
    compose = tmp_path / "compose.yml"
    compose.write_text("environment:\n  - DB_POSTGRESDB_PASSWORD=${N8N_PG_PASSWORD}\n  POSTGRES_PASSWORD: hunter2\n")
    h = _sec_handlers(relay_files="/run/user/1/tradeai/env (ignore_errors=yes)|/x/n8n-relay.env (ignore_errors=yes)",
                      exec_mode=None, roles=[{"rolname": "n8n", "super": True, "createrole": True}], db_user="n8n",
                      app_env=("DB_POSTGRESDB_PASSWORD", "N8N_ENCRYPTION_KEY"), db_env=("POSTGRES_PASSWORD",),
                      compose_path=str(compose))
    probe = _probe(tmp_path, FakeRunner(h), dims={"security": {"served_code_root": str(served)}})
    r = g.collect_security(probe)
    subs = r["metrics"]["sub_scores"]
    assert subs == {"relay_env_allowlist": 0.0, "p7_executor_env_allowlist": 0.0, "n8n_app_role": 0.0,
                    "password_out_of_env": 0.0}
    assert r["metrics"]["password_out"]["compose_literal_password_keys"] == ["POSTGRES_PASSWORD"]
    assert r["score"] == 0.0 and r["gate"]["pass"] is False
    assert r["metrics"]["p7"] == {"code_served": False}


def test_security_staged_credit_below_gate(tmp_path):
    served = _served(tmp_path, lane_modes=("enforce", "report"))
    h = _sec_handlers(relay_files="/run/user/1/tradeai/env (ignore_errors=yes)", db_user="n8n",
                      compose_path=_clean_compose(tmp_path))
    probe = _probe(tmp_path, FakeRunner(h), dims={"security": {"served_code_root": str(served)}})
    r = g.collect_security(probe)
    subs = r["metrics"]["sub_scores"]
    assert subs["relay_env_allowlist"] == pytest.approx(core.ratio_score(0.25, 1.0))   # code served, unit not cut
    assert subs["p7_executor_env_allowlist"] == pytest.approx(core.ratio_score(0.25 + 0.75 * 0.5, 1.0))
    rw = SEC["app_role_weights"]
    assert subs["n8n_app_role"] == pytest.approx(
        core.ratio_score((rw["exists"] + rw["least_privilege"]) / sum(rw.values()), 1.0))  # role exists, unused
    assert subs["password_out_of_env"] == 10.0
    assert r["gate"]["pass"] is False and r["score"] <= GATE_CAP


def test_security_never_emits_env_values(tmp_path):
    served = _served(tmp_path)
    runner = FakeRunner(_sec_handlers())
    probe = _probe(tmp_path, runner, dims={"security": {"served_code_root": str(served)}})
    r = g.collect_security(probe)
    blob = json.dumps(r, default=str) + json.dumps(probe.commands)
    assert SECRET_VALUE not in blob
    # container env is only ever read through the names-only template or the single DB-user key
    for a in runner.calls:
        if a[:2] == ["docker", "inspect"]:
            fmt = a[-1]
            assert ('split . "="' in fmt and "{{.}}" not in fmt) or g.DB_USER_ENV in fmt or "config_files" in fmt


def test_security_empty_inputs_never_pass(tmp_path):
    served = _served(tmp_path, lane_modes=())               # P7 code served but 0 allowlisted lanes
    h = _sec_handlers(roles=[], app_env=(), db_env=())     # empty pg_roles, empty env-name lists, no compose
    probe = _probe(tmp_path, FakeRunner(h), dims={"security": {"served_code_root": str(served)}})
    r = g.collect_security(probe)
    subs = r["metrics"]["sub_scores"]
    assert subs["p7_executor_env_allowlist"] is None
    assert subs["n8n_app_role"] is None
    assert subs["password_out_of_env"] is None
    assert r["gate"]["pass"] is False and r["score"] <= GATE_CAP


def test_security_unread_executor_mode_is_not_enforce(tmp_path):
    served = _served(tmp_path)
    h = _sec_handlers(exec_mode=None, compose_path=_clean_compose(tmp_path))
    probe = _probe(tmp_path, FakeRunner(h), dims={"security": {"served_code_root": str(served)}})
    r = g.collect_security(probe)
    assert r["metrics"]["p7"]["lanes_enforced"] == 0 and r["metrics"]["p7"]["global_mode"] is None
    assert any("not counted as enforce" in n for n in r["notes"])
    assert r["gate"]["pass"] is False


def test_security_unread_container_db_user_is_not_scored(tmp_path):
    served = _served(tmp_path)
    h = _sec_handlers(db_user="", compose_path=_clean_compose(tmp_path))
    probe = _probe(tmp_path, FakeRunner(h), dims={"security": {"served_code_root": str(served)}})
    assert g.collect_security(probe)["metrics"]["sub_scores"]["n8n_app_role"] is None


def test_security_everything_unreadable_is_unverified(tmp_path):
    probe = _probe(tmp_path, FakeRunner({}, fail={"docker", "systemctl"}),
                   dims={"security": {"served_code_root": str(tmp_path / "nope")}})
    r = g.collect_security(probe)
    assert r["status"] == core.UNVERIFIED and r["score"] == 0.0


# ================================================================================================
# CI signal
# ================================================================================================

def _ci_repo(tmp_path: Path, worktree: bool = True):
    proj = tmp_path / "repo"
    wf = proj / ".github" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    (wf / "nightly.yml").write_text("on:\n  schedule:\n    - cron: \"17 7 * * *\"\njobs:\n  x:\n")
    (wf / "sharded.yml").write_text("on:\n  pull_request:\njobs:\n  ci-gate:\n    name: ci-gate\n")
    common = tmp_path / "common.git"
    (common / "worktrees" / "wt").mkdir(parents=True, exist_ok=True)
    (common / "config").write_text('[core]\n\tbare = false\n[remote "origin"]\n\turl = git@github.com:Owner/repo-x.git\n'
                                    '\tfetch = +refs/heads/*:refs/remotes/origin/*\n')
    if worktree:
        (common / "worktrees" / "wt" / "commondir").write_text("../..\n")
        (proj / ".git").write_text(f"gitdir: {common / 'worktrees' / 'wt'}\n")


def _runs_handler(nightly: list[dict], gate: list[dict]):
    def h(a):
        wf = a[a.index("--workflow") + 1]
        return json.dumps(nightly if wf == "nightly.yml" else gate)
    return {lambda a: a[:3] == ["gh", "run", "list"]: h}


def _run(hours_ago, conclusion="success", event="schedule", status="completed"):
    return {"createdAt": _iso(hours_ago), "conclusion": conclusion, "event": event, "status": status,
            "headSha": "abcdef1234567890"}


def test_ci_both_green_with_week_streak_scores_10(tmp_path):
    _ci_repo(tmp_path)
    nightly = [_run(10 + 24 * i) for i in range(8)]
    gate = [_run(3, event="push"), _run(1, event="pull_request", conclusion="failure")]
    runner = FakeRunner(_runs_handler(nightly, gate))
    r = g.collect_ci_signal(_probe(tmp_path, runner))
    assert r["metrics"]["repo"] == "Owner/repo-x"
    assert r["metrics"]["nightly_workflow"] == "nightly.yml" and r["metrics"]["ci_gate_workflow"] == "sharded.yml"
    assert r["score"] == 10.0 and r["gate"]["pass"] is True
    assert all(a[a.index("-R") + 1] == "Owner/repo-x" for a in runner.calls)


def test_ci_short_streak_passes_between_8_and_10(tmp_path):
    _ci_repo(tmp_path)
    nightly = [_run(10), _run(34, conclusion="failure"), _run(9, status="in_progress", conclusion="")]
    gate = [_run(3, event="push")]
    r = g.collect_ci_signal(_probe(tmp_path, FakeRunner(_runs_handler(nightly, gate))))
    assert r["metrics"]["nightly"]["green_streak"] == 1
    assert r["score"] == pytest.approx((8.0 + 2.0 / 7 + 10.0) / 2, abs=0.01)
    assert r["gate"]["pass"] is True


def test_ci_red_nightly_and_no_main_gate_run_fail(tmp_path):
    _ci_repo(tmp_path)
    nightly = [_run(12, conclusion="failure"), _run(36)]
    gate = [_run(2, event="pull_request")]
    r = g.collect_ci_signal(_probe(tmp_path, FakeRunner(_runs_handler(nightly, gate))))
    assert r["score"] == 0.0 and r["gate"]["pass"] is False
    assert r["metrics"]["ci_gate"]["main_runs"] == 0
    assert r["metrics"]["sub_scores"]["ci_gate_green_on_main"] is None      # no main run → UNVERIFIED, not 0
    assert r["status"] == core.PARTIAL
    assert any("no completed run on main" in n for n in r["notes"])


def test_ci_no_runs_on_main_at_all_is_unverified_not_zero_verified(tmp_path):
    _ci_repo(tmp_path)
    r = g.collect_ci_signal(_probe(tmp_path, FakeRunner(_runs_handler([], [_run(2, event="pull_request")]))))
    assert r["metrics"]["sub_scores"] == {"nightly_green": None, "ci_gate_green_on_main": None}
    assert r["status"] == core.UNVERIFIED and r["score"] == 0.0


def test_ci_in_progress_only_runs_are_unverified(tmp_path):
    _ci_repo(tmp_path)
    pending = [_run(1, status="in_progress", conclusion="")]
    r = g.collect_ci_signal(_probe(tmp_path, FakeRunner(_runs_handler(pending, [_run(1, event="push", status="queued",
                                                                                         conclusion="")]))))
    assert r["status"] == core.UNVERIFIED


def test_ci_stale_green_nightly_is_not_met(tmp_path):
    _ci_repo(tmp_path)
    r = g.collect_ci_signal(_probe(tmp_path, FakeRunner(_runs_handler([_run(40)], [_run(3, event="push")]))))
    assert r["metrics"]["sub_scores"]["nightly_green"] == 0.0
    assert r["gate"]["pass"] is False and r["score"] <= GATE_CAP


def test_ci_gh_failure_is_unverified(tmp_path):
    _ci_repo(tmp_path)
    r = g.collect_ci_signal(_probe(tmp_path, FakeRunner({}, fail={"gh"})))
    assert r["status"] == core.UNVERIFIED and r["score"] == 0.0


def test_ci_repo_override_and_missing_slug(tmp_path):
    (tmp_path / "repo").mkdir()
    r = g.collect_ci_signal(_probe(tmp_path, FakeRunner({})))
    assert r["status"] == core.UNVERIFIED
    _ci_repo(tmp_path, worktree=False)
    r2 = g.collect_ci_signal(_probe(tmp_path, FakeRunner(_runs_handler([_run(5)], [_run(5, event="push")])),
                                    dims={"ci_signal": {"repo": "Cfg/override"}}))
    assert r2["metrics"]["repo"] == "Cfg/override"


# ================================================================================================
# docs synced
# ================================================================================================

AGENTS_OK = """# AGENTS
```
Policy-Version: 3.0.0
Status: ACTIVE
Effective-Date: 2026-10-09
```
See `scripts/real.py` and `docs/ops/RUNBOOK.md`.

| Version | Date | Status | Class | Approval |
|---|---|---|---|---|
| 3.0.0 | 2026-10-09 | ACTIVE | MAJOR | ratified |
| 2.0.0 | 2026-10-08 | ACTIVE | MAJOR | ratified |
"""


def _docs_repo(tmp_path: Path, *, adr_text="Policy: AGENTS.md 3.0.0 ACTIVE\n", runbook_extra="", agents=AGENTS_OK):
    proj = tmp_path / "repo"
    for d in ("scripts", "docs/ops", "docs/architecture/n8n"):
        (proj / d).mkdir(parents=True, exist_ok=True)
    (proj / "scripts" / "real.py").write_text("")
    if agents is not None:
        (proj / "AGENTS.md").write_text(agents)
    (proj / "docs" / "architecture" / "n8n" / "ADR.md").write_text(adr_text)
    (proj / "docs" / "ops" / "RUNBOOK.md").write_text("units: a.service b.service\n" + runbook_extra)
    (proj / "scripts" / "deploy.sh").write_text('local units="${TRADEAI_CURRENT_BOUND_UNITS:-a.service b.service}"\n')


DOCS_CFG = {"docs_synced": {"adr_paths": ["docs/architecture/n8n/ADR.md"], "runbook_paths": ["docs/ops/*.md"],
                            "unit_runbooks": ["docs/ops/RUNBOOK.md"], "deploy_script": "scripts/deploy.sh"}}


def test_docs_zero_drift_scores_10(tmp_path):
    _docs_repo(tmp_path)
    r = g.collect_docs_synced(_probe(tmp_path, FakeRunner({}), dims=DOCS_CFG))
    assert r["metrics"]["drift_findings"] == 0, r["metrics"]
    assert r["score"] == 10.0 and r["gate"]["pass"] is True and r["status"] == core.VERIFIED


def test_docs_counts_each_finding_kind(tmp_path):
    _docs_repo(tmp_path, adr_text="Amended by 3.0.0 PROPOSED; see `docs/missing.md`, `scripts/gone.py:12` and `scripts/*.py`\n")
    (tmp_path / "repo" / "docs" / "ops" / "RUNBOOK.md").write_text("units: b.service\n")
    r = g.collect_docs_synced(_probe(tmp_path, FakeRunner({}), dims=DOCS_CFG))
    by = r["metrics"]["by_check"]
    assert by == {"agents_policy_state": 0, "stale_proposed": 1, "dangling_refs": 2, "runbook_units": 1}
    # 4 findings → gate_score × (1 − 4/findings_zero_at) = 8 × (1 − 4/20) = 6.4
    assert r["score"] == pytest.approx(6.4) and r["gate"]["pass"] is False


def test_docs_one_finding_is_below_gate(tmp_path):
    _docs_repo(tmp_path, adr_text="see `docs/gone.md`\n")
    r = g.collect_docs_synced(_probe(tmp_path, FakeRunner({}), dims=DOCS_CFG))
    assert r["metrics"]["drift_findings"] == 1
    assert r["score"] == pytest.approx(7.6) and r["gate"]["pass"] is False


def test_docs_agents_policy_state_error_counts(tmp_path):
    bad = AGENTS_OK.replace("| 3.0.0 | 2026-10-09 | ACTIVE |", "| 3.0.0 | 2026-10-09 | PROPOSED |")
    _docs_repo(tmp_path, agents=bad)
    r = g.collect_docs_synced(_probe(tmp_path, FakeRunner({}), dims=DOCS_CFG))
    assert r["metrics"]["by_check"]["agents_policy_state"] == 1


def test_docs_missing_agents_is_partial_and_fails_gate(tmp_path):
    _docs_repo(tmp_path, agents=None)
    r = g.collect_docs_synced(_probe(tmp_path, FakeRunner({}), dims=DOCS_CFG))
    assert r["status"] == core.PARTIAL
    assert r["gate"]["pass"] is False and r["score"] <= GATE_CAP


def test_docs_no_adr_or_runbook_in_scope_is_not_a_clean_pass(tmp_path):
    _docs_repo(tmp_path)
    cfg = {"docs_synced": {**DOCS_CFG["docs_synced"], "adr_paths": ["docs/nope/*.md"],
                           "runbook_paths": ["docs/nope2/*.md"]}}
    r = g.collect_docs_synced(_probe(tmp_path, FakeRunner({}), dims=cfg))
    assert r["metrics"]["checks_ran"]["stale_proposed"] is False
    assert r["status"] == core.PARTIAL and r["gate"]["pass"] is False and r["score"] <= GATE_CAP


def test_docs_missing_in_scope_doc_fails_gate(tmp_path):
    _docs_repo(tmp_path)
    cfg = {"docs_synced": {**DOCS_CFG["docs_synced"],
                           "runbook_paths": ["docs/ops/*.md", "docs/ops/NOT_THERE.md"]}}
    r = g.collect_docs_synced(_probe(tmp_path, FakeRunner({}), dims=cfg))
    assert r["metrics"]["drift_findings"] == 0
    assert "docs/ops/NOT_THERE.md" in r["metrics"]["docs_missing"]
    assert r["status"] == core.PARTIAL and r["gate"]["pass"] is False


def test_docs_no_bound_units_means_unit_check_did_not_run(tmp_path):
    _docs_repo(tmp_path)
    (tmp_path / "repo" / "scripts" / "deploy.sh").write_text('local units="${TRADEAI_CURRENT_BOUND_UNITS:-}"\n')
    r = g.collect_docs_synced(_probe(tmp_path, FakeRunner({}), dims=DOCS_CFG))
    assert r["metrics"]["checks_ran"]["runbook_units"] is False
    assert r["gate"]["pass"] is False


def test_docs_nothing_readable_is_unverified(tmp_path):
    (tmp_path / "repo").mkdir()
    r = g.collect_docs_synced(_probe(tmp_path, FakeRunner({}), dims=DOCS_CFG))
    assert r["status"] == core.UNVERIFIED and r["score"] == 0.0


# ================================================================================================
# boundaries + registration
# ================================================================================================

@pytest.mark.parametrize("frac,expected", [(1.0, 10.0), (0.999, core.ratio_score(0.999, 1.0)), (0.0, 0.0), (None, None)])
def test_met_score_boundary(frac, expected):
    gs = float(REAL_CONFIG["gate_score"])
    assert g._met_score(frac, gs) == expected
    if frac is not None and frac < 1.0:
        assert g._met_score(frac, gs) < gs


def test_collectors_registered_and_deterministic(tmp_path):
    assert set(g.COLLECTORS) == {"governance", "security", "ci_signal", "docs_synced"}
    _docs_repo(tmp_path)
    a = g.collect_docs_synced(_probe(tmp_path, FakeRunner({}), dims=DOCS_CFG))
    b = g.collect_docs_synced(_probe(tmp_path, FakeRunner({}), dims=DOCS_CFG))
    assert a == b


def test_every_command_is_on_the_read_only_allowlist(tmp_path):
    handlers, _ = _gov_world(tmp_path)
    served = _served(tmp_path)
    handlers.update(_sec_handlers(compose_path=_clean_compose(tmp_path)))
    _ci_repo(tmp_path)
    handlers.update(_runs_handler([_run(5)], [_run(5, event="push")]))
    runner = FakeRunner(handlers)
    probe = _probe(tmp_path, runner, dims={"security": {"served_code_root": str(served)}})
    _write_gov_receipts(probe)
    for collect in g.COLLECTORS.values():
        collect(probe)
    assert runner.calls
    bad = [a for a in runner.calls if not core.is_read_only(a)]
    assert not bad, bad
    psql = [a for a in runner.calls if "psql" in a]
    assert psql, "governance/security must read the n8n DB"
    for a in psql:
        assert a[:5] == ["docker", "exec", "-e", f"PGOPTIONS={core.PG_READ_ONLY_OPTIONS}", DBC]
        assert core.is_safe_sql(a[a.index("-c") + 1])
    exes = {a[0] for a in runner.calls}
    assert exes <= {"docker", "crontab", "systemctl", "gh"}
    assert not any(a[:2] == ["gh", "api"] or a[0] == "git" for a in runner.calls)


def test_n8n_sql_is_safe():
    assert core.is_safe_sql(g.PG_ROLES_SQL)
    p16 = g._load_module("p16", "scripts/check_n8n_activation_grants.py")
    for name in ("WORKFLOW_LIST_SQL", "PUBLISH_HISTORY_SQL", "PUBLISHED_VERSION_SQL", "VERSION_HISTORY_SQL"):
        assert core.is_safe_sql(getattr(p16.inv, name)), name


@pytest.mark.parametrize("dim,key", [
    ("governance", "receipt_max_age_hours"), ("governance", "check_weights"), ("governance", "n8n_db_user"),
    ("security", "code_stage_weight"), ("security", "app_role_weights"), ("security", "relay_unit"),
    ("ci_signal", "nightly_max_age_hours"), ("ci_signal", "nightly_streak_top"), ("ci_signal", "branch"),
    ("docs_synced", "findings_zero_at"), ("docs_synced", "runbook_paths"),
])
def test_missing_config_key_raises_config_error(tmp_path, dim, key):
    cfg = _config()
    del cfg["dimensions"][dim][key]
    probe = _probe(tmp_path, FakeRunner({}), config=cfg)
    with pytest.raises(core.ConfigError):
        g.COLLECTORS[dim](probe)


@pytest.mark.parametrize("top_key", ["gate_score", "gate_cap"])
def test_missing_top_level_gate_raises_config_error(tmp_path, top_key):
    cfg = _config()
    del cfg[top_key]
    probe = _probe(tmp_path, FakeRunner({}), config=cfg)
    for collect in g.COLLECTORS.values():
        with pytest.raises(core.ConfigError):
            collect(probe)


def test_window_hours_comes_from_config(tmp_path):
    handlers, _ = _gov_world(tmp_path)
    probe = _probe(tmp_path, FakeRunner(handlers), dims={"governance": {"window_hours": 2}})
    log = probe.root / GOV["guard_hook_log"]
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("\n".join(json.dumps({"ts": _iso(h)}) for h in (1, 3, 5)) + "\n")
    r = g.collect_governance(probe)
    assert r["metrics"]["guard_hook"]["window_hours"] == 2.0
    assert r["metrics"]["guard_hook"]["decisions_in_window"] == 1


# ================================================================================================
# round 2 (#1593 review)
# ================================================================================================

def test_r2_executor_mode_read_from_unit_files_never_environment_property(tmp_path):
    unit = tmp_path / "exec.service"
    unit.write_text("[Service]\nEnvironment=PROJ=/p TRADEAI_EXECUTOR_ENV_ALLOWLIST=report\n")
    dropin = tmp_path / "override.conf"
    dropin.write_text(f"[Service]\nEnvironment=\"TRADEAI_EXECUTOR_ENV_ALLOWLIST=enforce\" SOME_TOKEN={SECRET_VALUE}\n")
    calls: list[list[str]] = []

    def show(a):
        calls.append(a)
        return f"FragmentPath={unit}\nDropInPaths={dropin}\n"

    probe = _probe(tmp_path, FakeRunner({lambda a: a[:3] == ["systemctl", "--user", "show"]: show}))
    assert g._unit_env_value(probe, "x.service", "TRADEAI_EXECUTOR_ENV_ALLOWLIST") == "enforce"  # drop-in wins
    assert calls and all("Environment" not in a for a in calls)
    assert all(core.is_read_only(a) for a in calls)


def test_r2_governance_cap_uses_shared_config_helper(tmp_path):
    served = _served(tmp_path, lane_modes=("enforce", "report"))
    h = _sec_handlers(relay_files="/run/user/1/tradeai/env (ignore_errors=yes)", db_user="n8n",
                      compose_path=_clean_compose(tmp_path))
    cfg = _config({"security": {"served_code_root": str(served)}})
    cfg["gate_cap"] = 1.5
    r = g.collect_security(_probe(tmp_path, FakeRunner(h), config=cfg))
    assert not r["gate"]["pass"] and r["score"] == 1.5
