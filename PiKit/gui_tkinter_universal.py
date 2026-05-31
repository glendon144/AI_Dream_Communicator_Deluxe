# gui_tkinter.py — Universal, compatibility-hardened GUI for PiKit/DemoKit
# Date: 2025-08-23 (regen)
# Key features:
# - Accepts legacy module names (cmdprocessor.py / hypertextparser.py)
# - Accepts both 5-arg and legacy 4-arg CommandProcessor.query_ai()
# - Works whether CommandProcessor class is named CommandProcessor or CmdProcessor
# - Preserves selection for ASK; re-renders doc so green links appear immediately
# - Adds "Reparse Links" command to rebuild clickable links in-place
# - Tries multiple OPML import function names
# - Provides compatibility alias: DemoKitGUI = App
#
# Install path: modules/gui_tkinter.py

from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, simpledialog, messagebox

# ---- Optional image support (Pillow) ----
try:
    from PIL import Image, ImageTk  # type: ignore
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

# ---- Safe importer ----
def _try_import(modpath: str, name: str | None = None, default=None):
    try:
        mod = __import__(modpath, fromlist=["*"])
        return getattr(mod, name, mod) if name else mod
    except Exception:
        return default

# ---- Primary module names ----
command_processor_mod = _try_import("modules.command_processor")
document_store_mod    = _try_import("modules.document_store")
hypertext_parser_mod  = _try_import("modules.hypertext_parser")
renderer_mod          = _try_import("modules.renderer")
opml_plugin           = _try_import("modules.opml_extras_plugin_v3")

# ---- Legacy/alternate module names (shims) ----
if command_processor_mod is None:
    command_processor_mod = _try_import("modules.cmdprocessor")
if hypertext_parser_mod is None:
    hypertext_parser_mod = _try_import("modules.hypertextparser")

# Resolve CP class (CommandProcessor or CmdProcessor)
CommandProcessor = None
if command_processor_mod:
    CommandProcessor = getattr(
        command_processor_mod,
        "CommandProcessor",
        getattr(command_processor_mod, "CmdProcessor", None),
    )

# Resolve link parser function(s)
parse_links = None
if hypertext_parser_mod:
    # common names first
    for fname in ("parse_links", "parse_links_v2", "reparse_links"):
        parse_links = getattr(hypertext_parser_mod, fname, None)
        if callable(parse_links):
            break

# Optional renderer helpers
render_binary_preview = getattr(renderer_mod or object(), "render_binary_preview", None)
render_binary_as_text = getattr(renderer_mod or object(), "render_binary_as_text", None)


class App(tk.Tk):
    """
    Universal GUI:
      - Flexible constructor accepts legacy args/kwargs:
          App(doc_store, processor, root)  # legacy style (extra args ignored)
          App(doc_store=..., processor=...)  # preferred explicit kwargs
          App()  # will self-initialize store & processor if modules present
    """
    def __init__(self, *args, **kwargs):
        # Accept legacy positional args: (doc_store, processor, root?) — we ignore root
        doc_store_pos = args[0] if len(args) >= 1 else None
        processor_pos = args[1] if len(args) >= 2 else None

        super().__init__()
        self.title("PiKit / DemoKit — GUI")
        self.geometry("1120x740")

        # Public state
        self.current_doc_id: int | None = None
        self.history: list[int] = []
        self._last_selection: tuple[str, str] | None = None
        self._current_content: str | bytes | None = None  # for Reparse Links

        # Prefer explicit kwargs, else positional, else auto-init modules if available
        self.doc_store = kwargs.get("doc_store") or doc_store_pos
        self.processor = kwargs.get("processor") or processor_pos

        if self.doc_store is None and document_store_mod and hasattr(document_store_mod, "DocumentStore"):
            try:
                self.doc_store = document_store_mod.DocumentStore()
            except Exception as e:
                print("Warning: DocumentStore failed to init:", e)

        if self.processor is None and CommandProcessor:
            try:
                self.processor = CommandProcessor()
            except Exception as e:
                print("Warning: CommandProcessor failed to init:", e)

        self._build_ui()
        self._refresh_index()

    # ---------- UI ----------
    def _build_ui(self):
        root = self

        # Toolbar
        bar = ttk.Frame(root)
        bar.pack(side="top", fill="x")

        ttk.Button(bar, text="Ask", command=self._on_ask).pack(side="left", padx=4, pady=4)
        ttk.Button(bar, text="Back", command=self._go_back).pack(side="left", padx=4, pady=4)
        ttk.Button(bar, text="Open by ID", command=self._open_by_id).pack(side="left", padx=4, pady=4)

        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6)

        ttk.Button(bar, text="Import Dir", command=self._import_directory).pack(side="left", padx=4, pady=4)
        ttk.Button(bar, text="Open OPML", command=self._open_opml_from_file).pack(side="left", padx=4, pady=4)
        ttk.Button(bar, text="Convert → OPML", command=self._convert_selection_to_opml).pack(side="left", padx=4, pady=4)

        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6)

        ttk.Button(bar, text="Search", command=self._on_search_clicked).pack(side="left", padx=4, pady=4)
        ttk.Button(bar, text="Reparse Links", command=self._reparse_links).pack(side="left", padx=4, pady=4)

        # Panes
        self.panes = ttk.Panedwindow(root, orient="horizontal")
        self.panes.pack(fill="both", expand=True)

        # Left: index
        left = ttk.Frame(self.panes)
        self.sidebar = ttk.Treeview(left, columns=("id", "title", "extra"), show="headings", height=20)
        self.sidebar.heading("id", text="ID")
        self.sidebar.heading("title", text="Title")
        self.sidebar.heading("extra", text="")
        self.sidebar.column("id", width=80, anchor="w")
        self.sidebar.column("title", width=380, anchor="w")
        self.sidebar.column("extra", width=60, anchor="center")
        self.sidebar.pack(fill="both", expand=True)
        self.sidebar.bind("<<TreeviewSelect>>", self._on_sidebar_select)

        left_bottom = ttk.Frame(left)
        left_bottom.pack(fill="x")
        ttk.Button(left_bottom, text="Refresh", command=self._refresh_index).pack(side="left", padx=4, pady=4)
        self.panes.add(left, weight=1)

        # Right: document text
        right = ttk.Frame(self.panes)
        self.text = tk.Text(right, wrap="word", undo=True)
        yscroll = ttk.Scrollbar(right, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=yscroll.set)
        self.text.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="left", fill="y")

        # Preserve selection for Ask
        self.text.bind("<<Selection>>", self._on_text_selection_changed)
        self.text.bind("<ButtonRelease-1>", self._on_text_selection_changed, add="+")

        self.panes.add(right, weight=3)

        # Status
        self.status = tk.StringVar(value="Ready")
        ttk.Label(root, textvariable=self.status, anchor="w").pack(side="bottom", fill="x")

        # Shortcuts
        root.bind_all("<Control-Return>", lambda e: self._on_ask())
        root.bind_all("<Control-Shift-O>", lambda e: self._convert_selection_to_opml())
        root.bind_all("<Control-u>", lambda e: self._open_opml_from_file())

    # ---------- Selection handling ----------
    def _on_text_selection_changed(self, event=None):
        try:
            start = self.text.index("sel.first")
            end = self.text.index("sel.last")
            self._last_selection = (start, end)
        except Exception:
            self._last_selection = None

    def _get_selected_text(self) -> str:
        try:
            return self.text.get("sel.first", "sel.last")
        except Exception:
            pass
        if self._last_selection:
            s, e = self._last_selection
            try:
                return self.text.get(s, e)
            except Exception:
                return ""
        return ""

    # ---------- Index / navigation ----------
    def _refresh_index(self):
        try:
            self.sidebar.delete(*self.sidebar.get_children())
        except Exception:
            return

        rows = []
        if self.doc_store and hasattr(self.doc_store, "get_document_index"):
            try:
                rows = self.doc_store.get_document_index() or []
            except Exception as e:
                print("get_document_index failed:", e)

        for row in rows:
            if isinstance(row, dict):
                doc_id, title = row.get("id"), row.get("title", "")
            elif isinstance(row, (list, tuple)):
                doc_id, title = row[0], (row[1] if len(row) > 1 else "")
            else:
                continue
            self.sidebar.insert("", "end", values=(doc_id, title, ""))

    def _on_sidebar_select(self, event=None):
        sel = self.sidebar.selection()
        if not sel:
            return
        item = self.sidebar.item(sel[0])
        vals = item.get("values") or []
        if not vals:
            return
        doc_id = vals[0]
        self._open_doc_id(doc_id)

    def _open_doc_id(self, doc_id):
        try:
            doc_id = int(doc_id)
        except Exception:
            messagebox.showerror("Open", f"Invalid document id: {doc_id}")
            return

        if self.current_doc_id is not None:
            self.history.append(self.current_doc_id)

        doc = None
        if self.doc_store and hasattr(self.doc_store, "get_document"):
            try:
                doc = self.doc_store.get_document(doc_id)
            except Exception as e:
                print("get_document failed:", e)
        if not doc:
            messagebox.showerror("Open", f"Document {doc_id} not found.")
            return

        self.current_doc_id = doc_id
        self._render_document(doc)

    # ---------- Render ----------
    def _render_document(self, doc):
        self.text.delete("1.0", "end")

        content = ""
        title = ""
        if isinstance(doc, dict):
            title = doc.get("title", "")
            content = doc.get("content", "") or doc.get("body", "") or ""
        elif isinstance(doc, (list, tuple)):
            title = doc[1] if len(doc) > 1 else ""
            content = doc[2] if len(doc) > 2 else ""
        else:
            content = str(doc)

        self._current_content = content  # save for Reparse Links

        # Binary-as-image render path
        if PIL_AVAILABLE and isinstance(content, (bytes, bytearray)):
            try:
                from io import BytesIO
                im = Image.open(BytesIO(content))
                imtk = ImageTk.PhotoImage(im)
                self.text.image_create("end", image=imtk)
                self.text.insert("end", "\n")
                if not hasattr(self, "_img_refs"):
                    self._img_refs = []
                self._img_refs.append(imtk)
            except Exception:
                self._render_binary_preview(content)
        else:
            # Text path
            self.text.insert("1.0", content)

        # Parse links if available
        if parse_links and isinstance(content, str):
            try:
                parse_links(self.text, content, self._open_doc_id)
            except Exception as e:
                print("parse_links failed:", e)

        self.status.set(f"Viewing: {title} (id={self.current_doc_id})")

    def _render_binary_preview(self, payload):
        if render_binary_preview:
            try:
                render_binary_preview(self.text, payload)
                return
            except Exception as e:
                print("render_binary_preview failed:", e)
        if render_binary_as_text:
            try:
                render_binary_as_text(self.text, payload)
            except Exception as e:
                print("render_binary_as_text failed:", e)

    # ---------- Commands ----------
    def _on_ask(self):
        sel = self._get_selected_text()
        if not sel.strip():
            messagebox.showinfo("ASK", "Please select some text in the document first.")
            return

        if not self.processor or not hasattr(self.processor, "query_ai"):
            messagebox.showerror("ASK", "CommandProcessor.query_ai is unavailable.")
            return

        current_id = self.current_doc_id
        prefix = simpledialog.askstring(
            "ASK prefix",
            "Enter prefix (optional):",
            initialvalue="Please expand on this: "
        )
        if prefix is None:
            return

        def _on_success(new_id):
            try:
                messagebox.showinfo("ASK", f"Created new document {new_id}")
            finally:
                self._refresh_index()

        def _on_link_created(_t):
            # Re-open current doc so green link appears immediately
            if current_id is not None and self.doc_store:
                try:
                    doc = self.doc_store.get_document(current_id)
                    if doc:
                        self._render_document(doc)
                except Exception as e:
                    print("on_link_created refresh failed:", e)

        # Try 5-arg signature first, then legacy 4-arg
        try:
            self.processor.query_ai(
                selected_text=sel,
                current_doc_id=current_id,
                on_success=_on_success,
                on_link_created=_on_link_created,
                prefix=prefix,
            )
        except TypeError:
            try:
                self.processor.query_ai(sel, current_id, _on_success, _on_link_created)
            except Exception as e:
                messagebox.showerror("ASK", f"query_ai failed: {e}")
        except Exception as e:
            messagebox.showerror("ASK", f"query_ai error: {e}")

    def _go_back(self):
        if not self.history:
            messagebox.showinfo("Back", "No previous document.")
            return
        prev = self.history.pop()
        self._open_doc_id(prev)

    def _open_by_id(self):
        s = simpledialog.askstring("Open", "Document ID:")
        if not s:
            return
        self._open_doc_id(s)

    def _import_directory(self):
        if not self.processor or not hasattr(self.processor, "import_directory"):
            messagebox.showerror("Import", "CommandProcessor.import_directory unavailable.")
            return
        path = filedialog.askdirectory(title="Choose a directory to import")
        if not path:
            return
        try:
            added = self.processor.import_directory(path)
        except Exception as e:
            messagebox.showerror("Import", f"Import failed: {e}")
            return
        messagebox.showinfo("Import", f"Imported {added} documents.")
        self._refresh_index()

    def _open_opml_from_file(self):
        # Prefer plugin flow when available
        if opml_plugin and hasattr(opml_plugin, "open_opml_file_dialog"):
            try:
                new_id = opml_plugin.open_opml_file_dialog(self)
                if new_id:
                    self._open_doc_id(new_id)
                return
            except Exception as e:
                messagebox.showerror("OPML", f"Open OPML failed: {e}")
                return

        # Fallback: let user pick a file and call into processor with any of the common names
        filepath = filedialog.askopenfilename(
            title="Open OPML file",
            filetypes=[("OPML files", "*.opml *.xml"), ("All files", "*.*")]
        )
        if not filepath:
            return

        if not self.processor:
            messagebox.showerror("OPML", "OPML feature unavailable (no processor).")
            return

        # Try common import function names
        func = None
        for name in ("import_opml_from_path", "import_opml", "import_opml_file"):
            func = getattr(self.processor, name, None)
            if callable(func):
                break

        if not func:
            messagebox.showerror("OPML", "No OPML import function found in CommandProcessor.")
            return

        try:
            new_id = func(filepath)
        except Exception as e:
            messagebox.showerror("OPML", f"OPML import failed: {e}")
            return
        if new_id:
            self._open_doc_id(new_id)

    def _convert_selection_to_opml(self):
        sel = self._get_selected_text()
        if not sel.strip():
            messagebox.showinfo("Convert → OPML", "Select some text first.")
            return
        # Prefer plugin conversion if present
        xml_text = None
        if opml_plugin:
            conv = getattr(opml_plugin, "convert_text_to_opml_inplace", None)
            if callable(conv):
                try:
                    xml_text = conv(sel)
                except Exception as e:
                    messagebox.showerror("Convert → OPML", f"Conversion failed: {e}")
                    return
        if xml_text is None:
            xml_text = self._basic_text_to_opml(sel)

        win = tk.Toplevel(self)
        win.title("OPML Preview")
        txt = tk.Text(win, wrap="word")
        txt.pack(fill="both", expand=True)
        txt.insert("1.0", xml_text)

        def _save():
            out = filedialog.asksaveasfilename(
                title="Save OPML",
                defaultextension=".opml",
                filetypes=[("OPML files", "*.opml"), ("XML files", "*.xml"), ("All files", "*.*")]
            )
            if not out:
                return
            Path(out).write_text(xml_text, encoding="utf-8")
            messagebox.showinfo("OPML", f"Saved to {out}")

        ttk.Button(win, text="Save…", command=_save).pack(pady=6)

    def _reparse_links(self):
        """Re-run link parsing on the current Text widget content."""
        if not parse_links:
            messagebox.showinfo("Reparse Links", "No link parser available.")
            return
        try:
            # Get current visible content (may include edits)
            current_text = self.text.get("1.0", "end-1c")
            self._current_content = current_text  # keep in sync
            parse_links(self.text, current_text, self._open_doc_id)
            self.status.set("Links reparsed.")
        except Exception as e:
            messagebox.showerror("Reparse Links", f"Failed: {e}")

    @staticmethod
    def _basic_text_to_opml(text: str) -> str:
        import html
        body = "\n".join(
            f'<outline text="{html.escape(line)}" />'
            for line in text.splitlines() if line.strip()
        )
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<opml version="2.0">\n'
            '  <head><title>Converted</title></head>\n'
            '  <body>\n'
            f'{body}\n'
            '  </body>\n'
            '</opml>\n'
        )

def main():
    app = App()
    app.mainloop()

if __name__ == "__main__":
    main()

# --- Compatibility alias for old imports ---
DemoKitGUI = App
