"""
Memory Dialog for PiKit — with Presets (+ JSON Sanitizer integration)
--------------------------------------------------------------------
Drop-in Tkinter dialog to view/edit AI memory stored in the `ai_memory` table.
Now includes one-click **Presets** to populate the editor with curated templates.

New in this version:
- "Sanitize JSON before sending" checkbox (toggles plain-text rendering)
- "Preview → Model Text" (shows a read-only preview of what would be sent)
- "Copy → Model Text" (copies that exact text to the clipboard)

Usage (in gui_tkinter.py):
--------------------------
from modules.memory_dialog import open_memory_dialog
...
toolsmenu = tk.Menu(menubar, tearoff=0)
toolsmenu.add_command(label="Memory…", command=lambda: open_memory_dialog(self))
menubar.add_cascade(label="Tools", menu=toolsmenu)

Expectations:
- `app.doc_store` has a `.conn` attribute (sqlite3 Connection).
- `app.current_doc_id` is the current document id or None.
"""

from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk, messagebox

from modules.ai_memory import get_memory, set_memory
# ⤵ Sanitizer module (your new helper file)
from modules.json_sanitizer import sanitize_json_to_plain, SanitizeOptions


PRESETS: dict[str, dict] = {
    "Crisp & practical": {
        "persona": "succinct, pragmatic, no filler",
        "style": "prefer bullet lists; show code first, words second",
        "rules": ["absolute dates", "no markdown tables"]
    },
    "Explainer mode": {
        "persona": "patient teacher who explains step-by-step",
        "style": "short paragraphs; give a tiny example",
        "rules": ["define jargon once", "avoid metaphors"]
    },
    "Translation helper (per-doc recommended)": {
        "persona": "bilingual technical editor",
        "style": "natural English, maintain formatting",
        "rules": ["preserve proper nouns", "keep numbers & units unchanged"]
    },
    "Structured output for coding": {
        "persona": "senior Python dev",
        "style": "show runnable snippet; add 3 bullet notes below",
        "rules": ["no external libraries unless asked", "PEP8-friendly"]
    },
    "Security red-team (ethical)": {
        "persona": "security analyst performing ethical red-team thinking",
        "style": "structured findings with risk, impact, likelihood; short, direct sentences",
        "rules": [
            "defensive guidance only",
            "no step-by-step exploit code",
            "focus on mitigations and detection",
            "assume legal and ethical boundaries"
        ]
    },
    "Marketing tone": {
        "persona": "friendly product marketer",
        "style": "benefit-led copy, short punchy sentences, clear call-to-action",
        "rules": ["avoid jargon", "be positive and concrete", "2–4 bullets max when listing"]
    },
    "Academic style": {
        "persona": "academic writer and editor",
        "style": "formal tone; include a 1–2 sentence abstract; cite sources inline (Author, Year) when provided",
        "rules": ["define key terms", "avoid rhetorical questions", "use objective voice"]
    }
}


def _get_conn(app) -> object | None:
    conn = getattr(app.doc_store, "conn", None)
    if conn:
        return conn
    if hasattr(app.doc_store, "get_connection"):
        try:
            return app.doc_store.get_connection()
        except Exception:
            return None
    return None


def _key_for_mode(mode: str, doc_id: int | None) -> str:
    if mode == "doc" and doc_id is not None:
        return f"doc:{doc_id}"
    return "global"


def open_memory_dialog(app) -> None:
    conn = _get_conn(app)
    if not conn:
        messagebox.showerror("PiKit", "No database connection found for memory editor.")
        return

    win = tk.Toplevel(app)
    win.title("AI Memory")
    win.geometry("840x640")
    win.transient(app)
    win.grab_set()

    # --- Mode selection: Global vs Doc memory ---
    mode_var = tk.StringVar(value="global")
    doc_id = getattr(app, "current_doc_id", None)

    frm_top = ttk.Frame(win)
    frm_top.pack(fill="x", padx=10, pady=(10, 6))

    ttk.Label(frm_top, text="Scope:").pack(side="left")

    rb_global = ttk.Radiobutton(frm_top, text="Global", value="global", variable=mode_var)
    rb_global.pack(side="left", padx=(8, 4))

    rb_doc = ttk.Radiobutton(frm_top, text=f"Doc {doc_id}" if doc_id else "Doc (none)", value="doc", variable=mode_var)
    rb_doc.pack(side="left", padx=(8, 4))
    if doc_id is None:
        rb_doc.state(["disabled"])

    # --- Buttons row & sanitizer toggle ---
    frm_btns = ttk.Frame(win)
    frm_btns.pack(fill="x", padx=10, pady=(0, 6))

    # Sanitizer toggle
    sanitize_var = tk.BooleanVar(value=False)
    chk = ttk.Checkbutton(frm_btns, text="Sanitize JSON before sending", variable=sanitize_var)
    chk.pack(side="right")

    def load_current():
        key = _key_for_mode(mode_var.get(), doc_id)
        data = get_memory(conn, key=key)
        try:
            text = json.dumps(data if isinstance(data, dict) else {}, indent=2, ensure_ascii=False)
        except Exception:
            text = "{}"
        txt.delete("1.0", "end")
        txt.insert("1.0", text)
        status_var.set(f"Loaded memory for key '{key}'")

    def parse_editor_json() -> dict:
        raw = txt.get("1.0", "end").strip()
        if not raw:
            return {}
        try:
            obj = json.loads(raw)
            if not isinstance(obj, dict):
                raise ValueError("Top-level JSON must be an object")
            return obj
        except Exception as e:
            raise ValueError(f"Invalid JSON: {e}")

    def save_current():
        key = _key_for_mode(mode_var.get(), doc_id)
        try:
            data = parse_editor_json()
        except ValueError as e:
            messagebox.showerror("PiKit", str(e))
            return
        try:
            set_memory(conn, data, key=key)
            status_var.set(f"Saved memory for key '{key}'")
        except Exception as e:
            messagebox.showerror("PiKit", f"Failed saving memory: {e}")

    def clear_current():
        key = _key_for_mode(mode_var.get(), doc_id)
        if not messagebox.askyesno("PiKit", f"Clear memory for '{key}'?"):
            return
        try:
            set_memory(conn, {}, key=key)
            txt.delete("1.0", "end")
            txt.insert("1.0", "{}\n")
            status_var.set(f"Cleared memory for key '{key}'")
        except Exception as e:
            messagebox.showerror("PiKit", f"Failed clearing memory: {e}")

    # Buttons (left side)
    ttk.Button(frm_btns, text="Load", command=load_current).pack(side="left")
    ttk.Button(frm_btns, text="Save", command=save_current).pack(side="left", padx=6)
    ttk.Button(frm_btns, text="Clear", command=clear_current).pack(side="left")

    # Preview / Copy actions (center)
    def build_model_text() -> str:
        """
        Returns the exact text you'd hand to the model for this memory block,
        honoring the sanitizer toggle.
        """
        try:
            obj = parse_editor_json()
        except ValueError as e:
            messagebox.showerror("PiKit", str(e))
            return ""
        if sanitize_var.get():
            # You can adjust options here globally if you like:
            opts = SanitizeOptions(
                indent=2,
                sort_keys=True,
                truncate_value_len=0,  # set e.g. 160 if you want shorter values
                width=0,               # set e.g. 88 to soft-wrap long strings
            )
            return sanitize_json_to_plain(obj, opts)
        else:
            # Raw JSON, but as pretty text (not braces removed)
            return json.dumps(obj, indent=2, ensure_ascii=False)

    def preview_model_text():
        text = build_model_text()
        if not text:
            return
        # Simple modal preview
        prev = tk.Toplevel(win)
        prev.title("Preview — Model Text")
        prev.geometry("720x520")
        prev.transient(win)
        prev.grab_set()

        yscroll = ttk.Scrollbar(prev, orient="vertical")
        xscroll = ttk.Scrollbar(prev, orient="horizontal")
        view = tk.Text(prev, wrap="none")
        view.configure(font=("TkFixedFont", 10), state="normal")

        yscroll.config(command=view.yview)
        xscroll.config(command=view.xview)
        view.config(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)

        view.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        prev.rowconfigure(0, weight=1)
        prev.columnconfigure(0, weight=1)

        view.insert("1.0", text)
        view.config(state="disabled")

        def close_prev():
            prev.grab_release()
            prev.destroy()

        prev.protocol("WM_DELETE_WINDOW", close_prev)

    def copy_model_text():
        text = build_model_text()
        if not text:
            return
        try:
            win.clipboard_clear()
            win.clipboard_append(text)
            status_var.set("Copied model text to clipboard.")
        except Exception as e:
            messagebox.showerror("PiKit", f"Clipboard error: {e}")

    ttk.Button(frm_btns, text="Preview → Model Text", command=preview_model_text).pack(side="left", padx=(12, 6))
    ttk.Button(frm_btns, text="Copy → Model Text", command=copy_model_text).pack(side="left")

    # --- Presets ---
    def apply_preset(name: str):
        template = PRESETS.get(name, {})
        txt.delete("1.0", "end")
        txt.insert("1.0", json.dumps(template, indent=2, ensure_ascii=False))
        status_var.set(f"Inserted preset: {name}")

    preset_btn = ttk.Menubutton(frm_btns, text="Presets")
    preset_menu = tk.Menu(preset_btn, tearoff=0)
    for pname in PRESETS:
        preset_menu.add_command(label=pname, command=lambda n=pname: apply_preset(n))
    preset_btn["menu"] = preset_menu
    preset_btn.pack(side="left", padx=(12, 0))

    # --- Text editor ---
    frm_text = ttk.Frame(win)
    frm_text.pack(fill="both", expand=True, padx=10, pady=(6, 4))

    yscroll = ttk.Scrollbar(frm_text, orient="vertical")
    xscroll = ttk.Scrollbar(frm_text, orient="horizontal")

    txt = tk.Text(frm_text, wrap="none", undo=True, maxundo=2000)
    txt.configure(font=("TkFixedFont", 10))

    yscroll.config(command=txt.yview)
    xscroll.config(command=txt.xview)
    txt.config(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)

    txt.grid(row=0, column=0, sticky="nsew")
    yscroll.grid(row=0, column=1, sticky="ns")
    xscroll.grid(row=1, column=0, sticky="ew")

    frm_text.rowconfigure(0, weight=1)
    frm_text.columnconfigure(0, weight=1)

    # --- Status bar ---
    status_var = tk.StringVar(value="")
    status = ttk.Label(win, textvariable=status_var, anchor="w")
    status.pack(fill="x", padx=10, pady=(0, 8))

    # Load initial content
    load_current()

    # Close behavior
    def on_close():
        win.grab_release()
        win.destroy()

    win.protocol("WM_DELETE_WINDOW", on_close)

