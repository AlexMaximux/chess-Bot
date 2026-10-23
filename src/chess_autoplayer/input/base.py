"""Base interfaces and protocols for chess move input."""

import random
from dataclasses import dataclass, field
from typing import Protocol

import chess

from chess_autoplayer.board.snapshot import PromotionOption, Rect


@dataclass(frozen=True)
class MoveContext:
    """Context required to execute a move on the board."""

    board_rect: Rect
    flipped: bool
    style: str = "drag"  # "drag", "click", or "mixed"
    promotion_piece: str | None = None
    rng: random.Random | None = None
    promotion_options: list[PromotionOption] = field(default_factory=list)


class MoveInput(Protocol):
    """Protocol implemented by CDP input and real OS mouse input."""

    async def perform_move(self, move: chess.Move, ctx: MoveContext) -> None:
        """Execute the chess move with human-like mouse trajectories and timing."""
        ...

    async def click_promotion(self, piece: str, options: list[PromotionOption]) -> bool:
        """Click the chosen piece option in the promotion picker dialog."""
        ...

    async def close(self) -> None:
        """Release any pressed mouse buttons and clean up resources."""
        ...
