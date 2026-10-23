# Brief 03: Hands and game loop

Follow `.ang/RULES.md`. Read `.ang/PLAN.md`. Build on briefs 01–02; keep all tests green.

## Goal

`uv run chess-autoplayer run` plays complete games on `chess.com/play/computer` by itself:
it waits for its turn, thinks with the brain from brief 02, moves the piece with human-like
mouse input (CDP mode by default, real OS cursor optional), verifies the move landed,
handles promotion, and keeps going until the game ends. It then waits for the next game.

## Decisions already made

### Input interface (`input/base.py`)
`MoveInput` protocol: `async perform_move(move: chess.Move, ctx: MoveContext) -> None`, where
`MoveContext` has the board rect, orientation, style (`drag`|`click`), promotion piece, and the
RNG. `async close()`.

### CDP input (`input/cdp_input.py`, default)
- `Input.dispatchMouseEvent` with `mouseMoved` along the path from `human/mouse.py`, then
  `mousePressed` (button `left`, `buttons=1`, `clickCount=1`), moves with `buttons=1` while
  dragging, `mouseReleased`. Sleep each point's `dt_ms`.
- Track the last cursor position between moves so each path starts where the previous one ended
  (first move starts from a random point near the board edge).
- Small human delays: 40–120 ms hover before press, 30–90 ms hold before the first drag move.
- `click` style: move → press/release on source → path to target → press/release.
- `mixed` style: 75% drag, 25% click, chosen per move.

### OS input (`input/os_input.py`, optional)
- `pyobjc-framework-Quartz` (add as a dependency; import lazily so the rest works without it).
- Check Accessibility permission at start (`AXIsProcessTrusted` via `ApplicationServices`, or
  equivalent). If missing, fail with a message telling the user exactly where to grant it
  (System Settings → Privacy & Security → Accessibility → the terminal app they run it from).
- Bring Chrome to the front before each move (`Page.bringToFront` + activate the Chrome app).
- Viewport→screen mapping by **calibration**, not guessed offsets: install a `mousemove` listener
  in the isolated world that stores the last `clientX/clientY`; move the OS cursor to two
  screen points inside the expected viewport; read back the client coordinates; solve
  `screen = scale * client + offset` per axis. Initial guess for those two points comes from
  `Browser.getWindowForTarget` bounds and `window.outerHeight - window.innerHeight`.
  Re-calibrate when the window bounds or `devicePixelRatio` change, and after each game.
  Pure solver in `input/calibration.py` with tests.
- Use `kCGEventMouseMoved`, `kCGEventLeftMouseDown`, `kCGEventLeftMouseDragged`,
  `kCGEventLeftMouseUp`, posted to `kCGHIDEventTap`.
- Safety: before each step, read the real cursor position. If it is more than 40 px away from
  where we left it, the user has taken the mouse: abort the move, release the button if pressed,
  and pause the bot with reason "user moved the mouse".

### Promotion
- Extend `reader.js` to return `promotionOptions: [{"piece": "q", "rect": {...}}]` when the picker is open
  (use the real selectors found in brief 01; re-verify live).
- After the drop, if the picker opens, click the wanted piece (default queen; the engine's choice
  if it under-promotes) with a short human path. If chess.com auto-queens, accept it.

### Controller (`bot/controller.py`)
Async state machine with states: `IDLE`, `BLOCKED_URL`, `WAITING_FOR_GAME`, `OPPONENT_TURN`,
`THINKING`, `MOVING`, `VERIFYING`, `GAME_OVER`, `PAUSED`, `ERROR`, `STOPPED`.
- Poll the snapshot every 250 ms ± 50 ms.
- URL guard first: if not allowed → `BLOCKED_URL`, never move.
- Our turn needs a **stable** read: same FEN in 2 reads ≥ 300 ms apart, `dragging` false, no
  unexpected promotion picker.
- Trust: when `GameState.source == "pieces"` (move list and pieces disagree, e.g. mid-animation),
  do not move until the same fallback FEN has been stable for ≥ 2 s; log a warning when it then moves.
- Our color comes from `GameState.our_color` (which honours the `play_as` setting and `ourColorHint`).
- `THINKING`: run the engine with `asyncio.to_thread`; wait the remaining think time
  (think time minus engine time); during the wait, re-read the page every 250 ms; if the
  position changed, pause, or stop → abandon the move.
- `MOVING` → `VERIFYING`: within 3 s, the move list must have ply+1 and the last move must equal
  ours (compare via python-chess). If not: re-read; if it is still our turn with the same FEN,
  retry once with `click` style; on a second failure go to `ERROR` and pause with a clear reason.
- `GAME_OVER`: log the result from `gameOverText`; when a new game appears (ply resets / FEN changes
  to a new start), continue automatically.
- Commands: `start()`, `pause()`, `resume()`, `stop()`, `set_strength()`, `set_speed()`,
  `set_input_mode()` (takes effect from the next move).
- Publish events through a typed callback/queue for the UI: `StatusEvent(state, message)`,
  `DecisionEvent(move_san, candidates, chosen, eval_cp, think_s)`, `MoveEvent(ply, san, by_bot)`,
  `GameOverEvent(text)`, `ErrorEvent(message)`.
- Reconnect: if the CDP connection drops, retry with backoff (1, 2, 5, 10 s), then `ERROR`.
- Engine runs in a thread; it must never block the event loop.

### `run` CLI
`uv run chess-autoplayer run [--strength NAME] [--speed X] [--input cdp|os] [--style drag|click|mixed] [--seed N]`.
Prints one line per state change, decision, and move. Ctrl+C stops cleanly (release any pressed
mouse button, close the engine, close CDP; Chrome stays open).

## Tasks

1. `input/base.py`, `input/cdp_input.py`, `input/calibration.py`, `input/os_input.py`.
2. Promotion support in `reader.js`, snapshot model, and input.
3. `bot/controller.py` and the event types (`bot/events.py`).
4. `run` CLI.
5. Tests with fakes (`FakePage` feeding scripted snapshots, `FakeEngine`, `FakeInput`, fake clock/sleep
   so tests are fast):
   - plays only on our turn and only after a stable read;
   - blocked URL → never calls input;
   - position change during thinking → move abandoned;
   - verify success; verify failure → one retry with click; second failure → `ERROR` + paused;
   - pause stops moves, resume continues; stop exits within 1 s;
   - game over → waits → new game continues;
   - CDP input emits the right event sequence (moved…, pressed, moved with buttons=1…, released) for drag and click;
   - calibration solver recovers known scale/offset from two points, rejects degenerate input;
   - promotion option is clicked when the picker is open.
6. Live test: run the bot for at least one full game as white and one as black against a chess.com
   bot in CDP mode with `--strength club`. Save the run logs under `docs/live-runs/` (create the folder)
   with the result. Try OS mode for a few moves; if Accessibility permission is missing, record that
   the permission check printed the correct message.

## Acceptance criteria

- `uv run pytest -q`; `uv run mypy --strict src`; `uv run ruff check .`; `uv run ruff format --check .` all pass.
- Live: at least one complete game as white and one as black finished by the bot in CDP mode
  without manual help; logs saved in `docs/live-runs/`.
- Run the bot with Chrome on a non-allowed URL (e.g. `https://www.chess.com/play/online`): it reports
  `BLOCKED_URL` and sends no input.

## Out of scope

Tkinter UI, README (brief 04).

## Report back

1. Files created or changed.
2. Every acceptance command and its real result.
3. Live game results (color, bot opponent, result, moves played, any retries or errors).
4. OS-mode outcome.
5. Known issues.
