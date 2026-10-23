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
    assert "analyse" in res.stdout
    assert "run" in res.stdout
    assert "gui" in res.stdout


def test_cli_analyse_mate_in_one() -> None:
    res = subprocess.run(
        [
            sys.executable,
            "-m",
            "chess_autoplayer",
            "analyse",
            "--fen",
            "6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1",
            "--strength",
            "club",
            "--seed",
            "1",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "Chosen Move:     d1d8" in res.stdout
    assert "Decision Reason: fastest_mate" in res.stdout


def test_cli_analyse_invalid_fen() -> None:
    res = subprocess.run(
        [
            sys.executable,
            "-m",
            "chess_autoplayer",
            "analyse",
            "--fen",
            "not-a-valid-fen",
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 1
    assert "invalid FEN" in res.stderr


def test_cli_analyse_invalid_strength() -> None:
    res = subprocess.run(
        [
            sys.executable,
            "-m",
            "chess_autoplayer",
            "analyse",
            "--fen",
            "6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1",
            "--strength",
            "godmode",
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0
    assert "invalid choice" in res.stderr


def test_cli_run_invalid_speed() -> None:
    res = subprocess.run(
        [
            sys.executable,
            "-m",
            "chess_autoplayer",
            "run",
            "--speed",
            "10.0",
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 1
    assert "must be between 0.1 and 5.0" in res.stderr


def test_cli_run_help() -> None:
    res = subprocess.run(
        [sys.executable, "-m", "chess_autoplayer", "run", "--help"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "--strength" in res.stdout
    assert "--speed" in res.stdout
    assert "--input" in res.stdout
    assert "--style" in res.stdout


def test_cli_gui_smoke() -> None:
    res = subprocess.run(
        [sys.executable, "-m", "chess_autoplayer", "gui", "--smoke", "1"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert res.returncode == 0
