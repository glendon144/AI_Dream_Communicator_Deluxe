"""
ai_interface.py — Baseten (OpenAI-compatible) client
Release: v1.31

Usage:
  from modules.ai_interface import chat_once, stream_chat, quick_ask

  # Non-stream (returns full string)
  text = chat_once(
      messages=[{"role": "user", "content": "Say hi"}],
      model=None,            # optional override
      temperature=0.7,
      max_tokens=800
  )

  # Streaming (yield chunks)
  for chunk in stream_chat(
      messages=[{"role": "user", "content": "Stream me a haiku"}],
      model=None,
      temperature=0.8,
  ):
      print(chunk, end="", flush=True)

Environment:
  BASETEN_API_KEY    (required)  — your Baseten key
  BASETEN_BASE_URL   (optional)  — default "https://inference.baseten.co/v1"
  BASETEN_MODEL      (optional)  — default "openai/gpt-oss-120b"
  OPENAI_API_TIMEOUT (optional)  — seconds (float/int), default 60
"""

from __future__ import annotations

import os
import time
from typing import Generator, Iterable, List, Optional

# Requires openai>=1.0.0
# pip install --upgrade openai
from openai import OpenAI
from openai._exceptions import APIError, RateLimitError, APITimeoutError, APIConnectionError

# --------------------------
# Configuration / Defaults
# --------------------------
_DEFAULT_BASE_URL = os.getenv("BASETEN_BASE_URL", "https://inference.baseten.co/v1")
_DEFAULT_MODEL    = os.getenv("BASETEN_MODEL", "openai/gpt-oss-120b")

_API_KEY = os.getenv("BASETEN_API_KEY")
_TIMEOUT = float(os.getenv("OPENAI_API_TIMEOUT", "60"))

_client = OpenAI(
    api_key=_API_KEY or "MISSING_BASeTEN_API_KEY",
    base_url=_DEFAULT_BASE_URL,
    timeout=_TIMEOUT,
)

# --------------------------
# Core helpers
# --------------------------

def _retryable(func, /, *, retries: int = 2, backoff: float = 0.8):
    """
    Lightweight retry wrapper for transient network / rate limit issues.
    """
    def _wrapped(*args, **kwargs):
        delay = backoff
        last_err = None
        for attempt in range(retries + 1):
            try:
                return func(*args, **kwargs)
            except (RateLimitError, APITimeoutError, APIConnectionError, APIError) as e:
                last_err = e
                if attempt >= retries:
                    break
                time.sleep(delay)
                delay *= 2
        raise last_err
    return _wrapped


@_retryable
def chat_once(
    *,
    messages: List[dict],
    model: Optional[str] = None,
    temperature: float = 1.0,
    top_p: float = 1.0,
    max_tokens: int = 1000,
    presence_penalty: float = 0.0,
    frequency_penalty: float = 0.0,
    stop: Optional[Iterable[str]] = None,
    extra: Optional[dict] = None,
) -> str:
    """
    Non-streaming completion. Returns the assistant's full text.
    """
    if not _API_KEY:
        raise RuntimeError("BASETEN_API_KEY not set in environment")

    kwargs = dict(
        model=model or _DEFAULT_MODEL,
        messages=messages,
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        presence_penalty=presence_penalty,
        frequency_penalty=frequency_penalty,
    )
    if stop:
        kwargs["stop"] = list(stop)
    if extra:
        kwargs.update(extra)

    resp = _client.chat.completions.create(**kwargs)
    # OpenAI-compatible response shape
    if not resp.choices:
        return ""
    text = resp.choices[0].message.content or ""
    return text


def stream_chat(
    *,
    messages: List[dict],
    model: Optional[str] = None,
    temperature: float = 1.0,
    top_p: float = 1.0,
    max_tokens: int = 1000,
    presence_penalty: float = 0.0,
    frequency_penalty: float = 0.0,
    stop: Optional[Iterable[str]] = None,
    include_usage: bool = True,
    continuous_usage_stats: bool = True,
    extra: Optional[dict] = None,
) -> Generator[str, None, None]:
    """
    Streaming completion. Yields text deltas (str) as they arrive.
    """
    if not _API_KEY:
        raise RuntimeError("BASETEN_API_KEY not set in environment")

    kwargs = dict(
        model=model or _DEFAULT_MODEL,
        messages=messages,
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        presence_penalty=presence_penalty,
        frequency_penalty=frequency_penalty,
        stream=True,
        stream_options={
            "include_usage": include_usage,
            "continuous_usage_stats": continuous_usage_stats,
        },
    )
    if stop:
        kwargs["stop"] = list(stop)
    if extra:
        kwargs.update(extra)

    # minimal retry loop around the stream opener
    opener = _retryable(_client.chat.completions.create)
    response = opener(**kwargs)

    for chunk in response:
        try:
            if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
        except Exception:
            # ignore malformed chunks but keep the stream alive
            continue


# --------------------------
# Convenience wrappers
# --------------------------

def quick_ask(
    prompt: str,
    *,
    system: Optional[str] = None,
    model: Optional[str] = None,
    stream: bool = False,
    **kw,
):
    """
    Quick one-off ask that builds messages array for you.

    Returns:
      - str if stream=False
      - generator[str] if stream=True
    """
    messages: List[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    if stream:
        return stream_chat(messages=messages, model=model, **kw)
    return chat_once(messages=messages, model=model, **kw)


# --------------------------
# Backwards-compat helpers for your CommandProcessor
# --------------------------

def run_chat_for_processor(
    selected_text: str,
    *,
    prefix: str = "",
    system: Optional[str] = None,
    model: Optional[str] = None,
    stream: bool = False,
    **kw,
) -> str | Generator[str, None, None]:
    """
    Typical call from CommandProcessor.query_ai:
      result = run_chat_for_processor(sel, prefix="Please expand: ")
    """
    user = (prefix or "") + selected_text
    return quick_ask(user, system=system, model=model, stream=stream, **kw)

