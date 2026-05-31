from pathlib import Path
from modules.document_store import DocumentStore
from modules.command_processor import CommandProcessor
from modules.gui_tkinter import DemoKitGUI
from modules.ai_interface import AIInterface

def main():
    # Ensure the storage directory exists
    Path("storage").mkdir(parents=True, exist_ok=True)

    # Initialize the document store
    doc_store = DocumentStore("storage/documents.db")

    # Initialize the AI interface
    ai = AIInterface()

    # Initialize the command processor with doc store and AI
    processor = CommandProcessor(doc_store, ai)

    # Launch the GUI

    app = DemoKitGUI(doc_store, processor)
    app = DemoKitGUI(doc_store, processor)

    from modules.save_as_text_plugin import install_save_as_text_into_app
    install_save_as_text_into_app(app)

    app.mainloop()

if __name__ == "__main__":
    main()

