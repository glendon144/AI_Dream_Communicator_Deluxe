#!/usr/bin/env bash
set -euo pipefail

GUI="modules/gui_tkinter.py"
MOD="modules"
ST="storage"

[ -f "$GUI" ] || { echo "❌ $GUI not found (expected modules/gui_tkinter.py)."; exit 1; }

# 0) Backup
cp -f "$GUI" "$GUI.bak.$(date +%Y%m%d%H%M%S)"

# 1) Drop legacy provider_switch import lines (any form)
sed -i '/from[[:space:]]\+modules\.provider_switch[[:space:]]\+import/d' "$GUI"

# 2) Ensure JSON-backed dropdown + registry imports exist
grep -q "from modules.provider_dropdown import ProviderDropdown" "$GUI" || \
  sed -i '1i from modules.provider_dropdown import ProviderDropdown' "$GUI"
grep -q "from modules.provider_registry import registry" "$GUI" || \
  sed -i '1i from modules.provider_registry import registry' "$GUI"

# 3) Rename old class to DEPRECATED (don’t delete in case other code refers to it)
# (only if it still exists un-renamed)
if grep -qE '^class[[:space:]]+ProviderSwitcher\(' "$GUI"; then
  sed -i 's/^class[[:space:]]\+ProviderSwitcher(/class ProviderSwitcher_DEPRECATED(/' "$GUI"
fi

# 4) Replace first instantiation of ProviderSwitcher(...) with ProviderDropdown(...)
#    (your grep showed one at ~line 341)
if grep -q "ProviderSwitcher(" "$GUI"; then
  sed -i '0,/ProviderSwitcher(/s//ProviderDropdown(/' "$GUI"
fi

# 5) If there’s no ProviderDropdown instance yet, insert one on the top bar
if ! grep -q "ProviderDropdown(" "$GUI"; then
  awk '
    BEGIN{ins=0}
    /self\.topbar[[:space:]]*=/ && ins==0 {
      print
      print "        # Provider dropdown (JSON-backed; reads providers.json, writes app_state.json)"
      print "        try:"
      print "            self.provider_dd = ProviderDropdown(self.topbar, status_cb=lambda lbl, mdl: getattr(self, \"set_ticker_text\", lambda *_: None)(f\"{lbl} • {mdl}\"))"
      print "            self.provider_dd.grid(row=0, column=0, sticky=\"w\")"
      print "        except Exception as _e:"
      print "            print(\"[WARN] Provider dropdown init failed:\", _e)"
      ins=1; next
    }
    { print }
  ' "$GUI" > "$GUI.tmp" && mv "$GUI.tmp" "$GUI"
fi

# 6) Clean up any auto-added shim blocks, if they exist
sed -i '/# --- BEGIN: provider dropdown (auto-added) ---/,/# --- END: provider dropdown (auto-added) ---/d' "$GUI" || true

# 7) (Optional) Make the currently selected provider "baseten" once to avoid timeouts.
#     This does NOT change providers.json defaults; it only writes app_state.json.
mkdir -p "$ST"
python3 - <<'PY'
import json, os
p = os.path.join("storage","app_state.json")
state = {"selected_provider": "baseten"}
try:
    if os.path.exists(p):
        with open(p,"r",encoding="utf-8") as f:
            cur = json.load(f)
        # don’t clobber if user already picked something else
        if cur.get("selected_provider"):
            state = cur
except Exception:
    pass
with open(p,"w",encoding="utf-8") as f:
    json.dump(state, f, indent=2)
print("↪️  storage/app_state.json:", state)
PY

echo "✅ Patched modules/gui_tkinter.py to use ProviderDropdown."

echo
echo "Quick sanity checks:"
echo "1) Remaining ProviderSwitcher references:"
grep -RIn --exclude-dir=.git "ProviderSwitcher(" modules || true
echo "2) Run and test:"
echo "   python3 - <<'PY'"
echo "from modules.provider_registry import registry; print('Default:', registry.default_key); print('Selected:', registry.read_selected()); print('Options:', registry.list_labels())"
echo "PY"

