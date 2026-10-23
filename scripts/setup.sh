#!/usr/bin/env bash
# Setup script for Chess Autoplayer on macOS
# Verifies prerequisites, installs missing tools, and synchronizes Python dependencies.

set -euo pipefail

echo "=========================================="
echo "    Chess Autoplayer Environment Setup    "
echo "=========================================="

# 1. Check Homebrew
echo -n "Checking Homebrew... "
if ! command -v brew >/dev/null 2>&1; then
    echo "FAILED"
    echo "Error: Homebrew is required on macOS. Install from https://brew.sh and re-run setup." >&2
    exit 1
fi
echo "OK ($(brew --version | head -n1))"

# 2. Check Google Chrome
echo -n "Checking Google Chrome... "
CHROME_APP="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
if [ -f "$CHROME_APP" ]; then
    echo "OK ($CHROME_APP)"
elif command -v google-chrome >/dev/null 2>&1; then
    echo "OK ($(command -v google-chrome))"
else
    echo "WARNING"
    echo "Google Chrome was not found at standard location ($CHROME_APP)."
    echo "Please install Google Chrome from https://www.google.com/chrome/"
fi

# 3. Check uv package manager
echo -n "Checking uv... "
if ! command -v uv >/dev/null 2>&1; then
    echo "MISSING"
    echo "Installing uv via Homebrew..."
    brew install uv
fi
echo "OK ($(uv --version))"

# 4. Check Stockfish engine
echo -n "Checking Stockfish... "
if ! command -v stockfish >/dev/null 2>&1; then
    echo "MISSING"
    echo "Installing Stockfish via Homebrew..."
    brew install stockfish
fi
echo "OK ($(stockfish --version 2>&1 | head -n1 || echo 'Stockfish installed'))"

# 5. Check Tkinter / Python-tk support
echo -n "Checking Python Tkinter support... "
if ! uv run python -c "import tkinter" >/dev/null 2>&1; then
    echo "MISSING"
    echo "Installing python-tk via Homebrew..."
    brew install python-tk@3.13 || true
fi
echo "OK"

# 6. Synchronize project dependencies
echo "Synchronizing project virtual environment with uv sync..."
uv sync

echo "=========================================="
echo " Setup complete! You can run the bot with:"
echo "   uv run chess-autoplayer"
echo " or double-click 'Chess Autoplayer.command'"
echo "=========================================="
