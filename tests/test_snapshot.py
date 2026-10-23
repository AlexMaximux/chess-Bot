"""Tests for chess_autoplayer.board.snapshot."""

from typing import Any

import pytest

from chess_autoplayer.board.snapshot import (
    PieceInfo,
    Rect,
    SnapshotError,
    WindowInfo,
    parse_snapshot,
)


def sample_valid_raw_snapshot() -> dict[str, Any]:
    return {
        "url": "https://www.chess.com/play/computer",
        "found": True,
        "boardRect": {"x": 100.0, "y": 200.0, "width": 800.0, "height": 800.0},
        "flippedClass": False,
        "flippedGeometry": False,
        "pieces": [
            {"color": "w", "type": "p", "square": "e2"},
            {"color": "w", "type": "k", "square": "e1"},
            {"color": "b", "type": "k", "square": "e8"},
        ],
        "moves": ["e4", "e5"],
        "lastMoveHighlights": ["e7", "e5"],
        "gameOver": False,
        "gameOverText": None,
        "promotionOpen": False,
        "devicePixelRatio": 2.0,
        "window": {
            "screenX": 0.0,
            "screenY": 25.0,
            "outerWidth": 1440.0,
            "outerHeight": 900.0,
            "innerWidth": 1200.0,
            "innerHeight": 800.0,
        },
        "dragging": False,
    }


def test_parse_valid_snapshot() -> None:
    raw = sample_valid_raw_snapshot()
    snap = parse_snapshot(raw)

    assert snap.found is True
    assert snap.url == "https://www.chess.com/play/computer"
    assert snap.board_rect == Rect(100.0, 200.0, 800.0, 800.0)
    assert snap.flipped_class is False
    assert snap.flipped_geometry is False
    assert len(snap.pieces) == 3
    assert snap.pieces[0] == PieceInfo(color="w", type="p", square="e2")
    assert snap.moves == ["e4", "e5"]
    assert snap.last_move_highlights == ["e7", "e5"]
    assert snap.game_over is False
    assert snap.game_over_text is None
    assert snap.promotion_open is False
    assert snap.device_pixel_ratio == 2.0
    assert snap.window == WindowInfo(0.0, 25.0, 1440.0, 900.0, 1200.0, 800.0)
    assert snap.dragging is False
    assert snap.our_color_hint is None
    assert snap.promotion_options == []


def test_parse_snapshot_with_promotion_options() -> None:
    raw = sample_valid_raw_snapshot()
    raw["promotionOpen"] = True
    raw["promotionOptions"] = [
        {"piece": "q", "rect": {"x": 200.0, "y": 200.0, "width": 50.0, "height": 50.0}},
        {"piece": "n", "rect": {"x": 200.0, "y": 250.0, "width": 50.0, "height": 50.0}},
    ]
    snap = parse_snapshot(raw)
    assert snap.promotion_open is True
    assert len(snap.promotion_options) == 2
    assert snap.promotion_options[0].piece == "q"
    assert snap.promotion_options[0].rect == Rect(200.0, 200.0, 50.0, 50.0)
    assert snap.promotion_options[1].piece == "n"


def test_parse_not_found_snapshot() -> None:
    raw = {
        "url": "https://www.chess.com/play/computer",
        "found": False,
        "boardRect": {"x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0},
        "flippedClass": False,
        "flippedGeometry": False,
        "pieces": [],
        "moves": [],
        "lastMoveHighlights": [],
        "gameOver": False,
        "gameOverText": None,
        "promotionOpen": False,
        "devicePixelRatio": 1.0,
        "window": {
            "screenX": 0.0,
            "screenY": 0.0,
            "outerWidth": 0.0,
            "outerHeight": 0.0,
            "innerWidth": 0.0,
            "innerHeight": 0.0,
        },
        "dragging": False,
    }
    snap = parse_snapshot(raw)
    assert snap.found is False
    assert len(snap.pieces) == 0


def test_parse_missing_field_raises() -> None:
    raw = sample_valid_raw_snapshot()
    del raw["boardRect"]
    with pytest.raises(SnapshotError, match="boardRect"):
        parse_snapshot(raw)


def test_parse_wrong_type_raises() -> None:
    raw = sample_valid_raw_snapshot()
    raw["pieces"] = "not-a-list"
    with pytest.raises(SnapshotError, match="pieces"):
        parse_snapshot(raw)


def test_parse_invalid_piece_square_raises() -> None:
    raw = sample_valid_raw_snapshot()
    raw["pieces"] = [{"color": "w", "type": "p", "square": "z9"}]
    with pytest.raises(SnapshotError, match="square"):
        parse_snapshot(raw)


def test_parse_non_dict_input_raises() -> None:
    with pytest.raises(SnapshotError, match="object"):
        parse_snapshot("not a dict")


def test_parse_snapshot_with_clocks_and_structured_moves() -> None:
    raw = sample_valid_raw_snapshot()
    raw["clocks"] = {
        "top": {"text": "09:45", "seconds": 585.0, "ticking": False, "color": "b"},
        "bottom": {"text": "04:32.5", "seconds": 272.5, "ticking": True, "color": "w"},
        "white": {"text": "04:32.5", "seconds": 272.5, "ticking": True, "color": "w"},
        "black": {"text": "09:45", "seconds": 585.0, "ticking": False, "color": "b"},
    }
    raw["structuredMoves"] = [
        {"ply": 1, "moveNumber": 1, "color": "w", "san": "e4", "time": "09:58"},
        {"ply": 2, "moveNumber": 1, "color": "b", "san": "e5", "time": "09:55"},
    ]
    raw["ourColorHint"] = "w"

    snap = parse_snapshot(raw)
    assert snap.clocks.top is not None
    assert snap.clocks.top.seconds == 585.0
    assert snap.clocks.bottom is not None
    assert snap.clocks.bottom.seconds == 272.5
    assert snap.clocks.bottom.ticking is True
    assert snap.our_clock is not None
    assert snap.our_clock.seconds == 272.5

    assert len(snap.structured_moves) == 2
    assert snap.structured_moves[0].san == "e4"
    assert snap.structured_moves[0].ply == 1
    assert snap.structured_moves[0].color == "w"
    assert snap.structured_moves[0].time == "09:58"
    assert snap.structured_moves[1].san == "e5"
    assert snap.structured_moves[1].ply == 2
    assert snap.structured_moves[1].color == "b"
