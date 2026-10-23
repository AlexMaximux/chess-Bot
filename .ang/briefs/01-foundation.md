# Brief 01: Foundation (Chrome + CDP + board reading)

Follow `.ang/RULES.md`. Read `.ang/PLAN.md` first: it has the architecture and the verified chess.com DOM facts.

## Goal

After this brief, `uv run chess-autoplayer probe` launches (or attaches to) the real Google
Chrome with the app's own profile, opens `https://www.chess.com/play/computer`, reads the
board through raw CDP in an isolated world, and prints a full game state: FEN, our color,
whose turn, move list, board rectangle, and game-over status. Pure logic is unit-tested
against real captured fixtures.

## Decisions already made

- Package `chess_autoplayer`, src layout, `uv` project, Python 3.13 (`.python-version`).
- Runtime deps: `python-chess`, `websockets`. Dev deps: `pytest`, `mypy`, `ruff`.
  (`pyobjc-framework-Quartz` comes in brief 03.)
- Console script: `chess-autoplayer = chess_autoplayer.__main__:main` with subcommands
  `probe`, `run`, `gui` (`run`/`gui` may print "not implemented yet" in this brief).
- `reader.js` ships as package data and is loaded with `importlib.resources`.
- Default debug port: `9333`. Default profile dir: `~/.chess-autoplayer/chrome-profile`.
- CDP: connect to the **browser** websocket (`/json/version` → `webSocketDebuggerUrl`) and use
  `Target.*` with `flatten: true` sessions. Do not use `/json/new` (needs PUT, changes by version).
- **Do not call `Runtime.enable`, `Debugger.enable`, `Console.enable`, or `Log.enable`.**
  Pages can detect them. Evaluate code in an isolated world:
  `Page.getFrameTree` → `Page.createIsolatedWorld(frameId, worldName="cap")` →
  `Runtime.evaluate(contextId=..., returnByValue=true, awaitPromise=true)`.
  `Page.enable` is allowed. Recreate the isolated world after navigation
  (`Page.frameNavigated` for the main frame) and when evaluate fails with a context error.
- Launch Chrome with only: `--remote-debugging-port=<port>`, `--user-data-dir=<profile>`,
  `--no-first-run`, `--no-default-browser-check`, and the start URL. **No** `--enable-automation`,
  no `--headless`, no other automation flags. Start it detached (`start_new_session=True`) so
  Chrome stays open when the app exits. If the port already answers, attach instead of launching.
  Wait up to 20 s for the port, then fail with a clear message.
- If no tab is on chess.com, create one with `Target.createTarget(url=start_url)`. If a tab is on
  `/play/computer`, use it. If several match, use the most recently focused/first one and log it.

## Tasks

1. Scaffold: `pyproject.toml` (ruff, mypy strict, pytest config), `.python-version`, `.gitignore`
   (include `.venv`, `__pycache__`, `.mypy_cache`, `.ruff_cache`, `*.log`), `git init`,
   `src/chess_autoplayer/__init__.py`, `py.typed`.
2. `config.py`: frozen dataclass `Settings` with: `chrome_path`, `stockfish_path`,
   `profile_dir`, `debug_port`, `start_url`, plus placeholders for later briefs:
   `strength` (default `"club"`), `input_mode` (`"cdp"` | `"os"`, default `"cdp"`),
   `move_style` (`"drag"` | `"click"` | `"mixed"`, default `"mixed"`). Load/save JSON at
   `~/.chess-autoplayer/config.json`; unknown keys ignored with a warning; invalid values
   raise a clear error. Paths expand `~`.
3. `logging_setup.py`: console + rotating file log in `~/.chess-autoplayer/logs/app.log`.
4. `chrome/launcher.py`: find Chrome (config path, then standard macOS path), check port,
   launch or attach, return the browser websocket URL.
5. `chrome/cdp.py`: async CDP client. Message ids, per-command futures with timeout (default 10 s),
   CDP error responses raised as a typed `CDPError`, event handlers per session, clean `close()`,
   and a `ConnectionLost` error when the socket drops.
6. `chrome/page.py`: `ChessPage` that attaches to the target, keeps the isolated world, exposes
   `async evaluate_json(expression) -> object`, `async url() -> str`, and the URL guard
   `is_allowed_url(url: str) -> bool` (pure function: scheme `https`, host `www.chess.com`,
   path starts with `/play/computer`; everything else false, including `chess.com/play/online`,
   lookalike hosts, and `http`).
7. `board/reader.js`: one function, no side effects, no global state, returning:
   ```json
   {
     "url": "...", "found": true,
     "boardRect": {"x": 0, "y": 0, "width": 0, "height": 0},
     "flippedClass": false, "flippedGeometry": false,
     "pieces": [{"color": "w", "type": "n", "square": "g1"}],
     "moves": ["e4", "e6", "Nf3"],
     "lastMoveHighlights": ["e7", "e6"],
     "gameOver": false, "gameOverText": null,
     "promotionOpen": false,
     "devicePixelRatio": 2,
     "window": {"screenX": 0, "screenY": 0, "outerWidth": 0, "outerHeight": 0, "innerWidth": 0, "innerHeight": 0},
     "dragging": false
   }
   ```
   - `found:false` (and empty fields) when there is no board.
   - `flippedGeometry`: compute from rendered piece/coordinate positions (e.g. the y of a rank-1
     piece vs the board centre, or the board's coordinate labels), not from classes.
   - Figurine notation: replace any `[data-figurine]` icon with its letter before reading SAN.
   - Strip annotation glyphs (`!`, `?`, `+`, `#` stay; remove `!?` etc. only if python-chess cannot parse them).
   - `gameOver`: detect the game-over modal / result banner; discover the real selector live (see task 10)
     and put the text in `gameOverText`.
   - `promotionOpen`: detect the promotion piece picker; discover the real selector live.
   - `dragging`: true if a piece is currently being dragged (e.g. a `dragging` class), so later briefs never read mid-drag.
8. `board/snapshot.py`: typed `Snapshot` (dataclasses), `parse_snapshot(raw: object) -> Snapshot`
   with strict validation and a clear `SnapshotError`.
9. `board/state.py`: `GameState` built from a `Snapshot`:
   - Rebuild a `chess.Board` by pushing the SAN list from the start position.
   - Compare its piece placement with the DOM pieces. If equal: `source="moves"`.
   - If SAN parsing fails or placement differs: build from DOM pieces; side to move = white when
     the move count is even else black; castling rights inferred from king/rook home squares;
     no en passant; `source="pieces"` and log a warning. If even that board is invalid, raise
     `StateError`.
   - `our_color` from `flippedGeometry` (fallback `flippedClass`); log a warning if they disagree.
   - Properties: `fen`, `turn`, `is_our_turn`, `is_game_over` (DOM `gameOver` or board outcome),
     `ply`, `last_move`.
   - Pure: no I/O.
10. Live discovery and fixtures. Add `scripts/dev_move.py` (dev only, not part of the package):
    attaches with the app's CDP client and plays one move given as UCI (e.g. `e2e4`) with a
    simple straight drag via `Input.dispatchMouseEvent`, so you can drive real games.
    Then, with the real Chrome:
    - accept the cookie banner, start a game against a bot as **white**, play at least 6 moves,
    - start a game as **black** (flipped board), play at least 4 moves,
    - reach a game-over screen (e.g. resign or get mated quickly),
    - open a promotion picker if feasible (otherwise note it in the report),
    and save real snapshots with `uv run chess-autoplayer probe --save-fixture <name>` into
    `tests/fixtures/<name>.json`. Use what you see to set the real selectors in `reader.js`.
11. `__main__.py`: `probe [--save-fixture NAME] [--json]` prints a readable summary (FEN, our color,
    turn, last move, ply, game over, URL allowed yes/no, board rect) or raw JSON.
12. Tests (`tests/`):
    - URL guard: allowed and rejected cases (at least 10).
    - Snapshot parsing: valid, missing fields, wrong types.
    - State from each real fixture (white, black/flipped, game over).
    - Synthetic fixtures: castling both sides, en passant, promotion with `=Q`, figurine-converted SAN,
      mismatch fallback path, invalid board → `StateError`.
    - Config load/save round trip, unknown key, invalid value.
    - CDP client with a fake in-process websocket server: command/response, CDP error, timeout,
      event dispatch by session.

## Acceptance criteria

- `uv sync` succeeds.
- `uv run pytest -q` passes (0 failures).
- `uv run mypy --strict src` passes.
- `uv run ruff check .` and `uv run ruff format --check .` pass.
- With a game open in Chrome, `uv run chess-autoplayer probe` prints a FEN that matches the
  board, the correct color, and the correct side to move.
- `tests/fixtures/` holds at least 3 real captured fixtures (white mid-game, black mid-game, game over).
- No `Runtime.enable`/`Debugger.enable`/`Console.enable`/`Log.enable` anywhere in `src/`.

## Out of scope

Engine, move selection, timing, real move input in the package (only the dev script), UI.

## Report back

1. Files created.
2. Every acceptance command and its real result (pass/fail with counts).
3. The real selectors you found for game over, promotion picker, flipped board, and dragging.
4. Anything you could not do, and why.
