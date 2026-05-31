
#!/usr/bin/env python3
"""
ai_interface.py — OpenAI-compatible adapter for FunKit (LocalAI / vLLM / OpenAI)
==============================================================================
- Uses plain HTTP via 'requests' (no openai lib dependency)
- Exposes ASK-first legacy methods directly on AIInterface:
    ask(), query(), completions(), completion(), complete(), chat_completions()
- Also exports TriAIInterface shim for older imports
- Compatible with /v1/chat/completions and /v1/embeddings

Environment (with defaults):
  PIKIT_OPENAI_BASE_URL   default: http://localhost:8080/v1
  PIKIT_OPENAI_API_KEY    default: sk-local
  PIKIT_MODEL_NAME        default: mistral-7b-instruct
  PIKIT_REQUEST_TIMEOUT   default: 120
  PIKIT_CHAT_TEMPERATURE  default: 0.7
"""

from __future__ import annotations
import os, json, typing as t, requests

Json = t.Dict[str, t.Any]
Headers = t.Dict[str, str]

DEFAULTS = {
    "base_url": os.getenv("PIKIT_OPENAI_BASE_URL", "http://localhost:8080/v1").rstrip("/"),
    "api_key": os.getenv("PIKIT_OPENAI_API_KEY", "sk-local"),
    "model": os.getenv("PIKIT_MODEL_NAME", "mistral-7b-instruct"),
    "timeout": float(os.getenv("PIKIT_REQUEST_TIMEOUT", "120")),
    "temperature": float(os.getenv("PIKIT_CHAT_TEMPERATURE", "0.7")),
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
        text = ai.ask("Say hi.")              # legacy alias
        text = ai.chat("Say hi.")             # modern
        for chunk in ai.ask("stream", stream=True): print(chunk, end="")
        vecs = ai.embed(["hello", "world"])
    """
    def __init__(self,
                 base_url: str | None = None,
                 api_key: str | None = None,
                 model: str | None = None,
                 timeout: float | None = None,
                 default_temperature: float | None = None):
        cfg = DEFAULTS.copy()
        if base_url: cfg["base_url"] = base_url.rstrip("/")
        if api_key: cfg["api_key"] = api_key
        if model: cfg["model"] = model
        if timeout is not None: cfg["timeout"] = timeout
        if default_temperature is not None: cfg["temperature"] = default_temperature
        self.base_url = cfg["base_url"]
        self.api_key = cfg["api_key"]
        self.model = cfg["model"]
        self.timeout = cfg["timeout"]
        self.default_temperature = cfg["temperature"]
        self._session = requests.Session()
        self._system_prompt: str | None = None

    # ---- config ----
    def set_system_prompt(self, text: str | None) -> None:
        self._system_prompt = text or None

    def get_config(self) -> Json:
        return {
            "base_url": self.base_url,
            "model": self.model,
            "timeout": self.timeout,
            "default_temperature": self.default_temperature,
            "has_system_prompt": bool(self._system_prompt),
        }

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
             **extra) -> t.Union[str, t.Iterator[str]]:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)
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

        if stream:
            payload["stream"] = True
            resp = self._session.post(url, headers=headers, json=payload, timeout=self.timeout, stream=True)
            resp.raise_for_status()
            return self._stream_text(resp)
        else:
            resp = self._session.post(url, headers=headers, json=payload, timeout=self.timeout)
            return self._extract_text(resp)

    # ---- embeddings ----
    def embed(self, texts: t.List[str], model: str | None = None) -> t.List[t.List[float]]:
        url = f"{self.base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: Json = {
            "model": model or self.model,
            "input": texts,
        }
        resp = self._session.post(url, headers=headers, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        return [item["embedding"] for item in data.get("data", [])]

    # ---- internals ----
    def _extract_text(self, resp: requests.Response) -> str:
        try:
            resp.raise_for_status()
        except Exception as e:
            raise RuntimeError(self._format_http_error(resp, e))
        data = resp.json()
        # Chat-style primary
        try:
            return data["choices"][0]["message"]["content"] or ""
        except Exception:
            # Completion-style fallback
            try:
                return data["choices"][0].get("text", "") or ""
            except Exception:
                raise RuntimeError(f"Unexpected response: {json.dumps(data)[:600]}")

    def _stream_text(self, resp: requests.Response) -> t.Iterator[str]:
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

    def _format_http_error(self, resp: requests.Response, exc: Exception) -> str:
        body = ""
        try:
            body = resp.text
        except Exception:
            pass
        return f"HTTP {resp.status_code}: {exc}\n{body[:800]}"

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
