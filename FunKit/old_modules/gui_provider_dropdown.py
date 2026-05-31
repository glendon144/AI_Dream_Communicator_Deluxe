# at top
import tkinter as tk
from tkinter import ttk
from modules.provider_registry import registry
from modules.ai_interface import AIInterface

# in your App.__init__(...)
self.provider_var = tk.StringVar(value=registry.read_selected())

# Build dropdown (e.g., in a toolbar frame)
provider_frame = ttk.Frame(self.toolbar)  # adapt to your layout
provider_frame.pack(side="left", padx=6)

ttk.Label(provider_frame, text="Provider:").pack(side="left")
labels = registry.list_labels()  # [(key, label), ...]
keys, values = zip(*labels) if labels else ([], [])
self.provider_combo = ttk.Combobox(provider_frame, state="readonly",
                                   values=[lbl for _, lbl in labels])
# map label back to key
def _label_to_key(lbl: str) -> str:
    for k, l in labels:
        if l == lbl:
            return k
    return registry.default_key

# Initialize UI to stored selection
init_key = registry.read_selected()
init_label = dict(labels).get(init_key, labels[0][1] if labels else "OpenAI")
self.provider_combo.set(init_label)
self.provider_combo.pack(side="left")

def on_provider_change(event=None):
    chosen_label = self.provider_combo.get()
    key = _label_to_key(chosen_label)
    registry.write_selected(key)
    # Optional: update a status bar / ticker with current model
    cfg = registry.get(key)
    if hasattr(self, "set_ticker_text"):
        self.set_ticker_text(f"{cfg.label} • {cfg.model}")

self.provider_combo.bind("<<ComboboxSelected>>", on_provider_change)

# wherever you run a chat/completion:
def run_chat(self, user_text: str):
    key = registry.read_selected()
    ai = AIInterface(provider_key=key)
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": user_text}
    ]
    reply = ai.chat(messages)
    self.render_ai_reply(reply)

