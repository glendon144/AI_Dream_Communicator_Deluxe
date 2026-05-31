#!/usr/bin/env bash
set -euo pipefail

GUI="gui_tkinter.py"
MOD="modules"
ST="storage"
AI="$MOD/ai_interface.py"

[ -f "$GUI" ] || { echo "❌ $GUI not found. Run from FunKit root."; exit 1; }
mkdir -p "$MOD" "$ST"

backup() { cp -f "$1" "$1.bak.$(date +%Y%m%d%H%M%S)"; }

echo "==> Backing up files"
backup "$GUI"
[ -f "$AI" ] && backup "$AI"

echo "==> Installing ProviderDropdown"
cat > "$MOD/provider_dropdown.py" <<'PY'
from __future__ import annotations
import tkinter as tk
from tkinter import ttk
from typing import Optional, Callable
from .provider_registry import registry

class ProviderDropdown(ttk.Frame):
    """
    JSON-backed provider chooser for FunKit.
    Reads/writes storage/providers.json + storage/app_state.json via registry.
    Calls status_cb(label, model) on change (if provided).
    """
    def __init__(self, parent, status_cb: Optional[Callable[[str, str], None]] = None, **kwargs):
        super().__init__(parent, **kwargs)
        self.status_cb = status_cb

        ttk.Label(self, text="Provider:").grid(row=0, column=0, padx=(0, 6), pady=4, sticky="w")

        self._labels = registry.list_labels()  # [(key, label), ...]
        self._label_by_key = {k: lbl for k, lbl in self._labels}
        self._key_by_label = {lbl: k for k, lbl in self._labels}

        self.var = tk.StringVar()
        width = max(12, max((len(lbl) for _, lbl in self._labels), default=12))
        self.cbo = ttk.Combobox(self, state="readonly", width=width,
                                values=[lbl for _, lbl in self._labels],
                                textvariable=self.var)

        init_key = registry.read_selected()
        init_label = self._label_by_key.get(init_key, (self._labels[0][1] if self._labels else "Baseten"))
        self.var.set(init_label)
        self.cbo.grid(row=0, column=1, padx=(0, 8), pady=4, sticky="ew")
        self.grid_columnconfigure(1, weight=1)
        self.cbo.bind("<<ComboboxSelected>>", self._on_changed)

        self._notify_status()

    def current_key(self) -> str:
        return self._key_by_label.get(self.var.get(), registry.read_selected())

    def current_config(self):
        return registry.get(self.current_key())

    def _on_changed(self, _evt=None):
        key = self.current_key()
        registry.write_selected(key)
        self._notify_status()

    def _notify_status(self):
        if not self.status_cb:
            return
        cfg = registry.get(self.current_key())
        self.status_cb(cfg.label, cfg.model)
PY

echo "==> Forcing Baseten as default/selected"
cat > "$ST/providers.json" <<'JSON'
{
  "default": "baseten",
  "providers": [
    {
      "key": "baseten",
      "label": "Baseten",
      "model": "YOUR_BASETEN_MODEL",
      "endpoint": "https://app.baseten.co/models",
      "env_key": "BASETEN_API_KEY",
      "extras": {}
    },
    {
      "key": "local_llama",
      "label": "Local (llama.cpp)",
      "model": "mistral-7b-instruct",
      "endpoint": "http://127.0.0.1:8081",
      "env_key": null,
      "extras": { "timeout": 600 }
    },
    {
      "key": "openai",
      "label": "OpenAI (GPT-4o)",
      "model": "gpt-4o-mini",
      "endpoint": null,
      "env_key": "OPENAI_API_KEY",
      "extras": {}
    }
  ]
}
JSON
echo '{ "selected_provider": "baseten" }' > "$ST/app_state.json"

echo "==> Patching AIInterface to honor selected provider + robust routes"
python3 - "$AI" <<'PY'
import sys,re,io,os,json
p=sys.argv[1]
s=open(p,"r",encoding="utf-8").read()

# ensure it imports registry
if "from .provider_registry import registry" not in s:
    s = s.replace("from __future__ import annotations\n", "from __future__ import annotations\nfrom .provider_registry import registry\n")

# make __init__ default to selected provider if None
s = re.sub(r"class AIInterface\([^)]+\):\s+def __init__\(self, provider_key:.*?\):\s+self\.provider = registry\.get\(provider_key\)",
           "class AIInterface:\n    def __init__(self, provider_key: str | None = None):\n        if provider_key is None:\n            provider_key = registry.read_selected()\n        self.provider = registry.get(provider_key)", s, flags=re.S)

# candidate routes should try llama.cpp first, then v1/chat/...
if "def _candidate_routes" in s:
    s = re.sub(r"def _candidate_routes\(self\):[\s\S]*?return\s*\[[\s\S]*?\]\n",
               ("def _candidate_routes(self):\n"
                "    base = (self.provider.endpoint or '').rstrip('/')\n"
                "    if self.provider.key == 'openai':\n"
                "        return ['https://api.openai.com/v1/chat/completions']\n"
                "    return [\n"
                "        f\"{base}/chat/completions\",      # llama.cpp\n"
                "        f\"{base}/v1/chat/completions\",   # vLLM/LM Studio/Ollama compat\n"
                "        f\"{base}/v1/completions\",        # rare shims\n"
                "    ]\n"), s)

# add query/complete wrappers if missing
if "def query(self," not in s:
    s += (
        "\n    # ---- Back-compat wrappers ----\n"
        "    def query(self, prompt: str, *, system: str = 'You are a helpful assistant.', max_tokens: int = 512, temperature: float = 0.7) -> str:\n"
        "        messages=[{'role':'system','content':system},{'role':'user','content':prompt}]\n"
        "        return self.chat(messages, temperature=temperature, max_tokens=max_tokens)\n"
        "    def complete(self, prompt: str, *, max_tokens: int = 512, temperature: float = 0.7) -> str:\n"
        "        return self.query(prompt, system='You are a helpful assistant.', max_tokens=max_tokens, temperature=temperature)\n"
    )

open(p,"w",encoding="utf-8").write(s)
print('AIInterface patched.')
PY

echo "==> Rewiring gui_tkinter.py to drop provider_switch and use ProviderDropdown"
# 1) remove old import(s)
sed -i '/from modules.provider_switch import/d' "$GUI"

# 2) add needed imports
grep -q "from modules.provider_dropdown import ProviderDropdown" "$GUI" || \
  sed -i '1i from modules.provider_dropdown import ProviderDropdown' "$GUI"
grep -q "from modules.provider_registry import registry" "$GUI" || \
  sed -i '1i from modules.provider_registry import registry' "$GUI"

# 3) rename class if it still exists (avoid conflicts)
sed -i 's/^class[[:space:]]\+ProviderSwitcher(/class ProviderSwitcher_DEPRECATED(/' "$GUI"

# 4) replace first instantiation of ProviderSwitcher with ProviderDropdown
if grep -q "ProviderSwitcher(" "$GUI"; then
  sed -i '0,/ProviderSwitcher(/s//ProviderDropdown(/' "$GUI"
fi

# 5) ensure a working dropdown is present even if no switcher was found:
#    insert after first occurrence of "self.topbar"
if ! grep -q "ProviderDropdown(" "$GUI"; then
  awk '
    BEGIN{ins=0}
    /self\.topbar/ && ins==0 { print; print "        # Provider dropdown (JSON-backed)"; print "        self.provider_dd = ProviderDropdown(self.topbar, status_cb=lambda lbl,mdl: getattr(self, '\''set_ticker_text'\'', lambda *_: None)(f\"{lbl} • {mdl}\"))"; print "        self.provider_dd.grid(row=0, column=0, sticky=\"w\")"; ins=1; next }
    { print }
  ' "$GUI" > "$GUI.tmp" && mv "$GUI.tmp" "$GUI"
fi

# 6) remove any old auto-added block markers if present
sed -i '/# --- BEGIN: provider dropdown (auto-added) ---/,/# --- END: provider dropdown (auto-added) ---/d' "$GUI"

echo
echo "✅ Done."
echo "• Default/selected provider set to Baseten."
echo "• Dropdown now JSON-backed; status ticker updates to \"Provider • Model\" when changed."
echo
echo "Before launching, ensure your Baseten env is set:"
echo "  export BASETEN_API_KEY=...    # required"
echo "  export BASETEN_MODEL=...      # optional: overrides model in providers.json"
echo
echo "Run: python3 main.py"

