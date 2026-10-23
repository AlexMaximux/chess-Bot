"""Asynchronous Chrome DevTools Protocol (CDP) client over WebSockets."""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import websockets
from websockets.asyncio.client import ClientConnection, connect

logger = logging.getLogger(__name__)

EventHandler = Callable[[dict[str, Any]], Awaitable[None] | None]


class CDPException(Exception):
    """Base exception for CDP client operations."""


class CDPError(CDPException):
    """Raised when a CDP command returns an error response."""

    def __init__(self, code: int, message: str, data: object | None = None) -> None:
        super().__init__(f"CDP error {code}: {message}")
        self.code = code
        self.message = message
        self.data = data


class CDPTimeoutError(CDPException):
    """Raised when a CDP command times out waiting for a response."""


class ConnectionLost(CDPException):
    """Raised when the underlying WebSocket connection is closed unexpectedly."""


class CDPClient:
    """Async client managing communication with Chrome DevTools Protocol."""

    def __init__(self, connection: ClientConnection) -> None:
        self._ws: ClientConnection = connection
        self._next_id: int = 1
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        # Listeners key: (session_id or None, event_method) -> list[EventHandler]
        self._listeners: dict[tuple[str | None, str], list[EventHandler]] = {}
        self._closed: bool = False
        self._read_task: asyncio.Task[None] = asyncio.create_task(self._listen_loop())

    @classmethod
    async def connect(cls, ws_url: str) -> "CDPClient":
        """Connect to the browser WebSocket debugger URL."""
        try:
            conn = await connect(ws_url, max_size=25 * 1024 * 1024)
            return cls(conn)
        except Exception as exc:
            raise ConnectionLost(f"Failed to connect to CDP at {ws_url}: {exc}") from exc

    async def _listen_loop(self) -> None:
        """Background task reading and dispatching incoming WebSocket messages."""
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError as exc:
                    logger.warning("Failed to decode CDP JSON message: %s", exc)
                    continue

                if not isinstance(msg, dict):
                    continue

                msg_id = msg.get("id")
                if isinstance(msg_id, int):
                    future = self._pending.pop(msg_id, None)
                    if future and not future.done():
                        if "error" in msg:
                            err_info = msg["error"]
                            code = err_info.get("code", -1) if isinstance(err_info, dict) else -1
                            message = (
                                err_info.get("message", "Unknown error")
                                if isinstance(err_info, dict)
                                else str(err_info)
                            )
                            data = err_info.get("data") if isinstance(err_info, dict) else None
                            future.set_exception(CDPError(code, message, data))
                        else:
                            res = msg.get("result", {})
                            future.set_result(res if isinstance(res, dict) else {})
                elif "method" in msg and isinstance(msg["method"], str):
                    method = msg["method"]
                    session_id = msg.get("sessionId")
                    params = msg.get("params", {})
                    self._dispatch_event(
                        method,
                        params if isinstance(params, dict) else {},
                        session_id if isinstance(session_id, str) else None,
                    )
        except (websockets.exceptions.ConnectionClosed, OSError) as exc:
            logger.debug("CDP connection closed: %s", exc)
        except Exception as exc:
            logger.error("Unexpected error in CDP listen loop: %s", exc)
        finally:
            self._closed = True
            self._fail_all_pending("CDP connection closed")

    def _fail_all_pending(self, reason: str) -> None:
        """Fail all currently pending command futures when connection drops."""
        for future in self._pending.values():
            if not future.done():
                future.set_exception(ConnectionLost(reason))
        self._pending.clear()

    def _dispatch_event(self, method: str, params: dict[str, Any], session_id: str | None) -> None:
        """Dispatch event notifications to matching listeners."""
        handlers: list[EventHandler] = []
        if session_id is not None:
            handlers.extend(self._listeners.get((session_id, method), []))
        # Also dispatch to session-agnostic listeners
        handlers.extend(self._listeners.get((None, method), []))

        for handler in handlers:
            try:
                res = handler(params)
                if asyncio.iscoroutine(res):
                    asyncio.create_task(self._safe_await(res, method))
            except Exception as exc:
                logger.error("Error in CDP event listener for %s: %s", method, exc)

    async def _safe_await(self, coro: Awaitable[None], method: str) -> None:
        """Safely await an asynchronous event callback."""
        try:
            await coro
        except Exception as exc:
            logger.error("Error in async CDP event listener for %s: %s", method, exc)

    def add_event_listener(
        self,
        event: str,
        callback: EventHandler,
        session_id: str | None = None,
    ) -> None:
        """Add a callback for a specific CDP event."""
        key = (session_id, event)
        self._listeners.setdefault(key, []).append(callback)

    def remove_event_listener(
        self,
        event: str,
        callback: EventHandler,
        session_id: str | None = None,
    ) -> None:
        """Remove an existing event callback."""
        key = (session_id, event)
        if key in self._listeners:
            try:
                self._listeners[key].remove(callback)
            except ValueError:
                pass

    async def send(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        session_id: str | None = None,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """Send a CDP command and await its result."""
        if self._closed:
            raise ConnectionLost("Cannot send on a closed CDP client")

        cmd_id = self._next_id
        self._next_id += 1

        payload: dict[str, Any] = {"id": cmd_id, "method": method}
        if params is not None:
            payload["params"] = params
        if session_id is not None:
            payload["sessionId"] = session_id

        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[cmd_id] = future

        try:
            await self._ws.send(json.dumps(payload))
        except (websockets.exceptions.ConnectionClosed, OSError) as exc:
            self._pending.pop(cmd_id, None)
            raise ConnectionLost(f"Failed to send CDP command {method}: {exc}") from exc

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError as exc:
            self._pending.pop(cmd_id, None)
            raise CDPTimeoutError(f"CDP command {method} timed out after {timeout:.1f}s") from exc

    async def close(self) -> None:
        """Cleanly close the client and underlying connection."""
        if self._closed:
            return
        self._closed = True
        self._fail_all_pending("CDP client closed by user")
        try:
            await self._ws.close()
        except Exception as exc:
            logger.debug("Error closing websocket: %s", exc)
        self._read_task.cancel()
        try:
            await self._read_task
        except asyncio.CancelledError:
            pass
