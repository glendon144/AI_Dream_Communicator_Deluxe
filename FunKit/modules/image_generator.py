import io
import os
import requests
from openai import OpenAI
from PIL import Image

def generate_image(prompt: str, size: str = "512x512"):
    """Generate a DALL·E image and return as PIL.Image."""
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    resp = client.images.generate(prompt=prompt, n=1, size=size)
    url = resp.data[0].url
    img_bytes = requests.get(url, timeout=20).content
    return Image.open(io.BytesIO(img_bytes))
