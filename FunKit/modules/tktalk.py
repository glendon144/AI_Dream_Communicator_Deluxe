import os
import sys
import time
import tempfile
import subprocess
import base64
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import threading

from modules.tts_engine import get_piper_model_candidates, resolve_piper_bin, resolve_piper_model

# Get model path relative to project root
APP_ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(APP_ROOT)
TKTALK_INITIAL_TEXT_ENV = "FUNKIT_TALK_TEXT"
PIPER_CMD = resolve_piper_bin(os.environ.get("PIPER_CMD") or os.environ.get("PIPER_BIN") or "piper")
PIPER_MODEL = resolve_piper_model(os.environ.get("PIPER_MODEL"))

if not os.path.isfile(PIPER_MODEL):
    searched = "\n".join(f"- {candidate}" for candidate in get_piper_model_candidates(os.environ.get("PIPER_MODEL")))
    raise FileNotFoundError(
        "Piper voice model not found. Checked:\n"
        f"{searched}\n\n"
        "Please include a voice + matching .json file, or set the PIPER_MODEL environment variable."
    )
print(f"Using Piper binary: {PIPER_CMD}", flush=True)
print(f"Using Piper model: {PIPER_MODEL}", flush=True)

try:
    from modules.document_store import DocumentStore
except ImportError:
    from document_store import DocumentStore  # type: ignore

def synthesize_with_piper(text: str) -> bytes:
    with tempfile.TemporaryDirectory() as td:
        wav_path = os.path.join(td, "out.wav")
        cmd = [
            PIPER_CMD, "--model", PIPER_MODEL, "--output_file", wav_path, "--text", text
        ]
        subprocess.run(cmd, check=True)
        with open(wav_path, "rb") as f:
            return f.read()

def play_wav_bytes(wav_bytes: bytes):
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
        tf.write(wav_bytes)
        tf.flush()
        path = tf.name

    if sys.platform == "darwin":
        subprocess.run(["afplay", path])
    elif sys.platform.startswith("linux"):
        try:
            subprocess.run(["aplay", "-q", path], check=True)
        except Exception:
            subprocess.run(["ffplay", "-autoexit", "-nodisp", path], check=True)
    elif os.name == "nt":
        os.startfile(path)  # type: ignore

def _save_text_doc(store: DocumentStore, text: str) -> int:
    title_head = (text.splitlines()[0] if text.strip() else "TTS").strip()
    title = f"TTS Text: {time.strftime('%Y-%m-%d %H:%M:%S')} — {title_head[:60]}"
    return store.add_document(title, text)

def _save_wav_doc(store: DocumentStore, wav_bytes: bytes, from_text_doc_id: int) -> int:
    b64 = base64.b64encode(wav_bytes).decode("ascii")
    title = f"TTS Audio: {time.strftime('%Y-%m-%d %H:%M:%S')} — from #{from_text_doc_id}"
    audio_id = store.add_document(title, b64)
    try:
        conn = store.get_connection() if hasattr(store, "get_connection") else store.conn
        conn.execute("UPDATE documents SET content_type=? WHERE id=?", ("audio/wav", audio_id))
        conn.commit()
    except Exception:
        pass
    return audio_id

def play_wav_doc(store: DocumentStore, doc_id: int):
    row = store.get_document(doc_id)
    if not row:
        raise RuntimeError(f"No document #{doc_id}")
    body = row["body"]
    if not body:
        raise RuntimeError("Empty document body")
    wav_bytes = base64.b64decode(body)
    play_wav_bytes(wav_bytes)

class CrawlCanvas(tk.Canvas):
    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.configure(bg="black", highlightthickness=0)
        self.lines = []
        self.running = True
        self.after(33, self._tick)

    def add_line(self, text: str):
        y = self.winfo_height() - 40 if self.winfo_height() > 0 else int(self["height"]) - 40
        scale = 1.0
        item = self.create_text(
            int(self.winfo_width()/2) or int(self["width"])//2,
            y,
            text=text,
            fill="#39FF14",
            font=("Helvetica", 20, "bold"),
            anchor="s",
        )
        shadow = self.create_text(
            int(self.winfo_width()/2) or int(self["width"])//2 + 2,
            y + 2,
            text=text,
            fill="#004d00",
            font=("Helvetica", 20, "bold"),
            anchor="s",
        )
        self.lines.append({"id": item, "shadow": shadow, "y": y, "scale": scale, "text": text})

    def _tick(self):
        if not self.running:
            return
        scroll_speed = 1.5
        scale_decay = 0.995
        kill_y = 40
        to_remove = []
        for entry in self.lines:
            entry["y"] -= scroll_speed
            entry["scale"] *= scale_decay
            y = entry["y"]
            s = max(0.5, entry["scale"])
            fs = int(20 * s)
            fs = max(10, fs)
            self.itemconfigure(entry["id"], font=("Helvetica", fs, "bold"))
            self.itemconfigure(entry["shadow"], font=("Helvetica", fs, "bold"))
            self.coords(entry["id"], self.winfo_width()//2, y)
            self.coords(entry["shadow"], self.winfo_width()//2 + 2, y + 2)
            if y < kill_y:
                to_remove.append(entry)
        for e in to_remove:
            self.delete(e["id"])
            self.delete(e["shadow"])
            self.lines.remove(e)
        self.after(33, self._tick)

class TkTalkApp(tk.Tk):
    def __init__(self, store_path: str = "storage/documents.db", initial_text: str = ""):
        super().__init__()
        self.store_path = store_path
        self.initial_text = initial_text or ""
        self.title("TkTalk — Piper TTS")
        self.geometry("800x600")
        self.store = DocumentStore(store_path)
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=0)

        self.crawl = CrawlCanvas(self, width=800, height=320)
        self.crawl.grid(row=0, column=0, sticky="nsew")

        frm = ttk.Frame(self)
        frm.grid(row=1, column=0, sticky="ew", padx=8, pady=8)
        frm.columnconfigure(0, weight=1)
        frm.columnconfigure(1, weight=0)
        frm.columnconfigure(2, weight=0)

        self.txt = tk.Text(frm, height=5, wrap="word")
        self.txt.grid(row=0, column=0, sticky="ew", padx=(0,8))
        if self.initial_text:
            self.txt.insert("1.0", self.initial_text)
        self.txt.focus_set()
        self.txt.bind("<Control-Return>", self._on_speak)

        speak_btn = ttk.Button(frm, text="Speak (Ctrl+Enter)", command=self._on_speak)
        speak_btn.grid(row=0, column=1, sticky="e")

        play_btn = ttk.Button(frm, text="Play WAV doc…", command=self._on_play_wav)
        play_btn.grid(row=0, column=2, sticky="e", padx=(8,0))

        m = tk.Menu(self); self.config(menu=m)
        filem = tk.Menu(m, tearoff=False); m.add_cascade(label="File", menu=filem)
        filem.add_command(label="Exit", command=self.destroy)
        toolsm = tk.Menu(m, tearoff=False); m.add_cascade(label="Tools", menu=toolsm)
        toolsm.add_command(label="Speak", command=self._on_speak)
        toolsm.add_command(label="Play WAV doc…", command=self._on_play_wav)

        self.status = tk.StringVar(value="Ready")
        ttk.Label(self, textvariable=self.status, anchor="w").grid(row=2, column=0, sticky="ew")

    def _on_speak(self, evt=None):
        text = self.txt.get("1.0", "end").strip()
        if not text:
            self.status.set("Type something to speak.")
            return
        self.crawl.add_line(text)
        self.status.set("Synthesizing with Piper…")
        self.txt.configure(state="disabled")
        threading.Thread(target=self._do_speak_save, args=(text,), daemon=True).start()

    def _do_speak_save(self, text: str):
        status_msg = ""
        error_msg = None
        try:
            local_store = DocumentStore(self.store_path)
            text_id = _save_text_doc(local_store, text)
            wav_bytes = synthesize_with_piper(text)
            play_wav_bytes(wav_bytes)  # Play immediately after synthesis!
            audio_id = _save_wav_doc(local_store, wav_bytes, from_text_doc_id=text_id)
            status_msg = f"Saved text #{text_id} and audio #{audio_id}. Playing now…"
        except Exception as e:
            error_msg = str(e)
        def mainthread_update():
            if error_msg:
                self.status.set(f"Error: {error_msg}")
                messagebox.showerror("TkTalk error", error_msg)
            else:
                self.status.set(status_msg)
            self.txt.configure(state="normal")
            self.txt.delete("1.0", "end")
            self.txt.focus_set()
        self.after(0, mainthread_update)

    def _on_play_wav(self):
        doc_id = simpledialog.askinteger("Play WAV", "Enter audio document ID:", parent=self)
        if not doc_id:
            return
        try:
            play_wav_doc(self.store, int(doc_id))
        except Exception as e:
            messagebox.showerror("Play error", str(e))

def launch(store_path: str = "storage/documents.db", initial_text: str = ""):
    app = TkTalkApp(store_path=store_path, initial_text=initial_text)
    app.mainloop()

if __name__ == "__main__":
    db_path = sys.argv[1] if len(sys.argv) > 1 else "storage/documents.db"
    initial_text = os.environ.get(TKTALK_INITIAL_TEXT_ENV) or os.environ.get("TKTALK_INITIAL_TEXT", "")
    if len(sys.argv) > 2:
        initial_text = " ".join(sys.argv[2:])
    launch(store_path=db_path, initial_text=initial_text)

