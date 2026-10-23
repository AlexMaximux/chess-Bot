"""Tests for human mouse path generation."""

import math
import random

import chess

from chess_autoplayer.board.geometry import square_to_center, square_to_point
from chess_autoplayer.board.snapshot import Rect
from chess_autoplayer.human.mouse import (
    compute_fitts_duration_ms,
    generate_drag_path,
    generate_hover_path,
)


def test_fitts_duration_bounds() -> None:
    rng = random.Random(42)
    for dist in (50.0, 100.0, 300.0, 600.0):
        for _ in range(100):
            d = compute_fitts_duration_ms(distance=dist, target_width=80.0, rng=rng)
            assert 180.0 <= d <= 900.0


def test_mouse_path_start_and_end() -> None:
    rng = random.Random(42)
    start = (100.0, 100.0)
    end = (500.0, 400.0)
    sq_size = 70.0

    path = generate_drag_path(start, end, square_size=sq_size, rng=rng)
    assert len(path) >= 5

    # Path starts at start
    assert abs(path[0].x - start[0]) < 1e-4
    assert abs(path[0].y - start[1]) < 1e-4

    # Path ends at end
    assert abs(path[-1].x - end[0]) < 1e-4
    assert abs(path[-1].y - end[1]) < 1e-4


def test_mouse_path_dt_and_duration_clamp() -> None:
    rng = random.Random(42)
    start = (150.0, 200.0)
    end = (450.0, 250.0)
    sq_size = 60.0

    for _ in range(100):
        path = generate_drag_path(start, end, square_size=sq_size, rng=rng)
        total_time = sum(pt.dt_ms for pt in path)
        assert 180.0 <= total_time <= 950.0
        # Time intervals 8–12 ms
        for pt in path[1:]:
            assert 7.9 <= pt.dt_ms <= 12.1

        # Monotone cumulative time
        cum_time = 0.0
        for pt in path[1:]:
            cum_time += pt.dt_ms
            assert cum_time > 0


def test_mouse_target_inside_square_inner_fraction() -> None:
    board_rect = Rect(x=100.0, y=100.0, width=800.0, height=800.0)
    sq_size = 100.0
    rng = random.Random(77)

    target_sq = chess.E4
    cx, cy = square_to_center(target_sq, board_rect, flipped=False)
    half_inner = (sq_size * 0.6) / 2.0

    for _ in range(100):
        # Choose target point inside inner 60%
        target_pt = square_to_point(
            target_sq, board_rect, flipped=False, rng=rng, inner_fraction=0.6
        )
        assert cx - half_inner <= target_pt[0] <= cx + half_inner
        assert cy - half_inner <= target_pt[1] <= cy + half_inner

        # Path ends at that target point
        path = generate_drag_path((100.0, 100.0), target_pt, square_size=sq_size, rng=rng)
        assert abs(path[-1].x - target_pt[0]) < 1e-4
        assert abs(path[-1].y - target_pt[1]) < 1e-4


def test_overshoot_path_correction_ends_on_target() -> None:
    # Force overshoot on a long move
    rng = random.Random(123)
    start = (100.0, 100.0)
    end = (600.0, 600.0)
    sq_size = 50.0

    # Test 50 draws with overshoot enabled
    for _ in range(50):
        path = generate_drag_path(start, end, square_size=sq_size, force_overshoot=True, rng=rng)
        assert abs(path[-1].x - end[0]) < 1e-4
        assert abs(path[-1].y - end[1]) < 1e-4
        # Verify that at least one intermediate point was past the target (overshot)
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        dist = math.hypot(dx, dy)
        max_dist_from_start = max(math.hypot(pt.x - start[0], pt.y - start[1]) for pt in path)
        assert max_dist_from_start > dist


def test_hover_path_generation() -> None:
    rng = random.Random(42)
    current_pos = (50.0, 50.0)
    target_pos = (200.0, 300.0)
    path = generate_hover_path(current_pos, target_pos, square_size=70.0, rng=rng)

    assert len(path) >= 3
    assert abs(path[0].x - current_pos[0]) < 1e-4
    assert abs(path[-1].x - target_pos[0]) < 1e-4
