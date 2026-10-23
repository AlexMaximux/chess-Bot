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
