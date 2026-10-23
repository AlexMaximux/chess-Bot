"""Tests for ChessPage and isolated world execution."""

import asyncio
import json
from typing import Any

import pytest
from websockets.asyncio.server import ServerConnection, serve

from chess_autoplayer.chrome.cdp import CDPClient
from chess_autoplayer.chrome.page import ChessPage, EvaluationError, find_or_create_chess_tab


class FakePageCDPServer:
    def __init__(self) -> None:
        self.url = ""
        self.session_id = "session_page_1"
        self.target_id = "target_tab_1"
        self._server: Any = None
        self.eval_call_count = 0
        self.last_eval_context_id: int | None = None
        self.current_url: str = "https://www.chess.com/play/computer"
        self.navigated_urls: list[str] = []

    async def start(self) -> None:
        async def handler(websocket: ServerConnection) -> None:
            try:
                async for raw in websocket:
                    msg = json.loads(raw)
                    msg_id = msg.get("id")
                    method = msg.get("method")
                    params = msg.get("params", {})

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
                                                "url": "https://www.chess.com/play/computer",
                                                "title": "Play Computer",
                                            }
                                        ]
                                    },
                                }
                            )
                        )
                    elif method == "Target.attachToTarget":
                        await websocket.send(
                            json.dumps(
                                {
                                    "id": msg_id,
                                    "result": {"sessionId": self.session_id},
                                }
                            )
                        )
                    elif method == "Page.enable":
                        await websocket.send(json.dumps({"id": msg_id, "result": {}}))
                    elif method == "Page.navigate":
                        nav_url = params.get("url", "")
                        self.navigated_urls.append(nav_url)
                        self.current_url = nav_url
                        await websocket.send(json.dumps({"id": msg_id, "result": {}}))
                    elif method == "Page.getFrameTree":
                        await websocket.send(
                            json.dumps(
                                {
                                    "id": msg_id,
                                    "result": {
                                        "frameTree": {
                                            "frame": {"id": "frame_main_1"},
                                            "childFrames": [],
                                        }
                                    },
                                }
                            )
                        )
                    elif method == "Page.createIsolatedWorld":
                        world_name = params.get("worldName")
                        assert world_name == "cap"
                        await websocket.send(
                            json.dumps(
                                {
                                    "id": msg_id,
                                    "result": {"executionContextId": 42},
                                }
                            )
                        )
                    elif method == "Runtime.evaluate":
                        self.eval_call_count += 1
                        self.last_eval_context_id = params.get("contextId")
                        expr = params.get("expression")
                        if expr == "window.location.href":
                            await websocket.send(
                                json.dumps(
                                    {
                                        "id": msg_id,
                                        "result": {
                                            "result": {
                                                "type": "string",
                                                "value": self.current_url,
                                            }
                                        },
                                    }
                                )
                            )
                        elif expr == "throw_error":
                            await websocket.send(
                                json.dumps(
                                    {
                                        "id": msg_id,
                                        "result": {
                                            "result": {"type": "undefined"},
                                            "exceptionDetails": {"text": "Uncaught Error: boom"},
                                        },
                                    }
                                )
                            )
                        elif expr == "expire_context_then_succeed" and self.eval_call_count == 1:
                            await websocket.send(
                                json.dumps(
                                    {
                                        "id": msg_id,
                                        "error": {
                                            "code": -32000,
                                            "message": "Cannot find context with specified id",
                                        },
                                    }
                                )
                            )
                        else:
                            await websocket.send(
                                json.dumps(
                                    {
                                        "id": msg_id,
                                        "result": {
                                            "result": {
                                                "type": "object",
                                                "value": {"hello": "world"},
                                            }
                                        },
                                    }
                                )
                            )
            except Exception:
                pass

        self._server = await serve(handler, "127.0.0.1", 0)
        assert self._server.sockets is not None
        port = self._server.sockets[0].getsockname()[1]
        self.url = f"ws://127.0.0.1:{port}"

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()


class CustomTargetsServer:
    def __init__(self, target_infos: list[dict[str, Any]]) -> None:
        self.target_infos = target_infos
        self.created_urls: list[str] = []
        self._server: Any = None
        self.url = ""

    async def start(self) -> None:
        async def handler(websocket: ServerConnection) -> None:
            try:
                async for raw in websocket:
                    msg = json.loads(raw)
                    msg_id = msg.get("id")
                    method = msg.get("method")
                    params = msg.get("params", {})

                    if method == "Target.getTargets":
                        await websocket.send(
                            json.dumps({"id": msg_id, "result": {"targetInfos": self.target_infos}})
                        )
                    elif method == "Target.createTarget":
                        self.created_urls.append(params.get("url", ""))
                        await websocket.send(
                            json.dumps({"id": msg_id, "result": {"targetId": "newly_created_tab"}})
                        )
            except Exception:
                pass

        self._server = await serve(handler, "127.0.0.1", 0)
        assert self._server.sockets is not None
        port = self._server.sockets[0].getsockname()[1]
        self.url = f"ws://127.0.0.1:{port}"

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()


def test_chess_page_isolated_world_evaluate() -> None:
    async def run() -> None:
        server = FakePageCDPServer()
        await server.start()
        client = await CDPClient.connect(server.url)
        try:
            page = await ChessPage.attach(client, target_id="target_tab_1")
            res = await page.evaluate_json("return_obj")
            assert res == {"hello": "world"}
            assert server.last_eval_context_id == 42
        finally:
            await client.close()
            await server.stop()

    asyncio.run(run())


def test_chess_page_recreates_isolated_world_on_context_loss() -> None:
    async def run() -> None:
        server = FakePageCDPServer()
        await server.start()
        client = await CDPClient.connect(server.url)
        try:
            page = await ChessPage.attach(client, target_id="target_tab_1")
            res = await page.evaluate_json("expire_context_then_succeed")
            assert res == {"hello": "world"}
            assert server.eval_call_count == 2
        finally:
            await client.close()
            await server.stop()

    asyncio.run(run())


def test_chess_page_evaluation_exception_raised() -> None:
    async def run() -> None:
        server = FakePageCDPServer()
        await server.start()
        client = await CDPClient.connect(server.url)
        try:
            page = await ChessPage.attach(client, target_id="target_tab_1")
            with pytest.raises(EvaluationError, match="boom"):
                await page.evaluate_json("throw_error")
        finally:
            await client.close()
            await server.stop()

    asyncio.run(run())


def test_find_or_create_tab_reuses_allowed() -> None:
    async def run() -> None:
        server = FakePageCDPServer()
        await server.start()
        client = await CDPClient.connect(server.url)
        try:
            target_id = await find_or_create_chess_tab(client)
            assert target_id == "target_tab_1"
        finally:
            await client.close()
            await server.stop()

    asyncio.run(run())


def test_find_or_create_tab_ignores_online_and_creates_new() -> None:
    async def run() -> None:
        targets = [
            {
                "targetId": "online_game_tab",
                "type": "page",
                "url": "https://www.chess.com/play/online",
            }
        ]
        server = CustomTargetsServer(targets)
        await server.start()
        client = await CDPClient.connect(server.url)
        try:
            target_id = await find_or_create_chess_tab(client)
            assert target_id == "newly_created_tab"
            assert server.created_urls == ["https://www.chess.com/play/computer"]

            # Even if caller passes a non-allowed start_url, it must fall back to /play/computer
            server.created_urls.clear()
            target_id2 = await find_or_create_chess_tab(
                client, start_url="https://www.chess.com/play/online"
            )
            assert target_id2 == "newly_created_tab"
            assert server.created_urls == ["https://www.chess.com/play/computer"]
        finally:
            await client.close()
            await server.stop()

    asyncio.run(run())


def test_find_or_create_tab_creates_new_when_no_matching_tabs() -> None:
    async def run() -> None:
        server = CustomTargetsServer([])
        await server.start()
        client = await CDPClient.connect(server.url)
        try:
            target_id = await find_or_create_chess_tab(client)
            assert target_id == "newly_created_tab"
            assert server.created_urls == ["https://www.chess.com/play/computer"]
        finally:
            await client.close()
            await server.stop()

    asyncio.run(run())


def test_find_or_create_tab_human_mode_allows_online() -> None:
    async def run() -> None:
        targets = [
            {
                "targetId": "online_game_tab",
                "type": "page",
                "url": "https://www.chess.com/play/online",
            }
        ]
        server = CustomTargetsServer(targets)
        await server.start()
        client = await CDPClient.connect(server.url)
        try:
            target_id = await find_or_create_chess_tab(
                client, start_url="https://www.chess.com/play/online", mode="human"
            )
            assert target_id == "online_game_tab"
            assert server.created_urls == []
        finally:
            await client.close()
            await server.stop()

    asyncio.run(run())


def test_find_or_create_tab_prioritizes_start_url_match() -> None:
    async def run() -> None:
        targets = [
            {
                "targetId": "computer_tab",
                "type": "page",
                "url": "https://www.chess.com/play/computer",
            },
            {
                "targetId": "online_tab",
                "type": "page",
                "url": "https://www.chess.com/play/online",
            },
        ]
        server = CustomTargetsServer(targets)
        await server.start()
        client = await CDPClient.connect(server.url)
        try:
            target_id = await find_or_create_chess_tab(
                client, start_url="https://www.chess.com/play/online", mode="human"
            )
            assert target_id == "online_tab"
        finally:
            await client.close()
            await server.stop()

    asyncio.run(run())


def test_chess_page_ensure_start_url() -> None:
    async def run() -> None:
        server = FakePageCDPServer()
        server.current_url = "https://www.chess.com/play/computer"
        await server.start()
        client = await CDPClient.connect(server.url)
        try:
            page = await ChessPage.attach(client, target_id="target_tab_1")

            # 1. When on /play/computer and start_url is /play/online, it navigates
            navigated = await page.ensure_start_url(
                "https://www.chess.com/play/online", delay=0.0
            )
            assert navigated is True
            assert server.navigated_urls == ["https://www.chess.com/play/online"]

            # 2. When already on /play/online, it does not navigate
            navigated2 = await page.ensure_start_url(
                "https://www.chess.com/play/online", delay=0.0
            )
            assert navigated2 is False
            assert len(server.navigated_urls) == 1

            # 3. When in an active game (/game/live), it does not navigate
            server.current_url = "https://www.chess.com/game/live/123456"
            navigated3 = await page.ensure_start_url(
                "https://www.chess.com/play/online", delay=0.0
            )
            assert navigated3 is False
            assert len(server.navigated_urls) == 1
        finally:
            await client.close()
            await server.stop()

    asyncio.run(run())

