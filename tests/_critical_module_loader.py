"""Load a module under test from its FILE, not through its package (AGENTS.md:484).

The rule exists for a measured reason: an earlier suite left an empty stub in ``sys.modules``, and every later test that
did ``from scripts.lib import <module>`` silently asserted against that stub instead of the implementation. A package
import consults whatever the process happens to hold; a file-path load cannot.

So every critical-texts suite loads its subject with ``spec_from_file_location`` and registers the module in
``sys.modules[spec.name]`` **before** ``exec_module`` (dataclasses and pickling look the name up during execution).

Two guards keep this from becoming the same trap in a new shape:

* the registered name is test-private (``_under_test_<name>``), so it can never satisfy a later package import;
* ``load`` caches per name within the process, so two suites asking for the same module get the same object and exception
  classes compare equal.

``critical_channels`` imports ``critical_delivery`` through the package. A suite that loads both by file would otherwise
catch the package's exception class while the module under test raises the loaded one — same file, different class
object, and ``pytest.raises`` would miss it. Those suites bind the loaded copy explicitly (``cc.cd = cd``); that binding
is what makes the identity real rather than assumed.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
_CACHE: dict[str, ModuleType] = {}


def load(name: str) -> ModuleType:
    """Load ``scripts/lib/<name>.py`` by file path and return the module (identical object on repeat calls)."""
    if name in _CACHE:
        return _CACHE[name]
    path = ROOT / "scripts" / "lib" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_under_test_{name}", path)
    if spec is None or spec.loader is None:  # pragma: no cover - only on a missing or unreadable file
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # BEFORE exec_module, per AGENTS.md:484
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(spec.name, None)
        raise
    _CACHE[name] = module
    return module
