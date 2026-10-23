"""Tests for chess_autoplayer.config."""

import json
from pathlib import Path

import pytest

from chess_autoplayer.config import ConfigError, Settings, load_config, save_config


def test_default_settings() -> None:
    settings = Settings()
    assert settings.debug_port == 9333
    assert settings.strength == "club"
    assert settings.input_mode == "cdp"
    assert settings.move_style == "mixed"
    assert settings.start_url == "https://www.chess.com/play/computer"
    assert settings.resolved_chrome_path().is_absolute()
    assert settings.resolved_profile_dir().is_absolute()
    assert settings.resolved_stockfish_path().is_absolute()


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.json"
    original = Settings(debug_port=9444, strength="master", input_mode="os", move_style="drag")
    save_config(original, config_path=cfg_file)

    loaded = load_config(config_path=cfg_file)
    assert loaded == original


def test_load_ignores_unknown_keys_with_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    cfg_file = tmp_path / "config.json"
    data = {"debug_port": 9555, "unknown_future_key": "some_value"}
    cfg_file.write_text(json.dumps(data), encoding="utf-8")

    loaded = load_config(config_path=cfg_file)
    assert loaded.debug_port == 9555
    assert "unknown_future_key" in caplog.text


def test_invalid_values_raise_config_error(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.json"

    # Invalid port
    cfg_file.write_text(json.dumps({"debug_port": -1}), encoding="utf-8")
    with pytest.raises(ConfigError, match="debug_port"):
        load_config(config_path=cfg_file)

    # Invalid port type
    cfg_file.write_text(json.dumps({"debug_port": "not-a-port"}), encoding="utf-8")
    with pytest.raises(ConfigError, match="debug_port"):
        load_config(config_path=cfg_file)

    # Invalid input mode
    cfg_file.write_text(json.dumps({"input_mode": "invalid"}), encoding="utf-8")
    with pytest.raises(ConfigError, match="input_mode"):
        load_config(config_path=cfg_file)

    # Invalid move style
    cfg_file.write_text(json.dumps({"move_style": "teleport"}), encoding="utf-8")
    with pytest.raises(ConfigError, match="move_style"):
        load_config(config_path=cfg_file)

    # Malformed JSON
    cfg_file.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(ConfigError, match="Failed to parse"):
        load_config(config_path=cfg_file)


def test_default_config_path_when_file_does_not_exist(tmp_path: Path) -> None:
    cfg_file = tmp_path / "nonexistent" / "config.json"
    loaded = load_config(config_path=cfg_file)
    assert loaded == Settings()
