
"""
image_render_overlay.py — Drop-in image rendering for FunKit/DemoKit GUI.

Usage:
    from image_render_overlay import attach_image_rendering
    attach_image_rendering(gui)

Features:
  • Renders images when a document body is bytes or a data URI (data:image/...;base64,...)
  • Fits image to content width by default; click to toggle 1:1 "Actual Size"
  • Adds File→ "Save Image As…" when an image is shown
  • Adds context-menu items: "Save Image As…" and "Copy Image (PNG)"
"""
import base64
from io import BytesIO

try:
    from PIL import Image, ImageTk
    _HAVE_PIL = True
except Exception:
    _HAVE_PIL = False

def attach_image_rendering(gui):
    if not _HAVE_PIL:
        return gui  # Pillow not installed; skip gracefully

    # Ensure we have a label holder under the Text widget
    def _ensure_img_label():
        # Expect text widget lives in a container laid out by grid
        parent = gui.text.master if hasattr(gui, "text") else gui
        if not hasattr(gui, "img_label") or not getattr(gui.img_label, "winfo_exists", lambda: False)():
            import tkinter as tk
            gui.img_label = tk.Label(parent)
            # Prefer to keep image below the text area
            try:
                gui.img_label.grid(row=1, column=0, sticky="ew", pady=(8, 0))
            except Exception:
                # Fallback: pack below
                try:
                    gui.img_label.pack(side="bottom", fill="x", pady=(8, 0))
                except Exception:
                    pass
            gui.img_label.bind("<Button-1>", lambda e: _toggle_size())
        return gui.img_label

    # State
    gui._last_pil_img = None
    gui._last_tk_img = None
    gui._image_actual_size = False

    def _clear_image():
        if hasattr(gui, "img_label") and getattr(gui.img_label, "winfo_exists", lambda: False)():
            try:
                gui.img_label.configure(image="")
                gui.img_label.image = None
            except Exception:
                pass
        gui._last_pil_img = None
        gui._last_tk_img = None
        gui._image_actual_size = False

    def _data_uri_to_bytes(s: str):
        # data:image/png;base64,....
        try:
            if not s.startswith("data:image/"):
                return None
            head, b64 = s.split(",", 1)
            return base64.b64decode(b64.encode("utf-8"))
        except Exception:
            return None

    def _render_image_from_bytes(data: bytes, title: str = ""):
        _ensure_img_label()
        try:
            pil = Image.open(BytesIO(bytes(data)))
        except Exception:
            return False
        gui._last_pil_img = pil
        _fit_to_width()
        return True

    def _fit_to_width():
        if gui._last_pil_img is None:
            return False
        # Determine max width from text widget geometry
        try:
            max_w = max(300, gui.text.winfo_width() - 24)
        except Exception:
            max_w = 900
        pil = gui._last_pil_img.copy()
        pil.thumbnail((max_w, 1200))  # preserve aspect
        tk_img = ImageTk.PhotoImage(pil)
        gui.img_label.configure(image=tk_img)
        gui.img_label.image = tk_img
        gui._last_tk_img = tk_img
        gui._image_actual_size = False
        return True

    def _show_actual_size():
        if gui._last_pil_img is None:
            return False
        tk_img = ImageTk.PhotoImage(gui._last_pil_img)
        gui.img_label.configure(image=tk_img)
        gui.img_label.image = tk_img
        gui._last_tk_img = tk_img
        gui._image_actual_size = True
        return True

    def _toggle_size():
        if gui._image_actual_size:
            _fit_to_width()
        else:
            _show_actual_size()

    # File/Context helpers
    def _save_image_as():
        import tkinter.filedialog as fd
        if gui._last_pil_img is None:
            return
        path = fd.asksaveasfilename(
            title="Save Image As",
            defaultextension=".png",
            filetypes=[("PNG Image", "*.png"), ("JPEG Image", "*.jpg;*.jpeg"), ("All Files", "*.*")],
            initialfile="document.png"
        )
        if not path:
            return
        # Choose format by extension
        ext = path.lower().rsplit(".", 1)[-1]
        fmt = "PNG" if ext not in {"jpg", "jpeg"} else "JPEG"
        try:
            im = gui._last_pil_img
            if fmt == "JPEG" and (im.mode in ("RGBA", "LA")):
                im = im.convert("RGB")  # drop alpha for JPEG
            im.save(path, fmt, quality=92)
        except Exception as e:
            try:
                from tkinter import messagebox
                messagebox.showerror("Save Image", f"Could not save image:\n{e}")
            except Exception:
                pass

    def _copy_image_to_clipboard_png():
        # Note: Tk clipboard doesn't support binary image natively.
        # We place PNG bytes as text/base64 for portability inside the app.
        if gui._last_pil_img is None:
            return
        try:
            buff = BytesIO()
            gui._last_pil_img.save(buff, format="PNG")
            b64 = base64.b64encode(buff.getvalue()).decode("ascii")
            gui.clipboard_clear()
            gui.clipboard_append(b64)
            try:
                from tkinter import messagebox
                messagebox.showinfo("Copy Image", "PNG placed on clipboard as base64 text.")
            except Exception:
                pass
        except Exception:
            pass

    # Wrap the GUI's renderer so images display automatically
    if hasattr(gui, "_orig_render_document"):
        # already wrapped earlier
        pass
    else:
        gui._orig_render_document = gui._render_document

        def _render_document_with_images(doc):
            # First, clear previous image
            _clear_image()

            # Quickly probe body & ctype
            if isinstance(doc, dict):
                body = doc.get("body")
                ctype = (doc.get("content_type") or "").lower()
                title = doc.get("title") or ""
            else:
                body = doc[2] if len(doc) > 2 else ""
                ctype = ""
                title = doc[1] if len(doc) > 1 else ""

            # Detect data URI
            if isinstance(body, str):
                data = _data_uri_to_bytes(body.strip())
                if data is not None:
                    if _render_image_from_bytes(data, title):
                        # still show a small caption in Text area
                        try:
                            gui.text.delete("1.0", "end")
                            gui.text.insert("1.0", f"{title or 'Image'} ({ctype or 'image'})\n")
                        except Exception:
                            pass
                        return
            # Detect raw bytes (likely imported via Directory Import)
            if isinstance(body, (bytes, bytearray)):
                if _render_image_from_bytes(body, title):
                    try:
                        gui.text.delete("1.0", "end")
                        gui.text.insert("1.0", f"{title or 'Image'} ({ctype or 'image'})\n")
                    except Exception:
                        pass
                    return

            # Fallback to original rendering
            return gui._orig_render_document(doc)

        gui._render_document = _render_document_with_images

    # Add menu/context entries
    try:
        menubar = gui.nametowidget(gui.winfo_toplevel().cget("menu"))
    except Exception:
        menubar = None
    if menubar:
        # Put under File menu if present
        try:
            last = menubar.index("end") or -1
            file_menu = None
            for i in range(last + 1):
                if menubar.type(i) == "cascade" and menubar.entrycget(i, "label").lower() == "file":
                    file_menu = menubar.nametowidget(menubar.entrycget(i, "menu"))
                    break
            if file_menu:
                file_menu.add_command(label="Save Image As…", command=_save_image_as)
        except Exception:
            pass

    ctx = getattr(gui, "context_menu", None)
    if ctx is not None:
        try:
            ctx.add_separator()
            ctx.add_command(label="Save Image As…", command=_save_image_as)
            ctx.add_command(label="Copy Image (PNG)", command=_copy_image_to_clipboard_png)
        except Exception:
            pass

    # Re-fit image when the text widget resizes (for responsive thumbnails)
    if hasattr(gui, "text"):
        try:
            gui.text.bind("<Configure>", lambda e: (not gui._image_actual_size) and _fit_to_width())
        except Exception:
            pass

    # Expose helpers
    gui.save_image_as = _save_image_as
    gui.copy_image_png = _copy_image_to_clipboard_png
    gui.toggle_image_size = _toggle_size
    gui.fit_image_to_width = _fit_to_width
    return gui
