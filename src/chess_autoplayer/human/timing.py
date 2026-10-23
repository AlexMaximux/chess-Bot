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

    # Without a move stack, the prior board state cannot be known reliably
    if not board.move_stack:
        return False

    b_prev = board.copy()
    b_prev.pop()
    was_capture = b_prev.is_capture(effective_last)

    if not was_capture:
        return False

    # Chosen move must capture on the same square
    if chosen_move.to_square != effective_last.to_square:
        return False
    if not board.is_capture(chosen_move):
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
    increment_seconds: float = 0.0,
    speed: float = 1.0,
    rng: random.Random | None = None,
    is_book: bool = False,
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
        # NOTE: Obvious recapture or forced move - در بازپس‌گیری‌های واضح یا تک‌حرکت قانونی،
        # انسان زمان پردازش ذهنی را بسیار کوتاه می‌کند و ظرف ۰.۴ تا ۱.۲ ثانیه واکنش نشان می‌دهد.
        duration = r.uniform(0.4, 1.2)

    # 2. Book phase: early plies (< 10) or recognized opening book recall: 0.6–2.0 s
    elif is_book or (effective_ply < 10 and any(c.move == chosen_move for c in candidates[:2])):
        # NOTE: Opening phase recall - در حرکات گشایش، بازیکن از حافظه با مکث طبیعی ۰.۶ تا ۲.۰ ثانیه بازی می‌کند.
        duration = r.uniform(0.6, 2.0)


    # 3. Base by complexity
    else:
        # NOTE: Positional complexity scaling - هرچه گزینه‌های قانونی و مهره‌های درگیر بیشتر باشند
        # یا شاه در معرض کیش باشد، فرآیند محاسبه شاخه‌ها در قشر مخ انسان طولانی‌تر می‌شود.
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

        # NOTE: Log-normal timing jitter - زمان تصمیم‌گیری انسان دارای نوسان طبیعی و نویز لگ‌نرمال است
        # تا الگوی ماشینی و فواصل زمانی تکراری تولید نشود.
        noise = math.exp(r.gauss(0, 0.35))
        duration = base * noise
        # Typical 2–10 s, hard cap 25 s
        duration = min(25.0, max(0.5, duration))

    # 4. Speed multiplier (applied before clock caps so caps are never violated)
    effective_speed = max(0.01, speed)
    duration = duration / effective_speed

    # 5. Panic mode vs Hard floor constraint
    is_panic = clock_seconds is not None and clock_seconds < 10.0 and increment_seconds == 0.0

    if is_panic:
        # NOTE: Panic floor 0.12s - در تنگی وقت شدید (زیر ۱۰ ثانیه و بدون اینکریمنت در بولت)،
        # بازیکن انسان با تکیه بر پیش‌حرکت (premove) و واکنش‌های غریزی با حداقل تأخیر ممکن (~۱۲۰ms)
        # بازی می‌کند تا پرچم نخورد (flag نشود)، اما کمتر از ۱۲۰ میلی‌ثانیه نقض محدودیت فیزیکی عصب و عضله انسان است.
        hard_floor = 0.12
    else:
        # NOTE: Hard floor 0.30s - حداقل زمان واکنش بینایی-حرکتی انسان ۳۰۰ میلی‌ثانیه است؛
        # حرکت آنی و بدون وقفه (زیر ۳۰۰ms) در حالت عادی بارزترین نشانه استفاده از بات برای سیستم‌های ضدتقلب است.
        hard_floor = 0.30

    # 6. Clock-aware budgeting & constraints
    if clock_seconds is not None:
        moves_remaining = max(10, min(40, 45 - (effective_ply // 2)))
        clock_budget = (clock_seconds / moves_remaining) + (increment_seconds * 0.75)
        budget_noise = math.exp(r.gauss(0, 0.20))
        budget = max(hard_floor, clock_budget * budget_noise)

        if is_panic:
            # Panic mode: clock is low (< 10s without increment)
            # Instinctive rapid moves while preserving human jitter
            panic_jitter = math.exp(r.gauss(0, 0.25))
            panic_budget = max(hard_floor, (clock_seconds / 15.0) * panic_jitter)
            panic_budget = min(panic_budget, 1.5)
            duration = min(duration, panic_budget)
        else:
            # Hard clock limits with subtle human jitter to avoid flagging
            jitter_clock = math.exp(r.gauss(0, 0.10))
            max_clock_time = max(
                hard_floor, (clock_seconds * 0.05 + increment_seconds * 0.75) * jitter_clock
            )
            if clock_seconds < 20.0 and increment_seconds == 0.0:
                max_clock_time = min(max_clock_time, 1.5)
            duration = min(duration, max(budget, hard_floor))
            duration = min(duration, max_clock_time)

    delay = max(hard_floor, duration)
    return delay
