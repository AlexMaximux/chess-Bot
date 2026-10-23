"""Find, launch, or attach to Google Chrome with remote debugging."""

import asyncio
import json
import logging
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from chess_autoplayer.config import Settings

logger = logging.getLogger(__name__)

STANDARD_MAC_CHROME_PATH = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


class ChromeLaunchError(Exception):
    """Raised when finding, launching, or connecting to Chrome fails."""


def find_chrome_executable(settings: Settings) -> Path:
    """Locate the Chrome executable from config or standard macOS location."""
    configured = settings.resolved_chrome_path()
    if configured.is_file():
        return configured

    if STANDARD_MAC_CHROME_PATH.is_file():
        return STANDARD_MAC_CHROME_PATH

    raise ChromeLaunchError(
        f"Google Chrome executable not found at {configured} or standard macOS path "
        f"{STANDARD_MAC_CHROME_PATH}. Please check chrome_path in config."
    )


def _fetch_ws_url_sync(port: int, timeout: float) -> str | None:
    """Synchronous HTTP request to fetch webSocketDebuggerUrl from /json/version."""
    url = f"http://127.0.0.1:{port}/json/version"
    req = urllib.request.Request(url, headers={"User-Agent": "chess-autoplayer"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status != 200:
                return None
            body = response.read().decode("utf-8")
            data: dict[str, Any] = json.loads(body)
            ws_url = data.get("webSocketDebuggerUrl")
            return str(ws_url) if isinstance(ws_url, str) else None
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError):
        return None


async def get_browser_ws_url(port: int, timeout: float = 1.0) -> str | None:
    """Check if Chrome debug port is answering and return browser WebSocket URL."""
    return await asyncio.to_thread(_fetch_ws_url_sync, port, timeout)


async def launch_or_attach_chrome(settings: Settings, timeout: float = 20.0) -> str:
    """Attach to existing Chrome debug port or launch a new detached Chrome instance.

    Returns the browser WebSocket URL.
    """
    # 1. Check if debug port is already open
    existing_ws = await get_browser_ws_url(settings.debug_port, timeout=1.0)
    if existing_ws:
        logger.info(
            "Chrome debug port %d is already active; attaching to %s",
            settings.debug_port,
            existing_ws,
        )
        return existing_ws

    # 2. Chrome is not running on debug port; find executable and launch
    chrome_bin = find_chrome_executable(settings)
    profile_dir = settings.resolved_profile_dir()
    profile_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(chrome_bin),
        f"--remote-debugging-port={settings.debug_port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        settings.start_url,
    ]
    logger.info(
        "Launching Chrome at %s with profile %s on port %d...",
        chrome_bin,
        profile_dir,
        settings.debug_port,
    )

    try:
        subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        raise ChromeLaunchError(f"Failed to launch Chrome process: {exc}") from exc

    # 3. Poll for debug port to become active
    start_time = time.monotonic()
    deadline = start_time + timeout
    poll_interval = 0.25

    while time.monotonic() < deadline:
        ws_url = await get_browser_ws_url(settings.debug_port, timeout=0.5)
        if ws_url:
            elapsed = time.monotonic() - start_time
            logger.info("Chrome debug port became ready in %.2fs (%s)", elapsed, ws_url)
            return ws_url
        await asyncio.sleep(poll_interval)

    raise ChromeLaunchError(
        f"Chrome was launched but debug port {settings.debug_port} did not answer "
        f"within {timeout:.0f}s. Check if another process is using port {settings.debug_port} "
        "or if Chrome crashed."
    )
