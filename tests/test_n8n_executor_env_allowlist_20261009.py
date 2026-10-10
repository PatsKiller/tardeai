"""P7 (n8n maturity, 2026-10-09; supersedes #1561): per-lane executor child env allowlist.

One builder (``build_child_env``) for the v1 serial ``drain`` and the v2 worker path. Hermetic: tmp_path ledgers and
state roots, synthetic fixture values, fake runners plus one tiny real child. Never touches the live ledger, unit
files, crontab, token store or any .env file."""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import n8n_run_executor as X  # noqa: E402
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerRunStore  # noqa: E402
from scripts.lib.n8n_retry_policy import load_policies  # noqa: E402

DOC = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text(encoding="utf-8"))
LANES = {e["lane_id"]: e for e in DOC["lanes"]}
SIGNERS = set(X.CHILD_ENV_LANE_PASSTHROUGH)
SECRET_RE = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|BEARER", re.I)
FIXTURE = "fixture-value-"
SECRETS = {
    "UNLISTED_API_KEY", "UNLISTED_TOKEN", "UNLISTED_SECRET", "DB_PASSWORD",
    "TRADEAI_N8N_GATEWAY_HMAC_KEY", "TRADEAI_N8N_GATEWAY_HMAC_KEY_PREVIOUS", "TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N",
    "TRADEAI_N8N_RELAY_BEARER", "N8N_ENCRYPTION_KEY_ESCROW",
}


def environment(mode: str | None = "enforce") -> dict[str, str]:
    env = {name: FIXTURE + name for name in SECRETS | X.CHILD_ENV_BASE_NAMES}
    env.update({"UNLISTED_NON_SECRET": FIXTURE + "plain", "TRADEAI_N8N_GATEWAY_URL": "http://127.0.0.1:18091",
                "TRADEAI_VENV_PYTHON": sys.executable})  # $PY resolves into the receipt argv by design
    if mode is not None:
        env[X.ENV_ALLOWLIST_MODE_ENV] = mode
    return env


def _entry(tmp_path: Path, **fields) -> dict:
    base = {"lane_id": "fixture-lane", "command": ["$PY", "scripts/fake.py", "--lane", "fixture-lane"],
            "lock": str(tmp_path / "fixture.lock"), "timeout_s": 5, "dry_run_arg": [], "live_arg": [],
            "env_names": ["DB_PASSWORD"], "env_allowlist_mode": "enforce"}
    base.update(fields)
    return {k: v for k, v in base.items() if v is not ...}


def _run(tmp_path: Path, env: dict, **fields):
    seen: list[dict] = []

    def runner(argv, *, timeout, env, cwd):
        seen.append(dict(env))
        return subprocess.CompletedProcess(argv, 0, "", "")

    row = {"run_id": "run-env-fixture-00000001", "lane_id": "fixture-lane", "mode": "dry_run"}
    receipt = X.execute(row, _entry(tmp_path, **fields), env=env, state_root=tmp_path, code_root=tmp_path,
                        runner=runner)
    return receipt, seen


def _no_values(receipt) -> None:
    text = json.dumps(receipt, default=str)
    assert FIXTURE not in text
    assert "http://127.0.0.1:18091" not in text


# ── the scorer contract ───────────────────────────────────────────────────────────────────────────────────────

def test_mode_env_literal_is_in_the_executor_source():
    # scripts/lib/n8n_maturity/dims_governance.py::_p7 greps the served executor for this exact string
    src = (ROOT / "scripts" / "n8n_run_executor.py").read_text(encoding="utf-8")
    assert "TRADEAI_EXECUTOR_ENV_ALLOWLIST" in src
    assert X.ENV_ALLOWLIST_MODE_ENV == "TRADEAI_EXECUTOR_ENV_ALLOWLIST"
    cfg = json.loads((ROOT / "config" / "n8n_platform_maturity.json").read_text(encoding="utf-8"))
    assert X.ENV_ALLOWLIST_MODE_ENV in json.dumps(cfg)


def test_installed_unit_is_unchanged_and_carries_no_mode():
    # the operator sets enforce in the unit under a grant; this PR never edits the unit
    unit = (ROOT / "config" / "systemd" / "user" / "tradeai-n8n-run-executor.service").read_text(encoding="utf-8")
    assert X.ENV_ALLOWLIST_MODE_ENV not in unit


# ── builder: off / report / enforce ───────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("mode", [None, "", "  ", "report", "REPORT"])
def test_unset_empty_and_report_keep_the_pre_p7_env_and_record_names(mode):
    env = environment(mode)
    entry = {"lane_id": "x", "env_names": ["DB_PASSWORD"]}
    child, block = X.build_child_env(env, "x", entry)
    assert child == X.child_env(env, "x")
    assert block["requested_mode"] == block["effective_mode"] == "report"
    assert "UNLISTED_TOKEN" in block["dropped_names"] and "UNLISTED_NON_SECRET" in block["dropped_names"]
    assert "DB_PASSWORD" not in block["dropped_names"]
    assert not set(block["dropped_names"]) & X.CHILD_ENV_BASE_NAMES
    _no_values(block)


def test_off_is_the_pre_p7_env_with_no_name_evidence():
    env = environment("off")
    child, block = X.build_child_env(env, "x", {"lane_id": "x"})
    assert child == X.child_env(env, "x")
    assert block["effective_mode"] == "off" and block["dropped_names"] is None


def test_enforce_passes_only_base_plus_lane_names_and_never_mutates():
    env = environment("enforce")
    before = dict(env)
    child, block = X.build_child_env(env, "x", {"lane_id": "x", "env_names": ["DB_PASSWORD"]})
    assert set(child) == X.CHILD_ENV_BASE_NAMES | {"DB_PASSWORD"}
    assert X.ENV_ALLOWLIST_MODE_ENV not in child
    assert block["effective_mode"] == "enforce" and block["reason"] is None
    assert "UNLISTED_TOKEN" in block["dropped_names"]
    assert env == before
    _no_values(block)


def test_enforce_with_empty_list_is_base_only():
    child, _ = X.build_child_env(environment(), "x", {"lane_id": "x", "env_names": []})
    assert set(child) == X.CHILD_ENV_BASE_NAMES


def test_enforce_never_readmits_an_n8n_secret_even_if_the_env_has_it():
    child, _ = X.build_child_env(environment(), "x", {"lane_id": "x", "env_names": ["TRADEAI_N8N_GATEWAY_URL"]})
    assert not [k for k in child if k.startswith(X.CHILD_ENV_STRIP_PREFIXES) and k != "TRADEAI_N8N_GATEWAY_URL"]


def test_signer_gets_the_dispatch_key_only_when_listed():
    lane = "n8n-pilot-dispatch"
    child, _ = X.build_child_env(environment(), lane, {"lane_id": lane, "env_names": []})
    assert X.GATEWAY_DISPATCH_KEY_ENV not in child
    child, _ = X.build_child_env(environment(), lane, {"lane_id": lane, "env_names": [X.GATEWAY_DISPATCH_KEY_ENV]})
    assert X.GATEWAY_DISPATCH_KEY_ENV in child
    assert "TRADEAI_N8N_GATEWAY_HMAC_KEY_PREVIOUS" not in child


def test_lane_pinned_report_keeps_the_pre_p7_env_under_global_enforce():
    env = environment("enforce")
    child, block = X.build_child_env(env, "x", {"lane_id": "x", "env_names": [], "env_allowlist_mode": "report"})
    assert child == X.child_env(env, "x")
    assert block["requested_mode"] == "enforce" and block["effective_mode"] == "report"
    assert block["reason"] == "lane_report_only"


def test_enforced_lane_without_env_names_fails_closed():
    child, block = X.build_child_env(environment("enforce"), "x", {"lane_id": "x"})
    assert child is None and block["reason"] == "env_names_missing"
    child, block = X.build_child_env(environment("enforce"), "x", {"lane_id": "x", "env_allowlist_mode": "enforce"})
    assert child is None and block["reason"] == "env_names_missing"


@pytest.mark.parametrize("bad", ["enforced", "on", "true", "typo-secret-value"])
def test_unknown_global_mode_fails_closed_and_never_records_the_value(bad):
    child, block = X.build_child_env(environment(bad), "x", {"lane_id": "x", "env_names": []})
    assert child is None
    assert block["requested_mode"] is None and block["reason"] == "bad_env_allowlist_mode"
    assert json.dumps(bad) not in json.dumps(block)


@pytest.mark.parametrize("fields,reason", [
    ({"env_names": "DB_PASSWORD"}, "bad_env_names"),
    ({"env_names": ["DB_PASSWORD", "DB_PASSWORD"]}, "bad_env_names"),
    ({"env_names": ["bad-name"]}, "bad_env_names"),
    ({"env_names": [1]}, "bad_env_names"),
    ({"env_allowlist_mode": "off"}, "bad_lane_env_allowlist_mode"),
    ({"env_names": ["TRADEAI_N8N_RELAY_BEARER"]}, "forbidden_env_name"),
    ({"env_names": [X.GATEWAY_DISPATCH_KEY_ENV]}, "forbidden_env_name"),
])
def test_malformed_lane_policy_is_invalid_and_refused(tmp_path, fields, reason):
    entry = _entry(tmp_path, **fields)
    assert X.validate_entry(entry) == reason
    receipt, seen = _run(tmp_path, environment("report"), **fields)
    assert receipt["state"] == "RUN_REFUSED" and receipt["reason"] == f"env_allowlist:{reason}"
    assert seen == []


def test_malformed_lane_is_dropped_by_load_allowlist(tmp_path):
    doc = {"schema": X.ALLOWLIST_SCHEMA, "lanes": [_entry(tmp_path, lane_id="good"),
                                                     _entry(tmp_path, lane_id="bad", env_names="X")]}
    path = tmp_path / "allow.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert set(X.load_allowlist(path)) == {"good"}


# ── execute(): receipts, no values, no spawn on refusal ──────────────────────────────────────────────────────

def test_execute_report_runs_inherited_env_and_receipt_carries_names_only(tmp_path):
    env = environment(None)
    receipt, seen = _run(tmp_path, env)
    assert receipt["state"] == "RUN_DONE"
    assert seen == [X.child_env(env, "fixture-lane")]
    block = receipt["env_allowlist"]
    assert block["effective_mode"] == "report" and "UNLISTED_API_KEY" in block["dropped_names"]
    _no_values(receipt)


def test_execute_enforce_spawns_with_the_allowlisted_env(tmp_path):
    receipt, seen = _run(tmp_path, environment("enforce"))
    assert receipt["state"] == "RUN_DONE"
    assert set(seen[0]) == X.CHILD_ENV_BASE_NAMES | {"DB_PASSWORD"}
    _no_values(receipt)


def test_execute_enforce_missing_list_refuses_without_spawning(tmp_path):
    receipt, seen = _run(tmp_path, environment("enforce"), env_names=...)
    assert receipt["state"] == "RUN_REFUSED" and receipt["reason"] == "env_allowlist:env_names_missing"
    assert seen == [] and receipt["exit_code"] is None
    _no_values(receipt)


def test_execute_bad_mode_refuses_without_spawning(tmp_path):
    receipt, seen = _run(tmp_path, environment("typo-secret-value"))
    assert receipt["state"] == "RUN_REFUSED" and receipt["reason"] == "env_allowlist:bad_env_allowlist_mode"
    assert seen == [] and "typo-secret-value" not in json.dumps(receipt)


def test_real_child_under_enforce_sees_no_unlisted_secret(tmp_path):
    script = tmp_path / "dump_env.py"
    out = tmp_path / "child.json"
    script.write_text("import os, json, sys\nopen(sys.argv[1], 'w').write(json.dumps(dict(os.environ)))\n")
    env = environment("enforce")
    env["PATH"] = "/usr/bin:/bin"
    entry = _entry(tmp_path, command=[sys.executable, str(script), str(out)], lock_kind="flock")
    row = {"run_id": "run-env-realchild-0001", "lane_id": "fixture-lane", "mode": "dry_run"}
    receipt = X.execute(row, entry, env=env, state_root=tmp_path, code_root=tmp_path)
    assert receipt["state"] == "RUN_DONE", receipt
    seen = json.loads(out.read_text())
    assert {k for k in seen if SECRET_RE.search(k)} == {"DB_PASSWORD"}
    assert "UNLISTED_NON_SECRET" not in seen and X.ENV_ALLOWLIST_MODE_ENV not in seen


# ── both executor paths share the builder ─────────────────────────────────────────────────────────────────────

@pytest.fixture
def ledger(tmp_path):
    led = CoordinationLedger(tmp_path / "ledger.sqlite")
    store = LedgerRunStore(led)
    state = tmp_path / "state"
    state.mkdir()

    def request(run_id: str, lane: str):
        return store.request(run_id=run_id, lane_id=lane, mode="dry_run", requested_by="t", caller_id="n8n-relay",
                             now=1_791_500_000.0)

    yield SimpleNamespace(store=store, state=state, request=request, tmp=tmp_path)
    led.close()


def _allowlist(tmp_path: Path) -> dict:
    return {
        "enf": _entry(tmp_path, lane_id="enf", command=["$PY", "scripts/fake.py", "--lane", "enf"]),
        "rep": _entry(tmp_path, lane_id="rep", command=["$PY", "scripts/fake.py", "--lane", "rep"],
                      env_allowlist_mode="report"),
        "nolist": _entry(tmp_path, lane_id="nolist", command=["$PY", "scripts/fake.py", "--lane", "nolist"],
                         env_names=...),
    }


def _check_path_results(receipts: dict, seen: dict, env: dict) -> None:
    assert receipts["enf"]["state"] == "RUN_DONE"
    assert set(seen["enf"]) == X.CHILD_ENV_BASE_NAMES | {"DB_PASSWORD"}
    assert receipts["rep"]["state"] == "RUN_DONE" and receipts["rep"]["env_allowlist"]["reason"] == "lane_report_only"
    assert seen["rep"] == X.child_env(env, "rep")
    assert receipts["nolist"]["state"] == "RUN_REFUSED"
    assert receipts["nolist"]["reason"] == "env_allowlist:env_names_missing" and "nolist" not in seen
    for r in receipts.values():
        _no_values(r)


def test_v1_drain_path_uses_the_builder(ledger):
    env = environment("enforce")
    seen: dict[str, dict] = {}

    def runner(argv, *, timeout, env, cwd):
        seen[argv[argv.index("--lane") + 1]] = dict(env)
        return subprocess.CompletedProcess(argv, 0, "", "")

    for i, lane in enumerate(("enf", "rep", "nolist")):
        ledger.request(f"run-v1-{lane}-{i:010d}", lane)
    out = X.drain(ledger.store, _allowlist(ledger.tmp), env=env, state_root=ledger.state, code_root=ledger.tmp,
                  runner=runner)
    receipts = {r["lane_id"]: r for r in out}
    assert {r["schema"] for r in out} == {X.RECEIPT_SCHEMA}
    _check_path_results(receipts, seen, env)
    stored = json.loads((ledger.state / X.RUNS_REL / "run-v1-nolist-0000000002.json").read_text())
    assert stored["env_allowlist"]["reason"] == "env_names_missing"


def test_v2_worker_path_uses_the_builder(ledger):
    env = environment("enforce")
    seen: dict[str, dict] = {}

    def factory(on_spawn, on_beat):
        def run(argv, *, timeout, env, cwd):
            seen[argv[argv.index("--lane") + 1]] = dict(env)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return run

    allow = _allowlist(ledger.tmp)
    for i, lane in enumerate(allow):
        ledger.request(f"run-v2-{lane}-{i:010d}", lane)
    ex = X.ExecutorV2(ledger.store, allow, env=env, state_root=ledger.state, code_root=ledger.tmp, workers=2,
                      policies=load_policies(), runner_factory=factory, worker_prefix="test", quiet=True,
                      registry_rows=[{"lane_id": lane, "dispatch": {"retry_policy": "transient-2"}} for lane in allow],
                      sleeper=lambda s: None)
    ex.drain_until_idle(deadline_s=20)
    receipts = {r["lane_id"]: r for r in ex.receipts}
    assert set(receipts) == set(allow)
    assert {r["schema"] for r in receipts.values()} == {X.RECEIPT_SCHEMA_V2}
    _check_path_results(receipts, seen, env)


# ── the committed allowlist ───────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("lane_id", sorted(LANES))
def test_every_lane_declares_a_valid_policy_with_evidence(lane_id):
    entry = LANES[lane_id]
    assert X.validate_entry(entry) is None
    assert isinstance(entry["env_names"], list) and entry["env_names"] == sorted(set(entry["env_names"]))
    assert not set(entry["env_names"]) & X.CHILD_ENV_BASE_NAMES, "base names are implicit"
    assert entry["env_allowlist_mode"] in X.LANE_ENV_ALLOWLIST_MODES
    assert entry["env_evidence"]
    if entry["env_allowlist_mode"] == "report":
        assert entry["env_report_reason"]


def test_dispatch_key_is_listed_only_for_the_signing_lanes():
    listed = {lane for lane, e in LANES.items() if X.GATEWAY_DISPATCH_KEY_ENV in e["env_names"]}
    assert listed == SIGNERS


def test_every_lane_runs_under_global_enforce_with_least_privilege():
    for lane, entry in LANES.items():
        child, block = X.build_child_env(environment("enforce"), lane, entry)
        assert child is not None, lane
        if entry["env_allowlist_mode"] == "enforce":
            assert set(child) <= X.CHILD_ENV_BASE_NAMES | set(entry["env_names"]), lane
            assert {k for k in child if SECRET_RE.search(k)} <= set(entry["env_names"]), lane


def _env_reads(path: Path, visited: set) -> set:
    """Static drift guard for the enforced lanes: literal env reads across the recursive local import closure;
    a non-literal read fails (the lane must go back to report)."""
    if path in visited:
        return set()
    visited.add(path)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    consts = {t.id: n.value.value for n in ast.walk(tree) if isinstance(n, ast.Assign)
              and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)
              for t in n.targets if isinstance(t, ast.Name)}
    reads: set = set()
    for node in ast.walk(tree):
        key = None
        if isinstance(node, ast.Call) and ast.unparse(node.func) in {
                "os.getenv", "os.environ.get", "env.get", "env.setdefault"}:
            assert node.args, (path, node.lineno)
            key = node.args[0]
        elif isinstance(node, ast.Subscript) and ast.unparse(node.value) in {"os.environ", "env"}:
            key = node.slice
        if key is not None:
            name = key.value if isinstance(key, ast.Constant) else consts.get(key.id) if isinstance(key, ast.Name) \
                else None
            assert isinstance(name, str), f"unresolved env read {path.relative_to(ROOT)}:{node.lineno}"
            reads.add(name)
        mods: list[str] = []
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and not node.level:
            mod = node.module or ""
            mods = [mod, *(f"{mod}.{a.name}" for a in node.names)]
        for mod in mods:
            rel = mod.replace(".", "/") + ".py"
            for base in (ROOT, ROOT / "scripts", ROOT / "scripts" / "lib"):
                if (base / rel).is_file():
                    reads |= _env_reads(base / rel, visited)
                    break
    return reads


@pytest.mark.parametrize("lane_id", sorted(k for k, e in LANES.items() if e["env_allowlist_mode"] == "enforce"))
def test_enforced_inventories_cover_every_literal_read_in_the_import_closure(lane_id):
    entry = LANES[lane_id]
    scripts = [ROOT / t for t in entry["command"] if t.endswith(".py")]
    visited: set = set()
    reads = set().union(set(), *(_env_reads(p, visited) for p in scripts))
    assert len(visited) <= 10, f"{lane_id}: closure grew to {len(visited)} modules; re-inventory before enforcing"
    if entry.get("lock_kind", "safe_flock") == "safe_flock":
        reads |= {"PROJECT_ROOT", "SAFE_FLOCK_LOG_DIR"}
    assert reads <= X.CHILD_ENV_BASE_NAMES | set(entry["env_names"]), sorted(reads - X.CHILD_ENV_BASE_NAMES
                                                                              - set(entry["env_names"]))


def test_lane_mode_counts_match_the_pr():
    modes = [e["env_allowlist_mode"] for e in LANES.values()]
    assert modes.count("enforce") == 7 and modes.count("report") == len(LANES) - 7
