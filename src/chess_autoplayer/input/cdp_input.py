"""CDP-based mouse input implementation using Chrome DevTools Protocol."""

import asyncio
import logging
import random
import time
from typing import Any, Protocol

import chess

from chess_autoplayer.board.geometry import square_to_point
from chess_autoplayer.board.snapshot import PromotionOption, Rect
from chess_autoplayer.human.mouse import generate_drag_path, generate_hover_path
from chess_autoplayer.input.base import MoveContext

logger = logging.getLogger(__name__)


class CDPCommander(Protocol):
    """Protocol for sending raw CDP commands."""

    async def send_command(
        self, method: str, params: dict[str, Any] | None = None, timeout: float = 10.0
    ) -> dict[str, Any]: ...


class CDPInput:
    """Dispatches human-like mouse events via CDP Input.dispatchMouseEvent."""

    def __init__(self, commander: CDPCommander) -> None:
        self.commander = commander
        self.last_pos: tuple[float, float] | None = None
        self._mouse_pressed = False

    async def _dispatch(
        self,
        event_type: str,
        x: float,
        y: float,
        button: str = "none",
        buttons: int = 0,
        click_count: int = 0,
    ) -> None:
        """Send a single mouse event to Chrome."""
        params: dict[str, Any] = {
            "type": event_type,
            "x": round(x, 1),
            "y": round(y, 1),
            "button": button,
            "buttons": buttons,
            "clickCount": click_count,
        }
        await self.commander.send_command("Input.dispatchMouseEvent", params)

    async def perform_move(self, move: chess.Move, ctx: MoveContext) -> None:
        """Perform a human-like chess move using CDP mouse events."""
        r = ctx.rng if ctx.rng is not None else random.Random()
        sq_size = ctx.board_rect.width / 8.0

        src_pt = square_to_point(
            move.from_square,
            ctx.board_rect,
            ctx.flipped,
            rng=r,
            inner_fraction=0.6,
        )
        dst_pt = square_to_point(
            move.to_square,
            ctx.board_rect,
            ctx.flipped,
            rng=r,
            inner_fraction=0.6,
        )

        # Style determination
        style = ctx.style
        if style == "mixed":
            style = "drag" if r.random() < 0.75 else "click"

        # Initialize starting cursor position near the board edge if unset
        if self.last_pos is None:
            init_x = ctx.board_rect.x - r.uniform(10.0, 30.0)
            init_y = ctx.board_rect.y + r.uniform(20.0, ctx.board_rect.height - 20.0)
            self.last_pos = (init_x, init_y)

        # 1. Hover move to source square
        hover_path = generate_hover_path(self.last_pos, src_pt, square_size=sq_size, rng=r)
        t_hov_start = time.monotonic()
        cum_hov_ms = 0.0
        for pt in hover_path:
            cum_hov_ms += pt.dt_ms
            elapsed = time.monotonic() - t_hov_start
            sleep_s = (cum_hov_ms / 1000.0) - elapsed
            if sleep_s > 0.001:
                await asyncio.sleep(sleep_s)
            await self._dispatch("mouseMoved", pt.x, pt.y, button="none", buttons=0)
            self.last_pos = (pt.x, pt.y)
        self.last_pos = src_pt

        # Hover delay before press: 40-120 ms
        await asyncio.sleep(r.uniform(0.040, 0.120))

        if style == "drag":
            try:
                # Press left button on source
                await self._dispatch(
                    "mousePressed", src_pt[0], src_pt[1], button="left", buttons=1, click_count=1
                )
                self._mouse_pressed = True

                # Hold delay before drag starts: 30-90 ms
                await asyncio.sleep(r.uniform(0.030, 0.090))

                # Drag path to destination
                drag_path = generate_drag_path(src_pt, dst_pt, square_size=sq_size, rng=r)
                t_drag_start = time.monotonic()
                cum_drag_ms = 0.0
                for pt in drag_path:
                    cum_drag_ms += pt.dt_ms
                    elapsed = time.monotonic() - t_drag_start
                    sleep_s = (cum_drag_ms / 1000.0) - elapsed
                    if sleep_s > 0.001:
                        await asyncio.sleep(sleep_s)
                    await self._dispatch("mouseMoved", pt.x, pt.y, button="left", buttons=1)
                    self.last_pos = (pt.x, pt.y)

                # Release left button on destination
                await self._dispatch(
                    "mouseReleased", dst_pt[0], dst_pt[1], button="left", buttons=0, click_count=1
                )
                self._mouse_pressed = False
                self.last_pos = dst_pt
            finally:
                if self._mouse_pressed:
                    try:
                        pos = self.last_pos or dst_pt
                        await self._dispatch(
                            "mouseReleased", pos[0], pos[1], button="left", buttons=0, click_count=1
                        )
                    except Exception as rel_exc:
                        logger.debug("Failed to release mouse button in finally: %s", rel_exc)
                    finally:
                        self._mouse_pressed = False

        else:
            # Click style: click on source, move to dest, click on dest
            try:
                await self._dispatch(
                    "mousePressed", src_pt[0], src_pt[1], button="left", buttons=1, click_count=1
                )
                self._mouse_pressed = True
                await asyncio.sleep(r.uniform(0.030, 0.070))
                await self._dispatch(
                    "mouseReleased", src_pt[0], src_pt[1], button="left", buttons=0, click_count=1
                )
                self._mouse_pressed = False

                # Move path to target
                move_path = generate_hover_path(src_pt, dst_pt, square_size=sq_size, rng=r)
                t_move_start = time.monotonic()
                cum_move_ms = 0.0
                for pt in move_path:
                    cum_move_ms += pt.dt_ms
                    elapsed = time.monotonic() - t_move_start
                    sleep_s = (cum_move_ms / 1000.0) - elapsed
                    if sleep_s > 0.001:
                        await asyncio.sleep(sleep_s)
                    await self._dispatch("mouseMoved", pt.x, pt.y, button="none", buttons=0)
                    self.last_pos = (pt.x, pt.y)
                self.last_pos = dst_pt

                # Hover delay on target
                await asyncio.sleep(r.uniform(0.040, 0.120))

                await self._dispatch(
                    "mousePressed", dst_pt[0], dst_pt[1], button="left", buttons=1, click_count=1
                )
                self._mouse_pressed = True
                await asyncio.sleep(r.uniform(0.030, 0.070))
                await self._dispatch(
                    "mouseReleased", dst_pt[0], dst_pt[1], button="left", buttons=0, click_count=1
                )
                self._mouse_pressed = False
            finally:
                if self._mouse_pressed:
                    try:
                        pos = self.last_pos or dst_pt
                        await self._dispatch(
                            "mouseReleased", pos[0], pos[1], button="left", buttons=0, click_count=1
                        )
                    except Exception as rel_exc:
                        logger.debug("Failed to release mouse button in click finally: %s", rel_exc)
                    finally:
                        self._mouse_pressed = False

        # Handle promotion piece selection if picker options are already known
        if move.promotion and ctx.promotion_options:
            wanted = chess.piece_symbol(move.promotion).lower()
            await self.click_promotion(wanted, ctx.promotion_options)

    async def click_promotion(
        self,
        piece: str,
        options: list[PromotionOption],
        rng: random.Random | None = None,
    ) -> bool:
        """Click on the wanted piece in the promotion dialog."""
        if not options:
            return False

        r = rng if rng is not None else random.Random()
        matching = [opt for opt in options if opt.piece.lower() == piece.lower()]
        target_opt = matching[0] if matching else options[0]

        cx = target_opt.rect.x + target_opt.rect.width / 2.0
        cy = target_opt.rect.y + target_opt.rect.height / 2.0

        cur_pos = self.last_pos if self.last_pos is not None else (cx, cy)
        path = generate_hover_path(cur_pos, (cx, cy), square_size=target_opt.rect.width, rng=r)
        for pt in path:
            if pt.dt_ms > 0:
                await asyncio.sleep(pt.dt_ms / 1000.0)
            await self._dispatch("mouseMoved", pt.x, pt.y, button="none", buttons=0)
        self.last_pos = (cx, cy)

        await asyncio.sleep(r.uniform(0.040, 0.100))
        await self._dispatch("mousePressed", cx, cy, button="left", buttons=1, click_count=1)
        await asyncio.sleep(r.uniform(0.030, 0.070))
        await self._dispatch("mouseReleased", cx, cy, button="left", buttons=0, click_count=1)
        return True

    async def click_rect(
        self,
        rect: Rect,
        rng: random.Random | None = None,
    ) -> bool:
        """Click on the center of the specified rectangle with human hover and click."""
        if rect.width <= 0 or rect.height <= 0:
            return False

        r = rng if rng is not None else random.Random()
        cx = rect.x + rect.width / 2.0
        cy = rect.y + rect.height / 2.0

        cur_pos = self.last_pos if self.last_pos is not None else (cx, cy)
        path = generate_hover_path(
            cur_pos, (cx, cy), square_size=min(rect.width, rect.height), rng=r
        )
        for pt in path:
            if pt.dt_ms > 0:
                await asyncio.sleep(pt.dt_ms / 1000.0)
            await self._dispatch("mouseMoved", pt.x, pt.y, button="none", buttons=0)
        self.last_pos = (cx, cy)

        await asyncio.sleep(r.uniform(0.040, 0.100))
        await self._dispatch("mousePressed", cx, cy, button="left", buttons=1, click_count=1)
        await asyncio.sleep(r.uniform(0.030, 0.070))
        await self._dispatch("mouseReleased", cx, cy, button="left", buttons=0, click_count=1)
        return True

    async def close(self) -> None:
        """Ensure mouse button is released on close."""
        if self._mouse_pressed and self.last_pos is not None:
            try:
                await self._dispatch(
                    "mouseReleased",
                    self.last_pos[0],
                    self.last_pos[1],
                    button="left",
                    buttons=0,
                    click_count=1,
                )
            except Exception as exc:
                logger.debug("Error releasing mouse button on close: %s", exc)
            self._mouse_pressed = False
