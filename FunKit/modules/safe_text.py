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
