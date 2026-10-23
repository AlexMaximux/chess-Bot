"""Human think-time model factoring in book phase, recaptures, complexity, clock, and speed."""

import math
import random

import chess

from chess_autoplayer.engine.stockfish import Line


def is_obvious_recapture(
    board: chess.Board,
    candidates: list[Line],
    chosen_move: chess.Move,
    last_move: chess.Move | None = None,
) -> bool:
    """Return True if chosen move is an obvious recapture of the opponent's prior capture."""
    effective_last = last_move
    if effective_last is None:
        if not board.move_stack:
            return False
        effective_last = board.peek()

    # Check if last move was a capture
    # In python-chess, we can verify by popping if move_stack has moves
    if board.move_stack:
        b_prev = board.copy()
        b_prev.pop()
        was_capture = b_prev.is_capture(effective_last)
    else:
        # If board came from FEN without move_stack, check if chosen move is capture on same square
        was_capture = board.is_capture(chosen_move)

    if not was_capture:
        return False

    # Chosen move must capture on the same square
    if chosen_move.to_square != effective_last.to_square:
        return False

    # Must be ≥ 150 cp better than second candidate (if at least 2 candidates exist)
    if len(candidates) >= 2:
        spread = candidates[0].score_cp - candidates[1].score_cp
        if spread < 150:
            return False

    return True


def compute_think_time(
    board: chess.Board,
    candidates: list[Line],
    chosen_move: chess.Move,
    ply: int | None = None,
    last_move: chess.Move | None = None,
    clock_seconds: float | None = None,
    speed: float = 1.0,
    rng: random.Random | None = None,
) -> float:
    """Calculate realistic human think time in seconds for the chosen move."""
    r = rng if rng is not None else random.Random()
    if ply is not None:
        effective_ply = ply
    elif board.move_stack:
        effective_ply = len(board.move_stack)
    else:
        effective_ply = board.ply()

    # 1. Single legal move or obvious recapture: 0.4–1.2 s
    if (
        board.legal_moves.count() == 1
        or len(candidates) == 1
        or is_obvious_recapture(board, candidates, chosen_move, last_move=last_move)
    ):
        duration = r.uniform(0.4, 1.2)

    # 2. Book phase: ply < 10 and move is among top-2 candidates
    elif effective_ply < 10 and any(c.move == chosen_move for c in candidates[:2]):
        duration = r.uniform(0.6, 2.0)

    # 3. Base by complexity
    else:
        legal_count = board.legal_moves.count()
        piece_count = len(board.piece_map())

        if len(candidates) >= 2:
            spread = abs(candidates[0].score_cp - candidates[1].score_cp)
        else:
            spread = 100

        base = 2.5 + (legal_count / 35.0) * 1.5 + (piece_count / 32.0) * 1.0
        if spread < 50:
            base += 1.5
        if board.is_check():
            base += 1.0

        noise = math.exp(r.gauss(0, 0.35))
        duration = base * noise
        # Typical 2–10 s, hard cap 25 s
        duration = min(25.0, max(0.5, duration))

    # 4. Clock-aware constraints
    if clock_seconds is not None:
        duration = min(duration, max(0.2, clock_seconds * 0.05))
        if clock_seconds < 20.0:
            duration = min(duration, 1.5)

    # 5. Speed multiplier
    effective_speed = max(0.01, speed)
    duration = duration / effective_speed

    return duration
