#!/usr/bin/env bash
set -euo pipefail

# --- paths
GUI="gui_tkinter.py"
MOD="modules"
STOR="storage"

[ -f "$GUI" ] || { echo "❌ $GUI not found (run from FunKit root)"; exit 1; }
mkdir -p "$MOD" "$STOR"

# --- 1) Ensure providers.json has Baseten and make it default
python3 - <<'PY'
import json, os, sys, os.path as p
P = "storage/providers.json"
data = {"default":"baseten","providers":[]}
if p.exists(P):
    with open(P,"r",encoding="utf-8") as f:
        try: data = json.load(f)
        except Exception: data = {"default":"baseten","providers":[]}

# normalize structure
data.setdefault("default","baseten")
data.setdefault("providers",[])

# pull optional model from env
base_model = os.environ.get("BASETEN_MODEL","YOUR_BASETEN_MODEL")

# ensure baseten provider exists/updated
found_b = False
for pr in data["providers"]:
    if pr.get("key") == "baseten":
        pr["label"]    = pr.get("label","Baseten")
        pr["model"]    = pr.get("model", base_model)
        pr["endpoint"] = pr.get("endpoint","https://app.baseten.co/models")
        pr["env_key"]  = "BASETEN_API_KEY"
        pr.setdefault("extras",{})
        found_b = True
        break
if not found_b:
    data["providers"].insert(0,{
        "key":"baseten",
        "label":"Baseten",
        "model": base_model,
        "endpoint":"https://app.baseten.co/models",
        "env_key":"BASETEN_API_KEY",
        "extras":{}
    })

# keep a sane local_llama entry but DO NOT set it default
has_llama = any(pr.get("key")=="local_llama" for pr in data["providers"])
if not has_llama:
    data["providers"].append({
        "key":"local_llama",
        "label":"Local (llama.cpp)",
        "model":"mistral-7b-instruct",
        "endpoint":"http://127.0.0.1:8081",
        "env_key": None,
        "extras":{"timeout":600}
    })

# set default to baseten
data["default"] = "baseten"

with open(P,"w",encoding="utf-8") as f:
    json.dump(data,f,indent=2)
print("✅ storage/providers.json -> default=baseten")
PY

# --- 2) Persist current selection to baseten
cat > "$STOR/app_state.json" <<'JSON'
{ "selected_provider": "baseten" }
JSON
echo "✅ storage/app_state.json -> selected_provider=baseten"

# --- 3) Install ProviderDropdown widget (idempotent)
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
    Optionally calls status_cb(label, model) when selection changes.
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

        # fire once to populate status/ticker
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
echo "✅ modules/provider_dropdown.py installed"

# --- 4) Patch gui_tkinter.py to use ProviderDropdown instead of ProviderSwitcher
cp -f "$GUI" "$GUI.bak.$(date +%Y%m%d%H%M%S)"

# add imports if missing
grep -q "from modules.provider_dropdown import ProviderDropdown" "$GUI" || \
  sed -i '1i from modules.provider_dropdown import ProviderDropdown' "$GUI"
grep -q "from modules.provider_registry import registry" "$GUI" || \
  sed -i '1i from modules.provider_registry import registry' "$GUI"
grep -q "from modules.ai_interface import AIInterface" "$GUI" || \
  sed -i '1i from modules.ai_interface import AIInterface' "$GUI"

# rename old class so it no longer collides/gets constructed
sed -i 's/^class[[:space:]]\+ProviderSwitcher(/class ProviderSwitcher_DEPRECATED(/' "$GUI"

# replace constructor calls
sed -i 's/ProviderSwitcher(/ProviderDropdown(/g' "$GUI"

echo "✅ $GUI patched to use ProviderDropdown (old class renamed to ProviderSwitcher_DEPRECATED)"

# --- 5) Friendly reminder about API key
echo
echo "NOTE: Ensure your Baseten API key is set in the environment before launching:"
echo "      export BASETEN_API_KEY=xxxxxxxxxxxxxxxx"
echo
echo "All set. Start FunKit:"
echo "  python3 main.py"

