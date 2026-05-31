from pathlib import Path
from modules.document_store import DocumentStore
from modules.command_processor import CommandProcessor
from modules.gui_tkinter import DemoKitGUI
from modules.ai_interface import AIInterface
from modules.memory_dialog import open_memory_dialog
from modules.opml_extras_plugin import install_opml_extras_into_app
from modules.save_as_text_plugin_v3 import install_save_as_text_into_app
from modules.image_render_overlay import attach_image_rendering

def main():
    # Create storage directories
    data_dir = Path("storage").absolute()
    data_dir.mkdir(parents=True, exist_ok=True)
    
    # Initialize core components
    doc_store = DocumentStore(db_path=str(data_dir / "documents.db"))
    ai = AIInterface()
    processor = CommandProcessor(doc_store, ai)
    
    # Initialize GUI
    app = DemoKitGUI(doc_store, processor)
    app.app_data_dir = str(data_dir / "data")  # Set application data directory
    
    # Attach plugins
    attach_image_rendering(app)
    open_memory_dialog(app)
    install_opml_extras_into_app(app)
    install_save_as_text_into_app(app)
    
    app.mainloop()

if __name__ == "__main__":
    main()
