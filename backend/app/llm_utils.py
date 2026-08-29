"""Shared LLM plumbing for the scenario_gen / classifier stages.

Centralizes what analyzer.py, generator.py and judge.py each used to duplicate:
building the Groq-pointed OpenAI client, resolving the model name (via the
MODEL_NAME env var the README documents), and robustly parsing a JSON response
that may be wrapped in markdown fences or padded with stray prose.
"""
import os
import json
import socket
import asyncio
import ipaddress
import importlib
from urllib.parse import urlparse
from typing import Any, Dict, List, Optional

import openai


def _resolve_httpx():
    """Return the exact httpx module the installed openai SDK is built against.

    Some openai builds vendor httpx under a non-standard name (this environment
    ships it as ``httpx2``). The ``http_client`` we hand to ``AsyncOpenAI`` must be
    an instance of the SDK's own ``httpx.AsyncClient``, and our SSRF transport must
    subclass the SDK's ``AsyncHTTPTransport`` — so we bind to whichever module the
    SDK actually uses instead of hardcoding the import name.
    """
    try:
        base = openai.DefaultAsyncHttpxClient.__mro__[1]  # the SDK's httpx.AsyncClient
        return importlib.import_module(base.__module__.split(".")[0])
    except Exception:  # pragma: no cover - fall back to the standard package name
        import httpx as _hx  # type: ignore
        return _hx


httpx = _resolve_httpx()

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "openai/gpt-oss-20b"


def get_model_name() -> str:
    """Model id for all LLM calls. Overridable via MODEL_NAME (see README)."""
    return os.environ.get("MODEL_NAME", DEFAULT_MODEL)


def _base_url() -> str:
    """Base URL for the backend evaluator LLM (generator / analyzer / judge).

    Defaults to Groq. Override with LLM_BASE_URL to point the evaluator at any
    other OpenAI-compatible gateway (e.g. when the Groq quota is exhausted). The
    OpenAI SDK appends ``/chat/completions`` to this, so include the API path the
    gateway expects (commonly a trailing ``/v1``). Only the base endpoint changes;
    the evaluator still runs on the backend's own credentials, independent of any
    user-supplied model-under-test.
    """
    return os.environ.get("LLM_BASE_URL", GROQ_BASE_URL).strip().rstrip("/")


def _api_key() -> Optional[str]:
    return os.environ.get("LLM_API_KEY") or os.environ.get("GROQ_API_KEY")


def is_llm_configured() -> bool:
    """True when a real LLM is available. When False the harness can only
    fabricate placeholder traces, so nothing should be certified — callers must
    report NOT EVALUATED rather than a green result."""
    return bool(_api_key())


def get_sync_client(timeout: float = 60.0) -> Optional[openai.OpenAI]:
    """Synchronous evaluator client, or None when no API key is configured."""
    key = _api_key()
    if not key:
        return None
    return openai.OpenAI(api_key=key, base_url=_base_url(), timeout=timeout)


def get_async_client(timeout: float = 60.0) -> Optional[openai.AsyncOpenAI]:
    """Asynchronous evaluator client, or None when no API key is configured."""
    key = _api_key()
    if not key:
        return None
    return openai.AsyncOpenAI(api_key=key, base_url=_base_url(), timeout=timeout)


def _strip_fences(content: str) -> str:
    text = content.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def parse_json_response(content: Optional[str]) -> Dict[str, Any]:
    """Parse a model JSON response defensively.

    Handles None, markdown code fences, and leading/trailing prose by falling
    back to the outermost ``{ ... }`` slice. Raises ValueError if nothing
    parseable is found so callers can decide how to degrade.
    """
    if not content:
        raise ValueError("Empty LLM response content")

    text = _strip_fences(content)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Fallback: slice the outermost object in case the model added prose.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError("Could not parse JSON from LLM response")


# ---------------------------------------------------------------------------
# Model-under-test plumbing (user-supplied endpoints)
# ---------------------------------------------------------------------------
# The evaluator stages above (generator / analyzer / judge) ALWAYS use the
# backend's own Groq credentials, so scenario generation and judging stay on our
# trusted model. Only the agent-under-test runner may be pointed at a
# user-supplied model, validated and constructed here. Supplied API keys are used
# per request and are NEVER persisted to the database or written to logs.


class ModelConfigError(ValueError):
    """A user-supplied model-under-test config is invalid or unsafe (bad key,
    missing field, or an SSRF-prone base URL)."""


def mask_key(key: Optional[str]) -> str:
    """Redact an API key for display/logging: keep only the first and last few
    chars. Never returns the full secret."""
    if not key:
        return ""
    k = str(key)
    return "****" if len(k) <= 8 else f"{k[:4]}…{k[-4:]}"


def safe_error(exc: Exception, *secrets: Optional[str]) -> str:
    """Stringify an exception with any secret values masked, so an upstream error
    can never leak a user's API key into a log line or HTTP response body."""
    msg = str(exc)
    for s in secrets:
        if s and len(str(s)) >= 4:
            msg = msg.replace(str(s), mask_key(s))
    return msg


def _require_https_default() -> bool:
    """HTTPS is required for user-supplied endpoints in production; in dev we
    allow http:// so a local gateway can be pointed at during development."""
    return os.environ.get("APP_ENV", "development").strip().lower() in ("production", "prod")


_BLOCKED_HOSTNAMES = {"metadata.google.internal", "metadata.goog"}


def _ip_is_internal(ip: "ipaddress._BaseAddress") -> bool:
    return bool(ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified)


def _assert_addrinfos_safe(infos, host: str) -> None:
    """Reject if ANY resolved address for `host` is internal (SSRF guard)."""
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if _ip_is_internal(ip):
            raise ModelConfigError(
                "Base URL resolves to a private/internal address, which is not allowed."
            )


def assert_safe_base_url(base_url: str, *, require_https: Optional[bool] = None) -> str:
    """Validate a *user-supplied* base URL before making outbound calls to it.

    Blocks SSRF into private / loopback / link-local / reserved ranges (including
    the cloud metadata endpoint 169.254.169.254) by resolving the host and
    rejecting if ANY resolved address is internal. Enforces https in production.
    Returns the normalized URL, or raises ModelConfigError.

    NOTE: this is the pre-flight check. It cannot pin the IP, so the outbound
    client re-validates each connection at connect time (see
    ``_SSRFGuardTransport``) to close the DNS-rebinding / redirect windows.
    """
    if require_https is None:
        require_https = _require_https_default()
    if not base_url or not isinstance(base_url, str) or not base_url.strip():
        raise ModelConfigError("A base URL is required for a custom model provider.")
    url = base_url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ModelConfigError("Base URL must start with http:// or https://")
    if require_https and parsed.scheme != "https":
        raise ModelConfigError("Base URL must use https://")
    host = parsed.hostname
    if not host:
        raise ModelConfigError("Base URL has no host.")
    if host.lower() in _BLOCKED_HOSTNAMES:
        raise ModelConfigError("That host is not allowed.")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise ModelConfigError(f"Could not resolve host '{host}'.")
    _assert_addrinfos_safe(infos, host)
    return url


class _SSRFGuardTransport(httpx.AsyncHTTPTransport):
    """httpx transport that re-validates the destination host on EVERY outbound
    connection, closing the gap the one-time pre-flight ``assert_safe_base_url``
    check leaves open:

    * DNS rebinding / TOCTOU — the host is re-resolved and every resolved IP is
      re-checked against the private/internal blocklist right before the request,
      so a short-TTL record that flipped to an internal address after validation
      is rejected here.
    * Metadata hostnames — the explicit blocklist is re-applied.

    Combined with ``follow_redirects=False`` on the owning client (so a 3xx to an
    internal address is surfaced as an error rather than silently followed), this
    hardens the user-supplied-endpoint path against SSRF. A vanishingly small
    resolve-then-connect window remains (the OS resolver re-queries inside
    httpcore); OS/stub DNS caching within the record TTL makes it impractical to
    exploit, and full IP-pinning would require live-endpoint TLS testing.
    """

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host and host.lower() in _BLOCKED_HOSTNAMES:
            raise ModelConfigError("That host is not allowed.")
        if host:
            port = request.url.port or (443 if request.url.scheme == "https" else 80)
            try:
                loop = asyncio.get_running_loop()
                infos = await loop.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
            except socket.gaierror:
                raise ModelConfigError(f"Could not resolve host '{host}'.")
            _assert_addrinfos_safe(infos, host)
        return await super().handle_async_request(request)


def build_async_client(base_url: str, api_key: str,
                       extra_headers: Optional[Dict[str, str]] = None,
                       timeout: float = 60.0) -> openai.AsyncOpenAI:
    """Async OpenAI-compatible client for a *validated* model-under-test endpoint.

    Callers MUST have already run any user-supplied base_url through
    ``assert_safe_base_url`` (see routers.resolve_model_cfg). Outbound requests go
    through a redirect-disabled client backed by ``_SSRFGuardTransport``, which
    re-checks the resolved IPs on each connection so a redirect or DNS rebind
    cannot steer the call into internal space after validation. Requires an API
    key. The key is used only for this client's requests and is never logged or
    persisted.
    """
    if not api_key or not str(api_key).strip():
        raise ModelConfigError("An API key is required for the model under test.")
    http_client = httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        transport=_SSRFGuardTransport(),
    )
    kwargs: Dict[str, Any] = {
        "api_key": api_key,
        "base_url": base_url,
        "timeout": timeout,
        "http_client": http_client,
    }
    if extra_headers:
        kwargs["default_headers"] = extra_headers
    return openai.AsyncOpenAI(**kwargs)
