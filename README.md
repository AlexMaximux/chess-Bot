# Chess Autoplayer

An autonomous desktop chess companion that drives real Google Chrome on chess.com against bots using the Chrome DevTools Protocol (CDP) or native macOS mouse events, powered by Stockfish and human-like move selection and timing models.

> [!WARNING]
> **Fair Play & Terms of Service Warning**
> Chess.com's Terms of Service strictly prohibit automation, bots, and engine assistance against human players. Using automation can result in immediate account closure and IP bans.
>
> **Hard Limit**: This software is engineered with a strict fair play guard that operates **exclusively** on `https://www.chess.com/play/computer` (and authorized bot subpaths). It will instantly pause and block inputs if navigated to online matchmaking (`/play/online`, `/live`, etc.).
>
> We strongly recommend playing as a **Guest** or using a **separate dedicated test account**. Never use your primary account.

---

## Table of Contents

1. [Features](#features)
2. [Prerequisites & System Requirements](#prerequisites--system-requirements)
3. [Quick Start & Setup](#quick-start--setup)
4. [First Run & Chrome Profile Isolation](#first-run--chrome-profile-isolation)
5. [Using the Desktop Control Panel](#using-the-desktop-control-panel)
6. [Command-Line Interface (CLI)](#command-line-interface-cli)
7. [Engine Strength Profiles](#engine-strength-profiles)
8. [Humanization: Speed, Timing & Input Modes](#humanization-speed-timing--input-modes)
9. [macOS Accessibility Permissions (OS Mode)](#macos-accessibility-permissions-os-mode)
10. [Troubleshooting Guide](#troubleshooting-guide)
11. [Architecture Overview](#architecture-overview)
12. [Configuration & Log Locations](#configuration--log-locations)

---

## Features

- **Isolated World Board DOM Reader**: Injects an isolated JavaScript scanner (`reader.js`) via CDP to reliably reconstruct board geometry, pieces, turn, and move history without interfering with page scripts.
- **Dual Input Modes**:
  - **Browser (CDP)**: Dispatches synthetic mouse events (`mousePressed`, `mouseMoved`, `mouseReleased`) directly through CDP.
  - **Real Mouse (OS)**: Drives the physical macOS cursor using CoreGraphics (`CGEvent`) with Bézier curve kinematics and micro-jitter.
- **Stockfish MultiPV + Softmax Selection**: Uses MultiPV engine analysis and temperature-scaled Boltzmann distribution to simulate realistic human candidate evaluation across 6 Elo profiles.
- **Human Timing Model**: Dynamic think time based on ply, candidate count, tactical volatility, and blunder avoidance.
- **Promotion & Verification Guard**: Automatically handles pawn promotion dialogs and verifies move landing on the board, retrying with click input if a drag fails.
- **Tkinter Desktop GUI**: Native desktop control panel with real-time status indicators, engine evaluation bar, last decision breakdown, scrollable move log, and session tally.

---

## Prerequisites & System Requirements

- **Operating System**: macOS (tested on macOS 14 Sonoma and macOS 15 Sequoia / Apple Silicon & Intel).
- **Python**: Python 3.13 or later.
- **Package Manager**: [uv](https://docs.astral.sh/uv/) (recommended) and [Homebrew](https://brew.sh/).
- **Browser**: Google Chrome.
- **Chess Engine**: Stockfish (version 16, 17, or 18; installable via Homebrew).

---

## Quick Start & Setup

The easiest way to configure your environment is using the automated setup script:

```bash
# 1. Clone or navigate to the repository
cd chess-autoplayer

# 2. Run the environment setup script
bash scripts/setup.sh
```

`setup.sh` verifies Homebrew, Google Chrome, and `uv`, installs Stockfish (`brew install stockfish`) and Python Tkinter support (`brew install python-tk@3.13`) if missing, and synchronizes virtual environment dependencies via `uv sync`.

To launch the desktop GUI, simply run:
```bash
uv run chess-autoplayer
```
or double-click the **`Chess Autoplayer.command`** launcher in the project root folder.

---

## First Run & Chrome Profile Isolation

### Why a Dedicated Profile is Required

Starting with **Chrome 136+**, Google Chrome strictly blocks remote debugging flags (`--remote-debugging-port`) when attached to the default user profile directory. To prevent security conflicts and tab collisions:

1. Chess Autoplayer launches an isolated instance of Chrome using a dedicated profile folder at `~/.chess-autoplayer/chrome-profile`.
2. Chrome is started with remote debugging on port `9333`.
3. If you wish to play as a logged-in user, open Chrome via the **Open Chrome** button in the control panel and log in once. Your cookies and session will persist in the dedicated profile.
4. Closing the bot or control panel **does not** close your Chrome browser—your open tabs remain intact.

---

## Using the Desktop Control Panel

Run `uv run chess-autoplayer` (or double-click `Chess Autoplayer.command`) to open the control panel.

### Controls & Buttons
- **Open Chrome**: Launches Google Chrome in debug mode and opens `https://www.chess.com/play/computer`.
- **Start**: Attaches to the active chess tab, initializes Stockfish, and starts autonomous play.
- **Pause / Resume**: Temporarily halts bot input (e.g. to inspect a position or take a turn yourself).
- **Stop**: Stops the controller, closes the engine, and detaches cleanly from Chrome.

### Live Display Elements
- **Status Indicator**: Displays real-time bot state (`IDLE`, `THINKING`, `MOVING`, `VERIFYING`, `GAME_OVER`, `BLOCKED_URL`). Colors: Green (active play), Amber (paused/waiting), Red (error/blocked).
- **Evaluation Bar**: Clamped between ±1000 centipawns from the bot's perspective (50% = equal). Displays pawn evaluation (`+1.5`, `-0.8`) or distance to mate (`M3`, `-M2`).
- **Last Decision**: Shows the chosen move, human think time in seconds, and top 3 MultiPV candidate moves.
- **Move Log**: Live scrollable table displaying move numbers, SAN notations, and who played each move (Bot vs Opponent).
- **Session Tally**: Automatically tallies Games, Wins, Losses, and Draws parsed from game-over modals.

### Keyboard Shortcuts
- <kbd>Space</kbd>: Toggle Pause / Resume.
- <kbd>Esc</kbd>: Stop the bot.

---

## Command-Line Interface (CLI)

In addition to the GUI, Chess Autoplayer provides comprehensive CLI tools:

### 1. `probe` (Inspect Browser Board)
Inspects the current board in Chrome, prints FEN and active pieces, and validates DOM selectors:
```bash
# Print game state summary
uv run chess-autoplayer probe

# Output raw JSON snapshot
uv run chess-autoplayer probe --json

# Capture current board position into a test fixture
uv run chess-autoplayer probe --save-fixture custom_position
```

### 2. `analyse` (Stockfish Analysis)
Analyzes either a live browser board or a custom FEN string:
```bash
# Analyze current live board in Chrome
uv run chess-autoplayer analyse --strength club

# Analyze a specific FEN
uv run chess-autoplayer analyse --fen "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1" --strength master
```

### 3. `run` (Autonomous Bot Loop)
Runs the autonomous bot directly from the terminal without the GUI:
```bash
# Run with default settings
uv run chess-autoplayer run

# Run with custom strength, speed, and input mode
uv run chess-autoplayer run --strength strong --speed 1.5 --input cdp --style mixed
```

### 4. `gui` (GUI & CI Smoke Testing)
```bash
# Open desktop GUI
uv run chess-autoplayer gui

# CI Smoke test: opens GUI, verifies worker thread, runs for 3 seconds, and exits cleanly
uv run chess-autoplayer gui --smoke 3
```

---

## Engine Strength Profiles

Profiles configure Stockfish UCI parameters and temperature-scaled move selection:

| Profile | Target Elo | MultiPV | Search Time | Depth / Skill | Behavior |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **`beginner`** | ~800 | 5 | 0.05s | Skill 3 | Plays simple moves, occasional blunders |
| **`casual`** | ~1200 | 4 | 0.05s | Skill 6 | Solid opening basics, intermediate tactics |
| **`club`** | ~1600 | 3 | 0.08s | Skill 10 | Strong positional play, punishes clear mistakes |
| **`strong`** | ~2000 | 3 | 0.12s | Skill 14 | Advanced tactical awareness, rapid punishment |
| **`master`** | ~2400 | 2 | 0.15s | Skill 18 | Master-level depth and endgames |
| **`max`** | Uncapped | 1 | 0.20s | Full UCI | Pure maximum Stockfish evaluation |

---

## Humanization: Speed, Timing & Input Modes

### Speed Multiplier (`speed`)
- Configurable from `0.5x` (deliberate, thoughtful play) to `2.0x` (rapid blitz play).
- Think time scales with:
  - Game phase: Openings (< 10 plies) are played faster from memory.
  - Candidate disparity: Clear best moves (recaptures, obvious tactics) are played quickly.
  - Complex positions: Equal top candidates trigger longer evaluation pauses.

### Move Styles (`style`)
- **`drag`**: Smoothly picks up the piece at the source square and drags it along a randomized Bézier trajectory to the destination square.
- **`click`**: Clicks the source square, moves the cursor to the destination, and clicks to drop.
- **`mixed`** (default): Randomly alternates between 75% drag moves and 25% click moves.

---

## macOS Accessibility Permissions (OS Mode)

To use **Real Mouse (OS)** input mode, macOS requires Accessibility permissions so the application can synthesize hardware mouse events:

1. Open **System Settings** on your Mac.
2. Navigate to **Privacy & Security** → **Accessibility**.
3. Click the **+** button and add your terminal emulator (e.g. **Terminal**, **iTerm2**, or **Ghostty**) and/or Python.
4. Ensure the toggle switch next to the application is turned **ON**.
5. If permissions are missing, the bot automatically notifies you via an error event and safely retains Browser (CDP) mode.

---

## Troubleshooting Guide

### 1. Port Busy (`Port 9333 in use`)
- **Cause**: An existing instance of Chrome or another process is using port 9333.
- **Fix**: Run `lsof -i :9333` to find the process ID, or kill existing Chrome instances with:
  ```bash
  pkill -f "remote-debugging-port=9333"
  ```

### 2. Stockfish Not Found
- **Cause**: Stockfish is not in your system PATH.
- **Fix**: Install via Homebrew:
  ```bash
  brew install stockfish
  ```
  Or specify the path in `~/.chess-autoplayer/config.json`:
  ```json
  {
    "stockfish_path": "/opt/homebrew/bin/stockfish"
  }
  ```

### 3. Board Not Detected (`WAITING_FOR_GAME`)
- **Cause**: Browser is not navigated to `https://www.chess.com/play/computer` or the board element is hidden.
- **Fix**: Click **Open Chrome** or navigate your browser tab to `https://www.chess.com/play/computer`. Ensure the tab is not zoomed in or covered by external modals.

### 4. Moves Not Landing
- **Cause**: Chess.com rejected a drag due to timing, or a piece promotion dialog was pending.
- **Fix**: Chess Autoplayer includes automatic verification with an immediate click fallback. If drags consistently fail, switch **Move style** to `click` or **Input mode** to `Real mouse (OS)` in settings.

### 5. Chess.com DOM Layout Changed
- **Location**: All DOM selectors and board geometry calculations reside in:
  [`src/chess_autoplayer/board/reader.js`](src/chess_autoplayer/board/reader.js)
  If chess.com updates class names, update the board query selectors (`wc-chess-board`, `chess-board`, `#board-layout-player-bottom`) in that file.

---

## Architecture Overview

```
src/chess_autoplayer/
├── __main__.py          # Unified CLI entry point (probe, analyse, run, gui)
├── config.py            # Typed settings, validation, and JSON config persistence
├── logging_setup.py     # Colored terminal and file logging configuration
├── board/
│   ├── reader.js        # In-browser DOM scanner for pieces, coordinates, and game state
│   ├── reader.py        # JavaScript script loader
│   ├── snapshot.py      # Pydantic-style typed dataclass snapshot parser
│   └── state.py         # python-chess board reconstruction and move validator
├── engine/
│   ├── profiles.py      # Elo strength profiles and MultiPV configurations
│   ├── selector.py      # Human-like softmax candidate move selection
│   └── stockfish.py     # UCI engine wrapper and crash-recovery supervisor
├── human/
│   ├── geometry.py      # Board coordinate mapping and inner-square jitter
│   ├── mouse.py         # Two-stage cubic Bézier curve kinematic generator
│   └── timing.py        # Dynamic human think time calculation
├── input/
│   ├── base.py          # Abstract MoveInput protocol and MoveContext dataclass
│   ├── cdp_input.py     # CDP synthetic mouse event dispatcher
│   └── os_input.py      # macOS CoreGraphics native mouse input dispatcher
├── bot/
│   ├── events.py        # Typed BotEvent hierarchy and BotState enum
│   └── controller.py    # Autonomous async state machine and verification loop
└── ui/
    ├── view_model.py    # Pure presentation formatting, eval clamping, and tally logic
    └── app.py           # Tkinter + ttk control panel and async worker bridge
```

### Developer Commands
```bash
# Run unit and integration tests
uv run pytest -q

# Run strict type checking
uv run mypy --strict src

# Check linting and code formatting
uv run ruff check .
uv run ruff format --check .

# Execute 3-second GUI smoke test
uv run chess-autoplayer gui --smoke 3
```

---

## Configuration & Log Locations

- **Configuration File**: `~/.chess-autoplayer/config.json`
- **Chrome Debug Profile**: `~/.chess-autoplayer/chrome-profile`
- **Application Logs**: `~/.chess-autoplayer/logs/`
- **Live Run Logs**: `docs/live-runs/`
