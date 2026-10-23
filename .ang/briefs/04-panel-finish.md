# Brief 04: Control panel and finish

Follow `.ang/RULES.md`. Read `.ang/PLAN.md`. Build on briefs 01–03; keep all tests green.

## Goal

A non-technical user double-clicks a launcher, gets a clean control panel, presses Start,
and the bot plays on chess.com/play/computer in their Chrome. The project is documented and
ready to hand over.

## Decisions already made

- Tkinter + `ttk`. Tk runs on the main thread; the asyncio controller runs in one background
  thread with its own event loop. Communication: controller events → `queue.Queue` → polled by
  `root.after(50, ...)`; UI commands → `asyncio.run_coroutine_threadsafe`. No Tk calls from the
  worker thread.
- Presentation logic (formatting status, eval bar fraction, move log rows, W/L/D tally) lives in a
  pure `ui/view_model.py` with tests. `ui/app.py` only builds widgets and binds them.
- `chess-autoplayer` with no subcommand opens the GUI (`gui` subcommand stays as an alias).

## Tasks

1. Panel layout (`ui/app.py`), window title "Chess Autoplayer", min size ~420×640:
   - Status line: state + message, colour by state (green playing, amber paused/waiting, red error/blocked).
   - Buttons: **Open Chrome** (launch/attach and open the computer-play page), **Start**,
     **Pause/Resume** (one toggle button), **Stop**.
   - Settings: strength (dropdown of profiles), speed (slider 0.5–2.0, shows value), input mode
     (radio: "Browser (CDP)" / "Real mouse (OS)"), move style (drag/click/mixed).
     Changes save to `config.json` and apply from the next move.
   - Evaluation bar from the bot's point of view (clamped ±1000 cp, mate shown as "M3" etc.).
   - Last decision: chosen move (SAN), top 3 candidates with eval, think time.
   - Move log (scrollable): ply, SAN, "bot"/"opponent".
   - Session tally: games, wins, losses, draws (parse `gameOverText`).
   - Footer note: "Works only on chess.com/play/computer."
   - Shortcuts: Space = pause/resume, Esc = stop.
   - Closing the window stops the controller cleanly (engine closed, mouse button released, CDP closed; Chrome stays open).
2. `uv run chess-autoplayer gui --smoke 3` builds the window, starts the worker thread, runs 3 s,
   closes cleanly, exit code 0 (for CI-style checks).
3. Launchers:
   - `scripts/setup.sh`: checks for Homebrew, Google Chrome, `uv`; installs Stockfish with
     `brew install stockfish` if missing; runs `uv sync`. Clear messages, `set -euo pipefail`.
   - `Chess Autoplayer.command` at the project root: double-clickable, `cd` to its own folder,
     runs `uv run chess-autoplayer`. Make it executable.
4. `README.md`:
   - What it does, with the hard limit (only `/play/computer`) and a clear **warning** that
     chess.com's terms forbid automation and the account may be closed; suggest a separate account.
   - Requirements, setup (`scripts/setup.sh`), first run (log in once in the "ChessBot" Chrome
     profile and why a separate profile is needed: Chrome 136+ blocks remote debugging on the default profile).
   - Using the panel; using the CLI (`probe`, `analyse`, `run` with flags).
   - Strength profiles table, speed, input modes, move styles.
   - OS mode: Accessibility permission steps.
   - Troubleshooting: port busy, Chrome not found, Stockfish not found, board not detected,
     moves not landing, permission errors, chess.com layout changed (where selectors live).
   - Architecture overview (module map) and developer commands.
   - Logs and config locations.
5. Polish pass over the whole codebase: remove dead code and debug leftovers, consistent naming,
   docstrings on public APIs, no TODOs left without an explanation.
6. Tests: view-model formatting (status colours, eval bar clamp, mate display, tally parsing of
   "You Won", "You Lost", "Draw", "Checkmate", "Resignation", "Stalemate" style texts found live).
7. Live: open the GUI, start the bot, and let it finish one complete game via the panel (CDP mode).
   Save the log under `docs/live-runs/`.

## Acceptance criteria

- `uv run pytest -q`; `uv run mypy --strict src`; `uv run ruff check .`; `uv run ruff format --check .` pass.
- `uv run chess-autoplayer gui --smoke 3` exits 0.
- `bash scripts/setup.sh` runs to completion on this machine.
- One complete game played through the GUI; log saved.
- README covers every item in task 4.

## Report back

1. Files created or changed.
2. Every acceptance command and its real result.
3. Live GUI game result.
4. Known issues and limits.
