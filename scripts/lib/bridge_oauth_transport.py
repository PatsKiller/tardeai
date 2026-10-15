"""OAuth-lane transports for the governed bridge (Grok xai-oauth :8645, ChatGPT openai-codex :8646).

The routing policy puts Grok OAuth first and ChatGPT OAuth second for the n8n_* rows (AGENTS.md §23.4 decision
2), but until 2026-10-14 the bridge's only live transport was DeepSeek (`RealProvider`), so every such call
walked straight to the fallback. This module is the missing adapter: it speaks to the two local OAuth proxies
already on the host (`scripts/grok_oauth_proxy.py`, `scripts/chatgpt_oauth_proxy.py`), the same endpoints
`lib.oauth_lane_status` probes. It holds no credential: Hermes owns the OAuth sessions behind the proxies.

Also here, with no bridge import so it can be tested alone:
  * `TransportError` - a typed transport failure (`auth_failure` is distinct from a serving failure);
  * `parse_retry_after` - seconds or an HTTP-date;
  * `ProviderCircuits` - a per-provider breaker plus the Retry-After hold.

Off by default. `CIO_BRIDGE_OAUTH_TRANSPORTS` (comma list of `grok`, `chatgpt`) enables a transport; empty or
unset keeps the bridge's DeepSeek-only behaviour byte-for-byte.
"""

from __future__ import annotations

import email.utils
import json
import os
import threading
import time
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

#: Env that enables OAuth transports in the bridge (comma list). Unset -> none.
ENABLE_ENV = "CIO_BRIDGE_OAUTH_TRANSPORTS"
OAUTH_PROVIDERS = ("grok", "chatgpt")

#: Proxy URL env names - the same names lib.oauth_lane_status reads, so one drop-in moves both.
URL_ENV = {"grok": "HERMES_XAI_PROXY_URL", "chatgpt": "CHATGPT_PROXY_URL"}
_URL_DEFAULT = {"grok": "http://127.0.0.1:8645/v1/chat/completions", "chatgpt": "http://127.0.0.1:8646"}
#: Optional model pin per lane. Unset -> the request names no model and the proxy serves its own default
#: (grok-oauth-proxy GROK_PROXY_MODEL; chatgpt-oauth-proxy CHATGPT_PROXY_MODEL, gpt-6.1-sol since drop-in
#: 50-model-20261014). Set -> the reply must name that model or the attempt is a serving failure.
MODEL_ENV = {"grok": "CIO_BRIDGE_GROK_MODEL", "chatgpt": "CIO_BRIDGE_CHATGPT_MODEL"}
CONNECT_TIMEOUT_S = float(os.environ.get("CIO_BRIDGE_OAUTH_CONNECT_TIMEOUT_S", "5"))
_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})

OUTCOMES = frozenset(
    {
        "ok",
        "auth_failure",
        "rate_limited",
        "serving_failure",
        "timeout",
        "invalid_response",
        "model_mismatch",
        # skipped before any request:
        "no_transport",
        "lane_unhealthy",
        "policy_not_allowed",
        "registry_lane_not_allowed",
        "tools_unsupported",
        "circuit_open",
        "retry_after_pending",
        "deadline_exhausted",
        "paid_after_billable_attempt",
    }
)


class TransportError(RuntimeError):
    """One failed attempt. `kind` is a receipt outcome; auth is never folded into a serving failure."""

    def __init__(
        self,
        kind: str,
        message: str,
        *,
        http_status: int | None = None,
        retry_after_s: float | None = None,
        request_sent: bool = True,
        possibly_billable: bool = False,
    ) -> None:
        assert kind in OUTCOMES, kind
        super().__init__(message)
        self.kind = kind
        self.http_status = http_status
        self.retry_after_s = retry_after_s
        self.request_sent = request_sent
        self.possibly_billable = possibly_billable


def enabled_oauth_providers(env: Mapping[str, str] | None = None) -> frozenset[str]:
    raw = (os.environ if env is None else env).get(ENABLE_ENV) or ""
    return frozenset(p.strip().lower() for p in raw.split(",") if p.strip().lower() in OAUTH_PROVIDERS)


def proxy_url(provider: str, env: Mapping[str, str] | None = None) -> str:
    """The chat-completions URL for a lane. Loopback only: anything else raises (no remote egress here)."""
    e = os.environ if env is None else env
    raw = (e.get(URL_ENV[provider]) or _URL_DEFAULT[provider]).strip().rstrip("/")
    if not raw.endswith("/v1/chat/completions"):
        raw = raw + "/v1/chat/completions"
    host = urlparse(raw).hostname or ""
    if host not in _LOOPBACK:
        raise ValueError(f"{URL_ENV[provider]} must point at a loopback proxy, got host {host!r}")
    return raw


def pinned_model(provider: str, env: Mapping[str, str] | None = None) -> str | None:
    value = ((os.environ if env is None else env).get(MODEL_ENV[provider]) or "").strip()
    return value or None


def parse_retry_after(value: Any, *, now: float | None = None) -> float | None:
    """Retry-After as seconds (>= 0), from delta-seconds or an HTTP-date. Unparseable -> None."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return max(0.0, float(text))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    return max(0.0, when.timestamp() - (time.time() if now is None else now))


class ProviderCircuits:
    """Per-provider breaker. A provider opens after `threshold` consecutive failures (an auth failure opens it at
    once: it does not heal by retrying) for `cooldown_s`; a 429 holds it until its Retry-After. Thread-safe."""

    def __init__(
        self,
        threshold: int | None = None,
        cooldown_s: float | None = None,
        default_retry_after_s: float | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.threshold = int(
            threshold if threshold is not None else os.environ.get("CIO_BRIDGE_PROVIDER_CIRCUIT_ERRORS", "3")
        )
        self.cooldown_s = float(
            cooldown_s if cooldown_s is not None else os.environ.get("CIO_BRIDGE_PROVIDER_CIRCUIT_COOLDOWN_SEC", "300")
        )
        self.default_retry_after_s = float(
            default_retry_after_s
            if default_retry_after_s is not None
            else os.environ.get("CIO_BRIDGE_DEFAULT_RETRY_AFTER_S", "60")
        )
        self.clock = clock
        self._lock = threading.Lock()
        self._state: dict[str, dict[str, Any]] = {}

    def reset(self) -> None:
        with self._lock:
            self._state.clear()

    def _row(self, provider: str) -> dict[str, Any]:
        return self._state.setdefault(
            provider, {"errors": 0, "open_until": 0.0, "retry_after_until": 0.0, "last_outcome": None}
        )

    def blocked(self, provider: str) -> tuple[str, float] | None:
        """('circuit_open' | 'retry_after_pending', seconds left) or None when the provider may be tried."""
        now = self.clock()
        with self._lock:
            row = self._row(provider)
            if now < float(row["retry_after_until"]):
                return "retry_after_pending", float(row["retry_after_until"]) - now
            if now < float(row["open_until"]):
                return "circuit_open", float(row["open_until"]) - now
        return None

    def success(self, provider: str) -> None:
        with self._lock:
            row = self._row(provider)
            row.update(errors=0, open_until=0.0, last_outcome="ok")

    def failure(self, provider: str, kind: str, retry_after_s: float | None = None) -> None:
        now = self.clock()
        with self._lock:
            row = self._row(provider)
            row["last_outcome"] = kind
            if kind == "rate_limited":
                wait = self.default_retry_after_s if retry_after_s is None else float(retry_after_s)
                row["retry_after_until"] = max(float(row["retry_after_until"]), now + wait)
                return
            row["errors"] = int(row["errors"]) + 1
            if kind == "auth_failure" or int(row["errors"]) >= self.threshold:
                row["open_until"] = now + self.cooldown_s

    def snapshot(self) -> dict[str, dict[str, Any]]:
        now = self.clock()
        with self._lock:
            return {
                p: {
                    "errors": int(r["errors"]),
                    "open": now < float(r["open_until"]),
                    "retry_after_s": round(max(0.0, float(r["retry_after_until"]) - now), 1),
                    "last_outcome": r["last_outcome"],
                }
                for p, r in self._state.items()
            }


def is_mid_body_read_timeout(exc: BaseException) -> bool:
    """True for a socket read timeout raised while the body is being read.

    requests re-raises urllib3's ReadTimeoutError from inside `iter_content` as `requests.ConnectionError`
    (requests 2.33.1 models.py:827-828), not as `requests.Timeout`, so a class check alone files a read
    timeout as a network error. Walks args and the exception chain; matches by name so urllib3 need not load.
    """
    seen: set[int] = set()
    stack: list[Any] = [exc]
    while stack:
        cur = stack.pop()
        if not isinstance(cur, BaseException) or id(cur) in seen:
            continue
        seen.add(id(cur))
        if type(cur).__name__ in ("ReadTimeoutError", "ReadTimeout"):
            return True
        stack.extend(a for a in getattr(cur, "args", ()) if isinstance(a, BaseException))
        stack.extend((cur.__cause__, cur.__context__))
    return False


def read_with_hard_deadline(
    resp: Any,
    started: float,
    deadline_s: float,
    clock: Callable[[], float],
    expired: Callable[[int], BaseException],
    read_timeout: Callable[[int], BaseException] | None = None,
) -> bytes:
    """Read a streamed body, returning or raising by `started + deadline_s` whether or not bytes arrive.

    2026-10-15: the deadline was checked only when `iter_content` yielded a chunk, so a provider that sent one
    keep-alive byte per read timeout overran a 150 s budget to 180 s (3 bytes received), and a silent one was
    bounded only by the per-read socket timeout. The read now runs on a daemon thread and the caller joins it
    until the deadline. On expiry the response is closed and the caller raises at once; the reader exits at its
    next chunk or socket read timeout and holds no slot or semaphore, only `resp` and its own buffer.
    `expired(n)` / `read_timeout(n)` build the exception for n bytes received; a mid-body read timeout uses
    `read_timeout` (default: `expired`).
    """
    limit = float(deadline_s)
    buf = bytearray()
    stop = threading.Event()
    outcome: list[BaseException] = []
    on_read_timeout = read_timeout or expired

    def _pump() -> None:
        try:
            for chunk in resp.iter_content(chunk_size=8192):
                if stop.is_set():
                    return
                if chunk:
                    buf.extend(chunk)
                if clock() - started > limit:
                    outcome.append(expired(len(buf)))
                    return
        except BaseException as exc:  # noqa: BLE001 -- handed to the caller's thread
            if stop.is_set():
                return  # the caller already gave up and closed the response under us
            outcome.append(on_read_timeout(len(buf)) if is_mid_body_read_timeout(exc) else exc)

    remaining = max(0.0, limit - (clock() - started))
    reader = threading.Thread(target=_pump, name="bridge-upstream-read", daemon=True)
    try:
        reader.start()
        reader.join(remaining)
        if reader.is_alive():
            stop.set()
            raise expired(len(buf))
        if outcome:
            raise outcome[0]
    finally:
        try:
            resp.close()
        except (OSError, RuntimeError, AttributeError):
            pass
    return bytes(buf)


def _read_with_deadline(resp: Any, started: float, deadline_s: float, clock: Callable[[], float]) -> bytes:
    return read_with_hard_deadline(
        resp,
        started,
        deadline_s,
        clock,
        lambda n: TransportError("timeout", f"proxy kept the request open past {deadline_s:g}s ({n} bytes received)"),
        lambda n: TransportError("timeout", f"proxy read timed out mid-body ({n} bytes received)"),
    )


class OAuthProxyTransport:
    """OpenAI-shaped `generate()` over one local OAuth proxy. `http_post` is injectable (tests mock the HTTP
    layer, never a live proxy). Returns a chat.completion dict; raises TransportError on any failure."""

    _instances: dict[str, "OAuthProxyTransport"] = {}

    def __init__(
        self,
        provider: str,
        *,
        http_post: Callable[..., Any] | None = None,
        env: Mapping[str, str] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if provider not in OAUTH_PROVIDERS:
            raise ValueError(f"not an OAuth lane: {provider!r}")
        self.provider = provider
        self._http_post = http_post
        self._env = env
        self._clock = clock
        self.call_count = 0

    @classmethod
    def for_provider(cls, provider: str) -> "OAuthProxyTransport":
        inst = cls._instances.get(provider)
        if inst is None:
            inst = cls(provider)
            cls._instances[provider] = inst
        return inst

    def _post(self, url: str, **kwargs: Any) -> Any:
        if self._http_post is not None:
            return self._http_post(url, **kwargs)
        import requests

        return requests.post(url, **kwargs)

    def generate(
        self,
        messages: list[dict],
        model_id: str | None = None,
        *,
        tools: list[dict] | None = None,
        max_tokens: int = 2048,
        deadline_s: float = 150.0,
        client_request_id: str | None = None,
        **_ignored: Any,
    ) -> dict[str, Any]:
        if tools:
            raise TransportError("tools_unsupported", "OAuth proxies do not carry tools", request_sent=False)
        self.call_count += 1
        try:
            url = proxy_url(self.provider, self._env)
        except ValueError as exc:
            raise TransportError("serving_failure", str(exc), request_sent=False) from exc
        want = model_id or pinned_model(self.provider, self._env)
        body: dict[str, Any] = {"messages": messages, "stream": False, "max_tokens": int(max_tokens)}
        if want:
            body["model"] = want
        headers = {"Content-Type": "application/json", "User-Agent": "tradeai-cio-bridge/oauth"}
        if client_request_id:
            headers["X-TradeAI-Request-Id"] = client_request_id
        t0 = self._clock()
        try:
            resp = self._post(
                url,
                json=body,
                headers=headers,
                stream=True,
                timeout=(min(CONNECT_TIMEOUT_S, deadline_s), max(0.1, deadline_s)),
            )
        except TransportError:
            raise
        except Exception as exc:  # noqa: BLE001 -- requests.* and socket errors alike
            name = type(exc).__name__
            if "Timeout" in name:
                raise TransportError("timeout", f"{self.provider} proxy timeout: {name}") from exc
            # Connection refused: the request never reached the proxy.
            raise TransportError(
                "serving_failure", f"{self.provider} proxy unreachable: {name}", request_sent="Connect" not in name
            ) from exc
        status = int(getattr(resp, "status_code", 0) or 0)
        raw = _read_with_deadline(resp, t0, deadline_s, self._clock)
        if status in (401, 403):
            raise TransportError(
                "auth_failure", f"{self.provider} OAuth session refused (HTTP {status})", http_status=status
            )
        if status == 429:
            hdrs = getattr(resp, "headers", None) or {}
            ra = parse_retry_after(hdrs.get("retry-after") or hdrs.get("Retry-After"))
            raise TransportError(
                "rate_limited", f"{self.provider} rate limited (HTTP 429)", http_status=429, retry_after_s=ra
            )
        if status != 200:
            raise TransportError("serving_failure", f"{self.provider} proxy HTTP {status}", http_status=status)
        try:
            payload = json.loads(raw)
            content = payload["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise TransportError(
                "invalid_response", f"{self.provider} proxy returned no message", http_status=200
            ) from exc
        if not isinstance(content, str) or not content.strip():
            raise TransportError("invalid_response", f"{self.provider} proxy returned empty content", http_status=200)
        returned = str(payload.get("model") or "")
        pinned = pinned_model(self.provider, self._env)
        if pinned and returned and returned != pinned:
            raise TransportError(
                "model_mismatch", f"{self.provider} requested {pinned}, served {returned}", http_status=200
            )
        return {
            "id": client_request_id or str(payload.get("id") or ""),
            "object": "chat.completion",
            "created": int(payload.get("created") or time.time()),
            "model": returned or (want or f"{self.provider}-oauth-default"),
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": payload.get("usage") or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "_tradeai": {
                "real": True,
                "provider": self.provider,
                "billing": "free_oauth",
                "latency_ms": int((self._clock() - t0) * 1000),
            },
        }
