"""Typed events and state definitions for the bot controller."""

from dataclasses import dataclass
from enum import StrEnum

import chess

from chess_autoplayer.engine.stockfish import Line


class BotState(StrEnum):
    """Lifecycle states of the autonomous chess bot."""

    IDLE = "IDLE"
    BLOCKED_URL = "BLOCKED_URL"
    WAITING_FOR_GAME = "WAITING_FOR_GAME"
    OPPONENT_TURN = "OPPONENT_TURN"
    THINKING = "THINKING"
    MOVING = "MOVING"
    VERIFYING = "VERIFYING"
    GAME_OVER = "GAME_OVER"
    PAUSED = "PAUSED"
    ERROR = "ERROR"
    STOPPED = "STOPPED"


@dataclass(frozen=True)
class StatusEvent:
    """Emitted when the bot transitions between states."""

    state: BotState
    message: str


@dataclass(frozen=True)
class DecisionEvent:
    """Emitted when the engine selects a move to play."""

    move_san: str
    candidates: list[Line]
    chosen: chess.Move
    eval_cp: int
    think_s: float


@dataclass(frozen=True)
class MoveEvent:
    """Emitted when a move is executed and confirmed on the board."""

    ply: int
    san: str
    by_bot: bool


@dataclass(frozen=True)
class GameOverEvent:
    """Emitted when the game finishes."""

    text: str


@dataclass(frozen=True)
class ErrorEvent:
    """Emitted on an unrecoverable or paused error condition."""

    message: str


BotEvent = StatusEvent | DecisionEvent | MoveEvent | GameOverEvent | ErrorEvent
