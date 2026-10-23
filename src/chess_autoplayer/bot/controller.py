"""Autonomous game controller state machine driving board inspection, brain, and hands."""

import asyncio
import logging
import random
import time
from collections.abc import Callable

import chess

from chess_autoplayer.board.reader import get_reader_js
from chess_autoplayer.board.snapshot import Snapshot, parse_snapshot
from chess_autoplayer.board.state import GameState, StateError
from chess_autoplayer.bot.events import (
    BotEvent,
    BotState,
    DecisionEvent,
    ErrorEvent,
    GameOverEvent,
    MoveEvent,
    StatusEvent,
)
from chess_autoplayer.chrome.cdp import CDPError, ConnectionLost
from chess_autoplayer.chrome.page import ChessPage, is_allowed_url
from chess_autoplayer.config import Settings
from chess_autoplayer.engine.profiles import get_profile
from chess_autoplayer.engine.selector import select_move
from chess_autoplayer.engine.stockfish import Engine
from chess_autoplayer.human.timing import compute_think_time
from chess_autoplayer.input.base import MoveContext, MoveInput
from chess_autoplayer.input.cdp_input import CDPInput

logger = logging.getLogger(__name__)


class BotController:
    """Async state machine controlling autonomous chess games."""

    def __init__(
        self,
        page: ChessPage,
        engine: Engine,
        input_handler: MoveInput,
        settings: Settings,
        event_callback: Callable[[BotEvent], None] | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self.page = page
        self.engine = engine
        self.input_handler = input_handler
        self.settings = settings
        self.event_callback = event_callback
        self.rng = rng if rng is not None else random.Random()

        self.state = BotState.IDLE
        self._paused = False
        self._stop_event = asyncio.Event()
        self._loop_task: asyncio.Task[None] | None = None

        # Settings variables that can be modified at runtime
        self._strength = settings.strength
        self._speed = settings.speed
        self._move_style = settings.move_style
        self._input_mode = settings.input_mode

        # Stabilization state
        self._last_stable_fen: str | None = None
        self._stable_fen_time: float = 0.0
        self._stable_fen_count: int = 0
        self._pieces_source_start_time: float | None = None

        # Game tracking
        self._last_seen_ply: int = -1
        self._retry_count: int = 0
        self._override_style: str | None = None
        self.verify_timeout: float = 3.0
        self.pieces_fallback_wait: float = 2.0

    def _emit(self, event: BotEvent) -> None:
        """Dispatch a typed event to callback and logger."""
        if isinstance(event, StatusEvent):
            logger.info("State: %s (%s)", event.state.value, event.message)
        elif isinstance(event, DecisionEvent):
            logger.info(
                "Decision: %s (eval=%+d cp, think=%.2fs)",
                event.move_san,
                event.eval_cp,
                event.think_s,
            )
        elif isinstance(event, MoveEvent):
            who = "Bot" if event.by_bot else "Opponent"
            logger.info("Move %d: %s by %s", event.ply, event.san, who)
        elif isinstance(event, GameOverEvent):
            logger.info("Game Over: %s", event.text)
        elif isinstance(event, ErrorEvent):
            logger.error("Bot Error: %s", event.message)

        if self.event_callback is not None:
            try:
                self.event_callback(event)
            except Exception as exc:
                logger.warning("Event callback raised exception: %s", exc)

    def _transition(self, new_state: BotState, message: str) -> None:
        """Transition to a new state and emit StatusEvent."""
        if self.state != new_state:
            self.state = new_state
            self._emit(StatusEvent(state=new_state, message=message))

    def pause(self) -> None:
        """Pause playback."""
        self._paused = True
        self._transition(BotState.PAUSED, "Paused by user")

    def resume(self) -> None:
        """Resume playback."""
        self._paused = False
        self._transition(BotState.IDLE, "Resumed by user")

    def set_strength(self, strength: str) -> None:
        """Update strength profile name."""
        self._strength = strength

    def set_speed(self, speed: float) -> None:
        """Update speed multiplier."""
        self._speed = max(0.01, speed)

    def set_input_mode(self, mode: str) -> None:
        """Switch input mode ('cdp' or 'os')."""
        self._input_mode = mode
        if mode == "cdp":
            self.input_handler = CDPInput(self.page)
        elif mode == "os":
            from chess_autoplayer.input.os_input import OSInput

            self.input_handler = OSInput(self.page)

    async def start(self) -> None:
        """Start the autonomous controller loop task."""
        if self._loop_task is not None and not self._loop_task.done():
            return
        self._stop_event.clear()
        self._paused = False
        self._loop_task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        """Stop playback and wait for controller loop to exit within 1s."""
        self._stop_event.set()
        if self._loop_task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._loop_task), timeout=1.0)
            except (TimeoutError, asyncio.CancelledError):
                self._loop_task.cancel()
            self._loop_task = None

        await self.input_handler.close()
        self._transition(BotState.STOPPED, "Controller stopped")

    async def _fetch_snapshot_with_retry(self) -> Snapshot | None:
        """Read reader.js snapshot from the page with connection backoff."""
        backoffs = [1.0, 2.0, 5.0, 10.0]
        reader_code = get_reader_js()

        for attempt, delay in enumerate(backoffs):
            try:
                raw = await self.page.evaluate_json(reader_code, timeout=5.0)
                if not isinstance(raw, dict):
                    return None
                return parse_snapshot(raw)
            except (TimeoutError, CDPError, ConnectionLost) as exc:
                logger.warning(
                    "CDP read error (attempt %d/%d): %s; retrying in %.1fs",
                    attempt + 1,
                    len(backoffs),
                    exc,
                    delay,
                )
                if attempt == len(backoffs) - 1:
                    self._transition(BotState.ERROR, f"CDP connection lost after retries: {exc}")
                    self._paused = True
                    return None
                await asyncio.sleep(delay)

        return None

    async def _run_loop(self) -> None:
        """Main state machine loop polling page state every 250ms ± 50ms."""
        self._transition(BotState.IDLE, "Controller started")

        while not self._stop_event.is_set():
            if self._paused:
                await asyncio.sleep(0.2)
                continue

            # 1. URL Guard check first
            current_url = await self.page.url()
            if not is_allowed_url(current_url):
                self._transition(
                    BotState.BLOCKED_URL,
                    f"Guard active: URL {current_url!r} is not an allowed computer play path",
                )
                await asyncio.sleep(0.25 + self.rng.uniform(-0.05, 0.05))
                continue

            # 2. Fetch DOM snapshot
            snapshot = await self._fetch_snapshot_with_retry()
            if snapshot is None or not snapshot.found:
                self._transition(BotState.WAITING_FOR_GAME, "Waiting for chess board to appear")
                await asyncio.sleep(0.25 + self.rng.uniform(-0.05, 0.05))
                continue

            # 3. Game Over check
            if snapshot.game_over:
                if self.state != BotState.GAME_OVER:
                    text = snapshot.game_over_text or "Game Over"
                    self._transition(BotState.GAME_OVER, text)
                    self._emit(GameOverEvent(text=text))

                # Check if a new game has reset the ply
                if len(snapshot.moves) == 0 and not snapshot.game_over:
                    self._last_seen_ply = -1
                    self._transition(BotState.IDLE, "New game detected")
                await asyncio.sleep(0.5)
                continue

            # 4. State reconstruction
            try:
                game_state = GameState.from_snapshot(snapshot, play_as=self.settings.play_as)
            except StateError as s_err:
                logger.debug("State reconstruction incomplete: %s", s_err)
                await asyncio.sleep(0.25)
                continue

            # Record moves made by opponent
            if game_state.ply > self._last_seen_ply:
                if self._last_seen_ply >= 0 and game_state.last_move:
                    # Previous move was made
                    san = snapshot.moves[-1] if snapshot.moves else game_state.last_move.uci()
                    self._emit(
                        MoveEvent(
                            ply=game_state.ply,
                            san=san,
                            by_bot=False,
                        )
                    )
                self._last_seen_ply = game_state.ply

            # 5. Check whose turn it is
            if not game_state.is_our_turn:
                self._stable_fen_count = 0
                self._pieces_source_start_time = None
                self._transition(BotState.OPPONENT_TURN, "Waiting for opponent move")
                await asyncio.sleep(0.25 + self.rng.uniform(-0.05, 0.05))
                continue

            # 6. Stable read requirements on our turn:
            # - Dragging must be false
            # - Promotion picker not unexpectedly open
            # - Same FEN in 2 reads >= 300 ms apart
            if snapshot.dragging or (
                snapshot.promotion_open and not game_state.board.is_checkmate()
            ):
                await asyncio.sleep(0.1)
                continue

            if game_state.fen == self._last_stable_fen:
                dt = time.monotonic() - self._stable_fen_time
                if dt >= 0.300:
                    self._stable_fen_count += 1
            else:
                self._last_stable_fen = game_state.fen
                self._stable_fen_time = time.monotonic()
                self._stable_fen_count = 1
                self._pieces_source_start_time = None

            if self._stable_fen_count < 2:
                # Wait for stable second read
                await asyncio.sleep(0.300)
                continue

            # 7. Trust check for pieces-only fallback
            if game_state.source == "pieces":
                now = time.monotonic()
                if self._pieces_source_start_time is None:
                    self._pieces_source_start_time = now
                    await asyncio.sleep(0.25)
                    continue
                elif now - self._pieces_source_start_time < self.pieces_fallback_wait:
                    await asyncio.sleep(0.25)
                    continue
                else:
                    logger.warning(
                        "Moving from pieces-fallback FEN after %.1fs stabilization: %s",
                        self.pieces_fallback_wait,
                        game_state.fen,
                    )

            # 8. THINKING state: run engine in thread, calculate human think time
            self._transition(BotState.THINKING, f"Thinking on ply {game_state.ply}")
            profile = get_profile(self._strength)

            t0 = time.monotonic()
            lines = await asyncio.to_thread(self.engine.analyse, game_state.board)
            engine_time = time.monotonic() - t0

            if not lines:
                self._transition(BotState.ERROR, "Engine produced no candidate lines")
                self._paused = True
                continue

            decision = select_move(game_state.board, lines, profile=profile, rng=self.rng)
            think_time = compute_think_time(
                board=game_state.board,
                candidates=decision.candidates,
                chosen_move=decision.move,
                ply=game_state.ply,
                last_move=game_state.last_move,
                speed=self._speed,
                rng=self.rng,
            )

            move_san = game_state.board.san(decision.move)
            self._emit(
                DecisionEvent(
                    move_san=move_san,
                    candidates=decision.candidates,
                    chosen=decision.move,
                    eval_cp=decision.candidates[0].score_cp,
                    think_s=think_time,
                )
            )

            # Wait remaining think time, polling page every 250ms for position change/pause
            remaining_wait = max(0.0, think_time - engine_time)
            wait_start = time.monotonic()
            move_abandoned = False

            while (time.monotonic() - wait_start) < remaining_wait:
                if self._paused or self._stop_event.is_set():
                    move_abandoned = True
                    break

                step_sleep = min(0.25, remaining_wait - (time.monotonic() - wait_start))
                if step_sleep > 0:
                    await asyncio.sleep(step_sleep)

                # Re-check snapshot
                check_snap = await self._fetch_snapshot_with_retry()
                if check_snap is None or not check_snap.found:
                    move_abandoned = True
                    break
                try:
                    cur_state = GameState.from_snapshot(check_snap, play_as=self.settings.play_as)
                    if cur_state.fen != game_state.fen or not cur_state.is_our_turn:
                        logger.info("Position changed while thinking; abandoning move")
                        move_abandoned = True
                        break
                except StateError:
                    pass

            if move_abandoned or self._stop_event.is_set():
                continue

            # 9. MOVING state: execute move
            self._transition(BotState.MOVING, f"Playing move {move_san}")
            chosen_style = self._override_style or self._move_style
            self._override_style = None

            ctx = MoveContext(
                board_rect=snapshot.board_rect,
                flipped=snapshot.flipped_geometry,
                style=chosen_style,
                promotion_piece=(
                    chess.piece_symbol(decision.move.promotion).lower()
                    if decision.move.promotion
                    else None
                ),
                rng=self.rng,
                promotion_options=snapshot.promotion_options,
            )

            try:
                await self.input_handler.perform_move(decision.move, ctx)
            except Exception as move_exc:
                logger.warning("Move execution error: %s", move_exc)
                self._transition(BotState.ERROR, f"Input error: {move_exc}")
                self._paused = True
                continue

            # 10. VERIFYING state: verify move landed within verify_timeout seconds
            self._transition(BotState.VERIFYING, f"Verifying {move_san}")
            verified = False
            ver_start = time.monotonic()

            while (time.monotonic() - ver_start) < self.verify_timeout:
                await asyncio.sleep(0.2)
                ver_snap = await self._fetch_snapshot_with_retry()
                if ver_snap is None or not ver_snap.found:
                    continue

                # If promotion dialog is open, handle clicking the wanted piece
                if ver_snap.promotion_open and decision.move.promotion:
                    wanted = chess.piece_symbol(decision.move.promotion).lower()
                    await self.input_handler.click_promotion(wanted, ver_snap.promotion_options)
                    await asyncio.sleep(0.2)
                    continue

                try:
                    ver_state = GameState.from_snapshot(ver_snap, play_as=self.settings.play_as)
                    if ver_state.ply == game_state.ply + 1 and ver_state.last_move == decision.move:
                        verified = True
                        self._retry_count = 0
                        self._last_seen_ply = ver_state.ply
                        self._emit(MoveEvent(ply=ver_state.ply, san=move_san, by_bot=True))
                        break
                except StateError:
                    continue

            if not verified:
                # Re-read state
                final_snap = await self._fetch_snapshot_with_retry()
                if final_snap and final_snap.found:
                    try:
                        final_state = GameState.from_snapshot(
                            final_snap, play_as=self.settings.play_as
                        )
                        if final_state.is_our_turn and final_state.fen == game_state.fen:
                            if self._retry_count == 0:
                                self._retry_count += 1
                                self._override_style = "click"
                                logger.warning(
                                    "Move %s did not register; retrying once with 'click' style",
                                    move_san,
                                )
                                continue
                            else:
                                msg = f"Move {move_san} failed to register after retry"
                                self._transition(BotState.ERROR, msg)
                                self._emit(ErrorEvent(msg))
                                self._paused = True
                                continue
                    except StateError:
                        pass

            # Loop continues to next turn
            await asyncio.sleep(0.25 + self.rng.uniform(-0.05, 0.05))
