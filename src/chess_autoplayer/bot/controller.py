"""Autonomous game controller state machine driving board inspection, brain, and hands."""

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import replace

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
from chess_autoplayer.engine.profiles import PROFILES, get_profile
from chess_autoplayer.engine.selector import select_move
from chess_autoplayer.engine.stockfish import Engine
from chess_autoplayer.human.timing import compute_think_time
from chess_autoplayer.input.base import MoveContext, MoveInput
from chess_autoplayer.input.cdp_input import CDPInput

logger = logging.getLogger(__name__)

ReconnectFactory = Callable[[], Awaitable[tuple[ChessPage, MoveInput]]]


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
        reconnect_factory: ReconnectFactory | None = None,
    ) -> None:
        self.page = page
        self.engine = engine
        self.input_handler = input_handler
        self.settings = settings
        self.event_callback = event_callback
        self.rng = rng if rng is not None else random.Random()
        self.reconnect_factory = reconnect_factory

        self.state = BotState.IDLE
        self._paused = False
        self._stop_event = asyncio.Event()
        self._loop_task: asyncio.Task[None] | None = None

        # Settings variables that can be modified at runtime
        self._strength = settings.strength
        self._speed = settings.speed
        self._move_style = settings.move_style
        self._input_mode = settings.input_mode
        self._pending_input_mode: str | None = None
        self._pending_move_style: str | None = None
        self._pending_strength: str | None = None
        self._is_searching: bool = False

        # Stabilization state
        self._last_stable_fen: str | None = None
        self._stable_fen_time: float = 0.0
        self._stable_fen_count: int = 0
        self._pieces_source_start_time: float | None = None

        # Game tracking
        self._last_seen_ply: int = -1
        self._retry_count: int = 0
        self._override_style: str | None = None
        self._game_over_latch: bool = False
        self._game_over_final_ply: int = -1
        self.verify_timeout: float = 3.0
        self.pieces_fallback_wait: float = 2.0
        self.backoffs: list[float] = [1.0, 2.0, 5.0, 10.0]

    @property
    def is_paused(self) -> bool:
        """True if playback is currently paused (either manually or after error)."""
        return self._paused

    @property
    def strength(self) -> str:
        return self._strength

    @property
    def speed(self) -> float:
        return self._speed

    @property
    def move_style(self) -> str:
        return self._move_style

    @property
    def input_mode(self) -> str:
        return self._input_mode

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
        """Update strength profile name.

        Applied between engine searches to prevent race conditions on the UCI pipe.
        """
        if strength not in PROFILES:
            msg = f"Unknown strength profile: {strength!r}"
            logger.warning(msg)
            self._emit(ErrorEvent(msg))
            return
        self._strength = strength
        self._pending_strength = strength
        if not self._is_searching:
            try:
                self.engine.set_profile(strength)
                self._pending_strength = None
            except Exception as exc:
                logger.warning("Error setting engine profile: %s", exc)

    def set_move_style(self, style: str) -> None:
        """Schedule move style change ('mixed', 'drag', 'click') from the next move."""
        if style not in ("mixed", "drag", "click"):
            msg = f"Invalid move style: {style!r}"
            logger.warning(msg)
            self._emit(ErrorEvent(msg))
            return
        self._pending_move_style = style

    def set_speed(self, speed: float) -> None:
        """Update speed multiplier."""
        self._speed = max(0.1, min(5.0, speed))

    def set_input_mode(self, mode: str) -> None:
        """Schedule input mode change ('cdp' or 'os') from the next move."""
        if mode not in ("cdp", "os"):
            msg = f"Invalid input mode: {mode!r}"
            self._emit(ErrorEvent(msg))
            return
        if mode == "os":
            from chess_autoplayer.input.os_input import is_accessibility_trusted

            if not is_accessibility_trusted():
                msg = "macOS Accessibility permission is not granted; keeping current input mode."
                logger.warning(msg)
                self._emit(ErrorEvent(msg))
                return
        self._pending_input_mode = mode

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
        """Read reader.js snapshot from the page with connection backoff and reconnect."""
        backoffs = self.backoffs
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
                if isinstance(exc, ConnectionLost) and self.reconnect_factory is not None:
                    try:
                        logger.info("Attempting CDP reconnect...")
                        old_cdp = getattr(self.page, "cdp", None)
                        old_input = self.input_handler
                        new_page, new_input = await self.reconnect_factory()
                        self.page = new_page
                        self.input_handler = new_input
                        if old_cdp is not None and old_cdp is not getattr(new_page, "cdp", None):
                            try:
                                await old_cdp.close()
                            except Exception as cdp_err:
                                logger.debug(
                                    "Error closing old CDP client after reconnect: %s", cdp_err
                                )
                        if old_input is not None and old_input is not new_input:
                            try:
                                await old_input.close()
                            except Exception as inp_err:
                                logger.debug(
                                    "Error closing old input handler after reconnect: %s", inp_err
                                )
                        logger.info("Successfully reconnected to page and input handler")
                        try:
                            raw = await self.page.evaluate_json(reader_code, timeout=5.0)
                            if isinstance(raw, dict):
                                return parse_snapshot(raw)
                        except Exception as post_rec_err:
                            logger.warning(
                                "Read immediately after reconnect failed: %s", post_rec_err
                            )
                    except Exception as rec_exc:
                        logger.warning("Reconnect attempt failed: %s", rec_exc)

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

            # 0. Apply pending strength, move style, and input mode changes between turns
            if self._pending_strength is not None and not self._is_searching:
                strength_to_apply = self._pending_strength
                self._pending_strength = None
                try:
                    self.engine.set_profile(strength_to_apply)
                except Exception as eng_exc:
                    logger.warning("Error updating engine profile: %s", eng_exc)

            if self._pending_move_style is not None:
                self._move_style = self._pending_move_style
                self._pending_move_style = None

            if self._pending_input_mode is not None:
                new_mode = self._pending_input_mode
                self._pending_input_mode = None
                if new_mode != self._input_mode:
                    old_handler = self.input_handler
                    if new_mode == "cdp":
                        self.input_handler = CDPInput(self.page)
                    elif new_mode == "os":
                        from chess_autoplayer.input.os_input import OSInput

                        self.input_handler = OSInput(self.page)
                    self._input_mode = new_mode
                    try:
                        await old_handler.close()
                    except Exception as exc:
                        logger.debug("Error closing old input handler: %s", exc)

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

            # 3. State reconstruction
            try:
                game_state = GameState.from_snapshot(snapshot, play_as=self.settings.play_as)
            except StateError as s_err:
                logger.debug("State reconstruction incomplete: %s", s_err)
                await asyncio.sleep(0.25)
                continue

            # 4. Game Over latching and detection
            is_game_finished = snapshot.game_over or game_state.board.is_game_over()
            if is_game_finished and not self._game_over_latch:
                self._game_over_latch = True
                self._game_over_final_ply = game_state.ply
                text = snapshot.game_over_text or ""
                if not text:
                    if game_state.board.is_checkmate():
                        winner = "Black" if game_state.board.turn == chess.WHITE else "White"
                        text = f"Checkmate - {winner} wins"
                    elif game_state.board.is_stalemate():
                        text = "Draw by stalemate"
                    elif game_state.board.is_insufficient_material():
                        text = "Draw by insufficient material"
                    else:
                        text = "Game Over"
                self._transition(BotState.GAME_OVER, text)
                self._emit(GameOverEvent(text=text))

            if self._game_over_latch:
                # Check for new game:
                # - move list empty or shorter than at game end
                # - ply lower than final ply
                # - standard starting position
                moves_reset = (
                    len(snapshot.moves) < self._game_over_final_ply
                    if self._game_over_final_ply >= 0
                    else False
                )
                ply_reset = (
                    game_state.ply < self._game_over_final_ply
                    if self._game_over_final_ply >= 0
                    else False
                )
                start_fen = game_state.board.fen().startswith(chess.STARTING_BOARD_FEN)

                if (
                    len(snapshot.moves) == 0
                    or moves_reset
                    or ply_reset
                    or (start_fen and not is_game_finished)
                ):
                    logger.info("New game detected; resetting per-game state")
                    self._game_over_latch = False
                    self._game_over_final_ply = -1
                    self._last_seen_ply = -1
                    self._retry_count = 0
                    self._override_style = None
                    self._stable_fen_count = 0
                    self._last_stable_fen = None
                    self._stable_fen_time = 0.0
                    self._pieces_source_start_time = None
                    self._transition(BotState.IDLE, "New game detected")
                else:
                    if self.state != BotState.GAME_OVER:
                        self._transition(BotState.GAME_OVER, "Game finished (waiting for new game)")
                    await asyncio.sleep(0.5)
                    continue

            # Record moves made by opponent
            if game_state.ply > self._last_seen_ply:
                if self._last_seen_ply >= 0 and game_state.last_move:
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
                await asyncio.sleep(0.300)
                continue

            if self._stable_fen_count < 2:
                await asyncio.sleep(0.1)
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
            if self._pending_strength is not None:
                strength_to_apply = self._pending_strength
                self._pending_strength = None
                try:
                    self.engine.set_profile(strength_to_apply)
                except Exception as eng_exc:
                    logger.warning("Error updating engine profile before search: %s", eng_exc)

            self._transition(BotState.THINKING, f"Thinking on ply {game_state.ply}")
            profile = get_profile(self._strength)

            t0 = time.monotonic()
            self._is_searching = True
            try:
                lines = await asyncio.to_thread(self.engine.analyse, game_state.board)
            finally:
                self._is_searching = False
            engine_time = time.monotonic() - t0

            # Apply pending strength profile if one was requested during search
            if self._pending_strength is not None:
                strength_to_apply = self._pending_strength
                self._pending_strength = None
                try:
                    self.engine.set_profile(strength_to_apply)
                except Exception as eng_exc:
                    logger.warning("Error updating engine profile after search: %s", eng_exc)

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

            # Wait remaining think time, polling page and checking URL guard every 250ms
            remaining_wait = max(0.0, think_time - engine_time)
            wait_start = time.monotonic()
            move_abandoned = False

            while (time.monotonic() - wait_start) < remaining_wait:
                if self._paused or self._stop_event.is_set():
                    move_abandoned = True
                    break

                # Re-check URL guard during thinking wait
                check_url = await self.page.url()
                if not is_allowed_url(check_url):
                    self._transition(
                        BotState.BLOCKED_URL,
                        f"Guard active: URL {check_url!r} is not an allowed computer play path",
                    )
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

            # 9. Pre-move URL guard check immediately before move execution
            pre_move_url = await self.page.url()
            if not is_allowed_url(pre_move_url):
                self._transition(
                    BotState.BLOCKED_URL,
                    f"Guard active: URL {pre_move_url!r} is not an allowed computer play path",
                )
                continue

            # 10. MOVING state: execute move
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
                try:
                    await self.input_handler.close()
                except Exception as rel_exc:
                    logger.debug("Error releasing input on error: %s", rel_exc)
                self._transition(BotState.ERROR, f"Input error: {move_exc}")
                self._paused = True
                continue

            # 11. VERIFYING state: verify move landed within verify_timeout seconds
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
                    clean_move_san = move_san.rstrip("+#")
                    if ver_state.ply >= game_state.ply + 1:
                        matched = False
                        landed_desc: str = ""

                        # 1. Check reconstructed move stack at index game_state.ply
                        if len(ver_state.board.move_stack) > game_state.ply:
                            stack_move = ver_state.board.move_stack[game_state.ply]
                            if stack_move == decision.move:
                                matched = True
                            else:
                                landed_desc = stack_move.uci()

                        # 2. Check moves list SAN at index game_state.ply
                        if not matched and len(ver_snap.moves) > game_state.ply:
                            san_move = ver_snap.moves[game_state.ply]
                            if san_move.rstrip("+#") == clean_move_san:
                                matched = True
                            elif not landed_desc:
                                landed_desc = san_move

                        # 3. Check last_move if exact ply+1
                        if (
                            not matched
                            and ver_state.ply == game_state.ply + 1
                            and ver_state.last_move is not None
                        ):
                            if ver_state.last_move == decision.move:
                                matched = True
                            elif not landed_desc:
                                landed_desc = ver_state.last_move.uci()

                        if matched:
                            verified = True
                            self._retry_count = 0
                            self._last_seen_ply = ver_state.ply
                            self._emit(MoveEvent(ply=game_state.ply + 1, san=move_san, by_bot=True))
                            break
                        else:
                            # A different move landed on the board!
                            landed = landed_desc or "unknown"
                            err_msg = f"unexpected move landed: {landed} (expected {move_san})"
                            logger.error(err_msg)
                            self._transition(BotState.ERROR, err_msg)
                            self._emit(ErrorEvent(err_msg))
                            self._paused = True
                            break
                except StateError:
                    continue

            if self._paused or self._stop_event.is_set():
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
                            # Re-check URL guard before immediate retry
                            retry_url = await self.page.url()
                            if not is_allowed_url(retry_url):
                                self._transition(
                                    BotState.BLOCKED_URL,
                                    f"Guard active: URL {retry_url!r} not allowed",
                                )
                                continue

                            # Immediate retry with 'click' style right away
                            logger.warning(
                                "Move %s did not register; retrying immediately with 'click' style",
                                move_san,
                            )
                            retry_ctx = replace(ctx, style="click")
                            try:
                                await self.input_handler.perform_move(decision.move, retry_ctx)
                            except Exception as retry_exc:
                                logger.warning("Retry input error: %s", retry_exc)
                                try:
                                    await self.input_handler.close()
                                except Exception as exc:
                                    logger.debug(
                                        "Error closing input handler during retry: %s", exc
                                    )
                                self._transition(
                                    BotState.ERROR, f"Input error on retry: {retry_exc}"
                                )
                                self._paused = True
                                continue

                            # Verify retry
                            retry_ver_start = time.monotonic()
                            retry_verified = False
                            clean_move_san = move_san.rstrip("+#")
                            while (time.monotonic() - retry_ver_start) < self.verify_timeout:
                                await asyncio.sleep(0.2)
                                r_snap = await self._fetch_snapshot_with_retry()
                                if r_snap is None or not r_snap.found:
                                    continue
                                try:
                                    r_state = GameState.from_snapshot(
                                        r_snap, play_as=self.settings.play_as
                                    )
                                    if r_state.ply >= game_state.ply + 1:
                                        r_matched = False
                                        r_landed: str = ""
                                        if len(r_state.board.move_stack) > game_state.ply:
                                            r_sm = r_state.board.move_stack[game_state.ply]
                                            if r_sm == decision.move:
                                                r_matched = True
                                            else:
                                                r_landed = r_sm.uci()

                                        if not r_matched and len(r_snap.moves) > game_state.ply:
                                            r_m = r_snap.moves[game_state.ply]
                                            if r_m.rstrip("+#") == clean_move_san:
                                                r_matched = True
                                            elif not r_landed:
                                                r_landed = r_m

                                        if (
                                            not r_matched
                                            and r_state.ply == game_state.ply + 1
                                            and r_state.last_move is not None
                                        ):
                                            if r_state.last_move == decision.move:
                                                r_matched = True
                                            elif not r_landed:
                                                r_landed = r_state.last_move.uci()

                                        if r_matched:
                                            retry_verified = True
                                            self._last_seen_ply = r_state.ply
                                            self._emit(
                                                MoveEvent(
                                                    ply=game_state.ply + 1,
                                                    san=move_san,
                                                    by_bot=True,
                                                )
                                            )
                                            break
                                        else:
                                            landed = r_landed or "unknown"
                                            err_msg = (
                                                f"unexpected move landed: {landed} "
                                                f"(expected {move_san})"
                                            )
                                            logger.error(err_msg)
                                            self._transition(BotState.ERROR, err_msg)
                                            self._emit(ErrorEvent(err_msg))
                                            self._paused = True
                                            break
                                except StateError:
                                    continue

                            if self._paused or self._stop_event.is_set():
                                continue

                            if not retry_verified:
                                msg = f"Move {move_san} failed to register after retry"
                                self._transition(BotState.ERROR, msg)
                                self._emit(ErrorEvent(msg))
                                self._paused = True
                                continue
                    except StateError:
                        pass

            # Loop continues to next turn
            await asyncio.sleep(0.25 + self.rng.uniform(-0.05, 0.05))
