"""UI package for Chess Autoplayer."""

from chess_autoplayer.ui.app import AutoplayerApp, run_app
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

__all__ = [
    "AutoplayerApp",
    "run_app",
    "get_status_color",
    "format_status",
    "format_eval",
    "format_decision",
    "format_move_log_row",
    "SessionTally",
    "COLOR_PLAYING",
    "COLOR_PAUSED",
    "COLOR_ERROR",
    "COLOR_NEUTRAL",
]
