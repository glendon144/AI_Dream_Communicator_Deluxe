# test_hyperlink_renderer.py
import tkinter as tk
from tkinter import messagebox
from modules.hyperlink_renderer import render_links

DEMO_TEXT = """Welcome to the PiKit link demo.

This is plain text. Below are some embedded links in the format [Label](doc:ID).

- Open the [Intro Doc](doc:1) to see a sample.
- Jump to the [API Reference](doc:42) for advanced knobs.
- Non-doc links like [OpenAI](https://openai.com) are ignored by this renderer.

You can edit this text and re-run render_links(...) to refresh the link tagging.
"""

def on_open_doc(doc_id: int):
    # Replace with your app's open logic
    print(f"[demo] open doc id: {doc_id}")
    try:
        messagebox.showinfo("Link Clicked", f"You clicked a link for doc:{doc_id}")
    except Exception:
        pass

def main():
    root = tk.Tk()
    root.title("Hyperlink Renderer Demo")

    # Optional: tweak link appearance via env vars before import
    # os.environ["PIKIT_LINK_COLOR"] = "#0a84ff"
    # os.environ["PIKIT_LINK_UNDERLINE"] = "1"  # or "0"

    text = tk.Text(root, wrap="word", font=("Segoe UI", 11))
    text.pack(fill="both", expand=True)

    # Populate text and render links
    text.insert("1.0", DEMO_TEXT)
    render_links(text, on_open_doc)

    # Simple toolbar to re-render after edits
    toolbar = tk.Frame(root)
    toolbar.pack(side="bottom", fill="x")
    tk.Button(toolbar, text="Re-Parse Links", command=lambda: render_links(text, on_open_doc)).pack(side="right", padx=6, pady=6)

    root.mainloop()

if __name__ == "__main__":
    main()
