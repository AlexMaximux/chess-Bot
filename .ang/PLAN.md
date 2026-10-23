# chess-autoplayer: Plan

## Goal

A macOS desktop app that drives the user's real Google Chrome (visible, not headless) on
`https://www.chess.com/play/computer`, reads the game from the page, picks moves with
Stockfish, and plays them with human-like timing and mouse movement.

Hard limit: the bot only acts on `https://www.chess.com/play/computer` (path prefix
`/play/computer`). On any other URL it refuses to move and shows why. This protects
fair play in games against people.

## Environment (verified on target machine)

- macOS 26.5 on Apple Silicon (arm64)
- Google Chrome 155 at `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`
- Stockfish at `/opt/homebrew/bin/stockfish` (Homebrew)
- `uv` at `/opt/homebrew/bin/uv`; system Python 3.14. The project pins Python 3.13 via uv.

## Stack and why

| Concern | Choice | Why |
|---|---|---|
| Language | Python 3.13, managed by `uv` | Best chess tooling (`python-chess`), fast setup |
| Browser control | Raw Chrome DevTools Protocol over `websockets` | No Playwright/Puppeteer fingerprints; full control |
| Chess logic | `python-chess` | Legal moves, SAN parsing, FEN, UCI engine wrapper |
| Engine | Stockfish via `chess.engine` (UCI) | Strongest free engine; supports MultiPV and UCI_Elo |
| OS mouse (optional mode) | `pyobjc-framework-Quartz` (CGEvent) | Real hardware-level cursor movement on macOS |
| UI | Tkinter | Ships with Python; no web server; small and reliable |
| Quality | `pytest`, `ruff` (lint + format), `mypy --strict` | Fast and standard |

## Why a separate Chrome profile

Chrome 136+ ignores `--remote-debugging-port` when Chrome uses the default user data
directory (security change against cookie theft). The app therefore launches the user's
real Chrome app with its own profile directory `~/.chess-autoplayer/chrome-profile`.
The user logs in to chess.com there once; the login persists. If Chrome is already
running with that profile and the debug port answers, the app attaches instead of
launching.

## Verified chess.com DOM facts (2026-10-23)

- Board element: `wc-chess-board` (id `board-play-computer` on this page).
- Pieces: child `div.piece` with classes `piece <color><type> square-<file><rank>`.
  color `w|b`, type `p n b r q k`, file 1–8 = a–h, rank 1–8. Example: `piece wn square-71` = white knight on g1.
- Square geometry: board `getBoundingClientRect()`; square size = width/8. When not flipped,
  file 1 is on the left and rank 8 at the top. When the user plays black, the board is flipped
  (expected: `flipped` class on `wc-chess-board`; the reader must also cross-check by the
  y-position of the rendered pieces, because class names can change).
- Last-move highlights: `div.highlight square-XY`.
- Move list: `wc-simple-move-list` → `.node.white-move` / `.node.black-move`, SAN in
  `span.node-highlight-content` (text like `e4`, `Nf3`). If the user enables figurine notation,
  the piece letter is an icon span with a `data-figurine` attribute: the reader must
  convert that to the letter.
- Moves are accepted from trusted CDP mouse input with both drag (press → moves → release)
  and click-click (click source, then click target).
- Guest play works: page shows cookie banner (`I Accept`), bot chooser, time-control buttons, and `Play`.

## Architecture

```
src/chess_autoplayer/
  __main__.py          CLI: `chess-autoplayer [gui|run|probe]`
  config.py            Settings dataclass; JSON load/save at ~/.chess-autoplayer/config.json
  logging_setup.py     Rotating file log at ~/.chess-autoplayer/logs/ + console
  chrome/launcher.py   Find Chrome, launch or attach with debug port + own profile
  chrome/cdp.py        Async CDP client: commands, events, sessions, timeouts
  chrome/page.py       Page target attach, isolated world, evaluate helpers, URL guard
  board/reader.js      Pure JS snapshot function (pieces, flipped, rect, moves, game-over, promotion UI)
  board/snapshot.py    Typed Snapshot model parsed from reader.js JSON
  board/state.py       Rebuild python-chess Board from move list; verify against pieces; our color; turn
  engine/stockfish.py  Engine wrapper: strength profiles, MultiPV analysis
  engine/selector.py   Human-like move choice among MultiPV candidates
  human/timing.py      Think-time model
  human/mouse.py       Curved mouse path (Bezier + jitter + overshoot), duration model
  input/base.py        MoveInput protocol
  input/cdp_input.py   Input.dispatchMouseEvent (default)
  input/os_input.py    Quartz CGEvent real cursor + viewport→screen calibration
  bot/controller.py    State machine: wait → think → move → verify; pause/stop; guards
  ui/app.py            Tkinter control panel
tests/                 pytest; fixtures/ holds real captured snapshots
```

## Milestones

1. **Foundation:** scaffold, config, logging, Chrome launcher, CDP client, isolated-world page access, reader.js, snapshot + state reconstruction, URL guard, `probe` command, captured fixtures, tests.
2. **Brain:** Stockfish wrapper, strength profiles, human-like move selection, think-time model, mouse-path model, tests.
3. **Hands + loop:** CDP input, OS input with calibration, promotion handling, controller state machine, `run` terminal command, tests with a fake page.
4. **Panel + finish:** Tkinter UI, end-to-end live games against chess.com bots, README, final polish.
