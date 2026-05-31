#!/usr/bin/env bash
set -euo pipefail

mkdir -p modules

# 1) Install conditional sanitizer (minimal, preserves most glyphs)
cat > modules/safe_text.py <<'PY'
"""
Conditional sanitizer for Tk on X11.
- Default: return text unchanged.
- If running under X11 AND text contains risky emoji/non-BMP codepoints,
  replace only those with readable fallbacks to avoid Xlib RenderAddGlyphs crashes.
"""
import os
from typing import Iterable

# quick env probe
_IS_X11 = bool(os.environ.get("DISPLAY")) and not os.environ.get("WAYLAND_DISPLAY")

# fallbacks that still look nice in Tk
FALLBACKS = {
    "\U00002705": "✓",   # ✅  -> plain check
    "\U0000274C": "×",   # ❌  -> multiplication sign
    "\U0001F197": "OK",  # 🆗  ->
    "\U0001F4A1": "💡",  # 💡 stays (BMP on many), keep as-is
    "\U0001F504": "↻",   # 🔄  -> clockwise open circle arrow
    "\U0001F501": "↺",   # 🔁  -> anticlockwise open circle arrow
    "\U0001F7E2": "●",   # 🟢  -> green circle -> filled circle
    "\U0001F534": "●",   # 🔴  -> red circle   -> filled circle
}

def _is_risky_codepoint(cp: int) -> bool:
    # Non-BMP (>= 0x10000) are the usual crashers with color emoji fonts.
    return cp >= 0x10000

def contains_risky(text: str) -> bool:
    return any(_is_risky_codepoint(ord(ch)) for ch in text)

def soften(text: str) -> str:
    # Replace only risky characters; keep BMP glyphs untouched (e.g., ✓ U+2713).
    out = []
    for ch in text:
        cp = ord(ch)
        if _is_risky_codepoint(cp):
            out.append(FALLBACKS.get(ch, "□"))
        else:
            # Strip weird control chars except \n\t
            if cp < 32 and ch not in ("\n", "\t"):
                out.append(" ")
            else:
                out.append(ch)
    return "".join(out)

def sanitize_if_needed(text: str) -> str:
    # Only sanitize on X11 AND text contains risky codepoints; otherwise passthrough.
    if _IS_X11 and contains_risky(text):
        return soften(text)
    return text
PY
echo "✅ Installed modules/safe_text.py"

# 2) Patch ai_interface.py to call sanitize_if_needed ONLY on returned text
AI="modules/ai_interface.py"
cp -f "$AI" "$AI.bak.$(date +%Y%m%d%H%M%S)"

python3 - <<'PY'
import re
p="modules/ai_interface.py"
s=open(p,"r",encoding="utf-8").read()

# add import if missing
if "from modules.safe_text import sanitize_if_needed" not in s:
    s = s.replace("from .provider_registry import registry",
                  "from .provider_registry import registry\nfrom modules.safe_text import sanitize_if_needed")

# wrap all return sites that output text
replacements = [
    (r"return choices\[0\]\[\"message\"\]\.get\(\"content\", \"\"\)",
     "return sanitize_if_needed(choices[0][\"message\"].get(\"content\", \"\"))"),
    (r"return choices\[0\]\.get\(\"text\", \"\"\)",
     "return sanitize_if_needed(choices[0].get(\"text\", \"\"))"),
    (r"return data\.get\(\"generated_text\", \"\"\)",
     "return sanitize_if_needed(data.get(\"generated_text\", \"\"))"),
    (r"return data\[\"message\"\]\[\"content\"\]",
     "return sanitize_if_needed(data[\"message\"][\"content\"])"),
]

for pat, rep in replacements:
    s = re.sub(pat, rep, s)

open(p,"w",encoding="utf-8").write(s)
print("✅ Patched ai_interface.py to sanitize replies only when needed.")
PY

cat <<'MSG'

Done.

What changed:
- New helper modules/safe_text.py detects X11 + risky emoji and replaces just those
  glyphs with readable fallbacks (e.g., ✅ -> ✓), otherwise leaves text untouched.
- ai_interface.py now runs sanitize_if_needed() on AI replies before Tk sees them.
  No change to your UI code required.

Tips:
- If you want to be extra cautious on this machine, you can launch with
    XLIB_SKIP_ARGB_VISUALS=1 python3 main.py
  (It often prevents the XRender crash path entirely.)
MSG

