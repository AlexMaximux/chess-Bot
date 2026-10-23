# Brief 02: Brain (engine, move choice, human timing, mouse paths)

Follow `.ang/RULES.md`. Read `.ang/PLAN.md`. Build on brief 01; do not break its tests.

## Goal

Pure, tested modules that decide *what* to play and *how a human would play it*:
Stockfish analysis with strength profiles, human-like move choice, think time, and
curved mouse paths. No browser input yet.

## Decisions already made

- Engine through `chess.engine.SimpleEngine.popen_uci` (sync API) wrapped in our own class.
  The controller in brief 03 will call it from a worker thread.
- Strength profiles (name → settings). Put them in one table in `engine/profiles.py`:

  | name | UCI_LimitStrength / UCI_Elo | analysis limit | MultiPV | temperature (cp) | max cp loss | blunder chance |
  |---|---|---|---|---|---|---|
  | `beginner` | on / 1350 | 0.10 s | 5 | 120 | 400 | 6% |
  | `casual` | on / 1600 | 0.15 s | 5 | 80 | 250 | 3% |
  | `club` (default) | on / 1900 | 0.25 s | 4 | 45 | 150 | 1.5% |
  | `strong` | on / 2300 | 0.40 s | 3 | 20 | 80 | 0.5% |
  | `master` | off | 0.80 s | 3 | 10 | 40 | 0% |
  | `max` | off | 1.50 s | 1 | 0 | 0 | 0% |

  Clamp UCI_Elo to the engine's real `UCI_Elo` option min/max read at start-up.
  Also set `Threads` = min(4, cpu_count) and `Hash` = 128.
- Move choice (`engine/selector.py`, pure, takes an injectable `random.Random`):
  1. Candidates = MultiPV lines with score from our point of view (mate scores mapped to ±100000 minus distance).
  2. If any candidate mates or the best is a forced mate for us, play the fastest mate.
  3. If only one legal move, play it.
  4. Drop candidates worse than best by more than `max cp loss`.
  5. With probability `blunder chance`, and only if the position is not already lost and the best line
     is not a mate, allow candidates up to 2× max cp loss.
  6. Pick with softmax over `-loss / temperature` (temperature 0 → always best).
  7. Never pick a move that allows mate-in-1 unless all legal moves do.
  Return the move plus a `Decision` record (candidates, losses, chosen index, reason) for logging and the UI.
- Think time (`human/timing.py`, pure, injectable RNG), in seconds:
  - Book phase (ply < 10 and the move is among the top-2): 0.6–2.0 s.
  - Only legal move or obvious recapture (best move captures on the square of the last capture
    and is ≥ 150 cp better than the second): 0.4–1.2 s.
  - Otherwise base by complexity: legal-move count, eval spread among candidates, check, material
    on board. Lognormal noise (sigma ≈ 0.35). Typical 2–10 s, hard cap 25 s.
  - Clock-aware: if a clock value is given, never exceed 5% of remaining time; under 20 s left,
    cap at 1.5 s.
  - A global `speed` multiplier in settings (default 1.0).
- Mouse path (`human/mouse.py`, pure, injectable RNG):
  - Input: start and end points (CSS px), square size. Output: list of `(x, y, dt_ms)` points.
  - Cubic Bezier with 1–2 control points offset perpendicular to the line (random side, 5–25% of
    distance), ease-in-out velocity, small Gaussian jitter (≤ 1.5 px), 8–12 ms between points.
  - Duration by Fitts's law: `a + b * log2(distance / width + 1)` with a ≈ 120 ms, b ≈ 150 ms,
    plus noise; clamp 180–900 ms.
  - Overshoot (25% chance on long moves) then correct back.
  - Target point: random point inside the target square's central 60%, not the exact centre.
  - Also a helper for the idle "hover" move to the source piece before pressing.
- Coordinate math (`board/geometry.py`, pure): square ↔ CSS point given board rect and
  orientation (`flipped`). Square centre and random inner point.

## Tasks

1. `engine/profiles.py`, `engine/stockfish.py` (`Engine` class: start, `analyse(board) -> list[Line]`,
   `close()`, context manager, restart once on crash, clear error when the binary is missing).
2. `engine/selector.py` as above.
3. `human/timing.py` as above.
4. `human/mouse.py` as above.
5. `board/geometry.py` as above.
6. Wire `strength` and a new `speed` setting into `Settings` (validated).
7. CLI: `uv run chess-autoplayer analyse --fen "<FEN>" [--strength club] [--seed N]` prints the
   candidates, chosen move, reason, and think time. If `--fen` is omitted, read the live page
   state (like `probe`) and analyse it.
8. Tests:
   - Selector: mate-in-1 always taken; single legal move; temperature 0 → best; max cp loss
     respected over 1000 seeded draws; blunder chance bounds; never allows mate-in-1 when avoidable;
     works for black to move (score sign).
   - Timing: bounds for each branch over 1000 seeded draws; clock caps; speed multiplier.
   - Mouse: path starts at start, ends inside target inner area, duration within clamp, monotone time,
     overshoot correction ends on target.
   - Geometry: all 64 squares round-trip both orientations.
   - Engine (skip if Stockfish missing): finds mate-in-1 in a known FEN at `max`; profiles start with
     valid options; `close()` is idempotent.

## Acceptance criteria

- `uv run pytest -q` passes; `uv run mypy --strict src`; `uv run ruff check .`; `uv run ruff format --check .`.
- `uv run chess-autoplayer analyse --fen "6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1" --strength club --seed 1`
  chooses `d1d8` (mate in 1).
- `uv run chess-autoplayer analyse --fen "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1" --strength club --seed 1`
  prints a sensible opening move and a think time in the book range.

## Out of scope

Sending input to the browser, the controller loop, the UI.

## Report back

1. Files created or changed.
2. Every acceptance command and its real result.
3. Any deviation from the decisions above, with the reason.
