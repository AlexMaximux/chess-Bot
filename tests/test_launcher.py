"""Tests for chess_autoplayer.chrome.launcher."""

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest

from chess_autoplayer.chrome.launcher import (
    ChromeLaunchError,
    find_chrome_executable,
    get_browser_ws_url,
    launch_or_attach_chrome,
)
from chess_autoplayer.config import Settings


class MockJsonVersionHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/json/version":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            resp = json.dumps({"webSocketDebuggerUrl": "ws://127.0.0.1:9999/devtools/browser/xyz"})
            self.wfile.write(resp.encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        pass


def test_find_chrome_executable_found(tmp_path: Path) -> None:
    fake_chrome = tmp_path / "Google Chrome"
    fake_chrome.write_text("#!/bin/sh\n", encoding="utf-8")
    fake_chrome.chmod(0o755)

    settings = Settings(chrome_path=str(fake_chrome))
    found = find_chrome_executable(settings)
    assert found == fake_chrome.resolve()


def test_find_chrome_executable_not_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(chrome_path=str(tmp_path / "nonexistent_chrome"))
    monkeypatch.setattr(
        "chess_autoplayer.chrome.launcher.STANDARD_MAC_CHROME_PATH",
        tmp_path / "nonexistent_default",
    )
    with pytest.raises(ChromeLaunchError, match="Google Chrome executable not found"):
        find_chrome_executable(settings)


def test_get_browser_ws_url_active_port() -> None:
    server = HTTPServer(("127.0.0.1", 0), MockJsonVersionHandler)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        ws_url = asyncio.run(get_browser_ws_url(port=port, timeout=1.0))
        assert ws_url == "ws://127.0.0.1:9999/devtools/browser/xyz"
    finally:
        server.shutdown()
        server.server_close()


def test_get_browser_ws_url_closed_port() -> None:
    # Port 65432 should not be running
    ws_url = asyncio.run(get_browser_ws_url(port=65432, timeout=0.1))
    assert ws_url is None


def test_launch_or_attach_attaches_if_port_already_open() -> None:
    server = HTTPServer(("127.0.0.1", 0), MockJsonVersionHandler)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        settings = Settings(debug_port=port)
        ws_url = asyncio.run(launch_or_attach_chrome(settings, timeout=1.0))
        assert ws_url == "ws://127.0.0.1:9999/devtools/browser/xyz"
    finally:
        server.shutdown()
        server.server_close()
