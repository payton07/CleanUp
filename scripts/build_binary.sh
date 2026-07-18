#!/usr/bin/env bash
# Build a standalone `cleanup` binary with PyInstaller.
#
# Produces a LEAN binary: the core CLI (sort, dedupe, undo/redo, watch, rules,
# ignore, profiles). Heavy optional stacks — AI (fastembed/onnxruntime), the web
# GUI (fastapi/uvicorn), and libmagic — are excluded to keep the binary small
# and portable; those features degrade gracefully (content detection falls back
# to extensions). Install via pip to use AI or the web GUI.
set -euo pipefail

NAME="cleanup"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

pyinstaller --onefile --name "$NAME" --clean --noconfirm \
  --paths . \
  --hidden-import cleanup.ai.adaptive \
  --hidden-import cleanup.ai.memory \
  --collect-all pydantic \
  --collect-all pydantic_core \
  --exclude-module fastembed \
  --exclude-module onnxruntime \
  --exclude-module fastapi \
  --exclude-module uvicorn \
  --exclude-module starlette \
  --exclude-module httpx \
  --exclude-module magic \
  --exclude-module PIL \
  --exclude-module numpy \
  --exclude-module torch \
  --exclude-module watchdog \
  scripts/pyinstaller_entry.py

echo ""
echo "Built: dist/$NAME"
