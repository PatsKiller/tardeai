"""Load each of our own modules once, whichever spelling imports it (portfolio-server, 2026-10-25).

The server runs with ``<root>/scripts`` first on ``sys.path``, ``<root>`` added by ``lib/__init__``
and, for two lazy routes, ``<root>/scripts/lib``. One file is therefore importable as ``lib.X``,
``scripts.lib.X`` and sometimes bare ``X``, or as ``holding_family`` and ``scripts.holding_family``.
Python keys modules by name, so each spelling executes the file again. Measured on a sandboxed
instance after one route replay: 40 files under ``scripts/`` loaded as 81 module objects. Each copy
holds its own caches, locks and singletons (the identity registry cache was held twice, about
18 MB each), and a class from one copy fails ``isinstance`` against the same class from the other.

``install(scripts_dir)`` puts a finder at the front of ``sys.meta_path``. When a name is imported
for the first time, the finder asks the remaining finders which file that name would load. If a
module from the same file is already loaded under another spelling, the import returns that module
object instead of executing the file again. Every other import proceeds as before:
- only files under ``scripts_dir`` are aliased; stdlib and third-party modules are never touched;
- the file must match exactly. A bare ``calendar`` that resolves to the stdlib is not aliased to
  ``scripts/lib/calendar.py``;
- a plain module still executing its body (an import cycle through two spellings) is not aliased.
  That import loads a second copy, which is the same result as without the finder. A package whose
  ``__init__`` imports its own submodules under the other spelling is aliased (same-name semantics);
  if another thread is running that ``__init__``, the import waits for it to finish (bounded, and not
  while that thread is waiting on this one).

The module keeps its first ``__name__`` and ``__spec__``, so ``importlib.reload``, ``pickle`` and
``logging.getLogger(__name__)`` see one canonical name, and every spelling resolves to it.

Scope: the portfolio-server entrypoint calls ``install()`` only when it runs as ``__main__``.
Tests that import the server module and cron or n8n scripts are unaffected, and both import styles
keep working there exactly as before. ``PORTFOLIO_SERVER_SINGLE_MODULE_LOAD=0`` turns it off.
"""

from __future__ import annotations

import importlib.abc
import importlib.util
import os
import sys
import threading
import time
from pathlib import Path

_LOCK = threading.Lock()
_FINDER: "SingleLoadFinder | None" = None
_SCRIPTS_PREFIX = "scripts."
_LIB_PREFIX = "lib."
_WAIT_SEC = 30.0  # bounded wait for another thread's package __init__ (exec_module only, never under the global lock)


def enabled() -> bool:
    """Off only when the operator sets the variable to 0/false/no/off."""
    raw = os.environ.get("PORTFOLIO_SERVER_SINGLE_MODULE_LOAD", "1")
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _real(path: str | None) -> str | None:
    if not path:
        return None
    try:
        return os.path.realpath(path)
    except (OSError, ValueError):
        return None


def _module_file(mod) -> str | None:
    return _real(getattr(mod, "__file__", None))


def alias_names(name: str) -> list[str]:
    """Other spellings that can load the same file as ``name`` (deduplicated, never ``name``)."""
    out: list[str] = []
    if name.startswith(_SCRIPTS_PREFIX):
        rest = name[len(_SCRIPTS_PREFIX) :]
        out.append(rest)
        if rest.startswith(_LIB_PREFIX):
            out.append(rest[len(_LIB_PREFIX) :])
    else:
        out.append(_SCRIPTS_PREFIX + name)
        if name.startswith(_LIB_PREFIX):
            out.append(name[len(_LIB_PREFIX) :])
        elif name != "lib":
            out.append(_LIB_PREFIX + name)
            out.append(_SCRIPTS_PREFIX + _LIB_PREFIX + name)
    seen: list[str] = []
    for cand in out:
        if cand and cand != name and cand not in seen:
            seen.append(cand)
    return seen


def _initializing(mod) -> bool:
    spec = getattr(mod, "__spec__", None)
    return bool(getattr(spec, "_initializing", False))


def _lock_owner(name: str):
    """Thread id holding the import lock of ``name`` (CPython importlib internals); None when unknown."""
    try:
        from importlib import _bootstrap

        ref = _bootstrap._module_locks.get(name)
        lock = ref() if ref is not None else None
        return getattr(lock, "owner", None)
    except Exception:
        return None


def _waits_on_me(owner) -> bool:
    """Is thread ``owner`` (transitively) blocked on an import lock this thread holds? CPython internals."""
    try:
        from importlib import _bootstrap

        return bool(
            _bootstrap._has_deadlocked(
                threading.get_ident(), seen_ids=set(), candidate_ids=[owner], blocking_on=_bootstrap._blocking_on
            )
        )
    except Exception:
        return True  # unknown: do not wait on a thread that may be waiting on us


def _package_alias_wait(mod):
    """Can a package still executing its ``__init__`` be aliased, and must the alias wait for it?

    Returns ``(alias, owner)``: ``owner`` is the thread id the alias waits on, or None.
    Same thread: alias, no wait. The package is importing its own submodules under the other spelling, and
    aliasing gives the ordinary same-name semantics (its ``__path__`` is already set). A second package copy
    would also hold its own submodule attributes, so ``import scripts.lib.pkg.child as c`` could fail on the
    shared parent.
    Another thread: alias, and ``exec_module`` waits until that ``__init__`` finishes, as an import of the
    same name would. (``find_spec`` runs under the global import lock, so it never waits itself.)
    A plain module mid-cycle is never aliased: the caller loads a second copy, as without the finder.
    """
    if not hasattr(mod, "__path__"):
        return False, None
    owner = _lock_owner(getattr(getattr(mod, "__spec__", None), "name", "") or "")
    if owner is None or owner == threading.get_ident():
        return True, None
    return True, owner


class _AliasLoader(importlib.abc.Loader):
    """Returns an already-loaded module object for a second spelling and never re-executes it."""

    def __init__(self, module, wait_owner=None) -> None:
        self._module = module
        self._spec = getattr(module, "__spec__", None)
        self._wait_owner = wait_owner

    def create_module(self, spec):
        return self._module

    def exec_module(self, module) -> None:
        # module_from_spec() overwrote __spec__ with the alias spec; keep the canonical one so
        # importlib.reload() and pickle resolve the module by its first name.
        if self._spec is not None:
            try:
                module.__spec__ = self._spec
            except AttributeError:
                pass
        if self._wait_owner is None:
            return
        # Another thread is executing this package's __init__. Wait for it (only the module lock of this
        # spelling is held here). Stop waiting when that thread waits on this one: its __init__ imports this
        # spelling, and it then proceeds on the alias with same-name semantics. Bounded by _WAIT_SEC.
        deadline = time.monotonic() + _WAIT_SEC
        while _initializing(module) and not _waits_on_me(self._wait_owner) and time.monotonic() < deadline:
            time.sleep(0.005)


class SingleLoadFinder(importlib.abc.MetaPathFinder):
    def __init__(self, scripts_dir: str | os.PathLike) -> None:
        self.scripts_dir = os.path.realpath(os.fspath(scripts_dir))
        self.aliased = 0

    def _owned(self, path: str | None) -> bool:
        return bool(path) and (path == self.scripts_dir or path.startswith(self.scripts_dir + os.sep))

    def _loaded_twin(self, name: str):
        for cand in alias_names(name):
            mod = sys.modules.get(cand)
            if mod is None:
                continue
            path = _module_file(mod)
            if not self._owned(path):
                continue
            wait_owner = None
            if _initializing(mod):
                alias, wait_owner = _package_alias_wait(mod)
                if not alias:
                    continue
            yield mod, path, wait_owner

    def _would_load(self, name, path, target):
        for finder in sys.meta_path:
            if finder is self or isinstance(finder, SingleLoadFinder):
                continue
            find_spec = getattr(finder, "find_spec", None)
            if find_spec is None:
                continue
            spec = find_spec(name, path, target)
            if spec is not None:
                return spec
        return None

    def find_spec(self, name, path=None, target=None):
        if sys.modules.get(name) is not None:
            return None  # importlib.reload(): re-execute the file under its own name, never alias it
        twins = list(self._loaded_twin(name))
        if not twins:
            return None
        spec = self._would_load(name, path, target)
        if spec is None:
            return None
        origin = _real(spec.origin) if spec.has_location else None
        if not self._owned(origin):
            return None
        for mod, mod_path, wait_owner in twins:
            if mod_path == origin:
                self.aliased += 1
                return importlib.util.spec_from_loader(
                    name, _AliasLoader(mod, wait_owner), origin=spec.origin, is_package=hasattr(mod, "__path__")
                )
        return spec


def install(scripts_dir: str | os.PathLike | None = None) -> SingleLoadFinder | None:
    """Install the finder once per process and fold spellings that are already loaded. Idempotent."""
    global _FINDER
    if not enabled():
        return None
    scripts_dir = scripts_dir or Path(__file__).resolve().parents[1]
    with _LOCK:
        if _FINDER is None:
            _FINDER = SingleLoadFinder(scripts_dir)
            sys.meta_path.insert(0, _FINDER)
        _fold_loaded(_FINDER)
        return _FINDER


def uninstall() -> None:
    """Remove the finder (tests). Aliases already in sys.modules stay."""
    global _FINDER
    with _LOCK:
        if _FINDER is not None:
            try:
                sys.meta_path.remove(_FINDER)
            except ValueError:
                pass
        _FINDER = None


def _bind_parent(name: str, mod) -> None:
    parent, _, child = name.rpartition(".")
    if parent and parent in sys.modules:
        try:
            setattr(sys.modules[parent], child, mod)
        except (AttributeError, TypeError):
            pass


def _fold_loaded(finder: SingleLoadFinder) -> None:
    """Point an absent spelling at a module loaded before install(). Two existing copies stay as they are."""
    for name, mod in list(sys.modules.items()):
        path = _module_file(mod)
        if not finder._owned(path) or _initializing(mod):
            continue
        for cand in alias_names(name):
            if cand in sys.modules:
                continue
            parent = cand.rpartition(".")[0]
            if parent and sys.modules.get(parent) is None:
                continue
            if not _would_resolve_to(cand, path):
                continue
            sys.modules[cand] = mod
            _bind_parent(cand, mod)


def _would_resolve_to(name: str, path: str) -> bool:
    try:
        parent = name.rpartition(".")[0]
        search = getattr(sys.modules[parent], "__path__", None) if parent else None
        if parent and search is None:
            return False
        for finder in sys.meta_path:
            if isinstance(finder, SingleLoadFinder):
                continue
            find_spec = getattr(finder, "find_spec", None)
            if find_spec is None:
                continue
            spec = find_spec(name, search, None)
            if spec is not None:
                return _real(spec.origin) == path
    except (ImportError, ValueError, AttributeError, KeyError):
        return False
    return False


def duplicate_modules(scripts_dir: str | os.PathLike | None = None) -> dict[str, list[str]]:
    """Files under ``scripts_dir`` held by more than one distinct module object: {file: [names]}."""
    root = os.path.realpath(os.fspath(scripts_dir or Path(__file__).resolve().parents[1]))
    by_file: dict[str, dict[int, list[str]]] = {}
    for name, mod in list(sys.modules.items()):
        path = _module_file(mod)
        if not path or not (path == root or path.startswith(root + os.sep)):
            continue
        by_file.setdefault(path, {}).setdefault(id(mod), []).append(name)
    return {
        path: sorted(n for names in objs.values() for n in names)
        for path, objs in sorted(by_file.items())
        if len(objs) > 1
    }
