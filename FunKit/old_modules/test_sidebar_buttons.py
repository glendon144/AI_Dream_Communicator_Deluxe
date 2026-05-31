import tkinter as tk
import pytest


@pytest.fixture
def sidebar_app():
    root = tk.Tk()
    root.title("Sidebar-button test")
    root.geometry("300x250")

    sidebar_frame = tk.Frame(root, bg="#eeeeee")
    sidebar_frame.grid(row=0, column=0, sticky="ns")
    lb = tk.Listbox(sidebar_frame, width=20)
    lb.grid(row=0, column=0, sticky="ns")
    for i in range(1, 6):
        lb.insert(tk.END, f"Doc {i}")

    btn_frame = tk.Frame(sidebar_frame, bg="#cccccc")
    btn_frame.grid(row=1, column=0, pady=8)

    edit_clicked = {"called": False}
    delete_clicked = {"called": False}

    def on_edit():
        edit_clicked["called"] = True

    def on_delete():
        delete_clicked["called"] = True

    edit_button = tk.Button(btn_frame, text="Edit", command=on_edit)
    edit_button.pack(fill=tk.X)
    delete_button = tk.Button(btn_frame, text="Delete", command=on_delete)
    delete_button.pack(fill=tk.X, pady=4)

    editor = tk.Text(root, width=25)
    editor.grid(row=0, column=1, sticky="nsew")
    root.grid_rowconfigure(0, weight=1)
    root.grid_columnconfigure(1, weight=1)

    root.update_idletasks()
    root.update()

    yield {
        "root": root,
        "sidebar_frame": sidebar_frame,
        "btn_frame": btn_frame,
        "edit_button": edit_button,
        "delete_button": delete_button,
        "edit_clicked": edit_clicked,
        "delete_clicked": delete_clicked,
    }

    root.destroy()


def test_buttons_exist_under_sidebar(sidebar_app):
    sidebar_frame = sidebar_app["sidebar_frame"]
    btn_frame = sidebar_app["btn_frame"]
    edit_button = sidebar_app["edit_button"]
    delete_button = sidebar_app["delete_button"]

    assert edit_button.winfo_exists()
    assert delete_button.winfo_exists()
    assert edit_button.master is btn_frame
    assert delete_button.master is btn_frame
    assert btn_frame.master is sidebar_frame


def test_button_callbacks(sidebar_app):
    root = sidebar_app["root"]
    edit_button = sidebar_app["edit_button"]
    delete_button = sidebar_app["delete_button"]
    edit_clicked = sidebar_app["edit_clicked"]
    delete_clicked = sidebar_app["delete_clicked"]

    for button in (edit_button, delete_button):
        button.event_generate("<Enter>", x=1, y=1)
        button.event_generate("<ButtonPress-1>", x=1, y=1)
        button.event_generate("<ButtonRelease-1>", x=1, y=1)
        root.update_idletasks()
        root.update()

    assert edit_clicked["called"] is True
    assert delete_clicked["called"] is True
