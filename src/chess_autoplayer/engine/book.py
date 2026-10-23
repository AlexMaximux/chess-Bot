from __future__ import annotations

"""Opening book implementation for human-like repertoire recall.

Provides natural opening theory recall for the first 8 to 12 moves (up to 24 plies)
with diverse branching lines across all major chess openings (Ruy Lopez, Italian,
Sicilian, French, Caro-Kann, Queen's Gambit, King's Indian, Nimzo-Indian, London,
English, Reti).
"""

import math
import random
from typing import TYPE_CHECKING, NamedTuple

import chess

if TYPE_CHECKING:
    from chess_autoplayer.engine.stockfish import Line

MAX_BOOK_PLY = 24  # Up to 12 full moves (24 half-moves)


class BookMove(NamedTuple):
    uci: str
    weight: float
    score_cp: int


_VARIATIONS: list[tuple[list[str], float]] = [
    # 1. Ruy Lopez Main Line
    (
        [
            "e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Ba4", "Nf6", "O-O", "Be7",
            "Re1", "b5", "Bb3", "d6", "c3", "O-O", "h3", "Nb8", "d4", "Nbd7",
        ],
        100.0,
    ),
    # 2. Ruy Lopez Berlin
    (
        [
            "e4", "e5", "Nf3", "Nc6", "Bb5", "Nf6", "O-O", "Nxe4", "d4", "Nd6",
            "Bxc6", "dxc6", "dxe5", "Nf5", "Qxd8+", "Kxd8", "Nc3", "Ke8", "h3", "h5",
        ],
        70.0,
    ),
    # 3. Ruy Lopez Exchange
    (
        [
            "e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Bxc6", "dxc6", "O-O", "f6",
            "d4", "exd4", "Nxd4", "c5", "Nb3", "Qxd1", "Rxd1", "Bd6", "Be3", "b6",
        ],
        50.0,
    ),
    # 4. Italian Game Giuoco Piano
    (
        [
            "e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5", "c3", "Nf6", "d3", "d6",
            "O-O", "a6", "a4", "Ba7", "Re1", "O-O", "h3", "h6", "Nbd2", "Re8",
        ],
        90.0,
    ),
    # 5. Italian Two Knights
    (
        [
            "e4", "e5", "Nf3", "Nc6", "Bc4", "Nf6", "d3", "Be7", "O-O", "O-O",
            "Re1", "d6", "a4", "Kh8", "c3", "Ng8", "d4", "f5",
        ],
        60.0,
    ),
    # 6. Scotch Game
    (
        [
            "e4", "e5", "Nf3", "Nc6", "d4", "exd4", "Nxd4", "Nf6", "Nxc6", "bxc6",
            "e5", "Qe7", "Qe2", "Nd5", "c4", "Ba6", "b3", "g6", "f4", "Bg7",
        ],
        60.0,
    ),
    # 7. Sicilian Najdorf
    (
        [
            "e4", "c5", "Nf3", "d6", "d4", "cxd4", "Nxd4", "Nf6", "Nc3", "a6",
            "Be3", "e5", "Nb3", "Be6", "f3", "Be7", "Qd2", "O-O", "O-O-O", "Nbd7",
        ],
        100.0,
    ),
    # 8. Sicilian Dragon
    (
        [
            "e4", "c5", "Nf3", "d6", "d4", "cxd4", "Nxd4", "Nf6", "Nc3", "g6",
            "Be3", "Bg7", "f3", "O-O", "Qd2", "Nc6", "Bc4", "Bd7", "O-O-O", "Rc8",
        ],
        70.0,
    ),
    # 9. Sicilian Sveshnikov
    (
        [
            "e4", "c5", "Nf3", "Nc6", "d4", "cxd4", "Nxd4", "Nf6", "Nc3", "e5",
            "Ndb5", "d6", "Bg5", "a6", "Na3", "b5", "Nd5", "Be7", "Bxf6", "Bxf6",
        ],
        70.0,
    ),
    # 10. Sicilian Kan
    (
        [
            "e4", "c5", "Nf3", "e6", "d4", "cxd4", "Nxd4", "a6", "Bd3", "Nf6",
            "O-O", "Qc7", "Qe2", "d6", "c4", "g6", "Nc3", "Bg7", "Nf3", "O-O",
        ],
        50.0,
    ),
    # 11. Sicilian Alapin
    (
        [
            "e4", "c5", "c3", "Nf6", "e5", "Nd5", "d4", "cxd4", "Nf3", "e6",
            "cxd4", "d6", "Bc4", "Nc6", "O-O", "Be7", "Qe2", "O-O", "Rd1", "Bd7",
        ],
        50.0,
    ),
    # 12. French Winawer
    (
        [
            "e4", "e6", "d4", "d5", "Nc3", "Bb4", "e5", "c5", "a3", "Bxc3+",
            "bxc3", "Ne7", "Qg4", "O-O", "Bd3", "Nbc6", "Qh5", "Ng6", "Nf3", "Qc7",
        ],
        70.0,
    ),
    # 13. French Classical
    (
        [
            "e4", "e6", "d4", "d5", "Nc3", "Nf6", "e5", "Nfd7", "f4", "c5",
            "Nf3", "Nc6", "Be3", "a6", "Qd2", "b5", "a3", "Qb6", "Ne2", "c4",
        ],
        60.0,
    ),
    # 14. French Tarrasch
    (
        [
            "e4", "e6", "d4", "d5", "Nd2", "Nf6", "e5", "Nfd7", "Bd3", "c5",
            "c3", "Nc6", "Ne2", "cxd4", "cxd4", "f6", "exf6", "Nxf6", "Nf3", "Bd6",
        ],
        60.0,
    ),
    # 15. Caro-Kann Classical
    (
        [
            "e4", "c6", "d4", "d5", "Nc3", "dxe4", "Nxe4", "Bf5", "Ng3", "Bg6",
            "h4", "h6", "Nf3", "Nd7", "h5", "Bh7", "Bd3", "Bxd3", "Qxd3", "e6",
        ],
        80.0,
    ),
    # 16. Caro-Kann Advance
    (
        [
            "e4", "c6", "d4", "d5", "e5", "Bf5", "Nf3", "e6", "Be2", "c5",
            "Be3", "Qb6", "Nc3", "Nc6", "O-O", "Qxb2", "Qe1", "cxd4", "Bxd4", "Nxd4",
        ],
        60.0,
    ),
    # 17. QGD Classical
    (
        [
            "d4", "d5", "c4", "e6", "Nc3", "Nf6", "cxd5", "exd5", "Bg5", "c6",
            "e3", "Be7", "Bd3", "O-O", "Qc2", "Nbd7", "Nf3", "Re8", "O-O", "Nf8",
        ],
        80.0,
    ),
    # 18. QGD Tartakower
    (
        [
            "d4", "d5", "c4", "e6", "Nc3", "Nf6", "Nf3", "Be7", "Bg5", "h6",
            "Bh4", "O-O", "e3", "b6", "Bd3", "Bb7", "O-O", "Nbd7", "Qe2", "c5",
        ],
        70.0,
    ),
    # 19. Slav Main Line
    (
        [
            "d4", "d5", "c4", "c6", "Nf3", "Nf6", "Nc3", "dxc4", "a4", "Bf5",
            "e3", "e6", "Bxc4", "Bb4", "O-O", "O-O", "Qe2", "Nbd7", "e4", "Bg6",
        ],
        80.0,
    ),
    # 20. Queen's Gambit Accepted
    (
        [
            "d4", "d5", "c4", "dxc4", "Nf3", "Nf6", "e3", "e6", "Bxc4", "c5",
            "O-O", "a6", "Qe2", "b5", "Bb3", "Bb7", "Rd1", "Nbd7", "Nc3", "Qb8",
        ],
        60.0,
    ),
    # 21. King's Indian Classical
    (
        [
            "d4", "Nf6", "c4", "g6", "Nc3", "Bg7", "e4", "d6", "Nf3", "O-O",
            "Be2", "e5", "O-O", "Nc6", "d5", "Ne7", "Ne1", "Nd7", "Be3", "f5",
        ],
        90.0,
    ),
    # 22. Gruenfeld Exchange
    (
        [
            "d4", "Nf6", "c4", "g6", "Nc3", "d5", "cxd5", "Nxd5", "e4", "Nxc3",
            "bxc3", "Bg7", "Nf3", "c5", "Rb1", "O-O", "Be2", "cxd4", "cxd4", "Qa5+",
        ],
        70.0,
    ),
    # 23. Nimzo-Indian Rubinstein
    (
        [
            "d4", "Nf6", "c4", "e6", "Nc3", "Bb4", "e3", "O-O", "Bd3", "d5",
            "Nf3", "c5", "O-O", "dxc4", "Bxc4", "Nbd7", "Qe2", "b6", "Rd1", "cxd4",
        ],
        80.0,
    ),
    # 24. London System
    (
        [
            "d4", "d5", "Bf4", "Nf6", "e3", "c5", "c3", "Nc6", "Nd2", "e6",
            "Ngf3", "Bd6", "Bg3", "O-O", "Bd3", "b6", "Ne5", "Bb7", "f4", "Ne7",
        ],
        80.0,
    ),
    # 25. English Four Knights
    (
        [
            "c4", "e5", "Nc3", "Nf6", "Nf3", "Nc6", "g3", "d5", "cxd5", "Nxd5",
            "Bg2", "Nb6", "O-O", "Be7", "d3", "O-O", "a3", "Be6", "b4", "f6",
        ],
        70.0,
    ),
    # 26. Reti Opening
    (
        [
            "Nf3", "d5", "g3", "Nf6", "Bg2", "c6", "O-O", "Bf5", "d3", "e6",
            "Nbd2", "h6", "Qe1", "Be7", "e4", "Bh7", "b3", "O-O", "Bb2", "a5",
        ],
        60.0,
    ),
]


def _build_book_tree() -> dict[str, list[BookMove]]:
    """Compile variations into a position-keyed map with calibrated weights and scores."""
    raw_tree: dict[str, dict[str, float]] = {}

    for moves, weight in _VARIATIONS:
        b = chess.Board()
        for san in moves:
            epd = b.epd()
            try:
                mv = b.parse_san(san)
            except ValueError:
                break
            uci = mv.uci()
            if epd not in raw_tree:
                raw_tree[epd] = {}
            raw_tree[epd][uci] = raw_tree[epd].get(uci, 0.0) + weight
            b.push(mv)

    tree: dict[str, list[BookMove]] = {}
    for epd, move_weights in raw_tree.items():
        max_w = max(move_weights.values())
        bmoves: list[BookMove] = []
        for uci, w in sorted(move_weights.items(), key=lambda item: item[1], reverse=True):
            # Scale score_cp so softmax selection preserves relative book frequency
            # without exceeding max_cp_loss.
            rel_loss = min(35, int(round(12.0 * math.log(max_w / max(1.0, w)))))
            score_cp = 25 - rel_loss
            bmoves.append(BookMove(uci=uci, weight=w, score_cp=score_cp))
        tree[epd] = bmoves

    return tree


_BOOK_TREE = _build_book_tree()


def get_book_lines(board: chess.Board, rng: random.Random | None = None) -> list[Line]:
    """Retrieve opening book candidates if the position is a recognized opening position.

    Covers the first 8 to 12 moves (up to 24 plies) with varied candidate options.
    """
    if board.ply() >= MAX_BOOK_PLY:
        return []

    epd = board.epd()
    book_moves = _BOOK_TREE.get(epd)
    if not book_moves:
        return []

    # Filter to legally valid moves
    valid_entries: list[tuple[chess.Move, int, float]] = []
    for bm in book_moves:
        try:
            mv = chess.Move.from_uci(bm.uci)
            if mv in board.legal_moves:
                valid_entries.append((mv, bm.score_cp, bm.weight))
        except ValueError:
            continue

    if not valid_entries:
        return []

    from chess_autoplayer.engine.stockfish import Line

    lines: list[Line] = []
    for mv, score_cp, _ in valid_entries:
        lines.append(
            Line(
                move=mv,
                score_cp=score_cp,
                mate_score=None,
                pv=[mv],
            )
        )

    return lines
