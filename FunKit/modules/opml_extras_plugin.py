# modules/opml_extras_plugin.py
# v2.1 — OPML helpers + provider-aware engine glue for FunKit/DemoKit

from __future__ import annotations

import re
import sys
import html
import codecs
from typing import Callable, Optional, Tuple

# --- Tk / UI imports kept optional so this module can be imported headless ---
try:
    import tkinter as tk
    from tkinter import ttk, messagebox
except Exception:  # headless import
    tk = None
    ttk = None
    messagebox = None

# --- Provider switch (optional; tolerate absence) ---
try:
    # Primary path used by your stack
    from modules.provider_switch import resolve_endpoint, model_name, whoami  # noqa: F401
except Exception:
    resolve_endpoint = None
    model_name = lambda: "unknown"       # noqa: E731
    whoami = lambda: "unknown-provider"  # noqa: E731

# --- Optional AI ping (used by banner/provider checks) ---
try:
    from modules.ai_interface import AIInterface  # has robust .query/.stream and may include .ping
except Exception:
    AIInterface = None  # type: ignore


# ============================================================================
# Public helpers expected by gui_tkinter.py
#   - _decode_bytes_best(b) -> str
#   - _resolve_engine() -> (EngineConfig, build_outline_from_html, build_outline_from_text)
#   - install_opml_extras_into_app(app)
# ============================================================================

def _decode_bytes_best(b: bytes | bytearray | memoryview | str, default: str = "utf-8") -> str:
    """
    Heuristic HTML/text decoder:
      1) If already str → return
      2) Try UTF-8
      3) Look for <meta charset=...> or XML decl; retry
      4) Fall back through common encodings
    """
    if isinstance(b, str):
        return b
    raw = bytes(b)

    # Try UTF-8 first
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass

    # Look for charset hints
    head = raw[:4096].decode("latin-1", errors="replace")
    m = re.search(r'charset=["\']?([\w\-\.:]+)', head, re.I)
    if not m:
        m = re.search(r"<\?xml[^>]*encoding=['\"]([\w\-\.]+)['\"]", head, re.I)
    if m:
        enc = (m.group(1) or "").strip().lower()
        for candidate in (enc, enc.replace("-", ""), enc.replace("_", "-")):
            try:
                return raw.decode(candidate)
            except Exception:
                continue

    # Try a few common encodings
    for enc in ("utf-8-sig", "windows-1252", "latin-1", default):
        try:
            return raw.decode(enc, errors="strict")
        except Exception:
            continue

    # Last resort: replace errors
    return raw.decode("utf-8", errors="replace")


def _resolve_engine() -> Tuple[Optional[type], Optional[Callable], Optional[Callable]]:
    """
    Attempts to locate your OPML engine components.
    Expected return: (EngineConfig, build_outline_from_html, build_outline_from_text)
    If not found, returns (None, None, None).
    """
    # Preferred modern name
    for name in ("modules.Aopmlengine", "Aopmlengine", "modules.aopmlengine", "aopmlengine"):
        try:
            mod = __import__(name, fromlist=["*"])
        except Exception:
            continue

        # Common symbol spellings
        EC = getattr(mod, "EngineConfig", None) or getattr(mod, "Config", None)
        BOH = getattr(mod, "build_outline_from_html", None) or getattr(mod, "build_from_html", None)
        BOT = getattr(mod, "build_outline_from_text", None) or getattr(mod, "build_from_text", None)
        if EC and (BOH or BOT):
            return EC, BOH, BOT
    return None, None, None


# ============================================================================
# Core: selection → OPML (also callable directly by other modules)
# ============================================================================

def _selection_or_doc_body(app) -> str:
    """
    Read the current Tk text selection; if none, fall back to the current document body.
    Works with dict rows or tuple rows from doc_store.
    """
    # Try selection
    try:
        if hasattr(app, "text") and app.text is not None:
            start = app.text.index(tk.SEL_FIRST)
            end = app.text.index(tk.SEL_LAST)
            return app.text.get(start, end)
    except Exception:
        pass

    # Fallback: read body from doc_store / current_doc_id
    try:
        row = app.doc_store.get_document(app.current_doc_id)
        if isinstance(row, dict):
            return (row.get("body") or "") if not isinstance(row.get("body"), (bytes, bytearray)) else ""
        if isinstance(row, (list, tuple)) and len(row) >= 3:
            return row[2] if not isinstance(row[2], (bytes, bytearray)) else ""
    except Exception:
        pass
    return ""


def _string_to_opml_xml(title: str, text: str) -> str:
    """
    Simple line-per-outline OPML generator (keeps XML safe).
    Used when the full Aopmlengine is not available.
    """
    safe_title = html.escape(title or "Document", quote=True)
    lines = []
    for line in (text or "").splitlines():
        t = html.escape(line, quote=True)
        lines.append(f'      <outline text="{t}"/>')

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<opml version="2.0">
  <head>
    <title>{safe_title}</title>
  </head>
  <body>
    <outline text="{safe_title}">
{chr(10).join(lines)}
    </outline>
  </body>
</opml>
""".rstrip()
    return xml


def convert_current_to_opml(app) -> Optional[int]:
    """
    Convert current selection (or whole doc) → OPML.
    - If Aopmlengine is available, uses it.
    - Otherwise falls back to line-per-outline OPML.
    Returns new document id (int) on success, or None.
    """
    content = (_selection_or_doc_body(app) or "").strip()
    if not content:
        try:
            if messagebox:
                messagebox.showinfo("Convert → OPML", "No text to convert.")
        except Exception:
            pass
        return None

    # Title hint
    title = None
    try:
        title = (getattr(app, "current_title", None) or f"Doc {getattr(app, 'current_doc_id', '')}").strip()
    except Exception:
        title = "Document"

    EC, BOH, BOT = _resolve_engine()
    xml: str

    if EC and (BOH or BOT):
        # Try the richer engine
        try:
            # If content looks HTML-ish, prefer the HTML path
            looks_html = bool(re.search(r"</?(html|body|div|p|h\d|ul|ol|li|title)\b", content, re.I))
            cfg = EC(enable_ai=False, title=f"{title} (OPML)", owner_name=None)
            if looks_html and BOH:
                opml_doc = BOH(content, cfg)
            elif BOT:
                opml_doc = BOT(content, cfg)
            else:
                raise RuntimeError("Aopmlengine found but lacks suitable builders.")
            xml = opml_doc.to_xml()
        except Exception as e:
            # Fallback if engine fails
            xml = _string_to_opml_xml(title, content)
    else:
        # Minimal fallback
        xml = _string_to_opml_xml(title, content)

    # Store in DB and append backlink to source doc
    try:
        new_id = app.doc_store.add_document(f"{title} (OPML)", xml, content_type="text/opml")
        try:
            app.doc_store.append_to_document(getattr(app, "current_doc_id", None), f"[OPML version](doc:{new_id})")
        except Exception:
            pass

        # Update UI
        try:
            if hasattr(app, "_render_document"):
                app._render_document(app.doc_store.get_document(new_id))
            if hasattr(app, "_refresh_sidebar"):
                app._refresh_sidebar()
        except Exception:
            pass

        # Status/banner
        try:
            if hasattr(app, "status") and callable(app.status):
                app.status("Converted selection to OPML")
        except Exception:
            pass

        return int(new_id)
    except Exception as e:
        try:
            if messagebox:
                messagebox.showerror("Convert → OPML", f"OPML conversion failed:\n{e}")
        except Exception:
            pass
        return None


# ============================================================================
# UI wiring (menu item, toolbar button, hotkeys), provider banner helpers
# ============================================================================

def _mk_toolbar_button(app):
    if not hasattr(app, "toolbar"):
        return
    try:
        btn = ttk.Button(app.toolbar, text="CONVERT → OPML", command=lambda: convert_current_to_opml(app))
        # place near OPEN OPML if present; otherwise append at end
        btn.grid(row=0, column=99, sticky="we", padx=(0, 4))
    except Exception:
        pass


def _mk_menu_items(app):
    try:
        mb = app.nametowidget(app["menu"]) if hasattr(app, "nametowidget") else None
    except Exception:
        mb = None
    if not mb:
        return

    # Add a simple "OPML" menu if one doesn't exist
    try:
        opml_menu = tk.Menu(mb, tearoff=0)
        opml_menu.add_command(label="Convert Selection → OPML\tCtrl+Alt+O",
                              command=lambda: convert_current_to_opml(app))
        mb.add_cascade(label="OPML", menu=opml_menu)
    except Exception:
        pass

    # Hotkey
    try:
        app.bind("<Control-Alt-o>", lambda e: convert_current_to_opml(app))
    except Exception:
        pass


def _provider_banner_messages() -> list[str]:
    """
    Build marquee/status messages about the provider/model when possible.
    Uses provider_switch + AIInterface.ping() if available.
    """
    msgs = []
    # Static best-effort info from provider_switch
    try:
        prov = whoami() if callable(whoami) else "unknown"
        mdl = model_name() if callable(model_name) else "unknown"
        msgs.append(f"Provider: {prov} — Model: {mdl}")
    except Exception:
        pass

    # Optional live ping via AIInterface
    try:
        if AIInterface is not None:
            ai = AIInterface()
            if hasattr(ai, "ping"):
                # ai_interface.py ships a small .ping() helper in some forks  :contentReference[oaicite:2]{index=2}
                info = ai.ping()  # may raise; ignore details
                if isinstance(info, dict) and info.get("data"):
                    msgs.append("AI: endpoint OK ✓")
    except Exception:
        # don't spam; a silent failure is fine
        pass

    return [m for m in msgs if m]


def install_opml_extras_into_app(app) -> None:
    """
    Attaches:
      - Menu item: OPML → “Convert Selection → OPML”  (Ctrl+Alt+O)
      - Toolbar button: “CONVERT → OPML”
      - Marquee/banner addendum: provider/model line(s), when available
      - Attribute shims so other modules can call: app.convert_current_to_opml()
    Also leaves _decode_bytes_best and _resolve_engine importable by other modules. :contentReference[oaicite:3]{index=3}
    """
    # Expose method on the app for convenience
    try:
        setattr(app, "convert_current_to_opml", lambda: convert_current_to_opml(app))
    except Exception:
        pass

    # Add UI affordances
    try:
        if tk and ttk:
            _mk_toolbar_button(app)
            _mk_menu_items(app)
    except Exception:
        pass

    # Push provider/model messages into your MarqueeStatusBar if present
    try:
        if hasattr(app, "banner") and hasattr(app.banner, "push"):
            for m in _provider_banner_messages():
                app.banner.push(m)
    except Exception:
        pass

