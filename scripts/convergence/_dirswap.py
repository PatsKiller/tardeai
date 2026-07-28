#!/usr/bin/env python3
"""True atomic directory exchange via renameat2(RENAME_EXCHANGE) — no interval where the live path is
absent. Used by the static install/restore so the "atomic swap" claim is literally true on filesystems
that support the syscall (ext4/xfs/tmpfs/btrfs). Falls back with a distinct exit code so the caller can
degrade to a documented two-rename window rather than silently pretending it was atomic.

CLI:  _dirswap.py exchange <A> <B>
  exit 0  -> A and B were atomically exchanged (A now holds B's old content and vice-versa)
  exit 3  -> RENAME_EXCHANGE unsupported here (ENOSYS/EINVAL/ENOTSUP/EXDEV) — caller must fall back
  exit 2  -> a real error (missing path, permissions, cross-check failed)
"""
from __future__ import annotations

import ctypes
import os
import sys

RENAME_EXCHANGE = 1 << 1  # 2
AT_FDCWD = -100
_FALLBACK_ERRNOS = {getattr(__import__("errno"), n) for n in ("ENOSYS", "EINVAL", "ENOTSUP", "EOPNOTSUPP", "EXDEV") if hasattr(__import__("errno"), n)}


def renameat2_exchange(a: str, b: str) -> None:
    libc = ctypes.CDLL("libc.so.6", use_errno=True)
    libc.renameat2.restype = ctypes.c_int
    libc.renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    res = libc.renameat2(AT_FDCWD, os.fsencode(a), AT_FDCWD, os.fsencode(b), RENAME_EXCHANGE)
    if res != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err))


def main(argv: list[str]) -> int:
    if len(argv) != 4 or argv[1] != "exchange":
        print("usage: _dirswap.py exchange <A> <B>", file=sys.stderr)
        return 2
    a, b = argv[2], argv[3]
    if not os.path.exists(a) or not os.path.exists(b):
        print(f"dirswap|MISSING_PATH|a_exists={os.path.exists(a)}|b_exists={os.path.exists(b)}", file=sys.stderr)
        return 2
    try:
        renameat2_exchange(a, b)
    except OSError as e:
        if e.errno in _FALLBACK_ERRNOS:
            print(f"dirswap|UNSUPPORTED|errno={e.errno}", file=sys.stderr)
            return 3
        print(f"dirswap|ERROR|errno={e.errno}|{e.strerror}", file=sys.stderr)
        return 2
    print("dirswap|EXCHANGED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
