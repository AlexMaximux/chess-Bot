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


def test_opening_book_candidates() -> None:
    board = chess.Board()
    from chess_autoplayer.engine.book import get_book_lines

    lines = get_book_lines(board)
    assert len(lines) >= 3
    moves = [l.move.uci() for l in lines]
    assert "e2e4" in moves
    assert "d2d4" in moves


def test_opening_book_deep_plies() -> None:
    """Verify that the opening book provides moves into 8 to 12 moves (up to 20+ plies)."""
    from chess_autoplayer.engine.book import get_book_lines

    # 1. Test Ruy Lopez up to move 8 (ply 16)
    board = chess.Board()
    for san in ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Ba4", "Nf6", "O-O", "Be7", "Re1", "b5", "Bb3", "d6", "c3", "O-O"]:
        board.push_san(san)
    assert board.ply() == 16
    lines = get_book_lines(board)
    assert len(lines) >= 1
    assert any(l.move == chess.Move.from_uci("h2h3") for l in lines)

    # 2. Test Sicilian Najdorf up to move 8 (ply 16)
    board2 = chess.Board()
    for san in ["e4", "c5", "Nf3", "d6", "d4", "cxd4", "Nxd4", "Nf6", "Nc3", "a6", "Be3", "e5", "Nb3", "Be6", "f3", "Be7"]:
        board2.push_san(san)
    assert board2.ply() == 16
    lines2 = get_book_lines(board2)
    assert len(lines2) >= 1
    assert any(l.move == chess.Move.from_uci("d1d2") for l in lines2)


def test_opening_book_diversity() -> None:
    """Verify that opening moves are diverse across games and not locked into a single fixed line."""
    import random
    from chess_autoplayer.engine.book import get_book_lines
    from chess_autoplayer.engine.profiles import get_profile
    from chess_autoplayer.engine.selector import select_move

    board = chess.Board()
    lines = get_book_lines(board)
    assert len(lines) >= 3

    profile = get_profile("club")
    chosen_moves: set[str] = set()

    for seed in range(200):
        decision = select_move(board, lines, profile=profile, rng=random.Random(seed))
        chosen_moves.add(decision.move.uci())

    # Must have picked more than 1 opening move (e.g. e4, d4, c4, etc.)
    assert len(chosen_moves) >= 2
    assert "e2e4" in chosen_moves
    assert "d2d4" in chosen_moves


def test_engine_uses_book_without_stockfish(monkeypatch: pytest.MonkeyPatch) -> None:
    board = chess.Board()
    engine = Engine(Path("/nonexistent/stockfish"))

    # When starting on ply 0, analyse must return book moves without attempting to launch Stockfish
    lines = engine.analyse(board, use_book=True)
    assert len(lines) >= 3
    assert all(l.move in board.legal_moves for l in lines)

