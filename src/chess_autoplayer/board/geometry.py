"""Pure geometry and coordinate transformations between chess squares and screen/viewport pixels."""

import random

import chess

from chess_autoplayer.board.snapshot import Rect


def square_to_center(square: chess.Square, board_rect: Rect, flipped: bool) -> tuple[float, float]:
    """Calculate the exact center (x, y) coordinates of a chess square in viewport pixels."""
    file_idx = chess.square_file(square)  # 0..7 (a..h)
    rank_idx = chess.square_rank(square)  # 0..7 (1..8)

    if not flipped:
        col = file_idx
        row = 7 - rank_idx
    else:
        col = 7 - file_idx
        row = rank_idx

    sq_size = board_rect.width / 8.0
    x = board_rect.x + (col + 0.5) * sq_size
    y = board_rect.y + (row + 0.5) * sq_size
    return x, y


def square_to_point(
    square: chess.Square,
    board_rect: Rect,
    flipped: bool,
    rng: random.Random | None = None,
    inner_fraction: float = 0.6,
) -> tuple[float, float]:
    """Calculate a randomized point inside the inner fraction of a chess square."""
    cx, cy = square_to_center(square, board_rect, flipped)
    sq_size = board_rect.width / 8.0
    r = rng if rng is not None else random.Random()

    # Half-width of the inner bounding box
    half_inner = (sq_size * inner_fraction) / 2.0
    dx = r.uniform(-half_inner, half_inner)
    dy = r.uniform(-half_inner, half_inner)
    return cx + dx, cy + dy


def point_to_square(x: float, y: float, board_rect: Rect, flipped: bool) -> chess.Square | None:
    """Map viewport (x, y) coordinates back to a chess square, or None if outside the board."""
    if not (board_rect.x <= x < board_rect.x + board_rect.width):
        return None
    if not (board_rect.y <= y < board_rect.y + board_rect.height):
        return None

    sq_size = board_rect.width / 8.0
    col = int((x - board_rect.x) / sq_size)
    row = int((y - board_rect.y) / sq_size)

    col = max(0, min(7, col))
    row = max(0, min(7, row))

    if not flipped:
        file_idx = col
        rank_idx = 7 - row
    else:
        file_idx = 7 - col
        rank_idx = row

    return chess.square(file_idx, rank_idx)
