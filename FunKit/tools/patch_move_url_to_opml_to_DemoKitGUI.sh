#!/usr/bin/env bash
set -euo pipefail

GUI="modules/gui_tkinter.py"
[ -f "$GUI" ] || { echo "❌ $GUI not found"; exit 1; }

ts() { date +"%Y%m%d-%H%M%S"; }
cp -p "$GUI" "$GUI.bak.$(ts)"

python3 - "$GUI" <<'PY'
import re, sys
p=sys.argv[1]
s=open(p,'r',encoding='utf-8',errors='ignore').read()

# --- helpers ---
def extract_method_from_class(src, class_name, meth_names):
    """
    Find first def with any name in meth_names INSIDE class class_name.
    Return (new_src, method_text) removing it from original place.
    """
    # Find class block start
    c = re.search(rf"(^class\s+{class_name}\b.*?:\s*\n)", src, flags=re.M)
    if not c:
        return src, None
    start = c.end()
    # Find next class or EOF to get class body slice
    nxt = re.search(r"^class\s+\w+\b.*?:\s*\n", src[start:], flags=re.M)
    body_end = start + (nxt.start() if nxt else len(src)-start)
    body = src[start:body_end]
    # Look for method defs at one indent level
    m = re.search(rf"(^[ \t]+def\s+({'|'.join(map(re.escape,meth_names))})\s*\(self[^\)]*\)\s*:[\s\S]*?)(?=^\S|^class\s|\Z)", body, flags=re.M)
    if not m:
        return src, None
    method = m.group(1)
    # Remove it from the class body
    new_body = body[:m.start()] + body[m.end():]
    new_src  = src[:start] + new_body + src[body_end:]
    return new_src, method

def ensure_method_in_class(src, class_name, method_block):
    if not method_block:
        return src
    # Normalize name to _open_url_to_opml
    method_block = re.sub(r"def\s+open_url_to_opml\s*\(", "def _open_url_to_opml(", method_block, count=1)
    # Ensure imports inside are present and strings use double quotes consistently
    # Insert at top of class body, right after class header
    c = re.search(rf"(^class\s+{class_name}\b.*?:\s*\n)", src, flags=re.M)
    if not c:
        return src
    insert_at = c.end()
    # Avoid duplicate if already present
    if re.search(r"\bdef\s+_open_url_to_opml\s*\(\s*self\s*\)\s*:", src):
        return src
    return src[:insert_at] + method_block + ("\n" if not method_block.endswith("\n") else "") + src[insert_at:]

def ensure_debug_wrapper(src, class_name):
    if re.search(r"\bdef\s+_debug_url_to_opml\s*\(\s*self\s*\)\s*:", src):
        return src
    block = (
        "    def _debug_url_to_opml(self):\n"
        "        import traceback\n"
        "        from tkinter import messagebox\n"
        "        try:\n"
        "            self._open_url_to_opml()\n"
        "        except Exception:\n"
        "            tb = traceback.format_exc()\n"
        "            print('[URL→OPML] ERROR:', tb)\n"
        "            try:\n"
        "                messagebox.showerror('URL → OPML failed', tb)\n"
        "            except Exception:\n"
        "                pass\n\n"
    )
    c = re.search(rf"(^class\s+{class_name}\b.*?:\s*\n)", src, flags=re.M)
    if not c: return src
    return src[:c.end()] + block + src[c.end():]

def rebind_menu_to_lambda(src):
    # Replace any existing command=... for the URL→OPML item with a lambda that calls the debug wrapper
    patterns = [
        r"(add_command\([^)]*label\s*=\s*['\"]URL\s*(?:→|to)\s*OPML['\"][^)]*command\s*=\s*)([^)\n]+)",
        r"(add_command\([^)]*label\s*=\s*['\"]URL\s*→\s*Import\s+as\s+OPML['\"][^)]*command\s*=\s*)([^)\n]+)",
    ]
    for pat in patterns:
        src = re.sub(pat, r"\1lambda s=self: s._debug_url_to_opml()", src, flags=re.I)
    # Remove any accidental double-closing parens
    src = src.replace("s._debug_url_to_opml()))", "s._debug_url_to_opml())")
    return src

# 1) Pull method from ProviderSwitcher_DEPRECATED (or ProviderSwitcher) if present
s, moved = extract_method_from_class(s, "ProviderSwitcher_DEPRECATED", ["open_url_to_opml","_open_url_to_opml"])
if not moved:
    s, moved = extract_method_from_class(s, "ProviderSwitcher", ["open_url_to_opml","_open_url_to_opml"])

# 2) Ensure it lives on DemoKitGUI
s = ensure_method_in_class(s, "DemoKitGUI", moved)

# 3) Ensure debug wrapper on DemoKitGUI
s = ensure_debug_wrapper(s, "DemoKitGUI")

# 4) Rebind menu entry to call the debug wrapper via lambda
s = rebind_menu_to_lambda(s)

open(p,'w',encoding='utf-8').write(s)
print("✅ Moved URL→OPML handler into DemoKitGUI and rebound the menu.")
PY

echo "🎉 Done. Launch with: python3 main.py"

