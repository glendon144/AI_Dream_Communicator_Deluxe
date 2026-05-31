#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-.}"
MOD="$ROOT/modules"
AI="$MOD/ai_interface.py"
GUI="$MOD/gui_tkinter.py"
SW="$MOD/provider_switch.py"
DATE="$(date +%Y%m%d-%H%M%S)"

need() { command -v "$1" >/dev/null 2>&1 || { echo "Missing $1"; exit 1; }; }
need python3
need awk
need sed

echo "[*] Working root: $ROOT"
test -d "$MOD" || { echo "ERROR: ${MOD} not found"; exit 1; }

# -------------------------------------------------------------------
# 1) Write provider_switch.py (always overwrite—small, single source)
# -------------------------------------------------------------------
echo "[*] Writing $SW"
install -d "$MOD"
cat > "$SW" <<'PY'
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
PY

# -------------------------------------------------------------------
# 2) Patch modules/ai_interface.py
#    - add imports (once)
#    - add ping() helper if missing
#    - add provider-aware POST helper if missing
# -------------------------------------------------------------------
if [[ -f "$AI" ]]; then
  cp "$AI" "${AI}.bak.${DATE}"
  echo "[*] Backed up $AI -> ${AI}.bak.${DATE}"

  # a) ensure import
  if ! grep -q "from modules.provider_switch import" "$AI"; then
    awk '
      BEGIN{done=0}
      /^from|^import/ {print; next}
      { if(!done){ print "from modules.provider_switch import resolve_endpoint, model_name, whoami"; done=1 } print }
    ' "$AI" > "${AI}.tmp.${DATE}"
    mv "${AI}.tmp.${DATE}" "$AI"
    echo "[*] Injected provider_switch import"
  else
    echo "[=] provider_switch import already present"
  fi

  # b) add ping() if missing
  if ! grep -q "def ping(self)" "$AI"; then
    cat >> "$AI" <<'PY'

# --- BEGIN: provider ping helper (auto-added) ---
import requests as _req  # safe alias to avoid collisions

class _AIInterfacePingMixin:
    def ping(self) -> dict:
        base, headers = resolve_endpoint()
        models_url = base.rsplit("/chat/completions", 1)[0] + "/models"
        r = _req.get(models_url, headers=headers, timeout=10)
        r.raise_for_status()
        return r.json()
# --- END: provider ping helper (auto-added) ---
PY
    echo "[*] Added ping() helper (mixin)"
  else
    echo "[=] ping() already present"
  fi

  # c) add provider-aware POST helper if missing
  if ! grep -q "def _post_chat_with_provider(" "$AI"; then
    cat >> "$AI" <<'PY'

# --- BEGIN: provider-aware POST helper (auto-added) ---
def _post_chat_with_provider(session, messages, temperature=0.7, max_tokens=512, **kwargs):
    """
    Centralized POST using provider_switch. Returns parsed JSON.
    session: requests.Session()
    """
    url, headers = resolve_endpoint()
    payload = {
        "model": model_name(),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens
    }
    # pass through llama.cpp extras if provided (n_threads, top_p, etc.)
    for k in ("n_threads","top_p","presence_penalty","frequency_penalty","stop","stream"):
        if k in kwargs and kwargs[k] is not None:
            payload[k] = kwargs[k]
    r = session.post(url, headers=headers, json=payload, timeout=kwargs.get("timeout", 180))
    r.raise_for_status()
    return r.json()
# --- END: provider-aware POST helper (auto-added) ---
PY
    echo "[*] Added _post_chat_with_provider() helper"
  else
    echo "[=] _post_chat_with_provider() already present"
  fi

else
  echo "WARNING: $AI not found. Skipping ai_interface patch."
fi

# -------------------------------------------------------------------
# 3) Patch modules/gui_tkinter.py
#    - add dropdown methods (once)
#    - auto-wire into top bar if we can detect a top frame
# -------------------------------------------------------------------
if [[ -f "$GUI" ]]; then
  cp "$GUI" "${GUI}.bak.${DATE}"
  echo "[*] Backed up $GUI -> ${GUI}.bak.${DATE}"

  # a) add methods if missing
  if ! grep -q "_add_provider_dropdown" "$GUI"; then
    cat >> "$GUI" <<'PY'

# --- BEGIN: provider dropdown (auto-added) ---
try:
    from tkinter import ttk, StringVar
    from modules.provider_switch import list_labels as _ps_list_labels, set_current_provider as _ps_set_current, get_current_provider as _ps_get_current
except Exception:
    ttk = None

def _funkit_status(self, msg: str):
    try:
        self.status_var.set(msg)  # if you already have a status bar
    except Exception:
        try:
            self._update_status(msg)  # alt naming in some forks
        except Exception:
            print(msg)

def _on_provider_changed(self, event=None):
    try:
        label = self.provider_var.get()
        p = _ps_set_current(label)
        try:
            # optional health check if AIInterface exists
            from modules.ai_interface import AIInterface
            # if AIInterface is a class, instantiate and try ping()
            try:
                ai = AIInterface()  # may or may not need args in your fork
                if hasattr(ai, "ping"):
                    ai.ping()
            except Exception:
                pass
        except Exception:
            pass
        _funkit_status(self, f"Provider: {p.name} ✓")
    except Exception as e:
        _funkit_status(self, f"Provider switch error: {e}")

def _add_provider_dropdown(self, parent_frame):
    if ttk is None:
        print("[FunKit] ttk not available; skipping provider dropdown")
        return
    try:
        self.provider_var = StringVar(value=_ps_get_current().name)
        self.provider_dd = ttk.Combobox(
            parent_frame,
            textvariable=self.provider_var,
            values=_ps_list_labels(),
            state="readonly",
            width=22
        )
        self.provider_dd.bind("<<ComboboxSelected>>", self._on_provider_changed if hasattr(self, "_on_provider_changed") else _on_provider_changed)
        self.provider_dd.pack(side="right", padx=8)
    except Exception as e:
        print("[FunKit] Failed to create provider dropdown:", e)

# monkey-attach to class if DemoKitGUI exists
try:
    # Compatible with multiple naming variants
    import inspect
    glb = globals()
    for _cls_name in ("DemoKitGUI","DemokitGUI","App"):
        if _cls_name in glb and inspect.isclass(glb[_cls_name]):
            cls = glb[_cls_name]
            if not hasattr(cls, "_add_provider_dropdown"):
                setattr(cls, "_add_provider_dropdown", _add_provider_dropdown)
            if not hasattr(cls, "_on_provider_changed"):
                setattr(cls, "_on_provider_changed", _on_provider_changed)
            if not hasattr(cls, "_funkit_status"):
                setattr(cls, "_funkit_status", _funkit_status)
            # try to auto-inject into a common topbar builder if present
            for cand in ("build_ui","_build_ui","_create_top_bar","_create_toolbar"):
                if hasattr(cls, cand):
                    # wrap once
                    if not hasattr(cls, "__provider_dd_wrapped__"):
                        orig = getattr(cls, cand)
                        def wrapper(self, *a, **kw):
                            out = orig(self, *a, **kw)
                            # find a reasonable parent frame: try self.topbar or self.root
                            parent = getattr(self, "topbar", None) or getattr(self, "toolbar", None) or getattr(self, "root", None)
                            try:
                                self._add_provider_dropdown(parent)
                            except Exception:
                                pass
                            return out
                        setattr(cls, cand, wrapper)
                        setattr(cls, "__provider_dd_wrapped__", True)
            break
except Exception as _e:
    print("[FunKit] Provider dropdown hook warning:", _e)
# --- END: provider dropdown (auto-added) ---
PY
    echo "[*] Added provider dropdown methods to $GUI"
  else
    echo "[=] Provider dropdown already present"
  fi

else
  echo "WARNING: $GUI not found. Skipping GUI patch."
fi

# -------------------------------------------------------------------
# 4) Post-run tips
# -------------------------------------------------------------------
cat <<'NOTE'

[✓] Provider toggle installed.

Environment overrides you can set:
  export PIKIT_PROVIDER="Local (Mistral)"
  export PIKIT_OPENAI_BASE_URL=http://localhost:8081/v1
  export PIKIT_OPENAI_API_KEY=funkit-local
  export PIKIT_MODEL_NAME="mistral-7b-instruct-v0.2.Q4_K_M.gguf"

Or switch to OpenAI:
  export PIKIT_PROVIDER="OpenAI"
  export OPENAI_API_KEY=sk-...

If your GUI’s top bar has a different construction path, the script
wrapped common builders (build_ui/_build_ui/_create_top_bar/_create_toolbar).
If you don’t see the dropdown, call `self._add_provider_dropdown(<your_topbar_frame>)`
after you create the top bar.

Backups:
  - ${AI}.bak.${DATE}
  - ${GUI}.bak.${DATE}

Run:
  python3 main.py
Then try switching providers from the new dropdown.
NOTE

