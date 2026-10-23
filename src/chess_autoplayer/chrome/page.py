"""Chrome page interaction, isolated world management, and fair-play URL guard."""

import asyncio
import logging
from typing import Any
from urllib.parse import urlsplit

from chess_autoplayer.chrome.cdp import CDPClient, CDPError

logger = logging.getLogger(__name__)


class PageError(Exception):
    """Raised when page operations fail."""


class EvaluationError(PageError):
    """Raised when JavaScript evaluation in the isolated world throws an exception."""


def is_allowed_url(url: str) -> bool:
    """Fair-play URL guard.

    Returns True only if url uses https, hostname is www.chess.com (default port),
    and path starts with /play/computer.
    """
    if not url:
        return False
    try:
        parts = urlsplit(url)
    except Exception:
        return False

    if parts.scheme != "https":
        return False

    if parts.hostname != "www.chess.com":
        return False
    if parts.port is not None and parts.port != 443:
        return False

    if not parts.path.startswith("/play/computer"):
        return False

    return True


async def find_or_create_chess_tab(
    cdp: CDPClient,
    start_url: str = "https://www.chess.com/play/computer",
) -> str:
    """Find a chess.com tab or create one if none exists.

    Returns the targetId of the tab.
    """
    targets_res = await cdp.send("Target.getTargets")
    target_infos: list[dict[str, Any]] = targets_res.get("targetInfos", [])

    page_targets = [t for t in target_infos if t.get("type") == "page"]

    # 1. Look for tab already on an allowed /play/computer URL
    matching_computer: list[dict[str, Any]] = []

    for t in page_targets:
        url = t.get("url", "")
        if is_allowed_url(url):
            matching_computer.append(t)

    if matching_computer:
        chosen = matching_computer[0]
        target_id = chosen.get("targetId", "")
        logger.info(
            "Found existing chess.com/play/computer tab: %s (%s)",
            target_id,
            chosen.get("url"),
        )
        return str(target_id)

    # 2. Never hijack non-allowed tabs (e.g. /play/online); create a new target
    logger.info(
        "No tab found on an allowed /play/computer URL; creating new target with url %s",
        start_url,
    )
    create_res = await cdp.send("Target.createTarget", {"url": start_url})
    new_id = create_res.get("targetId")
    if not new_id or not isinstance(new_id, str):
        raise PageError(f"Target.createTarget returned invalid targetId: {create_res}")
    return new_id


class ChessPage:
    """Manages an attached Chrome page target using an isolated world for safe script execution."""

    def __init__(self, cdp: CDPClient, target_id: str, session_id: str) -> None:
        self._cdp: CDPClient = cdp
        self._target_id: str = target_id
        self._session_id: str = session_id
        self._main_frame_id: str | None = None
        self._context_id: int | None = None
        self._lock = asyncio.Lock()

        # Listen to navigation on this session to invalidate isolated world
        self._cdp.add_event_listener(
            "Page.frameNavigated",
            self._on_frame_navigated,
            session_id=self._session_id,
        )

    @classmethod
    async def attach(cls, cdp: CDPClient, target_id: str) -> "ChessPage":
        """Attach to target with flatten: true and initialize page."""
        attach_res = await cdp.send(
            "Target.attachToTarget",
            {"targetId": target_id, "flatten": True},
        )
        session_id = attach_res.get("sessionId")
        if not session_id or not isinstance(session_id, str):
            raise PageError(f"Target.attachToTarget did not return a valid sessionId: {attach_res}")

        page = cls(cdp, target_id, session_id)
        # Page.enable is explicitly permitted by rules; do NOT call Runtime.enable / Debugger.enable
        await cdp.send("Page.enable", session_id=session_id)
        await page._ensure_isolated_world()
        return page

    def _on_frame_navigated(self, params: dict[str, Any]) -> None:
        """Handle Page.frameNavigated event."""
        frame = params.get("frame", {})
        parent_id = frame.get("parentId")
        frame_id = frame.get("id")
        # Top-level frame has no parentId
        if not parent_id or frame_id == self._main_frame_id:
            logger.debug("Main frame navigated (%s); invalidating isolated world context", frame_id)
            self._context_id = None

    async def _ensure_isolated_world(self) -> int:
        """Ensure an active isolated world exists for the main frame."""
        async with self._lock:
            if self._context_id is not None:
                return self._context_id

            # Discover main frame ID
            tree_res = await self._cdp.send("Page.getFrameTree", session_id=self._session_id)
            frame_tree = tree_res.get("frameTree", {})
            frame = frame_tree.get("frame", {})
            self._main_frame_id = frame.get("id")

            if not self._main_frame_id:
                raise PageError("Failed to obtain main frame ID from Page.getFrameTree")

            # Create isolated world named "cap"
            world_res = await self._cdp.send(
                "Page.createIsolatedWorld",
                {
                    "frameId": self._main_frame_id,
                    "worldName": "cap",
                    "grantUniveralAccess": False,
                },
                session_id=self._session_id,
            )
            ctx_id = world_res.get("executionContextId")
            if not isinstance(ctx_id, int):
                raise PageError(
                    f"Page.createIsolatedWorld returned non-integer executionContextId: {world_res}"
                )

            logger.debug("Created isolated world 'cap' with contextId=%d", ctx_id)
            self._context_id = ctx_id
            return self._context_id

    async def evaluate_json(self, expression: str, timeout: float = 10.0) -> object:
        """Evaluate a JavaScript expression in the isolated world and return the value."""
        for attempt in range(2):
            context_id = await self._ensure_isolated_world()
            try:
                res = await self._cdp.send(
                    "Runtime.evaluate",
                    {
                        "expression": expression,
                        "contextId": context_id,
                        "returnByValue": True,
                        "awaitPromise": True,
                    },
                    session_id=self._session_id,
                    timeout=timeout,
                )

                if "exceptionDetails" in res:
                    exc_details = res["exceptionDetails"]
                    text = exc_details.get("text", "")
                    exception = exc_details.get("exception", {})
                    description = exception.get("description", text)
                    raise EvaluationError(f"JS evaluation error: {description or text}")

                result_obj = res.get("result", {})
                return result_obj.get("value")

            except CDPError as cdp_err:
                # If context is destroyed or not found, invalidate and retry once
                err_msg = cdp_err.message.lower()
                is_ctx_err = "cannot find context" in err_msg or "context was destroyed" in err_msg
                if attempt == 0 and is_ctx_err:
                    logger.debug(
                        "Context %d invalid (%s); recreating isolated world...",
                        context_id,
                        cdp_err.message,
                    )
                    self._context_id = None
                    continue
                raise

        raise PageError("Failed to evaluate script in isolated world after retry")

    async def url(self) -> str:
        """Get the current URL of the page."""
        val = await self.evaluate_json("window.location.href")
        return str(val) if isinstance(val, str) else ""

    async def navigate(self, url: str) -> None:
        """Navigate the tab to a given URL."""
        await self._cdp.send("Page.navigate", {"url": url}, session_id=self._session_id)
        self._context_id = None
