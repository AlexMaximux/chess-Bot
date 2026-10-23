"""Tests validating real captured fixtures from chess.com."""

import json
from pathlib import Path

import chess

from chess_autoplayer.board.snapshot import parse_snapshot
from chess_autoplayer.board.state import GameState

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_real_white_midgame_fixture() -> None:
    fix_path = FIXTURES_DIR / "white_midgame.json"
    assert fix_path.is_file(), f"Fixture file {fix_path} must exist"

    raw = json.loads(fix_path.read_text(encoding="utf-8"))
    snapshot = parse_snapshot(raw)
    state = GameState.from_snapshot(snapshot)

    assert snapshot.found is True
    assert snapshot.flipped_class is False
    assert snapshot.flipped_geometry is False
    assert state.source == "moves"
    assert state.our_color == chess.WHITE
    assert state.turn == chess.WHITE
    assert state.is_our_turn is True
    assert state.ply == 6
    assert state.is_game_over is False
    assert state.fen == "rnbqkbnr/pp2pppp/3p4/8/3pP3/5N2/PPP2PPP/RNBQKB1R w KQkq - 0 4"


def test_real_black_midgame_fixture() -> None:
    fix_path = FIXTURES_DIR / "black_midgame.json"
    assert fix_path.is_file(), f"Fixture file {fix_path} must exist"

    raw = json.loads(fix_path.read_text(encoding="utf-8"))
    snapshot = parse_snapshot(raw)
    state = GameState.from_snapshot(snapshot)

    assert snapshot.found is True
    assert snapshot.flipped_class is True
    assert snapshot.flipped_geometry is True
    assert state.source == "moves"
    assert state.our_color == chess.BLACK
    assert state.turn == chess.WHITE
    assert state.is_our_turn is False
    assert state.ply == 6
    assert state.is_game_over is False
    assert state.fen == "r1bqkbnr/1ppp1ppp/p1n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 0 4"


def test_real_game_over_fixture() -> None:
    fix_path = FIXTURES_DIR / "game_over.json"
    assert fix_path.is_file(), f"Fixture file {fix_path} must exist"

    raw = json.loads(fix_path.read_text(encoding="utf-8"))
    snapshot = parse_snapshot(raw)
    state = GameState.from_snapshot(snapshot)

    assert snapshot.found is True
    assert snapshot.game_over is True
    assert snapshot.game_over_text is not None
    assert "resignation" in snapshot.game_over_text.lower()
    assert state.is_game_over is True
