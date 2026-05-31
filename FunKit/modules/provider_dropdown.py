from __future__ import annotations
import tkinter as tk
from tkinter import ttk
from typing import Optional, Callable
from .provider_registry import registry


class ProviderDropdown(ttk.Frame):
    def __init__(
        self,
        parent,
        status_cb: Optional[Callable[[str, str], None]] = None,
        on_change: Optional[Callable[[str, object], None]] = None,
        **kwargs,
    ):
        super().__init__(parent, **kwargs)
        self.status_cb = status_cb
        self.on_change = on_change

        ttk.Label(self, text="Provider:").grid(
            row=0, column=0, padx=(0, 6), pady=4, sticky="w"
        )

        self._labels = registry.list_labels()
        self._label_by_key = {k: lbl for k, lbl in self._labels}
        self._key_by_label = {lbl: k for k, lbl in self._labels}

        self.var = tk.StringVar()
        width = max(12, max((len(lbl) for _, lbl in self._labels), default=12))
        self.cbo = ttk.Combobox(
            self,
            state="readonly",
            width=width,
            values=[lbl for _, lbl in self._labels],
            textvariable=self.var,
        )

        init_key = registry.read_selected()
        init_label = self._label_by_key.get(
            init_key, (self._labels[0][1] if self._labels else "Provider")
        )
        self.var.set(init_label)
        self.cbo.grid(row=0, column=1, padx=(0, 8), pady=4, sticky="ew")
        self.grid_columnconfigure(1, weight=1)
        self.cbo.bind("<<ComboboxSelected>>", self._on_changed)

        self._notify_status()

    def current_key(self) -> str:
        return self._key_by_label.get(self.var.get(), registry.read_selected())

    def current_config(self):
        return registry.get(self.current_key())

    def _on_changed(self, _evt=None):
        key = self.current_key()
        cfg = registry.get(key)
        registry.write_selected(key)
        self._notify_status()
        if self.on_change:
            self.on_change(key, cfg)

    def _notify_status(self):
        if not self.status_cb:
            return
        cfg = registry.get(self.current_key())
        self.status_cb(cfg.label, cfg.model)
