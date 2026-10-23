"""Stockfish engine wrapper with strength profiles and MultiPV analysis."""

import logging
import os
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chess
import chess.engine

from chess_autoplayer.engine.book import get_book_lines
from chess_autoplayer.engine.profiles import Profile, get_profile

logger = logging.getLogger(__name__)


class EngineError(Exception):
    """Base exception for chess engine errors."""


class EngineNotFoundError(EngineError):
    """Raised when Stockfish binary is missing or not executable."""


@dataclass(frozen=True)
class Line:
    """MultiPV candidate evaluation line."""

    move: chess.Move
    score_cp: int  # Centipawn score from moving player's POV (higher = better)
    mate_score: int | None  # Distance to mate (positive = winning, negative = losing)
    pv: list[chess.Move]


def map_engine_score(score: chess.engine.PovScore, turn: chess.Color) -> tuple[int, int | None]:
    """Map python-chess PovScore to centipawns (from moving player's POV) and mate distance."""
    pov = score.pov(turn)
    if pov.is_mate():
        mate_dist = pov.mate()
        assert mate_dist is not None
        # Map mate to high centipawn value: ±100,000 minus distance
        if mate_dist > 0:
            score_cp = 100000 - mate_dist * 10
        else:
            score_cp = -100000 - mate_dist * 10
        return score_cp, mate_dist

    cp = pov.score()
    return cp if cp is not None else 0, None


class Engine:
    """Wrapper around Stockfish UCI engine."""

    def __init__(
        self,
        stockfish_path: Path | str,
        profile: Profile | str = "club",
        rng: random.Random | None = None,
    ) -> None:
        self.path = Path(stockfish_path).expanduser().resolve()
        self.profile = get_profile(profile) if isinstance(profile, str) else profile
        self.rng = rng if rng is not None else random.Random()
        self._engine: chess.engine.SimpleEngine | None = None

    def start(self) -> None:
        """Start the Stockfish UCI process and configure options."""
        if not self.path.is_file():
            raise EngineNotFoundError(
                f"Stockfish binary not found at {self.path}. "
                "Please verify stockfish_path in config or install via 'brew install stockfish'."
            )
        if not os.access(self.path, os.X_OK):
            raise EngineNotFoundError(f"Stockfish binary at {self.path} is not executable.")

        try:
            self._engine = chess.engine.SimpleEngine.popen_uci(str(self.path))
            self._configure_engine()
        except Exception as exc:
            self.close()
            raise EngineError(f"Failed to start Stockfish process: {exc}") from exc

    def _configure_engine(self) -> None:
        """Apply strength, hash, and thread options to the running engine."""
        if self._engine is None:
            return

        options: dict[str, Any] = {}

        # Threads and Hash
        threads = min(4, os.cpu_count() or 1)
        if "Threads" in self._engine.options:
            options["Threads"] = threads
        if "Hash" in self._engine.options:
            options["Hash"] = 128

        # Strength limitation and Elo
        if "UCI_LimitStrength" in self._engine.options:
            options["UCI_LimitStrength"] = self.profile.limit_strength

        if self.profile.limit_strength and self.profile.elo is not None:
            if "UCI_Elo" in self._engine.options:
                elo_opt = self._engine.options["UCI_Elo"]
                min_elo = getattr(elo_opt, "min", 1320)
                max_elo = getattr(elo_opt, "max", 3190)
                clamped_elo = max(min_elo, min(max_elo, self.profile.elo))
                options["UCI_Elo"] = clamped_elo

        self._engine.configure(options)
        logger.debug("Configured Stockfish with profile %s: %s", self.profile.name, options)

    def set_profile(self, profile: Profile | str) -> None:
        """Update strength profile and reconfigure UCI options if engine is running."""
        self.profile = get_profile(profile) if isinstance(profile, str) else profile
        if self._engine is not None:
            self._configure_engine()

    def analyse(
        self,
        board: chess.Board,
        rng: random.Random | None = None,
        use_book: bool = True,
    ) -> list[Line]:
        r = rng if rng is not None else self.rng

        # NOTE: Opening book usage - انسان در حرکات آغازین از تئوری گشایش و حافظه استفاده می‌کند
        # و عمق انجین محاسبه نمی‌شود. این کار هم بار پردازشی را برمی‌دارد و هم الگوهای طبیعی گشایش انسانی ایجاد می‌کند.
        if use_book:
            book_lines = get_book_lines(board, rng=r)
            if book_lines:
                return book_lines

        if self._engine is None:
            self.start()

        for attempt in range(2):
            try:
                assert self._engine is not None
                # NOTE: Variable calculation depth (10-16 plies) - عمق محاسبه انسان در هر حرکت ثابت نیست
                # و بر اساس خستگی و پیچیدگی تغییر می‌کند. استفاده از عمق متغیر مانع از تشخیص اثر انگشت ثابت انجین می‌شود.
                chosen_depth = r.randint(10, 16)
                limit = chess.engine.Limit(depth=chosen_depth)
                infos = self._engine.analyse(
                    board,
                    limit,
                    multipv=min(self.profile.multipv, max(1, board.legal_moves.count())),
                )

                # Ensure infos is a list of InfoDicts (in multipv mode it is list[InfoDict])
                info_list: list[chess.engine.InfoDict]
                if isinstance(infos, dict):
                    info_list = [infos]
                else:
                    info_list = list(infos)

                lines: list[Line] = []
                for entry in info_list:
                    pv = entry.get("pv", [])
                    if not pv:
                        continue
                    move = pv[0]
                    score = entry.get("score")
                    if score is None:
                        continue
                    score_cp, mate_dist = map_engine_score(score, board.turn)
                    lines.append(
                        Line(
                            move=move,
                            score_cp=score_cp,
                            mate_score=mate_dist,
                            pv=list(pv),
                        )
                    )

                # Sort by score_cp descending (best move first)
                lines.sort(key=lambda x: x.score_cp, reverse=True)
                return lines

            except (chess.engine.EngineError, chess.engine.EngineTerminatedError, OSError) as exc:
                logger.warning("Stockfish encountered error during analysis: %s", exc)
                self.close()
                if attempt == 0:
                    logger.info("Restarting Stockfish engine and retrying analysis once...")
                    self.start()
                    continue
                raise EngineError(f"Stockfish analysis failed after restart: {exc}") from exc

        return []

    def close(self) -> None:
        """Idempotently terminate the Stockfish engine process."""
        if self._engine is not None:
            try:
                self._engine.quit()
            except Exception as exc:
                logger.debug("Error while quitting Stockfish: %s", exc)
            self._engine = None

    def __enter__(self) -> "Engine":
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
