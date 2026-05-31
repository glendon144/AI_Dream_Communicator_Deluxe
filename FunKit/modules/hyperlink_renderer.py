# modules/hyperlink_renderer.py
"""
Hyperlink renderer for Tkinter Text widgets (idempotent).
- Parses markup like:  [Label](doc:123)
- Preferred path: keep the original text and *elide* the markup parts so only "Label" shows.
- Fallback path (if 'elide' not supported): rewrite text to "Label" and tag ranges; on re-parse,
  reuse previously stored ranges so links don't disappear.

Usage:
    from modules.hyperlink_renderer import render_links

    def on_open_doc(doc_id: int):
        print("Open doc:", doc_id)

    render_links(text_widget, on_open_doc)

Env knobs (optional):
- PIKIT_LINK_COLOR: default "#0a84ff"
- PIKIT_LINK_UNDERLINE: "1" or "0", default "1"
"""

from __future__ import annotations
import os
import re
import tkinter as tk
from typing import Callable, List, Tuple

LINK_PATTERN = re.compile(r"\[([^\]]+)\]\(doc:(\d+)\)")

def _cfg_tags(text: tk.Text) -> bool:
    # Configure base tags (idempotent). Return whether elide is supported.
    link_color = os.getenv("PIKIT_LINK_COLOR", "#0a84ff")
    underline = bool(int(os.getenv("PIKIT_LINK_UNDERLINE", "1")))
    try:
        text.tag_configure("link", foreground=link_color, underline=underline)
    except tk.TclError:
        pass
    elide_ok = True
    try:
        text.tag_configure("elide", elide=1)  # hide markup
    except tk.TclError:
        elide_ok = False
    text._elide_supported = elide_ok  # cache
    return elide_ok

def _bind_handlers(text: tk.Text):
    if getattr(text, "_link_handler_bound", False):
        return

    def on_click(event):
        try:
            index = event.widget.index(f"@{event.x},{event.y}")
            tags = event.widget.tag_names(index)
            if "link" not in tags:
                return
            for (start, end, doc_id) in getattr(event.widget, "_links", []):
                if (event.widget.compare(start, "<=", index) and
                    event.widget.compare(index, "<", end)):
                    cb = getattr(event.widget, "_on_open_doc", None)
                    if callable(cb):
                        cb(int(doc_id))
                    break
        except Exception:
            pass

    def on_enter(event):
        try:
            event.widget.configure(cursor="hand2")
        except Exception:
            pass

    def on_leave(event):
        try:
            event.widget.configure(cursor="")
        except Exception:
            pass

    text.tag_bind("link", "<Button-1>", on_click)
    text.tag_bind("link", "<Enter>", on_enter)
    text.tag_bind("link", "<Leave>", on_leave)
    text._link_handler_bound = True

def _char_index(offset: int) -> str:
    return f"1.0+{offset}c"

def render_links(text: tk.Text, on_open_doc: Callable[[int], None]) -> None:
    """
    Parse and render links in the given Text widget.
    Preferred: use 'elide' to hide markup so re-parsing is idempotent.
    Fallback: rewrite text, but retain and reuse previous ranges if no new markup is found.
    """
    if not isinstance(text, tk.Text):
        raise TypeError("render_links(text, on_open_doc): 'text' must be a tk.Text")

    elide_ok = _cfg_tags(text)
    _bind_handlers(text)

    # Read current content
    try:
        raw = text.get("1.0", "end-1c")
    except Exception as e:
        raise RuntimeError(f"Cannot read from Text widget: {e}")

    matches = list(LINK_PATTERN.finditer(raw))

    # Always clear existing tags first
    try:
        text.tag_remove("link", "1.0", "end")
        if elide_ok:
            text.tag_remove("elide", "1.0", "end")
    except Exception:
        pass

    links: List[Tuple[str, str, int]] = []

    if elide_ok:
        # Do not rewrite content. Hide markup, tag label as link.
        for m in matches:
            label, doc_id = m.group(1), int(m.group(2))
            start = m.start()
            end = m.end()
            label_start = start + 1              # after '['
            label_end = label_start + len(label) # before ']'
            # Hide '[' and '](doc:ID)'
            try:
                text.tag_add("elide", _char_index(start), _char_index(label_start))
                text.tag_add("elide", _char_index(label_end), _char_index(end))
            except Exception:
                pass
            # Make the label clickable
            try:
                text.tag_add("link", _char_index(label_start), _char_index(label_end))
            except Exception:
                pass
            links.append((_char_index(label_start), _char_index(label_end), doc_id))

        # If no matches but we had prior links, reapply them so links don't disappear.
        if not matches and getattr(text, "_links", []):
            for (start, end, _doc_id) in text._links:
                try:
                    text.tag_add("link", start, end)
                except Exception:
                    pass

        text._links = links

    else:
        # Fallback path: rewrite content once, compute positions in the new text.
        if matches:
            pieces: List[str] = []
            links = []
            pos = 0
            for m in matches:
                label, doc_id = m.group(1), int(m.group(2))
                before = raw[pos:m.start()]
                pieces.append(before)
                start_offset = sum(len(p) for p in pieces)
                pieces.append(label)
                end_offset = sum(len(p) for p in pieces)
                links.append((_char_index(start_offset), _char_index(end_offset), doc_id))
                pos = m.end()
            pieces.append(raw[pos:])
            new_text = "".join(pieces)

            # Replace entire content (preserve view/insert if we can)
            try:
                yview = text.yview()
            except Exception:
                yview = None
            try:
                insert_index = text.index("insert")
            except Exception:
                insert_index = None

            state = str(text.cget("state"))
            try:
                if state != "normal":
                    text.configure(state="normal")
                text.delete("1.0", "end")
                text.insert("1.0", new_text)
                if yview is not None:
                    text.yview_moveto(yview[0])
                if insert_index is not None:
                    try:
                        text.mark_set("insert", insert_index)
                    except Exception:
                        pass
            finally:
                if state != "normal":
                    text.configure(state=state)

            # Add link tags
            for (start, end, _doc_id) in links:
                try:
                    text.tag_add("link", start, end)
                except Exception:
                    pass

            text._links = links

        else:
            # No new markup found. Reapply previous link ranges, if any.
            prior = getattr(text, "_links", [])
            for (start, end, _doc_id) in prior:
                try:
                    text.tag_add("link", start, end)
                except Exception:
                    pass
            # Keep prior links as-is
            links = prior

    # Store callback & link map
    text._on_open_doc = on_open_doc
    text._links = links
