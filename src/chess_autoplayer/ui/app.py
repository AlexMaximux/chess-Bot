"""Tkinter and ttk desktop control panel for Chess Autoplayer."""

from __future__ import annotations

import asyncio
import logging
import queue
import sys
import threading
import tkinter as tk
from dataclasses import replace
from tkinter import ttk
from typing import Any

import chess

from chess_autoplayer.bot.controller import BotController
from chess_autoplayer.bot.events import (
    BotEvent,
    BotState,
    DecisionEvent,
    ErrorEvent,
    GameOverEvent,
    MoveEvent,
    StatusEvent,
)
from chess_autoplayer.chrome.cdp import CDPClient
from chess_autoplayer.chrome.launcher import launch_or_attach_chrome
from chess_autoplayer.chrome.page import ChessPage, find_or_create_chess_tab
from chess_autoplayer.config import Settings, load_config, save_config
from chess_autoplayer.engine.profiles import PROFILES
from chess_autoplayer.engine.stockfish import Engine
from chess_autoplayer.input.base import MoveInput
from chess_autoplayer.input.cdp_input import CDPInput
from chess_autoplayer.input.os_input import OSInput, is_accessibility_trusted
from chess_autoplayer.ui.view_model import (
    COLOR_NEUTRAL,
    SessionTally,
    format_decision,
    format_eval,
    format_move_log_row,
    format_status,
)

logger = logging.getLogger(__name__)


class AutoplayerApp:
    """Tkinter-based desktop control panel."""

    def __init__(self, root: tk.Tk, smoke_seconds: float | None = None) -> None:
        self.root = root
        self.smoke_seconds = smoke_seconds
        self.settings: Settings = load_config()

        # Threading and async infrastructure
        self._event_queue: queue.Queue[BotEvent | str] = queue.Queue()
        self._loop = asyncio.new_event_loop()
        self._worker_thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self._worker_thread.start()

        # Runtime instances managed on worker thread
        self._cdp: CDPClient | None = None
        self._page: ChessPage | None = None
        self._engine: Engine | None = None
        self._controller: BotController | None = None

        # Presentation tracking
        self._tally = SessionTally()
        self._current_state = BotState.STOPPED
        self._last_our_color = self.settings.play_as
        self._speed_save_after_id: str | None = None
        self._last_applied_speed: float = self.settings.speed

        # Build UI layout
        self._setup_window()
        self._create_widgets()
        self._bind_shortcuts()

        # Start periodic queue polling
        self.root.after(50, self._poll_queue)

        # Handle smoke test if requested
        if self.smoke_seconds is not None:
            self.root.after(int(self.smoke_seconds * 1000), self._on_smoke_exit)

    def _setup_window(self) -> None:
        self.root.title("Chess Autoplayer")
        self.root.minsize(420, 640)
        self.root.geometry("460x700")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Style configuration
        self.style = ttk.Style()
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass

    def _create_widgets(self) -> None:
        main_frame = ttk.Frame(self.root, padding=12)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 1. Status section
        status_frame = ttk.LabelFrame(main_frame, text="Status", padding=8)
        status_frame.pack(fill=tk.X, pady=(0, 8))

        self.status_var = tk.StringVar(value="[STOPPED] Ready to connect")
        self.status_label = tk.Label(
            status_frame,
            textvariable=self.status_var,
            fg="white",
            bg=COLOR_NEUTRAL,
            font=("Helvetica", 11, "bold"),
            padx=8,
            pady=4,
            anchor="w",
        )
        self.status_label.pack(fill=tk.X)

        # 2. Control buttons
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(0, 8))

        self.btn_open_chrome = ttk.Button(
            btn_frame, text="Open Chrome", command=self._on_open_chrome
        )
        self.btn_open_chrome.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 4))

        self.btn_start = ttk.Button(btn_frame, text="Start", command=self._on_start)
        self.btn_start.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)

        self.btn_pause = ttk.Button(
            btn_frame, text="Pause", command=self._on_toggle_pause, state=tk.DISABLED
        )
        self.btn_pause.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)

        self.btn_stop = ttk.Button(btn_frame, text="Stop", command=self._on_stop, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(4, 0))

        # 3. Settings panel
        settings_frame = ttk.LabelFrame(main_frame, text="Settings", padding=8)
        settings_frame.pack(fill=tk.X, pady=(0, 8))

        # Row 1: Strength profile
        row1 = ttk.Frame(settings_frame)
        row1.pack(fill=tk.X, pady=2)
        ttk.Label(row1, text="Strength:", width=12).pack(side=tk.LEFT)
        self.strength_var = tk.StringVar(value=self.settings.strength)
        self.strength_combo = ttk.Combobox(
            row1,
            textvariable=self.strength_var,
            values=list(PROFILES.keys()),
            state="readonly",
            width=16,
        )
        self.strength_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.strength_combo.bind("<<ComboboxSelected>>", self._on_strength_changed)

        # Row 2: Speed slider
        row2 = ttk.Frame(settings_frame)
        row2.pack(fill=tk.X, pady=2)
        ttk.Label(row2, text="Speed:", width=12).pack(side=tk.LEFT)
        self.speed_val_label = ttk.Label(row2, text=f"{self.settings.speed:.1f}x", width=6)
        self.speed_val_label.pack(side=tk.RIGHT)
        self.speed_var = tk.DoubleVar(value=self.settings.speed)
        self.speed_scale = ttk.Scale(
            row2,
            from_=0.5,
            to=2.0,
            variable=self.speed_var,
            command=self._on_speed_changed,
        )
        self.speed_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Row 3: Input mode (CDP vs OS)
        row3 = ttk.Frame(settings_frame)
        row3.pack(fill=tk.X, pady=2)
        ttk.Label(row3, text="Input mode:", width=12).pack(side=tk.LEFT)
        self.input_mode_var = tk.StringVar(value=self.settings.input_mode)
        ttk.Radiobutton(
            row3,
            text="Browser (CDP)",
            variable=self.input_mode_var,
            value="cdp",
            command=self._on_input_mode_changed,
        ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Radiobutton(
            row3,
            text="Real mouse (OS)",
            variable=self.input_mode_var,
            value="os",
            command=self._on_input_mode_changed,
        ).pack(side=tk.LEFT)

        # Row 4: Move style (drag, click, mixed)
        row4 = ttk.Frame(settings_frame)
        row4.pack(fill=tk.X, pady=2)
        ttk.Label(row4, text="Move style:", width=12).pack(side=tk.LEFT)
        self.style_var = tk.StringVar(value=self.settings.move_style)
        self.style_combo = ttk.Combobox(
            row4,
            textvariable=self.style_var,
            values=["mixed", "drag", "click"],
            state="readonly",
            width=16,
        )
        self.style_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.style_combo.bind("<<ComboboxSelected>>", self._on_style_changed)

        # 4. Evaluation bar
        eval_frame = ttk.LabelFrame(main_frame, text="Evaluation", padding=6)
        eval_frame.pack(fill=tk.X, pady=(0, 8))

        eval_row = ttk.Frame(eval_frame)
        eval_row.pack(fill=tk.X)
        self.eval_progress = ttk.Progressbar(
            eval_row, orient=tk.HORIZONTAL, mode="determinate", maximum=100
        )
        self.eval_progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self.eval_progress["value"] = 50  # 50% = equal 0.0

        self.eval_label_var = tk.StringVar(value="0.0")
        self.eval_label = ttk.Label(
            eval_row, textvariable=self.eval_label_var, font=("Helvetica", 10, "bold"), width=6
        )
        self.eval_label.pack(side=tk.RIGHT)

        # 5. Last decision info
        decision_frame = ttk.LabelFrame(main_frame, text="Last Decision", padding=6)
        decision_frame.pack(fill=tk.X, pady=(0, 8))
        self.decision_var = tk.StringVar(value="No moves played yet")
        self.decision_label = ttk.Label(
            decision_frame,
            textvariable=self.decision_var,
            justify=tk.LEFT,
            font=("Helvetica", 9),
        )
        self.decision_label.pack(fill=tk.X)

        # 6. Move log table
        log_frame = ttk.LabelFrame(main_frame, text="Move Log", padding=4)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 6))

        tree_scroll = ttk.Scrollbar(log_frame)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree = ttk.Treeview(
            log_frame,
            columns=("turn", "san", "role"),
            show="headings",
            yscrollcommand=tree_scroll.set,
            height=6,
        )
        tree_scroll.config(command=self.tree.yview)

        self.tree.heading("turn", text="Turn")
        self.tree.heading("san", text="Move")
        self.tree.heading("role", text="Player")
        self.tree.column("turn", width=60, anchor="center")
        self.tree.column("san", width=80, anchor="center")
        self.tree.column("role", width=90, anchor="center")
        self.tree.pack(fill=tk.BOTH, expand=True)

        # 7. Session tally
        self.tally_var = tk.StringVar(value=self._tally.format())
        self.tally_label = ttk.Label(
            main_frame,
            textvariable=self.tally_var,
            font=("Helvetica", 9, "bold"),
            anchor="center",
        )
        self.tally_label.pack(fill=tk.X, pady=(0, 4))

        # 8. Footer note
        footer = ttk.Label(
            main_frame,
            text="Works only on chess.com/play/computer.",
            font=("Helvetica", 8, "italic"),
            foreground="#6b7280",
            anchor="center",
        )
        footer.pack(fill=tk.X)

    def _bind_shortcuts(self) -> None:
        self.root.bind("<space>", lambda e: self._on_toggle_pause())
        self.root.bind("<Escape>", lambda e: self._on_stop())

    def _run_async_loop(self) -> None:
        """Background thread target driving the asyncio event loop."""
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _poll_queue(self) -> None:
        """Poll incoming events from worker thread on Tk's main thread."""
        try:
            while True:
                item = self._event_queue.get_nowait()
                if isinstance(item, BotEvent):
                    self._handle_bot_event(item)
                elif isinstance(item, str):
                    self._update_status(BotState.IDLE, item)
        except queue.Empty:
            pass

        self.root.after(50, self._poll_queue)

    def _update_status(self, state: BotState | str, message: str) -> None:
        text, color = format_status(state, message)
        self.status_var.set(text)
        self.status_label.config(bg=color)
        if isinstance(state, BotState):
            self._current_state = state

    def _handle_bot_event(self, event: BotEvent) -> None:
        if isinstance(event, StatusEvent):
            self._update_status(event.state, event.message)
            if event.state == BotState.PAUSED:
                self.btn_pause.config(text="Resume")
            elif event.state == BotState.ERROR:
                self.btn_pause.config(text="Resume")
            elif event.state in (
                BotState.THINKING,
                BotState.MOVING,
                BotState.OPPONENT_TURN,
                BotState.IDLE,
            ):
                self.btn_pause.config(text="Pause")

        elif isinstance(event, DecisionEvent):
            self.decision_var.set(format_decision(event.move_san, event.candidates, event.think_s))
            # Update eval bar
            top_candidate = event.candidates[0] if event.candidates else None
            mate_score = top_candidate.mate_score if top_candidate else None
            frac, label = format_eval(event.eval_cp, mate_score=mate_score)
            self.eval_progress["value"] = int(frac * 100)
            self.eval_label_var.set(label)

        elif isinstance(event, MoveEvent):
            turn_str, san_str, role_str = format_move_log_row(event.ply, event.san, event.by_bot)
            item_id = self.tree.insert("", tk.END, values=(turn_str, san_str, role_str))
            self.tree.see(item_id)

        elif isinstance(event, GameOverEvent):
            our_color = (
                self._controller.page_color
                if (self._controller and hasattr(self._controller, "page_color"))
                else self._last_our_color
            )
            color_arg = chess.WHITE if our_color in ("w", "white", chess.WHITE) else chess.BLACK
            self._tally.record_game(event.text, our_color=color_arg)
            self.tally_var.set(self._tally.format())

        elif isinstance(event, ErrorEvent):
            self._update_status(BotState.ERROR, event.message)
            self.btn_pause.config(text="Resume")

    def _on_open_chrome(self) -> None:
        """Launch or focus Chrome and navigate to the computer play tab."""
        self._update_status(BotState.IDLE, "Connecting to Chrome...")

        async def action() -> None:
            try:
                ws_url = await launch_or_attach_chrome(self.settings)
                cdp = await CDPClient.connect(ws_url)
                target_id = await find_or_create_chess_tab(
                    cdp, self.settings.start_url, mode=self.settings.mode
                )
                page = await ChessPage.attach(cdp, target_id)
                await page.ensure_start_url(self.settings.start_url)
                await page.bring_to_front()
                await cdp.close()
                self._event_queue.put(f"Chrome ready on {self.settings.start_url}")
            except Exception as exc:
                logger.error("Open Chrome error: %s", exc)
                self._event_queue.put(ErrorEvent(f"Chrome error: {exc}"))

        asyncio.run_coroutine_threadsafe(action(), self._loop)

    def _on_start(self) -> None:
        """Start the bot controller."""
        self._update_status(BotState.IDLE, "Starting autoplayer...")
        self.btn_start.config(state=tk.DISABLED)
        self.btn_pause.config(state=tk.NORMAL, text="Pause")
        self.btn_stop.config(state=tk.NORMAL)

        # Clear move log on start of new run session
        for row in self.tree.get_children():
            self.tree.delete(row)

        async def action() -> None:
            try:
                ws_url = await launch_or_attach_chrome(self.settings)
                self._cdp = await CDPClient.connect(ws_url)
                target_id = await find_or_create_chess_tab(
                    self._cdp, self.settings.start_url, mode=self.settings.mode
                )
                self._page = await ChessPage.attach(self._cdp, target_id)
                await self._page.ensure_start_url(self.settings.start_url)
                await self._page.bring_to_front()

                # Build input handler
                input_h: MoveInput
                if self.settings.input_mode == "os" and is_accessibility_trusted():
                    input_h = OSInput(self._page)
                else:
                    input_h = CDPInput(self._page)

                # Build engine
                self._engine = Engine(
                    self.settings.resolved_stockfish_path(), profile=self.settings.strength
                )
                self._engine.start()

                # Build reconnect factory
                async def reconnect_factory() -> tuple[ChessPage, MoveInput]:
                    assert self.settings is not None
                    ws = await launch_or_attach_chrome(self.settings)
                    new_cdp = await CDPClient.connect(ws)
                    self._cdp = new_cdp
                    tid = await find_or_create_chess_tab(
                        new_cdp, self.settings.start_url, mode=self.settings.mode
                    )
                    new_pg = await ChessPage.attach(new_cdp, tid)
                    await new_pg.ensure_start_url(self.settings.start_url)
                    self._page = new_pg
                    new_inp: MoveInput = (
                        OSInput(new_pg)
                        if (self.settings.input_mode == "os" and is_accessibility_trusted())
                        else CDPInput(new_pg)
                    )
                    return new_pg, new_inp

                self._controller = BotController(
                    page=self._page,
                    engine=self._engine,
                    input_handler=input_h,
                    settings=self.settings,
                    event_callback=self._event_queue.put,
                    reconnect_factory=reconnect_factory,
                )

                await self._controller.start()
            except Exception as exc:
                logger.error("Controller start error: %s", exc)
                self._event_queue.put(ErrorEvent(f"Start error: {exc}"))

        asyncio.run_coroutine_threadsafe(action(), self._loop)

    def _on_toggle_pause(self) -> None:
        """Toggle pause/resume state."""
        if self._controller is None:
            return

        if self._controller.is_paused:
            self._loop.call_soon_threadsafe(self._controller.resume)
            self.btn_pause.config(text="Pause")
        else:
            self._loop.call_soon_threadsafe(self._controller.pause)
            self.btn_pause.config(text="Resume")

    def _on_stop(self) -> None:
        """Stop the controller and release resources cleanly."""
        self._update_status(BotState.STOPPED, "Stopping autoplayer...")
        self.btn_start.config(state=tk.NORMAL)
        self.btn_pause.config(state=tk.DISABLED, text="Pause")
        self.btn_stop.config(state=tk.DISABLED)

        async def action() -> None:
            await self._async_stop()

        asyncio.run_coroutine_threadsafe(action(), self._loop)

    async def _async_stop(self) -> None:
        """Clean shutdown coroutine executed on worker thread."""
        if self._controller is not None:
            try:
                await self._controller.stop()
            except Exception as exc:
                logger.debug("Error stopping controller: %s", exc)
            self._controller = None

        if self._engine is not None:
            try:
                self._engine.close()
            except Exception as exc:
                logger.debug("Error closing engine: %s", exc)
            self._engine = None

        if self._cdp is not None:
            try:
                await self._cdp.close()
            except Exception as exc:
                logger.debug("Error closing CDP: %s", exc)
            self._cdp = None

        self._event_queue.put(StatusEvent(BotState.STOPPED, "Autoplayer stopped"))

    def _on_strength_changed(self, event: Any = None) -> None:
        val = self.strength_var.get()
        if val in PROFILES:
            self.settings = replace(self.settings, strength=val)
            save_config(self.settings)
            if self._controller is not None:
                self._loop.call_soon_threadsafe(self._controller.set_strength, val)

    def _on_speed_changed(self, val_str: str) -> None:
        try:
            val = round(float(val_str), 1)
            self.speed_val_label.config(text=f"{val:.1f}x")
            if self._last_applied_speed != val:
                self._last_applied_speed = val
                if self._controller is not None:
                    self._loop.call_soon_threadsafe(self._controller.set_speed, val)
            self._schedule_debounced_save_speed(val)
        except ValueError:
            pass

    def _schedule_debounced_save_speed(self, speed: float) -> None:
        if self._speed_save_after_id is not None:
            self.root.after_cancel(self._speed_save_after_id)
        self._speed_save_after_id = self.root.after(500, self._save_debounced_speed, speed)

    def _save_debounced_speed(self, speed: float) -> None:
        self._speed_save_after_id = None
        self.settings = replace(self.settings, speed=speed)
        save_config(self.settings)

    def _on_input_mode_changed(self) -> None:
        mode = self.input_mode_var.get()
        if mode == "os" and not is_accessibility_trusted():
            self._update_status(
                BotState.ERROR, "macOS Accessibility permissions required for OS mode"
            )
            self.input_mode_var.set(self.settings.input_mode)
            return

        self.settings = replace(self.settings, input_mode=mode)
        save_config(self.settings)
        if self._controller is not None:
            self._loop.call_soon_threadsafe(self._controller.set_input_mode, mode)

    def _on_style_changed(self, event: Any = None) -> None:
        st = self.style_var.get()
        if st in ("mixed", "drag", "click"):
            self.settings = replace(self.settings, move_style=st)
            save_config(self.settings)
            if self._controller is not None:
                self._loop.call_soon_threadsafe(self._controller.set_move_style, st)

    def _on_smoke_exit(self) -> None:
        """Smoke test exit handler."""
        logger.info("Smoke test duration reached; shutting down cleanly")
        self._on_close()

    def _on_close(self) -> None:
        """Gracefully handle window close event."""
        if self._speed_save_after_id is not None:
            self.root.after_cancel(self._speed_save_after_id)
            self._speed_save_after_id = None
            save_config(self.settings)

        # Stop controller on worker thread
        fut = asyncio.run_coroutine_threadsafe(self._async_stop(), self._loop)
        try:
            fut.result(timeout=1.5)
        except Exception as exc:
            logger.debug("Exception waiting for async shutdown: %s", exc)

        # Stop worker thread loop
        self._loop.call_soon_threadsafe(self._loop.stop)
        self.root.destroy()


def run_app(smoke_seconds: float | None = None) -> int:
    """Entry point for the GUI control panel."""
    root = tk.Tk()
    AutoplayerApp(root, smoke_seconds=smoke_seconds)
    root.mainloop()
    return 0


if __name__ == "__main__":
    smoke: float | None = None
    if len(sys.argv) > 1 and sys.argv[1] == "--smoke":
        smoke = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0
    sys.exit(run_app(smoke_seconds=smoke))
