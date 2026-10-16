"""Read-only broker sync (scripts/ops/broker_read_sync.sh; AGENTS.md 14.0.0 §24.11, PROPOSED) — hermetic tests.

Operator 2026-10-16: "make that bash so agents can run, make amendment, not trading just reading".

Pins: the step allowlist is closed and exact; the CLI takes only --plan/--apply and dry run is the default; every
refusal fires on its own (no grant, trading lock unlocked, Schwab mode not read_only, capability found, not the served
release, no .env); the capability audit of the real step closures is clean and goes red when an excluded family
(stop manager, stop sync, options lifecycle, defense execution, order pilot ...) is added or a stub is missing; the
runtime guards refuse excluded imports, order/re-auth functions, broker-host writes and child Pythons; output is
scrubbed; needs_operator_reauth stops the run; the receipt carries per-step rc and per-account status.

Never contacts a broker: steps are replaced by fake runners, the guard checks run before any network call, and the
runtime-guard probe only imports modules. TRADE_AI_CI=1.
"""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lib import broker_read_sync_policy as P  # noqa: E402
from scripts.ops import broker_read_sync as S  # noqa: E402
from scripts.ops import broker_read_sync_child as C  # noqa: E402

EXPECTED_STEPS = (
    ("schwab_positions", "scripts/schwab_position_sync.py", (), ("--apply",)),
    ("schwab_transactions", "scripts/schwab_transaction_ingest.py", ("--days", "7"), ("--days", "7", "--apply")),
    ("alpaca_live_read", "scripts/alpaca_live_read_sync.py", ("--dry-run",), ()),
    ("moomoo_live_read", "scripts/moomoo_live_read_sync.py", ("--dry-run",), ()),
    ("snaptrade", "scripts/snaptrade_sync.py", (), ("--apply",)),
    ("positions_store", "scripts/positions_sync.py", (), ("--apply",)),
    ("positions_fresh", "scripts/positions_sync.py", None, ("--check-fresh",)),
    ("stop_health", "scripts/stop_health_check.py", ("--quiet",), ("--quiet",)),
)


# ------------------------------------------------------------------------------------------- closed allowlist


def test_step_allowlist_is_closed_and_exact():
    assert isinstance(P.STEPS, tuple)
    assert tuple((s.id, s.script, s.dry_argv, s.apply_argv) for s in P.STEPS) == EXPECTED_STEPS
    with pytest.raises(dataclasses.FrozenInstanceError):
        P.STEPS[0].script = "scripts/alpaca_stop_manager.py"  # type: ignore[misc]
    for s in P.STEPS:
        assert (ROOT / s.script).is_file(), s.script


@pytest.mark.parametrize("argv", [["schwab_positions"], ["--apply", "--plan"], ["--apply", "extra"],
                                  ["--", "--apply"], ["--days", "30"], ["--step", "stop_health"]])
def test_cli_accepts_nothing_but_plan_or_apply(argv):
    with pytest.raises(SystemExit) as exc:
        S.parse_args(argv)
    assert exc.value.code == 2


@pytest.mark.parametrize("argv", [["x"], ["--plan", "--apply"], ["--apply", "--apply"], ["--dry-run"]])
def test_wrapper_refuses_other_arguments_before_python(argv):
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash unavailable")
    out = subprocess.run([bash, str(ROOT / "scripts" / "ops" / "broker_read_sync.sh"), *argv],
                         capture_output=True, text=True, timeout=20, check=False)
    assert out.returncode == 64 and "closed allowlist" in out.stderr


@pytest.mark.parametrize("args", [["nope", "apply"], ["schwab_positions", "live"], ["schwab_positions"],
                                  ["positions_fresh", "dry_run"], ["stop_health", "apply", "--extra"]])
def test_child_refuses_anything_outside_the_allowlist(args, capsys):
    assert C.main(args) == C.EXIT_USAGE
    assert P.GUARD_MARK in capsys.readouterr().err


def test_dry_run_is_the_default_and_never_passes_apply():
    assert not S.parse_args([]).apply and not S.parse_args([]).plan
    for s in P.STEPS:
        dry = s.argv("dry_run")
        assert dry is None or "--apply" not in dry
    seen: list[tuple[str, tuple[str, ...]]] = []

    def runner(_root, step, mode):
        seen.append((step.id, step.argv(mode)))
        return 0, ""

    results, outcome = S.run_steps(ROOT, "dry_run", runner=runner, emit=lambda _l: None)
    assert outcome == "ok"
    assert [i for i, _ in seen] == [s.id for s in P.STEPS if s.dry_argv is not None]
    assert all("--apply" not in a for _, a in seen)


# ------------------------------------------------------------------------------------------------ refusals


def _fake_root(tmp_path: Path, env_file: bool = True) -> Path:
    root = tmp_path / "CURRENT"
    root.mkdir()
    if env_file:
        (root / ".env").write_text("", encoding="utf-8")
    return root


def _ok_kwargs(root: Path) -> dict:
    return dict(
        served=root,
        adir=root / "approvals",
        grant_fn=lambda _r, _a: {"active": True, "uses_left": 3},
        lock_fn=lambda: {b: {"locked": True, "reason": "test"} for b in P.LOCK_BROKERS},
        mode_fn=lambda _env: {"mode": "read_only", "source": "test"},
        audit_fn=lambda _r: {"ok": True, "findings": [], "steps": {}},
    )


def test_preflight_passes_when_every_condition_holds(tmp_path):
    root = _fake_root(tmp_path)
    assert S.preflight(root, need_grant=True, **_ok_kwargs(root))["refusals"] == []


@pytest.mark.parametrize(
    "override,expected",
    [
        ({"grant_fn": lambda _r, _a: {"active": False}}, ["broker_read_grant_missing"]),
        ({"lock_fn": lambda: {"schwab": {"locked": False}, "alpaca": {"locked": True}}},
         ["trading_lock_not_locked:schwab"]),
        ({"mode_fn": lambda _env: {"mode": "normal", "source": "env"}}, ["schwab_access_mode_not_read_only"]),
        ({"mode_fn": lambda _env: {"mode": "forbidden", "source": "file"}}, ["schwab_access_mode_not_read_only"]),
        ({"audit_fn": lambda _r: {"ok": False, "findings": [
            {"kind": "order_capability_unstubbed", "module": "scripts/x.py"}]}},
         ["capability_found:order_capability_unstubbed:scripts/x.py"]),
    ],
)
def test_each_refusal_fires_on_its_own(tmp_path, override, expected):
    root = _fake_root(tmp_path)
    kw = _ok_kwargs(root)
    kw.update(override)
    assert S.preflight(root, need_grant=True, **kw)["refusals"] == expected


def test_refuses_outside_the_served_release_and_without_env_file(tmp_path):
    root = _fake_root(tmp_path, env_file=False)
    kw = _ok_kwargs(root)
    kw["served"] = tmp_path / "elsewhere"
    assert S.preflight(root, need_grant=True, **kw)["refusals"] == ["not_served_release", "env_file_missing"]


def test_plan_needs_no_grant(tmp_path):
    root = _fake_root(tmp_path)
    kw = _ok_kwargs(root)
    kw["grant_fn"] = lambda _r, _a: {"active": False}
    assert S.preflight(root, need_grant=False, **kw)["refusals"] == []


def test_grant_is_read_from_the_real_ledger_format(tmp_path):
    import importlib.util
    import time

    spec = importlib.util.spec_from_file_location("gl_test", ROOT / ".cursor" / "hooks" / "guard_ledger.py")
    gl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gl)  # type: ignore[union-attr]
    adir = tmp_path / "approvals"
    adir.mkdir()
    gl.ledger_init_empty(adir)
    assert S.grant_state(ROOT, adir)["active"] is False
    gl.ledger_create_grant("service", expires=int(time.time()) + 600, uses=2, reason="other tier", adir=adir)
    assert S.grant_state(ROOT, adir)["active"] is False
    gl.ledger_create_grant("broker-read", expires=int(time.time()) + 600, uses=2, reason="test", adir=adir)
    st = S.grant_state(ROOT, adir)
    assert st["active"] is True and st["uses_left"] == 2
    assert S.consume_grant(ROOT, adir) is True
    assert S.grant_state(ROOT, adir)["uses_left"] == 1


def test_ledger_location_ignores_environment_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("GUARD_APPROVALS_DIR", str(tmp_path / "self-made"))
    monkeypatch.setenv("HOME", str(tmp_path))
    assert S.ledger_dir() == S.operator_home() / ".cursor" / "approvals"
    assert str(tmp_path) not in str(S.ledger_dir())


def test_child_environment_forces_read_only_and_drops_injection(monkeypatch):
    monkeypatch.setenv("TRADEAI_SCHWAB_ACCESS_MODE", "normal")
    monkeypatch.setenv("PYTHONPATH", "/tmp/evil")
    monkeypatch.setenv("BASH_ENV", "/tmp/evil.sh")
    monkeypatch.setenv("GUARD_APPROVALS_DIR", "/tmp/fake")
    env = S.child_env(ROOT)
    assert env["TRADEAI_SCHWAB_ACCESS_MODE"] == "read_only"
    for k in ("PYTHONPATH", "BASH_ENV", "GUARD_APPROVALS_DIR"):
        assert k not in env
    assert S.resolved_child_mode(env)["mode"] == "read_only"
    assert os.environ["TRADEAI_SCHWAB_ACCESS_MODE"] == "normal"  # the probe restores the caller's env


def test_boot_sources_env_only_in_the_step_shell_and_reexports_read_only():
    assert ". ./.env" in S.BOOT and "export TRADEAI_SCHWAB_ACCESS_MODE=read_only" in S.BOOT
    assert S.BOOT.index(". ./.env") < S.BOOT.index("export TRADEAI_SCHWAB_ACCESS_MODE=read_only")
    src = (ROOT / "scripts" / "ops" / "broker_read_sync.py").read_text(encoding="utf-8")
    assert "load_dotenv" not in src and "dotenv" not in src  # the orchestrator never parses .env


def test_main_refusal_writes_a_receipt_and_runs_no_step(tmp_path, monkeypatch):
    root = _fake_root(tmp_path)
    monkeypatch.setenv("TRADEAI_BROKER_READ_SYNC_RECEIPT_DIR", str(tmp_path / "receipts"))
    monkeypatch.setattr(S, "run_child", lambda *a: pytest.fail("a step ran despite a refusal"))
    monkeypatch.setattr(S, "consume_grant", lambda *a: pytest.fail("grant consumed despite a refusal"))
    kw = _ok_kwargs(root)
    kw["grant_fn"] = lambda _r, _a: {"active": False}
    lines: list[str] = []
    assert S.main(["--apply"], root=root, emit=lines.append, **kw) == S.EXIT_REFUSED
    doc = json.loads(next((tmp_path / "receipts").glob("*.json")).read_text())
    assert doc["schema"] == "BrokerReadSyncReceipt@v1" and doc["outcome"] == "refused"
    assert doc["refusals"] == ["broker_read_grant_missing"] and doc["steps"] == []
    assert any(line.startswith("REFUSED: broker_read_grant_missing") for line in lines)


def test_main_apply_runs_every_step_and_records_rc_and_accounts(tmp_path, monkeypatch):
    root = _fake_root(tmp_path)
    monkeypatch.setenv("TRADEAI_BROKER_READ_SYNC_RECEIPT_DIR", str(tmp_path / "receipts"))
    monkeypatch.setattr(S, "consume_grant", lambda *a: True)
    summary = {"mode": "APPLY", "status": "complete", "accounts_ok": ["schwab_roth", "alpaca_live"],
               "accounts_failed": ["snaptrade_x"]}
    outputs = {"positions_store": (0, json.dumps(summary)),
               "schwab_positions": (0, json.dumps({"schwab_ira": {"status": "applied", "wrote": True}}))}
    monkeypatch.setattr(S, "run_child", lambda _r, step, _m: outputs.get(step.id, (0, "ok")))
    assert S.main(["--apply"], root=root, emit=lambda _l: None, **_ok_kwargs(root)) == S.EXIT_OK
    doc = json.loads(next((tmp_path / "receipts").glob("*.json")).read_text())
    assert doc["outcome"] == "ok" and doc["mode"] == "apply"
    assert [s["id"] for s in doc["steps"]] == [s.id for s in P.STEPS]
    assert all(s["rc"] == 0 and s["status"] == "ok" for s in doc["steps"])
    assert doc["accounts"] == {"schwab_ira": "applied", "schwab_roth": "ok", "alpaca_live": "ok",
                               "snaptrade_x": "failed"}


# ------------------------------------------------------------------------------------- reauth, guard, failure


def _runner_with(first_output: str, rc: int = 0):
    calls: list[str] = []

    def runner(_root, step, _mode):
        calls.append(step.id)
        return (rc, first_output) if len(calls) == 1 else (0, "ok")

    return runner, calls


@pytest.mark.parametrize("text", ["degraded: no Schwab login token (manager is system-of-record)",
                                  '{"status": "degraded", "needs_reauth": true}',
                                  "HTTP 400 invalid_grant from token endpoint"])
def test_missing_token_reports_needs_operator_reauth_and_stops(text):
    runner, calls = _runner_with(text)
    results, outcome = S.run_steps(ROOT, "apply", runner=runner, emit=lambda _l: None)
    assert outcome == "needs_operator_reauth" and calls == ["schwab_positions"]
    assert results[0]["status"] == "needs_operator_reauth"


def test_auth_failure_exit_is_reauth_not_a_plain_failure():
    runner, calls = _runner_with("schwab: 401 Unauthorized", rc=1)
    _results, outcome = S.run_steps(ROOT, "apply", runner=runner, emit=lambda _l: None)
    assert outcome == "needs_operator_reauth" and len(calls) == 1


def test_guard_trip_stops_the_run():
    runner, calls = _runner_with(f"{P.GUARD_MARK}: import of scripts/api_v2.py refused", rc=66)
    _results, outcome = S.run_steps(ROOT, "apply", runner=runner, emit=lambda _l: None)
    assert outcome == "guard_tripped" and len(calls) == 1


def test_a_failed_step_is_partial_and_the_rest_still_run():
    runner, calls = _runner_with("Traceback: KeyError 'x'", rc=1)
    _results, outcome = S.run_steps(ROOT, "apply", runner=runner, emit=lambda _l: None)
    assert outcome == "partial" and len(calls) == len(P.STEPS)


# --------------------------------------------------------------------------------------------------- scrubbing


def _secrets() -> list[str]:
    # Assembled at runtime so no scanner mistakes the fixtures for real material.
    return [
        "eyJ" + "hbGciOi" * 3 + "." + "eyJzdWIi" * 3 + "." + "SflKxw" * 3,
        "Z9y8" * 10,
        "q1w2e3r4" * 2,
        "r2t3" * 12,
        "C0d3" * 6,
        "A1b2C3d4" * 6,
    ]


def test_scrub_removes_token_like_strings():
    jwt, bearer, secret, refresh, code, opaque = _secrets()
    text = "\n".join([
        f"token={jwt}",
        f"Authorization: Bearer {bearer}",
        f"SCHWAB_APP_SECRET={secret}",
        f'{{"refresh_token": "{refresh}", "status": "ok"}}',
        f"redirect https://127.0.0.1/cb?code={code}&state=1",
        f"opaque {opaque} end",
        f"plain {jwt}",
    ])
    out = S.scrub(text)
    for s in _secrets():
        assert s not in out, s
    assert out.count("[REDACTED") >= 7


@pytest.mark.parametrize("line", ["rc=0 status=ok", "accounts_ok: 3 position_rows 42 open_lots 17",
                                  "release 766914db2", "Schwab positions (3 accounts)", "acct ...1234 qty 10.5"])
def test_scrub_keeps_ordinary_output(line):
    assert S.scrub(line) == line


def test_step_output_is_scrubbed_before_print_and_receipt():
    jwt = _secrets()[0]
    printed: list[str] = []
    results, _ = S.run_steps(ROOT, "apply", runner=lambda *_a: (0, f"access_token={jwt}\ndone"),
                             emit=printed.append)
    assert jwt not in "\n".join(printed)
    assert jwt not in json.dumps(results)


# ------------------------------------------------------------------------------------------- capability audit


def test_real_step_closures_are_clean():
    """THE CI PIN: no order write, order route, stop writer, re-auth/refresh or direct sender is reachable in any
    step's effective closure outside the runtime stubs, and every stub target exists."""
    result = P.audit(ROOT)
    assert result["findings"] == [], json.dumps(result["findings"], indent=1)[:3000]
    steps = result["steps"]
    for sid in ("schwab_positions", "schwab_transactions"):
        assert "scripts/schwab_transport.py" in steps[sid]["stubbed_modules"]
        assert "scripts/schwab_token_manager.py" in steps[sid]["stubbed_modules"]
    assert "scripts/moomoo/client.py" in steps["moomoo_live_read"]["stubbed_modules"]
    denied = set().union(*(set(s["runtime_denied_modules"]) for s in steps.values()))
    assert {"scripts/brokers/options_order_pilot.py", "scripts/alpaca_stop_manager.py",
            "scripts/options_lifecycle_model.py"} <= denied


EXCLUDED_EXAMPLES = [
    ("scripts/alpaca_stop_manager.py", "stop_manager"),
    ("scripts/broker_stop_reconcile.py", "stop_sync"),
    ("scripts/lib/fidelity_stop_sync.py", "stop_sync"),
    ("scripts/brokers/protective_stop_pilot.py", "stop_writer"),
    ("scripts/schwab_oco_bracket.py", "stop_writer"),
    ("scripts/options_lifecycle_run.py", "options_lifecycle"),
    ("scripts/defense_execution.py", "defense_execution"),
    ("scripts/brokers/options_order_pilot.py", "order_pilot"),
    ("scripts/brokers/approval_service.py", "approval_2fa"),
    ("scripts/brokers/snaptrade_trade.py", "order_transport"),
    ("scripts/api_v2.py", "api_server"),
]


@pytest.mark.parametrize("rel,family", EXCLUDED_EXAMPLES)
def test_excluded_families_are_recognised(rel, family):
    assert P.excluded_family(rel) == family
    if rel not in P.READ_EXEMPT:
        assert P.runtime_denied(rel) == family


@pytest.mark.parametrize("rel,family", [e for e in EXCLUDED_EXAMPLES if (ROOT / e[0]).is_file()])
def test_adding_an_excluded_family_as_a_step_fails_the_audit(rel, family):
    extra = P.Step("added", "added", rel, (), ("--apply",), "schwab")
    result = P.audit(ROOT, steps=(extra,))
    assert {"step": "added", "kind": "excluded_entrypoint", "module": rel, "family": family} in result["findings"]


def test_the_excluded_examples_exist_in_the_repo():
    """Non-vacuous: the stop manager, defense execution, options lifecycle and order pilot files are real."""
    for rel in ("scripts/alpaca_stop_manager.py", "scripts/defense_execution.py", "scripts/options_lifecycle_run.py",
                "scripts/brokers/options_order_pilot.py", "scripts/brokers/protective_stop_pilot.py"):
        assert (ROOT / rel).is_file(), rel


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(body), encoding="utf-8")
    return root


def _audit_one(root: Path, script: str = "scripts/step.py") -> list[dict]:
    return P.audit(root, steps=(P.Step("s", "s", script, (), ("--apply",), "schwab"),))["findings"]


@pytest.mark.parametrize(
    "files,kind",
    [
        ({"scripts/step.py": "import helper\n", "scripts/helper.py": "def submit_order(x):\n    return x\n"},
         "order_capability_unstubbed"),
        ({"scripts/step.py": "import helper\n", "scripts/helper.py": "def exchange_code(u):\n    return u\n"},
         "reauth_capability_unstubbed"),
        ({"scripts/step.py": "import alpaca_stop_manager\n", "scripts/alpaca_stop_manager.py": "X = 1\n"},
         "excluded_module_eager"),
        ({"scripts/step.py": "import helper\n",
          "scripts/helper.py": "import requests\nURL = '/v1/accounts/abc/orders'\n"
                               "def go():\n    return requests.post(URL)\n"},
         "order_route_write"),
        ({"scripts/step.py": "import smtplib\n"}, "direct_sender"),
    ],
)
def test_audit_goes_red_on_each_capability(tmp_path, files, kind):
    findings = _audit_one(_tree(tmp_path, files))
    assert kind in {f["kind"] for f in findings}, findings


def test_lazy_excluded_import_is_pruned_not_failed(tmp_path):
    root = _tree(tmp_path, {
        "scripts/step.py": "def later():\n    import defense_execution\n",
        "scripts/defense_execution.py": "def submit_order():\n    pass\n",
    })
    result = P.audit(root, steps=(P.Step("s", "s", "scripts/step.py", (), (), "schwab"),))
    assert result["findings"] == []
    assert result["steps"]["s"]["runtime_denied_modules"] == ["scripts/defense_execution.py"]


def test_missing_stub_target_fails(tmp_path, monkeypatch):
    root = _tree(tmp_path, {"scripts/step.py": "import schwab_transport\n",
                            "scripts/schwab_transport.py": "def place_order():\n    pass\n"})
    findings = _audit_one(root)
    assert {"kind": "stub_target_missing", "module": "scripts/schwab_transport.py",
            "names": ["replace_order"]} in findings


# ------------------------------------------------------------------------------------------- runtime guards

PROBE = r"""
import sys, json
sys.path[:0] = [{root!r} + "/scripts", {root!r}]
from scripts.ops import broker_read_sync_child as C
sys.meta_path.insert(0, C.ImportGuard(C.ROOT))
C.install_http_guard()
C.install_subprocess_guard()
out = {{}}
def expect(name, fn, exc):
    try:
        fn()
        out[name] = "NOT REFUSED"
    except exc as e:
        out[name] = "refused" if C.MARK in str(e) else "wrong: " + str(e)[:80]
import schwab_transport, schwab_token_manager
from moomoo import client as mc
expect("place_order", lambda: schwab_transport.place_order("a", {{}}, None), C.BrokerReadSyncRefused)
expect("cancel_order", lambda: schwab_transport.cancel_order("a", "1"), C.BrokerReadSyncRefused)
expect("exchange_code", lambda: schwab_token_manager.exchange_code("a", "u"), C.BrokerReadSyncRefused)
expect("refresh", lambda: schwab_token_manager._refresh_access_token("a", "schwab", "live"), C.BrokerReadSyncRefused)
expect("moomoo_place", lambda: mc.MoomooClient.place_order(None), C.BrokerReadSyncRefused)
expect("import_pilot", lambda: __import__("brokers.options_order_pilot"), ImportError)
expect("import_stop_manager", lambda: __import__("alpaca_stop_manager"), ImportError)
expect("import_defense", lambda: __import__("defense_execution"), ImportError)
expect("import_lifecycle", lambda: __import__("options_lifecycle_model"), ImportError)
import urllib3, urllib.request, subprocess
expect("urllib3_post", lambda: urllib3.connectionpool.HTTPConnectionPool("api.schwabapi.com").urlopen("POST", "/v1/oauth/token"), C.BrokerReadSyncRefused)
expect("urllib_post", lambda: urllib.request.urlopen(urllib.request.Request("https://api.alpaca.markets/v2/orders", data=b"x")), C.BrokerReadSyncRefused)
try:
    import httpx
    expect("httpx_delete", lambda: httpx.Client().send(httpx.Request("DELETE", "https://api.schwabapi.com/trader/v1/accounts/h/orders/1")), C.BrokerReadSyncRefused)
except ImportError:
    out["httpx_delete"] = "refused"
expect("child_python", lambda: subprocess.run([sys.executable, "-c", "pass"]), C.BrokerReadSyncRefused)
out["get_allowed"] = C._check_http("GET", "https://api.schwabapi.com/trader/v1/accounts") is None
out["telegram_post_allowed"] = C._check_http("POST", "https://api.telegram.org/x") is None
out["git_allowed"] = subprocess.run(["true"]).returncode == 0
print(json.dumps(out))
"""


def test_runtime_guards_refuse_orders_reauth_writes_and_excluded_imports(tmp_path):
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "TRADE_AI_CI": "1", "PYTHONDONTWRITEBYTECODE": "1",
           "TRADEAI_SCHWAB_ACCESS_MODE": "read_only", "TRADEAI_TRADING_LOCK_AUDIT_PATH": str(tmp_path / "a.jsonl")}
    out = subprocess.run([sys.executable, "-c", PROBE.format(root=str(ROOT))], capture_output=True, text=True,
                         timeout=120, check=False, env=env, cwd=str(tmp_path))
    assert out.returncode == 0, out.stderr[-2000:]
    got = json.loads(out.stdout.strip().splitlines()[-1])
    for k, v in got.items():
        assert v in ("refused", True), (k, v)
    assert len(got) == 16


def test_child_refuses_when_mode_or_lock_is_wrong(monkeypatch, capsys):
    monkeypatch.setattr(C, "preconditions", lambda: ["trading_lock_not_locked (schwab)"])
    assert C.main(["stop_health", "apply"]) == C.EXIT_PRECONDITION
    assert "trading_lock_not_locked" in capsys.readouterr().err


def test_child_preconditions_read_the_real_switch_and_lock(monkeypatch, tmp_path):
    from lib import trading_lock as tl

    monkeypatch.setenv("TRADEAI_SCHWAB_ACCESS_MODE", "normal")
    monkeypatch.setattr(tl, "lock_state", lambda **_k: {"locked": True})
    assert C.preconditions() == ["schwab_access_mode_not_read_only (mode=normal, source=env:TRADEAI_SCHWAB_ACCESS_MODE)"]
    monkeypatch.setenv("TRADEAI_SCHWAB_ACCESS_MODE", "read_only")
    monkeypatch.setattr(tl, "lock_state", lambda **k: {"locked": k.get("broker") != "alpaca"})
    assert C.preconditions() == ["trading_lock_not_locked (alpaca)"]
