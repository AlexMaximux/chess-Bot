"""OS-level hardware mouse input for macOS using Quartz (CGEvent)."""

import asyncio
import ctypes
import logging
import math
import random
import subprocess
from typing import Any

import chess
import Quartz  # type: ignore[import-untyped]

from chess_autoplayer.board.geometry import square_to_point
from chess_autoplayer.board.snapshot import PromotionOption, Rect, WindowInfo
from chess_autoplayer.chrome.page import ChessPage
from chess_autoplayer.human.mouse import generate_drag_path, generate_hover_path
from chess_autoplayer.input.base import MoveContext
from chess_autoplayer.input.calibration import CalibrationError, CalibrationModel, solve_calibration

logger = logging.getLogger(__name__)


class AccessibilityPermissionError(Exception):
    """Raised when macOS Accessibility permission is not granted to the running terminal app."""


class UserInterruptedError(Exception):
    """Raised when the user moves the physical mouse during autonomous playback."""


def is_accessibility_trusted() -> bool:
    """Check if the current process has macOS Accessibility permission."""
    try:
        app_services = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
        )
        app_services.AXIsProcessTrusted.restype = ctypes.c_bool
        app_services.AXIsProcessTrusted.argtypes = []
        return bool(app_services.AXIsProcessTrusted())
    except Exception as exc:
        logger.warning("Failed to check AXIsProcessTrusted: %s", exc)
        return False


def get_real_cursor_pos() -> tuple[float, float]:
    """Get the current physical screen cursor position (x, y) on macOS."""
    loc = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
    return float(loc.x), float(loc.y)


def post_cg_mouse_event(
    event_type: Any,
    x: float,
    y: float,
    button: Any = None,
) -> None:
    """Create and post a CGEvent to the macOS HID event stream."""
    if button is None:
        button = Quartz.kCGMouseButtonLeft
    point = Quartz.CGPoint(x=x, y=y)
    evt = Quartz.CGEventCreateMouseEvent(None, event_type, point, button)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, evt)


class OSInput:
    """Dispatches physical macOS mouse events via Quartz CGEvent."""

    def __init__(self, page: ChessPage) -> None:
        self.page = page
        self.calibration: CalibrationModel | None = None
        self.last_screen_pos: tuple[float, float] | None = None
        self._mouse_pressed = False
        self._listener_installed = False

    def verify_permissions(self) -> None:
        """Verify macOS Accessibility permission or raise AccessibilityPermissionError."""
        if not is_accessibility_trusted():
            raise AccessibilityPermissionError(
                "macOS Accessibility permission is required for OS mouse input.\n"
                "Please grant permission in: System Settings → Privacy & Security → Accessibility "
                "→ the terminal app you run it from."
            )

    async def bring_chrome_to_front(self) -> None:
        """Bring Google Chrome window to the front."""
        try:
            await self.page.bring_to_front()
        except Exception as exc:
            logger.debug("Page.bringToFront failed: %s", exc)

        # Activate Chrome via AppleScript
        try:
            cmd = 'tell application "Google Chrome" to activate'
            proc = await asyncio.create_subprocess_exec(
                "osascript",
                "-e",
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            await proc.wait()
        except Exception as exc:
            logger.debug("Failed to activate Chrome via AppleScript: %s", exc)

    async def ensure_calibrated(self, win: WindowInfo, board_rect: Rect) -> None:
        """Calibrate client-to-screen coordinate mapping if not yet calibrated."""
        if self.calibration is not None:
            return

        self.verify_permissions()
        await self.bring_chrome_to_front()
        await asyncio.sleep(0.1)

        if not self._listener_installed:
            install_script = (
                "window.__cap_last_mouse = null;\n"
                "window.addEventListener('mousemove', (e) => {\n"
                "  window.__cap_last_mouse = { clientX: e.clientX, clientY: e.clientY };\n"
                "}, { capture: true });\n"
                "true;"
            )
            await self.page.evaluate_json(install_script)
            self._listener_installed = True

        top_chrome = max(60.0, win.outerHeight - win.innerHeight)

        # Sample point 1 inside board
        s1_x = win.screenX + board_rect.x + 50.0
        s1_y = win.screenY + top_chrome + board_rect.y + 50.0

        # Sample point 2 inside board
        s2_x = win.screenX + board_rect.x + 200.0
        s2_y = win.screenY + top_chrome + board_rect.y + 200.0

        post_cg_mouse_event(Quartz.kCGEventMouseMoved, s1_x, s1_y)
        await asyncio.sleep(0.08)
        c1_raw = await self.page.evaluate_json("window.__cap_last_mouse;")
        if not isinstance(c1_raw, dict):
            raise CalibrationError("Could not read client coordinates for calibration point 1")
        c1 = (float(c1_raw["clientX"]), float(c1_raw["clientY"]))

        post_cg_mouse_event(Quartz.kCGEventMouseMoved, s2_x, s2_y)
        await asyncio.sleep(0.08)
        c2_raw = await self.page.evaluate_json("window.__cap_last_mouse;")
        if not isinstance(c2_raw, dict):
            raise CalibrationError("Could not read client coordinates for calibration point 2")
        c2 = (float(c2_raw["clientX"]), float(c2_raw["clientY"]))

        self.calibration = solve_calibration((s1_x, s1_y), c1, (s2_x, s2_y), c2)
        logger.info("Calibrated OS screen mapping: %s", self.calibration)

    def _check_safety(self) -> None:
        """Check if user moved physical cursor > 40px away from expected position."""
        if self.last_screen_pos is None:
            return
        real_x, real_y = get_real_cursor_pos()
        dist = math.hypot(real_x - self.last_screen_pos[0], real_y - self.last_screen_pos[1])
        if dist > 40.0:
            if self._mouse_pressed:
                post_cg_mouse_event(Quartz.kCGEventLeftMouseUp, real_x, real_y)
                self._mouse_pressed = False
            raise UserInterruptedError(
                f"user moved the mouse (drifted {dist:.1f}px > 40px threshold)"
            )

    async def perform_move(self, move: chess.Move, ctx: MoveContext) -> None:
        """Perform a human-like chess move using real OS mouse events."""
        self.verify_permissions()
        await self.bring_chrome_to_front()

        # Fallback window info for calibration if not provided
        win_info = WindowInfo(
            screenX=0.0,
            screenY=0.0,
            outerWidth=1200.0,
            outerHeight=900.0,
            innerWidth=1200.0,
            innerHeight=800.0,
        )
        await self.ensure_calibrated(win_info, ctx.board_rect)
        assert self.calibration is not None

        r = ctx.rng if ctx.rng is not None else random.Random()
        sq_size = ctx.board_rect.width / 8.0

        src_client = square_to_point(
            move.from_square,
            ctx.board_rect,
            ctx.flipped,
            rng=r,
            inner_fraction=0.6,
        )
        dst_client = square_to_point(
            move.to_square,
            ctx.board_rect,
            ctx.flipped,
            rng=r,
            inner_fraction=0.6,
        )

        src_screen = self.calibration.client_to_screen(*src_client)
        dst_screen = self.calibration.client_to_screen(*dst_client)

        cur_screen = get_real_cursor_pos()
        self.last_screen_pos = cur_screen

        # Move to source
        hover_path = generate_hover_path(
            cur_screen, src_screen, square_size=sq_size * self.calibration.scale_x, rng=r
        )
        for pt in hover_path:
            self._check_safety()
            if pt.dt_ms > 0:
                await asyncio.sleep(pt.dt_ms / 1000.0)
            post_cg_mouse_event(Quartz.kCGEventMouseMoved, pt.x, pt.y)
            self.last_screen_pos = (pt.x, pt.y)

        await asyncio.sleep(r.uniform(0.040, 0.120))
        self._check_safety()

        # Style
        style = ctx.style
        if style == "mixed":
            style = "drag" if r.random() < 0.75 else "click"

        if style == "drag":
            post_cg_mouse_event(Quartz.kCGEventLeftMouseDown, src_screen[0], src_screen[1])
            self._mouse_pressed = True
            await asyncio.sleep(r.uniform(0.030, 0.090))

            drag_path = generate_drag_path(
                src_screen, dst_screen, square_size=sq_size * self.calibration.scale_x, rng=r
            )
            for pt in drag_path:
                self._check_safety()
                if pt.dt_ms > 0:
                    await asyncio.sleep(pt.dt_ms / 1000.0)
                post_cg_mouse_event(Quartz.kCGEventLeftMouseDragged, pt.x, pt.y)
                self.last_screen_pos = (pt.x, pt.y)

            post_cg_mouse_event(Quartz.kCGEventLeftMouseUp, dst_screen[0], dst_screen[1])
            self._mouse_pressed = False
            self.last_screen_pos = dst_screen

        else:
            post_cg_mouse_event(Quartz.kCGEventLeftMouseDown, src_screen[0], src_screen[1])
            await asyncio.sleep(r.uniform(0.030, 0.070))
            post_cg_mouse_event(Quartz.kCGEventLeftMouseUp, src_screen[0], src_screen[1])

            move_path = generate_hover_path(
                src_screen, dst_screen, square_size=sq_size * self.calibration.scale_x, rng=r
            )
            for pt in move_path:
                self._check_safety()
                if pt.dt_ms > 0:
                    await asyncio.sleep(pt.dt_ms / 1000.0)
                post_cg_mouse_event(Quartz.kCGEventMouseMoved, pt.x, pt.y)
                self.last_screen_pos = (pt.x, pt.y)

            await asyncio.sleep(r.uniform(0.040, 0.120))
            self._check_safety()
            post_cg_mouse_event(Quartz.kCGEventLeftMouseDown, dst_screen[0], dst_screen[1])
            await asyncio.sleep(r.uniform(0.030, 0.070))
            post_cg_mouse_event(Quartz.kCGEventLeftMouseUp, dst_screen[0], dst_screen[1])
            self.last_screen_pos = dst_screen

        if move.promotion and ctx.promotion_options:
            wanted = chess.piece_symbol(move.promotion).lower()
            await self.click_promotion(wanted, ctx.promotion_options, rng=r)

    async def click_promotion(
        self,
        piece: str,
        options: list[PromotionOption],
        rng: random.Random | None = None,
    ) -> bool:
        """Click on the wanted piece in the promotion dialog using real OS mouse events."""
        if not options or self.calibration is None:
            return False

        r = rng if rng is not None else random.Random()
        matching = [opt for opt in options if opt.piece.lower() == piece.lower()]
        target_opt = matching[0] if matching else options[0]

        cx_client = target_opt.rect.x + target_opt.rect.width / 2.0
        cy_client = target_opt.rect.y + target_opt.rect.height / 2.0
        cx_screen, cy_screen = self.calibration.client_to_screen(cx_client, cy_client)

        cur_screen = get_real_cursor_pos()
        path = generate_hover_path(
            cur_screen,
            (cx_screen, cy_screen),
            square_size=target_opt.rect.width,
            rng=r,
        )
        for pt in path:
            self._check_safety()
            if pt.dt_ms > 0:
                await asyncio.sleep(pt.dt_ms / 1000.0)
            post_cg_mouse_event(Quartz.kCGEventMouseMoved, pt.x, pt.y)
            self.last_screen_pos = (pt.x, pt.y)

        await asyncio.sleep(r.uniform(0.040, 0.100))
        self._check_safety()
        post_cg_mouse_event(Quartz.kCGEventLeftMouseDown, cx_screen, cy_screen)
        await asyncio.sleep(r.uniform(0.030, 0.070))
        post_cg_mouse_event(Quartz.kCGEventLeftMouseUp, cx_screen, cy_screen)
        self.last_screen_pos = (cx_screen, cy_screen)
        return True

    async def close(self) -> None:
        """Release mouse button if currently held down."""
        if self._mouse_pressed:
            try:
                pos = self.last_screen_pos or get_real_cursor_pos()
                post_cg_mouse_event(Quartz.kCGEventLeftMouseUp, pos[0], pos[1])
            except Exception as exc:
                logger.debug("Error releasing OS mouse button on close: %s", exc)
            self._mouse_pressed = False
