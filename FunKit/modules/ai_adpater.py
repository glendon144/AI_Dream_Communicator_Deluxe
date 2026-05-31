# modules/ai_adapter.py
import os
import logging
import inspect
from typing import Iterable, Optional, Dict, Any

from modules.pikit_port.ai_interface import AIInterface as PiKitAI

log = logging.getLogger(__name__)

PROVIDER_ALIASES = {
    "openai": "openai",
    "mistral": "mistral",
    "baseten": "baseten",
    "local": "local",
    "llamacpp": "llamacpp",
}


def _filter_kwargs_for_ctor(cls, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Only pass kwargs that the target class __init__ actually accepts."""
    try:
        sig = inspect.signature(cls.__init__)
        valid = {p.name for p in sig.parameters.values() if p.name != "self"}
        return {k: v for k, v in kwargs.items() if k in valid}
    except Exception:
        return {}


class AIInterface:
    """Adapter that lets FunKit use PiKit’s AIInterface transparently."""

    def __init__(
        self,
        provider: Optional[str] = None,
        default_model: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
        timeout_s: int = 120,
    ):
        prov = provider or os.getenv("FUNKIT_AI_PROVIDER") or "openai"
        prov = PROVIDER_ALIASES.get(prov.lower(), prov.lower())

        self._provider = prov
        self._default_model = default_model
        self._extra_headers = extra_headers or {}
        self._timeout_s = timeout_s

        ctor_kwargs = {
            "provider": prov,
            "default_model": default_model,
            "timeout": timeout_s,
            "extra_headers": self._extra_headers,
        }
        filtered = _filter_kwargs_for_ctor(PiKitAI, ctor_kwargs)

        try:
            self._client = PiKitAI(**filtered)
        except TypeError:
            self._client = PiKitAI()

        log.info("AIAdapter initialized (provider=%s, model=%s)", prov, default_model)

    def ask(self, prompt: str, model: Optional[str] = None, **kw) -> str:
        return self._client.ask(prompt=prompt, model=model or self._default_model, **kw)

    def stream(self, prompt: str, model: Optional[str] = None, **kw) -> Iterable[str]:
        stream_fn = getattr(self._client, "stream", None)
        if not callable(stream_fn):
            yield self.ask(prompt, model, **kw)
            return
        yield from stream_fn(prompt=prompt, model=model or self._default_model, **kw)

    def set_provider(self, provider: str, default_model: Optional[str] = None) -> None:
        prov = PROVIDER_ALIASES.get(provider.lower(), provider.lower())
        setter = getattr(self._client, "set_provider", None)

        if callable(setter):
            setter(prov, default_model or self._default_model)
        else:
            ctor_kwargs = {
                "provider": prov,
                "default_model": default_model or self._default_model,
                "timeout": self._timeout_s,
                "extra_headers": self._extra_headers,
            }
            filtered = _filter_kwargs_for_ctor(PiKitAI, ctor_kwargs)
            try:
                self._client = PiKitAI(**filtered)
            except TypeError:
                self._client = PiKitAI()

        self._provider = prov
        if default_model:
            self._default_model = default_model

    def get_provider(self) -> str:
        return self._provider

    def models(self):
        fn = getattr(self._client, "models", None)
        return list(fn()) if callable(fn) else []

    def healthcheck(self) -> Dict[str, Any]:
        fn = getattr(self._client, "healthcheck", None)
        if callable(fn):
            try:
                return fn()
            except Exception as e:
                return {"ok": False, "error": str(e), "provider": self._provider}
        return {"ok": True, "provider": self._provider}

