"""Tiny client helper for loopback callers of the Command Center (127.0.0.1:7777).

Adds the per-host service token header (config/cc_auth.yaml ``service_token``) to requests whose URL
targets the CC service listener on loopback, and ONLY those — the token is never attached to any other
host or port. A missing token file is not an error here: the request goes out without the header and
the server decides (report_only logs it; enforce answers 401).

    from lib.cc_client import cc_urlopen, cc_headers
    with cc_urlopen("http://127.0.0.1:7777/api/v2/risk", timeout=30) as r: ...
    requests.get(url, headers=cc_headers(url), timeout=10)

Shell callers use scripts/cc_curl.sh (same rule, header via process substitution so the token never
appears in argv).
"""
from __future__ import annotations

import urllib.request
from typing import Any
from urllib.parse import urlparse

try:  # imported as lib.cc_client / scripts.lib.cc_client
    from .cc_auth import LOOPBACK_HOSTS, load_config, read_service_token
except ImportError:  # pragma: no cover - imported with scripts/lib itself on sys.path
    from cc_auth import LOOPBACK_HOSTS, load_config, read_service_token  # type: ignore

_UNSET = object()


def _targets_cc(url: str, port: int) -> bool:
    try:
        u = urlparse(url)
    except Exception:
        return False
    if u.scheme != "http" or (u.hostname or "") not in LOOPBACK_HOSTS:
        return False
    return (u.port or 80) == port


def cc_headers(url: str, headers: dict | None = None) -> dict:
    """Return ``headers`` plus the service-token header when ``url`` is the loopback CC listener."""
    out = dict(headers or {})
    cfg = load_config()
    if not _targets_cc(url, cfg.service_port):
        return out
    token = read_service_token(cfg)
    if token:
        out[cfg.token_header] = token
    return out


def cc_request(url: str, data: bytes | None = None, headers: dict | None = None,
               method: str | None = None) -> urllib.request.Request:
    return urllib.request.Request(url, data=data, headers=cc_headers(url, headers), method=method)


def cc_urlopen(url_or_request: Any, data: bytes | None = None, timeout: Any = _UNSET, **kwargs: Any):
    """Drop-in for ``urllib.request.urlopen`` that authenticates loopback CC calls.

    When no header is needed (other host/port, or no token file) the original argument is passed
    through untouched, so behaviour — and any test double on ``urllib.request.urlopen`` — is unchanged.
    """
    is_req = isinstance(url_or_request, urllib.request.Request)
    url = url_or_request.full_url if is_req else str(url_or_request)
    extra = cc_headers(url)
    target = url_or_request
    if extra:
        if is_req:
            for k, v in extra.items():
                if not url_or_request.has_header(k.capitalize()):
                    url_or_request.add_header(k, v)
        else:
            target = urllib.request.Request(url, headers=extra)
    if data is not None:
        kwargs["data"] = data
    if timeout is not _UNSET:
        kwargs["timeout"] = timeout
    return urllib.request.urlopen(target, **kwargs)
