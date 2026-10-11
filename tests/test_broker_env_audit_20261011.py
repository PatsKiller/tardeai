"""Broker env-name read audit — log only, zero behaviour change (operator 2026-10-11 ~10:55 ET, step 1 of 3).

``scripts/lib/broker_env_audit.py`` (installed by ``env_bootstrap`` when ``TRADEAI_BROKER_ENV_AUDIT=1``) records
WHICH process/module reads each broker env name, never the value. ``scripts/report_broker_env_audit.py`` aggregates
a week of records into per-lane / per-module / per-name tables. Pins:

- no value, length or presence ever reaches the log (synthetic secrets, every read form);
- unset (or any value other than "1") is a no-op: ``os.environ`` keeps its stock class, nothing is written;
- every recorder failure is swallowed and the read returns exactly what it would without the audit;
- throttle: one line per (process, name, caller); a forked child logs its own;
- whole-env copies are ``bulk``; env_bootstrap's own loader reads are not recorded;
- ``os.environ`` identity, aliases and child-process inheritance are unchanged;
- report aggregation, lane resolution, malformed/foreign lines, field whitelist;
- benchmark: the per-read overhead stays small.

Hermetic: subprocesses with a minimal env, synthetic values, a tmp state root; the live render, a real .env, the
lane registry's live state and any broker are never touched.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import broker_env_audit as BEA  # noqa: E402

from scripts import report_broker_env_audit as R  # noqa: E402

FAKE = "fixture-secret-value-"
BROKER = ["ALPACA_API_KEY", "ALPACA_SECRET_KEY", "SCHWAB_APP_SECRET", "SNAPTRADE_USER_SECRET", "MOOMOO_TRADE_PWD",
          "IBKR_ACCOUNT", "TRADING_MODE", "PAPER_BROKER_TOKEN"]
PRELUDE = f"""
import os, sys
sys.path.insert(0, {str(ROOT / "scripts" / "lib")!r})
import env_bootstrap
import broker_env_audit as BEA
"""


def _env(tmp_path: Path, flag: str | None = "1", **extra: str) -> dict[str, str]:
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp_path), "LANG": "C.UTF-8",
           "TRADEAI_STATE_ROOT": str(tmp_path / "state")}
    env.update({n: FAKE + n for n in BROKER})
    if flag is not None:
        env["TRADEAI_BROKER_ENV_AUDIT"] = flag
    env.update(extra)
    return env


def _run(tmp_path: Path, body: str, *, name: str = "probe.py", args=(), **envkw) -> subprocess.CompletedProcess:
    script = tmp_path / "scripts" / name
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(PRELUDE + textwrap.dedent(body), encoding="utf-8")
    p = subprocess.run([sys.executable, str(script), *args], env=_env(tmp_path, **envkw), capture_output=True,
                       text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    return p


def _lines(tmp_path: Path) -> list[dict]:
    d = tmp_path / "state" / "data" / "runtime" / "broker_env_audit"
    out = []
    for f in sorted(d.glob("*.jsonl")) if d.is_dir() else []:
        out += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
    return out


def _raw(tmp_path: Path) -> str:
    d = tmp_path / "state" / "data" / "runtime" / "broker_env_audit"
    return "".join(f.read_text(encoding="utf-8") for f in d.glob("*.jsonl")) if d.is_dir() else ""


READS = """
def main():
    a = os.environ["ALPACA_API_KEY"]
    b = os.environ.get("ALPACA_SECRET_KEY")
    c = "SCHWAB_APP_SECRET" in os.environ
    d = os.getenv("SNAPTRADE_USER_SECRET")
    e = os.environ.setdefault("MOOMOO_TRADE_PWD", "x")
    try:
        os.environ["IBKR_MISSING_NAME"]
    except KeyError:
        pass
    h = os.environ.get("HOME")
    print(json.dumps([a, b, c, d, e, h]))
import json
main()
"""


def test_no_value_ever_logged_and_reads_unchanged(tmp_path):
    p = _run(tmp_path, READS, args=("--apply",))
    got = json.loads(p.stdout)
    assert got == [FAKE + "ALPACA_API_KEY", FAKE + "ALPACA_SECRET_KEY", True, FAKE + "SNAPTRADE_USER_SECRET",
                   FAKE + "MOOMOO_TRADE_PWD", str(tmp_path)]
    raw = _raw(tmp_path)
    assert raw and FAKE not in raw and "fixture-secret" not in raw
    recs = _lines(tmp_path)
    names = {r["name"]: r["access"] for r in recs}
    assert names == {"ALPACA_API_KEY": "getitem", "ALPACA_SECRET_KEY": "get", "SCHWAB_APP_SECRET": "contains",
                     "SNAPTRADE_USER_SECRET": "get", "MOOMOO_TRADE_PWD": "contains", "IBKR_MISSING_NAME": "getitem"}
    for r in recs:
        assert set(r) == {"schema", "ts", "host", "pid", "ppid", "name", "access", "script", "arg1", "lane", "unit",
                          "caller", "caller_file", "via", "mode"}
        assert r["mode"] == "audit" and r["schema"] == BEA.SCHEMA and r["arg1"] == "--apply"
        assert r["caller"].startswith("probe.py:main:") and r["script"].endswith("scripts/probe.py")
        assert not any(isinstance(v, str) and FAKE in v for v in r.values())


def test_positional_argv_never_logged(tmp_path):
    _run(tmp_path, READS, args=(FAKE + "positional",))
    raw = _raw(tmp_path)
    assert FAKE not in raw and {r["arg1"] for r in _lines(tmp_path)} == {"<arg>"}


@pytest.mark.parametrize("flag", [None, "0", "true", "", " 1x"])
def test_no_op_when_flag_off(tmp_path, flag):
    p = _run(tmp_path, READS + "\nprint(type(os.environ) is os._Environ, BEA.installed())\n", flag=flag)
    assert p.stdout.splitlines()[-1] == "True False"
    assert not (tmp_path / "state" / "data").exists()


def test_environ_identity_alias_and_child_inheritance(tmp_path):
    p = _run(tmp_path, """
        from os import environ as E
        import subprocess
        os.environ["ZZ_SET_AFTER"] = "v1"
        r = subprocess.run(["sh", "-c", 'printf "%s|%s" "$ZZ_SET_AFTER" "${ALPACA_API_KEY:+set}"'],
                           capture_output=True, text=True).stdout
        print(BEA.installed(), E is os.environ, isinstance(os.environ, os._Environ), r)
        os.environ.pop("ZZ_SET_AFTER"); print("ZZ_SET_AFTER" in os.environ)
    """)
    assert p.stdout.split() == ["True", "True", "True", "v1|set", "False"]


def test_recorder_failures_swallowed(tmp_path):
    (tmp_path / "state").write_text("not a dir")  # mkdir under a file fails
    p = _run(tmp_path, READS + "\nprint(BEA._stats['swallowed'] > 0)\n")
    out = p.stdout.splitlines()
    assert json.loads(out[0])[0] == FAKE + "ALPACA_API_KEY" and out[-1] == "True"


def test_classifier_and_frame_failures_swallowed(tmp_path):
    p = _run(tmp_path, """
        def boom(name):
            raise RuntimeError("classifier exploded")
        BEA.uninstall(); BEA._classifier = None; BEA._reset_for_tests()
        assert BEA.install(boom)
        print(os.environ["ALPACA_API_KEY"] == %r, os.environ.get("NOPE_X", "d"))
        BEA.uninstall(); BEA._classifier = None; BEA._reset_for_tests()
        BEA.install(lambda n: True)
        real = BEA._callers
        BEA._callers = lambda f: (_ for _ in ()).throw(ValueError("x"))
        print(os.environ["ALPACA_API_KEY"] == %r, BEA._stats["swallowed"])
        BEA._callers = real
        try:
            os.environ[["unhashable"]]
        except TypeError:
            print("typeerror")
    """ % (FAKE + "ALPACA_API_KEY", FAKE + "ALPACA_API_KEY"))
    assert p.stdout.split() == ["True", "d", "True", "1", "typeerror"]


def test_throttle_one_line_per_process_name_caller_and_fork(tmp_path):
    _run(tmp_path, """
        def hot():
            for _ in range(500):
                os.environ["ALPACA_API_KEY"]
        def other():
            return os.getenv("ALPACA_API_KEY")
        hot(); hot(); other(); other()
        pid = os.fork()
        if pid == 0:
            hot(); os._exit(0)
        os.waitpid(pid, 0)
    """)
    recs = _lines(tmp_path)
    by = sorted((r["pid"] != recs[0]["pid"], r["caller"].split(":")[1]) for r in recs)
    assert by == [(False, "hot"), (False, "other"), (True, "hot")]


def test_line_cap_per_process(tmp_path):
    _run(tmp_path, """
        BEA.MAX_LINES_PER_PROCESS = 3
        for i in range(10):
            os.environ.get(f"ALPACA_NAME_{i}")
    """)
    assert len(_lines(tmp_path)) == 3


def test_bulk_copies_are_bulk_and_loader_reads_not_recorded(tmp_path):
    render = tmp_path / "fake_render.env"
    render.write_text("\n".join(f"{n}='{FAKE}{n}2'" for n in BROKER + ["ALPACA_NEW_NAME"]) + "\n")
    _run(tmp_path, f"""
        env_bootstrap._apply_file(__import__("pathlib").Path({str(render)!r}), override=True)
        env_bootstrap._apply_file(__import__("pathlib").Path({str(render)!r}))
        def copy_for_child():
            return dict(os.environ)
        def splat():
            return {{**os.environ}}
        def via_copy():
            return os.environ.copy()
        def via_items():
            return [k for k, v in os.environ.items()]
        copy_for_child(); splat(); via_copy(); via_items()
    """)
    recs = _lines(tmp_path)
    assert recs and {r["access"] for r in recs} == {"bulk"}
    assert {r["caller"].split(":")[1] for r in recs} == {"copy_for_child", "splat", "via_copy", "via_items"}
    assert not any("env_bootstrap" in str(r["caller_file"]) for r in recs)
    assert FAKE not in _raw(tmp_path)


def test_flag_name_itself_not_audited_and_lane_env(tmp_path):
    _run(tmp_path, """
        os.environ.get("TRADEAI_BROKER_ENV_AUDIT"); os.environ.get("ALPACA_API_KEY")
    """, TRADEAI_LANE="options-tick")
    recs = _lines(tmp_path)
    assert [(r["name"], r["lane"]) for r in recs] == [("ALPACA_API_KEY", "options-tick")]


def test_env_bootstrap_load_env_installs_after_copy(tmp_path):
    """A flag delivered by the env file (not the process env) still turns the audit on after load_env."""
    render = tmp_path / "xdg" / "tradeai" / "env"
    render.parent.mkdir(parents=True)
    render.write_text("TRADEAI_BROKER_ENV_AUDIT=1\nZZ_PLAIN=1\n")
    p = _run(tmp_path, """
        print(BEA.installed())
        env_bootstrap._candidates = lambda: [__import__("pathlib").Path(os.environ["XDG_RUNTIME_DIR"]) / "tradeai" / "env"]
        env_bootstrap.load_env(names=("TRADEAI_BROKER_ENV_AUDIT", "ZZ_PLAIN"))
        print(BEA.installed())
    """, flag=None, XDG_RUNTIME_DIR=str(tmp_path / "xdg"))
    assert p.stdout.split() == ["False", "True"]


_DB_PROBE = r"""
import os, sys, types
stub = types.ModuleType("psycopg2")
stub.extras = types.ModuleType("psycopg2.extras")
stub.extensions = types.ModuleType("psycopg2.extensions")
sys.modules.update({"psycopg2": stub, "psycopg2.extras": stub.extras, "psycopg2.extensions": stub.extensions})
sys.path.insert(0, os.path.join(os.environ["PROJ_UNDER_TEST"], "scripts"))
import db_adapter
bea = sys.modules.get("broker_env_audit")
print(bool(bea and bea.installed()), type(os.environ) is os._Environ)
os.environ.get("ALPACA_API_KEY")
"""


@pytest.mark.parametrize("flag,expect", [("1", "True False"), (None, "False True")])
def test_db_adapter_installs_audit_even_when_db_password_already_set(tmp_path, flag, expect):
    """A process with DB_PASSWORD already in its env never reaches env_bootstrap; db_adapter's hook still installs."""
    env = _env(tmp_path, flag=flag, DB_PASSWORD="fixture-db", PROJ_UNDER_TEST=str(ROOT))
    p = subprocess.run([sys.executable, "-c", _DB_PROBE], env=env, cwd=str(tmp_path), capture_output=True, text=True,
                       timeout=60)
    assert p.returncode == 0, p.stderr
    assert p.stdout.strip().splitlines()[-1] == expect
    assert bool(_lines(tmp_path)) is (flag == "1")
    assert FAKE not in _raw(tmp_path)


def test_benchmark_overhead_small(tmp_path):
    p = _run(tmp_path, """
        import timeit, json
        N = 200000
        BEA.uninstall()
        def t(stmt):
            return min(timeit.repeat(stmt, globals={"E": os.environ, "os": os}, number=N, repeat=5)) / N * 1e9
        assert type(os.environ) is os._Environ
        off = {"plain": t("E['HOME']"), "broker": t("E['ALPACA_API_KEY']")}
        os.environ["TRADEAI_BROKER_ENV_AUDIT"] = "1"; BEA.maybe_install(env_bootstrap.is_broker_name)
        on = {"plain": t("E['HOME']"), "broker": t("E['ALPACA_API_KEY']")}
        print(json.dumps({"off": off, "on": on}))
    """)
    r = json.loads(p.stdout)
    # Measured 2026-10-11 on ms01: plain +~110 ns, throttled broker read ~1 us. Bounds are loose for loaded hosts.
    assert r["on"]["plain"] - r["off"]["plain"] < 2000
    assert r["on"]["broker"] < 20000


# ── report ─────────────────────────────────────────────────────────────────────────────────────────────────────


def _rec(**kw):
    base = {"schema": BEA.SCHEMA, "mode": "audit", "ts": "2026-10-11T14:00:00+00:00", "host": "h", "pid": 1,
            "ppid": 0, "name": "ALPACA_API_KEY", "access": "get", "script": "/x/CURRENT/scripts/a.py", "arg1": None,
            "lane": None, "unit": "cron.service", "caller": "a.py:main:3", "caller_file": "/x/CURRENT/scripts/a.py",
            "via": None}
    base.update(kw)
    return base


def test_report_aggregation_verdicts_and_whitelist(tmp_path):
    d = tmp_path / "audit"
    d.mkdir()
    rows = [
        _rec(),
        _rec(pid=2, name="ALPACA_SECRET_KEY", access="getitem", caller="market_quote_provider:fetch:10",
             caller_file="/x/CURRENT/scripts/lib/market_quote_provider.py"),
        _rec(pid=3, script="/x/scripts/b.py", caller_file="/x/scripts/b.py", caller="b.py:spawn:5", access="bulk",
             name="SCHWAB_APP_SECRET", value=FAKE + "leak"),
        _rec(pid=4, script="/x/scripts/c.py", lane="lane-from-env", access="contains", name="TRADING_MODE",
             caller_file="/x/scripts/c.py"),
    ]
    (d / "2026-10-11.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n"
                                        + json.dumps({"schema": "Other@v1", "name": "X"}) + "\n")
    (d / "2026-09-01.jsonl").write_text(json.dumps(_rec(name="OUT_OF_WINDOW")) + "\n")
    rep = R.build_report(d, 7, date(2026, 10, 11), resolve_lanes=False)
    assert rep["meta"]["malformed"] == 1 and rep["meta"]["foreign"] == 1 and rep["summary"]["records"] == 4
    lanes = {r["lane"]: r for r in rep["lanes"]}
    assert lanes["script:scripts/a.py"]["verdict"] == "needs"
    assert lanes["script:scripts/a.py"]["names_needed"] == ["ALPACA_API_KEY", "ALPACA_SECRET_KEY"]
    assert lanes["script:scripts/b.py"]["verdict"] == "passthrough_only"
    assert lanes["script:scripts/b.py"]["names_bulk_only"] == ["SCHWAB_APP_SECRET"]
    assert lanes["lane-from-env"]["names_needed"] == ["TRADING_MODE"]
    mods = {m["module"]: m for m in rep["modules"]}
    assert mods["scripts/lib/market_quote_provider.py"]["names_needed"] == ["ALPACA_SECRET_KEY"]
    names = {n["name"]: n for n in rep["names"]}
    assert names["SCHWAB_APP_SECRET"]["lanes_bulk_only"] == ["script:scripts/b.py"]
    assert "OUT_OF_WINDOW" not in names
    md = R.render_markdown(rep)
    blob = md + json.dumps(rep)
    assert FAKE not in blob and "leak" not in blob
    assert "| `script:scripts/a.py` | needs |" in md


def test_report_lane_resolution_from_registry(tmp_path):
    reg = tmp_path / "lane_registry.json"
    reg.write_text(json.dumps({"schema": "LaneRegistry@v1", "lanes": [
        {"lane_id": "a-lane", "scheduler": {"kind": "cron", "expression": "0 1 * * *", "match": "scripts/a.py"}},
        {"lane_id": "svc-lane", "scheduler": {"kind": "systemd", "expression": "tradeai-svc.service"}},
    ]}))
    resolve = R.registry_resolver(reg)
    assert R.lane_of(_rec(), resolve) == "a-lane"
    assert R.lane_of(_rec(script="/usr/bin/x", unit="tradeai-svc.service"), resolve) == "svc-lane"
    assert R.lane_of(_rec(script="/x/scripts/zz.py"), resolve) == "script:scripts/zz.py"


def test_report_cli_writes_only_given_paths(tmp_path):
    d = tmp_path / "audit"
    d.mkdir()
    (d / "2026-10-11.jsonl").write_text(json.dumps(_rec()) + "\n")
    before = sorted(p.name for p in d.iterdir())
    assert R.main(["--dir", str(d), "--until", "2026-10-11", "--no-lanes", "--json", str(tmp_path / "r.json"),
                   "--md", str(tmp_path / "r.md")]) == 0
    assert sorted(p.name for p in d.iterdir()) == before
    assert json.loads((tmp_path / "r.json").read_text())["summary"]["lanes_needing"] == 1
    assert (tmp_path / "r.md").read_text().startswith("# Broker env-name read audit")


def test_report_static_scan_excludes_broker_subsystem_and_compares_runtime(tmp_path):
    root = tmp_path / "repo"
    files = {
        "scripts/a.py": 'import os\nk = os.environ.get("ALPACA_API_KEY")\ns = os.getenv("ALPACA_SECRET_KEY")\n',
        "scripts/lib/m.py": 'import os\nif "SCHWAB_APP_KEY" in os.environ:\n    pass\nx = "ALPACA_NOT_AN_ENV_READ"\n',
        "scripts/brokers/x.py": 'import os\nos.environ["ALPACA_BROKER_ONLY"]\n',
        "scripts/archive/old.py": 'import os\nos.environ["ALPACA_ARCHIVED"]\n',
        "scripts/plain.py": 'import os\nos.environ["HOME"]\n',
    }
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    import env_bootstrap as EB
    static = R.static_references(root, EB.is_broker_name)
    assert static == {"scripts/a.py": ["ALPACA_API_KEY", "ALPACA_SECRET_KEY"], "scripts/lib/m.py": ["SCHWAB_APP_KEY"]}
    rep = R.aggregate([_rec(caller_file="/x/scripts/a.py")])
    rows = {r["module"]: r for r in R.static_vs_runtime(static, rep)}
    assert rows["scripts/a.py"]["observed_in_module"] == ["ALPACA_API_KEY"]
    assert rows["scripts/a.py"]["not_observed_anywhere"] == ["ALPACA_SECRET_KEY"]
    assert rows["scripts/lib/m.py"]["not_observed_anywhere"] == ["SCHWAB_APP_KEY"]
    assert R.name_kind("ALPACA_API_KEY") == "credential" and R.name_kind("BROKER_PRICE_MAX_AGE_MIN") == "config"
