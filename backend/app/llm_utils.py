"""Shared LLM plumbing for the scenario_gen / classifier stages.

Centralizes what analyzer.py, generator.py and judge.py each used to duplicate:
building the Groq-pointed OpenAI client, resolving the model name (via the
MODEL_NAME env var the README documents), and robustly parsing a JSON response
that may be wrapped in markdown fences or padded with stray prose.
"""
import os
import json
from typing import Any, Dict, Optional

import openai

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "openai/gpt-oss-20b"


def get_model_name() -> str:
    """Model id for all LLM calls. Overridable via MODEL_NAME (or LLM_MODEL)."""
    return os.environ.get("MODEL_NAME") or os.environ.get("LLM_MODEL") or DEFAULT_MODEL


def _api_key() -> Optional[str]:
    """Resolve the inference API key. LLM_API_KEY (any OpenAI-compatible gateway)
    takes precedence over the Groq default, so the whole backend can be pointed at
    a corporate/custom gateway with env vars alone — no code change. For gateways
    that authenticate via a header instead of a bearer key, set LLM_API_KEY to any
    non-empty placeholder and put the real auth in LLM_EXTRA_HEADERS."""
    return os.environ.get("LLM_API_KEY") or os.environ.get("GROQ_API_KEY")


def get_base_url() -> str:
    """Base URL of the OpenAI-compatible endpoint. Defaults to Groq; override with
    LLM_BASE_URL (or OPENAI_BASE_URL) to route through any OpenAI-compatible
    gateway. Must be the API root that serves /chat/completions."""
    return (
        os.environ.get("LLM_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or GROQ_BASE_URL
    ).rstrip("/")


def _extra_headers() -> Optional[Dict[str, str]]:
    """Optional custom request headers for gateways that need them (tenant/project
    id, non-standard auth). Set LLM_EXTRA_HEADERS to a JSON object of string pairs.
    Malformed JSON is logged and ignored rather than crashing client construction."""
    raw = os.environ.get("LLM_EXTRA_HEADERS")
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        print("WARNING: LLM_EXTRA_HEADERS is not valid JSON; ignoring it.")
        return None
    if isinstance(parsed, dict) and parsed:
        return {str(k): str(v) for k, v in parsed.items()}
    return None


def is_llm_configured() -> bool:
    """True when a real LLM is available. When False the harness can only
    fabricate placeholder traces, so nothing should be certified — callers must
    report NOT EVALUATED rather than a green result."""
    return bool(_api_key())


def get_sync_client(timeout: float = 60.0) -> Optional[openai.OpenAI]:
    """Synchronous OpenAI-compatible client (Groq by default; overridable via
    LLM_BASE_URL/LLM_API_KEY), or None when no API key is configured."""
    key = _api_key()
    if not key:
        return None
    return openai.OpenAI(
        api_key=key,
        base_url=get_base_url(),
        timeout=timeout,
        default_headers=_extra_headers(),
    )


def get_async_client(timeout: float = 60.0) -> Optional[openai.AsyncOpenAI]:
    """Asynchronous OpenAI-compatible client (Groq by default; overridable via
    LLM_BASE_URL/LLM_API_KEY), or None when no API key is configured."""
    key = _api_key()
    if not key:
        return None
    return openai.AsyncOpenAI(
        api_key=key,
        base_url=get_base_url(),
        timeout=timeout,
        default_headers=_extra_headers(),
    )


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
