#!/usr/bin/env python3
"""
ai_interface.py — Friendly OpenAI-compatible adapter for PiKit (LocalAI / vLLM / OpenAI)
========================================================================================

What's new vs. the previous version:
- Robust HTTP retries with exponential backoff for 429/5xx
- Friendly errors (short, user-facing) + verbose (debug) option
- Health checks: .ping() and .whoami() (reports server + model details)
- Model discovery: .list_models() (works with OpenAI/LocalAI/vLLM)
- Safer streaming: .stream_text() (yields tokens) and .stream_json() (raw SSE)
- Timeouts per-call override; sensible defaults from env
- Extra helpers: .set_headers(), .with_options(), .raw() (low-level access)
- Fully backward compatible with legacy ASK-first aliases

Environment (with defaults):
  PIKIT_OPENAI_BASE_URL   default: http://localhost:8080/v1
  PIKIT_OPENAI_API_KEY    default: sk-local
  PIKIT_MODEL_NAME        default: mistral-7b-instruct
  PIKIT_REQUEST_TIMEOUT   default: 120
  PIKIT_CHAT_TEMPERATURE  default: 0.7
  PIKIT_RETRY_TOTAL       default: 4
  PIKIT_RETRY_BACKOFF     default: 0.5
"""

from __future__ import annotations

import os, json, typing as t
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

Json = t.Dict[str, t.Any]
Headers = t.Dict[str, str]

DEFAULTS = {
    "base_url": os.getenv("PIKIT_OPENAI_BASE_URL", "http://localhost:8080/v1").rstrip("/"),
    "api_key": os.getenv("PIKIT_OPENAI_API_KEY", "sk-local"),
    "model": os.getenv("PIKIT_MODEL_NAME", "mistral-7b-instruct"),
    "timeout": float(os.getenv("PIKIT_REQUEST_TIMEOUT", "120")),
    "temperature": float(os.getenv("PIKIT_CHAT_TEMPERATURE", "0.7")),
    "retry_total": int(os.getenv("PIKIT_RETRY_TOTAL", "4")),
    "retry_backoff": float(os.getenv("PIKIT_RETRY_BACKOFF", "0.5")),
}

def _as_messages(user_or_messages: t.Union[str, t.List[Json]], system_prompt: t.Optional[str]) -> t.List[Json]:
    if isinstance(user_or_messages, str):
        msgs = [{"role": "user", "content": user_or_messages}]
    else:
        msgs = list(user_or_messages)
    if system_prompt:
        if not msgs or msgs[0].get("role") != "system":
            msgs = [{"role": "system", "content": system_prompt}] + msgs
    return msgs

class AIInterface:
    """
    Usage:
        ai = AIInterface()
        text = ai.ask("Say hi.")              # legacy alias (chat)
        text = ai.chat("Say hi.")             # modern
        for tok in ai.chat("stream me", stream=True): print(tok, end="")
        vecs = ai.embed(["hello", "world"])
        print(ai.ping(), ai.whoami(), ai.list_models())
    """
    def __init__(self,
                 base_url: str | None = None,
                 api_key: str | None = None,
                 model: str | None = None,
                 timeout: float | None = None,
                 default_temperature: float | None = None,
                 retry_total: int | None = None,
                 retry_backoff: float | None = None,
                 debug: bool = False):
        cfg = DEFAULTS.copy()
        if base_url: cfg["base_url"] = base_url.rstrip("/")
        if api_key: cfg["api_key"] = api_key
        if model: cfg["model"] = model
        if timeout is not None: cfg["timeout"] = timeout
        if default_temperature is not None: cfg["temperature"] = default_temperature
        if retry_total is not None: cfg["retry_total"] = retry_total
        if retry_backoff is not None: cfg["retry_backoff"] = retry_backoff

        self.base_url = cfg["base_url"]
        self.api_key = cfg["api_key"]
        self.model = cfg["model"]
        self.timeout = cfg["timeout"]
        self.default_temperature = cfg["temperature"]
        self.debug = bool(debug)

        self._session = requests.Session()
        self._system_prompt: str | None = None
        self._extra_headers: Headers = {}

        # Install retries (idempotent POSTs to LLMs are generally safe to retry)
        retry = Retry(
            total=cfg["retry_total"],
            backoff_factor=cfg["retry_backoff"],
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET", "POST"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

    # ---- config ----
    def set_system_prompt(self, text: str | None) -> None:
        self._system_prompt = text or None

    def set_headers(self, headers: Headers | None) -> None:
        """Set/replace extra headers to be merged on every request."""
        self._extra_headers = dict(headers or {})

    def with_options(self, **overrides) -> "AIInterface":
        """Return a shallow clone with a few overrides (e.g., model='…')."""
        cls = self.__class__
        new = cls(
            base_url=overrides.get("base_url", self.base_url),
            api_key=overrides.get("api_key", self.api_key),
            model=overrides.get("model", self.model),
            timeout=overrides.get("timeout", self.timeout),
            default_temperature=overrides.get("default_temperature", self.default_temperature),
            retry_total=overrides.get("retry_total", DEFAULTS["retry_total"]),
            retry_backoff=overrides.get("retry_backoff", DEFAULTS["retry_backoff"]),
            debug=overrides.get("debug", self.debug),
        )
        new._system_prompt = self._system_prompt
        new._extra_headers = dict(self._extra_headers)
        return new

    def get_config(self) -> Json:
        return {
            "base_url": self.base_url,
            "model": self.model,
            "timeout": self.timeout,
            "default_temperature": self.default_temperature,
            "has_system_prompt": bool(self._system_prompt),
            "has_extra_headers": bool(self._extra_headers),
            "debug": self.debug,
        }

    # ---- utilities ----
    def _headers(self, extra_headers: Headers | None = None) -> Headers:
        h = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self._extra_headers:
            h.update(self._extra_headers)
        if extra_headers:
            h.update(extra_headers)
        return h

    def _format_http_error(self, resp: requests.Response, exc: Exception) -> str:
        try:
            body = resp.text
        except Exception:
            body = ""
        short = f"HTTP {resp.status_code}: {exc}"
        if not self.debug:
            # Try to compress noisy backend JSON into a single line
            return f"{short}\n{body[:800]}"
        return f"{short}\n{body}"

    def _extract_text(self, resp: requests.Response) -> str:
        try:
            resp.raise_for_status()
        except Exception as e:
            raise RuntimeError(self._format_http_error(resp, e))
        try:
            data = resp.json()
        except Exception as e:
            raise RuntimeError(f"Bad JSON from server: {e}\n{resp.text[:800]}")
        # Chat primary
        try:
            return data["choices"][0]["message"]["content"] or ""
        except Exception:
            # Completion fallback
            try:
                return data["choices"][0].get("text", "") or ""
            except Exception:
                raise RuntimeError(f"Unexpected response: {json.dumps(data)[:600]}")

    def _stream_text_from_resp(self, resp: requests.Response) -> t.Iterator[str]:
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            payload = line[6:].strip() if line.startswith("data: ") else line.strip()
            if payload == "[DONE]":
                break
            try:
                j = json.loads(payload)
                delta = j.get("choices", [{}])[0].get("delta", {}).get("content", "")
                if delta:
                    yield delta
            except Exception:
                # Some servers may stream raw text chunks
                yield payload

    # ---- health & discovery ----
    def ping(self, timeout: float | None = None) -> bool:
        """Quick health probe against base_url (returns True if HTTP 200..399)."""
        try:
            resp = self._session.get(self.base_url, headers=self._headers(), timeout=timeout or self.timeout)
            return 200 <= resp.status_code < 400
        except Exception:
            return False

    def whoami(self) -> Json:
        """Return a small dict describing the server and default model."""
        info = {"base_url": self.base_url, "model": self.model}
        try:
            # Try /models (works with OpenAI/LocalAI)
            ms = self.list_models()
            info["models_count"] = len(ms)
            info["has_default_model"] = any(m.get("id") == self.model for m in ms)
        except Exception as e:
            info["models_error"] = str(e)
        return info

    def list_models(self) -> t.List[Json]:
        url = f"{self.base_url}/models"
        resp = self._session.get(url, headers=self._headers(), timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        # OpenAI shape: {"data":[{"id":"gpt-3.5-turbo",...},...]}
        if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
            return data["data"]
        # LocalAI can return a plain list sometimes
        if isinstance(data, list):
            return data
        return []

    # ---- chat ----
    def chat(self,
             prompt_or_messages: t.Union[str, t.List[Json]],
             stream: bool = False,
             temperature: float | None = None,
             max_tokens: int | None = None,
             tools: t.Optional[t.List[Json]] = None,
             tool_choice: t.Optional[t.Union[str, Json]] = None,
             stop: t.Optional[t.Union[str, t.List[str]]] = None,
             extra_headers: t.Optional[Headers] = None,
             timeout: float | None = None,
             **extra) -> t.Union[str, t.Iterator[str]]:
        url = f"{self.base_url}/chat/completions"
        msgs = _as_messages(prompt_or_messages, self._system_prompt)
        payload: Json = {
            "model": self.model,
            "messages": msgs,
            "temperature": self.default_temperature if temperature is None else temperature,
        }
        if max_tokens is not None: payload["max_tokens"] = max_tokens
        if tools is not None: payload["tools"] = tools
        if tool_choice is not None: payload["tool_choice"] = tool_choice
        if stop is not None: payload["stop"] = stop
        if extra: payload.update(extra)

        headers = self._headers(extra_headers)
        to = timeout or self.timeout

        if stream:
            payload["stream"] = True
            resp = self._session.post(url, headers=headers, json=payload, timeout=to, stream=True)
            try:
                resp.raise_for_status()
            except Exception as e:
                raise RuntimeError(self._format_http_error(resp, e))
            return self._stream_text_from_resp(resp)
        else:
            resp = self._session.post(url, headers=headers, json=payload, timeout=to)
            return self._extract_text(resp)

    # Convenience wrappers for streaming explicitness
    def stream_text(self, prompt_or_messages: t.Union[str, t.List[Json]], **kw) -> t.Iterator[str]:
        kw["stream"] = True
        return self.chat(prompt_or_messages, **kw)  # type: ignore[return-value]

    def stream_json(self, prompt_or_messages: t.Union[str, t.List[Json]], **kw) -> t.Iterator[Json]:
        """Yield raw SSE JSON dicts (if server sends JSON events)."""
        url = f"{self.base_url}/chat/completions"
        msgs = _as_messages(prompt_or_messages, self._system_prompt)
        payload: Json = {
            "model": self.model,
            "messages": msgs,
            "temperature": self.default_temperature if kw.get("temperature") is None else kw["temperature"],
            "stream": True,
        }
        for k in ("max_tokens", "tools", "tool_choice", "stop"):
            if k in kw and kw[k] is not None:
                payload[k] = kw[k]
        headers = self._headers(kw.get("extra_headers"))
        to = kw.get("timeout", self.timeout)
        resp = self._session.post(url, headers=headers, json=payload, timeout=to, stream=True)
        try:
            resp.raise_for_status()
        except Exception as e:
            raise RuntimeError(self._format_http_error(resp, e))
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            payload = line[6:].strip() if line.startswith("data: ") else line.strip()
            if payload == "[DONE]":
                break
            try:
                yield json.loads(payload)
            except Exception:
                # Provide a consistent JSON wrapper if server emits raw text
                yield {"type": "text", "data": payload}

    # ---- embeddings ----
    def embed(self, texts: t.List[str], model: str | None = None, timeout: float | None = None) -> t.List[t.List[float]]:
        url = f"{self.base_url}/embeddings"
        payload: Json = {
            "model": model or self.model,
            "input": texts,
        }
        resp = self._session.post(url, headers=self._headers(), json=payload, timeout=timeout or self.timeout)
        resp.raise_for_status()
        data = resp.json()
        return [item["embedding"] for item in data.get("data", [])]

    # ---- raw access (power users) ----
    def raw(self, path: str, method: str = "GET", json_body: Json | None = None,
            headers: Headers | None = None, **req_kw) -> requests.Response:
        url = path if path.startswith("http") else f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        h = self._headers(headers)
        m = method.upper()
        func = self._session.get if m == "GET" else self._session.post
        return func(url, headers=h, json=json_body, timeout=req_kw.pop("timeout", self.timeout), **req_kw)

    # ---- Legacy aliases: ASK-first ----
    def ask(self, prompt_or_messages, **kw):
        """Legacy alias for .chat()."""
        return self.chat(prompt_or_messages, **kw)

    def query(self, prompt_or_messages, **kw):
        """Legacy alias for .chat()."""
        return self.chat(prompt_or_messages, **kw)

    def completions(self, prompt_or_messages, **kw):
        return self.chat(prompt_or_messages, **kw)

    def completion(self, prompt_or_messages, **kw):
        return self.chat(prompt_or_messages, **kw)

    def complete(self, prompt_or_messages, **kw):
        return self.chat(prompt_or_messages, **kw)

    def chat_completions(self, prompt_or_messages, **kw):
        return self.chat(prompt_or_messages, **kw)


# ---------------------------------------------------------------------------
# Compatibility shim for older imports
# ---------------------------------------------------------------------------
class TriAIInterface(AIInterface):
    """Backwards-compatible subclass — no changes needed."""
    pass

__all__ = ["AIInterface", "TriAIInterface"]
