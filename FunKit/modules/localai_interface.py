#!/usr/bin/env python3
"""
ai_interface.py — OpenAI-compatible adapter for FunKit (llama.cpp server)
- Always sends Authorization header from PIKIT_OPENAI_API_KEY
- Builds clean /v1/chat/completions payloads
- Default max_tokens from PIKIT_MAX_TOKENS_DEFAULT (256)
- ASK-first alias + TriAIInterface shim
- Debug logging when PIKIT_DEBUG=1
"""

from __future__ import annotations
import os, json, typing as t, requests

Json = t.Dict[str, t.Any]
Headers = t.Dict[str, str]

def _env(name: str, default: str) -> str:
    v = os.getenv(name)
    return v if v is not None and v != "" else default

DEFAULT_BASE_URL = _env("PIKIT_OPENAI_BASE_URL", "http://localhost:8081/v1").rstrip("/")
DEFAULT_API_KEY  = _env("PIKIT_OPENAI_API_KEY", "funkit-local")   # <— your server uses this key
DEFAULT_MODEL    = _env("PIKIT_MODEL_NAME", "mistral-7b-instruct")
DEFAULT_TIMEOUT  = float(_env("PIKIT_REQUEST_TIMEOUT", "600"))
DEFAULT_TEMP     = float(_env("PIKIT_CHAT_TEMPERATURE", "0.7"))
DEFAULT_MAXTOK   = int(_env("PIKIT_MAX_TOKENS_DEFAULT", "256"))
DEBUG            = _env("PIKIT_DEBUG", "0") == "1"

def _as_messages(user_or_messages: t.Union[str, t.List[Json]], system_prompt: t.Optional[str]) -> t.List[Json]:
    if isinstance(user_or_messages, str):
        msgs = [{"role": "user", "content": user_or_messages}]
    else:
        msgs = list(user_or_messages)
    if system_prompt:
        if not msgs or msgs[0].get("role") != "system":
            msgs = [{"role": "system", "content": system_prompt}] + msgs
    return msgs

def _prune(d: Json) -> Json:
    out: Json = {}
    for k, v in d.items():
        if v is None:  # drop nulls
            continue
        if isinstance(v, (list, dict, str)) and not v:  # drop empties
            continue
        out[k] = v
    return out

class AIInterface:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
        default_temperature: float | None = None,
        max_tokens_default: int | None = None,
    ):
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.api_key  = api_key if api_key not in (None, "") else DEFAULT_API_KEY
        self.model    = model or DEFAULT_MODEL
        self.timeout  = timeout if timeout is not None else DEFAULT_TIMEOUT
        self.default_temperature = default_temperature if default_temperature is not None else DEFAULT_TEMP
        self.max_tokens_default  = int(max_tokens_default) if max_tokens_default is not None else DEFAULT_MAXTOK
        self._session = requests.Session()
        self._system_prompt: str | None = None

    # Optional system prompt
    def set_system_prompt(self, text: str | None) -> None:
        self._system_prompt = text or None

    def get_config(self) -> Json:
        return {
            "base_url": self.base_url,
            "model": self.model,
            "timeout": self.timeout,
            "default_temperature": self.default_temperature,
            "max_tokens_default": self.max_tokens_default,
            "has_system_prompt": bool(self._system_prompt),
            "sends_auth_header": True,
        }

    def _headers(self, extra_headers: t.Optional[Headers] = None) -> Headers:
        h: Headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        if extra_headers:
            h.update(extra_headers)
        return h

    def chat(
        self,
        prompt_or_messages: t.Union[str, t.List[Json]],
        stream: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: t.Optional[t.List[Json]] = None,
        tool_choice: t.Optional[t.Union[str, Json]] = None,
        stop: t.Optional[t.Union[str, t.List[str]]] = None,
        extra_headers: t.Optional[Headers] = None,
        **extra: t.Any,
    ) -> t.Union[str, t.Iterator[str]]:
        url = f"{self.base_url}/chat/completions"
        msgs = _as_messages(prompt_or_messages, self._system_prompt)
        payload: Json = {
            "model": self.model,
            "messages": msgs,
            "temperature": self.default_temperature if temperature is None else temperature,
            "max_tokens": int(max_tokens) if max_tokens is not None else self.max_tokens_default,
            # llama.cpp ignores tools/tool_choice today, but keep fields off unless provided
        }
        if tools is not None:       payload["tools"] = tools
        if tool_choice is not None: payload["tool_choice"] = tool_choice
        if stop is not None:        payload["stop"] = stop
        # merge any extras, then prune empties/None
        payload = _prune({**payload, **extra})

        if DEBUG:
            print("[AIInterface] POST", url)
            print("[AIInterface] Headers:", {k: ("<redacted>" if k.lower()=="authorization" else v)
                                             for k, v in self._headers(extra_headers).items()})
            print("[AIInterface] Payload:", json.dumps(payload, ensure_ascii=False))

        if stream:
            payload["stream"] = True
            resp = self._session.post(url, headers=self._headers(extra_headers),
                                      json=payload, timeout=self.timeout, stream=True)
            resp.raise_for_status()
            return self._stream_text(resp)
        else:
            resp = self._session.post(url, headers=self._headers(extra_headers),
                                      json=payload, timeout=self.timeout)
            return self._extract_text(resp)

    def embed(self, texts: t.List[str], model: str | None = None) -> t.List[t.List[float]]:
        url = f"{self.base_url}/embeddings"
        payload: Json = _prune({
            "model": model or self.model,
            "input": texts,
        })
        if DEBUG:
            print("[AIInterface] POST", url)
            print("[AIInterface] Headers:", {"Content-Type":"application/json","Authorization":"<redacted>"})
            print("[AIInterface] Payload:", json.dumps(payload, ensure_ascii=False))
        resp = self._session.post(url, headers=self._headers(), json=payload, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        return [item["embedding"] for item in data.get("data", [])]

    # --- helpers -------------------------------------------------------------

    def _extract_text(self, resp: requests.Response) -> str:
        try:
            resp.raise_for_status()
        except Exception as e:
            raise RuntimeError(self._format_http_error(resp, e))
        data = resp.json()
        # OpenAI-like schema
        try:
            return data["choices"][0]["message"]["content"] or ""
        except Exception:
            # Fallback for engines that use "text"
            try:
                return data["choices"][0].get("text", "") or ""
            except Exception:
                raise RuntimeError(f"Unexpected response: {json.dumps(data)[:800]}")

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
                # best-effort passthrough
                yield payload

    def _format_http_error(self, resp: requests.Response, exc: Exception) -> str:
        body = ""
        try:
            body = resp.text
        except Exception:
            pass
        return f"HTTP {resp.status_code}: {exc}\n{body[:1000]}"

    # Legacy aliases / shims
    def ask(self, prompt_or_messages, **kw): return self.chat(prompt_or_messages, **kw)
    def query(self, prompt_or_messages, **kw): return self.chat(prompt_or_messages, **kw)
    def completions(self, prompt_or_messages, **kw): return self.chat(prompt_or_messages, **kw)
    def completion(self, prompt_or_messages, **kw): return self.chat(prompt_or_messages, **kw)
    def complete(self, prompt_or_messages, **kw): return self.chat(prompt_or_messages, **kw)
    def chat_completions(self, prompt_or_messages, **kw): return self.chat(prompt_or_messages, **kw)

class TriAIInterface(AIInterface):
    pass

__all__ = ["AIInterface", "TriAIInterface"]

