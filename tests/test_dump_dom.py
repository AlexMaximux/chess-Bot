import json
from pathlib import Path
import sys
from typing import Any
from unittest.mock import AsyncMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import pytest
from websockets.asyncio.server import ServerConnection, serve

from chess_autoplayer.board.reader import get_reader_js
from chess_autoplayer.chrome.cdp import CDPClient
from tools.dump_dom import (
    extract_selectors_from_reader_js,
    run_inspector,
    _print_console_summary,
)


def test_extract_selectors_from_reader_js() -> None:
    code = get_reader_js()
    categories = extract_selectors_from_reader_js(code)

    assert "board_and_pieces" in categories
    assert "clocks" in categories
    assert "moves_and_notation" in categories
    assert "players_and_usernames" in categories
    assert "game_over_modals" in categories
    assert "game_over_buttons" in categories

    # Verify key selectors are present
    all_selectors = [s for sublist in categories.values() for s in sublist]
    assert "wc-chess-board" in all_selectors
    assert ".piece" in all_selectors
    assert any("clock" in s for s in categories["clocks"])
    assert any("user" in s or "player" in s for s in categories["players_and_usernames"])
    assert any("rematch" in s or "new-game" in s for s in categories["game_over_buttons"])
    assert any("game-over" in s for s in categories["game_over_modals"])


class MockCDPServerForDump:
    def __init__(self) -> None:
        self.url = ""
        self.session_id = "sess_dump_1"
        self.target_id = "target_chess_1"
        self._server: Any = None

    async def start(self) -> None:
        async def handler(websocket: ServerConnection) -> None:
            try:
                async for raw in websocket:
                    msg = json.loads(raw)
                    msg_id = msg.get("id")
                    method = msg.get("method")

                    if method == "Target.getTargets":
                        await websocket.send(
                            json.dumps(
                                {
                                    "id": msg_id,
                                    "result": {
                                        "targetInfos": [
                                            {
                                                "targetId": self.target_id,
                                                "type": "page",
                                                "url": "https://www.chess.com/game/live/1234567890",
                                                "title": "Chess Online Game",
                                            }
                                        ]
                                    },
                                }
                            )
                        )
                    elif method == "Target.attachToTarget":
                        await websocket.send(
                            json.dumps(
                                {"id": msg_id, "result": {"sessionId": self.session_id}}
                            )
                        )
                    elif method == "Page.enable":
                        await websocket.send(json.dumps({"id": msg_id, "result": {}}))
                    elif method == "Page.getFrameTree":
                        await websocket.send(
                            json.dumps(
                                {
                                    "id": msg_id,
                                    "result": {
                                        "frameTree": {
                                            "frame": {"id": "frame_1"},
                                            "childFrames": [],
                                        }
                                    },
                                }
                            )
                        )
                    elif method == "Page.createIsolatedWorld":
                        await websocket.send(
                            json.dumps(
                                {"id": msg_id, "result": {"executionContextId": 42}}
                            )
                        )
                    elif method == "Runtime.evaluate":
                        params = msg.get("params", {})
                        expr = params.get("expression", "")
                        val: Any = ""
                        if "outerHTML" in expr:
                            val = "<html><body><wc-chess-board></wc-chess-board></body></html>"
                        elif "selectors" in expr:
                            val = {
                                "wc-chess-board": {"found": True, "count": 1, "samples": [{"text": ""}]},
                                ".piece": {"found": False, "count": 0, "samples": []},
                            }
                        elif "clocks" in expr or "deep" in expr:
                            val = {
                                "clocks": {"top": {"found": True, "text": "2:54"}, "bottom": {"found": True, "text": "3:00"}},
                                "moves": {"found": True, "totalPlies": 2, "first5": [{"san": "e4"}, {"san": "e5"}]},
                                "players": {"top": {"username": "Hikaru"}, "bottom": {"username": "Magnus"}},
                                "gameOver": {"modalFound": False, "buttons": []},
                            }
                        else:
                            # reader.js return
                            val = {
                                "found": True,
                                "pieces": [],
                                "moves": ["e4", "e5"],
                                "clocks": {"white": {"seconds": 180.0, "text": "3:00"}, "black": {"seconds": 174.0, "text": "2:54"}},
                                "ourColorHint": "w",
                                "gameOver": False,
                                "gameOverButtons": [],
                            }
                        await websocket.send(
                            json.dumps(
                                {
                                    "id": msg_id,
                                    "result": {"result": {"value": val}},
                                }
                            )
                        )
                    else:
                        await websocket.send(json.dumps({"id": msg_id, "result": {}}))
            except Exception:
                pass

        self._server = await serve(handler, "127.0.0.1", 0)
        assert self._server is not None
        port = self._server.sockets[0].getsockname()[1]
        self.url = f"ws://127.0.0.1:{port}"


    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()


@pytest.mark.asyncio
async def test_run_inspector_creates_html_and_report(tmp_path: Path) -> None:
    server = MockCDPServerForDump()
    await server.start()

    try:
        with (
            patch("tools.dump_dom.get_browser_ws_url", new=AsyncMock(return_value=server.url)),
            patch("tools.dump_dom.PROJECT_ROOT", tmp_path),
        ):
            report = await run_inspector(port=9222, url_filter="chess.com")

            assert report["tab"]["targetId"] == "target_chess_1"
            assert "inspections" in report
            assert "reader_js_parsed_state" in report
            assert report["summary"]["total_selectors"] > 0

            # Verify files on disk
            html_file = tmp_path / "debug" / "page.html"
            report_file = tmp_path / "debug" / "report.json"
            assert html_file.is_file()
            assert report_file.is_file()

            content = html_file.read_text(encoding="utf-8")
            assert "wc-chess-board" in content

            json_data = json.loads(report_file.read_text(encoding="utf-8"))
            assert json_data["tab"]["title"] == "Chess Online Game"
    finally:
        await server.stop()
