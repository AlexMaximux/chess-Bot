"""Tests for chess_autoplayer.chrome.cdp using an in-process websocket server."""

import asyncio
import json
from typing import Any

import pytest
import websockets
from websockets.asyncio.server import ServerConnection, serve

from chess_autoplayer.chrome.cdp import CDPClient, CDPError, CDPTimeoutError, ConnectionLost


class FakeServer:
    def __init__(self) -> None:
        self.last_received: list[dict[str, Any]] = []
        self.connections: list[ServerConnection] = []
        self._server = None
        self.url = ""

    async def start(self) -> None:
        async def handler(websocket: ServerConnection) -> None:
            self.connections.append(websocket)
            try:
                async for raw in websocket:
                    msg = json.loads(raw)
                    self.last_received.append(msg)
                    msg_id = msg.get("id")
                    method = msg.get("method")

                    if method == "Browser.getVersion":
                        await websocket.send(
                            json.dumps({"id": msg_id, "result": {"product": "Chrome/155"}})
                        )
                    elif method == "Fail.test":
                        await websocket.send(
                            json.dumps(
                                {
                                    "id": msg_id,
                                    "error": {"code": -32000, "message": "Failed intentionally"},
                                }
                            )
                        )
                    elif method == "Slow.test":
                        # Sleep longer than client timeout
                        await asyncio.sleep(0.5)
                        await websocket.send(json.dumps({"id": msg_id, "result": {"done": True}}))
                    elif method == "Trigger.event":
                        # Send response then emit event with sessionId
                        await websocket.send(json.dumps({"id": msg_id, "result": {"ok": True}}))
                        await websocket.send(
                            json.dumps(
                                {
                                    "method": "Page.frameNavigated",
                                    "sessionId": msg.get("sessionId"),
                                    "params": {"frame": {"id": "123"}},
                                }
                            )
                        )
            except (websockets.exceptions.ConnectionClosed, OSError):
                pass

        self._server = await serve(handler, "127.0.0.1", 0)
        assert self._server.sockets is not None
        port = self._server.sockets[0].getsockname()[1]
        self.url = f"ws://127.0.0.1:{port}"

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()


def test_cdp_command_and_response() -> None:
    async def run() -> None:
        server = FakeServer()
        await server.start()
        client = await CDPClient.connect(server.url)
        try:
            res = await client.send("Browser.getVersion")
            assert res["product"] == "Chrome/155"
            assert server.last_received[0]["method"] == "Browser.getVersion"
        finally:
            await client.close()
            await server.stop()

    asyncio.run(run())


def test_cdp_error_raised() -> None:
    async def run() -> None:
        server = FakeServer()
        await server.start()
        client = await CDPClient.connect(server.url)
        try:
            with pytest.raises(CDPError) as exc_info:
                await client.send("Fail.test")
            assert exc_info.value.code == -32000
            assert "Failed intentionally" in exc_info.value.message
        finally:
            await client.close()
            await server.stop()

    asyncio.run(run())


def test_cdp_timeout() -> None:
    async def run() -> None:
        server = FakeServer()
        await server.start()
        client = await CDPClient.connect(server.url)
        try:
            with pytest.raises(CDPTimeoutError):
                await client.send("Slow.test", timeout=0.1)
        finally:
            await client.close()
            await server.stop()

    asyncio.run(run())


def test_cdp_event_dispatch_by_session() -> None:
    async def run() -> None:
        server = FakeServer()
        await server.start()
        client = await CDPClient.connect(server.url)
        try:
            received_events: list[dict[str, Any]] = []

            def on_nav(params: dict[str, Any]) -> None:
                received_events.append(params)

            client.add_event_listener("Page.frameNavigated", on_nav, session_id="sess_abc")

            await client.send("Trigger.event", session_id="sess_abc")
            await asyncio.sleep(0.05)

            assert len(received_events) == 1
            assert received_events[0]["frame"]["id"] == "123"
        finally:
            await client.close()
            await server.stop()

    asyncio.run(run())


def test_cdp_connection_lost() -> None:
    async def run() -> None:
        server = FakeServer()
        await server.start()
        client = await CDPClient.connect(server.url)
        try:
            task = asyncio.create_task(client.send("Slow.test", timeout=5.0))
            await asyncio.sleep(0.05)
            for conn in server.connections:
                await conn.close()

            with pytest.raises(ConnectionLost):
                await task

            # Next send must fail fast with ConnectionLost
            with pytest.raises(ConnectionLost, match="closed"):
                await client.send("Browser.getVersion")
        finally:
            await client.close()
            await server.stop()

    asyncio.run(run())
