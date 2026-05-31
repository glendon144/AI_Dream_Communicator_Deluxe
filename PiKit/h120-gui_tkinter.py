import os
import threading
import tkinter as tk
from tkinter import ttk, filedialog, simpledialog, messagebox
from pathlib import Path
from PIL import ImageTk, Image
import subprocess
import sys
import json
import re
import xml.etree.ElementTree as ET

# === Tri-model integration imports ===
from concurrent.futures import ThreadPoolExecutor
from tkinter import messagebox
from modules.tri_pipeline import run_tri_pipeline
from modules.ai_memory import get_memory, set_memory
from modules.memory_dialog import open_memory_dialog


# PiKit modules
from modules import hypertext_parser, image_generator, document_store
from modules.renderer import render_binary_as_text
from modules.logger import Logger
from modules.directory_import import import_text_files_from_directory
from modules.TreeView import open_tree_view

SETTINGS_FILE = Path("pikit_settings.json")


class DemoKitGUI(tk.Tk):
    def _on_search_changed(self):
        # debounce so we don’t hammer the DB while typing
        if self._search_after_id:
            self.root.after_cancel(self._search_after_id)
            self._search_after_id = self.root.after(200, self._apply_search)

    def _apply_search(self):
        q = (self._search_var.get() or "").strip()
        if not q or q == "title or text…":
            # empty → show full tree
            self.refresh_index()
            return
        self.filter_index(q)
 
    def _on_image_clicked(self):
        """Image generation disabled here: viewing images is local-only.
        Hook your OpenAI-powered generation here if/when you want it."""
        from tkinter import messagebox
        messagebox.showinfo("Image", "Local image rendering is enabled. Generation is disabled in this build.")
    """PiKit / DemoKit GUI with OPML auto-rendering in the document pane, TreeView integration, and utilities."""

    SIDEBAR_WIDTH = 320

    def __init__(self, doc_store, processor):
        super().__init__()
        self.doc_store = doc_store
        self.processor = processor
        self.logger: Logger = getattr(processor, "logger", Logger())
        self.current_doc_id: int | None = None
        self.history: list[int] = []
        self._suppress_sidebar_select = False  # prevent re-entrant selects
# idempotent;  safe to call each startup
        # image state
        self._last_pil_img: Image.Image | None = None
        self._last_tk_img: ImageTk.PhotoImage | None = None
        self._image_enlarged: bool = False

        # ---- Settings ----
        self.settings = self._load_settings()
        self.opml_expand_depth: int = int(self.settings.get("opml_expand_depth", 2))

        self.title("Engelbart Journal – DemoKit")
        self.geometry("1200x800")
        self.columnconfigure(0, minsize=self.SIDEBAR_WIDTH, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_main_pane()
        self._build_context_menu()

        # --- Menubar ---
        menubar = tk.Menu(self)
        # --- Tools Menu --- 
        
        toolsmenu = tk.Menu(menubar, tearoff=0)
        toolsmenu.add_command(label="Memory…", command=lambda: open_memory_dialog(self))
        menubar.add_cascade(label="Tools", menu=toolsmenu)
        # File menu
        filemenu = tk.Menu(menubar, tearoff=0)
        filemenu.add_command(label="Import", command=self._import_doc)
        filemenu.add_command(label="Export Current", command=self._export_doc)
        filemenu.add_separator()
        filemenu.add_command(label="Export to Intraweb", command=self.export_and_launch_server)
        filemenu.add_separator()
        filemenu.add_command(label="Quit", command=self.destroy)
        menubar.add_cascade(label="File", menu=filemenu)
        # ---- Search UI (toolbar) ----
        self._search_var = tk.StringVar()
        self._search_after_id = None

        search_lbl = ttk.Label(self.toolbar, text="Search:")
        search_lbl.pack(side="left", padx=(6,2))

        self._search_entry = ttk.Entry(self.toolbar, textvariable=self._search_var, width=28)
        self._search_entry.pack(side="left", padx=(0,6))
        self._search_entry.insert(0, "title or text…")
        self._search_entry.bind("<FocusIn>", lambda e: _clear_placeholder())
        self._search_entry.bind("<KeyRelease>", lambda e: self._on_search_changed())

def _clear_placeholder():
    if self._search_entry.get() == "title or text…":
        self._search_entry.delete(0, "end")


        # View menu (adds TreeView entry + shortcut + depth)
        viewmenu = tk.Menu(menubar, tearoff=0)
        viewmenu.add_command(label="Document Tree\tCtrl+T", command=self.on_tree_button)
        viewmenu.add_separator()
