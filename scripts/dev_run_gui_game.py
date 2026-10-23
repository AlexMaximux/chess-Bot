#!/usr/bin/env python3
"""Run one complete game live through the GUI AutoplayerApp control panel.

Starts AutoplayerApp in Tkinter mainloop, triggers start, plays a full game against
the computer bot (Martin), logs all events to docs/live-runs/gui_game.log, and closes
cleanly when GAME_OVER is reached.
"""

import logging
import sys
import tkinter as tk
from dataclasses import replace
from pathlib import Path

from chess_autoplayer.bot.events import (
    BotEvent,
    DecisionEvent,
    GameOverEvent,
    MoveEvent,
    StatusEvent,
)
from chess_autoplayer.ui.app import AutoplayerApp


def main() -> int:
    log_dir = Path("docs/live-runs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "gui_game.log"

    print("=== Live GUI Game Test ===")
    print(f"Log will be saved to: {log_file}")

    # Set up file logger for the GUI run
    f_handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    f_handler.setFormatter(formatter)
    root_logger = logging.getLogger()
    root_logger.addHandler(f_handler)
    root_logger.setLevel(logging.INFO)

    root = tk.Tk()
    app = AutoplayerApp(root)

    # Use club profile and speed 2.5 for prompt live game play
    app.strength_var.set("club")
    app.speed_var.set(2.5)
    app.input_mode_var.set("cdp")
    app.settings = replace(app.settings, strength="club", speed=2.5, input_mode="cdp")

    # Wrap app._handle_bot_event to log all events and monitor game over
    orig_handle = app._handle_bot_event
    game_over_reached = False

    def wrapped_handle(event: BotEvent) -> None:
        nonlocal game_over_reached
        orig_handle(event)

        with open(log_file, "a", encoding="utf-8") as f:
            if isinstance(event, StatusEvent):
                f.write(f"[{event.state.value}] {event.message}\n")
            elif isinstance(event, MoveEvent):
                role = "bot" if event.by_bot else "opponent"
                f.write(f"[MOVE] ply {event.ply}: {event.san} ({role})\n")
            elif isinstance(event, DecisionEvent):
                f.write(
                    f"[DECISION] {event.move_san} (eval={event.eval_cp:+d} cp, "
                    f"think={event.think_s:.2f}s)\n"
                )
            elif isinstance(event, GameOverEvent):
                f.write(f"[GAME_OVER] {event.text}\n")
                print(f"GAME_OVER reached in GUI: {event.text}")
                game_over_reached = True
                # Allow 3 seconds for UI update and latch verification, then close cleanly
                root.after(3000, app._on_close)

    app._handle_bot_event = wrapped_handle  # type: ignore[assignment]

    # Trigger start 800ms after GUI opens
    def trigger_start() -> None:
        print("Triggering app._on_start() from GUI...")
        app._on_start()

    root.after(800, trigger_start)

    # Timeout safety after 300s (5 minutes)
    def on_timeout() -> None:
        if not game_over_reached:
            print("ERROR: GUI game timed out after 300s", file=sys.stderr)
            app._on_close()

    root.after(300000, on_timeout)

    print("Running Tkinter mainloop...")
    root.mainloop()

    if game_over_reached:
        print("SUCCESS: Full game completed cleanly via the GUI!")
        return 0
    else:
        print("FAILURE: Game did not complete to GAME_OVER", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
