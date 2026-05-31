import tkinter as tk
from tkinter import ttk

class MarqueeStatusBar(ttk.Frame):
    """
    Grid‑only scrolling status bar. Call .set_text(...) for a static line,
    or .push(msg) to append to the rotating queue. Use .start()/.stop() to control.
    """
    def __init__(self, parent, height=22, speed_px=2, interval_ms=40, **kwargs):
        super().__init__(parent, **kwargs)
        self.canvas = tk.Canvas(self, height=height, highlightthickness=0, bd=0)
        self.canvas.grid(row=0, column=0, sticky="ew")
        self.columnconfigure(0, weight=1)

        self._items: list[str] = []
        self._idx = 0
        self._text_item = None
        self._x = 0
        self._speed = speed_px
        self._interval = interval_ms
        self._running = False
        self._cur_text = ""

        self.bind("<Configure>", lambda e: self._redraw())

    def _redraw(self):
        w = self.winfo_width()
        self.canvas.config(width=w)
        self._draw_text(self._cur_text or " ")

    def _draw_text(self, text: str):
        self.canvas.delete("all")
        self._cur_text = text
        w = self.winfo_width()
        pad = 40  # gap between repeats
        self._text_item = self.canvas.create_text(w, 12, anchor="w", text=text)
        bbox = self.canvas.bbox(self._text_item) or (0, 0, 0, 0)
        text_w = bbox[2] - bbox[0]
        self.canvas.create_text(w + text_w + pad, 12, anchor="w", text=text)
        self._x = w

    def _tick(self):
        if not self._running:
            return
        for item in self.canvas.find_all():
            self.canvas.move(item, -self._speed, 0)
        items = self.canvas.find_all()
        if items:
            bbox = self.canvas.bbox(items[0])
            if bbox and bbox[2] < 0:
                self._advance_queue()
        self.after(self._interval, self._tick)

    def _advance_queue(self):
        if self._items:
            self._idx = (self._idx + 1) % len(self._items)
            nxt = self._items[self._idx]
        else:
            nxt = self._cur_text
        self._draw_text(nxt)

    def set_text(self, text: str):
        self._items = [text]
        self._idx = 0
        self._draw_text(text)

    def push(self, text: str):
        if not text:
            return
        self._items.append(text)
        if len(self._items) == 1:
            self.set_text(text)

    def replace_queue(self, messages: list[str]):
        self._items = [m for m in messages if m]
        self._idx = 0
        self._draw_text(self._items[0] if self._items else " ")

    def start(self):
        if self._running:
            return
        self._running = True
        self._tick()

    def stop(self):
        self._running = False
