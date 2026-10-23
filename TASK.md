# Work Status

## [x] Step 2 - Structural: unblock URL guard
Files: `config.py:32`, `chrome/page.py:21-47`, `bot/controller.py` (`is_allowed_url`)
- [x] add mode field: bot or human, default bot
- [x] in human mode only check chess.com domain, not path
- [x] allow: `play/computer`, `play/online`, `live`, `game/live`
- [x] url change between two games = new game, not disconnect
- Verified: `tests/test_page_guard.py`, `tests/test_config.py`, `tests/test_controller.py`

## [x] Step 3 - reader.js: color detection
- [x] detect our color by matching logged-in username against
  `board-layout-player-top` / `board-layout-player-bottom`
- [x] fallback to board geometry if username not found
- [x] read both clocks from DOM, read move list, output structured
- Verified: `tests/test_reader_js.py`, `tests/test_snapshot.py`, `tests/test_state.py`

## [x] Step 4 - timing: clock aware
- [x] budget as function of remaining clock and increment
- [x] panic mode when clock low (< 10s with 0 inc)
- [x] keep human jitter (log-normal without flat clipping)
- Verified: `tests/test_timing.py`

## [x] Step 5 - lifecycle
- [x] detect game end, click New Game / Rematch
- [x] handle dynamic `/game/live/<id>` without reset
- Verified: `tests/test_controller.py`, `tests/test_reader_js.py`