# save as fix_provider_status_cb.sh and run from the FunKit root
#!/usr/bin/env bash
set -euo pipefail

PD="modules/provider_dropdown.py"
GUI="modules/gui_tkinter.py"

[ -f "$PD" ] || { echo "❌ $PD not found"; exit 1; }
[ -f "$GUI" ] || { echo "❌ $GUI not found"; exit 1; }

cp -f "$PD" "$PD.bak.$(date +%Y%m%d%H%M%S)"
cp -f "$GUI" "$GUI.bak.$(date +%Y%m%d%H%M%S)"

# 1) ProviderDropdown: make _notify_status handle 1-arg or 2-arg callbacks
python3 - <<'PY'
import re, io
p="modules/provider_dropdown.py"
s=open(p,"r",encoding="utf-8").read()
pat = r"def _notify_status\(self\):\n\s*if not self\.status_cb:\s*return\n\s*cfg = registry\.get\(self\.current_key\(\)\)\n\s*self\.status_cb\(cfg\.label, cfg\.model\)\n"
if re.search(pat, s):
    s = re.sub(pat,
               "def _notify_status(self):\n"
               "        if not self.status_cb:\n"
               "            return\n"
               "        cfg = registry.get(self.current_key())\n"
               "        try:\n"
               "            self.status_cb(cfg.label, cfg.model)\n"
               "        except TypeError:\n"
               "            # Fallback for 1-arg callbacks like DemoKitGUI.status(msg)\n"
               "            self.status_cb(f\"{cfg.label} • {cfg.model}\")\n",
               s)
else:
    # if structure differs, append a safe version
    if "def _notify_status(self):" not in s:
        s += ("\n    def _notify_status(self):\n"
              "        if not self.status_cb:\n"
              "            return\n"
              "        cfg = registry.get(self.current_key())\n"
              "        try:\n"
              "            self.status_cb(cfg.label, cfg.model)\n"
              "        except TypeError:\n"
              "            self.status_cb(f\"{cfg.label} • {cfg.model}\")\n")
open(p,"w",encoding="utf-8").write(s)
print("✅ Patched provider_dropdown._notify_status to support 1-arg or 2-arg callbacks.")
PY

# 2) GUI: pass a wrapper lambda so we always send a single string to the status line/ticker
# Replace: ProviderDropdown(self.topbar, status_cb=getattr(self, "status", None))
# With:    ProviderDropdown(self.topbar, status_cb=lambda lbl, mdl: getattr(self, "set_ticker_text", self.status)(f"{lbl} • {mdl}"))
python3 - <<'PY'
import re
p="modules/gui_tkinter.py"
s=open(p,"r",encoding="utf-8").read()
s = re.sub(
    r"ProviderDropdown\(self\.topbar,\s*status_cb=getattr\(self,\s*\"status\",\s*None\)\)",
    "ProviderDropdown(self.topbar, status_cb=lambda lbl, mdl: getattr(self, 'set_ticker_text', self.status)(f\"{lbl} • {mdl}\"))",
    s
)
open(p,"w",encoding="utf-8").write(s)
print("✅ Updated modules/gui_tkinter.py to pass a 1-arg wrapper to the ticker/status.")
PY

echo "All set. Try: python3 main.py"

