from __future__ import annotations
import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    api_key: str
    model: str
    chat_path: str = "/v1/chat/completions"

LOCAL = Provider(
    name="Local (Mistral)",
    base_url=os.getenv("PIKIT_OPENAI_BASE_URL", "http://localhost:8081/v1").rstrip("/"),
    api_key=os.getenv("PIKIT_OPENAI_API_KEY", "funkit-local"),
    model=os.getenv("PIKIT_MODEL_NAME", "mistral-7b-instruct-v0.2.Q4_K_M.gguf"),
)

OPENAI = Provider(
    name="OpenAI",
    base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
    api_key=os.getenv("OPENAI_API_KEY", ""),
    model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
)

_REGISTRY = {
    LOCAL.name: LOCAL,
    OPENAI.name: OPENAI,
}

_current = os.getenv("PIKIT_PROVIDER", LOCAL.name)

def list_labels() -> list[str]:
    return list(_REGISTRY.keys())

def get_current_provider() -> Provider:
    global _current
    if _current not in _REGISTRY:
        _current = LOCAL.name
    return _REGISTRY[_current]

def set_current_provider(label: str) -> Provider:
    global _current
    if label in _REGISTRY:
        _current = label
    return get_current_provider()

def resolve_endpoint() -> tuple[str, dict]:
    p = get_current_provider()
    url = f"{p.base_url}{p.chat_path}"
    headers = {"Authorization": f"Bearer {p.api_key}", "Content-Type": "application/json"}
    return url, headers

def model_name() -> str:
    return get_current_provider().model

def whoami() -> str:
    p = get_current_provider()
    return f"{p.name} → {p.base_url} · model={p.model}"
