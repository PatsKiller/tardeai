"""ANCHOR: MODULE_SINGLE_LOAD_20261025 — portfolio-server loads each of its own modules once.

scripts/lib/module_single_load.py installs a meta-path finder (portfolio_server.py, as __main__ only). When a file
under scripts/ is already loaded under one spelling (lib.X, scripts.lib.X, bare X, or holding_family vs
scripts.holding_family), importing another spelling returns that module object, so caches, locks and classes are
shared instead of being held twice.

Every import below runs in a child interpreter: the finder and the aliases it adds to sys.modules are process-wide,
and this pytest process must keep its normal import behaviour. Children inherit the hermetic environment from
conftest (fixture HOME, empty env files) and install the hermetic guard themselves.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(ROOT))

from scripts.lib import module_single_load as M  # noqa: E402


def _run(code: str, *args: str, cwd: Path | None = None) -> dict:
    proc = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code), *args],
        cwd=str(cwd or ROOT),
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert proc.returncode == 0, proc.stderr[-4000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_alias_names_cover_the_three_spellings():
    assert M.alias_names("lib.identity_registry") == ["scripts.lib.identity_registry", "identity_registry"]
    assert M.alias_names("scripts.lib.identity_registry") == ["lib.identity_registry", "identity_registry"]
    assert M.alias_names("identity_registry") == [
        "scripts.identity_registry",
        "lib.identity_registry",
        "scripts.lib.identity_registry",
    ]
    assert M.alias_names("scripts.holding_family") == ["holding_family"]
    assert M.alias_names("lib") == ["scripts.lib"]
    assert M.alias_names("scripts.lib") == ["lib"]


# ── synthetic tree: identity, isinstance, pickle, reload, stdlib collision, cycles ────────────────────────────────

_TREE = {
    "scripts/lib/__init__.py": (
        "import sys as _s, pathlib as _p\n"
        "_R = str(_p.Path(__file__).resolve().parents[2])\n"
        "if _R not in _s.path:\n    _s.path.insert(0, _R)\n"
    ),
    "scripts/lib/registry.py": (
        "import builtins, threading\nbuiltins._REG_EXEC = getattr(builtins, '_REG_EXEC', 0) + 1\n"
        "CACHE = {}\nLOCK = threading.Lock()\nLOADS = []\nLOADS.append(__name__)\n"
        "class Entry:\n    def __init__(self, v):\n        self.v = v\n"
    ),
    "scripts/lib/pkg/__init__.py": "from scripts.lib.pkg.child import VALUE\n",
    "scripts/lib/pkg/child.py": "VALUE = 7\nSTATE = {}\n",
    # a plain-module cycle through two spellings: b needs LATE from a copy of a, which works only as a second copy
    "scripts/lib/cyc_a.py": "EARLY = 0\nimport scripts.lib.cyc_b\nLATE = 2\n",
    "scripts/lib/cyc_b.py": "from scripts.lib.cyc_a import LATE\nB = 1\n",
    "scripts/lib/calendar.py": "SHADOW = True\n",
    "scripts/topmod.py": (
        "import builtins, threading\nbuiltins._TOP_EXEC = getattr(builtins, '_TOP_EXEC', 0) + 1\nLOCK = threading.Lock()\n"
    ),
    "scripts/lib/slowpkg/__init__.py": "import time\ntime.sleep(0.4)\nfrom scripts.lib.slowpkg.child import V\nREADY = True\n",
    "scripts/lib/slowpkg/child.py": "V = 1\n",
    "scripts/lib/slowsame/__init__.py": "import time\ntime.sleep(0.4)\nfrom lib.slowsame.child import V\nREADY = True\n",
    "scripts/lib/slowsame/child.py": "V = 1\n",
    "scripts/lib/slowlong/__init__.py": "import time\ntime.sleep(1.0)\nfrom lib.slowlong.child import V\nREADY = True\n",
    "scripts/lib/slowlong/child.py": "V = 1\n",
}

_SYNTH = r"""
import importlib, json, pickle, sys
root, mode = sys.argv[1], sys.argv[2]
sys.path[:0] = [root + "/shim", root + "/scripts"]
from module_single_load import install, duplicate_modules, uninstall
import lib.registry as early   # loaded BEFORE install: install() must fold it
f = install(root + "/scripts") if mode == "on" else None
import scripts.lib.registry as b
sys.path.append(root + "/scripts/lib")
import registry as c
import lib.pkg, scripts.lib.pkg, scripts.lib.pkg.child as pc, lib.pkg.child as lc
import lib.cyc_a, scripts.lib.cyc_b
import topmod, scripts.topmod
import lib.calendar  # scripts/lib/calendar.py shadows the stdlib name only under the lib spelling
import calendar
e = early.Entry(5)
out = {
    "same3": early is b is c,
    "isinstance": isinstance(b.Entry(1), early.Entry) and isinstance(e, c.Entry),
    "cache_shared": early.CACHE is b.CACHE is c.CACHE and early.LOCK is b.LOCK,
    "loads": early.LOADS,
    "pkg": sys.modules["lib.pkg"] is sys.modules["scripts.lib.pkg"],
    "pkg_child": pc is lc,
    "attr_binding": sys.modules["scripts.lib"].pkg is sys.modules["lib.pkg"],
    "top": sys.modules["topmod"] is sys.modules["scripts.topmod"],
    "stdlib_calendar": calendar is not lib.calendar and not hasattr(calendar, "SHADOW"),
    "cyc_ok": lib.cyc_a.LATE == 2 and scripts.lib.cyc_b.B == 1,
    "dups": sorted(p.split("/scripts/", 1)[1] for p in duplicate_modules(root + "/scripts")),
}
if mode == "on":
    obj = pickle.loads(pickle.dumps(e))
    out["pickle"] = type(obj) is b.Entry and obj.v == 5
    import builtins
    out["exec_before_reload"] = builtins._REG_EXEC
    importlib.reload(b)
    out["exec_after_reload"] = builtins._REG_EXEC
    out["reload_keeps_identity"] = sys.modules["lib.registry"] is sys.modules["scripts.lib.registry"] is b
    out["canonical_name"] = b.__name__ == b.__spec__.name == "lib.registry"
    out["aliased"] = f.aliased
    uninstall()
    out["uninstalled"] = not any(type(x).__name__ == "SingleLoadFinder" for x in sys.meta_path)
print(json.dumps(out))
"""


@pytest.fixture()
def synthetic_root(tmp_path):
    for rel, body in _TREE.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    (tmp_path / "shim").mkdir()
    (tmp_path / "shim" / "module_single_load.py").write_text(
        Path(M.__file__).read_text(encoding="utf-8"), encoding="utf-8"
    )
    return tmp_path


def test_without_the_finder_each_spelling_executes_the_file_again(synthetic_root):
    """Control: the defect this fixes, reproduced on a synthetic tree."""
    out = _run(_SYNTH, str(synthetic_root), "off")
    assert out["same3"] is False and out["isinstance"] is False and out["cache_shared"] is False
    assert out["loads"] == ["lib.registry"]  # the other copies logged their own names in their own lists
    assert {"lib/registry.py", "topmod.py", "lib/pkg/__init__.py", "lib/cyc_a.py"} <= set(out["dups"])


def test_with_the_finder_every_spelling_is_one_module_object(synthetic_root):
    out = _run(_SYNTH, str(synthetic_root), "on")
    assert out["same3"] and out["isinstance"] and out["cache_shared"]
    assert out["loads"] == ["lib.registry"]  # executed once
    assert out["pkg"] and out["pkg_child"] and out["attr_binding"] and out["top"]
    assert out["pickle"] and out["reload_keeps_identity"] and out["canonical_name"]
    # executed once for three spellings; importlib.reload (api_v2 hot reload) still re-executes it
    assert (out["exec_before_reload"], out["exec_after_reload"]) == (1, 2)
    assert out["stdlib_calendar"], "a bare stdlib name must never be aliased to a file under scripts/"
    assert out["cyc_ok"], "an import cycle through two spellings must still import"
    # cyc_b imports cyc_a under the other spelling while cyc_a is still executing: that copy stays, as before.
    # pkg/__init__ imports its own child under the other spelling: aliased, so the package is one object.
    assert out["dups"] == ["lib/cyc_a.py"]
    assert out["aliased"] >= 6 and out["uninstalled"]


_THREADS = r"""
import importlib, json, sys, threading, time
root, pkg = sys.argv[1], sys.argv[2]
sys.path[:0] = [root + "/shim", root + "/scripts"]
import module_single_load
from module_single_load import install, duplicate_modules
if len(sys.argv) > 3:
    module_single_load._WAIT_SEC = float(sys.argv[3])
import lib
install(root + "/scripts")
got, errs = {}, []
def a():
    importlib.import_module("lib." + pkg)
def b():
    time.sleep(0.1)  # lib.<pkg> is mid-__init__ in thread a
    try:
        importlib.import_module("scripts.lib." + pkg + ".child")
        got["ready_at_import"] = getattr(sys.modules["scripts.lib." + pkg], "READY", False)
    except BaseException as exc:
        errs.append(repr(exc))
t0 = time.monotonic()
ts = [threading.Thread(target=a), threading.Thread(target=b)]
[t.start() for t in ts]; [t.join() for t in ts]
print(json.dumps({
    "same": sys.modules["lib." + pkg] is sys.modules["scripts.lib." + pkg],
    "child_same": sys.modules["lib." + pkg + ".child"] is sys.modules["scripts.lib." + pkg + ".child"]
    if "lib." + pkg + ".child" in sys.modules else True,
    "ready_at_import": got.get("ready_at_import"), "ready": sys.modules["lib." + pkg].READY,
    "errs": errs, "dups": len(duplicate_modules(root + "/scripts")), "secs": round(time.monotonic() - t0, 1),
}))
"""


def test_another_threads_package_init_is_awaited_not_split(synthetic_root):
    """Thread b imports scripts.lib.slowsame.child while thread a runs lib.slowsame's __init__: b waits for it,
    as an import of the same name would, and gets the finished package."""
    out = _run(_THREADS, str(synthetic_root), "slowsame")
    assert out["same"] and out["child_same"] and out["errs"] == [] and out["dups"] == 0
    assert out["ready_at_import"] is True and out["secs"] < 5


def test_cross_thread_self_import_does_not_deadlock(synthetic_root):
    """lib.slowpkg's __init__ imports scripts.lib.slowpkg.child while thread b holds that spelling's lock.
    Waiting would deadlock, so b runs the normal import (its own complete copy, as without the finder) and never
    sees the half-initialized package."""
    out = _run(_THREADS, str(synthetic_root), "slowpkg")
    assert out["errs"] == [] and out["ready_at_import"] is True and out["ready"] and out["secs"] < 5


def test_wait_timeout_runs_the_normal_import_not_a_half_initialized_package(synthetic_root):
    """Thread a's lib.slowlong __init__ outlasts the (shortened) wait: b imports a complete copy of its own."""
    out = _run(_THREADS, str(synthetic_root), "slowlong", "0.2")
    assert out["errs"] == [] and out["ready_at_import"] is True and out["ready"]
    assert out["same"] is False  # a separate copy, exactly as without the finder


_POPS = r"""
import builtins, importlib, json, sys
root = sys.argv[1]
sys.path[:0] = [root + "/shim", root + "/scripts"]
import module_single_load as M
import lib  # puts the synthetic root on sys.path, as scripts/lib/__init__ does
M.install(root + "/scripts")
count = lambda: builtins._TOP_EXEC
import topmod, scripts.topmod
out = {"one": topmod is scripts.topmod and count() == 1}
old = topmod
sys.modules.pop("topmod")  # pop only the module's own name (pre-fix api_v2): the alias must not revive it
fresh = importlib.import_module("topmod")
out["own_name_pop_is_fresh"] = fresh is not old and count() == 2
for spelling in ("topmod", "scripts.topmod"):  # api_v2 self-heal: every spelling
    sys.modules.pop(spelling, None)
again = importlib.import_module("scripts.topmod")
out["all_spellings_pop_is_fresh"] = again is not fresh and count() == 3 and importlib.import_module("topmod") is again

# F1: any error inside the finder steps aside and the normal import runs
def boom(self, name):
    raise RuntimeError("finder bug")
    yield
M.SingleLoadFinder._loaded_twin = boom
import lib.registry
out["finder_error_steps_aside"] = lib.registry.CACHE == {}
print(json.dumps(out))
"""


def test_popped_modules_load_fresh_and_finder_errors_step_aside(synthetic_root):
    out = _run(_POPS, str(synthetic_root))
    assert out == {
        "one": True,
        "own_name_pop_is_fresh": True,
        "all_spellings_pop_is_fresh": True,
        "finder_error_steps_aside": True,
    }


def test_api_v2_self_heal_pops_every_spelling():
    src = (SCRIPTS / "api_v2.py").read_text(encoding="utf-8")
    block = src[src.index("for _stale in (") : src.index("PROJECT_ROOT = ")]
    assert 'for _spelling in (_stale, "scripts." + _stale):' in block
    assert "_sys_heal.modules.pop(_spelling, None)" in block


# ── real modules ─────────────────────────────────────────────────────────────────────────────────────────────────

_REAL = r"""
import json, sys
root = sys.argv[1]
sys.path[:0] = [root + "/scripts"]
from scripts.lib import hermetic_test_guard as G
G.install()
from scripts.lib import module_single_load as M
M.install(root + "/scripts")
import lib.identity_registry as a
import scripts.lib.identity_registry as b
sys.path.insert(0, root + "/scripts/lib")
import identity_registry as c
import holding_family as h1
import scripts.holding_family as h2
print(json.dumps({
    "registry": a is b is c,
    "load_cached": a.load_cached is b.load_cached,
    "holding_family": h1 is h2,
    "dups": len(M.duplicate_modules(root + "/scripts")),
    "guard": len(G.drain()),
}))
"""


def test_identity_registry_and_holding_family_load_once():
    out = _run(_REAL, str(ROOT))
    assert out == {"registry": True, "load_cached": True, "holding_family": True, "dups": 0, "guard": 0}


# ── server import closure ────────────────────────────────────────────────────────────────────────────────────────


def _resolve(name: str) -> Path | None:
    rel = name.replace(".", "/")
    for base in (ROOT, SCRIPTS, SCRIPTS / "lib"):
        for p in (base / f"{rel}.py", base / rel / "__init__.py"):
            if p.is_file():
                rp = p.resolve()
                return rp if rp.is_relative_to(SCRIPTS) else None
    return None


def _server_closure_spellings() -> dict[str, list[str]]:
    """Every own file the server can reach (module-level and lazy imports), with each spelling that names it."""
    spell: dict[Path, set[str]] = {}
    seen: set[Path] = set()
    todo = [SCRIPTS / "portfolio_server.py"]
    while todo:
        f = todo.pop()
        if f in seen:
            continue
        seen.add(f)
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                names = [node.module, *(f"{node.module}.{a.name}" for a in node.names)]
            for nm in names:
                if nm.split(".")[0] in sys.stdlib_module_names:
                    continue
                parts = nm.split(".")
                for i in range(1, len(parts) + 1):
                    sub = ".".join(parts[:i])
                    p = _resolve(sub)
                    if p is not None:
                        spell.setdefault(p, set()).add(sub)
                        todo.append(p)
    return {str(p): sorted(s) for p, s in sorted(spell.items()) if len(s) > 1}


_CLOSURE = r"""
import contextlib, importlib, io, json, sys, types
root, spec_path, mode, order = sys.argv[1:5]
multi = json.load(open(spec_path))
sys.path[:0] = [root + "/scripts"]
from scripts.lib import hermetic_test_guard as G
G.install()
from scripts.lib import module_single_load as M
if mode == "on":
    M.install(root + "/scripts")
failed = {}
for path, names in sorted(multi.items()):
    for n in sorted(names, key=lambda n: (n.startswith("scripts.") == (order == "lib_first"), n)):
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                importlib.import_module(n)
        except BaseException as exc:
            failed[n] = type(exc).__name__
dups = M.duplicate_modules(root + "/scripts")
split = {}
for path, names in dups.items():
    objs = {id(sys.modules[n]): sys.modules[n] for n in names}.values()
    first, *rest = objs
    for other in rest:
        for k in set(vars(first)) | set(vars(other)):
            if k.startswith("__"):
                continue
            if getattr(first, k, None) is not getattr(other, k, None):
                split.setdefault(path, []).append(k)
print(json.dumps({"files": len(multi), "failed": failed, "dups": dups, "split": split, "guard": len(G.drain())}))
"""


@pytest.fixture(scope="module")
def closure_spec(tmp_path_factory):
    multi = _server_closure_spellings()
    path = tmp_path_factory.mktemp("closure") / "multi.json"
    path.write_text(json.dumps(multi), encoding="utf-8")
    return path, multi


def test_server_closure_is_reachable_under_more_than_one_spelling(closure_spec):
    _, multi = closure_spec
    assert str((SCRIPTS / "lib" / "identity_registry.py").resolve()) in multi
    assert str((SCRIPTS / "holding_family.py").resolve()) in multi
    assert len(multi) >= 40


@pytest.mark.parametrize("order", ["scripts_first", "lib_first"])
def test_server_import_closure_holds_one_module_per_file(closure_spec, order):
    path, multi = closure_spec
    off = _run(_CLOSURE, str(ROOT), str(path), "off", order)
    on = _run(_CLOSURE, str(ROOT), str(path), "on", order)
    assert len(off["dups"]) >= 40, "control: without the finder the closure must show the duplicates"
    # The finder never adds an import failure (CI lacks some optional drivers; those fail identically).
    assert set(on["failed"]) <= set(off["failed"]), sorted(set(on["failed"]) - set(off["failed"]))
    # Measured 2026-10-25: 362 files reachable under >1 spelling; without the finder 389 files load as 2+ objects,
    # with it none, in either import order. `split` lists names whose objects differ between copies.
    assert on["dups"] == {}, on["dups"]
    assert on["split"] == {}, on["split"]


# ── wiring ───────────────────────────────────────────────────────────────────────────────────────────────────────


def test_server_installs_the_finder_as_main_before_its_first_own_import():
    tree = ast.parse((SCRIPTS / "portfolio_server.py").read_text(encoding="utf-8"))
    install_line = first_own_import = None
    for node in tree.body:
        if (
            install_line is None
            and isinstance(node, ast.If)
            and ast.unparse(node.test) in {"__name__ == '__main__'", '__name__ == "__main__"'}
            and "module_single_load.install(" in ast.unparse(node)
        ):
            install_line = node.lineno
        if first_own_import is None:
            for sub in ast.walk(node):
                if isinstance(sub, ast.ImportFrom) and (sub.module or "").split(".")[0] in {"lib", "scripts"}:
                    if "module_single_load" not in ast.unparse(sub):
                        first_own_import = sub.lineno
                        break
    assert install_line is not None, "portfolio_server must install the finder under __name__ == '__main__'"
    assert first_own_import is not None and install_line < first_own_import


def test_importing_the_shim_does_not_install_it():
    assert not any(isinstance(f, M.SingleLoadFinder) for f in sys.meta_path)


def test_opt_out_variable(monkeypatch):
    monkeypatch.setenv("PORTFOLIO_SERVER_SINGLE_MODULE_LOAD", "0")
    assert M.enabled() is False
    assert M.install(SCRIPTS) is None
    monkeypatch.setenv("PORTFOLIO_SERVER_SINGLE_MODULE_LOAD", "1")
    assert M.enabled() is True
