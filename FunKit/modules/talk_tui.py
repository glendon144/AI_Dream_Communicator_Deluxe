#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
talk_tui.py
- Streams model tokens; speaks natural-length phrases with Piper
- Prefers OpenAI-compatible chat completions
- Falls back to Mistral-style instruct prompt on legacy /completion endpoint
- Keeps short rolling conversation history
- Star Wars-style crawl: newest lines appear at the bottom and rise upward
- F6/F7 = crawl slower/faster; Ctrl+Space/F8 = pause/resume; F9 = logs overlay
- F12 = toggle "Speak Debug" — numeric/config stream lines are spoken when ON
"""

import os, re, json, time, threading, queue, tempfile, subprocess, curses
from collections import deque
import requests

from modules.tts_engine import PiperTTSWorker, chunk_sentences, detect_player, resolve_piper_bin

# =======================
# Config (env-overridable)
# =======================
COMPLETION_API_URL = os.environ.get("TALK_API_URL", "http://localhost:8080/completion")
CHAT_API_URL = os.environ.get(
    "TALK_CHAT_API_URL", "http://localhost:8080/v1/chat/completions"
)

PIPER_BIN = os.environ.get("PIPER_BIN", "/usr/local/bin/piper/piper")
PIPER_MODEL = os.path.expanduser(
    os.environ.get("PIPER_MODEL", "~/piper-voices/en_US-amy-low.onnx")
)
SOUND_PLAYER = os.environ.get("SOUND_PLAYER", "")

PRINT_MIN_CHARS = int(os.environ.get("PRINT_MIN_CHARS", "24"))
SPEAK_MIN_CHARS = int(
    os.environ.get("SPEAK_MIN_CHARS", "100")
)  # retained for env compatibility
SPEAK_PAUSE_SEC = float(os.environ.get("SPEAK_PAUSE_SEC", "0.04"))
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "8192"))
TEMPERATURE = float(os.environ.get("TEMPERATURE", "0.7"))
ROLL_STYLE = (os.environ.get("ROLL_STYLE", "box") or "box").strip().lower()
SAVE_WAV = os.environ.get("TALK_SAVE_WAV", "0") == "1"
LOG_FILE_ENV = os.environ.get("TALK_LOG_FILE", "").strip()

CRAWL_SPEED_LPS = float(os.environ.get("CRAWL_SPEED_LPS", "0.8"))
CRAWL_MIN_LPS = 0.15
CRAWL_MAX_LPS = 5.0

CHAT_MODEL = os.environ.get("TALK_CHAT_MODEL", "").strip()
SYSTEM_PROMPT = os.environ.get(
    "TALK_SYSTEM_PROMPT",
    "You are a helpful voice assistant. Reply naturally, warmly, and conversationally. "
    "Do not dump raw training-style text, metadata, or role labels. "
    "Keep answers suitable for spoken audio.",
).strip()
HISTORY_TURNS = int(os.environ.get("TALK_HISTORY_TURNS", "6"))
REQUEST_TIMEOUT = int(os.environ.get("TALK_REQUEST_TIMEOUT", "300"))

DEBUG_PREFIX = "[dbg] "
DEFAULT_STOP = ["</s>", "[INST]", "[/INST]", "<s>"]


# =======================
# Safe screen writers
# =======================
def _safe_addnstr(win, y, x, s, n, attr=0):
    try:
        h, w = win.getmaxyx()
        if y < 0 or y >= h or x < 0 or x >= w:
            return
        n = max(0, min(n, w - x - 1))
        if n > 0:
            win.addnstr(y, x, s, n, attr)
    except curses.error:
        pass


def _safe_addstr(win, y, x, s, attr=0):
    _safe_addnstr(win, y, x, s, len(s), attr)


# =======================
# Helpers
# =======================
PIPER_BIN = resolve_piper_bin(PIPER_BIN)
AUDIO_PLAYER = detect_player(SOUND_PLAYER)


def wrap_to_width(text, width):
    if width <= 10:
        return [text]
    words = re.split(r"(\s+)", text)
    out = []
    line = ""
    for w in words:
        if len(line) + len(w) <= width:
            line += w
        else:
            if line:
                out.append(line.rstrip())
            line = w.lstrip()
    if line:
        out.append(line.rstrip())
    return out or [""]


# =======================
# Sentence-based accumulators
# =======================
class SentenceAccumulator:
    """
    Collects streaming text and emits only complete sentences.
    No length-triggered flushes during normal streaming.
    """

    SENTENCE_RE = re.compile(r'(.+?[.!?]["\')\]]*)(?=\s+|$)', re.DOTALL)

    def __init__(self):
        self.buf = ""

    def push(self, s):
        self.buf += s
        out = []

        while True:
            m = self.SENTENCE_RE.match(self.buf.strip())
            if not m:
                break

            sentence = m.group(1).strip()
            consumed = self.buf.find(sentence) + len(sentence)
            out.append(sentence)
            self.buf = self.buf[consumed:].lstrip()

            # If the buffer starts with text that is not yet sentence-terminated, stop.
            if not self.buf:
                break

            # Continue only if another full sentence seems present.
            probe = self.buf.strip()
            if not self.SENTENCE_RE.match(probe):
                break

        return out

    def flush(self):
        tail = self.buf.strip()
        self.buf = ""
        return [tail] if tail else []


# =======================
# Logging
# =======================
def get_log_file():
    if LOG_FILE_ENV:
        return LOG_FILE_ENV, False
    tmp = tempfile.NamedTemporaryFile(prefix="talk_tui_", suffix=".log", delete=False)
    path = tmp.name
    tmp.close()
    return path, True


LOG_PATH, LOG_IS_TEMP = get_log_file()


def log_line(msg):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def proc_io_redirects():
    logf = open(LOG_PATH, "ab")
    return {"stdout": logf, "stderr": logf, "_log_handle": logf}


def tail_file(path, max_bytes=200_000):
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            if size > max_bytes:
                f.seek(-max_bytes, os.SEEK_END)
            data = f.read()
        return data.decode("utf-8", "replace").splitlines()
    except Exception:
        return ["<no log data>"]


# =======================
# Stream filtering
# =======================
def _looks_like_debug(s: str) -> bool:
    if not s:
        return True
    if len(s) > 600:
        return True
    if re.search(
        r'"(timings|samplers|mirostat|top_p|min_p|temperature|logit_bias|tokens_cached|xtc|n_probs|grammar|dry_|speculative\.)"',
        s,
    ):
        return True
    core = re.sub(r'[\s.,:;+\-eE/\\"]', "", s)
    digits = sum(ch.isdigit() for ch in core)
    return digits > 0 and digits / max(1, len(core)) > 0.6


def _extract_stream(line: str):
    if not line:
        return None, None

    if line.startswith("data:"):
        line = line[5:].strip()

    if line == "[DONE]":
        return None, None

    if line and line[0] in "{[":
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                if isinstance(obj.get("content"), str):
                    return obj["content"], False
                if isinstance(obj.get("token"), str):
                    return obj["token"], False
                if "choices" in obj and obj["choices"]:
                    choice = obj["choices"][0]
                    delta = choice.get("delta") or {}
                    if isinstance(delta.get("content"), str):
                        return delta["content"], False
                    msg = choice.get("message") or {}
                    if isinstance(msg.get("content"), str):
                        return msg["content"], False
                    txt = choice.get("text")
                    if isinstance(txt, str):
                        return txt, False
            return (json.dumps(obj, ensure_ascii=False), True)
        except json.JSONDecodeError:
            pass

    if _looks_like_debug(line):
        return line, True
    return line, False


# =======================
# Prompt builders
# =======================
def trim_history(history, max_turns=HISTORY_TURNS):
    if max_turns <= 0:
        return []
    max_msgs = max_turns * 2
    return history[-max_msgs:]


def build_messages(history, user_text):
    msgs = []
    if SYSTEM_PROMPT:
        msgs.append({"role": "system", "content": SYSTEM_PROMPT})
    for role, content in trim_history(history):
        msgs.append({"role": role, "content": content})
    msgs.append({"role": "user", "content": user_text})
    return msgs


def build_instruct_prompt(history, user_text):
    turns = trim_history(history)
    prompt_parts = []
    sys_block = SYSTEM_PROMPT.strip()

    if not turns:
        if sys_block:
            return f"<s>[INST] {sys_block}\n\n{user_text.strip()} [/INST]"
        return f"<s>[INST] {user_text.strip()} [/INST]"

    first_user_done = False

    for role, content in turns:
        content = content.strip()
        if role == "user":
            if not first_user_done:
                combined = f"{sys_block}\n\n{content}" if sys_block else content
                prompt_parts.append(f"<s>[INST] {combined} [/INST]")
                first_user_done = True
            else:
                prompt_parts.append(f"<s>[INST] {content} [/INST]")
        elif role == "assistant":
            prompt_parts.append(f" {content}</s>")

    if not first_user_done:
        combined = (
            f"{sys_block}\n\n{user_text.strip()}" if sys_block else user_text.strip()
        )
        prompt_parts.append(f"<s>[INST] {combined} [/INST]")
    else:
        prompt_parts.append(f"<s>[INST] {user_text.strip()} [/INST]")

    return "".join(prompt_parts)


# =======================
# Model I/O
# =======================
class ModelRequestError(Exception):
    pass


def _post_stream(url, payload, timeout=REQUEST_TIMEOUT):
    headers = {"Accept": "text/event-stream"}
    log_line(f"POST stream -> {url}")
    log_line(f"payload keys: {list(payload.keys())}")
    r = requests.post(url, json=payload, headers=headers, stream=True, timeout=timeout)
    r.raise_for_status()
    saw = False
    for raw in r.iter_lines(decode_unicode=True):
        if not raw:
            continue
        saw = True
        text, is_dbg = _extract_stream(raw.strip())
        if text is None:
            continue
        yield (text, bool(is_dbg))
    if not saw:
        raise ModelRequestError(f"empty streaming response from {url}")


def stream_chat_response(
    user_text, history, include_debug=False, timeout=REQUEST_TIMEOUT
):
    payload = {
        "messages": build_messages(history, user_text),
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
        "stream": True,
    }
    if CHAT_MODEL:
        payload["model"] = CHAT_MODEL

    for text, is_dbg in _post_stream(CHAT_API_URL, payload, timeout=timeout):
        if is_dbg and not include_debug:
            continue
        yield (text, is_dbg)


def fetch_chat_response(user_text, history, timeout=REQUEST_TIMEOUT):
    payload = {
        "messages": build_messages(history, user_text),
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
        "stream": False,
    }
    if CHAT_MODEL:
        payload["model"] = CHAT_MODEL

    log_line(f"POST full chat -> {CHAT_API_URL}")
    r = requests.post(CHAT_API_URL, json=payload, timeout=timeout)
    r.raise_for_status()
    try:
        obj = r.json()
    except Exception:
        return r.text.strip()

    if isinstance(obj, dict):
        if "choices" in obj and obj["choices"]:
            choice = obj["choices"][0]
            msg = choice.get("message") or {}
            if isinstance(msg.get("content"), str):
                return msg["content"].strip()
            txt = choice.get("text")
            if isinstance(txt, str):
                return txt.strip()
        if "content" in obj:
            return str(obj["content"]).strip()
    return str(obj).strip()


def stream_completion_response(
    user_text, history, include_debug=False, timeout=REQUEST_TIMEOUT
):
    prompt = build_instruct_prompt(history, user_text)
    payload = {
        "prompt": prompt,
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
        "stream": True,
        "stop": DEFAULT_STOP,
    }

    for text, is_dbg in _post_stream(COMPLETION_API_URL, payload, timeout=timeout):
        if is_dbg and not include_debug:
            continue
        yield (text, is_dbg)


def fetch_completion_response(user_text, history, timeout=REQUEST_TIMEOUT):
    prompt = build_instruct_prompt(history, user_text)
    payload = {
        "prompt": prompt,
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
        "stop": DEFAULT_STOP,
    }

    log_line(f"POST full completion -> {COMPLETION_API_URL}")
    r = requests.post(COMPLETION_API_URL, json=payload, timeout=timeout)
    r.raise_for_status()
    try:
        obj = r.json()
    except Exception:
        return r.text.strip()

    if isinstance(obj, dict):
        if "content" in obj:
            return str(obj["content"]).strip()
        if "choices" in obj and obj["choices"]:
            choice = obj["choices"][0]
            msg = choice.get("message") or {}
            if isinstance(msg.get("content"), str):
                return msg["content"].strip()
            txt = choice.get("text")
            if isinstance(txt, str):
                return txt.strip()
    return str(obj).strip()


def stream_assistant_reply(
    user_text, history, include_debug=False, timeout=REQUEST_TIMEOUT
):
    try:
        gen = stream_chat_response(
            user_text, history, include_debug=include_debug, timeout=timeout
        )
        return gen, "chat"
    except Exception as e:
        log_line(f"chat stream setup failed: {e!r}")

    try:
        gen = stream_completion_response(
            user_text, history, include_debug=include_debug, timeout=timeout
        )
        return gen, "completion"
    except Exception as e:
        log_line(f"completion stream setup failed: {e!r}")

    raise ModelRequestError("unable to start chat or completion streaming")


def fetch_assistant_reply(user_text, history, timeout=REQUEST_TIMEOUT):
    try:
        return fetch_chat_response(user_text, history, timeout=timeout), "chat"
    except Exception as e:
        log_line(f"full chat failed: {e!r}")

    try:
        return (
            fetch_completion_response(user_text, history, timeout=timeout),
            "completion",
        )
    except Exception as e:
        log_line(f"full completion failed: {e!r}")

    raise ModelRequestError("unable to fetch reply from chat or completion backend")


# =======================
# Piper TTS
# =======================

# =======================
# UI
# =======================
class TalkUI:
    def __init__(self, stdscr, roll_style="box"):
        self.stdscr = stdscr
        self.roll_style = roll_style
        self.h, self.w = self.stdscr.getmaxyx()
        self.title_h = 1
        self.input_h = 2
        self.tokens_h = max(3, int(self.h * 0.25))
        self.roll_h = self.h - (self.title_h + self.input_h + self.tokens_h) - 2

        self.tokens_text = ""
        self.tokens_lines = deque(maxlen=500)
        self.rolling_lines = deque(maxlen=400)

        self.lock = threading.Lock()
        curses.curs_set(1)
        self.stdscr.nodelay(False)
        self.stdscr.keypad(True)
        self.stdscr.timeout(80)

        self.has_colors = curses.has_colors()
        if self.has_colors:
            curses.start_color()
            curses.init_pair(1, curses.COLOR_YELLOW, -1)
            curses.init_pair(2, curses.COLOR_YELLOW, -1)
            curses.init_pair(3, curses.COLOR_WHITE, -1)

        self.crawl_speed = max(CRAWL_MIN_LPS, min(CRAWL_MAX_LPS, CRAWL_SPEED_LPS))
        self.crawl_offset = 0.0
        self.last_tick = time.time()
        self.crawl_paused = False

    def set_crawl_speed(self, new_speed):
        self.crawl_speed = max(CRAWL_MIN_LPS, min(CRAWL_MAX_LPS, float(new_speed)))

    def toggle_crawl_pause(self):
        self.crawl_paused = not self.crawl_paused
        self.last_tick = time.time()

    def tick(self):
        if self.roll_style != "crawl" or self.crawl_paused:
            self.last_tick = time.time()
            return
        now = time.time()
        dt = now - self.last_tick
        self.last_tick = now
        self.crawl_offset += self.crawl_speed * dt
        if self.crawl_offset > 1e6:
            self.crawl_offset %= 1e6

    def resize(self):
        self.h, self.w = self.stdscr.getmaxyx()
        self.tokens_h = max(3, int(self.h * 0.25))
        self.roll_h = self.h - (self.title_h + self.input_h + self.tokens_h) - 2
        self._rewrap_tokens()

    def _rewrap_tokens(self):
        wrapped = wrap_to_width(self.tokens_text, max(10, self.w - 4))
        self.tokens_lines = deque(wrapped[-500:], maxlen=500)

    def clear_tokens(self):
        with self.lock:
            self.tokens_text = ""
            self.tokens_lines.clear()

    def append_token_text(self, text):
        with self.lock:
            if not self.tokens_text:
                self.tokens_text = text
            else:
                self.tokens_text += text
            self._rewrap_tokens()

    def draw_title(self, status=""):
        _safe_addstr(
            self.stdscr,
            0,
            0,
            (" Talk TTS  |  %s " % status).ljust(self.w - 1),
            curses.A_REVERSE,
        )

    def draw_tokens(self):
        y0 = self.title_h
        _safe_addstr(self.stdscr, y0, 0, " Stream ", curses.A_BOLD)
        self.stdscr.hline(y0 + 1, 0, curses.ACS_HLINE, self.w - 1)
        lines = list(self.tokens_lines)[-(self.tokens_h - 2) :]
        y = y0 + 2
        for line in lines:
            _safe_addnstr(self.stdscr, y, 1, line, self.w - 3)
            y += 1
        self.stdscr.hline(y0 + self.tokens_h, 0, curses.ACS_HLINE, self.w - 1)

    def _style_crawl_line(self, text, depth_ratio):
        max_spacing = 1
        spaces = max(0, int(round(max_spacing * (1.0 - depth_ratio))))
        if spaces > 0:
            parts = []
            for ch in text:
                parts.append(ch)
                if ch != " ":
                    parts.append(" " * spaces)
            text = "".join(parts).rstrip()

        attr = 0
        if self.has_colors:
            if depth_ratio < 0.33:
                attr |= curses.color_pair(1) | curses.A_BOLD
            elif depth_ratio < 0.66:
                attr |= curses.color_pair(2)
            else:
                attr |= curses.color_pair(3)
        else:
            if depth_ratio < 0.33:
                attr |= curses.A_BOLD
            elif depth_ratio > 0.66:
                attr |= curses.A_DIM
        return text, attr

    def draw_roll_crawl(self):
        y0 = self.title_h + self.tokens_h + 1
        _safe_addstr(self.stdscr, y0, 0, " Star Wars Crawl ", curses.A_BOLD)
        self.stdscr.hline(y0 + 1, 0, curses.ACS_HLINE, self.w - 1)

        lines_full = list(self.rolling_lines)
        inner_h = self.roll_h - 2
        n = len(lines_full)

        if n == 0:
            self.stdscr.hline(y0 + self.roll_h, 0, curses.ACS_HLINE, self.w - 1)
            return

        base_first = max(0, n - inner_h)
        off_all = self.crawl_offset
        off_int = int(off_all)
        off_frac = off_all - off_int

        start = max(0, base_first - off_int)
        end = min(n, start + inner_h)
        visible = lines_full[start:end]

        bottom_pad = 1 if off_frac > 0.001 and len(visible) >= inner_h else 0
        panel_bottom = y0 + self.roll_h - 1

        y = panel_bottom
        if bottom_pad:
            _safe_addnstr(self.stdscr, y, 2, " ", self.w - 4)
            y -= 1

        count = min(len(visible), inner_h - bottom_pad)
        for i in range(count):
            line = visible[-1 - i]
            dist_from_bottom = i
            depth_ratio = 1.0 - (dist_from_bottom / max(1, inner_h - 1))
            styled, attr = self._style_crawl_line(line, depth_ratio)

            indent = int(dist_from_bottom * 0.8)
            text = (" " * indent) + styled
            start_x = max(2, (self.w - len(text)) // 2)
            _safe_addnstr(self.stdscr, y, start_x, text, self.w - start_x - 2, attr)
            y -= 1

        self.stdscr.hline(y0 + self.roll_h, 0, curses.ACS_HLINE, self.w - 1)

    def draw_roll_box(self):
        y0 = self.title_h + self.tokens_h + 1
        _safe_addstr(self.stdscr, y0, 0, " Now Speaking ", curses.A_BOLD)
        self.stdscr.hline(y0 + 1, 0, curses.ACS_HLINE, self.w - 1)
        lines = list(self.rolling_lines)[-(self.roll_h - 2) :]
        y = y0 + 2
        for line in lines:
            _safe_addnstr(self.stdscr, y, 2, line, self.w - 4)
            y += 1
        self.stdscr.hline(y0 + self.roll_h, 0, curses.ACS_HLINE, self.w - 1)

    def draw_input(self, buf):
        y = self.h - self.input_h
        hint_full = "  (Enter=send, /style box|crawl, F5=test, F9=logs, F12=speak-debug, F6/7=speed, Ctrl+Space/F8=pause, /quit=exit)"
        hint_short = "  (Enter, /quit)"
        min_prompt_cols = 20

        if self.w - 1 < min_prompt_cols + len(hint_short):
            hint = ""
        elif self.w - 1 < min_prompt_cols + len(hint_full):
            hint = hint_short
        else:
            hint = hint_full

        max_text = max(min_prompt_cols, self.w - len(hint) - 1)
        text = ("> " + buf)[:max_text]
        pad_len = max(0, self.w - len(text) - len(hint) - 1)
        pad = " " * pad_len
        _safe_addstr(self.stdscr, y, 0, text + pad + hint)
        cursor_x = min(self.w - 2, min(2 + len(buf), max_text))
        try:
            self.stdscr.move(y, cursor_x)
        except curses.error:
            pass

    def add_roll_phrase(self, phrase):
        with self.lock:
            for line in wrap_to_width(phrase, self.w - 6):
                self.rolling_lines.append(line)
        if self.roll_style == "crawl":
            self.crawl_offset = 0.0
            self.last_tick = time.time()

    def render(self, input_buf, status=""):
        self.tick()
        self.stdscr.erase()
        self.resize()
        self.draw_title(status)
        self.draw_tokens()
        if self.roll_style == "crawl":
            self.draw_roll_crawl()
        else:
            self.draw_roll_box()
        self.draw_input(input_buf)
        self.stdscr.refresh()


# =======================
# Log Viewer
# =======================
class LogViewer:
    def __init__(self, path):
        self.path = path
        self.visible = False
        self.offset = 0
        self.cache = []

    def toggle(self):
        self.visible = not self.visible
        self.refresh_cache()

    def refresh_cache(self):
        self.cache = tail_file(self.path)

    def scroll(self, delta, page=0):
        if not self.visible:
            return
        if page:
            self.offset = max(0, self.offset + page)
        else:
            self.offset = max(0, self.offset + delta)

    def draw(self, stdscr):
        if not self.visible:
            return
        h, w = stdscr.getmaxyx()
        box_h = max(6, int(h * 0.8))
        y0 = (h - box_h) // 2
        title = f" Logs — {self.path}  (F9 close; ↑/↓/PgUp/PgDn/Home/End scroll) "
        stdscr.attron(curses.A_REVERSE)
        _safe_addstr(stdscr, y0, 0, title.ljust(w - 1))
        stdscr.attroff(curses.A_REVERSE)
        inner_h = box_h - 2
        start = max(0, len(self.cache) - inner_h - self.offset)
        end = max(0, len(self.cache) - self.offset)
        lines = self.cache[start:end]
        y = y0 + 1
        for line in lines:
            _safe_addnstr(stdscr, y, 1, line, w - 2)
            y += 1
        stdscr.hline(y0 + box_h - 1, 0, curses.ACS_HLINE, w - 1)


# =======================
# Main
# =======================
def main(stdscr):
    curses.use_default_colors()
    piper_dir = os.path.dirname(PIPER_BIN)
    if os.path.isdir(piper_dir):
        os.environ["LD_LIBRARY_PATH"] = (
            f"{piper_dir}:{os.environ.get('LD_LIBRARY_PATH', '')}"
        )

    ui = TalkUI(stdscr, roll_style=ROLL_STYLE)
    logs = LogViewer(LOG_PATH)

    speak_q = queue.Queue()
    status_q = queue.Queue()

    def queue_status(msg):
        try:
            status_q.put_nowait(msg)
        except Exception:
            pass

    tts = PiperTTSWorker(
        speak_q,
        status_cb=queue_status,
        bin_path=PIPER_BIN,
        model_path=PIPER_MODEL,
        sound_player=SOUND_PLAYER,
        pause=SPEAK_PAUSE_SEC,
        save_wav=SAVE_WAV,
        log_redirect_factory=proc_io_redirects,
    )
    tts.start()

    input_buf = ""
    speaking_acc = SentenceAccumulator()
    debug_acc = SentenceAccumulator()
    speak_debug = False

    history = []

    def set_status(s):
        try:
            status_q.put_nowait(s)
        except queue.Full:
            pass

    set_status(
        f"Chat={CHAT_API_URL} | Completion={COMPLETION_API_URL} | "
        f"Piper={PIPER_BIN} | Voice={PIPER_MODEL} | Player={AUDIO_PLAYER or 'none'} | "
        f"Style={ROLL_STYLE} | Log={LOG_PATH} | SpeakDebug={speak_debug}"
    )

    def redraw(status=""):
        ui.render(input_buf, status=status)
        if logs.visible:
            logs.refresh_cache()
            logs.draw(stdscr)
        stdscr.refresh()

    while True:
        status = ""
        try:
            while True:
                status = status_q.get_nowait()
        except queue.Empty:
            pass

        ui.render(input_buf, status=status)
        if logs.visible:
            logs.refresh_cache()
            logs.draw(stdscr)
            stdscr.refresh()

        try:
            ch = stdscr.getch()
        except KeyboardInterrupt:
            break

        if ch == curses.KEY_RESIZE:
            continue

        if ch == curses.KEY_F5:
            test_phrase = "Audio test. One, two, three."
            ui.add_roll_phrase(test_phrase)
            speak_q.put(test_phrase)
            set_status("Played test phrase.")
            redraw()
            continue

        if ch == curses.KEY_F9:
            logs.toggle()
            redraw()
            continue

        if ch == curses.KEY_F12:
            speak_debug = not speak_debug
            set_status(f"SpeakDebug={'on' if speak_debug else 'off'}")
            redraw()
            continue

        if ch == 0 or ch == curses.KEY_F8:
            ui.toggle_crawl_pause()
            set_status(
                f"Crawl {'paused' if ui.crawl_paused else 'running'} at {ui.crawl_speed:.2f} lps"
            )
            redraw()
            continue

        if ch == curses.KEY_F6:
            ui.set_crawl_speed(ui.crawl_speed * 0.8)
            set_status(f"Crawl speed: {ui.crawl_speed:.2f} lps")
            redraw()
            continue

        if ch == curses.KEY_F7:
            ui.set_crawl_speed(ui.crawl_speed * 1.25)
            set_status(f"Crawl speed: {ui.crawl_speed:.2f} lps")
            redraw()
            continue

        if logs.visible:
            if ch == curses.KEY_UP:
                logs.scroll(1)
                redraw()
                continue
            if ch == curses.KEY_DOWN:
                logs.scroll(-1)
                redraw()
                continue
            if ch == curses.KEY_PPAGE:
                logs.scroll(0, page=10)
                redraw()
                continue
            if ch == curses.KEY_NPAGE:
                logs.scroll(0, page=-10)
                redraw()
                continue
            if ch == curses.KEY_HOME:
                logs.offset = len(logs.cache)
                redraw()
                continue
            if ch == curses.KEY_END:
                logs.offset = 0
                redraw()
                continue

        if ch in (3, 4):
            break

        if ch in (curses.KEY_BACKSPACE, 127, 8):
            input_buf = input_buf[:-1] if input_buf else ""
            continue

        if ch in (10, 13):
            text = input_buf.strip()
            input_buf = ""

            if not text:
                continue

            if text.lower() == "/quit":
                break

            if text.lower().startswith("/style"):
                _, _, style = text.partition(" ")
                style = (style or "").strip().lower()
                if style in ("box", "crawl"):
                    ui.roll_style = style
                    if style == "crawl":
                        ui.crawl_offset = 0.0
                        ui.last_tick = time.time()
                        ui.crawl_paused = False
                    set_status(f"Style={style}")
                else:
                    set_status("Usage: /style box|crawl")
                redraw()
                continue

            speaking_acc = SentenceAccumulator()
            debug_acc = SentenceAccumulator()

            backend = "?"
            assistant_fragments = []

            ui.clear_tokens()
            ui.append_token_text(f"AI[{backend}]: ")

            set_status(f"Streaming... SpeakDebug={'on' if speak_debug else 'off'}")
            redraw("Streaming...")

            try:
                streamed, backend = stream_assistant_reply(
                    text, history, include_debug=speak_debug
                )
                ui.clear_tokens()
                ui.append_token_text(f"AI[{backend}]: ")
                redraw(f"Streaming ({backend})...")

                for frag, is_dbg in streamed:
                    vis_text = (DEBUG_PREFIX + frag) if is_dbg else frag
                    ui.append_token_text(vis_text)

                    if not is_dbg:
                        assistant_fragments.append(frag)

                    acc = debug_acc if is_dbg else speaking_acc
                    for phrase in acc.push(frag):
                        shown = phrase if not is_dbg else (DEBUG_PREFIX + phrase)
                        ui.add_roll_phrase(shown)
                        speak_q.put(phrase)
                    redraw(f"Streaming ({backend})...")
                    time.sleep(0.005)

                for phrase in speaking_acc.flush():
                    ui.add_roll_phrase(phrase)
                    speak_q.put(phrase)
                    redraw(f"Streaming ({backend})...")

                for phrase in debug_acc.flush():
                    ui.add_roll_phrase(DEBUG_PREFIX + phrase)
                    speak_q.put(phrase)
                    redraw(f"Streaming ({backend})...")

                assistant_text = "".join(assistant_fragments).strip()
                if assistant_text:
                    history.append(("user", text))
                    history.append(("assistant", assistant_text))
                    history[:] = trim_history(history)

                set_status(f"Ready. backend={backend}")
                redraw("Ready.")

            except Exception as e:
                log_line(f"streaming failed: {e!r}")
                set_status("Stream failed; trying non-streaming fallback...")
                redraw("Fallback...")

                try:
                    reply, backend = fetch_assistant_reply(text, history)
                    reply = reply.strip()

                    ui.clear_tokens()
                    ui.append_token_text(f"AI[{backend}]: " + reply)
                    redraw(f"Speaking ({backend})...")

                    if reply:
                        history.append(("user", text))
                        history.append(("assistant", reply))
                        history[:] = trim_history(history)

                    for sent in chunk_sentences(reply):
                        ui.add_roll_phrase(sent)
                        speak_q.put(sent)
                        redraw(f"Speaking ({backend})...")

                    set_status(f"Ready. backend={backend}")
                    redraw("Ready.")
                except Exception as e2:
                    log_line(f"fallback fetch failed: {e2!r}")
                    err = f"Model error: {e2}"
                    ui.clear_tokens()
                    ui.append_token_text(err)
                    ui.add_roll_phrase(err)
                    speak_q.put(err)
                    set_status("Model request failed. See F9 logs.")
                    redraw("Error.")
            continue

        if ch != -1:
            try:
                c = chr(ch)
                if c.isprintable():
                    input_buf += c
            except Exception:
                pass

    speak_q.put(None)
    tts.stop()
    tts.join()


# =======================
# Entry
# =======================
if __name__ == "__main__":
    curses.wrapper(main)
