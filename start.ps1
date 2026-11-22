$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$env:UV_CACHE_DIR = "$PSScriptRoot/data/uv-cache"
$env:UV_PYTHON_INSTALL_DIR = "$PSScriptRoot/data/python"
$env:HF_HOME = "$PSScriptRoot/data/huggingface"
$env:HF_HUB_DISABLE_TELEMETRY = "1"
$env:DO_NOT_TRACK = "1"
$env:TEMP = "$PSScriptRoot/data/tmp"
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
uv sync --python 3.13 --extra hf --no-dev
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "STT AI 0.2.0: http://127.0.0.1:8765 (ukonceni: Ctrl+C)"
uv run --python 3.13 --extra hf --no-dev uvicorn stt.app:app --host 127.0.0.1 --port 8765
