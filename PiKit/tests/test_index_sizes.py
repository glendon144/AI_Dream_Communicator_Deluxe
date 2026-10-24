"""Exercise index rendering without opening a Tk window."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.document_store import DocumentStore
from modules.gui_tkinter import DemoKitGUI


class IndexSizeTests(unittest.TestCase):
    def test_full_payload_sizes_in_index_and_search(self):
        store = DocumentStore(":memory:")
        self.addCleanup(store.conn.close)
        cases = [
            ("long text", "Long document body. " * 20, "400 B"),
            ("unicode", "é " * 40, "120 B"),
            ("binary", b"\x00\xff" * 100, "200 B"),
            ("empty", "", "0 B"),
        ]
        expected = {}
        for title, body, size in cases:
            expected[store.add_document("document " + title, body)] = size

        rows = store.get_document_index()
        long_row = next(row for row in rows if row["title"] == "document long text")
        self.assertEqual(len(long_row["description"]), 60)
        self.assertEqual(long_row["body"], cases[0][1])

        app = SimpleNamespace(doc_store=store, sidebar=MagicMock())
        app._approx_payload_size = DemoKitGUI._approx_payload_size.__get__(app)

        def check_sizes():
            actual = {
                call.kwargs["values"][0]: call.kwargs["values"][2]
                for call in app.sidebar.insert.call_args_list
            }
            self.assertEqual(actual, expected)

        DemoKitGUI._refresh_index(app)
        check_sizes()
        app.sidebar.insert.reset_mock()
        with patch("modules.gui_tkinter.simpledialog.askstring", return_value="document"):
            DemoKitGUI._on_search_clicked(app)
        check_sizes()


if __name__ == "__main__":
    unittest.main()
