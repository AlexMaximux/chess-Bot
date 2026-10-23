#!/usr/bin/env python3
"""Developer utility: play a UCI move on chess.com via raw CDP mouse events.

Usage:
    python scripts/dev_move.py e2e4
    python scripts/dev_move.py g8f6
"""

import asyncio
import sys

import chess

from chess_autoplayer.board.reader import get_reader_js
from chess_autoplayer.board.snapshot import parse_snapshot
from chess_autoplayer.chrome.cdp import CDPClient
from chess_autoplayer.chrome.launcher import launch_or_attach_chrome
from chess_autoplayer.chrome.page import ChessPage, find_or_create_chess_tab
from chess_autoplayer.config import load_config


def square_to_viewport_coords(
    sq_name: str,
    board_rect_x: float,
    board_rect_y: float,
    board_size: float,
    is_flipped: bool,
) -> tuple[float, float]:
    """Calculate viewport (x, y) center for a given algebraic square (e.g. 'e4')."""
    file_idx = ord(sq_name[0]) - ord("a")  # 0..7
    rank_idx = int(sq_name[1]) - 1  # 0..7

    if not is_flipped:
        col = file_idx
        row = 7 - rank_idx
    else:
        col = 7 - file_idx
        row = rank_idx

    sq_size = board_size / 8.0
    x = board_rect_x + (col + 0.5) * sq_size
    y = board_rect_y + (row + 0.5) * sq_size
    return x, y


async def play_uci_move(uci_str: str) -> None:
    """Send CDP mouse events to drag piece from source square to target square."""
    move = chess.Move.from_uci(uci_str)
    from_sq = chess.square_name(move.from_square)
    to_sq = chess.square_name(move.to_square)

    settings = load_config()
    ws_url = await launch_or_attach_chrome(settings)
    cdp = await CDPClient.connect(ws_url)

    try:
        target_id = await find_or_create_chess_tab(
            cdp, settings.start_url, mode=settings.mode
        )
        page = await ChessPage.attach(cdp, target_id)

        # Snapshot board geometry
        raw = await page.evaluate_json(get_reader_js())
        snap = parse_snapshot(raw)
        if not snap.found:
            print("Error: No chess board found on page!", file=sys.stderr)
            return

        is_flipped = snap.flipped_geometry
        x1, y1 = square_to_viewport_coords(
            from_sq, snap.board_rect.x, snap.board_rect.y, snap.board_rect.width, is_flipped
        )
        x2, y2 = square_to_viewport_coords(
            to_sq, snap.board_rect.x, snap.board_rect.y, snap.board_rect.width, is_flipped
        )

        session_id = page._session_id

        # Move to source square
        await cdp.send(
            "Input.dispatchMouseEvent",
            {"type": "mouseMoved", "x": x1, "y": y1},
            session_id=session_id,
        )
        await asyncio.sleep(0.05)

        # Mouse press
        await cdp.send(
            "Input.dispatchMouseEvent",
            {
                "type": "mousePressed",
                "x": x1,
                "y": y1,
                "button": "left",
                "buttons": 1,
                "clickCount": 1,
            },
            session_id=session_id,
        )
        await asyncio.sleep(0.05)

        # Drag across steps
        steps = 10
        for i in range(1, steps + 1):
            t = i / steps
            curr_x = x1 + (x2 - x1) * t
            curr_y = y1 + (y2 - y1) * t
            await cdp.send(
                "Input.dispatchMouseEvent",
                {"type": "mouseMoved", "x": curr_x, "y": curr_y, "buttons": 1},
                session_id=session_id,
            )
            await asyncio.sleep(0.015)

        # Mouse release
        await cdp.send(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseReleased",
                "x": x2,
                "y": y2,
                "button": "left",
                "buttons": 0,
                "clickCount": 1,
            },
            session_id=session_id,
        )

        print(f"Dispatched drag for {uci_str}: ({from_sq} -> {to_sq})")

    finally:
        await cdp.close()


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/dev_move.py <uci_move> (e.g. e2e4)", file=sys.stderr)
        sys.exit(1)
    asyncio.run(play_uci_move(sys.argv[1]))


if __name__ == "__main__":
    main()
