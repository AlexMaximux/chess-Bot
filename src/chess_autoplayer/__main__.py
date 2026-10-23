"""CLI entry point for chess-autoplayer."""

import argparse
import asyncio
import json
import logging
import random
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import chess

from chess_autoplayer.board.reader import get_reader_js
from chess_autoplayer.board.snapshot import parse_snapshot
from chess_autoplayer.board.state import GameState, StateError
from chess_autoplayer.bot.controller import BotController
from chess_autoplayer.bot.events import (
    BotEvent,
    DecisionEvent,
    ErrorEvent,
    GameOverEvent,
    MoveEvent,
    StatusEvent,
)
from chess_autoplayer.chrome.cdp import CDPClient
from chess_autoplayer.chrome.launcher import launch_or_attach_chrome
from chess_autoplayer.chrome.page import ChessPage, find_or_create_chess_tab, is_allowed_url
from chess_autoplayer.config import load_config
from chess_autoplayer.engine.profiles import PROFILES
from chess_autoplayer.engine.selector import select_move
from chess_autoplayer.engine.stockfish import Engine, EngineError
from chess_autoplayer.human.timing import compute_think_time
from chess_autoplayer.input.base import MoveInput
from chess_autoplayer.input.cdp_input import CDPInput
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


async def async_analyse(
    fen: str | None = None,
    strength: str | None = None,
    seed: int | None = None,
) -> int:
    """Analyse board position with Stockfish and select human-like move."""
    settings = load_config()
    chosen_strength = strength if strength is not None else settings.strength
    if chosen_strength not in PROFILES:
        valid_keys = sorted(PROFILES.keys())
        print(
            f"Error: Unknown strength profile {chosen_strength!r}. Choose from: {valid_keys}",
            file=sys.stderr,
        )
        return 1

    profile = PROFILES[chosen_strength]
    rng = random.Random(seed) if seed is not None else random.Random()

    last_move: chess.Move | None = None
    if fen is not None:
        try:
            board = chess.Board(fen)
        except ValueError as exc:
            print(f"Error: invalid FEN string {fen!r}: {exc}", file=sys.stderr)
            return 1
    else:
        # Read from live browser session
        try:
            ws_url = await launch_or_attach_chrome(settings)
            cdp = await CDPClient.connect(ws_url)
        except Exception as exc:
            print(f"Error connecting to Chrome: {exc}", file=sys.stderr)
            return 1

        try:
            target_id = await find_or_create_chess_tab(cdp, settings.start_url)
            page = await ChessPage.attach(cdp, target_id)

            start_wait = time.monotonic()
            raw_snapshot: object = None
            while time.monotonic() - start_wait < 10.0:
                reader_code = get_reader_js()
                raw_snapshot = await page.evaluate_json(reader_code)
                if isinstance(raw_snapshot, dict) and raw_snapshot.get("found"):
                    break
                await asyncio.sleep(0.5)

            if not isinstance(raw_snapshot, dict) or not raw_snapshot.get("found"):
                print("Error: No chess board detected on active page.", file=sys.stderr)
                return 1

            snapshot = parse_snapshot(raw_snapshot)
            state = GameState.from_snapshot(snapshot, play_as=settings.play_as)
            board = chess.Board(state.fen)
            last_move = state.last_move
        finally:
            await cdp.close()

    if board.is_game_over():
        print(f"Position is game over ({board.result()}). No moves to analyze.")
        return 0

    print("=" * 60)
    print("CHESS-AUTOPLAYER ANALYSIS REPORT")
    print("=" * 60)
    print(f"Position FEN:    {board.fen()}")
    print(f"Turn:            {'White' if board.turn == chess.WHITE else 'Black'}")
    prof_desc = (
        f"{profile.name} (Elo={profile.elo or 'max'}, "
        f"limit={profile.time_limit}s, MultiPV={profile.multipv})"
    )
    print(f"Strength Profile:{prof_desc}")

    try:
        with Engine(settings.resolved_stockfish_path(), profile=profile) as engine:
            lines = engine.analyse(board)
    except EngineError as exc:
        print(f"Stockfish engine error: {exc}", file=sys.stderr)
        return 1

    if not lines:
        print("Engine returned no candidate lines.", file=sys.stderr)
        return 1

    decision = select_move(board, lines, profile=profile, rng=rng)
    think_time = compute_think_time(
        board=board,
        candidates=decision.candidates,
        chosen_move=decision.move,
        ply=board.ply(),
        last_move=last_move,
        speed=settings.speed,
        rng=rng,
    )

    print("-" * 60)
    print("Candidates:")
    for i, (line, loss) in enumerate(
        zip(decision.candidates, decision.losses, strict=True), start=1
    ):
        marker = "=>" if i - 1 == decision.chosen_index else "  "
        if line.mate_score is not None:
            score_desc = (
                f"Mate in {abs(line.mate_score)}"
                if line.mate_score > 0
                else f"Mated in {abs(line.mate_score)}"
            )
        else:
            score_desc = f"{line.score_cp / 100.0:+.2f} ({line.score_cp:+d} cp)"
        print(f"{marker} {i}. {line.move.uci():<6} | loss: {loss:4d} cp | eval: {score_desc}")

    print("-" * 60)
    print(f"Chosen Move:     {decision.move.uci()}")
    print(f"Decision Reason: {decision.reason}")
    print(f"Think Time:      {think_time:.2f}s")
    print("=" * 60)
    return 0


async def async_run(
    strength: str | None = None,
    speed: float | None = None,
    input_mode: str | None = None,
    move_style: str | None = None,
    seed: int | None = None,
    start_url: str | None = None,
) -> int:
    """Run autonomous chess bot loop."""
    base_settings = load_config()
    kwargs: dict[str, Any] = {}
    if strength is not None:
        kwargs["strength"] = strength
    if speed is not None:
        kwargs["speed"] = speed
    if input_mode is not None:
        kwargs["input_mode"] = input_mode
    if move_style is not None:
        kwargs["move_style"] = move_style
    if start_url is not None:
        kwargs["start_url"] = start_url

    settings = replace(base_settings, **kwargs)

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

    target_id = await find_or_create_chess_tab(cdp, settings.start_url)
    page = await ChessPage.attach(cdp, target_id)

    engine = Engine(settings.resolved_stockfish_path(), profile=settings.strength)
    try:
        engine.start()
    except EngineError as exc:
        print(f"Stockfish engine error: {exc}", file=sys.stderr)
        await cdp.close()
        return 1

    input_handler: MoveInput
    if settings.input_mode == "os":
        from chess_autoplayer.input.os_input import AccessibilityPermissionError, OSInput

        try:
            os_inp = OSInput(page)
            os_inp.verify_permissions()
            input_handler = os_inp
        except AccessibilityPermissionError as a_err:
            print(f"Accessibility Error: {a_err}", file=sys.stderr)
            engine.close()
            await cdp.close()
            return 1
    else:
        input_handler = CDPInput(page)

    rng = random.Random(seed) if seed is not None else random.Random()

    def on_event(event: BotEvent) -> None:
        if isinstance(event, StatusEvent):
            print(f"[{event.state.value}] {event.message}")
        elif isinstance(event, DecisionEvent):
            print(
                f"[DECISION] {event.move_san} "
                f"(eval: {event.eval_cp:+d} cp, think: {event.think_s:.2f}s)"
            )
        elif isinstance(event, MoveEvent):
            who = "bot" if event.by_bot else "opponent"
            print(f"[MOVE] ply {event.ply}: {event.san} ({who})")
        elif isinstance(event, GameOverEvent):
            print(f"[GAME OVER] {event.text}")
        elif isinstance(event, ErrorEvent):
            print(f"[ERROR] {event.message}", file=sys.stderr)

    controller = BotController(
        page=page,
        engine=engine,
        input_handler=input_handler,
        settings=settings,
        event_callback=on_event,
        rng=rng,
    )

    print(
        f"Starting chess-autoplayer (strength={settings.strength}, speed={settings.speed}, "
        f"input={settings.input_mode}, style={settings.move_style})..."
    )
    print("Press Ctrl+C to stop.")

    await controller.start()

    stop_future: asyncio.Future[None] = asyncio.get_running_loop().create_future()

    def _sig_handler() -> None:
        if not stop_future.done():
            stop_future.set_result(None)

    loop = asyncio.get_running_loop()
    try:
        import signal

        loop.add_signal_handler(signal.SIGINT, _sig_handler)
        loop.add_signal_handler(signal.SIGTERM, _sig_handler)
    except (NotImplementedError, RuntimeError):
        pass

    try:
        while not stop_future.done():
            await asyncio.sleep(0.5)
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        print("\nStopping bot...")
        await controller.stop()
        engine.close()
        await cdp.close()
        print("Shutdown complete. Chrome left open.")

    return 0


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

    # analyse subcommand
    analyse_parser = subparsers.add_parser(
        "analyse", help="Analyse board position with Stockfish and select human-like move"
    )
    analyse_parser.add_argument(
        "--fen",
        type=str,
        default=None,
        metavar="FEN",
        help="FEN string of position to analyse (if omitted, reads live browser board)",
    )
    analyse_parser.add_argument(
        "--strength",
        type=str,
        default=None,
        metavar="NAME",
        help="Strength profile: beginner, casual, club, strong, master, max",
    )
    analyse_parser.add_argument(
        "--seed",
        type=int,
        default=None,
        metavar="N",
        help="Random seed for move choice and think time selection",
    )
    analyse_parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose debug logging"
    )

    # run subcommand
    run_parser = subparsers.add_parser("run", help="Run autoplayer bot loop")
    run_parser.add_argument(
        "--strength",
        type=str,
        default=None,
        metavar="NAME",
        help="Strength profile: beginner, casual, club, strong, master, max",
    )
    run_parser.add_argument(
        "--speed",
        type=float,
        default=None,
        metavar="X",
        help="Speed multiplier (default: 1.0)",
    )
    run_parser.add_argument(
        "--input",
        dest="input_mode",
        choices=["cdp", "os"],
        default=None,
        help="Input mode: cdp (default) or os",
    )
    run_parser.add_argument(
        "--style",
        dest="move_style",
        choices=["drag", "click", "mixed"],
        default=None,
        help="Move style: drag, click, or mixed",
    )
    run_parser.add_argument(
        "--seed",
        type=int,
        default=None,
        metavar="N",
        help="Random seed for move choice and human mouse trajectories",
    )
    run_parser.add_argument(
        "--start-url",
        type=str,
        default=None,
        metavar="URL",
        help="Initial URL to attach to or navigate (default: https://www.chess.com/play/computer)",
    )
    run_parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose debug logging"
    )

    # gui subcommand (placeholder for brief 04)
    subparsers.add_parser("gui", help="Launch Tkinter desktop GUI (brief 04)")

    args = parser.parse_args()

    log_level = logging.DEBUG if getattr(args, "verbose", False) else logging.INFO
    setup_logging(console_level=log_level)

    if args.command == "probe":
        exit_code = asyncio.run(async_probe(save_fixture=args.save_fixture, output_json=args.json))
        sys.exit(exit_code)
    elif args.command == "analyse":
        exit_code = asyncio.run(
            async_analyse(
                fen=args.fen,
                strength=args.strength,
                seed=args.seed,
            )
        )
        sys.exit(exit_code)
    elif args.command == "run":
        exit_code = asyncio.run(
            async_run(
                strength=args.strength,
                speed=args.speed,
                input_mode=args.input_mode,
                move_style=args.move_style,
                seed=args.seed,
                start_url=args.start_url,
            )
        )
        sys.exit(exit_code)
    elif args.command == "gui":
        print("Subcommand 'gui' is not implemented yet (scheduled for brief 04).")
        sys.exit(0)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
