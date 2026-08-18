from pathlib import Path
import sys
from modules.app_runtime import build_processor
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
    Path("storage").mkdir(parents=True, exist_ok=True)
    doc_store, _ai, processor = build_processor()

    app = DemoKitGUI(doc_store, processor)
    attach_image_rendering(app)
    from modules.memory_dialog import open_memory_dialog
    app.bind("<Control-m>", lambda e: open_memory_dialog(app))

    install_opml_extras_into_app(app)
    install_save_as_text_into_app(app)

    app.mainloop()

if __name__ == "__main__":
    main()
