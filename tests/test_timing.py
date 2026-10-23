"""Tests for human think-time modeling."""

import random

import chess

from chess_autoplayer.engine.stockfish import Line
from chess_autoplayer.human.timing import compute_think_time, is_obvious_recapture


def make_dummy_candidates(moves: list[str]) -> list[Line]:
    res: list[Line] = []
    for i, m in enumerate(moves):
        mv = chess.Move.from_uci(m)
        res.append(Line(move=mv, score_cp=100 - i * 10, mate_score=None, pv=[mv]))
    return res


def test_book_phase_bounds() -> None:
    board = chess.Board()  # ply = 0 (< 10)
    candidates = make_dummy_candidates(["e2e4", "d2d4", "c2c4"])
    chosen = candidates[0].move  # top-1
    rng = random.Random(42)

    for _ in range(1000):
        t = compute_think_time(board, candidates, chosen, rng=rng)
        assert 0.6 <= t <= 2.0


def test_single_legal_move_bounds() -> None:
    board = chess.Board("k7/8/1K6/8/8/8/8/8 b - - 0 1")
    candidates = make_dummy_candidates(["a8b8"])
    chosen = candidates[0].move
    rng = random.Random(42)

    for _ in range(1000):
        t = compute_think_time(board, candidates, chosen, rng=rng)
        assert 0.4 <= t <= 1.2


def test_obvious_recapture_bounds() -> None:
    # 1. e4 d5 2. exd5 Qxd5 3. Nc3
    board = chess.Board()
    board.push_san("e4")
    board.push_san("d5")
    # White captures on d5
    board.push_san("exd5")
    # Black recaptures on d5 with queen
    mv_d5 = chess.Move.from_uci("d8d5")
    mv_f6 = chess.Move.from_uci("g8f6")
    candidates = [
        Line(move=mv_d5, score_cp=0, mate_score=None, pv=[mv_d5]),
        Line(move=mv_f6, score_cp=-200, mate_score=None, pv=[mv_f6]),
    ]
    # Spread is 200 >= 150, captures on d5 (square of last capture)
    chosen = chess.Move.from_uci("d8d5")
    rng = random.Random(42)

    for _ in range(1000):
        t = compute_think_time(board, candidates, chosen, rng=rng)
        assert 0.4 <= t <= 1.2


def test_complexity_phase_and_hard_cap() -> None:
    # Ply >= 10
    board = chess.Board()
    for m in ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Ba4", "Nf6", "O-O", "Be7"]:
        board.push_san(m)
    assert len(board.move_stack) == 10

    candidates = make_dummy_candidates(["f1e1", "d2d3", "c2c3"])
    chosen = candidates[0].move
    rng = random.Random(42)

    times = []
    for _ in range(1000):
        t = compute_think_time(board, candidates, chosen, rng=rng)
        assert 0.5 <= t <= 25.0
        times.append(t)

    # Typical mean should be between 2 and 10 seconds
    avg = sum(times) / len(times)
    assert 2.0 <= avg <= 10.0


def test_clock_aware_caps() -> None:
    board = chess.Board()
    for m in ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Ba4", "Nf6", "O-O", "Be7"]:
        board.push_san(m)

    candidates = make_dummy_candidates(["f1e1", "d2d3"])
    chosen = candidates[0].move
    rng = random.Random(42)

    # When 100 seconds left: max 5% = 5.0 s
    for _ in range(100):
        t = compute_think_time(board, candidates, chosen, clock_seconds=100.0, rng=rng)
        assert t <= 5.0

    # Under 20s left: cap at 1.5 s
    for _ in range(100):
        t = compute_think_time(board, candidates, chosen, clock_seconds=15.0, rng=rng)
        assert t <= 1.5

    # Low speed (0.5) must never violate clock cap of 1.5 s when clock_seconds=10
    for _ in range(100):
        t = compute_think_time(board, candidates, chosen, clock_seconds=10.0, speed=0.5, rng=rng)
        assert t <= 1.5


def test_recapture_without_move_stack_returns_false() -> None:
    # Board instantiated directly from FEN has an empty move_stack
    board = chess.Board("rnbqkbnr/ppp1pppp/8/3P4/8/8/PPPP1PPP/RNBQKBNR b KQkq - 0 2")
    chosen = chess.Move.from_uci("d8d5")  # queen takes pawn on d5
    candidates = [
        Line(move=chosen, score_cp=0, mate_score=None, pv=[chosen]),
        Line(move=chess.Move.from_uci("g8f6"), score_cp=-200, mate_score=None, pv=[]),
    ]
    # Without move stack, recapture check cannot know prior board state
    assert not is_obvious_recapture(board, candidates, chosen)


def test_speed_multiplier() -> None:
    board = chess.Board()
    candidates = make_dummy_candidates(["e2e4", "d2d4"])
    chosen = candidates[0].move

    t_normal = compute_think_time(board, candidates, chosen, speed=1.0, rng=random.Random(10))
    t_fast = compute_think_time(board, candidates, chosen, speed=2.0, rng=random.Random(10))
    assert abs(t_normal / 2.0 - t_fast) < 1e-4


def test_hard_floor_and_panic_mode() -> None:
    board = chess.Board()
    candidates = make_dummy_candidates(["e2e4", "d2d4"])
    chosen = candidates[0].move

    # High speed (e.g. 100.0) must still strictly respect the 0.30s default hard floor
    for _ in range(50):
        t = compute_think_time(board, candidates, chosen, speed=100.0)
        assert t >= 0.30

    # Panic mode: clock < 10s and increment == 0 -> floor opens down to 0.12s
    panic_times = []
    for _ in range(100):
        t = compute_think_time(
            board,
            candidates,
            chosen,
            clock_seconds=2.0,
            increment_seconds=0.0,
            speed=50.0,
        )
        assert t >= 0.12
        panic_times.append(t)
    assert any(t < 0.30 for t in panic_times)

    # When increment > 0 (even with 2s on clock), non-panic floor 0.30s is enforced
    for _ in range(50):
        t = compute_think_time(
            board,
            candidates,
            chosen,
            clock_seconds=2.0,
            increment_seconds=1.0,
            speed=50.0,
        )
        assert t >= 0.30


def test_panic_mode_preserves_human_jitter() -> None:
    board = chess.Board()
    candidates = make_dummy_candidates(["e2e4", "d2d4"])
    chosen = candidates[0].move
    rng = random.Random(42)

    # In panic mode (e.g. clock 5s, no increment, speed 1.0)
    times = [
        compute_think_time(
            board,
            candidates,
            chosen,
            clock_seconds=5.0,
            increment_seconds=0.0,
            speed=1.0,
            rng=rng,
        )
        for _ in range(50)
    ]
    # All must obey panic floor
    for t in times:
        assert t >= 0.12
        assert t <= 1.5
    # Must preserve human jitter (not all identical values)
    assert len({round(t, 4) for t in times}) > 10


def test_increment_increases_budget() -> None:
    board = chess.Board()
    candidates = make_dummy_candidates(["e2e4", "d2d4"])
    chosen = candidates[0].move
    rng1 = random.Random(123)
    rng2 = random.Random(123)

    # 10s clock with 0 increment vs 10s clock with 3s increment
    t_no_inc = [
        compute_think_time(
            board, candidates, chosen, clock_seconds=10.0, increment_seconds=0.0, rng=rng1
        )
        for _ in range(50)
    ]
    t_with_inc = [
        compute_think_time(
            board, candidates, chosen, clock_seconds=10.0, increment_seconds=3.0, rng=rng2
        )
        for _ in range(50)
    ]
    # Average think time with 3s increment should be noticeably higher
    assert sum(t_with_inc) / len(t_with_inc) > sum(t_no_inc) / len(t_no_inc)
