# --- Add near your imports ---
from concurrent.futures import ThreadPoolExecutor
from tkinter import messagebox
from modules.tri_pipeline import run_tri_pipeline
from modules.ai_memory import get_memory, set_memory

# --- In __init__ or setup ---
self.executor = getattr(self, "executor", ThreadPoolExecutor(max_workers=2))

# --- Action handler ---
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

        new_id = self.store.create_document("Tri Synthesis", out.final)

        memory.setdefault("recent_immediate", [])
        memory["recent_immediate"] = (memory["recent_immediate"] + [out.immediate])[-10:]
        set_memory(conn, memory, key="global")

        self.replace_selection_with_green_link(doc_id, new_id)
        self.refresh_document_view(doc_id)
        self.set_status("Ready")

    future.add_done_callback(lambda f: self.after(0, on_done, f))

# --- Wiring examples ---
# Toolbar: self.add_toolbar_button("ASK (Tri)", command=self.ask_tri_action)
# Menu: ai_menu.add_command(label="ASK (Tri)", command=self.ask_tri_action)
# Context menu: ctx.add_command(label="ASK (Tri)", command=self.ask_tri_action)
