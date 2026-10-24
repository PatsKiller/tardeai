"""Execute the coordinator's reference tests byte-for-byte with package imports.

Only the import resolver changes: the test source and every assertion are intact.
No global sys.modules aliases or sys.path changes leak into other test suites.
"""
import builtins
import hashlib
import json
from pathlib import Path

from scripts.lib.conflicts import engine, profiles

_FIXTURES = Path(__file__).parent / "fixtures/conflicts"
_SOURCE = (_FIXTURES / "reference_tests.py.txt").read_bytes()
_IMPORT = builtins.__import__


def _reference_import(name, *args, **kwargs):
    return {"conflict_engine": engine, "profiles": profiles}.get(name) or _IMPORT(name, *args, **kwargs)


_namespace = {"__builtins__": {**vars(builtins), "__import__": _reference_import}}
exec(compile(_SOURCE, "coordinator_reference/test_conflict_engine.py", "exec"), _namespace)
globals().update({name: value for name, value in _namespace.items() if name.startswith("test_")})


def test_reference_source_and_core_are_verbatim():
    manifest = json.loads((_FIXTURES / "reference_sha256.json").read_text())
    assert hashlib.sha256(_SOURCE).hexdigest() == manifest["test_conflict_engine.py"]
    assert hashlib.sha256(Path(engine.__file__).read_bytes()).hexdigest() == manifest["conflict_engine.py"]
