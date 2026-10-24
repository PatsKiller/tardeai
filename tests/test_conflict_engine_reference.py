"""Historical baseline only: execute the coordinator reference bytes unchanged.

Only the import resolver changes: the test source and every assertion are intact.
No global sys.modules aliases or sys.path changes leak into other test suites.
"""
import builtins
import hashlib
import json
from pathlib import Path

import sys
import types
from unittest.mock import patch

_FIXTURES = Path(__file__).parent / "fixtures/conflicts"
_SOURCE = (_FIXTURES / "reference_tests.py.txt").read_bytes()
_IMPORT = builtins.__import__
engine = types.ModuleType("_conflict_historical_engine")
with patch.dict(sys.modules, {engine.__name__: engine}):
    exec(compile((_FIXTURES / "reference_conflict_engine.py.txt").read_bytes(), "reference_engine", "exec"), engine.__dict__)
profiles = types.ModuleType("_conflict_historical_profiles")
profiles.__dict__["__builtins__"] = {**vars(builtins), "__import__": lambda name, *a, **kw: engine if name == "conflict_engine" else _IMPORT(name, *a, **kw)}
with patch.dict(sys.modules, {profiles.__name__: profiles}):
    exec(compile((_FIXTURES / "reference_profiles.py.txt").read_bytes(), "reference_profiles", "exec"), profiles.__dict__)


def _reference_import(name, *args, **kwargs):
    return {"conflict_engine": engine, "profiles": profiles}.get(name) or _IMPORT(name, *args, **kwargs)


_namespace = {"__builtins__": {**vars(builtins), "__import__": _reference_import}}
exec(compile(_SOURCE, "coordinator_reference/test_conflict_engine.py", "exec"), _namespace)
globals().update({name: value for name, value in _namespace.items() if name.startswith("test_")})


def test_reference_source_and_core_are_verbatim():
    manifest = json.loads((_FIXTURES / "reference_sha256.json").read_text())
    assert hashlib.sha256(_SOURCE).hexdigest() == manifest["test_conflict_engine.py"]
    assert hashlib.sha256((_FIXTURES / "reference_conflict_engine.py.txt").read_bytes()).hexdigest() == manifest["conflict_engine.py"]
