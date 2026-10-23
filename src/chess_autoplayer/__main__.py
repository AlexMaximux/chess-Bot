"""CLI entry point for chess-autoplayer."""

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

import chess

from chess_autoplayer.board.reader import get_reader_js
from chess_autoplayer.board.snapshot import parse_snapshot
from chess_autoplayer.board.state import GameState, StateError
from chess_autoplayer.chrome.cdp import CDPClient
from chess_autoplayer.chrome.launcher import launch_or_attach_chrome
from chess_autoplayer.chrome.page import ChessPage, find_or_create_chess_tab, is_allowed_url
from chess_autoplayer.config import load_config
from chess_autoplayer.logging_setup import setup_logging

logger = logging.getLogger(__name__)


async def async_probe(save_fixture: str | None = None, output_json: bool = False) -> int:
    """Execute probe command to inspect the browser and chess board."""
    settings = load_config()

    try:
        ws_url = await launch_or_attach_chrome(settings)
    except Exception as exc:
        print(f"Error launching/attaching to Chrome: {exc}", file=sys.stderr)
        return 1

    try:
        cdp = await CDPClient.connect(ws_url)
    except Exception as exc:
        print(f"Error connecting to Chrome CDP at {ws_url}: {exc}", file=sys.stderr)
        return 1

    try:
        target_id = await find_or_create_chess_tab(cdp, settings.start_url)
        page = await ChessPage.attach(cdp, target_id)

        current_url = await page.url()
        url_allowed = is_allowed_url(current_url)

        # Wait up to 10s for the board to render if tab newly loaded
        start_wait = time.monotonic()
        raw_snapshot: object = None
        while time.monotonic() - start_wait < 10.0:
            reader_code = get_reader_js()
            raw_snapshot = await page.evaluate_json(reader_code)
            if isinstance(raw_snapshot, dict) and raw_snapshot.get("found"):
                break
            await asyncio.sleep(0.5)

        if not isinstance(raw_snapshot, dict):
            print(f"Error: reader.js returned invalid data: {raw_snapshot!r}", file=sys.stderr)
            return 1

        snapshot = parse_snapshot(raw_snapshot)

        if save_fixture:
            fix_name = save_fixture if save_fixture.endswith(".json") else f"{save_fixture}.json"
            fix_path = Path("tests/fixtures") / fix_name
            fix_path.parent.mkdir(parents=True, exist_ok=True)
            fix_path.write_text(json.dumps(raw_snapshot, indent=2) + "\n", encoding="utf-8")
            print(f"Saved fixture to {fix_path}")

        if output_json:
            print(json.dumps(raw_snapshot, indent=2))
            return 0

        # Human-readable summary
        allowed_desc = "YES (Fair play verified)" if url_allowed else "NO (Guard active!)"
        print("=" * 60)
        print("CHESS-AUTOPLAYER PROBE REPORT")
        print("=" * 60)
        print(f"Page URL:        {current_url}")
        print(f"URL Allowed:     {allowed_desc}")
        print(f"Board Found:     {'YES' if snapshot.found else 'NO'}")

        if not snapshot.found:
            print("No chess board detected on the active page.")
            return 0

        r = snapshot.board_rect
        print(f"Board Rect:      x={r.x:.1f}, y={r.y:.1f}, w={r.width:.1f}, h={r.height:.1f}")
        print(
            f"Flipped Board:   class={snapshot.flipped_class}, geometry={snapshot.flipped_geometry}"
        )
        print(f"Pieces Rendered: {len(snapshot.pieces)}")
        print(f"Moves Recorded:  {len(snapshot.moves)}: {' '.join(snapshot.moves)}")
        hl_str = (
            ", ".join(snapshot.last_move_highlights) if snapshot.last_move_highlights else "None"
        )
        print(f"Highlights:      {hl_str}")
        print(f"Dragging:        {snapshot.dragging}")
        print(f"Promotion Open:  {snapshot.promotion_open}")
        print(f"Game Over:       {snapshot.game_over} ({snapshot.game_over_text or 'No modal'})")

        try:
            state = GameState.from_snapshot(snapshot, play_as=settings.play_as)
            color_str = "White" if state.our_color == chess.WHITE else "Black"
            turn_str = "White" if state.turn == chess.WHITE else "Black"
            last_uci = state.last_move.uci() if state.last_move else "None"
            print("-" * 60)
            print(f"Reconstructed FEN: {state.fen}")
            print(f"Our Color:         {color_str}")
            print(f"Whose Turn:        {turn_str}")
            print(f"Is Our Turn:       {'YES' if state.is_our_turn else 'NO'}")
            print(f"Last Move:         {last_uci}")
            print(f"Ply (half-moves):  {state.ply}")
            print(f"Reconstruct Source:{state.source}")
            print(f"Game Over State:   {state.is_game_over}")
            print("=" * 60)
        except StateError as s_err:
            print(f"State reconstruction error: {s_err}", file=sys.stderr)
            return 1

        return 0

    finally:
        await cdp.close()


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="chess-autoplayer",
        description="Autonomous chess player driving real Google Chrome on chess.com against bots",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # probe subcommand
    probe_parser = subparsers.add_parser(
        "probe", help="Inspect chess.com board and print game state"
    )
    probe_parser.add_argument(
        "--save-fixture",
        type=str,
        metavar="NAME",
        help="Save captured snapshot JSON to tests/fixtures/<NAME>.json",
    )
    probe_parser.add_argument("--json", action="store_true", help="Output raw JSON snapshot")
    probe_parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose debug logging"
    )

    # run subcommand (placeholder for brief 03)
    subparsers.add_parser("run", help="Run autoplayer bot loop (brief 03)")

    # gui subcommand (placeholder for brief 04)
    subparsers.add_parser("gui", help="Launch Tkinter desktop GUI (brief 04)")

    args = parser.parse_args()

    log_level = logging.DEBUG if getattr(args, "verbose", False) else logging.INFO
    setup_logging(console_level=log_level)

    if args.command == "probe":
        exit_code = asyncio.run(async_probe(save_fixture=args.save_fixture, output_json=args.json))
        sys.exit(exit_code)
    elif args.command in ("run", "gui"):
        print(f"Subcommand {args.command!r} is not implemented yet (scheduled for later brief).")
        sys.exit(0)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
