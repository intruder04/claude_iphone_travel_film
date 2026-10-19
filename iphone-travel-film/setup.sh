#!/bin/sh
# One-time setup on Apple Silicon macOS. Installs Homebrew packages and a Python venv inside the skill folder.
set -e
cd "$(dirname "$0")"
command -v brew >/dev/null || { echo "Homebrew is required: https://brew.sh"; exit 1; }
[ "$(uname -m)" = "arm64" ] || echo "warning: built and tested on Apple Silicon; Intel Macs lack the fast media engines"
brew list ffmpeg-full >/dev/null 2>&1 || brew install ffmpeg-full      # zscale, libplacebo, drawtext, VideoToolbox
brew list exiftool    >/dev/null 2>&1 || brew install exiftool
brew list molten-vk   >/dev/null 2>&1 || brew install molten-vk vulkan-loader   # GPU tone-mapping via libplacebo
PY=$(command -v python3.12 || command -v python3)
[ -d venv ] || "$PY" -m venv venv
venv/bin/pip -q install --upgrade pip
venv/bin/pip -q install -r requirements.txt
venv/bin/python - <<'PY'
import torch, cv2; print('torch', torch.__version__, '| MPS (GPU):', torch.backends.mps.is_available(), '| OpenCV', cv2.__version__)
import Vision; print('Apple Vision framework: ok')
PY
echo "setup complete"
