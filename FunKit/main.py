import sys
try:
    from core import FunKitCore  # standalone: FunKit dir on sys.path
except ImportError:
    from .core import FunKitCore  # imported as the FunKit package
from modules.gui_tkinter import DemoKitGUI
from modules.opml_bridge import install_opml_extras_into_app
from modules.save_as_text_plugin_v3 import install_save_as_text_into_app
from modules.image_render_overlay import attach_image_rendering


def main():
    if "--packaged-smoke-test" in sys.argv:
        import tkinter
        from PIL import Image
        print(f"funkit ok: tkinter={tkinter.TkVersion} pillow={Image.__version__}")
        return

    # The core owns the non-visual lifecycle (store, AI/provider wiring,
    # command processor, settings, dream memory publishing) using explicit
    # product-root paths.
    core = FunKitCore()

    # Launch the Tk GUI as a view over the core.
    app = DemoKitGUI(core=core)
    core.status_callback = app.status
    attach_image_rendering(app)
    from modules.memory_dialog import open_memory_dialog
    app.bind("<Control-m>", lambda e: open_memory_dialog(app))

    install_opml_extras_into_app(app)
    install_save_as_text_into_app(app)

    app.mainloop()

if __name__ == "__main__":
    main()
