"""Human-like chess move selector using MultiPV engine candidates and softmax evaluation."""

import math
import random
from dataclasses import dataclass

import chess

from chess_autoplayer.engine.profiles import Profile
from chess_autoplayer.engine.stockfish import Line


@dataclass(frozen=True)
class Decision:
    """Record of a move selection decision for logging and analysis."""

    move: chess.Move
    candidates: list[Line]
    losses: list[int]
    chosen_index: int
    reason: str


def allows_mate_in_1(board: chess.Board, move: chess.Move) -> bool:
    """Return True if making this move allows opponent to checkmate on the immediate next ply."""
    b = board.copy()
    b.push(move)
    for opp_move in b.legal_moves:
        b.push(opp_move)
        is_mate = b.is_checkmate()
        b.pop()
        if is_mate:
            return True
    return False


def select_move(
    board: chess.Board,
    candidates: list[Line],
    profile: Profile,
    rng: random.Random | None = None,
) -> Decision:
    """Select a human-like move among MultiPV candidate lines."""
    if not candidates:
        raise ValueError("Cannot select move from empty candidates list")

    r = rng if rng is not None else random.Random()
    best_score = max(c.score_cp for c in candidates)
    losses = [best_score - c.score_cp for c in candidates]

    # 1. Fastest mate rule: if any candidate mates for us, take the fastest mate
    mating = [c for c in candidates if c.mate_score is not None and c.mate_score > 0]
    if mating:
        chosen = min(mating, key=lambda c: c.mate_score or 999)
        idx = candidates.index(chosen)
        return Decision(
            move=chosen.move,
            candidates=candidates,
            losses=losses,
            chosen_index=idx,
            reason="fastest_mate",
        )

    # 2. Only legal move
    if len(candidates) == 1 or board.legal_moves.count() == 1:
        return Decision(
            move=candidates[0].move,
            candidates=candidates,
            losses=losses,
            chosen_index=0,
            reason="only_legal_move",
        )

    # 3. Drop candidates worse than best by more than max cp loss
    pool = [c for c in candidates if (best_score - c.score_cp) <= profile.max_cp_loss]

    # 4. Blunder chance: if position not lost and not mating, allow candidates up to 2x max cp loss
    is_blunder = False
    blunder_candidates = [
        c
        for c in candidates
        if profile.max_cp_loss < (best_score - c.score_cp) <= 2 * profile.max_cp_loss
    ]
    if (
        profile.blunder_chance > 0
        and blunder_candidates
        and best_score >= -300
        and candidates[0].mate_score is None
        and r.random() < profile.blunder_chance
    ):
        is_blunder = True
        pool.extend(blunder_candidates)

    if not pool:
        pool = [candidates[0]]

    # 5. Guard against allowing mate-in-1
    # Priority order:
    # 1) Safe moves in pool
    # 2) Safe moves among all candidates (lowest loss)
    # 3) Any safe legal move not in candidates (prefer checks/captures, else first)
    # 4) Only then the unsafe pool
    safe_pool = [c for c in pool if not allows_mate_in_1(board, c.move)]
    if safe_pool:
        pool = safe_pool
    else:
        safe_candidates = [c for c in candidates if not allows_mate_in_1(board, c.move)]
        if safe_candidates:
            best_safe = min(safe_candidates, key=lambda c: best_score - c.score_cp)
            idx = candidates.index(best_safe)
            return Decision(
                move=best_safe.move,
                candidates=candidates,
                losses=losses,
                chosen_index=idx,
                reason="safe_candidate_fallback",
            )
        candidate_moves = {c.move for c in candidates}
        other_legal = [m for m in board.legal_moves if m not in candidate_moves]
        safe_legal = [m for m in other_legal if not allows_mate_in_1(board, m)]
        if safe_legal:

            def _legal_move_priority(m: chess.Move) -> tuple[int, int]:
                # Priority: 0 if check, 1 if capture, 2 other
                is_cap = board.is_capture(m)
                b_next = board.copy()
                b_next.push(m)
                is_chk = b_next.is_check()
                if is_chk:
                    return (0, 0)
                if is_cap:
                    return (1, 0)
                return (2, 0)

            safe_legal.sort(key=_legal_move_priority)
            chosen_move = safe_legal[0]
            return Decision(
                move=chosen_move,
                candidates=candidates,
                losses=losses,
                chosen_index=-1,
                reason="safe_legal_move_fallback",
            )
        # If no move is safe, fall through to unsafe pool

    # 6. Temperature selection (Softmax or best)
    prefix = "blunder" if is_blunder else "standard"
    if profile.temperature <= 0 or len(pool) == 1:
        chosen = min(pool, key=lambda c: best_score - c.score_cp)
        reason = f"{prefix}_best_score"
    else:
        # Softmax over -loss / temperature
        pool_losses = [best_score - c.score_cp for c in pool]
        weights = [math.exp(-loss / profile.temperature) for loss in pool_losses]
        chosen = r.choices(pool, weights=weights, k=1)[0]
        reason = f"{prefix}_softmax"

    idx = candidates.index(chosen)
    return Decision(
        move=chosen.move,
        candidates=candidates,
        losses=losses,
        chosen_index=idx,
        reason=reason,
    )
