# 0) sanity: make sure we're in the right folder
test -f main.py || { echo "Run this from the repo root (main.py not found)"; exit 1; }

# 1) see which Python / PyInstaller we're using
python3 -c "import sys,PyInstaller; print('Python:',sys.executable); print('PyInstaller:',PyInstaller.__version__)"
which pyinstaller || true

# 2) clean out previous artifacts
rm -rf build dist

# 3) build (one-dir) with excludes + hidden imports for Flask stack
python3 -m PyInstaller --noconfirm --clean --log-level=DEBUG \
  --name pikit --onedir \
  --hidden-import flask --hidden-import jinja2 --hidden-import werkzeug --hidden-import markupsafe --hidden-import itsdangerous \
  --exclude-module torch --exclude-module torchvision --exclude-module torchaudio \
  --exclude-module tensorflow --exclude-module onnx --exclude-module onnxruntime \
  --exclude-module numba --exclude-module llvmlite \
  --exclude-module cv2 --exclude-module moviepy \
  --exclude-module matplotlib --exclude-module pandas --exclude-module pyarrow \
  --strip \
  main.py | tee build.log

# 4) confirm output
echo "---- dist contents ----"; ls -lah dist
echo "---- pikit artifact ----"; ls -lah dist/pikit || true

