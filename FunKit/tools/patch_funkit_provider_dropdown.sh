#!/usr/bin/env bash
set -euo pipefail

# 0) Paths
GUI_FILE="gui_tkinter.py"
MOD_DIR="modules"
STORAGE_DIR="storage"

# 1) Safety checks
[ -f "$GUI_FILE" ] || { echo "❌ $GUI_FILE not found in current dir"; exit 1; }
mkdir -p "$MOD_DIR" "$STORAGE_DIR"

# 2) Install provider_dropdown.py (paste from the message above)
cat > "$MOD_DIR/provider_dropdown.py" <<'PY'
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
        self.cbo = ttk.Combobox(self, state="readonly",
                                width=max(12, max((len(lbl) for _, lbl in self._labels), default=12)),
                                values=[lbl for _, lbl in self._labels],
                                textvariable=self.var)
        init_key = registry.read_selected()
        init_label = self._label_by_key.get(init_key, (self._labels[0][1] if self._labels else "OpenAI"))
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

# 3) Backup GUI
cp -f "$GUI_FILE" "$GUI_FILE.bak.$(date +%Y%m%d%H%M%S)"

# 4) Ensure imports
# Add imports for registry/AIInterface and our new ProviderDropdown if missing
grep -q "from modules.provider_registry import registry" "$GUI_FILE" || \
  sed -i '1i from modules.provider_registry import registry' "$GUI_FILE"
grep -q "from modules.ai_interface import AIInterface" "$GUI_FILE" || \
  sed -i '1i from modules.ai_interface import AIInterface' "$GUI_FILE"
grep -q "from modules.provider_dropdown import ProviderDropdown" "$GUI_FILE" || \
  sed -i '1i from modules.provider_dropdown import ProviderDropdown' "$GUI_FILE"

# 5) Deprecate old ProviderSwitcher class (don’t delete user code; just rename class)
sed -i 's/^class[[:space:]]\+ProviderSwitcher(/class ProviderSwitcher_DEPRECATED(/' "$GUI_FILE"

# 6) Switch usages to new dropdown
sed -i 's/ProviderSwitcher(/ProviderDropdown(/g' "$GUI_FILE"

echo "✅ Patched $GUI_FILE to use ProviderDropdown. Old class renamed to ProviderSwitcher_DEPRECATED."
echo "   If you had code depending on ProviderSwitcher methods, it will now call the new widget."

