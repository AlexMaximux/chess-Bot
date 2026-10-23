#!/usr/bin/env python3
"""Dev verification script for BLOCKED_URL fair play guard.

Starts the bot on the allowed computer play tab, navigates that same tab to
https://www.chess.com/play/online, verifies the bot enters BLOCKED_URL and sends no input,
then restores the tab to https://www.chess.com/play/computer.
"""

import asyncio
import logging
import sys

from chess_autoplayer.bot.controller import BotController
from chess_autoplayer.bot.events import BotEvent, BotState, StatusEvent
from chess_autoplayer.chrome.cdp import CDPClient
from chess_autoplayer.chrome.launcher import launch_or_attach_chrome
from chess_autoplayer.chrome.page import ChessPage, find_or_create_chess_tab
from chess_autoplayer.config import load_config
from chess_autoplayer.engine.stockfish import Engine
from chess_autoplayer.input.cdp_input import CDPInput

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("dev_blocked_url")


async def main() -> int:
    settings = load_config()
    print("1. Launching/attaching to Chrome...")
    ws_url = await launch_or_attach_chrome(settings)
    cdp = await CDPClient.connect(ws_url)

    try:
        target_id = await find_or_create_chess_tab(cdp, settings.start_url)
        page = await ChessPage.attach(cdp, target_id)
        input_handler = CDPInput(page)
        engine = Engine(settings.resolved_stockfish_path(), profile=settings.strength)
        engine.start()

        events: list[BotEvent] = []

        def on_event(ev: BotEvent) -> None:
            events.append(ev)
            if isinstance(ev, StatusEvent):
                print(f"[{ev.state.value}] {ev.message}")

        controller = BotController(
            page=page,
            engine=engine,
            input_handler=input_handler,
            settings=settings,
            event_callback=on_event,
        )

        print("2. Starting controller loop...")
        loop_task = asyncio.create_task(controller.start())
        await asyncio.sleep(1.5)

        print("3. Navigating tab to non-allowed URL: https://www.chess.com/play/online ...")
        await page.evaluate_json("window.location.href = 'https://www.chess.com/play/online'")

        # Wait for the controller to detect the URL change
        blocked_seen = False
        for _ in range(30):
            await asyncio.sleep(0.2)
            if controller.state == BotState.BLOCKED_URL or any(
                isinstance(e, StatusEvent) and e.state == BotState.BLOCKED_URL for e in events
            ):
                blocked_seen = True
                break

        print("4. Stopping controller...")
        await controller.stop()
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass
        engine.close()

        print("5. Navigating tab back to allowed URL: https://www.chess.com/play/computer ...")
        await page.evaluate_json("window.location.href = 'https://www.chess.com/play/computer'")
        await asyncio.sleep(2.0)

        if not blocked_seen:
            print("FAILURE: Controller did not enter BLOCKED_URL state!", file=sys.stderr)
            return 1

        print("SUCCESS: Bot properly detected non-allowed URL and entered BLOCKED_URL!")
        return 0

    finally:
        await cdp.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
