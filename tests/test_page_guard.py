"""Tests for chess_autoplayer.chrome.page URL guard."""

import pytest

from chess_autoplayer.chrome.page import is_allowed_url


@pytest.mark.parametrize(
    "url",
    [
        "https://www.chess.com/play/computer",
        "https://www.chess.com/play/computer/",
        "https://www.chess.com/play/computer?bot=wally",
        "https://www.chess.com/play/computer#board",
        "https://www.chess.com/play/computer/custom-param",
    ],
)
def test_allowed_urls(url: str) -> None:
    assert is_allowed_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "http://www.chess.com/play/computer",  # HTTP rejected
        "https://chess.com/play/computer",  # Non-www rejected
        "https://www.chess.com/play/online",  # Fair play guard: online rejected
        "https://www.chess.com/play",  # Missing /computer
        "https://www.chess.com/game/live",  # Live game rejected
        "https://www.chess.com/",  # Homepage rejected
        "https://evil-chess.com/play/computer",  # Phishing domain rejected
        "https://www.chess.com.attacker.com/play/computer",  # Subdomain exploit rejected
        "https://www.chess.com:8443/play/computer",  # Non-standard port
        "javascript:alert(1)",  # XSS pseudo-url rejected
        "",  # Empty string rejected
        "not-a-url",  # Malformed string rejected
    ],
)
def test_rejected_urls(url: str) -> None:
    assert is_allowed_url(url) is False


@pytest.mark.parametrize(
    "url",
    [
        "https://www.chess.com/play/computer",
        "https://www.chess.com/play/online",
        "https://www.chess.com/live",
        "https://www.chess.com/game/live",
        "https://www.chess.com/game/live/1234567890",
        "https://chess.com/play/online",
        "https://chess.com/game/live/1234567890",
        "https://www.chess.com/puzzles",
    ],
)
def test_human_mode_allowed_urls(url: str) -> None:
    assert is_allowed_url(url, mode="human") is True


@pytest.mark.parametrize(
    "url",
    [
        "http://www.chess.com/play/online",  # HTTP rejected
        "http://chess.com/live",  # HTTP rejected
        "https://evil-chess.com/play/online",  # Phishing rejected
        "https://www.chess.com.attacker.com/live",  # Attacker subdomain rejected
        "https://www.chess.com:8443/play/online",  # Non-standard port rejected
        "",
        "not-a-url",
    ],
)
def test_human_mode_rejected_urls(url: str) -> None:
    assert is_allowed_url(url, mode="human") is False
