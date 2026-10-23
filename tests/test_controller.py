"""Tests for BotController async state machine using fake page, engine, and input."""

import asyncio
import time
from typing import Any
from unittest.mock import patch

import chess
import pytest

from chess_autoplayer.board.snapshot import PromotionOption
from chess_autoplayer.bot.controller import BotController, should_resign
from chess_autoplayer.bot.events import (
    BotEvent,
    BotState,
    ErrorEvent,
    GameOverEvent,
    MoveEvent,
    StatusEvent,
)
from chess_autoplayer.chrome.cdp import ConnectionLost
from chess_autoplayer.config import Settings
from chess_autoplayer.engine.stockfish import Line
from chess_autoplayer.input.base import MoveContext


def make_raw_snapshot(
    fen: str = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
    moves: list[str] | None = None,
    game_over: bool = False,
    game_over_text: str | None = None,
    promotion_open: bool = False,
    dragging: bool = False,
    our_color_hint: str | None = "w",
    game_over_buttons: list[dict[str, Any]] | None = None,
    clocks: dict[str, Any] | None = None,
    url: str = "https://www.chess.com/play/computer",
    has_start_button: bool = False,
    has_resign_button: bool = False,
    has_move_list: bool = False,
    start_game_button: dict[str, Any] | None = None,
) -> dict[str, Any]:
    b = chess.Board(fen)
    pieces: list[dict[str, str]] = []
    for sq in chess.SQUARES:
        p = b.piece_at(sq)
        if p is not None:
            c = "w" if p.color == chess.WHITE else "b"
            pieces.append({"color": c, "type": p.symbol().lower(), "square": chess.square_name(sq)})

    default_clocks = {
        "top": {"text": "3:00", "seconds": 180.0},
        "bottom": {"text": "3:00", "seconds": 180.0},
    }

    if has_start_button and start_game_button is None:
        start_game_button = {
            "text": "Play",
            "rect": {"x": 500.0, "y": 600.0, "width": 200.0, "height": 50.0},
        }

    return {
        "url": url,
        "found": True,
        "boardRect": {"x": 100.0, "y": 100.0, "width": 800.0, "height": 800.0},
        "flippedClass": False,
        "flippedGeometry": False,
        "pieces": pieces,
        "moves": moves if moves is not None else [],
        "lastMoveHighlights": [],
        "gameOver": game_over,
        "gameOverText": game_over_text,
        "gameOverButtons": game_over_buttons if game_over_buttons is not None else [],
        "promotionOpen": promotion_open,
        "promotionOptions": (
            [{"piece": "q", "rect": {"x": 200.0, "y": 200.0, "width": 50.0, "height": 50.0}}]
            if promotion_open
            else []
        ),
        "devicePixelRatio": 2.0,
        "window": {
            "screenX": 0.0,
            "screenY": 0.0,
            "outerWidth": 1200.0,
            "outerHeight": 900.0,
            "innerWidth": 1200.0,
            "innerHeight": 800.0,
        },
        "dragging": dragging,
        "ourColorHint": our_color_hint,
        "clocks": clocks if clocks is not None else default_clocks,
        "hasStartButton": has_start_button,
        "hasResignButton": has_resign_button,
        "hasMoveList": has_move_list,
        "startGameButton": start_game_button,
    }


class FakePage:
    def __init__(self, current_url: str = "https://www.chess.com/play/computer") -> None:
        self._url = current_url
        self.snapshots: list[Any] = []
        self._default_snapshot = make_raw_snapshot()
        self.evaluated_scripts: list[str] = []

    async def url(self) -> str:
        return self._url

    def set_url(self, u: str) -> None:
        self._url = u

    def set_default_snapshot(self, snap: dict[str, Any]) -> None:
        self._default_snapshot = snap

    async def evaluate_json(self, expression: str, timeout: float = 10.0) -> object:
        if self.snapshots:
            item = self.snapshots.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        return self._default_snapshot

    async def evaluate(self, expression: str, timeout: float = 10.0) -> object:
        self.evaluated_scripts.append(expression)
        return True

    async def bring_to_front(self) -> None:
        pass


class FakeEngine:
    def __init__(
        self,
        candidate_move: chess.Move | None = None,
        score_cp: int = 50,
        mate_score: int | None = None,
    ) -> None:
        self.candidate_move = candidate_move or chess.Move.from_uci("e2e4")
        self.score_cp = score_cp
        self.mate_score = mate_score
        self.analyse_count = 0
        self.profiles_set: list[str] = []

    def analyse(self, board: chess.Board) -> list[Line]:
        self.analyse_count += 1
        mv = self.candidate_move
        return [Line(move=mv, score_cp=self.score_cp, mate_score=self.mate_score, pv=[mv])]

    def set_profile(self, profile: str) -> None:
        self.profiles_set.append(profile)

    def start(self) -> None:
        pass

    def close(self) -> None:
        pass


class FakeInput:
    def __init__(self, on_move: Any = None) -> None:
        self.performed_moves: list[tuple[chess.Move, MoveContext]] = []
        self.clicked_promotions: list[tuple[str, list[PromotionOption]]] = []
        self.clicked_rects: list[Any] = []
        self.on_move = on_move

    async def perform_move(self, move: chess.Move, ctx: MoveContext) -> None:
        self.performed_moves.append((move, ctx))
        if self.on_move is not None:
            self.on_move()

    async def click_promotion(self, piece: str, options: list[PromotionOption]) -> bool:
        self.clicked_promotions.append((piece, options))
        return True

    async def click_rect(self, rect: Any, rng: Any = None) -> bool:
        self.clicked_rects.append(rect)
        return True

    async def close(self) -> None:
        pass


@pytest.mark.asyncio
async def test_blocked_url_prevents_moves() -> None:
    page = FakePage(current_url="https://www.chess.com/play/online")
    engine = FakeEngine()
    fake_input = FakeInput()
    events: list[BotEvent] = []

    controller = BotController(
        page=page,  # type: ignore[arg-type]
        engine=engine,  # type: ignore[arg-type]
        input_handler=fake_input,
        settings=Settings(mode="bot", speed=10.0),
        event_callback=events.append,
    )

    await controller.start()
    await asyncio.sleep(0.4)
    await controller.stop()

    assert controller.state == BotState.BLOCKED_URL or any(
        isinstance(e, StatusEvent) and e.state == BotState.BLOCKED_URL for e in events
    )
    assert len(fake_input.performed_moves) == 0


@pytest.mark.asyncio
async def test_stable_read_required_before_move() -> None:
    page = FakePage()
    # Initial startpos
    snap1 = make_raw_snapshot(fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
    snap_confirmed = make_raw_snapshot(
        fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
        moves=["e4"],
    )
    page.set_default_snapshot(snap1)

    # When fake_input executes move, the page updates to snap_confirmed
    fake_input = FakeInput(on_move=lambda: page.set_default_snapshot(snap_confirmed))
    engine = FakeEngine(candidate_move=chess.Move.from_uci("e2e4"))
    events: list[BotEvent] = []

    controller = BotController(
        page=page,  # type: ignore[arg-type]
        engine=engine,  # type: ignore[arg-type]
        input_handler=fake_input,
        settings=Settings(speed=20.0),  # very fast think time in test
        event_callback=events.append,
    )
    controller.verify_timeout = 0.5

    await controller.start()
    # Allow time for 2 stable reads and move execution + verification
    await asyncio.sleep(0.9)
    await controller.stop()

    # Must have performed e2e4
    assert len(fake_input.performed_moves) == 1
    assert fake_input.performed_moves[0][0] == chess.Move.from_uci("e2e4")

    # Must have confirmed move
    move_events = [e for e in events if isinstance(e, MoveEvent)]
    assert len(move_events) == 1
    assert move_events[0].by_bot is True


@pytest.mark.asyncio
async def test_position_change_during_thinking_abandons_move() -> None:
    page = FakePage()
    # Snap 1 & 2: Stable startpos
    snap1 = make_raw_snapshot()
    snap2 = make_raw_snapshot()
    # Snap 3: During thinking, position changes unexpectedly (e.g. user resets)
    snap3 = make_raw_snapshot(fen="rnbqkbnr/pppppppp/8/8/8/4P3/PPPP1PPP/RNBQKBNR b KQkq - 0 1")
    page.snapshots = [snap1, snap2, snap3]

    engine = FakeEngine()
    fake_input = FakeInput()

    controller = BotController(
        page=page,  # type: ignore[arg-type]
        engine=engine,  # type: ignore[arg-type]
        input_handler=fake_input,
        settings=Settings(speed=0.5),  # longer think time so it polls while thinking
    )

    await controller.start()
    await asyncio.sleep(0.6)
    await controller.stop()

    # Because position changed while thinking, move must have been abandoned!
    assert len(fake_input.performed_moves) == 0


@pytest.mark.asyncio
async def test_verification_failure_retries_with_click_then_errors() -> None:
    page = FakePage()
    # 2 stable reads to trigger move
    s_start1 = make_raw_snapshot()
    s_start2 = make_raw_snapshot()
    # Verifying reads: move never registers, FEN stays startpos
    page.snapshots = [s_start1, s_start2]
    # Default snapshot is startpos, so verification will timeout after 3s

    engine = FakeEngine()
    fake_input = FakeInput()
    events: list[BotEvent] = []

    controller = BotController(
        page=page,  # type: ignore[arg-type]
        engine=engine,  # type: ignore[arg-type]
        input_handler=fake_input,
        settings=Settings(speed=50.0, move_style="drag"),
        event_callback=events.append,
    )
    controller.verify_timeout = 0.2

    await controller.start()
    # Wait for first attempt (~0.4s + 0.2s) + second attempt (~0.4s + 0.2s)
    await asyncio.sleep(1.8)
    await controller.stop()

    # Must have retried at least once with click style
    assert len(fake_input.performed_moves) >= 2
    assert fake_input.performed_moves[1][1].style == "click"

    # On second failure, should emit ErrorEvent
    error_events = [e for e in events if isinstance(e, ErrorEvent)]
    assert len(error_events) >= 1
    assert "failed to register" in error_events[0].message


@pytest.mark.asyncio
async def test_pause_resume_and_clean_stop() -> None:
    page = FakePage()
    engine = FakeEngine()
    fake_input = FakeInput()

    controller = BotController(
        page=page,  # type: ignore[arg-type]
        engine=engine,  # type: ignore[arg-type]
        input_handler=fake_input,
        settings=Settings(speed=10.0),
    )

    await controller.start()
    await asyncio.sleep(0.1)

    controller.pause()
    assert controller.state == BotState.PAUSED
    assert controller._paused is True

    controller.resume()
    assert controller._paused is False

    # Stop exits quickly
    t0 = asyncio.get_running_loop().time()
    await controller.stop()
    t1 = asyncio.get_running_loop().time()
    assert (t1 - t0) < 1.0
    assert controller.state == BotState.STOPPED


@pytest.mark.asyncio
async def test_game_over_waits_for_new_game() -> None:
    page = FakePage()
    # Snap 1: Game over modal active
    s_over = make_raw_snapshot(game_over=True, game_over_text="Checkmate - Black wins")
    page.snapshots = [s_over]

    engine = FakeEngine()
    fake_input = FakeInput()
    events: list[BotEvent] = []

    controller = BotController(
        page=page,  # type: ignore[arg-type]
        engine=engine,  # type: ignore[arg-type]
        input_handler=fake_input,
        settings=Settings(speed=10.0),
        event_callback=events.append,
    )

    await controller.start()
    await asyncio.sleep(0.3)
    await controller.stop()

    assert any(isinstance(e, GameOverEvent) and "Checkmate" in e.text for e in events)
    assert len(fake_input.performed_moves) == 0


@pytest.mark.asyncio
async def test_promotion_picker_clicked_during_verification() -> None:
    page = FakePage()
    # Pawn on e7 ready to promote:
    # 7k/4P3/8/8/8/8/8/6K1 w - - 0 1
    s_pre = make_raw_snapshot(fen="7k/4P3/8/8/8/8/8/6K1 w - - 0 1")
    s_promo_open = make_raw_snapshot(
        fen="7k/4P3/8/8/8/8/8/6K1 w - - 0 1",
        promotion_open=True,
    )
    s_confirmed = make_raw_snapshot(
        fen="4Q2k/8/8/8/8/8/8/6K1 b - - 0 1",
        moves=["e8=Q"],
    )

    page.set_default_snapshot(s_pre)

    def on_move() -> None:
        # After move drops on e8, page opens promotion picker then confirms move
        page.snapshots = [s_promo_open, s_confirmed]

    engine = FakeEngine(candidate_move=chess.Move.from_uci("e7e8q"))
    fake_input = FakeInput(on_move=on_move)
    events: list[BotEvent] = []

    controller = BotController(
        page=page,  # type: ignore[arg-type]
        engine=engine,  # type: ignore[arg-type]
        input_handler=fake_input,
        settings=Settings(speed=20.0),
        event_callback=events.append,
    )
    controller.verify_timeout = 1.0
    controller.pieces_fallback_wait = 0.0

    await controller.start()
    await asyncio.sleep(1.2)
    await controller.stop()

    # Move e7e8q performed
    assert len(fake_input.performed_moves) == 1
    assert fake_input.performed_moves[0][0] == chess.Move.from_uci("e7e8q")

    # click_promotion must have been called for 'q'
    assert len(fake_input.clicked_promotions) >= 1
    assert fake_input.clicked_promotions[0][0] == "q"


@pytest.mark.asyncio
async def test_game_over_latch_persists_when_modal_closed_until_new_game() -> None:
    page = FakePage()
    # Snap 1: Checkmate position with game over modal open
    mate_fen = "r1bqkb1r/pppp1Qpp/2n5/4p3/2B1n3/8/PPPP1PPP/RNB1K1NR b KQkq - 0 4"
    moves = ["e4", "e5", "Qh5", "Nc6", "Bc4", "Nf6", "Qxf7#"]
    s_over = make_raw_snapshot(
        fen=mate_fen,
        moves=moves,
        game_over=True,
        game_over_text="Checkmate - White wins",
        our_color_hint="b",
    )
    # Snap 2: Modal closed, but board still at final position
    s_modal_closed = make_raw_snapshot(
        fen=mate_fen,
        moves=moves,
        game_over=False,
        game_over_text=None,
        our_color_hint="b",
    )
    # Snap 3 & 4: New game begins
    s_new_1 = make_raw_snapshot(moves=[], our_color_hint="w")
    s_new_2 = make_raw_snapshot(moves=[], our_color_hint="w")
    # Snap 5: Verified move
    s_moved = make_raw_snapshot(
        fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
        moves=["e4"],
        our_color_hint="w",
    )

    page.snapshots = [s_over, s_modal_closed, s_new_1, s_new_2]
    fake_input = FakeInput(on_move=lambda: page.set_default_snapshot(s_moved))
    engine = FakeEngine(candidate_move=chess.Move.from_uci("e2e4"))
    events: list[BotEvent] = []

    controller = BotController(
        page=page,  # type: ignore[arg-type]
        engine=engine,  # type: ignore[arg-type]
        input_handler=fake_input,
        settings=Settings(speed=20.0),
        event_callback=events.append,
    )
    controller.verify_timeout = 0.5

    await controller.start()
    # Step 1: Let it process s_over and s_modal_closed
    await asyncio.sleep(0.5)
    assert controller.state == BotState.GAME_OVER
    assert len(fake_input.performed_moves) == 0

    # Step 2: Let it process new game snapshots and play
    for _ in range(30):
        if len(fake_input.performed_moves) >= 1:
            break
        await asyncio.sleep(0.1)
    await controller.stop()

    assert len(fake_input.performed_moves) == 1
    assert fake_input.performed_moves[0][0] == chess.Move.from_uci("e2e4")


@pytest.mark.asyncio
async def test_url_change_during_thinking_transitions_to_blocked_url() -> None:
    page = FakePage()
    # Snap 1 & 2: Stable startpos
    snap1 = make_raw_snapshot()
    snap2 = make_raw_snapshot()
    page.snapshots = [snap1, snap2]

    engine = FakeEngine()
    fake_input = FakeInput()
    events: list[BotEvent] = []

    controller = BotController(
        page=page,  # type: ignore[arg-type]
        engine=engine,  # type: ignore[arg-type]
        input_handler=fake_input,
        settings=Settings(mode="bot", speed=0.2),  # deliberate think wait
        event_callback=events.append,
    )

    await controller.start()
    # Wait until it enters THINKING
    await asyncio.sleep(0.4)
    # Change URL to blocked URL while bot is thinking
    page.set_url("https://www.chess.com/play/online")
    await asyncio.sleep(0.4)
    await controller.stop()

    assert controller.state == BotState.BLOCKED_URL or any(
        isinstance(e, StatusEvent) and e.state == BotState.BLOCKED_URL for e in events
    )
    assert len(fake_input.performed_moves) == 0


@pytest.mark.asyncio
async def test_human_mode_allows_online_and_live_urls() -> None:
    page = FakePage()
    page.set_url("https://www.chess.com/play/online")
    snap1 = make_raw_snapshot()
    snap2 = make_raw_snapshot()
    page.snapshots = [snap1, snap2]

    engine = FakeEngine(candidate_move=chess.Move.from_uci("e2e4"))
    fake_input = FakeInput()
    events: list[BotEvent] = []

    controller = BotController(
        page=page,  # type: ignore[arg-type]
        engine=engine,  # type: ignore[arg-type]
        input_handler=fake_input,
        settings=Settings(speed=20.0, mode="human"),
        event_callback=events.append,
    )

    await controller.start()
    for _ in range(20):
        if len(fake_input.performed_moves) >= 1:
            break
        await asyncio.sleep(0.1)
    await controller.stop()

    # Never entered BLOCKED_URL
    assert not any(isinstance(e, StatusEvent) and e.state == BotState.BLOCKED_URL for e in events)
    assert len(fake_input.performed_moves) == 1


@pytest.mark.asyncio
async def test_url_change_between_two_games_starts_new_game() -> None:
    page = FakePage()
    page.set_url("https://www.chess.com/game/live/111111")

    # Mate position on game 1
    mate_fen = "r1bqkb1r/pppp1Qpp/2n5/4p3/2B1n3/8/PPPP1PPP/RNB1K1NR b KQkq - 0 4"
    moves = ["e4", "e5", "Qh5", "Nc6", "Bc4", "Nf6", "Qxf7#"]
    s_over = make_raw_snapshot(
        fen=mate_fen,
        moves=moves,
        game_over=True,
        game_over_text="Checkmate - White wins",
        our_color_hint="b",
    )
    # Snap 2: New game starting on different URL
    s_new_1 = make_raw_snapshot(
        fen=chess.STARTING_BOARD_FEN, moves=[], game_over=False, our_color_hint="w"
    )
    s_new_2 = make_raw_snapshot(
        fen=chess.STARTING_BOARD_FEN, moves=[], game_over=False, our_color_hint="w"
    )
    s_moved = make_raw_snapshot(moves=["e4"])

    page.snapshots = [s_over, s_new_1, s_new_2]
    fake_input = FakeInput(on_move=lambda: page.set_default_snapshot(s_moved))
    engine = FakeEngine(candidate_move=chess.Move.from_uci("e2e4"))
    events: list[BotEvent] = []

    controller = BotController(
        page=page,  # type: ignore[arg-type]
        engine=engine,  # type: ignore[arg-type]
        input_handler=fake_input,
        settings=Settings(speed=20.0, mode="human"),
        event_callback=events.append,
    )
    controller.verify_timeout = 0.5

    await controller.start()
    # Process game over
    await asyncio.sleep(0.4)
    assert controller.state == BotState.GAME_OVER

    # Now URL changes to a new live game URL
    page.set_url("https://www.chess.com/game/live/222222")
    for _ in range(30):
        if len(fake_input.performed_moves) >= 1:
            break
        await asyncio.sleep(0.1)
    await controller.stop()

    assert len(fake_input.performed_moves) == 1
    assert fake_input.performed_moves[0][0] == chess.Move.from_uci("e2e4")


@pytest.mark.asyncio
async def test_reconnect_on_connection_lost() -> None:
    page1 = FakePage()
    # First call will raise ConnectionLost
    page1.snapshots = [ConnectionLost("socket closed by peer")]

    page2 = FakePage()
    s_start1 = make_raw_snapshot()
    s_start2 = make_raw_snapshot()
    s_moved = make_raw_snapshot(
        fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
        moves=["e4"],
    )
    page2.snapshots = [s_start1, s_start2]

    input2 = FakeInput(on_move=lambda: page2.set_default_snapshot(s_moved))
    reconnect_called = False

    async def fake_reconnect() -> tuple[Any, Any]:
        nonlocal reconnect_called
        reconnect_called = True
        return page2, input2

    engine = FakeEngine(candidate_move=chess.Move.from_uci("e2e4"))
    input1 = FakeInput()

    controller = BotController(
        page=page1,  # type: ignore[arg-type]
        engine=engine,  # type: ignore[arg-type]
        input_handler=input1,
        settings=Settings(speed=20.0),
        reconnect_factory=fake_reconnect,
    )
    controller.backoffs = [0.01, 0.02, 0.05, 0.1]
    controller.verify_timeout = 0.5

    await controller.start()
    # Wait for ConnectionLost -> fake_reconnect -> stable reads on page2 -> move
    await asyncio.sleep(1.2)
    await controller.stop()

    assert reconnect_called is True
    assert len(input2.performed_moves) == 1
    assert input2.performed_moves[0][0] == chess.Move.from_uci("e2e4")


@pytest.mark.asyncio
async def test_runtime_settings_validation_and_events() -> None:
    page = FakePage()
    engine = FakeEngine()
    fake_input = FakeInput()
    events: list[BotEvent] = []

    controller = BotController(
        page=page,  # type: ignore[arg-type]
        engine=engine,  # type: ignore[arg-type]
        input_handler=fake_input,
        settings=Settings(mode="bot", input_mode="cdp", strength="club", speed=1.0),
        event_callback=events.append,
    )

    # 1. Invalid strength emits ErrorEvent
    controller.set_strength("invalid_strength_profile")
    assert controller.strength == "club"
    assert any(
        isinstance(e, ErrorEvent) and "Unknown strength profile" in e.message for e in events
    )

    # 2. Speed clamping
    controller.set_speed(10.0)
    assert controller.speed == 5.0
    controller.set_speed(-2.0)
    assert controller.speed == 0.1

    # 3. OS mode without accessibility permissions
    with patch("chess_autoplayer.input.os_input.is_accessibility_trusted", return_value=False):
        controller.set_input_mode("os")
        assert controller._pending_input_mode is None
        assert controller._input_mode == "cdp"
        assert any(isinstance(e, ErrorEvent) and "Accessibility" in e.message for e in events)

    # 4. OS mode with accessibility permissions sets pending
    with patch("chess_autoplayer.input.os_input.is_accessibility_trusted", return_value=True):
        controller.set_input_mode("os")
        assert controller._pending_input_mode == "os"


@pytest.mark.asyncio
async def test_verification_opponent_quick_reply() -> None:
    page = FakePage()
    s_start1 = make_raw_snapshot()
    s_start2 = make_raw_snapshot()
    # During verification, opponent already answered: moves=["e4", "e5"] at ply 2
    s_replied = make_raw_snapshot(
        fen="rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2",
        moves=["e4", "e5"],
    )
    page.snapshots = [s_start1, s_start2]

    fake_input = FakeInput(on_move=lambda: page.set_default_snapshot(s_replied))
    engine = FakeEngine(candidate_move=chess.Move.from_uci("e2e4"))
    events: list[BotEvent] = []

    controller = BotController(
        page=page,  # type: ignore[arg-type]
        engine=engine,  # type: ignore[arg-type]
        input_handler=fake_input,
        settings=Settings(speed=20.0),
        event_callback=events.append,
    )
    controller.verify_timeout = 0.5

    await controller.start()
    await asyncio.sleep(0.8)
    await controller.stop()

    assert len(fake_input.performed_moves) == 1
    # Move must have been verified successfully
    move_events = [e for e in events if isinstance(e, MoveEvent) and e.by_bot]
    assert len(move_events) == 1
    assert move_events[0].san == "e4"
    # No error events
    assert not any(isinstance(e, ErrorEvent) for e in events)


@pytest.mark.asyncio
async def test_verification_retry_plays_same_move_with_click_no_extra_engine_call() -> None:
    page = FakePage()
    s_start1 = make_raw_snapshot()
    s_start2 = make_raw_snapshot()
    # First attempt: verification fails (snapshot returns s_start1)
    s_retry_success = make_raw_snapshot(
        fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
        moves=["e4"],
    )

    page.snapshots = [s_start1, s_start2]

    engine = FakeEngine(candidate_move=chess.Move.from_uci("e2e4"))

    move_count = 0

    def on_move() -> None:
        nonlocal move_count
        move_count += 1
        if move_count >= 2:
            page.set_default_snapshot(s_retry_success)

    fake_input = FakeInput(on_move=on_move)
    events: list[BotEvent] = []

    controller = BotController(
        page=page,  # type: ignore[arg-type]
        engine=engine,  # type: ignore[arg-type]
        input_handler=fake_input,
        settings=Settings(speed=50.0, move_style="drag"),
        event_callback=events.append,
    )
    controller.verify_timeout = 0.3

    await controller.start()
    await asyncio.sleep(1.2)
    await controller.stop()

    # Performed 2 moves: initial and retry
    assert len(fake_input.performed_moves) == 2
    # First move was drag (default)
    assert fake_input.performed_moves[0][1].style == "drag"
    # Second move was retry with click style
    assert fake_input.performed_moves[1][1].style == "click"
    # Same move UCI
    assert fake_input.performed_moves[1][0] == chess.Move.from_uci("e2e4")
    # Crucial: Engine was only called ONCE!
    assert engine.analyse_count == 1


@pytest.mark.asyncio
async def test_set_strength_during_search_applies_after_search() -> None:
    page = FakePage()
    s_start1 = make_raw_snapshot()
    s_start2 = make_raw_snapshot()
    page.snapshots = [s_start1, s_start2]

    in_analyse_event = asyncio.Event()
    release_analyse_event = asyncio.Event()

    class BlockingEngine(FakeEngine):
        def analyse(self, board: chess.Board) -> list[Line]:
            self.analyse_count += 1
            # Signal we are inside analyse
            in_analyse_event.set()
            # Wait until released
            while not release_analyse_event.is_set():
                time.sleep(0.01)
            mv = self.candidate_move
            return [Line(move=mv, score_cp=50, mate_score=None, pv=[mv])]

    engine = BlockingEngine()
    fake_input = FakeInput()
    events: list[BotEvent] = []

    controller = BotController(
        page=page,  # type: ignore[arg-type]
        engine=engine,  # type: ignore[arg-type]
        input_handler=fake_input,
        settings=Settings(strength="casual", speed=50.0),
        event_callback=events.append,
    )

    await controller.start()
    # Wait until engine.analyse is running in the worker thread
    await asyncio.wait_for(in_analyse_event.wait(), timeout=2.0)
    assert controller.state == BotState.THINKING
    assert controller._is_searching is True

    # Call set_strength while search is in progress
    controller.set_strength("club")
    assert controller.strength == "club"
    assert controller._pending_strength == "club"
    # Crucial: engine.set_profile("club") must NOT have been called yet!
    assert "club" not in engine.profiles_set

    # Release engine search
    release_analyse_event.set()
    # Wait briefly for search to finish and move to proceed
    await asyncio.sleep(0.3)
    await controller.stop()

    # Now engine.set_profile("club") MUST have been called after search
    assert "club" in engine.profiles_set


@pytest.mark.asyncio
async def test_resume_from_error_state() -> None:
    page = FakePage()
    engine = FakeEngine()
    fake_input = FakeInput()
    events: list[BotEvent] = []

    controller = BotController(
        page=page,  # type: ignore[arg-type]
        engine=engine,  # type: ignore[arg-type]
        input_handler=fake_input,
        settings=Settings(),
        event_callback=events.append,
    )

    # Force into error state
    controller._transition(BotState.ERROR, "Unexpected error occurred")
    controller._paused = True

    assert controller.state == BotState.ERROR
    assert controller.is_paused is True

    # Resuming from error transitions to IDLE and unpauses
    controller.resume()
    assert controller.is_paused is False
    assert controller.state == BotState.IDLE


@pytest.mark.asyncio
async def test_set_move_style_validation_and_next_move_application() -> None:
    page = FakePage()
    engine = FakeEngine()
    fake_input = FakeInput()
    events: list[BotEvent] = []

    controller = BotController(
        page=page,  # type: ignore[arg-type]
        engine=engine,  # type: ignore[arg-type]
        input_handler=fake_input,
        settings=Settings(move_style="drag", speed=50.0),
        event_callback=events.append,
    )

    # Invalid move style emits ErrorEvent
    controller.set_move_style("teleport")
    assert controller.move_style == "drag"
    assert controller._pending_move_style is None
    assert any(isinstance(e, ErrorEvent) and "Invalid move style" in e.message for e in events)

    # Valid move style sets pending style
    controller.set_move_style("click")
    assert controller._pending_move_style == "click"

    # Start loop and execute one move
    s_start1 = make_raw_snapshot()
    s_start2 = make_raw_snapshot()
    s_moved = make_raw_snapshot(moves=["e4"])
    page.snapshots = [s_start1, s_start2]
    fake_input.on_move = lambda: page.set_default_snapshot(s_moved)

    await controller.start()
    await asyncio.sleep(1.0)
    await controller.stop()

    assert controller.move_style == "click"
    assert len(fake_input.performed_moves) >= 1
    assert fake_input.performed_moves[0][1].style == "click"


@pytest.mark.asyncio
async def test_verification_rejects_unexpected_move_and_pauses() -> None:
    page = FakePage()
    s_start1 = make_raw_snapshot()
    s_start2 = make_raw_snapshot()
    # Bot intends e2e4, but a DIFFERENT move (d2d4) landed on the board!
    s_wrong_move = make_raw_snapshot(
        fen="rnbqkbnr/pppppppp/8/8/3P4/8/PPP1PPPP/RNBQKBNR b KQkq d3 0 1",
        moves=["d4"],
    )
    page.snapshots = [s_start1, s_start2]

    engine = FakeEngine(candidate_move=chess.Move.from_uci("e2e4"))
    fake_input = FakeInput(on_move=lambda: page.set_default_snapshot(s_wrong_move))
    events: list[BotEvent] = []

    controller = BotController(
        page=page,  # type: ignore[arg-type]
        engine=engine,  # type: ignore[arg-type]
        input_handler=fake_input,
        settings=Settings(speed=50.0),
        event_callback=events.append,
    )
    controller.verify_timeout = 0.5

    await controller.start()
    await asyncio.sleep(1.0)

    # Bot must have caught the unexpected move, emitted ErrorEvent, and paused!
    assert controller.state == BotState.ERROR
    assert controller.is_paused is True
    err_events = [e for e in events if isinstance(e, ErrorEvent)]
    assert len(err_events) >= 1
    assert "unexpected move landed: d2d4 (expected e4)" in err_events[0].message

    await controller.stop()


@pytest.mark.asyncio
async def test_reconnect_succeeds_on_final_attempt_does_not_error() -> None:
    page1 = FakePage()
    # 4 consecutive ConnectionLost errors
    page1.snapshots = [
        ConnectionLost("conn lost 1"),
        ConnectionLost("conn lost 2"),
        ConnectionLost("conn lost 3"),
        ConnectionLost("conn lost 4"),
    ]

    page2 = FakePage()
    s_good = make_raw_snapshot()
    page2.snapshots = [s_good]

    reconnect_attempts = 0

    async def fake_reconnect() -> tuple[Any, Any]:
        nonlocal reconnect_attempts
        reconnect_attempts += 1
        return page2, FakeInput()

    controller = BotController(
        page=page1,  # type: ignore[arg-type]
        engine=FakeEngine(),  # type: ignore[arg-type]
        input_handler=FakeInput(),
        settings=Settings(),
        reconnect_factory=fake_reconnect,
    )
    controller.backoffs = [0.01, 0.01, 0.01, 0.01]

    snap = await controller._fetch_snapshot_with_retry()

    assert snap is not None
    assert snap.found is True
    assert controller.state != BotState.ERROR
    assert controller.is_paused is False
    assert reconnect_attempts >= 1


@pytest.mark.asyncio
async def test_dynamic_live_game_id_does_not_reset_active_game() -> None:
    page = FakePage(current_url="https://www.chess.com/play/online")
    snap1 = make_raw_snapshot(fen=chess.STARTING_FEN, our_color_hint="b")
    page.set_default_snapshot(snap1)

    controller = BotController(
        page=page,  # type: ignore[arg-type]
        engine=FakeEngine(),  # type: ignore[arg-type]
        input_handler=FakeInput(),
        settings=Settings(mode="human"),
    )

    await controller.start()
    await asyncio.sleep(0.3)
    assert controller.state == BotState.OPPONENT_TURN
    assert controller._current_game_url == "https://www.chess.com/play/online"

    # Simulate dynamic assignment of game ID by chess.com (/play/online -> /game/live/98765)
    page.set_url("https://www.chess.com/game/live/98765")
    await asyncio.sleep(0.4)

    # Controller should recognize dynamic assignment without resetting per-game state
    assert controller._current_game_url == "https://www.chess.com/game/live/98765"
    assert controller.state == BotState.OPPONENT_TURN

    await controller.stop()


def test_url_transition_between_distinct_live_games() -> None:
    # 1. Matching/lobby to game is dynamic assignment (not new game reset)
    assert not BotController._is_new_game_url_transition(
        "https://www.chess.com/play/online", "https://www.chess.com/game/live/12345"
    )
    assert not BotController._is_new_game_url_transition(
        "https://www.chess.com/live", "https://www.chess.com/game/live/12345"
    )

    # 2. Distinct live games (/game/live/111 -> /game/live/222) is a new game
    assert BotController._is_new_game_url_transition(
        "https://www.chess.com/game/live/111", "https://www.chess.com/game/live/222"
    )

    # 3. Same game is not a transition
    assert not BotController._is_new_game_url_transition(
        "https://www.chess.com/game/live/111", "https://www.chess.com/game/live/111"
    )

    # 4. Leaving live game back to lobby is a new game
    assert BotController._is_new_game_url_transition(
        "https://www.chess.com/game/live/111", "https://www.chess.com/play/online"
    )


@pytest.mark.asyncio
async def test_game_over_auto_clicks_new_game_or_rematch() -> None:
    page = FakePage()
    fake_input = FakeInput()
    buttons = [
        {
            "type": "new_game",
            "text": "New 3 min",
            "rect": {"x": 200.0, "y": 300.0, "width": 120.0, "height": 40.0},
        }
    ]
    snap_over = make_raw_snapshot(
        fen="rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3",  # Fool's mate
        moves=["f3", "e5", "g4", "Qh4#"],
        game_over=True,
        game_over_text="Checkmate - Black wins",
        game_over_buttons=buttons,
    )
    page.set_default_snapshot(snap_over)

    controller = BotController(
        page=page,  # type: ignore[arg-type]
        engine=FakeEngine(),  # type: ignore[arg-type]
        input_handler=fake_input,
        settings=Settings(),
    )

    await controller.start()
    await asyncio.sleep(0.3)

    assert controller.state == BotState.GAME_OVER
    # Explicitly ensure not lingering and age game over time
    controller._stay_on_game_over = False
    controller._game_over_delay = 1.0
    controller._game_over_time = time.monotonic() - 2.0

    await asyncio.sleep(0.6)

    # Must have auto-clicked the new game button!
    assert controller._rematch_clicked is True
    assert len(fake_input.clicked_rects) >= 1
    assert fake_input.clicked_rects[0].x == 200.0

    await controller.stop()


@pytest.mark.asyncio
async def test_game_over_delay_and_lingering_behavior() -> None:
    page = FakePage()
    fake_input = FakeInput()
    buttons = [
        {
            "type": "new_game",
            "text": "New 3 min",
            "rect": {"x": 200.0, "y": 300.0, "width": 120.0, "height": 40.0},
        }
    ]
    snap_over = make_raw_snapshot(
        fen="rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3",
        moves=["f3", "e5", "g4", "Qh4#"],
        game_over=True,
        game_over_text="Checkmate - Black wins",
        game_over_buttons=buttons,
    )
    page.set_default_snapshot(snap_over)

    # Test 1: Delay is sampled between 1.0 and 3.0 seconds
    controller = BotController(
        page=page,  # type: ignore[arg-type]
        engine=FakeEngine(),  # type: ignore[arg-type]
        input_handler=fake_input,
        settings=Settings(),
    )
    await controller.start()
    await asyncio.sleep(0.3)

    assert controller.state == BotState.GAME_OVER
    assert 1.0 <= controller._game_over_delay <= 3.0

    # Test 2: Lingering behavior - when _stay_on_game_over is True, it never clicks New Game
    controller._stay_on_game_over = True
    controller._game_over_time = time.monotonic() - 10.0  # long past delay
    await asyncio.sleep(0.6)

    assert controller._rematch_clicked is False
    assert len(fake_input.clicked_rects) == 0

    await controller.stop()


def test_should_resign_conditions() -> None:
    # 1. Early game (ply < 24): never resign
    assert not should_resign(ply=10, eval_cp=-1500, clock_seconds=10.0)

    # 2. Untimed / no clock: never resign
    assert not should_resign(ply=30, eval_cp=-1500, clock_seconds=None)

    # 3. High clock (> 30s): never resign, play on
    assert not should_resign(ply=30, eval_cp=-1500, clock_seconds=45.0)

    # 4. Winning position with low clock: never resign
    assert not should_resign(ply=30, eval_cp=400, clock_seconds=15.0)

    # 5. Equal/slight disadvantage: never resign
    assert not should_resign(ply=30, eval_cp=-350, clock_seconds=15.0)

    # 6. Completely lost position (eval <= -800) and low clock (< 30s): RESIGN
    assert should_resign(ply=26, eval_cp=-800, clock_seconds=29.0)
    assert should_resign(ply=34, eval_cp=-1200, clock_seconds=12.0)

    # 7. Opponent forced mate (mate_score < 0) and low clock: RESIGN
    assert should_resign(ply=24, eval_cp=-300, mate_score=-2, clock_seconds=20.0)

    # 8. We have forced mate (mate_score > 0): never resign
    assert not should_resign(ply=24, eval_cp=10000, mate_score=2, clock_seconds=20.0)


@pytest.mark.asyncio
async def test_controller_resigns_when_lost_and_low_clock() -> None:
    page = FakePage()
    fake_input = FakeInput()
    events: list[BotEvent] = []

    # Position at ply 26 with low clock (15 seconds)
    clocks = {"white": {"seconds": 15.0, "text": "0:15"}, "black": {"seconds": 90.0, "text": "1:30"}}
    moves_history = [
        "e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Ba4", "Nf6", "O-O", "Be7",
        "Re1", "b5", "Bb3", "d6", "c3", "O-O", "h3", "Nb8", "d4", "Nbd7",
        "Nbd2", "Bb7", "Bc2", "Re8", "Nf1", "Bf8"
    ]
    # Fen where it is White's turn at ply 26
    fen_ply26 = "r2qrbk1/1bpn1ppp/p2p1n2/1p2p3/3PP3/2P2N1P/PPB2PP1/R1BQRNK1 w - - 7 14"
    snap = make_raw_snapshot(
        fen=fen_ply26,
        moves=moves_history,
        clocks=clocks,
        our_color_hint="w",
    )
    page.set_default_snapshot(snap)

    # Engine evaluates position as completely lost (-950 cp)
    engine = FakeEngine(candidate_move=chess.Move.from_uci("a2a4"), score_cp=-950)

    controller = BotController(
        page=page,  # type: ignore[arg-type]
        engine=engine,  # type: ignore[arg-type]
        input_handler=fake_input,
        settings=Settings(strength="club"),
        event_callback=events.append,
    )

    await controller.start()
    await asyncio.sleep(2.5)

    # Controller must have resigned!
    assert controller.state == BotState.GAME_OVER
    assert controller._game_over_latch is True

    # No board move should have been performed by input_handler
    assert len(fake_input.performed_moves) == 0

    # Must have emitted GameOverEvent with resignation text
    game_over_events = [e for e in events if isinstance(e, GameOverEvent)]
    assert len(game_over_events) >= 1
    assert "Resigned lost position" in game_over_events[0].text

    await controller.stop()


@pytest.mark.asyncio
async def test_controller_does_not_resign_when_eval_lost_but_clock_high() -> None:
    page = FakePage()
    fake_input = FakeInput()
    events: list[BotEvent] = []

    # Position at ply 26 with plenty of clock (120 seconds)
    clocks = {"white": {"seconds": 120.0, "text": "2:00"}, "black": {"seconds": 90.0, "text": "1:30"}}
    moves_history = [
        "e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Ba4", "Nf6", "O-O", "Be7",
        "Re1", "b5", "Bb3", "d6", "c3", "O-O", "h3", "Nb8", "d4", "Nbd7",
        "Nbd2", "Bb7", "Bc2", "Re8", "Nf1", "Bf8"
    ]
    fen_ply26 = "r2qrbk1/1bpn1ppp/p2p1n2/1p2p3/3PP3/2P2N1P/PPB2PP1/R1BQRNK1 w - - 7 14"
    snap = make_raw_snapshot(
        fen=fen_ply26,
        moves=moves_history,
        clocks=clocks,
        our_color_hint="w",
    )
    page.set_default_snapshot(snap)

    # Even though eval is -950 cp, high clock means bot fights on
    engine = FakeEngine(candidate_move=chess.Move.from_uci("a2a4"), score_cp=-950)

    controller = BotController(
        page=page,  # type: ignore[arg-type]
        engine=engine,  # type: ignore[arg-type]
        input_handler=fake_input,
        settings=Settings(strength="club"),
        event_callback=events.append,
    )

    await controller.start()
    await asyncio.sleep(1.5)

    # Must NOT be in GAME_OVER from resigning
    assert controller.state != BotState.GAME_OVER
    # Input handler should have attempted to perform the move
    assert len(fake_input.performed_moves) >= 1

    await controller.stop()


@pytest.mark.asyncio
async def test_controller_no_play_mode_does_not_execute_moves() -> None:
    page = FakePage()
    fake_input = FakeInput()
    events: list[BotEvent] = []

    controller = BotController(
        page=page,  # type: ignore[arg-type]
        engine=FakeEngine(),  # type: ignore[arg-type]
        input_handler=fake_input,
        settings=Settings(no_play=True),
        event_callback=events.append,
    )

    await controller.start()
    await asyncio.sleep(1.5)

    # In no-play mode, the bot monitors and thinks, but performs 0 moves on input_handler
    assert len(fake_input.performed_moves) == 0

    await controller.stop()


@pytest.mark.asyncio
async def test_online_mode_waits_in_lobby_when_no_clocks() -> None:
    page = FakePage(current_url="https://www.chess.com/play/online")
    # In the online lobby, chess.com renders a starting board with no active game clocks
    snap_lobby = make_raw_snapshot(
        url="https://www.chess.com/play/online",
        clocks={},
        has_start_button=True,
    )
    page.set_default_snapshot(snap_lobby)

    fake_input = FakeInput()
    controller = BotController(
        page=page,  # type: ignore[arg-type]
        engine=FakeEngine(),  # type: ignore[arg-type]
        input_handler=fake_input,
        settings=Settings(mode="human"),
    )

    await controller.start()
    await asyncio.sleep(0.3)
    # The bot must sit quietly in WAITING_FOR_GAME without playing e4
    assert controller.state == BotState.WAITING_FOR_GAME
    assert len(fake_input.performed_moves) == 0
    # The bot clicked the start game button to initiate queue
    assert len(fake_input.clicked_rects) >= 1

    # Once matchmaking finds an opponent, clocks become active and live controls appear
    snap_game = make_raw_snapshot(
        url="https://www.chess.com/play/online",
        clocks={
            "top": {"text": "3:00", "seconds": 180.0},
            "bottom": {"text": "3:00", "seconds": 180.0},
        },
        has_start_button=False,
        has_resign_button=True,
        has_move_list=True,
    )
    page.set_default_snapshot(snap_game)
    await asyncio.sleep(0.5)

    # Controller starts thinking/moving
    assert controller.state in (BotState.THINKING, BotState.MOVING, BotState.VERIFYING)

    await controller.stop()


@pytest.mark.asyncio
async def test_online_mode_lobby_no_play_does_not_click_start_game() -> None:
    page = FakePage(current_url="https://www.chess.com/play/online")
    snap_lobby = make_raw_snapshot(
        url="https://www.chess.com/play/online",
        clocks={},
        has_start_button=True,
    )
    page.set_default_snapshot(snap_lobby)

    fake_input = FakeInput()
    controller = BotController(
        page=page,  # type: ignore[arg-type]
        engine=FakeEngine(),  # type: ignore[arg-type]
        input_handler=fake_input,
        settings=Settings(mode="human", no_play=True),
    )

    await controller.start()
    await asyncio.sleep(0.3)
    assert controller.state == BotState.WAITING_FOR_GAME
    assert len(fake_input.performed_moves) == 0
    assert len(fake_input.clicked_rects) == 0

    await controller.stop()




