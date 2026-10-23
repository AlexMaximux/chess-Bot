"""Tests for human-like move selection."""

import random

import chess

from chess_autoplayer.engine.profiles import Profile, get_profile
from chess_autoplayer.engine.selector import Decision, select_move
from chess_autoplayer.engine.stockfish import Line


def test_mate_in_one_always_chosen() -> None:
    board = chess.Board("6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1")
    mating_move = chess.Move.from_uci("d1d8")
    suboptimal = chess.Move.from_uci("d1d7")

    candidates = [
        Line(move=suboptimal, score_cp=400, mate_score=None, pv=[suboptimal]),
        Line(move=mating_move, score_cp=99990, mate_score=1, pv=[mating_move]),
    ]
    # Even on beginner profile with high blunder chance and temperature
    prof = get_profile("beginner")
    rng = random.Random(123)

    decision = select_move(board, candidates, prof, rng=rng)
    assert decision.move == mating_move
    assert "mate" in decision.reason.lower()


def test_single_legal_move() -> None:
    board = chess.Board("k7/8/1K6/8/8/8/8/8 b - - 0 1")
    mv = chess.Move.from_uci("a8b8")
    candidates = [Line(move=mv, score_cp=0, mate_score=None, pv=[mv])]
    prof = get_profile("club")
    decision = select_move(board, candidates, prof)
    assert decision.move == mv
    assert "only_legal" in decision.reason


def test_temperature_zero_picks_best_over_many_draws() -> None:
    board = chess.Board()
    best_move = chess.Move.from_uci("e2e4")
    second_move = chess.Move.from_uci("d2d4")
    candidates = [
        Line(move=best_move, score_cp=30, mate_score=None, pv=[best_move]),
        Line(move=second_move, score_cp=25, mate_score=None, pv=[second_move]),
    ]
    prof = get_profile("max")  # temperature=0, max_cp_loss=0
    rng = random.Random(42)

    for _ in range(100):
        decision = select_move(board, candidates, prof, rng=rng)
        assert decision.move == best_move


def test_max_cp_loss_respected_over_1000_draws() -> None:
    board = chess.Board()
    m1 = chess.Move.from_uci("e2e4")
    m2 = chess.Move.from_uci("d2d4")
    m3 = chess.Move.from_uci("c2c4")
    c1 = Line(move=m1, score_cp=50, mate_score=None, pv=[m1])
    c2 = Line(move=m2, score_cp=10, mate_score=None, pv=[m2])  # loss = 40
    c3 = Line(move=m3, score_cp=-60, mate_score=None, pv=[m3])  # loss = 110

    # Profile with max_cp_loss=50, blunder_chance=0.0
    prof = Profile(
        name="test_no_blunder",
        limit_strength=True,
        elo=1800,
        time_limit=0.2,
        multipv=3,
        temperature=30.0,
        max_cp_loss=50,
        blunder_chance=0.0,
    )
    rng = random.Random(42)

    chosen_moves = set()
    for _ in range(1000):
        dec = select_move(board, [c1, c2, c3], prof, rng=rng)
        chosen_moves.add(dec.move)
        # c3 has loss 110 > 50, so it must NEVER be chosen
        assert dec.move != c3.move

    # Both c1 and c2 should have been chosen at least once
    assert c1.move in chosen_moves
    assert c2.move in chosen_moves


def test_blunder_chance_bounds_over_1000_draws() -> None:
    board = chess.Board()
    m1 = chess.Move.from_uci("e2e4")
    m2 = chess.Move.from_uci("d2d4")
    c1 = Line(move=m1, score_cp=100, mate_score=None, pv=[m1])
    c2 = Line(move=m2, score_cp=20, mate_score=None, pv=[m2])  # loss = 80

    # max_cp_loss = 50 (c2 normally excluded). 2 * max_cp_loss = 100 (c2 included on blunder).
    prof = Profile(
        name="test_blunder",
        limit_strength=True,
        elo=1600,
        time_limit=0.2,
        multipv=2,
        temperature=20.0,
        max_cp_loss=50,
        blunder_chance=0.10,  # 10% blunder chance
    )
    rng = random.Random(42)

    blunder_count = 0
    draws = 1000
    for _ in range(draws):
        dec = select_move(board, [c1, c2], prof, rng=rng)
        if "blunder" in dec.reason:
            blunder_count += 1

    blunder_rate = blunder_count / draws
    # Should be close to 10% (allow 6% to 15%)
    assert 0.06 <= blunder_rate <= 0.15


def test_never_allows_mate_in_one_when_avoidable() -> None:
    # 7k/8/8/8/8/8/5qPP/6K1 w - - 0 1 -> in check from f2. Only moves: Kxf2 or Kh1 (allows Qf1#).
    board = chess.Board("7k/8/8/8/8/8/5qPP/6K1 w - - 0 1")
    move_safe = chess.Move.from_uci("g1f2")  # captures queen
    move_blunder = chess.Move.from_uci("g1h1")  # allows Qf1#

    candidates = [
        Line(move=move_safe, score_cp=500, mate_score=None, pv=[move_safe]),
        Line(move=move_blunder, score_cp=-99990, mate_score=-1, pv=[move_blunder]),
    ]
    prof = get_profile("beginner")  # even on beginner, never allow mate-in-1
    rng = random.Random(999)

    for _ in range(100):
        dec = select_move(board, candidates, prof, rng=rng)
        assert dec.move == move_safe


def test_pool_all_mate_picks_worse_safe_candidate() -> None:
    # Black threatens Qe1#
    # f3g5 and f3e5 allow mate-in-1, but h2h3 is safe
    board = chess.Board("4r1k1/8/8/8/8/5N2/4q1PP/6K1 w - - 0 1")
    m1 = chess.Move.from_uci("f3g5")  # allows Qe1#
    m2 = chess.Move.from_uci("f3e5")  # allows Qe1#
    m_safe = chess.Move.from_uci("h2h3")  # safe

    # c1 and c2 are in pool (loss 0 and 20 <= max_cp_loss 50), c_safe is worse (loss 120 > 50)
    c1 = Line(move=m1, score_cp=200, mate_score=None, pv=[m1])
    c2 = Line(move=m2, score_cp=180, mate_score=None, pv=[m2])
    c_safe = Line(move=m_safe, score_cp=80, mate_score=None, pv=[m_safe])

    prof = Profile(
        name="test",
        limit_strength=True,
        elo=1500,
        time_limit=0.2,
        multipv=3,
        temperature=20.0,
        max_cp_loss=50,
        blunder_chance=0.0,
    )
    dec = select_move(board, [c1, c2, c_safe], prof, rng=random.Random(42))
    assert dec.move == m_safe
    assert "safe_candidate" in dec.reason


def test_black_to_move_eval() -> None:
    board = chess.Board("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1")
    m1 = chess.Move.from_uci("e7e5")
    m2 = chess.Move.from_uci("c7c5")
    c1 = Line(move=m1, score_cp=10, mate_score=None, pv=[m1])
    c2 = Line(move=m2, score_cp=8, mate_score=None, pv=[m2])
    prof = get_profile("club")
    dec = select_move(board, [c1, c2], prof)
    assert dec.move in (c1.move, c2.move)
    assert isinstance(dec, Decision)


def test_close_position_alt_selection_rate() -> None:
    board = chess.Board()
    m1 = chess.Move.from_uci("e2e4")
    m2 = chess.Move.from_uci("d2d4")
    # Diff is 15 cp (< 50 cp)
    c1 = Line(move=m1, score_cp=30, mate_score=None, pv=[m1])
    c2 = Line(move=m2, score_cp=15, mate_score=None, pv=[m2])

    prof = get_profile("club")
    rng = random.Random(42)

    alt_reason_count = 0
    total = 1000
    for _ in range(total):
        dec = select_move(board, [c1, c2], prof, rng=rng)
        if "close_position_alt" in dec.reason:
            alt_reason_count += 1

    # Explicit chance is uniform(0.05, 0.15) -> mean around 10%
    rate = alt_reason_count / total
    assert 0.05 <= rate <= 0.15
