"""Reconstruct full chess board state from DOM snapshot with validation and fallbacks."""

import logging

import chess

from chess_autoplayer.board.snapshot import Snapshot

logger = logging.getLogger(__name__)


class StateError(Exception):
    """Raised when game state cannot be reconstructed or board is invalid."""


class GameState:
    """Reconstructed game state with chess.Board and fair-play metadata."""

    def __init__(
        self,
        board: chess.Board,
        snapshot: Snapshot,
        our_color: chess.Color,
        source: str,
    ) -> None:
        self.board: chess.Board = board
        self.snapshot: Snapshot = snapshot
        self.our_color: chess.Color = our_color
        self.source: str = source  # "moves" or "pieces"

    @classmethod
    def from_snapshot(cls, snapshot: Snapshot, play_as: str = "auto") -> "GameState":
        """Reconstruct GameState from a typed Snapshot."""
        if not snapshot.found:
            raise StateError("No board found on page")

        # Determine our color: play_as override > our_color_hint > flipped_geometry
        if play_as == "white":
            our_color = chess.WHITE
        elif play_as == "black":
            our_color = chess.BLACK
        elif snapshot.our_color_hint == "w":
            our_color = chess.WHITE
        elif snapshot.our_color_hint == "b":
            our_color = chess.BLACK
        else:
            if snapshot.flipped_geometry != snapshot.flipped_class:
                logger.warning(
                    "Flipped geometry (%s) disagrees with flipped class (%s)",
                    snapshot.flipped_geometry,
                    snapshot.flipped_class,
                )
            our_color = chess.BLACK if snapshot.flipped_geometry else chess.WHITE

        # Convert snapshot pieces to dictionary: square_int -> chess.Piece
        dom_pieces: dict[int, chess.Piece] = {}
        for p in snapshot.pieces:
            sq = chess.parse_square(p.square)
            color = chess.WHITE if p.color == "w" else chess.BLACK
            piece_type = chess.PIECE_SYMBOLS.index(p.type)
            dom_pieces[sq] = chess.Piece(piece_type, color)

        # 1. Try replay from moves list
        board = chess.Board()
        moves_valid = True
        try:
            for san in snapshot.moves:
                board.push_san(san)
        except (ValueError, chess.IllegalMoveError, chess.InvalidMoveError) as exc:
            logger.warning("SAN move playback failed: %s", exc)
            moves_valid = False

        if moves_valid and cls._pieces_match(board, dom_pieces):
            return cls(board=board, snapshot=snapshot, our_color=our_color, source="moves")

        # 2. Fallback: reconstruct from DOM pieces
        logger.warning(
            "Board pieces from moves replay do not match DOM pieces; "
            "falling back to piece layout reconstruction (fallback)."
        )
        fallback_board = cls._build_from_dom_pieces(dom_pieces, move_count=len(snapshot.moves))
        return cls(board=fallback_board, snapshot=snapshot, our_color=our_color, source="pieces")

    @staticmethod
    def _pieces_match(board: chess.Board, dom_pieces: dict[int, chess.Piece]) -> bool:
        """Check if board piece placement exactly matches DOM pieces."""
        board_pieces = board.piece_map()
        if len(board_pieces) != len(dom_pieces):
            return False
        for sq, piece in dom_pieces.items():
            if board_pieces.get(sq) != piece:
                return False
        return True

    @staticmethod
    def _build_from_dom_pieces(dom_pieces: dict[int, chess.Piece], move_count: int) -> chess.Board:
        """Construct a valid chess.Board directly from piece placement."""
        board = chess.Board(None)  # empty board
        for sq, piece in dom_pieces.items():
            board.set_piece_at(sq, piece)

        # Set turn: white if move count is even, black if odd
        board.turn = chess.WHITE if (move_count % 2 == 0) else chess.BLACK

        # Infer castling rights from king and rook positions on starting squares
        board.castling_rights = chess.BB_EMPTY
        if board.piece_at(chess.E1) == chess.Piece(chess.KING, chess.WHITE):
            if board.piece_at(chess.H1) == chess.Piece(chess.ROOK, chess.WHITE):
                board.castling_rights |= chess.BB_H1
            if board.piece_at(chess.A1) == chess.Piece(chess.ROOK, chess.WHITE):
                board.castling_rights |= chess.BB_A1

        if board.piece_at(chess.E8) == chess.Piece(chess.KING, chess.BLACK):
            if board.piece_at(chess.H8) == chess.Piece(chess.ROOK, chess.BLACK):
                board.castling_rights |= chess.BB_H8
            if board.piece_at(chess.A8) == chess.Piece(chess.ROOK, chess.BLACK):
                board.castling_rights |= chess.BB_A8

        board.ep_square = None

        status = board.status()
        if status != chess.STATUS_VALID:
            raise StateError(
                f"Reconstructed board state from DOM pieces is invalid (status code: {status})"
            )

        return board

    @property
    def fen(self) -> str:
        """Current FEN string of the position."""
        return self.board.fen()

    @property
    def turn(self) -> chess.Color:
        """Whose turn it is to move."""
        return self.board.turn

    @property
    def is_our_turn(self) -> bool:
        """True if it is the autoplayer's turn to move."""
        return self.turn == self.our_color

    @property
    def is_game_over(self) -> bool:
        """True if the game has concluded according to DOM or board rules."""
        return bool(self.snapshot.game_over or self.board.is_game_over())

    @property
    def ply(self) -> int:
        """Total number of half-moves played."""
        if self.board.move_stack:
            return len(self.board.move_stack)
        return len(self.snapshot.moves)

    @property
    def last_move(self) -> chess.Move | None:
        """The last move played in the game, if any."""
        if self.board.move_stack:
            return self.board.peek()
        return None
