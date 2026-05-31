class MemoryEditor:
    def __init__(self, app):
        self.app = app
        self.win = tk.Toplevel(app)
        self.win.title("AI Memory")
        self.win.geometry("840x640")
        
        # Initialize presets and widgets
        self._setup_widgets()
        self._load_memory()
        
    def _setup_widgets(self):
        # Scope toggle
        mode_frame = ttk.Frame(self.win)
        mode_frame.pack(fill="x", padx=10, pady=10)
        ttk.Label(mode_frame, text="Scope:").pack(side="left")
        self.mode_var = tk.StringVar(value="global")
        ttk.Radiobutton(mode_frame, text="Global", variable=self.mode_var, value="global").pack(side="left", padx=5)
        doc_id = self.app.current_doc_id
        ttk.Radiobutton(mode_frame, text=f"Doc {doc_id}" if doc_id else "Doc", 
                        variable=self.mode_var, value="doc", state="normal" if doc_id else "disabled").pack(side="left", padx=5)

        # Action buttons
        btn_frame = ttk.Frame(self.win)
        btn_frame.pack(fill="x", padx=10, pady=5)
        ttk.Button(btn_frame, text="Load", command=self._load_memory).pack(side="left")
        ttk.Button(btn_frame, text="Save", command=self._save_memory).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Clear", command=self._clear_memory).pack(side="left")
        
        # Presets menu
        preset_menu = ttk.Menubutton(btn_frame, text="Presets")
        preset_menu.pack(side="left", padx=10)
        menu = tk.Menu(preset_menu, tearoff=0)
        for name in PRESETS:
            menu.add_command(label=name, command=lambda n=name: self._apply_preset(n))
        preset_menu.config(menu=menu)

        # JSON sanitizer toggle
        self.sanitize_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(btn_frame, text="Sanitize JSON", variable=self.sanitize_var).pack(side="right")
        
        # Preview/Copy buttons
        ttk.Button(btn_frame, text="Preview → Model Text", command=self._preview_model_text).pack(side="right", padx=5)
        ttk.Button(btn_frame, text="Copy → Model Text", command=self._copy_model_text).pack(side="right")

        # JSON editor
        editor_frame = ttk.Frame(self.win)
        editor_frame.pack(fill="both", expand=True, padx=10, pady=5)
        scroll_y = ttk.Scrollbar(editor_frame)
        scroll_x = ttk.Scrollbar(editor_frame, orient="horizontal")
        self.editor = tk.Text(editor_frame, wrap="none", font=("TkFixedFont", 10))
        self.editor.config(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        scroll_y.config(command=self.editor.yview)
        scroll_x.config(command=self.editor.xview)
        self.editor.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")
        editor_frame.rowconfigure(0, weight=1)
        editor_frame.columnconfigure(0, weight=1)

        # Status bar
        self.status_var = tk.StringVar()
        ttk.Label(self.win, textvariable=self.status_var).pack(fill="x", padx=10, pady=5)

    def _get_current_key(self):
        return f"doc:{self.app.current_doc_id}" if self.mode_var.get() == "doc" else "global"

    def _load_memory(self):
        conn = _get_conn(self.app)
        key = self._get_current_key()
        try:
            memory = get_memory(conn, key) or {}
            self.editor.delete("1.0", "end")
            self.editor.insert("1.0", json.dumps(memory, indent=2, ensure_ascii=False))
            self.status_var.set(f"Loaded: {key}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load memory: {str(e)}")

    def _save_memory(self):
        conn = _get_conn(self.app)
        key = self._get_current_key()
        try:
            data = json.loads(self.editor.get("1.0", "end"))
            set_memory(conn, data, key)
            self.status_var.set(f"Saved: {key}")
        except Exception as e:
            messagebox.showerror("Error", f"Invalid JSON: {str(e)}")

    def _clear_memory(self):
        if messagebox.askyesno("Confirm", "Clear memory?"):
            self.editor.delete("1.0", "end")
            self.editor.insert("1.0", "{}")
            self.status_var.set("Memory cleared")

    def _apply_preset(self, name):
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", json.dumps(PRESETS[name], indent=2))
        self.status_var.set(f"Applied preset: {name}")

    def _get_model_text(self):
        try:
            data = json.loads(self.editor.get("1.0", "end"))
            if self.sanitize_var.get():
                return sanitize_json_to_plain(data, get_pikit_sanitize_options())
            return json.dumps(data, indent=2)
        except Exception:
            return ""

    def _preview_model_text(self):
        text = self._get_model_text()
        if not text: return
        preview = tk.Toplevel()
        preview.title("Model Text Preview")
        text_widget = tk.Text(preview, wrap="none", font=("TkFixedFont", 10))
        text_widget.insert("1.0", text)
        text_widget.config(state="disabled")
        text_widget.pack(fill="both", expand=True)

    def _copy_model_text(self):
        text = self._get_model_text()
        if text:
            self.win.clipboard_clear()
            self.win.clipboard_append(text)
            self.status_var.set("Copied to clipboard")

# Integration point
def open_memory_dialog(app):
    MemoryEditor(app)
