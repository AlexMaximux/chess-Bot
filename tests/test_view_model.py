"""Unit tests for pure UI view-model formatting and presentation logic."""

import chess

from chess_autoplayer.bot.events import BotState
from chess_autoplayer.engine.stockfish import Line
from chess_autoplayer.ui.view_model import (
    COLOR_ERROR,
    COLOR_NEUTRAL,
    COLOR_PAUSED,
    COLOR_PLAYING,
    SessionTally,
    format_decision,
    format_eval,
    format_move_log_row,
    format_status,
    get_status_color,
)


def test_status_formatting_and_colors() -> None:
    # Playing states
    for state in (
        BotState.THINKING,
        BotState.MOVING,
        BotState.VERIFYING,
        BotState.OPPONENT_TURN,
    ):
        assert get_status_color(state) == COLOR_PLAYING

    # Paused / Waiting states
    for state in (BotState.IDLE, BotState.PAUSED, BotState.WAITING_FOR_GAME, BotState.GAME_OVER):
        assert get_status_color(state) == COLOR_PAUSED

    # Error / Blocked states
    for state in (BotState.ERROR, BotState.BLOCKED_URL):
        assert get_status_color(state) == COLOR_ERROR

    # Stopped state
    assert get_status_color(BotState.STOPPED) == COLOR_NEUTRAL

    # Text formatting
    text, color = format_status(BotState.THINKING, "Searching ply 12")
    assert text == "[THINKING] Searching ply 12"
    assert color == COLOR_PLAYING

    empty_text, empty_color = format_status(BotState.IDLE, "")
    assert empty_text == "[IDLE]"
    assert empty_color == COLOR_PAUSED


def test_eval_formatting_and_clamping() -> None:
    # 0 centipawns is exact midpoint 0.5
    frac, label = format_eval(0)
    assert abs(frac - 0.5) < 1e-4
    assert label == "0.0"

    # +250 centipawns (+2.5 pawns)
    frac, label = format_eval(250)
    assert abs(frac - 0.625) < 1e-4
    assert label == "+2.5"

    # -400 centipawns (-4.0 pawns)
    frac, label = format_eval(-400)
    assert abs(frac - 0.3) < 1e-4
    assert label == "-4.0"

    # Clamping beyond ±1000 centipawns
    frac_hi, label_hi = format_eval(1500)
    assert frac_hi == 1.0
    assert label_hi == "+15.0"

    frac_lo, label_lo = format_eval(-1200)
    assert frac_lo == 0.0
    assert label_lo == "-12.0"

    # Mate announcements
    frac_mate_win, label_mate_win = format_eval(None, mate_score=3)
    assert frac_mate_win == 1.0
    assert label_mate_win == "M3"

    frac_mate_loss, label_mate_loss = format_eval(None, mate_score=-2)
    assert frac_mate_loss == 0.0
    assert label_mate_loss == "-M2"

    # None fallback
    frac_none, label_none = format_eval(None, mate_score=None)
    assert frac_none == 0.5
    assert label_none == "0.0"


def test_format_decision() -> None:
    candidates = [
        Line(move=chess.Move.from_uci("e2e4"), score_cp=35, mate_score=None, pv=[]),
        Line(move=chess.Move.from_uci("d2d4"), score_cp=20, mate_score=None, pv=[]),
        Line(move=chess.Move.from_uci("g1f3"), score_cp=-10, mate_score=None, pv=[]),
        Line(move=chess.Move.from_uci("c2c4"), score_cp=-50, mate_score=None, pv=[]),
    ]

    summary = format_decision("e4", candidates, think_s=1.23)
    assert "Move: e4 (think 1.2s)" in summary
    assert "1. e2e4 (+0.3)" in summary
    assert "2. d2d4 (+0.2)" in summary
    assert "3. g1f3 (-0.1)" in summary
    # Only top 3 candidates are listed
    assert "c2c4" not in summary

    # Empty decision
    assert format_decision("", [], 0.0) == "No moves played yet"


def test_format_move_log_row() -> None:
    # Ply 1: White's first half-move
    p1, san1, role1 = format_move_log_row(ply=1, san="e4", by_bot=True)
    assert p1 == "1."
    assert san1 == "e4"
    assert role1 == "bot"

    # Ply 2: Black's first half-move
    p2, san2, role2 = format_move_log_row(ply=2, san="e5", by_bot=False)
    assert p2 == "1..."
    assert san2 == "e5"
    assert role2 == "opponent"

    # Ply 3: White's second half-move
    p3, san3, role3 = format_move_log_row(ply=3, san="Nf3", by_bot=True)
    assert p3 == "2."
    assert san3 == "Nf3"
    assert role3 == "bot"


def test_session_tally_parsing_and_formatting() -> None:
    tally = SessionTally()
    assert tally.games == 0
    assert tally.format() == "Games: 0  |  Wins: 0  |  Losses: 0  |  Draws: 0"

    # 1. "You Won"
    res1 = tally.record_game("You Won! Well played.", our_color=chess.WHITE)
    assert res1 == "win"
    assert tally.wins == 1
    assert tally.games == 1

    # 2. "You Lost"
    res2 = tally.record_game("Game Over. You Lost by checkmate.", our_color=chess.WHITE)
    assert res2 == "loss"
    assert tally.losses == 1
    assert tally.games == 2

    # 3. Checkmate - Black wins (we are Black)
    res3 = tally.record_game("Checkmate - Black wins", our_color=chess.BLACK)
    assert res3 == "win"
    assert tally.wins == 2
    assert tally.games == 3

    # 4. Checkmate - White wins (we are Black)
    res4 = tally.record_game("Checkmate - White wins", our_color=chess.BLACK)
    assert res4 == "loss"
    assert tally.losses == 2
    assert tally.games == 4

    # 5. Resignation
    res5 = tally.record_game("White won by resignation", our_color=chess.WHITE)
    assert res5 == "win"
    assert tally.wins == 3

    # 6. Stalemate / Draw variations
    res6 = tally.record_game("Draw by stalemate", our_color=chess.WHITE)
    assert res6 == "draw"
    assert tally.draws == 1

    res7 = tally.record_game("Draw by insufficient material", our_color=chess.WHITE)
    assert res7 == "draw"
    assert tally.draws == 2

    res8 = tally.record_game("Draw by 50-move rule", our_color=chess.WHITE)
    assert res8 == "draw"
    assert tally.draws == 3

    assert tally.games == 8
    assert tally.format() == "Games: 8  |  Wins: 3  |  Losses: 2  |  Draws: 3"
