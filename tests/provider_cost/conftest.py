"""Provider-cost tests must not require a live network.

CI previously installed only pytest. Stub ``requests`` if absent so
deepseek_client can be imported; individual tests still mock HTTP.
"""
from __future__ import annotations

import sys
import types

if "requests" not in sys.modules:
    try:
        import requests  # noqa: F401
    except ImportError:
        req = types.ModuleType("requests")

        class _Timeout(Exception):
            pass

        class _RequestException(Exception):
            pass

        req.Timeout = _Timeout
        req.RequestException = _RequestException
        req.post = lambda *a, **k: None
        req.get = lambda *a, **k: None
        sys.modules["requests"] = req
