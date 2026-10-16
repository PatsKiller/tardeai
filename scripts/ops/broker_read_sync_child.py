#!/usr/bin/env python3
"""broker_read_sync_child — runs ONE allowlisted step of the read-only broker sync inside runtime guards.

Never invoked by hand. ``scripts/ops/broker_read_sync.py`` starts it as
``bash --noprofile --norc -c '<cd root; source .env; force read_only; exec python child STEP MODE>'``, so the
credential file is loaded by this process's own shell and never by the orchestrator an agent reads.

Arguments are a step id and a mode, nothing else. The step's script and argv come from
``scripts/lib/broker_read_sync_policy.STEPS``; an unknown id or mode exits 64 before anything is imported.

Before the step's code runs, in this process:
  1. ``TRADEAI_SCHWAB_ACCESS_MODE`` must resolve to ``read_only`` (``lib.schwab_access_mode.status()``);
  2. the trading lock must be LOCKED for schwab, alpaca, moomoo and snaptrade (``lib.trading_lock.lock_state``);
  3. an import hook refuses every EXCLUDED module (stop managers, stop sync, options lifecycle, defense
     execution, order pilots, approval/2FA, the API server, active trader) and, right after
     ``schwab_transport`` / ``moomoo.client`` / ``schwab_token_manager`` / the futu SDK execute, replaces their
     order-write and re-auth attributes with a refusal (``RUNTIME_STUBS``, ``SDK_STUBS``);
  4. HTTP clients (urllib3 pools — requests and SDKs ride them —, httpx, urllib.request) refuse any non-GET/HEAD
     request to a broker host: no order route, no OAuth token refresh;
  5. ``subprocess`` refuses to start another Python interpreter or a ``.py`` file (it would run unguarded).

Every refusal raises ``BrokerReadSyncRefused`` with the ``BROKER_READ_SYNC_GUARD`` marker; the orchestrator
stops the run on it. Exit codes: the step's own, 64 usage, 65 precondition refused, 66 guard tripped.
"""

from __future__ import annotations

import importlib.abc
import importlib.machinery
import os
import runpy
import sys
import threading
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT / "scripts"), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lib import broker_read_sync_policy as policy  # noqa: E402

MARK = policy.GUARD_MARK
EXIT_USAGE, EXIT_PRECONDITION, EXIT_GUARD = 64, 65, 66


class BrokerReadSyncRefused(RuntimeError):
    """A step reached something outside the read-only broker plane."""


def _refusal(what: str):
    def _refused(*_a: Any, **_k: Any) -> Any:
        raise BrokerReadSyncRefused(f"{MARK}: {what} is outside the broker-read plane (AGENTS.md 14.0.0 §24.11)")

    _refused.__name__ = "broker_read_refused"
    return _refused


def _apply_stubs(module: Any, names: tuple[str, ...], label: str) -> None:
    for dotted in names:
        owner = module
        *path, attr = dotted.split(".")
        for part in path:
            owner = getattr(owner, part, None)
            if owner is None:
                break
        if owner is None or not hasattr(owner, attr):
            continue  # the static audit pins that every stub target exists in the repo modules
        setattr(owner, attr, _refusal(f"{label}.{dotted}"))


def _rel(origin: Optional[str], root: Path) -> Optional[str]:
    if not origin:
        return None
    try:
        return Path(origin).resolve().relative_to(root).as_posix()
    except (ValueError, OSError):
        return None


class _PatchingLoader(importlib.abc.Loader):
    def __init__(self, inner: Any, names: tuple[str, ...], label: str) -> None:
        self._inner, self._names, self._label = inner, names, label

    def create_module(self, spec):  # noqa: ANN001
        return self._inner.create_module(spec)

    def exec_module(self, module) -> None:  # noqa: ANN001
        self._inner.exec_module(module)
        _apply_stubs(module, self._names, self._label)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class ImportGuard(importlib.abc.MetaPathFinder):
    """Refuses excluded repo modules by file path (every alias) and wraps the stub targets' loaders."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self._busy = threading.local()

    def find_spec(self, fullname, path=None, target=None):  # noqa: ANN001
        if getattr(self._busy, "on", False):
            return None
        self._busy.on = True
        try:
            spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        finally:
            self._busy.on = False
        if spec is None:
            return None
        rel = _rel(spec.origin, self.root)
        if rel is not None:
            fam = policy.runtime_denied(rel)
            if fam:
                raise ImportError(f"{MARK}: import of {rel} refused — excluded family {fam!r} "
                                  f"(AGENTS.md 14.0.0 §24.11)", name=fullname)
            names = policy.RUNTIME_STUBS.get(rel)
        else:
            names = policy.SDK_STUBS.get(fullname) if "." not in fullname else None
        if names and spec.loader is not None:
            spec.loader = _PatchingLoader(spec.loader, names, rel or fullname)
            return spec
        return None


def _check_http(method: Any, url: Any = None, host: Any = None) -> None:
    m = str(method or "GET").upper()
    if m in policy.READ_METHODS:
        return
    h = host
    if h is None and url is not None:
        try:
            h = urlsplit(str(url)).hostname
        except ValueError:
            h = None
    h = str(h or "").strip("[]").lower()
    if h and policy.BROKER_HOST_RE.search(h):
        raise BrokerReadSyncRefused(f"{MARK}: HTTP {m} to broker host {h} refused (read-only plane: GET/HEAD only)")


def install_http_guard() -> list[str]:
    patched: list[str] = []
    try:
        import urllib3.connectionpool as _cp

        _orig = _cp.HTTPConnectionPool.urlopen

        def _urlopen(self, method, url, *a, **k):  # noqa: ANN001
            _check_http(method, url, host=getattr(self, "host", None))
            return _orig(self, method, url, *a, **k)

        _cp.HTTPConnectionPool.urlopen = _urlopen
        patched.append("urllib3")
    except ImportError:
        pass
    try:
        import httpx

        _send = httpx.Client.send
        _asend = httpx.AsyncClient.send

        def _client_send(self, request, *a, **k):  # noqa: ANN001
            _check_http(request.method, str(request.url))
            return _send(self, request, *a, **k)

        async def _async_send(self, request, *a, **k):  # noqa: ANN001
            _check_http(request.method, str(request.url))
            return await _asend(self, request, *a, **k)

        httpx.Client.send = _client_send
        httpx.AsyncClient.send = _async_send
        patched.append("httpx")
    except ImportError:
        pass
    import urllib.request as _ur

    _open = _ur.OpenerDirector.open

    def _opener_open(self, fullurl, data=None, *a, **k):  # noqa: ANN001
        if isinstance(fullurl, _ur.Request):
            _check_http(fullurl.get_method(), fullurl.full_url)
        else:
            _check_http("POST" if data is not None else "GET", fullurl)
        return _open(self, fullurl, data, *a, **k)

    _ur.OpenerDirector.open = _opener_open
    patched.append("urllib.request")
    return patched


def install_subprocess_guard() -> None:
    import subprocess as _sp

    _init = _sp.Popen.__init__

    def _popen_init(self, args, *a, **k):  # noqa: ANN001
        argv = [args] if isinstance(args, (str, bytes, os.PathLike)) else list(args)
        flat = " ".join(os.fsdecode(x) if isinstance(x, (bytes, os.PathLike)) else str(x) for x in argv)
        first = Path(flat.split()[0]).name if flat.split() else ""
        if first.startswith("python") or ".py" in flat.replace(".pyc", ""):
            raise BrokerReadSyncRefused(f"{MARK}: subprocess {first or flat[:40]!r} refused "
                                        "(a child Python would run outside the read-only guards)")
        return _init(self, args, *a, **k)

    _sp.Popen.__init__ = _popen_init


def preconditions() -> list[str]:
    """Refusal reasons evaluated INSIDE the step process, after .env was sourced."""
    out: list[str] = []
    from lib import schwab_access_mode as sam
    from lib import trading_lock as tl

    st = sam.status()
    if st.get("mode") != policy.SCHWAB_MODE:
        out.append(f"schwab_access_mode_not_read_only (mode={st.get('mode')}, source={st.get('source')})")
    for broker in policy.LOCK_BROKERS:
        ls = tl.lock_state(broker=broker)
        if not ls.get("locked", True):
            out.append(f"trading_lock_not_locked ({broker})")
    return out


def main(argv: Optional[list[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    steps = {s.id: s for s in policy.STEPS}
    if len(args) != 2 or args[0] not in steps or args[1] not in ("dry_run", "apply"):
        print(f"{MARK}: usage: broker_read_sync_child.py <step_id> <dry_run|apply> (closed allowlist)",
              file=sys.stderr)
        return EXIT_USAGE
    step, mode = steps[args[0]], args[1]
    step_argv = step.argv(mode)
    if step_argv is None:
        print(f"{MARK}: step {step.id} does not run in {mode}", file=sys.stderr)
        return EXIT_USAGE
    os.environ["TRADEAI_SCHWAB_ACCESS_MODE"] = policy.SCHWAB_MODE
    refused = preconditions()
    if refused:
        print(f"{MARK}: precondition refused in step process: {'; '.join(refused)}", file=sys.stderr)
        return EXIT_PRECONDITION
    sys.meta_path.insert(0, ImportGuard(ROOT))
    for name in ("futu", "moomoo"):  # an SDK imported before the hook would keep its write methods
        mod = sys.modules.get(name)
        if mod is not None:
            _apply_stubs(mod, policy.SDK_STUBS[name], name)
    install_http_guard()
    install_subprocess_guard()
    script = ROOT / step.script
    sys.argv = [str(script), *step_argv]
    sys.path[0] = str(script.parent)  # what `python scripts/x.py` puts first
    try:
        runpy.run_path(str(script), run_name="__main__")
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        return code if isinstance(code, int) else 1
    except BrokerReadSyncRefused as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_GUARD
    except ImportError as exc:
        if MARK in str(exc):
            print(str(exc), file=sys.stderr)
            return EXIT_GUARD
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
