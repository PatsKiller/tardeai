"""Package marker for ``scripts.lib`` -- and the sys.path bootstrap for cron.

Why this file has content
-------------------------
``scripts`` has no ``__init__.py``. It is an implicit namespace package, and it
resolves only when the repository root is on ``sys.path``. Exactly one place put
it there -- ``scripts/portfolio_server.py`` -- the web server entrypoint. No
scheduled job had an equivalent.

A cron line that runs a script BY PATH gets ``sys.path[0] = <root>/scripts``,
not ``<root>``. So ``import scripts.lib.X`` raises
``ModuleNotFoundError: No module named 'scripts'``. Both morning briefs were
undelivered from 2026-08-28 for exactly this reason, and the failure reproduces
from the served release -- it is not a stale-checkout problem, and a promote
does not fix it.

Every failing import chain passes through this file before the import that
fails, so the bootstrap belongs here.

It is derived from ``__file__``, never from an environment variable. An env var
can be pointed at a directory that only appears to work -- that mistake is
already on record in ``CLAUDE.md``.
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

# <root>/scripts/lib/__init__.py -> parents[2] == <root>
_ROOT = _Path(__file__).resolve().parents[2]
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))


class DualImportIdentityError(RuntimeError):
    """A submodule is loaded as both ``lib.X`` and ``scripts.lib.X``."""


def _dual_loaded_submodules() -> list[str]:
    """Submodules present under both spellings as distinct objects."""
    out = []
    for name, mod in list(_sys.modules.items()):
        if not name.startswith("lib."):
            continue
        twin = _sys.modules.get("scripts." + name)
        if twin is not None and twin is not mod:
            out.append(name[4:])
    return sorted(out)


def assert_single_import_identity() -> None:
    """Raise if any submodule is loaded under both spellings.

    Putting the root on ``sys.path`` makes ``scripts.lib`` importable
    everywhere, while running a script by path keeps bare ``lib`` importable
    too. Python treats those as distinct module objects, so a class defined in
    one fails ``isinstance`` against the same class imported through the other.
    That defect is on record here: it cost ``isinstance`` checks on 8 of 18
    broker collectors.

    Scoped deliberately to SUBMODULES. The package itself is legitimately
    reachable under both names the moment both spellings exist in the tree, and
    the real delivery chain does exactly that -- ``aegis_morning_brief_delivery``
    imports ``lib.cio_operator_renderers``, which imports
    ``scripts.lib.brief_semantic_dedupe``. Raising on the package would convert
    a restored morning brief into a hard failure, which is a worse outcome than
    the one being fixed. Classes do not live in ``__init__``; they live in the
    submodules, and that is where ``isinstance`` actually breaks.

    NOT called at import time: during ``scripts.lib.__init__`` no submodule has
    loaded yet, so a check there is guaranteed to pass and would be theatre.
    Call it from an entrypoint after imports settle, or from a test.

    LIMIT, stated rather than implied: normalising the 3,244 ``scripts.``/
    ``lib.`` spellings is the real repair. It is a separate wave and must not
    gate restoring the briefs.
    """
    dual = _dual_loaded_submodules()
    if dual:
        raise DualImportIdentityError(
            "loaded under both lib.X and scripts.lib.X as distinct objects: "
            + ", ".join(dual)
            + ". isinstance() across this boundary silently returns False. "
            "Import one spelling consistently -- prefer scripts.lib.X."
        )
