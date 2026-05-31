import webbrowser
import tkinter as tk

# Try to use in-pane rendering if available
try:
    from tkinterweb import HtmlFrame  # install with:  python3 -m pip install tkinterweb
except Exception:
    HtmlFrame = None

def has_internal_renderer() -> bool:
    return HtmlFrame is not None

def make_frame(parent):
    """Return a widget suitable for embedding in the GUI."""
    if HtmlFrame is not None:
        return HtmlFrame(parent)
    # Fallback: show a notice; links will open in the system browser
    f = tk.Frame(parent)
    tk.Label(f, text="WebView fallback active.\nInstall 'tkinterweb' for in-pane pages.").pack(padx=8, pady=8)
    return f

def load_url(container, url: str) -> bool:
    """Load a URL into the container; fallback to system browser if needed."""
    if HtmlFrame is not None and isinstance(container, HtmlFrame):
        try:
            container.load_website(url)
            return True
        except Exception:
            pass
    webbrowser.open(url)
    return False

# Convenience used by some GUI call-sites
def open_url_in_pane(parent, url: str):
    frame = make_frame(parent)
    load_url(frame, url)
    return frame
