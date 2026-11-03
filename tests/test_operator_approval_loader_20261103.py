"""Trusted-main module loading: verified immutable bytes, normal import context.

All helper files are synthetic pytest artifacts. No installed guard, credentials,
network or subprocess is reached. Mismatch/file-safety tests remain in the
existing authority suite; these cover standard-loader execution and races.
"""

from __future__ import annotations

import builtins
import importlib.abc
import importlib.util
import io
import socket
import subprocess
import sys
import typing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def forbidden(*args, **kwargs):
    pytest.fail("Verified snapshot loading reached an unexpected filesystem/cache/process/network operation")


@pytest.fixture
def authority(monkeypatch):
    path = ROOT / "scripts/lib/operator_approval_authority.py"
    spec = importlib.util.spec_from_file_location("approval_loader_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    original = set(sys.modules)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    yield mod
    # Test-created module identities are the only entries this fixture retires.
    for name in set(sys.modules) - original:
        if name.startswith("approval_authority_helper_"):
            sys.modules.pop(name, None)


def helper(tmp_path, name, source):
    path = tmp_path / name
    path.write_text(source)
    path.chmod(0o600)
    return path


def test_future_annotations_dataclass_and_standard_module_context(authority, tmp_path, monkeypatch):
    source = (
        "from __future__ import annotations\n"
        "import sys\n"
        "from dataclasses import dataclass\n"
        "CONTEXT_READY = sys.modules[__name__].__dict__ is globals()\n"
        "@dataclass(frozen=True)\n"
        "class Record:\n"
        "    name: str\n"
        "    child: Record | None = None\n"
        "VALUE = Record('verified')\n"
    )
    path = helper(tmp_path, "helper_context.py", source)
    before = path.read_bytes()
    # Do not let pytest's bytecode-disabled environment hide a cache write.
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    import importlib._bootstrap_external as external

    monkeypatch.setattr(external, "_write_atomic", forbidden)
    module = authority._module(path, source)
    assert module.CONTEXT_READY is True
    assert module.VALUE.name == "verified" and module.VALUE.child is None
    assert module.Record.__annotations__["name"] == "str"
    assert module.Record in typing.get_args(typing.get_type_hints(module.Record)["child"])
    assert sys.modules[module.__name__] is module
    assert module.__spec__.loader is module.__loader__
    assert isinstance(module.__loader__, importlib.abc.SourceLoader)
    assert module.__spec__.origin == str(path) and module.__file__ == str(path)
    assert path.read_bytes() == before
    assert sorted(entry.name for entry in tmp_path.iterdir()) == [path.name]


def test_path_swap_after_verified_read_cannot_replace_executed_snapshot(authority, tmp_path, monkeypatch):
    original = "VALUE = 'verified snapshot'\n"
    replaced = "VALUE = 'unverified replacement'\n"
    path = helper(tmp_path, "helper_race.py", original)
    read = authority._read
    read_calls, exec_names = [], []

    def observed_read(target):
        read_calls.append(target)
        return read(target)

    standard_exec = importlib.abc.SourceLoader.exec_module

    def swap_before_standard_exec(loader, module):
        assert read_calls == [path]
        assert sys.modules[module.__name__] is module
        exec_names.append(module.__name__)
        # This is after _module received the verified bytes and before execution.
        path.write_text(replaced)
        with monkeypatch.context() as no_reread:
            no_reread.setattr(builtins, "open", forbidden)
            no_reread.setattr(io, "open", forbidden)
            no_reread.setattr(io, "open_code", forbidden)
            import os

            no_reread.setattr(os, "open", forbidden)
            import importlib._bootstrap_external as external

            no_reread.setattr(external, "_write_atomic", forbidden)
            return standard_exec(loader, module)

    monkeypatch.setattr(authority, "_read", observed_read)
    monkeypatch.setattr(importlib.abc.SourceLoader, "exec_module", swap_before_standard_exec)
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    module = authority._module(path, original)
    assert module.VALUE == "verified snapshot"
    assert read_calls == [path] and exec_names == [module.__name__]
    assert path.read_text() == replaced
    assert module.__loader__.get_data(str(path)) == original.encode()
    with pytest.raises(OSError, match="unverified_helper_read"):
        module.__loader__.get_data(str(path.with_suffix(".pyc")))
    assert sorted(entry.name for entry in tmp_path.iterdir()) == [path.name]


@pytest.mark.parametrize(
    "source,error",
    [
        ("raise RuntimeError('synthetic failure')\n", RuntimeError),
        ("raise SystemExit('synthetic failure')\n", SystemExit),
        ("def broken(:\n", SyntaxError),
    ],
)
def test_failed_import_unregisters_new_module(authority, tmp_path, monkeypatch, source, error):
    path = helper(tmp_path, "helper_failure.py", source)
    observed = []
    standard_exec = importlib.abc.SourceLoader.exec_module

    def observe(loader, module):
        assert sys.modules[module.__name__] is module
        observed.append(module.__name__)
        return standard_exec(loader, module)

    monkeypatch.setattr(importlib.abc.SourceLoader, "exec_module", observe)
    with pytest.raises(error):
        authority._module(path, source)
    assert len(observed) == 1
    assert observed[0] not in sys.modules
    assert sorted(entry.name for entry in tmp_path.iterdir()) == [path.name]


@pytest.mark.parametrize("previous_none", [False, True])
def test_failed_reload_restores_previous_module_or_none_entry(authority, tmp_path, monkeypatch, previous_none):
    source = (
        "import builtins\n"
        "if getattr(builtins, '_cx4_synthetic_loader_failure', False):\n"
        "    raise RuntimeError('synthetic reload failure')\n"
        "VALUE = 'previous verified module'\n"
    )
    path = helper(tmp_path, "helper_previous.py", source)
    monkeypatch.setattr(builtins, "_cx4_synthetic_loader_failure", False, raising=False)
    previous = authority._module(path, source)
    assert previous.VALUE == "previous verified module"
    if previous_none:
        sys.modules[previous.__name__] = None
    monkeypatch.setattr(builtins, "_cx4_synthetic_loader_failure", True)
    with pytest.raises(RuntimeError, match="synthetic reload failure"):
        authority._module(path, source)
    assert previous.__name__ in sys.modules
    assert sys.modules[previous.__name__] is (None if previous_none else previous)
