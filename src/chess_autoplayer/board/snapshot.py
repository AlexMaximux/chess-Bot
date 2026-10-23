"""Typed models and strict parsing for DOM snapshots."""

import re
from dataclasses import dataclass
from typing import Any

SQUARE_REGEX = re.compile(r"^[a-h][1-8]$")
VALID_COLORS = {"w", "b"}
VALID_PIECE_TYPES = {"p", "n", "b", "r", "q", "k"}


class SnapshotError(Exception):
    """Raised when DOM snapshot data is missing, malformed, or has invalid types."""


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class WindowInfo:
    screenX: float
    screenY: float
    outerWidth: float
    outerHeight: float
    innerWidth: float
    innerHeight: float


@dataclass(frozen=True)
class PieceInfo:
    color: str  # 'w' or 'b'
    type: str  # 'p', 'n', 'b', 'r', 'q', 'k'
    square: str  # 'a1'..'h8'


@dataclass(frozen=True)
class Snapshot:
    url: str
    found: bool
    board_rect: Rect
    flipped_class: bool
    flipped_geometry: bool
    pieces: list[PieceInfo]
    moves: list[str]
    last_move_highlights: list[str]
    game_over: bool
    game_over_text: str | None
    promotion_open: bool
    device_pixel_ratio: float
    window: WindowInfo
    dragging: bool


def _parse_rect(raw: Any) -> Rect:
    if not isinstance(raw, dict):
        raise SnapshotError(f"Expected boardRect to be dict, got {type(raw).__name__}")
    for k in ("x", "y", "width", "height"):
        if k not in raw or not isinstance(raw[k], (int, float)):
            raise SnapshotError(f"boardRect missing or invalid numeric field {k!r}: {raw.get(k)!r}")
    return Rect(
        x=float(raw["x"]),
        y=float(raw["y"]),
        width=float(raw["width"]),
        height=float(raw["height"]),
    )


def _parse_window(raw: Any) -> WindowInfo:
    if not isinstance(raw, dict):
        raise SnapshotError(f"Expected window to be dict, got {type(raw).__name__}")
    for k in ("screenX", "screenY", "outerWidth", "outerHeight", "innerWidth", "innerHeight"):
        if k not in raw or not isinstance(raw[k], (int, float)):
            raise SnapshotError(f"window missing or invalid numeric field {k!r}: {raw.get(k)!r}")
    return WindowInfo(
        screenX=float(raw["screenX"]),
        screenY=float(raw["screenY"]),
        outerWidth=float(raw["outerWidth"]),
        outerHeight=float(raw["outerHeight"]),
        innerWidth=float(raw["innerWidth"]),
        innerHeight=float(raw["innerHeight"]),
    )


def _parse_pieces(raw: Any) -> list[PieceInfo]:
    if not isinstance(raw, list):
        raise SnapshotError(f"Expected pieces to be list, got {type(raw).__name__}")
    pieces: list[PieceInfo] = []
    for item in raw:
        if not isinstance(item, dict):
            raise SnapshotError(f"Expected piece item to be dict, got {type(item).__name__}")
        color = item.get("color")
        ptype = item.get("type")
        square = item.get("square")

        if color not in VALID_COLORS:
            raise SnapshotError(f"Invalid piece color: {color!r}")
        if ptype not in VALID_PIECE_TYPES:
            raise SnapshotError(f"Invalid piece type: {ptype!r}")
        if not isinstance(square, str) or not SQUARE_REGEX.match(square):
            raise SnapshotError(f"Invalid piece square: {square!r}")

        pieces.append(PieceInfo(color=color, type=ptype, square=square))
    return pieces


def parse_snapshot(raw: object) -> Snapshot:
    """Parse and validate raw JSON snapshot returned by reader.js."""
    if not isinstance(raw, dict):
        raise SnapshotError(f"Snapshot raw data must be a JSON object, got {type(raw).__name__}")

    # Check required keys
    required_keys = [
        "url",
        "found",
        "boardRect",
        "flippedClass",
        "flippedGeometry",
        "pieces",
        "moves",
        "lastMoveHighlights",
        "gameOver",
        "devicePixelRatio",
        "window",
        "dragging",
    ]
    for key in required_keys:
        if key not in raw:
            raise SnapshotError(f"Missing required key in snapshot: {key!r}")

    url = raw["url"]
    if not isinstance(url, str):
        raise SnapshotError(f"Expected url to be str, got {type(url).__name__}")

    found = raw["found"]
    if not isinstance(found, bool):
        raise SnapshotError(f"Expected found to be bool, got {type(found).__name__}")

    board_rect = _parse_rect(raw["boardRect"])

    flipped_class = raw["flippedClass"]
    if not isinstance(flipped_class, bool):
        raise SnapshotError(f"Expected flippedClass to be bool, got {type(flipped_class).__name__}")

    flipped_geometry = raw["flippedGeometry"]
    if not isinstance(flipped_geometry, bool):
        raise SnapshotError(
            f"Expected flippedGeometry to be bool, got {type(flipped_geometry).__name__}"
        )

    pieces = _parse_pieces(raw["pieces"])

    moves_raw = raw["moves"]
    if not isinstance(moves_raw, list) or not all(isinstance(m, str) for m in moves_raw):
        raise SnapshotError("Expected moves to be a list of strings")

    highlights_raw = raw["lastMoveHighlights"]
    if not isinstance(highlights_raw, list) or not all(isinstance(h, str) for h in highlights_raw):
        raise SnapshotError("Expected lastMoveHighlights to be a list of strings")

    game_over = raw["gameOver"]
    if not isinstance(game_over, bool):
        raise SnapshotError(f"Expected gameOver to be bool, got {type(game_over).__name__}")

    game_over_text = raw.get("gameOverText")
    if game_over_text is not None and not isinstance(game_over_text, str):
        raise SnapshotError(
            f"Expected gameOverText to be str or None, got {type(game_over_text).__name__}"
        )

    # promotionOpen / promotion_open
    promo = raw.get("promotionOpen", raw.get("promotion_open", False))
    if not isinstance(promo, bool):
        raise SnapshotError(f"Expected promotionOpen to be bool, got {type(promo).__name__}")

    dpr = raw["devicePixelRatio"]
    if not isinstance(dpr, (int, float)):
        raise SnapshotError(f"Expected devicePixelRatio to be numeric, got {type(dpr).__name__}")

    win = _parse_window(raw["window"])

    dragging = raw["dragging"]
    if not isinstance(dragging, bool):
        raise SnapshotError(f"Expected dragging to be bool, got {type(dragging).__name__}")

    return Snapshot(
        url=url,
        found=found,
        board_rect=board_rect,
        flipped_class=flipped_class,
        flipped_geometry=flipped_geometry,
        pieces=pieces,
        moves=list(moves_raw),
        last_move_highlights=list(highlights_raw),
        game_over=game_over,
        game_over_text=game_over_text,
        promotion_open=promo,
        device_pixel_ratio=float(dpr),
        window=win,
        dragging=dragging,
    )
