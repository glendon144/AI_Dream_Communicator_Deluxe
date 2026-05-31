import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from queue import Empty, Queue

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PIPER_BIN = os.environ.get("PIPER_BIN") or os.environ.get("PIPER_CMD", "piper")
DEFAULT_PIPER_MODEL = os.path.expanduser(
    os.environ.get("PIPER_MODEL", str(PROJECT_ROOT / "voices" / "en_US-amy-low.onnx"))
)
DEFAULT_SOUND_PLAYER = os.environ.get("SOUND_PLAYER", "")


def _piper_model_has_sidecar(path: Path) -> bool:
    return Path(f"{path}.json").is_file()


def get_piper_model_candidates(path: str | None = None) -> list[Path]:
    explicit = os.path.expanduser(path) if path else None
    candidates = [
        explicit,
        DEFAULT_PIPER_MODEL,
        "~/piper/voices/en_US-amy-low.onnx",
        "~/piper/voices/en_US-amy-medium.onnx",
    ]

    seen: set[str] = set()
    ordered: list[Path] = []
    for candidate in candidates:
        if not candidate:
            continue
        normalized = str(Path(candidate).expanduser())
        if normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(Path(normalized))
    return ordered


def which(cmd: str):
    return shutil.which(cmd)


def resolve_piper_bin(path: str | None = None) -> str:
    candidate = os.path.expanduser(path or DEFAULT_PIPER_BIN)
    search_order = [
        candidate,
        os.path.expanduser("~/piper/piper"),
        os.path.expanduser("~/.local/share/pipx/venvs/piper-tts/bin/piper"),
        "/usr/bin/piper",
        "/usr/local/bin/piper",
        "piper",
    ]

    for entry in search_order:
        try:
            if os.path.isdir(entry):
                nested = os.path.join(entry, "piper")
                if os.path.isfile(nested) and os.access(nested, os.X_OK):
                    return nested
            if entry == "piper":
                found = which("piper")
                if found and os.access(found, os.X_OK):
                    return found
            elif os.path.isfile(entry) and os.access(entry, os.X_OK):
                return entry
        except Exception:
            pass
    return candidate


def resolve_piper_model(path: str | None = None) -> str:
    candidates = get_piper_model_candidates(path)

    for candidate in candidates:
        if candidate.is_file() and _piper_model_has_sidecar(candidate):
            return str(candidate)

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)

    return str(candidates[0]) if candidates else os.path.expanduser(DEFAULT_PIPER_MODEL)


def detect_player(sound_player: str = ""):
    if sound_player:
        return sound_player
    for candidate in ["ffplay", "paplay", "aplay", "afplay"]:
        found = which(candidate)
        if found:
            return found
    return None


def chunk_sentences(text: str, max_len: int = 280) -> list[str]:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return []

    parts = re.split(r"(?<=[.!?]) +", text)
    out: list[str] = []
    for sentence in parts:
        if not sentence:
            continue
        if len(sentence) <= max_len:
            out.append(sentence)
            continue

        buf: list[str] = []
        for token in re.split(r"([,;:])\s*", sentence):
            if sum(len(x) for x in buf) + len(token) <= max_len:
                buf.append(token)
            else:
                if buf:
                    out.append("".join(buf).strip())
                buf = [token]
        if buf:
            out.append("".join(buf).strip())
    return out


split_into_sentences = chunk_sentences


class PiperTTSWorker(threading.Thread):
    def __init__(
        self,
        speak_q: Queue,
        status_cb=None,
        bin_path: str | None = None,
        model_path: str | None = None,
        sound_player: str = "",
        pause: float = 0.04,
        save_wav: bool = False,
        log_redirect_factory=None,
    ):
        super().__init__(daemon=True)
        self.q = speak_q
        self.status_cb = status_cb
        self.pause = pause
        self.bin_path = resolve_piper_bin(bin_path)
        self.model_path = resolve_piper_model(model_path)
        self.player = detect_player(sound_player or DEFAULT_SOUND_PLAYER)
        self.save_wav = save_wav
        self.log_redirect_factory = log_redirect_factory
        self._stop_event = threading.Event()

    def status(self, msg: str):
        if self.status_cb:
            try:
                self.status_cb(msg)
            except Exception:
                pass

    def _redirects(self):
        if not self.log_redirect_factory:
            return {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "_log_handle": None}
        try:
            redirects = self.log_redirect_factory() or {}
        except Exception:
            redirects = {}
        redirects.setdefault("stdout", subprocess.DEVNULL)
        redirects.setdefault("stderr", subprocess.DEVNULL)
        redirects.setdefault("_log_handle", None)
        return redirects

    def _close_redirects(self, redirects):
        handle = redirects.get("_log_handle") if isinstance(redirects, dict) else None
        if handle:
            try:
                handle.close()
            except Exception:
                pass

    def _play_wav(self, path: str):
        if not self.player:
            self.status("No audio player found")
            return

        if self.player.endswith("aplay"):
            cmd = [self.player, "-q", path]
        elif self.player.endswith("paplay"):
            cmd = [self.player, path]
        elif self.player.endswith("afplay"):
            cmd = [self.player, path]
        elif self.player.endswith("ffplay"):
            cmd = [self.player, "-autoexit", "-nodisp", "-hide_banner", "-loglevel", "error", path]
        else:
            cmd = [self.player, path]

        redirects = self._redirects()
        try:
            subprocess.run(cmd, check=False, stdout=redirects["stdout"], stderr=redirects["stderr"])
        except Exception as e:
            self.status(f"Audio error: {e}")
        finally:
            self._close_redirects(redirects)

    def _synthesize_to_wav(self, text: str):
        tmp = tempfile.NamedTemporaryFile(prefix="piper_", suffix=".wav", delete=False)
        wav = tmp.name
        tmp.close()
        redirects = self._redirects()
        try:
            subprocess.run(
                [self.bin_path, "-m", self.model_path, "-f", wav],
                input=text.encode("utf-8"),
                check=True,
                stdout=redirects["stdout"],
                stderr=redirects["stderr"],
            )
            return wav
        except subprocess.CalledProcessError as e:
            self.status(f"Piper failed ({e.returncode})")
        except FileNotFoundError:
            self.status("piper not found")
        except Exception as e:
            self.status(f"TTS error: {e}")
        finally:
            self._close_redirects(redirects)

        try:
            os.remove(wav)
        except OSError:
            pass
        return None

    def _speak_chunk(self, text: str):
        if not text:
            return
        wav = self._synthesize_to_wav(text)
        if not wav:
            return
        try:
            self._play_wav(wav)
        finally:
            if not self.save_wav:
                try:
                    os.remove(wav)
                except OSError:
                    pass

    def run(self):
        while not self._stop_event.is_set():
            try:
                text = self.q.get(timeout=0.1)
            except Empty:
                continue
            if text is None:
                self.q.task_done()
                break
            self._speak_chunk(text)
            time.sleep(self.pause)
            self.q.task_done()

    def stop(self):
        self._stop_event.set()


class TTSManager:
    def __init__(self, **kwargs):
        self.speak_q: Queue = Queue()
        self.worker = PiperTTSWorker(self.speak_q, **kwargs)
        self.worker.start()

    def speak(self, text: str):
        text = (text or "").strip()
        if text:
            self.speak_q.put(text)

    def speak_text(self, text: str, chunk: bool = True, max_len: int = 280):
        chunks = chunk_sentences(text, max_len=max_len) if chunk else [(text or "").strip()]
        for chunk_text in chunks:
            self.speak(chunk_text)

    def shutdown(self):
        self.speak_q.put(None)
        self.worker.stop()
        self.worker.join(timeout=2)
