"""
save_as_text_plugin_v3.py — Resilient "Save As Text" for FunKit/DemoKit

Fixes:
  • "Document not found" or odd types from DB (e.g., sqlite3.Row as body).
  • Falls back to the visible text if DB row can't be loaded.

Install:
    from modules.save_as_text_plugin_v3 import install_save_as_text_into_app
    install_save_as_text_into_app(app)
"""

from __future__ import annotations
from typing import Any

def _is_opml_text(s: Any) -> bool:
    return isinstance(s, str) and "<opml" in s.lower()

def _flatten_opml_to_text(xml_text: str) -> str:
    import xml.etree.ElementTree as ET
    try:
        s = xml_text.lstrip("\ufeff\r\n\t ")
        if "<" in s:
            s = s[s.find("<"):]
        root = ET.fromstring(s)
    except Exception:
        return xml_text
    lines: list[str] = []
    def walk(node, depth=0):
        tag = (getattr(node, "tag", "") or "").lower()
        if tag.endswith("outline"):
            text = node.attrib.get("text") or node.attrib.get("title") or ""
            if text:
                lines.append(("  " * depth) + "- " + text)
            for child in list(node):
                walk(child, depth + 1)
    body = root.find(".//body")
    nodes = list(body) if body is not None else list(root)
    for n in nodes:
        walk(n, 0)
    return "\n".join(lines).strip()

def _doc_tuple(doc):
    """Normalize a doc-like object to (id, title, body).
       Handles dicts, sqlite3.Row (mapping), and indexables (tuple/list-like).
    """
    # 1) Mapping-style (sqlite3.Row also behaves like a mapping)
    try:
        if hasattr(doc, "keys"):
            keys = set(doc.keys())  # sqlite3.Row supports .keys()
            if "id" in keys and "title" in keys and "body" in keys:
                # sqlite3.Row: access by key
                return (doc["id"], doc["title"] or "Document", doc["body"])
            # Some stores may use different key names
            if "body" in keys and ("title" in keys or "name" in keys):
                title = doc.get("title") or doc.get("name") or "Document"
                body = doc.get("body")
                did  = doc.get("id")
                return (did, title, body)
    except Exception:
        pass

    # 2) Plain dict
    if isinstance(doc, dict):
        return (doc.get("id"), doc.get("title") or "Document", doc.get("body"))

    # 3) Indexable sequence (tuple/list/sqlite3.Row as sequence)
    try:
        # Avoid treating strings/bytes as sequences here
        if not isinstance(doc, (str, bytes, bytearray)) and hasattr(doc, "__getitem__"):
            did = doc[0]
            title = doc[1] if len(doc) > 1 else "Document"
            body = doc[2] if len(doc) > 2 else ""
            return (did, title or "Document", body)
    except Exception:
        pass

    # Fallback: treat entire object as body string
    return (None, "Document", doc)

def _visible_text_fallback(app) -> str | None:
    """Return what the user currently sees in the main Text widget, if available."""
    import tkinter as tk
    for name in ("_text", "text", "main_text", "editor", "body_text", "content_text"):
        w = getattr(app, name, None)
        if isinstance(w, tk.Text):
            try:
                return w.get("1.0", "end-1c")
            except Exception:
                continue
    # Try focused widget as last resort
    try:
        f = app.focus_get()
        import tkinter as tk
        if isinstance(f, tk.Text):
            return f.get("1.0", "end-1c")
    except Exception:
        pass
    return None

def _document_to_plain_text(app, doc_or_none) -> tuple[str, str]:
    """Return (title, plain_text) for the current document, robust."""
    title = "Document"
    body = None

    # Try DB first
    if doc_or_none is None and getattr(app, "current_doc_id", None) is not None:
        try:
            doc_or_none = app.doc_store.get_document(app.current_doc_id)
        except Exception:
            doc_or_none = None

    if doc_or_none is not None:
        did, title, body = _doc_tuple(doc_or_none)

    # If we don't have a body from DB, use visible text
    if body in (None, b"", "", bytearray()):
        vis = _visible_text_fallback(app)
        if vis:
            body = vis

    # Binary → text
    if isinstance(body, (bytes, bytearray)):
        try:
            from modules.hypertext_parser import render_binary_as_text  # type: ignore
        except Exception:
            render_binary_as_text = None  # type: ignore
        if render_binary_as_text is not None:
            try:
                return title, render_binary_as_text(body, title or "Document")
            except Exception:
                pass
        try:
            return title, body.decode("utf-8", errors="replace")
        except Exception:
            return title, str(body)

    # If somehow body is still not a string, coerce it
    if not isinstance(body, str):
        try:
            body = str(body)
        except Exception:
            body = ""

    s = (body or "").strip()

    # OPML → bullets
    if _is_opml_text(s):
        return title, _flatten_opml_to_text(s)

    # HTML → text (strip tags/script/style)
    import re
    low = s.lower()
    if ("<html" in low) or ("<body" in low) or ("<div" in low) or ("<p" in low) or ("<h1" in low):
        s = re.sub(r"<(script|style)[\s\S]*?</\1>", " ", s, flags=re.I)
        s = re.sub(r"<[^>]+>", " ", s)
    return title, s.strip()

def _default_save_dir() -> str:
    """Prefer ~/Downloads if it exists, else current dir."""
    import os
    downloads = os.path.join(os.path.expanduser("~"), "Downloads")
    return downloads if os.path.isdir(downloads) else os.getcwd()

def _save_current_as_text(self):
    """Export the current document (or currently visible text) to a .txt file."""
    try:
        from tkinter import filedialog, messagebox
    except Exception:
        return

    # Try to get DB doc (best), else rely on visible text
    doc = None
    if getattr(self, "current_doc_id", None) is not None:
        try:
            doc = self.doc_store.get_document(self.current_doc_id)
        except Exception:
            doc = None

    title, text_out = _document_to_plain_text(self, doc)

    # Build a safe default filename and directory
    safe = "".join(c if (c.isalnum() or c in "._- ") else "_" for c in (title or "Document")).strip() or "Document"
    default_name = f"{safe}.txt"

    path = filedialog.asksaveasfilename(
        title="Save As Text",
        defaultextension=".txt",
        initialfile=default_name,
        initialdir=_default_save_dir(),
        filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
    )
    if not path:
        return

    try:
        import os
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write((text_out or "") + "\n")
        messagebox.showinfo("Save As Text", f"Saved:\n{path}")
    except Exception as e:
        messagebox.showerror("Save As Text", f"Could not save:\n{e}")

def attach_save_as_text_plugin(DemoKitGUI_cls):
    setattr(DemoKitGUI_cls, "_save_current_as_text", _save_current_as_text)
    for alias in ("_save_as_text", "_save_text", "_export_as_text"):
        if not hasattr(DemoKitGUI_cls, alias):
            setattr(DemoKitGUI_cls, alias, _save_current_as_text)

def _rewire_save_button(app) -> int:
    """Rebind any 'SAVE AS TEXT' buttons to our robust saver; returns the number rewired."""
    try:
        import tkinter as tk
    except Exception:
        return 0
    count = 0
    def _walk(w):
        nonlocal count
        try:
            kids = w.winfo_children()
        except Exception:
            kids = []
        for c in kids:
            try:
                t = c.cget("text")
            except Exception:
                t = None
            if isinstance(t, str) and t.strip().upper() == "SAVE AS TEXT":
                try:
                    c.configure(command=lambda a=app: a._save_current_as_text())
                    count += 1
                except Exception:
                    pass
            _walk(c)
    _walk(app)
    return count

def install_save_as_text_into_app(app) -> None:
    """Attach and wire the robust saver; idempotent."""
    cls = app.__class__
    attach_save_as_text_plugin(cls)
    try:
        _ = _rewire_save_button(app)
    except Exception as e:
        print("[WARN] SaveAsText v3: toolbar wiring failed:", e)
