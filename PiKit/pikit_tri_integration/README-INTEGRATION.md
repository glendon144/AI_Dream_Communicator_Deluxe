# PiKit — Tri-Model Integration Bundle

This bundle adds a three-stage pipeline (Immediate → Long → Synthesis) to PiKit with:
- `modules/tri_pipeline.py` — calls three different OpenAI models
- `modules/ai_memory.py` — tiny JSON memory stored in SQLite
- `modules/db_migrations.py` — idempotent table creation
- Patch snippets for `gui_tkinter.py` and `command_processor.py`

> No core refactors required. You can merge the small snippets manually if your file layout differs.

---

## 1) Files to copy

Copy the `modules/*.py` files into your PiKit `modules/` package:
- `tri_pipeline.py`
- `ai_memory.py`
- `db_migrations.py`

If you keep your DB helpers elsewhere, just import and call `ensure_ai_memory_table(conn)` once at app start.

---

## 2) Call the migration on startup

Where you initialize the DB (or once after app start), add:

```python
from modules.db_migrations import ensure_ai_memory_table
conn = store.get_connection()   # adapt to your accessor
ensure_ai_memory_table(conn)
```

This creates a tiny `ai_memory` table if it doesn't exist.

---

## 3) Add a GUI action “ASK (Tri)”

Search for where you register toolbar/menu actions in `gui_tkinter.py` and:
1. Add a menu/toolbar item that calls `ask_tri_action(self)`
2. Add the following function (merge names as needed):

```python
from concurrent.futures import ThreadPoolExecutor
from tkinter import messagebox
from modules.tri_pipeline import run_tri_pipeline
from modules.ai_memory import get_memory, set_memory

# Somewhere during GUI init:
self.executor = getattr(self, "executor", ThreadPoolExecutor(max_workers=2))

def ask_tri_action(self):
    doc_id = self.get_current_document_id()
    if not doc_id:
        messagebox.showinfo("PiKit", "Select a document (or text) first.")
        return
    selected_text = self.get_selected_text_or_document_body()

    conn = self.store.get_connection()
    memory = get_memory(conn, key="global")
    self.set_status("Running 3-model synthesis…")
    future = self.executor.submit(run_tri_pipeline, selected_text, memory)

    def on_done(fut):
        try:
            out = fut.result()
        except Exception as e:
            self.set_status("Ready")
            messagebox.showerror("PiKit", f"Tri-model error: {e}")
            return

        # Create a NEW document and link to it
        new_id = self.store.create_document("Tri Synthesis", out.final)
        memory.setdefault("recent_immediate", [])
        memory["recent_immediate"] = (memory["recent_immediate"] + [out.immediate])[-10:]
        set_memory(conn, memory, key="global")

        # Replace selection with your Green Link™ helper
        self.replace_selection_with_green_link(doc_id, new_id)
        self.refresh_document_view(doc_id)
        self.set_status("Ready")

    future.add_done_callback(lambda f: self.after(0, on_done, f))
```

A small toolbar/menu wiring example is in `patches/gui_tkinter_snippet.py`.

---

## 4) CLI command: TRIASK

In your `command_processor.py`, register a command handler like this:

```python
def cmd_TRIASK(self, args):
    import shlex
    from modules.tri_pipeline import run_tri_pipeline
    from modules.ai_memory import get_memory, set_memory

    if not args:
        return "Usage: TRIASK <doc_id> [--instructions "..."]"

    parts = shlex.split(args)
    doc_id = int(parts[0])
    instructions = ""
    if "--instructions" in parts:
        i = parts.index("--instructions")
        if i + 1 < len(parts):
            instructions = parts[i+1]

    text = self.store.get_document_body(doc_id)
    conn = self.store.get_connection()
    memory = get_memory(conn, key="global")

    out = run_tri_pipeline(text, memory, instructions=instructions)
    new_id = self.store.create_document("Tri Synthesis", out.final)

    memory.setdefault("recent_immediate", [])
    memory["recent_immediate"] = (memory["recent_immediate"] + [out.immediate])[-10:]
    set_memory(conn, memory, key="global")

    # Insert a link in the source doc
    self.hypertext.insert_green_link(doc_id, new_id)  # adapt to your helper
    return f"Created doc {new_id} via TRIASK"
```

A minimal command-registration example is in `patches/command_processor_snippet.py`.

---

## 5) Environment variables / model selection

- `OPENAI_API_KEY`
- `IMMEDIATE_MODEL` (default: `gpt-4o-mini`)
- `LONG_MODEL` (default: `o3-mini`)
- `SYNTH_MODEL` (default: `gpt-5`, falls back to `gpt-4.1` inside code)

Expose these in your PiKit Settings if you wish; set them in the environment before launching PiKit.

---

## 6) Smoke test

1. Select text in a document → click **AI → ASK (Tri)**  
2. A new document titled **Tri Synthesis** appears with the final answer.  
3. The selected text is replaced with a **green clickable link** to the new doc.  
4. Run `TRIASK 1 --instructions "tone: concise"` in the CLI; verify it creates/links.  

Done!
