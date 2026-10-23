"""Logging configuration for chess-autoplayer."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

DEFAULT_LOG_DIR = Path("~/.chess-autoplayer/logs").expanduser()
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    log_dir: Path | None = None,
    console_level: int = logging.INFO,
    file_level: int = logging.DEBUG,
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 3,
) -> None:
    """Configure console and rotating file logging for the application."""
    target_dir = (log_dir if log_dir is not None else DEFAULT_LOG_DIR).expanduser()
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        # If directory creation fails, configure console only and warn
        logging.basicConfig(level=console_level, format=LOG_FORMAT, datefmt=DATE_FORMAT)
        logging.getLogger(__name__).warning(
            "Could not create log directory %s: %s", target_dir, exc
        )
        return

    log_file = target_dir / "app.log"
    root_logger = logging.getLogger()
    root_logger.setLevel(min(console_level, file_level))

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    # Remove existing handlers to prevent duplicates during reconfiguration
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    try:
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(file_level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    except OSError as exc:
        logging.getLogger(__name__).warning("Could not open log file %s: %s", log_file, exc)
