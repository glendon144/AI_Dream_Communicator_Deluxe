import subprocess
import base64
from io import BytesIO
from PIL import Image, ImageTk
import re


def render_binary_as_text(file_path: str, min_length: int = 4) -> str:
    #Extracts printable ASCII strings from a binary file using the Unix `strings` command."""
    try:
        result = subprocess.run(
        ['strings', f'-n', str(min_length), file_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        text=True
    )
        return result.stdout
    except Exception as e:
        return f"[Error extracting strings: {e}]"

def render_image_preview_from_base64(base64_data: str, max_size=(400, 400)):
    """Decodes a base64 image and returns a resized PIL ImageTk.PhotoImage."""
    try:
        decoded = base64.b64decode(base64_data)
        image = Image.open(BytesIO(decoded))
        image.thumbnail(max_size)
        return ImageTk.PhotoImage(image)
    except Exception as e:
        print(f"[Error rendering image preview: {e}]")
        return None

