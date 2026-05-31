from __future__ import annotations
import json, os, threading
from dataclasses import dataclass
from typing import Dict, Optional, Any

PROVIDERS_PATH = os.path.join("storage", "providers.json")
APP_STATE_PATH = os.path.join("storage", "app_state.json")
_lock = threading.Lock()

@dataclass
class ProviderConfig:
    key: str                 # e.g. "openai", "baseten", "local_llama"
    label: str               # UI label
    model: str               # default model name for this provider
    endpoint: Optional[str]  # http endpoint for self/3rd-party providers, else None
    env_key: Optional[str]   # which env var to read for secret, e.g. "OPENAI_API_KEY"
    extras: Dict[str, Any]   # any provider-specific knobs

class ProviderRegistry:
    def __init__(self):
        # use insertion-order-preserving dict (3.7+)
        self.providers: Dict[str, ProviderConfig] = {}
        self.default_key: str = "openai"
        self._load()

    def _ensure_defaults_on_disk(self):
        if not os.path.exists(PROVIDERS_PATH):
            os.makedirs(os.path.dirname(PROVIDERS_PATH), exist_ok=True)
            defaults = {
                "default": "local_llama",
                "providers": [
                    {
                        "key":"local_llama","label":"Local (llama.cpp)","model":"mistral-7b-instruct",
                        "endpoint":"http://127.0.0.1:8081","env_key":None,"extras":{"timeout":120}
                    },
                    {
                        "key":"openai","label":"OpenAI (GPT-4o/5)","model":"gpt-4o-mini",
                        "endpoint": None,"env_key":"OPENAI_API_KEY","extras":{}
                    },
                    {
                        "key":"baseten","label":"Baseten","model":"YOUR_BASETEN_MODEL",
                        "endpoint":"https://app.baseten.co/models","env_key":"BASETEN_API_KEY","extras":{}
                    }
                ]
            }
            with open(PROVIDERS_PATH, "w", encoding="utf-8") as f:
                json.dump(defaults, f, indent=2)

        if not os.path.exists(APP_STATE_PATH):
            with open(APP_STATE_PATH, "w", encoding="utf-8") as f:
                json.dump({"selected_provider": "local_llama"}, f)

    def _load(self):
        self._ensure_defaults_on_disk()
        with open(PROVIDERS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.providers.clear()
        self.default_key = data.get("default", "openai")
        for p in data.get("providers", []):
            cfg = ProviderConfig(**p)
            self.providers[cfg.key] = cfg

    # ----- public API -----

    def list_labels(self):
        """Return [(key, label), ...] preserving providers.json order."""
        return [(cfg.key, cfg.label) for cfg in self.providers.values()]

    def get(self, key: Optional[str]) -> ProviderConfig:
        """
        Safe lookup with resilient fallbacks:
        1) exact key if present,
        2) default_key if present,
        3) first provider if any,
        4) raise clear error.
        """
        if not self.providers:
            self._load()

        if key and key in self.providers:
            return self.providers[key]

        if self.default_key in self.providers:
            return self.providers[self.default_key]

        if self.providers:
            return next(iter(self.providers.values()))

        raise RuntimeError("No providers configured. Check storage/providers.json")

    def read_selected(self) -> str:
        """Return selected key if valid; otherwise a safe fallback."""
        try:
            with open(APP_STATE_PATH, "r", encoding="utf-8") as f:
                k = json.load(f).get("selected_provider")
                if k and k in self.providers:
                    return k
        except Exception:
            pass

        if self.default_key in self.providers:
            return self.default_key
        if self.providers:
            return next(iter(self.providers.keys()))
        return "openai"

    def write_selected(self, key: str):
        """Persist selected provider; ignore unknown keys silently."""
        if key not in self.providers:
            return
        with _lock:
            state = {}
            if os.path.exists(APP_STATE_PATH):
                try:
                    with open(APP_STATE_PATH, "r", encoding="utf-8") as f:
                        state = json.load(f)
                except Exception:
                    state = {}
            state["selected_provider"] = key
            with open(APP_STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)

registry = ProviderRegistry()

