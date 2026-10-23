#!/usr/bin/env python3
"""Run one complete game live through the GUI AutoplayerApp control panel for Review 04-r1.

Performs:
1. Strength change once ('casual' -> 'club')
2. Move style change once ('drag' -> 'click')
3. Pause for ~10 seconds, then resume
4. Plays until GAME_OVER is reached
5. Saves consolidated log to docs/live-runs/gui_game_r1.log
"""

import logging
import sys
import time
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
    log_file = log_dir / "gui_game_r1.log"

    print("=== Live GUI Game Review 04-r1 Test ===")
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

    # Initial settings: casual strength, drag move style, 2.5x speed
    app.strength_var.set("casual")
    app.strength_combo.set("casual")
    app.style_var.set("drag")
    app.style_combo.set("drag")
    app.speed_var.set(2.5)
    app.input_mode_var.set("cdp")
    app.settings = replace(
        app.settings, strength="casual", speed=2.5, move_style="drag", input_mode="cdp"
    )

    # Action tracking
    bot_move_count = 0
    strength_changed = False
    style_changed = False
    pause_triggered = False
    resumed = False
    game_over_reached = False
    pause_time: float = 0.0

    orig_handle = app._handle_bot_event

    def log_line(msg: str) -> None:
        print(msg)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")

    def trigger_resume() -> None:
        nonlocal resumed
        resumed = True
        elapsed = time.monotonic() - pause_time
        log_line(
            f"[USER_ACTION] Resuming game after {elapsed:.1f}s pause via app._on_toggle_pause()"
        )
        app._on_toggle_pause()

    def wrapped_handle(event: BotEvent) -> None:
        nonlocal bot_move_count, strength_changed, style_changed
        nonlocal pause_triggered, game_over_reached, pause_time
        orig_handle(event)

        if isinstance(event, StatusEvent):
            log_line(f"[STATUS] [{event.state.value}] {event.message}")
        elif isinstance(event, MoveEvent):
            role = "bot" if event.by_bot else "opponent"
            log_line(f"[MOVE] ply {event.ply}: {event.san} ({role})")

            if event.by_bot:
                bot_move_count += 1

                # Action 1: On bot move 1, change strength from 'casual' to 'club'
                if bot_move_count == 1 and not strength_changed:
                    strength_changed = True
                    log_line("[USER_ACTION] Changing strength profile from 'casual' to 'club'")
                    app.strength_var.set("club")
                    app.strength_combo.set("club")
                    app._on_strength_changed()

                # Action 2: On bot move 2, change move style from 'drag' to 'click'
                elif bot_move_count == 2 and not style_changed:
                    style_changed = True
                    log_line("[USER_ACTION] Changing move style from 'drag' to 'click'")
                    app.style_var.set("click")
                    app.style_combo.set("click")
                    app._on_style_changed()

                # Action 3: On bot move 3, pause for ~10 seconds
                elif bot_move_count == 3 and not pause_triggered:
                    pause_triggered = True
                    pause_time = time.monotonic()
                    log_line("[USER_ACTION] Pausing playback for 10.0s via app._on_toggle_pause()")
                    app._on_toggle_pause()
                    root.after(10000, trigger_resume)

        elif isinstance(event, DecisionEvent):
            log_line(
                f"[DECISION] {event.move_san} "
                f"(eval={event.eval_cp:+d} cp, think={event.think_s:.2f}s)"
            )
        elif isinstance(event, GameOverEvent):
            log_line(f"[GAME_OVER] {event.text}")
            print(f"GAME_OVER reached in GUI: {event.text}")
            game_over_reached = True
            root.after(3000, app._on_close)

    app._handle_bot_event = wrapped_handle  # type: ignore[assignment]

    # Trigger start 800ms after GUI opens
    def trigger_start() -> None:
        log_line("[GUI] Triggering app._on_start()...")
        app._on_start()

    root.after(800, trigger_start)

    # Timeout safety after 360s (6 minutes)
    def on_timeout() -> None:
        if not game_over_reached:
            print("ERROR: GUI game timed out after 360s", file=sys.stderr)
            app._on_close()

    root.after(360000, on_timeout)

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
