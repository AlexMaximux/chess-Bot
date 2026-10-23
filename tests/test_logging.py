"""Tests for logging_setup."""

import logging
from pathlib import Path

from chess_autoplayer.logging_setup import setup_logging


def test_setup_logging_creates_log_file(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    setup_logging(log_dir=log_dir, console_level=logging.DEBUG)

    test_logger = logging.getLogger("chess_autoplayer.test")
    test_logger.info("Test message for file log")

    log_file = log_dir / "app.log"
    assert log_file.is_file()
    content = log_file.read_text(encoding="utf-8")
    assert "Test message for file log" in content
