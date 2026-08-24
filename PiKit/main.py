import sys
try:
    from core import PiKitCore  # standalone: PiKit dir on sys.path
except ImportError:
    from .core import PiKitCore  # imported as the PiKit package
from modules.gui_tkinter import DemoKitGUI
# Plugins
from modules.opml_extras_plugin import install_opml_extras_into_app
from modules.save_as_text_plugin_v3 import install_save_as_text_into_app
from modules.image_render_overlay import attach_image_rendering
# NOTE: Do NOT import the old modules.opml_extras_plugin.
# NOTE: Do NOT import export_doc_patch; gui_tkinter already has robust _export_doc.

def main():
    if "--packaged-smoke-test" in sys.argv:
        import tkinter
        from PIL import Image
        print(f"pikit ok: tkinter={tkinter.TkVersion} pillow={Image.__version__}")
        return

    # The core owns the non-visual lifecycle (store, AI, command processor,
    # Dream processor, inbox paths) using explicit product-root paths.
    core = PiKitCore()

    # Launch the Tk GUI as a view over the core.
    app = DemoKitGUI(core=core)
    core.status_callback = lambda msg: app.status.set(msg)
    attach_image_rendering(app)

    # Wire plugins
    install_opml_extras_into_app(app)      # URL→OPML, Convert→OPML, Batch Convert
    install_save_as_text_into_app(app)     # Save Binary As Text (DB-safe)

    # AI Communicator handoffs use the same document-import logic as before,
    # but the core now owns inbox consumption; the GUI only schedules it and
    # reveals newly imported documents.
    def _on_handoff_imported(doc_id: int) -> None:
        app._refresh_index()
        app._open_doc_id(doc_id)

    def _poll_inbox() -> None:
        core.consume_inbox_once(on_imported=_on_handoff_imported)
        app.after(750, _poll_inbox)

    app.after_idle(_poll_inbox)

    app.mainloop()

if __name__ == "__main__":
    main()
