"""Loader for reader.js DOM snapshot script."""

from importlib import resources


def get_reader_js() -> str:
    """Read and return reader.js script from package resources."""
    board_pkg = resources.files("chess_autoplayer.board")
    return board_pkg.joinpath("reader.js").read_text(encoding="utf-8")
