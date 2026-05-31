import tkinter as tk
from tkinter import messagebox

class OPMLExtras:
    def __init__(self, doc_store, app):
        self.doc_store = doc_store
        self.app = app
        self.current_doc_id = None
        self.current_title = None
        self.text = None

    def _convert_current_to_opml(self):
        try:
            try:
                start = self.text.index(tk.SEL_FIRST)
                end = self.text.index(tk.SEL_LAST)
                content = self.text.get(start, end)
            except Exception:
                row = self.doc_store.get_document(self.current_doc_id)
                content = row["body"] if isinstance(row, dict) else (row[2] if row else "")

            content = (content or "").strip()
            if not content:
                messagebox.showinfo("Convert → OPML", "No text to convert.")
                return

            title = (self.current_title or f"Doc {self.current_doc_id}").strip()
            xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<opml version="2.0">
  <head>
    <title>{title}</title>
  </head>
  <body>
    <outline text="{title}">
{''.join('      <outline text="' + line.replace('"','&quot;') + '"/>' for line in content.splitlines())}
    </outline>
  </body>
</opml>
""".rstrip()

            new_id = self.doc_store.add_document(f"{title} (OPML)", xml, content_type="text/opml")
            self.doc_store.append_to_document(self.current_doc_id, f"[OPML version](doc:{new_id})")

            self.current_doc_id = new_id
            if hasattr(self, "_render_document"):
                self._render_document(self.doc_store.get_document(new_id))
            if hasattr(self, "_refresh_sidebar"):
                self._refresh_sidebar()

        except Exception as e:
            messagebox.showerror("Convert → OPML", f"OPML conversion failed:\n{e}")
