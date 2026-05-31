# modules/ai_singleton.py
from __future__ import annotations
from modules.ai_interface import AIInterface

# Single, shared instance used across GUI and processor
_AI = AIInterface()

def get_ai() -> AIInterface:
    return _AI



def set_provider_global(provider: str):
    _AI.set_provider(provider)
