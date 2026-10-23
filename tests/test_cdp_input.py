"""Tests for CDP-based mouse input execution and event sequences."""

from typing import Any

import chess
import pytest

from chess_autoplayer.board.snapshot import PromotionOption, Rect
from chess_autoplayer.input.base import MoveContext
from chess_autoplayer.input.cdp_input import CDPInput


class FakeCommander:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def send_command(
        self, method: str, params: dict[str, Any] | None = None, timeout: float = 10.0
    ) -> dict[str, Any]:
        if method == "Input.dispatchMouseEvent" and params is not None:
            self.events.append(params)
        return {}


@pytest.mark.asyncio
async def test_cdp_input_drag_event_sequence() -> None:
    commander = FakeCommander()
    cdp_input = CDPInput(commander)
    board_rect = Rect(x=100.0, y=100.0, width=800.0, height=800.0)

    ctx = MoveContext(board_rect=board_rect, flipped=False, style="drag")
    move = chess.Move.from_uci("e2e4")

    await cdp_input.perform_move(move, ctx)

    # Must have dispatched mouse events
    assert len(commander.events) > 10

    # First event must be mouseMoved (moving towards source)
    assert commander.events[0]["type"] == "mouseMoved"
    assert commander.events[0]["buttons"] == 0

    # Must contain a mousePressed with buttons=1
    pressed_events = [
        e
        for e in commander.events
        if e["type"] == "mousePressed" and e["button"] == "left" and e["buttons"] == 1
    ]
    assert len(pressed_events) == 1

    # While dragging, mouseMoved must have buttons=1
    drag_moves = [e for e in commander.events if e["type"] == "mouseMoved" and e["buttons"] == 1]
    assert len(drag_moves) >= 5

    # Final event must be mouseReleased with buttons=0
    released_events = [
        e
        for e in commander.events
        if e["type"] == "mouseReleased" and e["button"] == "left" and e["buttons"] == 0
    ]
    assert len(released_events) == 1
    assert commander.events[-1]["type"] == "mouseReleased"


@pytest.mark.asyncio
async def test_cdp_input_click_event_sequence() -> None:
    commander = FakeCommander()
    cdp_input = CDPInput(commander)
    board_rect = Rect(x=100.0, y=100.0, width=800.0, height=800.0)

    ctx = MoveContext(board_rect=board_rect, flipped=False, style="click")
    move = chess.Move.from_uci("g1f3")

    await cdp_input.perform_move(move, ctx)

    # In click style: source is clicked (press & release), then dest is clicked (press & release)
    presses = [e for e in commander.events if e["type"] == "mousePressed"]
    releases = [e for e in commander.events if e["type"] == "mouseReleased"]

    assert len(presses) == 2
    assert len(releases) == 2

    # In click style, intermediate mouse moves must NOT have buttons=1 held down
    drag_moves = [e for e in commander.events if e["type"] == "mouseMoved" and e["buttons"] == 1]
    assert len(drag_moves) == 0


@pytest.mark.asyncio
async def test_cdp_input_promotion_click() -> None:
    commander = FakeCommander()
    cdp_input = CDPInput(commander)

    promo_options = [
        PromotionOption(piece="q", rect=Rect(x=200.0, y=200.0, width=50.0, height=50.0)),
        PromotionOption(piece="n", rect=Rect(x=200.0, y=250.0, width=50.0, height=50.0)),
    ]

    clicked = await cdp_input.click_promotion("q", promo_options)
    assert clicked is True

    # Must have dispatched click on queen rect center (225, 225)
    last_press = [e for e in commander.events if e["type"] == "mousePressed"][-1]
    assert abs(last_press["x"] - 225.0) < 1.0
    assert abs(last_press["y"] - 225.0) < 1.0


@pytest.mark.asyncio
async def test_cdp_input_close_releases_button() -> None:
    commander = FakeCommander()
    cdp_input = CDPInput(commander)
    cdp_input._mouse_pressed = True
    cdp_input.last_pos = (300.0, 400.0)

    await cdp_input.close()
    assert cdp_input._mouse_pressed is False
    assert commander.events[-1]["type"] == "mouseReleased"
    assert commander.events[-1]["x"] == 300.0
