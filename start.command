#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if ! command -v uv >/dev/null 2>&1; then
  echo "Nejprve nainstalujte uv: brew install uv"
  exit 1
fi
export UV_CACHE_DIR="$PWD/data/uv-cache"
export UV_PYTHON_INSTALL_DIR="$PWD/data/python"
export HF_HOME="$PWD/data/huggingface"
export HF_HUB_DISABLE_TELEMETRY=1
export DO_NOT_TRACK=1
export TMPDIR="$PWD/data/tmp"
mkdir -p "$TMPDIR"
uv sync --python 3.13 --no-dev
echo "STT AI: http://127.0.0.1:8765 (ukončení: Ctrl+C)"
exec uv run --python 3.13 --no-dev uvicorn stt.app:app --host 127.0.0.1 --port 8765
