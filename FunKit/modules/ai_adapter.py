# modules/ai_adapter.py
from __future__ import annotations

import configparser
import logging
import os
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Optional

from modules.local_ai_interface import AIInterface as OpenAICompatibleAI
from modules.provider_registry import ProviderConfig, registry

log = logging.getLogger(__name__)

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_BASETEN_BASE_URL = "https://inference.baseten.co/v1"
DEFAULT_LOCAL_BASE_URL = "http://127.0.0.1:8081/v1"
PLACEHOLDER_MODELS = {"", "YOUR_BASETEN_MODEL"}

PROVIDER_ALIASES = {
    "openai": "openai",
    "baseten": "baseten",
    "local": "local_llama",
    "local_llama": "local_llama",
    "llamacpp": "local_llama",
    "mistral": "local_llama",
}


def _with_v1_suffix(url: str) -> str:
    trimmed = (url or "").rstrip("/")
    if not trimmed:
        return trimmed
    if trimmed.endswith("/v1"):
        return trimmed
    return f"{trimmed}/v1"


def _resolve_registry_key(provider: Optional[str]) -> str:
    raw = (provider or os.getenv("FUNKIT_AI_PROVIDER") or registry.read_selected()).strip().lower()
    return PROVIDER_ALIASES.get(raw, raw)


def _safe_provider_config(provider_key: str) -> ProviderConfig:
    try:
        return registry.get(provider_key)
    except Exception:
        if provider_key == "local_llama":
            return ProviderConfig(
                key="local_llama",
                label="Local (llama.cpp)",
                model=os.getenv("PIKIT_MODEL_NAME", "mistral-7b-instruct"),
                endpoint=os.getenv("PIKIT_OPENAI_BASE_URL", DEFAULT_LOCAL_BASE_URL),
                env_key=None,
                extras={"timeout": 120},
            )
        if provider_key == "baseten":
            return ProviderConfig(
                key="baseten",
                label="Baseten",
                model=os.getenv("BASETEN_MODEL", "openai/gpt-oss-120b"),
                endpoint=os.getenv("BASETEN_BASE_URL", DEFAULT_BASETEN_BASE_URL),
                env_key="BASETEN_API_KEY",
                extras={},
            )
        return ProviderConfig(
            key="openai",
            label="OpenAI",
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            endpoint=os.getenv("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL),
            env_key="OPENAI_API_KEY",
            extras={},
        )


def _normalize_query_kwargs(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(kwargs)
    overrides = normalized.pop("overrides", None)
    if isinstance(overrides, dict):
        normalized.update({k: v for k, v in overrides.items() if v is not None})
    extra_headers = normalized.pop("extra_headers", None)
    if extra_headers is not None:
        normalized["extra_headers"] = extra_headers
    return normalized


def _read_legacy_settings() -> dict:
    try:
        path = Path("funkit_settings.json")
        if path.exists():
            import json

            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _load_legacy_user_config() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    cfg_path = Path.home() / ".funkit" / "funkit.conf"
    if cfg_path.exists():
        cfg.read(cfg_path)
    return cfg


def _config_value(cfg: configparser.ConfigParser, section: str, option: str) -> str:
    try:
        return cfg.get(section, option, fallback="").strip()
    except Exception:
        return ""


class AIInterface:
    """
    FunKit-facing adapter that routes requests through the configured provider.
    It keeps the older FunKit method names while delegating actual I/O to a
    generic OpenAI-compatible client.
    """

    def __init__(
        self,
        provider: Optional[str] = None,
        default_model: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
        timeout_s: int = 120,
    ):
        self._provider_key = ""
        self._config: ProviderConfig | None = None
        self._default_model = default_model
        self._extra_headers = extra_headers or {}
        self._timeout_s = timeout_s
        self._api_key_override: str | None = None
        self._client: OpenAICompatibleAI | None = None
        self.set_provider(provider or registry.read_selected(), default_model=default_model)

    def _resolve_baseten_model(self, cfg: ProviderConfig, default_model: Optional[str]) -> str:
        legacy_cfg = _load_legacy_user_config()
        model = default_model if default_model not in PLACEHOLDER_MODELS else None
        if not model and cfg.model not in PLACEHOLDER_MODELS:
            model = cfg.model
        if not model:
            model = _config_value(legacy_cfg, "baseten", "model")
        if not model:
            model = os.getenv("BASETEN_MODEL") or os.getenv("BASETEN_MODEL_NAME")
        if not model:
            settings = _read_legacy_settings()
            baseten_cfg = settings.get("baseten") or {}
            model = baseten_cfg.get("model") or baseten_cfg.get("name")
        if not model:
            model = "openai/gpt-oss-120b"
        return str(model)

    def _resolve_baseten_base_url(self, cfg: ProviderConfig) -> str:
        legacy_cfg = _load_legacy_user_config()
        configured_url = cfg.endpoint if cfg.endpoint and "baseten.co/models" not in cfg.endpoint else None
        url = (
            os.getenv("BASETEN_BASE_URL")
            or os.getenv("BASETEN_URL")
            or _config_value(legacy_cfg, "baseten", "url")
            or configured_url
            or DEFAULT_BASETEN_BASE_URL
        )
        return _with_v1_suffix(url)

    def _resolve_baseten_api_key(self) -> str:
        legacy_cfg = _load_legacy_user_config()
        return (
            self._api_key_override
            or os.getenv("BASETEN_API_KEY", "")
            or _config_value(legacy_cfg, "baseten", "api_key")
        )

    def _build_client(
        self,
        provider_key: str,
        default_model: Optional[str] = None,
    ) -> OpenAICompatibleAI:
        cfg = _safe_provider_config(provider_key)
        timeout = float(cfg.extras.get("timeout", self._timeout_s))

        if provider_key == "openai":
            base_url = _with_v1_suffix(os.getenv("OPENAI_BASE_URL", cfg.endpoint or DEFAULT_OPENAI_BASE_URL))
            api_key = self._api_key_override or os.getenv("OPENAI_API_KEY", "")
            model = default_model or cfg.model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        elif provider_key == "baseten":
            base_url = self._resolve_baseten_base_url(cfg)
            api_key = self._resolve_baseten_api_key()
            model = self._resolve_baseten_model(cfg, default_model)
        else:
            base_url = _with_v1_suffix(
                os.getenv("PIKIT_OPENAI_BASE_URL", cfg.endpoint or DEFAULT_LOCAL_BASE_URL)
            )
            api_key = self._api_key_override or os.getenv("PIKIT_OPENAI_API_KEY", "sk-local")
            model = default_model or cfg.model or os.getenv("PIKIT_MODEL_NAME", "mistral-7b-instruct")

        client = OpenAICompatibleAI(
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout=timeout,
        )
        if self._extra_headers:
            client.set_headers(self._extra_headers)

        self._config = cfg
        self._default_model = model
        log.info("AIAdapter initialized (provider=%s, model=%s, base_url=%s)", provider_key, model, base_url)
        return client

    def _chat(self, prompt_or_messages, **kwargs):
        if self._client is None:
            raise RuntimeError("AI client is not initialized")
        return self._client.chat(prompt_or_messages, **_normalize_query_kwargs(kwargs))

    def ask(self, prompt, model: Optional[str] = None, **kwargs) -> str:
        if model:
            kwargs["model"] = model
        return self._chat(prompt, **kwargs)

    def stream(self, prompt, model: Optional[str] = None, **kwargs) -> Iterable[str]:
        if model:
            kwargs["model"] = model
        kwargs["stream"] = True
        stream = self._chat(prompt, **kwargs)
        if isinstance(stream, str):
            def _one_shot() -> Iterator[str]:
                yield stream
            return _one_shot()
        return stream

    def query(self, *args, **kwargs):
        messages = kwargs.pop("messages", None)
        prompt = kwargs.pop("prompt", None)
        system = kwargs.pop("system", None)
        stream = kwargs.pop("stream", False)

        if args:
            if len(args) == 1:
                prompt = args[0]
            else:
                prompt = args[0]
                system = args[1]

        if messages is None:
            if prompt is None:
                raise ValueError("query() requires messages=[...] or a prompt string")
            prompt_or_messages = []
            if system:
                prompt_or_messages.append({"role": "system", "content": system})
            prompt_or_messages.append({"role": "user", "content": str(prompt)})
        else:
            prompt_or_messages = messages

        kwargs = _normalize_query_kwargs(kwargs)
        if stream:
            kwargs["stream"] = True
        return self._chat(prompt_or_messages, **kwargs)

    def complete(self, *args, **kwargs):
        return self.query(*args, **kwargs)

    def completion(self, *args, **kwargs):
        return self.query(*args, **kwargs)

    def generate(self, *args, **kwargs):
        return self.query(*args, **kwargs)

    def chat(self, messages=None, prompt=None, model=None, **kwargs):
        if model:
            kwargs["model"] = model
        if messages is not None:
            return self._chat(messages, **kwargs)
        if prompt is None:
            raise ValueError("chat() requires messages or prompt")
        return self._chat(prompt, **kwargs)

    def set_provider(self, provider: str, default_model: Optional[str] = None) -> None:
        provider_key = _resolve_registry_key(provider)
        self._provider_key = provider_key
        self._client = self._build_client(provider_key, default_model=default_model)

    def get_provider(self) -> str:
        return self._provider_key

    def set_api_key(self, api_key: str) -> None:
        self._api_key_override = api_key
        self._client = self._build_client(self._provider_key, default_model=self._default_model)

    def models(self):
        if self._client is None:
            return []
        try:
            return list(self._client.list_models())
        except Exception:
            return []

    def healthcheck(self) -> Dict[str, Any]:
        if self._client is None:
            return {"ok": False, "provider": self._provider_key, "error": "client not initialized"}
        try:
            return {
                "ok": bool(self._client.ping()),
                "provider": self._provider_key,
                "details": self._client.whoami(),
            }
        except Exception as exc:
            return {"ok": False, "provider": self._provider_key, "error": str(exc)}
