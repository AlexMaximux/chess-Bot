# Standing rules for every brief

1. Work only inside this project folder. Never delete, move, or overwrite files outside it. The only exception: the app's own runtime folder `~/.chess-autoplayer/` (created by the app at runtime). Never touch `.ang/`; it belongs to the lead engineer.
2. Python 3.13 via `uv`. Use `uv add` / `uv add --dev` for dependencies. Commit `uv.lock`.
3. Full type hints. `uv run mypy --strict src` must pass. No `Any` unless at a JSON boundary, and then convert to typed models at once.
4. `uv run ruff check .` and `uv run ruff format --check .` must pass. Line length 100.
5. Every I/O path (process launch, websocket, engine, file, OS events) has explicit error handling with a clear, actionable message. No bare `except:`. No silent `except Exception: pass`.
6. Every wait has a timeout. No infinite blocking waits.
7. No hard-coded user-specific absolute paths in code except documented defaults (Chrome app path, Homebrew Stockfish path); each must be overridable in config.
8. Pure logic (state reconstruction, move selection, timing, mouse paths, coordinate math) is separated from I/O and has unit tests. Tests must not need network, Chrome, or a GUI. Engine tests may use the real Stockfish binary if present and must skip cleanly if it is absent.
9. Small modules and functions. Clear names. Docstrings on public functions. Comments explain why, not what.
10. Use `logging` (module loggers), not `print`, except in CLI output.
11. Keep the URL guard: the bot never sends a move unless the page URL path starts with `/play/computer` on host `www.chess.com`.
12. At the end of each brief: run all acceptance commands, then `git add -A && git commit -m "<brief NN: summary>"`. Initialize git in brief 01 with a proper `.gitignore`.
13. Report back exactly as each brief's "Report back" section says. Never claim a command passed unless you ran it and saw it pass.
