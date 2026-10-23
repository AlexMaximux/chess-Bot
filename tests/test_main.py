"""Tests for CLI entry points."""

import subprocess
import sys


def test_cli_help() -> None:
    res = subprocess.run(
        [sys.executable, "-m", "chess_autoplayer", "--help"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "probe" in res.stdout
    assert "run" in res.stdout
    assert "gui" in res.stdout


def test_cli_run_placeholder() -> None:
    res = subprocess.run(
        [sys.executable, "-m", "chess_autoplayer", "run"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "not implemented yet" in res.stdout


def test_cli_gui_placeholder() -> None:
    res = subprocess.run(
        [sys.executable, "-m", "chess_autoplayer", "gui"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "not implemented yet" in res.stdout
