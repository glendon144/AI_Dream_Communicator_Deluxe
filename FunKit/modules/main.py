import argparse

from modules.app_runtime import build_processor
from modules.gui_tkinter import DemoKitGUI
from modules.text_interface import run_text_loop


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--text",
        action="store_true",
        help="Run in text-only mode (CLI REPL)",
    )
    args = parser.parse_args()

    store, _ai, processor = build_processor()

    if args.text:
        run_text_loop(store, processor)
        return

    app = DemoKitGUI(store, processor)
    app.mainloop()


if __name__ == "__main__":
    main()
