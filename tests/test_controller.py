"""Tests for BotController async state machine using fake page, engine, and input."""

import asyncio
from typing import Any
from unittest.mock import patch

import chess
import pytest

from chess_autoplayer.board.snapshot import PromotionOption
from chess_autoplayer.bot.controller import BotController
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
) -> dict[str, Any]:
    b = chess.Board(fen)
    pieces: list[dict[str, str]] = []
    for sq in chess.SQUARES:
        p = b.piece_at(sq)
        if p is not None:
            c = "w" if p.color == chess.WHITE else "b"
            pieces.append({"color": c, "type": p.symbol().lower(), "square": chess.square_name(sq)})

    return {
        "url": "https://www.chess.com/play/computer",
        "found": True,
        "boardRect": {"x": 100.0, "y": 100.0, "width": 800.0, "height": 800.0},
        "flippedClass": False,
        "flippedGeometry": False,
        "pieces": pieces,
        "moves": moves if moves is not None else [],
        "lastMoveHighlights": [],
        "gameOver": game_over,
        "gameOverText": game_over_text,
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
    }


class FakePage:
    def __init__(self, current_url: str = "https://www.chess.com/play/computer") -> None:
        self._url = current_url
        self.snapshots: list[dict[str, Any]] = []
        self._default_snapshot = make_raw_snapshot()

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

    async def bring_to_front(self) -> None:
        pass


class FakeEngine:
    def __init__(self, candidate_move: chess.Move | None = None) -> None:
        self.candidate_move = candidate_move or chess.Move.from_uci("e2e4")
        self.analyse_count = 0

    def analyse(self, board: chess.Board) -> list[Line]:
        self.analyse_count += 1
        mv = self.candidate_move
        return [Line(move=mv, score_cp=50, mate_score=None, pv=[mv])]

    def start(self) -> None:
        pass

    def close(self) -> None:
        pass


class FakeInput:
    def __init__(self, on_move: Any = None) -> None:
        self.performed_moves: list[tuple[chess.Move, MoveContext]] = []
        self.clicked_promotions: list[tuple[str, list[PromotionOption]]] = []
        self.on_move = on_move

    async def perform_move(self, move: chess.Move, ctx: MoveContext) -> None:
        self.performed_moves.append((move, ctx))
        if self.on_move is not None:
            self.on_move()

    async def click_promotion(self, piece: str, options: list[PromotionOption]) -> bool:
        self.clicked_promotions.append((piece, options))
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
        settings=Settings(speed=10.0),
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
    await asyncio.sleep(1.0)
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
        settings=Settings(speed=0.2),  # deliberate think wait
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
async def test_reconnect_on_connection_lost() -> None:
    page1 = FakePage()
    # First call will raise ConnectionLost
    page1.snapshots = [ConnectionLost("socket closed by peer")]  # type: ignore[list-item]

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
        settings=Settings(strength="club", speed=1.0),
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
