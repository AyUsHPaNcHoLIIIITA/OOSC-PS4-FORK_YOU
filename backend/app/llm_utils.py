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
    """Model id for all LLM calls. Overridable via MODEL_NAME (see README)."""
    return os.environ.get("MODEL_NAME", DEFAULT_MODEL)


def _api_key() -> Optional[str]:
    return os.environ.get("GROQ_API_KEY")


def get_sync_client(timeout: float = 60.0) -> Optional[openai.OpenAI]:
    """Synchronous Groq client, or None when no API key is configured."""
    key = _api_key()
    if not key:
        return None
    return openai.OpenAI(api_key=key, base_url=GROQ_BASE_URL, timeout=timeout)


def get_async_client(timeout: float = 60.0) -> Optional[openai.AsyncOpenAI]:
    """Asynchronous Groq client, or None when no API key is configured."""
    key = _api_key()
    if not key:
        return None
    return openai.AsyncOpenAI(api_key=key, base_url=GROQ_BASE_URL, timeout=timeout)


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
