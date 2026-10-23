"""Tests for chess_autoplayer.board.state."""

import chess
import pytest

from chess_autoplayer.board.snapshot import PieceInfo, Rect, Snapshot, WindowInfo
from chess_autoplayer.board.state import GameState, StateError


def make_snapshot(
    moves: list[str],
    pieces: list[PieceInfo] | None = None,
    flipped_geometry: bool = False,
    flipped_class: bool = False,
    game_over: bool = False,
    game_over_text: str | None = None,
) -> Snapshot:
    """Helper to construct a typed Snapshot."""
    if pieces is None:
        # Generate pieces from moves by playing on standard board
        b = chess.Board()
        for m in moves:
            b.push_san(m)
        pieces = []
        for sq in chess.SQUARES:
            p = b.piece_at(sq)
            if p:
                color_str = "w" if p.color == chess.WHITE else "b"
                pieces.append(
                    PieceInfo(
                        color=color_str,
                        type=p.symbol().lower(),
                        square=chess.square_name(sq),
                    )
                )

    return Snapshot(
        url="https://www.chess.com/play/computer",
        found=True,
        board_rect=Rect(0.0, 0.0, 400.0, 400.0),
        flipped_class=flipped_class,
        flipped_geometry=flipped_geometry,
        pieces=pieces,
        moves=moves,
        last_move_highlights=[],
        game_over=game_over,
        game_over_text=game_over_text,
        promotion_open=False,
        device_pixel_ratio=1.0,
        window=WindowInfo(0, 0, 1000, 800, 1000, 800),
        dragging=False,
    )


def test_state_reconstruction_from_moves_white() -> None:
    moves = ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6"]
    snap = make_snapshot(moves=moves, flipped_geometry=False)
    state = GameState.from_snapshot(snap)

    assert state.source == "moves"
    assert state.our_color == chess.WHITE
    assert state.turn == chess.WHITE
    assert state.is_our_turn is True
    assert state.ply == 6
    assert state.last_move == chess.Move.from_uci("a7a6")
    assert state.is_game_over is False


def test_state_reconstruction_black_flipped() -> None:
    moves = ["d4", "d5", "c4"]
    snap = make_snapshot(moves=moves, flipped_geometry=True, flipped_class=True)
    state = GameState.from_snapshot(snap)

    assert state.source == "moves"
    assert state.our_color == chess.BLACK
    assert state.turn == chess.BLACK
    assert state.is_our_turn is True
    assert state.ply == 3
    assert state.last_move == chess.Move.from_uci("c2c4")


def test_state_castling_both_sides() -> None:
    moves = ["e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5", "O-O", "Nf6", "d3", "O-O"]
    snap = make_snapshot(moves=moves)
    state = GameState.from_snapshot(snap)

    assert state.source == "moves"
    assert state.ply == 10
    # Both kings castled kingside
    assert state.board.piece_at(chess.G1) == chess.Piece(chess.KING, chess.WHITE)
    assert state.board.piece_at(chess.G8) == chess.Piece(chess.KING, chess.BLACK)


def test_state_en_passant() -> None:
    moves = ["e4", "a6", "e5", "d5", "exd6"]
    snap = make_snapshot(moves=moves)
    state = GameState.from_snapshot(snap)

    assert state.source == "moves"
    assert state.ply == 5
    assert state.board.piece_at(chess.D6) == chess.Piece(chess.PAWN, chess.WHITE)
    assert state.board.piece_at(chess.D5) is None


def test_state_pawn_promotion() -> None:
    # Play moves leading to promotion
    moves = ["a4", "b5", "axb5", "a6", "bxa6", "Bb7", "axb7", "e6", "bxa8=Q"]
    snap = make_snapshot(moves=moves)
    state = GameState.from_snapshot(snap)

    assert state.source == "moves"
    assert state.board.piece_at(chess.A8) == chess.Piece(chess.QUEEN, chess.WHITE)


def test_state_figurine_converted_san() -> None:
    # Simulates SAN strings produced after [data-figurine] replacement
    moves = [
        "e4",
        "e5",
        "Nf3",
        "Nc6",
        "Bb5",
        "a6",
        "Bxc6",
        "dxc6",
        "O-O",
        "f6",
        "d4",
        "exd4",
        "Qxd4",
        "Qxd4",
        "Nxd4",
    ]
    snap = make_snapshot(moves=moves)
    state = GameState.from_snapshot(snap)

    assert state.source == "moves"
    assert state.ply == 15
    assert state.turn == chess.BLACK
    assert state.board.piece_at(chess.D4) == chess.Piece(chess.KNIGHT, chess.WHITE)


def test_state_disagreement_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    snap = make_snapshot(moves=["e4"], flipped_geometry=True, flipped_class=False)
    state = GameState.from_snapshot(snap)
    assert state.our_color == chess.BLACK
    assert "disagrees" in caplog.text


def test_state_mismatch_falls_back_to_pieces(caplog: pytest.LogCaptureFixture) -> None:
    # Corrupt moves list so SAN replay differs from piece layout
    moves = ["e4", "e5"]  # moves say 1. e4 e5
    # But piece layout has 1. d4 d5
    b_alt = chess.Board()
    b_alt.push_san("d4")
    b_alt.push_san("d5")
    pieces = []
    for sq in chess.SQUARES:
        p = b_alt.piece_at(sq)
        if p:
            pieces.append(
                PieceInfo(
                    color="w" if p.color == chess.WHITE else "b",
                    type=p.symbol().lower(),
                    square=chess.square_name(sq),
                )
            )

    snap = make_snapshot(moves=moves, pieces=pieces)
    state = GameState.from_snapshot(snap)

    assert state.source == "pieces"
    assert "fallback" in caplog.text
    # Reconstructed board has d4 and d5
    assert state.board.piece_at(chess.D4) == chess.Piece(chess.PAWN, chess.WHITE)
    assert state.board.piece_at(chess.D5) == chess.Piece(chess.PAWN, chess.BLACK)
    assert state.turn == chess.WHITE  # len(moves) == 2 (even -> white to move)


def test_state_invalid_board_raises_state_error() -> None:
    # Two white kings and no black king -> invalid
    pieces = [
        PieceInfo(color="w", type="k", square="e1"),
        PieceInfo(color="w", type="k", square="e2"),
    ]
    snap = make_snapshot(moves=["e4"], pieces=pieces)
    with pytest.raises(StateError, match="invalid"):
        GameState.from_snapshot(snap)


def test_state_board_not_found_raises_state_error() -> None:
    snap = Snapshot(
        url="https://www.chess.com/play/computer",
        found=False,
        board_rect=Rect(0, 0, 0, 0),
        flipped_class=False,
        flipped_geometry=False,
        pieces=[],
        moves=[],
        last_move_highlights=[],
        game_over=False,
        game_over_text=None,
        promotion_open=False,
        device_pixel_ratio=1.0,
        window=WindowInfo(0, 0, 0, 0, 0, 0),
        dragging=False,
    )
    with pytest.raises(StateError, match="No board found"):
        GameState.from_snapshot(snap)
