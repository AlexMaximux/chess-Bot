"""Tests for chess_autoplayer.board.geometry."""

import random

import chess
import pytest

from chess_autoplayer.board.geometry import point_to_square, square_to_center, square_to_point
from chess_autoplayer.board.snapshot import Rect


@pytest.fixture
def board_rect() -> Rect:
    return Rect(x=100.0, y=50.0, width=800.0, height=800.0)


def test_square_roundtrip_both_orientations(board_rect: Rect) -> None:
    for flipped in (False, True):
        for sq in chess.SQUARES:
            cx, cy = square_to_center(sq, board_rect, flipped)
            recovered = point_to_square(cx, cy, board_rect, flipped)
            name = chess.square_name(sq)
            assert recovered == sq, f"Failed roundtrip for {name} with flipped={flipped}"


def test_square_to_point_inner_region(board_rect: Rect) -> None:
    rng = random.Random(42)
    sq_size = board_rect.width / 8.0  # 100 px
    for sq in chess.SQUARES:
        cx, cy = square_to_center(sq, board_rect, False)
        for _ in range(10):
            px, py = square_to_point(sq, board_rect, False, rng=rng, inner_fraction=0.6)
            # Must be within 30% of sq_size from center in both axes
            assert abs(px - cx) <= 0.3 * sq_size + 1e-6
            assert abs(py - cy) <= 0.3 * sq_size + 1e-6


def test_point_outside_board_returns_none(board_rect: Rect) -> None:
    assert point_to_square(50.0, 50.0, board_rect, False) is None
    assert point_to_square(950.0, 50.0, board_rect, False) is None
    assert point_to_square(200.0, 950.0, board_rect, False) is None
