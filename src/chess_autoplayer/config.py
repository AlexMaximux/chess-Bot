"""Configuration management for chess-autoplayer."""

import json
import logging
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_DIR = Path("~/.chess-autoplayer").expanduser()
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.json"

VALID_INPUT_MODES = {"cdp", "os"}
VALID_MOVE_STYLES = {"drag", "click", "mixed"}
VALID_PLAY_AS = {"auto", "white", "black"}
VALID_STRENGTHS = {"beginner", "casual", "club", "strong", "master", "max"}


class ConfigError(Exception):
    """Raised when configuration file is invalid or corrupted."""


@dataclass(frozen=True)
class Settings:
    """Application settings with defaults."""

    chrome_path: str = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    stockfish_path: str = "/opt/homebrew/bin/stockfish"
    profile_dir: str = "~/.chess-autoplayer/chrome-profile"
    debug_port: int = 9333
    start_url: str = "https://www.chess.com/play/computer"
    strength: str = "club"
    speed: float = 1.0
    input_mode: str = "cdp"
    move_style: str = "mixed"
    play_as: str = "auto"

    def resolved_chrome_path(self) -> Path:
        """Return the resolved Path for the Chrome executable."""
        return Path(self.chrome_path).expanduser().resolve()

    def resolved_stockfish_path(self) -> Path:
        """Return the resolved Path for the Stockfish executable."""
        return Path(self.stockfish_path).expanduser().resolve()

    def resolved_profile_dir(self) -> Path:
        """Return the resolved Path for the Chrome user profile directory."""
        return Path(self.profile_dir).expanduser().resolve()


def _validate_raw_config(data: dict[str, Any]) -> dict[str, Any]:
    """Validate and filter raw JSON config dictionary."""
    valid_field_names = {f.name for f in fields(Settings)}
    cleaned: dict[str, Any] = {}

    for key, value in data.items():
        if key not in valid_field_names:
            logger.warning("Ignoring unknown configuration key: %s", key)
            continue
        cleaned[key] = value

    if "debug_port" in cleaned:
        port = cleaned["debug_port"]
        if not isinstance(port, int) or isinstance(port, bool) or not (1 <= port <= 65535):
            raise ConfigError(
                f"Invalid debug_port: {port!r}. Must be an integer between 1 and 65535."
            )

    if "input_mode" in cleaned:
        mode = cleaned["input_mode"]
        if mode not in VALID_INPUT_MODES:
            raise ConfigError(
                f"Invalid input_mode: {mode!r}. Must be one of {sorted(VALID_INPUT_MODES)}."
            )

    if "move_style" in cleaned:
        style = cleaned["move_style"]
        if style not in VALID_MOVE_STYLES:
            raise ConfigError(
                f"Invalid move_style: {style!r}. Must be one of {sorted(VALID_MOVE_STYLES)}."
            )

    if "play_as" in cleaned:
        play_as = cleaned["play_as"]
        if play_as not in VALID_PLAY_AS:
            raise ConfigError(
                f"Invalid play_as: {play_as!r}. Must be one of {sorted(VALID_PLAY_AS)}."
            )

    if "strength" in cleaned:
        strength = cleaned["strength"]
        if strength not in VALID_STRENGTHS:
            raise ConfigError(
                f"Invalid strength: {strength!r}. Must be one of {sorted(VALID_STRENGTHS)}."
            )

    if "speed" in cleaned:
        speed = cleaned["speed"]
        if (
            not isinstance(speed, (int, float))
            or isinstance(speed, bool)
            or not (0.1 <= speed <= 5.0)
        ):
            raise ConfigError(f"Invalid speed: {speed!r}. Must be between 0.1 and 5.0.")
        cleaned["speed"] = float(speed)

    for str_field in ("chrome_path", "stockfish_path", "profile_dir", "start_url"):
        if str_field in cleaned:
            val = cleaned[str_field]
            if not isinstance(val, str) or not val.strip():
                raise ConfigError(f"Field {str_field!r} must be a non-empty string.")

    if "start_url" in cleaned:
        from chess_autoplayer.chrome.page import is_allowed_url

        if not is_allowed_url(cleaned["start_url"]):
            logger.warning(
                "Configured start_url %r is not an allowed URL; using default.",
                cleaned["start_url"],
            )
            cleaned["start_url"] = Settings.start_url

    return cleaned


def load_config(config_path: Path | None = None) -> Settings:
    """Load settings from JSON file, returning defaults if file does not exist."""
    path = config_path if config_path is not None else DEFAULT_CONFIG_PATH
    path = path.expanduser()

    if not path.is_file():
        logger.debug("Config file %s does not exist; using default settings.", path)
        return Settings()

    try:
        content = path.read_text(encoding="utf-8")
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Failed to parse config JSON at {path}: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"Failed to read config file at {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError(f"Expected JSON object in {path}, got {type(data).__name__}")

    validated = _validate_raw_config(data)
    return Settings(**validated)


def save_config(settings: Settings, config_path: Path | None = None) -> None:
    """Save settings to a JSON file, creating parent directories if needed."""
    path = config_path if config_path is not None else DEFAULT_CONFIG_PATH
    path = path.expanduser()

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(asdict(settings), indent=2) + "\n"
        path.write_text(payload, encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Failed to write config file at {path}: {exc}") from exc
