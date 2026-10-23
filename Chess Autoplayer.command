#!/usr/bin/env bash
# Double-clickable macOS launcher for Chess Autoplayer

set -euo pipefail

# Navigate to the project root directory where this script resides
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "Starting Chess Autoplayer..."
exec uv run chess-autoplayer
