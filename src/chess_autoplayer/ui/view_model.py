"""Pure presentation logic for the GUI control panel.

Separates formatting, evaluation metrics, session tallying, and status color mapping
from widget construction and event binding.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import chess

from chess_autoplayer.bot.events import BotState
from chess_autoplayer.engine.stockfish import Line

# Semantic status colors for UI indicators
COLOR_PLAYING = "#15803d"  # Forest green
COLOR_PAUSED = "#d97706"  # Amber
COLOR_ERROR = "#b91c1c"  # Crimson red
COLOR_NEUTRAL = "#4b5563"  # Neutral slate gray


def get_status_color(state: BotState | str) -> str:
    """Return hex color corresponding to bot state."""
    state_str = state.value if isinstance(state, BotState) else str(state)
    if state_str in ("THINKING", "MOVING", "VERIFYING", "OPPONENT_TURN"):
        return COLOR_PLAYING
    if state_str in ("IDLE", "PAUSED", "WAITING_FOR_GAME", "GAME_OVER"):
        return COLOR_PAUSED
    if state_str in ("ERROR", "BLOCKED_URL"):
        return COLOR_ERROR
    return COLOR_NEUTRAL


def format_status(state: BotState | str, message: str) -> tuple[str, str]:
    """Format state and status message for display, returning (text, hex_color)."""
    state_str = state.value if isinstance(state, BotState) else str(state)
    color = get_status_color(state)
    msg = message.strip()
    if not msg:
        return f"[{state_str}]", color
    return f"[{state_str}] {msg}", color


def format_eval(eval_cp: int | None, mate_score: int | None = None) -> tuple[float, str]:
    """Format centipawn evaluation and mate score for eval bar.

    Returns:
        tuple[float, str]: (fraction 0.0-1.0 from bot POV, label string like "+1.2" or "M3").
        0.5 represents 0 cp (equal), 1.0 represents +1000 cp or win mate, 0.0 represents -1000 cp.
    """
    if mate_score is not None:
        if mate_score > 0:
            return 1.0, f"M{mate_score}"
        elif mate_score < 0:
            return 0.0, f"-M{abs(mate_score)}"
        else:
            return 1.0, "M0"

    if eval_cp is None:
        return 0.5, "0.0"

    # Clamp centipawns between -1000 and +1000 for visual progress fraction
    clamped = max(-1000, min(1000, eval_cp))
    fraction = (clamped + 1000.0) / 2000.0

    pawn_val = eval_cp / 100.0
    if pawn_val > 0:
        label = f"+{pawn_val:.1f}"
    elif pawn_val == 0.0:
        label = "0.0"
    else:
        label = f"{pawn_val:.1f}"

    return fraction, label


def format_decision(
    chosen_san: str,
    candidates: list[Line],
    think_s: float,
) -> str:
    """Format the engine's last move decision and top candidates for display."""
    if not chosen_san:
        return "No moves played yet"

    lines_summary: list[str] = []
    for idx, c in enumerate(candidates[:3]):
        if c.mate_score is not None:
            score_text = f"M{c.mate_score}" if c.mate_score > 0 else f"-M{abs(c.mate_score)}"
        else:
            pawn = c.score_cp / 100.0
            score_text = f"+{pawn:.1f}" if pawn > 0 else f"{pawn:.1f}"
        uci = c.move.uci()
        lines_summary.append(f"{idx + 1}. {uci} ({score_text})")

    cand_str = " | ".join(lines_summary) if lines_summary else "none"
    return f"Move: {chosen_san} (think {think_s:.1f}s)\nCandidates: {cand_str}"


def format_move_log_row(ply: int, san: str, by_bot: bool) -> tuple[str, str, str]:
    """Format a move event for the scrollable move log table.

    Returns:
        tuple[str, str, str]: (turn_prefix, san, role)
        e.g. ("1.", "e4", "bot") or ("1...", "e5", "opponent")
    """
    move_num = (ply + 1) // 2
    prefix = f"{move_num}." if (ply % 2 != 0) else f"{move_num}..."
    role = "bot" if by_bot else "opponent"
    return prefix, san, role


@dataclass
class SessionTally:
    """Session statistics tracking games, wins, losses, and draws."""

    games: int = 0
    wins: int = 0
    losses: int = 0
    draws: int = 0

    def record_game(self, text: str, our_color: chess.Color = chess.WHITE) -> str:
        """Parse game-over banner text and update tally counts.

        Returns:
            str: Outcome description ('win', 'loss', 'draw', or 'unknown').
        """
        self.games += 1
        t = text.lower()

        # 1. Direct player markers
        if "you won" in t or "you win" in t:
            self.wins += 1
            return "win"
        if "you lost" in t or "you lose" in t:
            self.losses += 1
            return "loss"

        # 2. Draws
        if any(
            w in t
            for w in (
                "draw",
                "stalemate",
                "insufficient material",
                "repetition",
                "50-move",
                "agreed",
            )
        ):
            self.draws += 1
            return "draw"

        # 3. Color-based wins (e.g. "Checkmate - Black wins", "White won by resignation")
        white_won = bool(re.search(r"white\s+(wins|won)", t))
        black_won = bool(re.search(r"black\s+(wins|won)", t))

        if white_won:
            if our_color == chess.WHITE:
                self.wins += 1
                return "win"
            else:
                self.losses += 1
                return "loss"

        if black_won:
            if our_color == chess.BLACK:
                self.wins += 1
                return "win"
            else:
                self.losses += 1
                return "loss"

        # Fallback if text doesn't identify winner
        self.draws += 1
        return "draw"

    def format(self) -> str:
        """Format tally into status string."""
        return (
            f"Games: {self.games}  |  Wins: {self.wins}  |  "
            f"Losses: {self.losses}  |  Draws: {self.draws}"
        )
