"""
export_doc_patch.py — Runtime patch for PiKit/DemoKit

Purpose
-------
Replace DemoKitGUI._export_doc with a robust version that:
  • Writes bytes with write_bytes() (images, PDFs, etc.)
  • Writes text with write_text() (OPML/HTML/TXT)
  • Picks a sensible default extension based on content
  • Works with sqlite3.Row, dict, or tuple rows from the document store

How to install
--------------
In main.py, AFTER you create the app:

    from modules.export_doc_patch import install_export_doc_patch
    install_export_doc_patch(app)

That's it. No need to edit gui_tkinter.py directly.
"""

from __future__ import annotations

def _robust_export_doc(self):
    from tkinter import filedialog, messagebox
    from pathlib import Path

    if getattr(self, "current_doc_id", None) is None:
        messagebox.showwarning("Export", "No document selected.")
        return

    # Fetch and normalize the current document (sqlite3.Row / dict / tuple)
    doc = self.doc_store.get_document(self.current_doc_id)
    if hasattr(doc, "keys"):  # sqlite3.Row-like
        title = doc["title"] if "title" in doc.keys() else "Document"
        body  = doc["body"]  if "body"  in doc.keys() else ""
    elif isinstance(doc, dict):
        title = doc.get("title") or "Document"
        body  = doc.get("body")  or ""
    else:  # tuple/list row: (id, title, body, ...)
        title = doc[1] if len(doc) > 1 else "Document"
        body  = doc[2] if len(doc) > 2 else ""

    # Pick a sensible default extension & filetypes
    ext = ".txt"
    filetypes = [("Text", "*.txt"), ("All files", "*.*")]
    if isinstance(body, (bytes, bytearray)):
        b = bytes(body)
        if b.startswith(b"\x89PNG\r\n\x1a\n"):
            ext, filetypes = ".png", [("PNG image", "*.png"), ("All files", "*.*")]
        elif b.startswith(b"\xff\xd8\xff"):
            ext, filetypes = ".jpg", [("JPEG image", "*.jpg;*.jpeg"), ("All files", "*.*")]
        elif b[:6] in (b"GIF87a", b"GIF89a"):
            ext, filetypes = ".gif", [("GIF image", "*.gif"), ("All files", "*.*")]
        elif b.startswith(b"%PDF-"):
            ext, filetypes = ".pdf", [("PDF", "*.pdf"), ("All files", "*.*")]
        elif b[:4] == b"RIFF" and b[8:12] == b"WEBP":
            ext, filetypes = ".webp", [("WebP", "*.webp"), ("All files", "*.*")]
        else:
            try:
                b.decode("utf-8")
                ext, filetypes = ".txt", [("Text", "*.txt"), ("All files", "*.*")]
            except Exception:
                ext, filetypes = ".bin", [("Binary", "*.bin"), ("All files", "*.*")]
    else:
        s = (body or "").lstrip()
        low = s.lower()
        if low.startswith("<opml"):
            ext, filetypes = ".opml", [("OPML", "*.opml"), ("XML", "*.xml"), ("All files", "*.*")]
        elif low.startswith("<html") or ("<body" in low) or ("<div" in low):
            ext, filetypes = ".html", [("HTML", "*.html;*.htm"), ("All files", "*.*")]
        elif low.startswith("<svg"):
            ext, filetypes = ".svg", [("SVG", "*.svg"), ("All files", "*.*")]
        else:
            ext, filetypes = ".txt", [("Text", "*.txt"), ("All files", "*.*")]

    # Ask destination
    safe = "".join(c if (c.isalnum() or c in "._- ") else "_" for c in (title or "Document")).strip() or "Document"
    path = filedialog.asksaveasfilename(
        title="Export Document",
        defaultextension=ext,
        initialfile=f"{safe}{ext}",
        filetypes=filetypes,
    )
    if not path:
        return

    # Write
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)

        if isinstance(body, (bytes, bytearray)) and ext not in (".txt", ".opml", ".html", ".svg", ".xml"):
            Path(path).write_bytes(bytes(body))
        else:
            if isinstance(body, (bytes, bytearray)):
                # Convert bytes to text if target is a text-like extension
                try:
                    text_out = body.decode("utf-8")
                except Exception:
                    try:
                        from modules.hypertext_parser import render_binary_as_text
                        text_out = render_binary_as_text(body, title or "Document")
                    except Exception:
                        text_out = body.decode("utf-8", errors="replace")
                Path(path).write_text(text_out, encoding="utf-8", newline="\n")
            else:
                Path(path).write_text(body or "", encoding="utf-8", newline="\n")

        messagebox.showinfo("Export", f"Saved:\n{path}")
    except Exception as e:
        messagebox.showerror("Export", f"Could not save:\n{e}")


def install_export_doc_patch(app) -> None:
    """Attach robust exporter to DemoKitGUI class; idempotent."""
    cls = app.__class__
    setattr(cls, "_export_doc", _robust_export_doc)
