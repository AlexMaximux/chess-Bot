#!/usr/bin/env python3
"""Run a single session of chess-autoplayer that plays two games in a row.

The first game is played to completion (GAME_OVER).
The script then triggers the second game externally (as required by Review 03-r1 item 1).
The bot detects the new game, resets its state, and plays the second game to completion.
All logs are saved to docs/live-runs/two_games_session.log.
"""

import asyncio
import subprocess
import sys
import time
from pathlib import Path

from chess_autoplayer.chrome.cdp import CDPClient
from chess_autoplayer.chrome.launcher import launch_or_attach_chrome
from chess_autoplayer.chrome.page import ChessPage, find_or_create_chess_tab
from chess_autoplayer.config import load_config


async def trigger_new_game(page: ChessPage) -> bool:
    """Click Rematch / Play Again / New Game or click Play button on computer page."""
    # Try finding rematch or play again button
    clicked = await page.evaluate_json("""
        (() => {
            const btns = Array.from(document.querySelectorAll('button, a'));
            const rematchBtn = btns.find(b => {
                const label = (b.innerText || b.getAttribute('aria-label') || '');
                return /rematch|play again|new game/i.test(label);
            });
            if (rematchBtn) {
                rematchBtn.click();
                return 'rematch_clicked';
            }
            const playBtn = btns.find(b => b.innerText && b.innerText.trim() === 'Play');
            if (playBtn) {
                playBtn.click();
                return 'play_clicked';
            }
            return 'none';
        })()
    """)
    return clicked in ("rematch_clicked", "play_clicked")


async def main() -> int:
    log_dir = Path("docs/live-runs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "two_games_session.log"

    print("=== Two Games in One Session Live Test ===")
    print(f"Log will be saved to: {log_file}")

    # Start Chrome and ensure computer tab is ready
    settings = load_config()
    ws_url = await launch_or_attach_chrome(settings)
    cdp = await CDPClient.connect(ws_url)
    target_id = await find_or_create_chess_tab(cdp, settings.start_url)
    page = await ChessPage.attach(cdp, target_id)

    # Ensure a game can start: if 'Play' button is visible, click it
    await page.evaluate_json("""
        (() => {
            const btns = Array.from(document.querySelectorAll('button'));
            const playBtn = btns.find(b => b.innerText && b.innerText.trim() === 'Play');
            if (playBtn) playBtn.click();
        })()
    """)
    await asyncio.sleep(1.0)

    # Launch chess-autoplayer run process with stdout/stderr piped to log_file
    print("Launching 'uv run chess-autoplayer run --strength club --speed 2.5' ...")
    with open(log_file, "w") as f_out:
        proc = subprocess.Popen(
            ["uv", "run", "chess-autoplayer", "run", "--strength", "club", "--speed", "2.5"],
            stdout=f_out,
            stderr=subprocess.STDOUT,
            text=True,
        )

    try:
        # Monitor log file for Game 1 completion
        print("Monitoring Game 1 progress...")
        game1_over = False
        t_start = time.time()
        while time.time() - t_start < 240:  # 4 minutes max for Game 1
            if proc.poll() is not None:
                print(f"ERROR: Process exited prematurely with code {proc.returncode}")
                return 1

            if log_file.exists():
                text = log_file.read_text()
                if "State: GAME_OVER" in text or "Game Over" in text or "Checkmate" in text:
                    print("Game 1 finished (GAME_OVER detected in log)!")
                    game1_over = True
                    break
            await asyncio.sleep(2.0)

        if not game1_over:
            print("ERROR: Timeout waiting for Game 1 to finish.")
            return 1

        print("Waiting 4 seconds in GAME_OVER state to verify latching...")
        await asyncio.sleep(4.0)

        print("Triggering Game 2 externally via dev script...")
        triggered = await trigger_new_game(page)
        print(f"Trigger action result: {triggered}")
        await asyncio.sleep(1.5)

        # Monitor log file for Game 2 completion
        print("Monitoring Game 2 progress...")
        game2_started = False
        game2_over = False
        t_start2 = time.time()
        while time.time() - t_start2 < 240:  # 4 minutes max for Game 2
            if proc.poll() is not None:
                print(f"ERROR: Process exited prematurely with code {proc.returncode}")
                return 1

            if log_file.exists():
                text = log_file.read_text()
                if "New game detected" in text and not game2_started:
                    print("Bot detected New Game and reset state successfully!")
                    game2_started = True

                # Check if second game over occurred
                count_game_over = text.count("State: GAME_OVER")
                if count_game_over >= 2 and game2_started:
                    print("Game 2 finished (Second GAME_OVER detected in log)!")
                    game2_over = True
                    break
            await asyncio.sleep(2.0)

        if not game2_over:
            print("ERROR: Timeout waiting for Game 2 to finish.")
            return 1

        print("Both games completed successfully in a single session!")
        return 0

    finally:
        print("Stopping autoplayer process...")
        proc.terminate()
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc.kill()
        await cdp.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
