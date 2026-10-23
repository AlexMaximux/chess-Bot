"""Typed models and strict parsing for DOM snapshots."""

import re
from dataclasses import dataclass, field
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
class PromotionOption:
    piece: str  # 'q', 'r', 'b', 'n'
    rect: Rect


@dataclass(frozen=True)
class ClockInfo:
    text: str | None = None
    seconds: float | None = None
    ticking: bool = False
    color: str | None = None


@dataclass(frozen=True)
class Clocks:
    top: ClockInfo | None = None
    bottom: ClockInfo | None = None
    white: ClockInfo | None = None
    black: ClockInfo | None = None


@dataclass(frozen=True)
class StructuredMove:
    ply: int
    move_number: int
    color: str  # 'w' or 'b'
    san: str
    time: str | None = None


@dataclass(frozen=True)
class GameOverButton:
    type: str  # "rematch" or "new_game"
    text: str
    rect: Rect


@dataclass(frozen=True)
class StartGameButton:
    rect: Rect


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
    our_color_hint: str | None = None
    promotion_options: list[PromotionOption] = field(default_factory=list)
    structured_moves: list[StructuredMove] = field(default_factory=list)
    clocks: Clocks = field(default_factory=Clocks)
    game_over_buttons: list[GameOverButton] = field(default_factory=list)
    has_resign_button: bool = False
    has_draw_button: bool = False
    has_move_list: bool = False
    has_start_button: bool = False
    start_game_button: StartGameButton | None = None

    @property
    def our_clock(self) -> ClockInfo | None:
        """Return the clock corresponding to our color if available, or bottom clock."""
        if self.our_color_hint == "w":
            return self.clocks.white
        if self.our_color_hint == "b":
            return self.clocks.black
        return self.clocks.bottom


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

    hint = raw.get("ourColorHint", raw.get("our_color_hint"))
    if hint is not None and hint not in ("w", "b"):
        raise SnapshotError(f"Expected ourColorHint to be 'w', 'b', or null, got {hint!r}")

    promotion_options: list[PromotionOption] = []
    raw_promo_opts = raw.get("promotionOptions", raw.get("promotion_options", []))
    if isinstance(raw_promo_opts, list):
        for opt in raw_promo_opts:
            if isinstance(opt, dict) and "piece" in opt and "rect" in opt:
                piece_str = str(opt["piece"]).lower()
                r_opt = _parse_rect(opt["rect"])
                promotion_options.append(PromotionOption(piece=piece_str, rect=r_opt))

    clocks = _parse_clocks(raw.get("clocks"))
    raw_struct_moves = raw.get("structuredMoves", raw.get("structured_moves", []))
    structured_moves = _parse_structured_moves(raw_struct_moves)

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
        our_color_hint=hint,
        promotion_options=promotion_options,
        structured_moves=structured_moves,
        clocks=clocks,
        game_over_buttons=_parse_game_over_buttons(
            raw.get("gameOverButtons", raw.get("game_over_buttons", []))
        ),
        has_resign_button=bool(raw.get("hasResignButton", False)),
        has_draw_button=bool(raw.get("hasDrawButton", False)),
        has_move_list=bool(raw.get("hasMoveList", False)),
        has_start_button=bool(raw.get("hasStartButton", False)),
        start_game_button=_parse_start_game_button(
            raw.get("startGameButton", raw.get("start_game_button"))
        ),
    )


def _parse_start_game_button(raw: Any) -> StartGameButton | None:
    if not isinstance(raw, dict) or "rect" not in raw:
        return None
    try:
        rect = _parse_rect(raw["rect"])
        return StartGameButton(rect=rect)
    except Exception:
        return None


def _parse_game_over_buttons(raw: Any) -> list[GameOverButton]:
    if not isinstance(raw, list):
        return []
    res: list[GameOverButton] = []
    for item in raw:
        if isinstance(item, dict):
            try:
                b_type = str(item.get("type", "new_game"))
                text = str(item.get("text", ""))
                r_dict = item.get("rect", {})
                if isinstance(r_dict, dict):
                    rect = Rect(
                        x=float(r_dict.get("x", 0.0)),
                        y=float(r_dict.get("y", 0.0)),
                        width=float(r_dict.get("width", 0.0)),
                        height=float(r_dict.get("height", 0.0)),
                    )
                    res.append(GameOverButton(type=b_type, text=text, rect=rect))
            except Exception:
                continue
    return res


def _parse_clock_info(raw: Any) -> ClockInfo | None:
    if not isinstance(raw, dict):
        return None
    text = raw.get("text")
    if text is not None and not isinstance(text, str):
        text = str(text)
    seconds_raw = raw.get("seconds")
    seconds = float(seconds_raw) if isinstance(seconds_raw, (int, float)) else None
    ticking = bool(raw.get("ticking", False))
    color = raw.get("color")
    if color is not None and not isinstance(color, str):
        color = str(color)
    return ClockInfo(text=text, seconds=seconds, ticking=ticking, color=color)


def _parse_clocks(raw: Any) -> Clocks:
    if not isinstance(raw, dict):
        return Clocks()
    return Clocks(
        top=_parse_clock_info(raw.get("top")),
        bottom=_parse_clock_info(raw.get("bottom")),
        white=_parse_clock_info(raw.get("white")),
        black=_parse_clock_info(raw.get("black")),
    )


def _parse_structured_moves(raw: Any) -> list[StructuredMove]:
    if not isinstance(raw, list):
        return []
    res: list[StructuredMove] = []
    for item in raw:
        if isinstance(item, dict):
            try:
                ply = int(item.get("ply", 0))
                move_num_val = item.get("moveNumber")
                if move_num_val is None:
                    move_num_val = item.get("move_number", 0)
                move_num = int(move_num_val) if move_num_val is not None else 0
                color = str(item.get("color", "w"))
                san = str(item.get("san", ""))
                time_val = item.get("time")
                if time_val is not None and not isinstance(time_val, str):
                    time_val = str(time_val)
                res.append(
                    StructuredMove(
                        ply=ply,
                        move_number=move_num,
                        color=color,
                        san=san,
                        time=time_val,
                    )
                )
            except Exception:
                continue
    return res
