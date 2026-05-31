import time
import socket
from modules.opml_extras_plugin import _decode_bytes_best

def fetch_html_with_fallback(url, max_bytes, connect_to, read_to, budget_s):
    """Do the network I/O only. Returns decoded HTML as str."""
    start = time.monotonic()

    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/122.0 Safari/537.36 FunKit/OPML",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "close",
    }

    # Try requests if available
    try:
        import requests
        with requests.get(url, headers=headers, timeout=(connect_to, read_to),
                          stream=True, allow_redirects=True) as r:
            r.raise_for_status()
            ctype = (r.headers.get("Content-Type") or "").lower()
            if "text/html" not in ctype and "xml" not in ctype:
                raise RuntimeError(f"Unsupported Content-Type: {ctype or 'unknown'}")
            raw = bytearray()
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    raw.extend(chunk)
                if len(raw) > max_bytes or (time.monotonic() - start) > budget_s:
                    break
        return _decode_bytes_best(bytes(raw))
    except Exception:
        pass

    # Fallback: urllib
    import urllib.request
    old_t = socket.getdefaulttimeout()
    socket.setdefaulttimeout(read_to)
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=connect_to) as resp:
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if "text/html" not in ctype and "xml" not in ctype:
                raise RuntimeError(f"Unsupported Content-Type: {ctype or 'unknown'}")
            raw = bytearray()
            while True:
                if (time.monotonic() - start) > budget_s:
                    break
                chunk = resp.read(65536)
                if not chunk:
                    break
                raw.extend(chunk)
                if len(raw) > max_bytes:
                    break
    finally:
        socket.setdefaulttimeout(old_t)

    return _decode_bytes_best(bytes(raw))
