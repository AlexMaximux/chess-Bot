"""Tests for Stockfish engine integration and profiles."""

import shutil
from pathlib import Path

import chess
import pytest

from chess_autoplayer.config import Settings
from chess_autoplayer.engine.profiles import PROFILES, get_profile
from chess_autoplayer.engine.stockfish import Engine, EngineNotFoundError


def test_profiles_table_definitions() -> None:
    expected_names = {"beginner", "casual", "club", "strong", "master", "max"}
    assert set(PROFILES.keys()) == expected_names

    club = get_profile("club")
    assert club.multipv == 4
    assert club.limit_strength is True
    assert club.elo == 1900
    assert club.time_limit == 0.25

    with pytest.raises(KeyError, match="Unknown strength profile"):
        get_profile("superhuman")


def test_engine_missing_binary_raises() -> None:
    engine = Engine(stockfish_path=Path("/path/to/nonexistent/stockfish"))
    with pytest.raises(EngineNotFoundError, match="Stockfish binary not found"):
        engine.start()


@pytest.fixture
def stockfish_path() -> Path | None:
    settings = Settings()
    path = settings.resolved_stockfish_path()
    if path.is_file():
        return path
    which = shutil.which("stockfish")
    if which:
        return Path(which)
    return None


def test_engine_mate_in_one_at_max(stockfish_path: Path | None) -> None:
    if stockfish_path is None:
        pytest.skip("Stockfish binary not found on target machine")

    fen = "6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1"
    board = chess.Board(fen)

    with Engine(stockfish_path, profile="max") as engine:
        lines = engine.analyse(board)
        assert len(lines) >= 1
        best = lines[0]
        # d1d8# is the only mate in 1
        assert best.move == chess.Move.from_uci("d1d8")
        assert best.mate_score == 1


def test_engine_close_is_idempotent(stockfish_path: Path | None) -> None:
    if stockfish_path is None:
        pytest.skip("Stockfish binary not found on target machine")

    engine = Engine(stockfish_path, profile="club")
    engine.start()
    assert engine._engine is not None
    engine.close()
    assert engine._engine is None
    # Second close must not raise
    engine.close()
    assert engine._engine is None


def test_engine_profiles_start(stockfish_path: Path | None) -> None:
    if stockfish_path is None:
        pytest.skip("Stockfish binary not found on target machine")

    board = chess.Board()
    for profile_name in ("beginner", "club", "master"):
        with Engine(stockfish_path, profile=profile_name) as engine:
            lines = engine.analyse(board)
            assert len(lines) >= 1
            assert all(line.move in board.legal_moves for line in lines)
