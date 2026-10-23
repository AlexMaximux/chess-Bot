#!/usr/bin/env python3
"""DOM Inspector & Debug Dumper for live chess.com pages.

Connects to the active chess.com tab in Chrome via CDP, dumps the full outerHTML
to debug/page.html, evaluates every selector used by reader.js, collects live samples
for clocks, move list, players, and game over buttons, runs reader.js to obtain the
parsed state, and outputs a complete diagnostic report in debug/report.json.

Usage:
    ./.venv/bin/python tools/dump_dom.py
    ./.venv/bin/python tools/dump_dom.py --port 9222
    ./.venv/bin/python tools/dump_dom.py --launch
"""

import argparse
import asyncio
import json
import logging
from pathlib import Path
import re
import sys
import time
from typing import Any

# Ensure project src is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from chess_autoplayer.board.reader import get_reader_js
from chess_autoplayer.chrome.cdp import CDPClient, CDPError
from chess_autoplayer.chrome.launcher import get_browser_ws_url, launch_or_attach_chrome
from chess_autoplayer.chrome.page import ChessPage
from chess_autoplayer.config import load_config

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
logger = logging.getLogger("dump_dom")


def extract_selectors_from_reader_js(reader_js_code: str) -> dict[str, list[str]]:
    """Dynamically parse and extract all CSS selectors referenced in reader.js.

    Categorizes them into logical domains for structured reporting.
    """
    # 1. Extract querySelector / querySelectorAll calls
    qs_calls = re.findall(
        r"querySelector(?:All)?\s*\(\s*([\"\x27\`][\s\S]*?[\"\x27\`])\s*\)",
        reader_js_code,
    )
    raw_selectors: list[str] = []
    for c in qs_calls:
        c = c.strip()
        if (
            (c.startswith("\x27") and c.endswith("\x27"))
            or (c.startswith("\"") and c.endswith("\""))
            or (c.startswith("`") and c.endswith("`"))
        ):
            c = c[1:-1].strip()
        if c and "${" not in c:
            raw_selectors.append(c)

    # 2. Extract arrays of selectors (e.g. gameOverSelectors, goBtnSelectors)
    for name in ["gameOverSelectors", "goBtnSelectors"]:
        m = re.search(rf"{name}\s*=\s*\[([\s\S]*?)\];", reader_js_code)
        if m:
            for line in m.group(1).split("\n"):
                cleaned = line.strip().rstrip(",").strip("\x27").strip("\"").strip()
                if cleaned and any(
                    ch in cleaned for ch in [".", "#", "[", "button", "text", "wc-", ":"]
                ):
                    raw_selectors.append(cleaned)

    # 3. Categorize selectors and include individual sub-selectors if composite
    categories: dict[str, list[str]] = {
        "board_and_pieces": [],
        "coordinates_and_geometry": [],
        "players_and_usernames": [],
        "clocks": [],
        "moves_and_notation": [],
        "game_over_modals": [],
        "game_over_buttons": [],
        "promotion": [],
        "other": [],
    }

    seen: set[str] = set()

    def add_selector(sel: str, cat: str) -> None:
        sel = sel.strip()
        if not sel or sel in seen:
            return
        seen.add(sel)
        categories[cat].append(sel)

    for raw in raw_selectors:
        low = raw.lower()
        if "coordinate" in low:
            target_cat = "coordinates_and_geometry"
        elif "clock" in low:
            target_cat = "clocks"
        elif "move" in low or "ply" in low or "figurine" in low:
            target_cat = "moves_and_notation"
        elif "rematch" in low or ("button" in low and ("game" in low or "ui_v5" in low)):
            target_cat = "game_over_buttons"
        elif "game-over" in low or "modal" in low or "dialog" in low:
            target_cat = "game_over_modals"
        elif (
            "player" in low
            or "user" in low
            or "member" in low
            or "profile" in low
            or "bot" in low
            or "side" in low
        ):
            target_cat = "players_and_usernames"
        elif "promotion" in low:
            target_cat = "promotion"
        elif (
            "board" in low
            or "piece" in low
            or "square" in low
            or "highlight" in low
        ):
            target_cat = "board_and_pieces"
        else:
            target_cat = "other"

        # Add composite
        add_selector(raw, target_cat)

        # If composite with commas, also evaluate each individual selector
        if "," in raw:
            parts = [p.strip() for p in raw.split(",") if p.strip()]
            for p in parts:
                add_selector(p, target_cat)

    return categories


BATCH_SELECTOR_EVAL_JS = """
((selectors) => {
  const results = {};
  for (const sel of selectors) {
    try {
      const els = Array.from(document.querySelectorAll(sel));
      results[sel] = {
        found: els.length > 0,
        count: els.length,
        samples: els.slice(0, 3).map(el => {
          const s = window.getComputedStyle(el);
          const isVisible = s && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
          const r = el.getBoundingClientRect();
          const attrs = {};
          for (const attr of ['id', 'class', 'data-cy', 'data-figurine', 'data-piece', 'data-user-username', 'data-username', 'href', 'content']) {
            if (el.hasAttribute && el.hasAttribute(attr)) {
              attrs[attr] = el.getAttribute(attr);
            }
          }
          return {
            tag: el.tagName.toLowerCase(),
            text: (el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 120),
            visible: Boolean(isVisible),
            rect: {
              x: Math.round(r.x !== undefined ? r.x : r.left),
              y: Math.round(r.y !== undefined ? r.y : r.top),
              width: Math.round(r.width),
              height: Math.round(r.height)
            },
            attrs: attrs
          };
        })
      };
    } catch (err) {
      results[sel] = {
        found: false,
        count: 0,
        error: String(err),
        samples: []
      };
    }
  }
  return results;
})
"""


DEEP_INSPECTION_JS = """
(() => {
  // 1. Clocks inspection
  const topPlayerEl = document.querySelector('#board-layout-player-top, .board-layout-player-top');
  const botPlayerEl = document.querySelector('#board-layout-player-bottom, .board-layout-player-bottom');

  function getClockInfo(playerEl, label) {
    if (!playerEl) return { label, found: false, text: null, ticking: false, classes: [], htmlSample: null };
    const clockEl = playerEl.querySelector(
      '.clock-component, .clock-time, [data-cy="clock-time"], .clock-player-turn, [class*="clock-"]'
    );
    if (!clockEl) {
      return { label, found: false, text: null, ticking: false, classes: [], htmlSample: null };
    }
    const timeEl = clockEl.querySelector('.clock-time, [data-cy="clock-time"]') || clockEl;
    const text = (timeEl.textContent || '').trim();
    const ticking = clockEl.classList.contains('clock-player-turn') ||
                    clockEl.classList.contains('clock-ticking') ||
                    clockEl.classList.contains('running') ||
                    (playerEl && playerEl.classList.contains('clock-player-turn')) ||
                    Boolean(clockEl.closest && clockEl.closest('.clock-player-turn'));
    return {
      label,
      found: true,
      text: text || null,
      ticking: Boolean(ticking),
      classes: Array.from(clockEl.classList),
      htmlSample: clockEl.outerHTML.slice(0, 250)
    };
  }

  const clockTop = getClockInfo(topPlayerEl, 'top');
  const clockBot = getClockInfo(botPlayerEl, 'bottom');

  const extraClocks = Array.from(document.querySelectorAll(
    '.board-layout-clock-top, .board-layout-clock-bottom, .clock-component, .clock-top, .clock-bottom, [data-cy*="clock"]'
  )).map(el => ({
    tag: el.tagName.toLowerCase(),
    class: el.className,
    text: (el.textContent || '').trim()
  }));

  // 2. Moves inspection
  const moveListContainer = document.querySelector(
    'wc-simple-move-list, wc-vertical-move-list, .move-list, .vertical-move-list'
  );

  let movesData = {
    found: false,
    containerTag: null,
    totalPlies: 0,
    first5: [],
    last5: [],
    rawTextSample: null
  };

  if (moveListContainer) {
    const hasMainLine = moveListContainer.querySelector('.main-line-ply') !== null;
    const plySelector = hasMainLine
      ? '.node.main-line-ply'
      : '.node.white-move, .node.black-move, .node, .move-text';
    const moveNodes = Array.from(moveListContainer.querySelectorAll(plySelector));

    const sampleMoves = moveNodes.map((node, idx) => {
      const figurineEl = node.querySelector('[data-figurine]');
      const prefix = figurineEl ? (figurineEl.getAttribute('data-figurine') || '') : '';
      const contentEl = node.querySelector('.node-highlight-content') || node;
      let text = (contentEl.textContent || '').trim();
      if (prefix && !text.startsWith(prefix)) text = prefix + text;
      text = text.replace(/[!?]+/g, '').trim();
      const timeEl = node.querySelector('.time, [data-time], .node-time');
      return {
        ply: idx + 1,
        san: text,
        time: timeEl ? (timeEl.textContent || '').trim() : null
      };
    });

    movesData = {
      found: true,
      containerTag: moveListContainer.tagName.toLowerCase(),
      totalPlies: moveNodes.length,
      first5: sampleMoves.slice(0, 5),
      last5: sampleMoves.length > 5 ? sampleMoves.slice(-5) : sampleMoves,
      rawTextSample: (moveListContainer.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 200)
    };
  }

  // 3. Player names inspection
  const metaUser = document.querySelector('meta[name="user"]');
  let contextUser = null;
  if (typeof window !== 'undefined' && window.context && window.context.user) {
    contextUser = {
      id: window.context.user.id || null,
      username: window.context.user.username || null
    };
  }
  const dataUserEl = document.querySelector('[data-user-username], [data-username]');

  function inspectPlayer(el, pos) {
    if (!el) return { position: pos, found: false };
    const usernameEl = el.querySelector(
      '.user-username-component, .user-tagline-username, [data-test-element="user-tagline-username"], .user-username, a.user-username-link'
    );
    const ratingEl = el.querySelector('.user-tagline-rating, .user-rating, [data-test-element="user-tagline-rating"]');
    return {
      position: pos,
      found: true,
      username: usernameEl ? (usernameEl.textContent || '').trim() : null,
      rating: ratingEl ? (ratingEl.textContent || '').trim() : null,
      rawText: (el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 150),
      htmlSample: el.outerHTML.slice(0, 250)
    };
  }

  const playersData = {
    detectedLoggedInUser: {
      meta: metaUser ? metaUser.getAttribute('content') : null,
      windowContext: contextUser,
      dataAttr: dataUserEl ? (dataUserEl.getAttribute('data-user-username') || dataUserEl.getAttribute('data-username')) : null
    },
    top: inspectPlayer(topPlayerEl, 'top'),
    bottom: inspectPlayer(botPlayerEl, 'bottom')
  };

  // 4. Game Over & Buttons
  const gameOverModal = document.querySelector(
    '.game-over-modal-header-component, .game-over-modal-title-component, .game-over-modal-shell-container, .game-over-modal, [data-cy="game-over-modal"], .modal-game-over-component, .game-over-header, .game-over-dialog'
  );
  const titleEl = document.querySelector('.game-over-modal-title-component');
  const subEl = document.querySelector('.game-over-modal-subtitle-component');

  const buttons = [];
  const candidateBtns = Array.from(document.querySelectorAll(
    'button[data-cy*="game"], button[data-cy*="rematch"], button[data-cy*="play-again"], button[data-cy="new-game-button"], button.game-over-button-component, button.game-over-rematch-button, .game-over-modal-buttons-component button, .game-over-modal button, .game-over-dialog button, .modal-game-over-component button, button, a.ui_v5-button-component'
  ));

  candidateBtns.forEach(btn => {
    const text = (btn.textContent || '').trim().replace(/\\s+/g, ' ');
    const dataCy = btn.getAttribute('data-cy') || '';
    const lower = text.toLowerCase();
    const isRelevant = lower.includes('rematch') || lower.includes('new') || lower.includes('play again') || lower.includes('next') || dataCy.includes('game') || dataCy.includes('rematch');
    if (!isRelevant) return;

    const s = window.getComputedStyle(btn);
    const visible = s && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
    const r = btn.getBoundingClientRect();
    buttons.push({
      text: text,
      dataCy: dataCy || null,
      visible: Boolean(visible),
      rect: {
        x: Math.round(r.x !== undefined ? r.x : r.left),
        y: Math.round(r.y !== undefined ? r.y : r.top),
        width: Math.round(r.width),
        height: Math.round(r.height)
      }
    });
  });

  return {
    clocks: {
      top: clockTop,
      bottom: clockBot,
      extra: extraClocks
    },
    moves: movesData,
    players: playersData,
    gameOver: {
      modalFound: Boolean(gameOverModal),
      title: titleEl ? (titleEl.textContent || '').trim() : null,
      subtitle: subEl ? (subEl.textContent || '').trim() : null,
      buttons: buttons
    }
  };
})()
"""


async def run_inspector(
    port: int | None = None,
    target_id: str | None = None,
    url_filter: str = "chess.com",
    auto_launch: bool = False,
    label: str | None = None,
) -> dict[str, Any]:
    """Connect to Chrome, inspect active chess.com tab, and generate report."""
    settings = load_config()

    # 1. Verify / connect to Chrome debug port (auto-detect between config port and 9222)
    candidate_ports = [port] if port is not None else [settings.debug_port, 9222]
    ws_url = None
    connected_port = None

    for p in candidate_ports:
        ws_url = await get_browser_ws_url(p, timeout=1.0)
        if ws_url:
            connected_port = p
            break

    if not ws_url:
        target_port = port or settings.debug_port
        if auto_launch:
            print(f"[!] Chrome debug port {target_port} is not answering. Attempting auto-launch...")
            ws_url = await launch_or_attach_chrome(settings)
            connected_port = settings.debug_port
        else:
            print(f"\n[ERROR] Chrome debug port {target_port} is not answering.")
            print("To start Google Chrome with remote debugging on macOS, run:")
            print(f'  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --remote-debugging-port={target_port}\n')
            print("Or run this tool with --launch to start it automatically:")
            print("  ./.venv/bin/python tools/dump_dom.py --launch\n")
            sys.exit(1)

    print(f"[*] Connected to Chrome debugger on port {connected_port}: {ws_url}")
    cdp = await CDPClient.connect(ws_url)


    # 2. Enumerate tabs
    targets_res = await cdp.send("Target.getTargets")
    target_infos = targets_res.get("targetInfos", [])
    page_targets = [t for t in target_infos if t.get("type") == "page"]

    if not page_targets:
        print("[ERROR] No page tabs found in Chrome.")
        sys.exit(1)

    # Filter chess.com tabs
    matching_tabs = [
        t for t in page_targets if url_filter in (t.get("url") or "").lower()
    ]

    chosen_tab: dict[str, Any] | None = None
    if target_id:
        for t in page_targets:
            if t.get("targetId") == target_id:
                chosen_tab = t
                break
        if not chosen_tab:
            print(f"[ERROR] Specified target-id {target_id} not found.")
            sys.exit(1)
    elif matching_tabs:
        # Prioritize live games / play online / computer
        def tab_score(tab: dict[str, Any]) -> int:
            u = (tab.get("url") or "").lower()
            if "/game/live" in u:
                return 4
            if "/play/online" in u:
                return 3
            if "/live" in u:
                return 2
            if "/play/computer" in u:
                return 1
            return 0

        matching_tabs.sort(key=tab_score, reverse=True)
        chosen_tab = matching_tabs[0]
    else:
        print("\n[ERROR] No active chess.com tab found in Chrome!")
        print("Available tabs:")
        for t in page_targets:
            print(f"  - [{t.get('targetId')}] {t.get('title')} ({t.get('url')})")
        print("\nPlease open https://www.chess.com in Chrome and try again.\n")
        sys.exit(1)

    chosen_target_id = str(chosen_tab.get("targetId"))
    chosen_url = str(chosen_tab.get("url"))
    chosen_title = str(chosen_tab.get("title"))

    print(f"\n[*] Inspecting Tab:")
    print(f"    Target ID: {chosen_target_id}")
    print(f"    Title:     {chosen_title}")
    print(f"    URL:       {chosen_url}\n")

    # 3. Attach page & isolated world
    page = await ChessPage.attach(cdp, chosen_target_id)

    # 4. Wait for page to finish loading if it's currently initializing
    print("[*] Waiting for page to load completely...")
    for _ in range(20):
        is_ready = await page.evaluate_json(
            "document.readyState === 'complete' && Boolean(document.body && document.body.children.length > 0)"
        )
        if is_ready:
            break
        await asyncio.sleep(0.5)

    # 5. Dump outerHTML
    print("[*] Capturing full outerHTML...")
    outer_html = await page.evaluate_json("document.documentElement.outerHTML")
    if not isinstance(outer_html, str):
        outer_html = ""

    debug_dir = PROJECT_ROOT / "debug"
    if label:
        debug_dir = debug_dir / label
    debug_dir.mkdir(parents=True, exist_ok=True)
    html_file = debug_dir / "page.html"
    html_file.write_text(outer_html, encoding="utf-8")
    html_size_kb = len(outer_html.encode("utf-8")) / 1024
    print(f"    -> Saved {html_size_kb:.1f} KB to {html_file.relative_to(PROJECT_ROOT)}")


    # 5. Extract selectors from reader.js
    reader_js = get_reader_js()
    categories = extract_selectors_from_reader_js(reader_js)
    all_selectors: list[str] = []
    for cat_list in categories.values():
        all_selectors.extend(cat_list)
    all_selectors = sorted(set(all_selectors))

    print(f"[*] Evaluating {len(all_selectors)} selectors extracted from reader.js...")
    eval_call_expr = f"({BATCH_SELECTOR_EVAL_JS})({json.dumps(all_selectors)})"
    selector_results = await page.evaluate_json(eval_call_expr)
    if not isinstance(selector_results, dict):
        selector_results = {}

    # 6. Deep inspections (clocks, moves, players, game over buttons)
    print("[*] Running targeted deep inspections (clocks, moves, players, buttons)...")
    deep_inspection_result = await page.evaluate_json(DEEP_INSPECTION_JS)
    if not isinstance(deep_inspection_result, dict):
        deep_inspection_result = {}

    # 7. Run reader.js directly for end-to-end parsed state
    print("[*] Running reader.js directly on active tab...")
    reader_result = await page.evaluate_json(reader_js)
    if not isinstance(reader_result, dict):
        reader_result = {}

    # 8. Compute statistics
    found_count = sum(1 for res in selector_results.values() if res.get("found"))
    missing_count = len(all_selectors) - found_count

    category_stats: dict[str, dict[str, int]] = {}
    for cat_name, sel_list in categories.items():
        cat_found = sum(
            1 for s in sel_list if selector_results.get(s, {}).get("found")
        )
        category_stats[cat_name] = {
            "total": len(sel_list),
            "found": cat_found,
            "missing": len(sel_list) - cat_found,
        }

    # 9. Build comprehensive report
    report: dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "tab": {
            "targetId": chosen_target_id,
            "title": chosen_title,
            "url": chosen_url,
        },
        "summary": {
            "total_selectors": len(all_selectors),
            "found_selectors": found_count,
            "missing_selectors": missing_count,
            "category_stats": category_stats,
        },
        "inspections": deep_inspection_result,
        "reader_js_parsed_state": reader_result,
        "selectors": selector_results,
    }

    report_file = debug_dir / "report.json"
    report_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"    -> Saved diagnostic report to {report_file.relative_to(PROJECT_ROOT)}\n")

    # 10. Print structured console summary
    _print_console_summary(report, categories, selector_results, label=label)

    return report


def _print_console_summary(
    report: dict[str, Any],
    categories: dict[str, list[str]],
    selector_results: dict[str, Any],
    label: str | None = None,
) -> None:
    """Print readable, formatted inspection summary to terminal."""
    inspections = report.get("inspections", {})
    reader_state = report.get("reader_js_parsed_state", {})

    print("=" * 72)
    print("                     DOM INSPECTION REPORT")
    print("=" * 72)

    # Board state
    print("\n[+] BOARD STATUS:")
    board_found = reader_state.get("found", False)
    if board_found:
        brect = reader_state.get("boardRect", {})
        print(f"    Board Element:  FOUND ({brect.get('width')}x{brect.get('height')} px)")
        print(f"    Orientation:    {'FLIPPED (Black bottom)' if reader_state.get('flippedGeometry') else 'NORMAL (White bottom)'}")
        print(f"    Our Color Hint: {reader_state.get('ourColorHint')}")
        print(f"    Pieces on Board: {len(reader_state.get('pieces', []))}")
    else:
        print("    Board Element:  NOT FOUND (or not on active game view)")

    # Players
    print("\n[+] PLAYERS & IDENTITIES:")
    p_info = inspections.get("players", {})
    logged = p_info.get("detectedLoggedInUser", {})
    print(f"    Logged-in User: meta={logged.get('meta')} | context={logged.get('windowContext')} | data={logged.get('dataAttr')}")
    top_p = p_info.get("top", {})
    bot_p = p_info.get("bottom", {})
    print(f"    Top Player:     username='{top_p.get('username')}' rating='{top_p.get('rating')}' (found={top_p.get('found')})")
    print(f"    Bottom Player:  username='{bot_p.get('username')}' rating='{bot_p.get('rating')}' (found={bot_p.get('found')})")

    # Clocks
    print("\n[+] CLOCKS (ساعت):")
    c_info = inspections.get("clocks", {})
    top_c = c_info.get("top", {})
    bot_c = c_info.get("bottom", {})
    print(f"    Top Clock:      text='{top_c.get('text')}' ticking={top_c.get('ticking')} (found={top_c.get('found')})")
    print(f"    Bottom Clock:   text='{bot_c.get('text')}' ticking={bot_c.get('ticking')} (found={bot_c.get('found')})")
    reader_clocks = reader_state.get("clocks", {})
    if reader_clocks:
        w_c = reader_clocks.get("white", {})
        b_c = reader_clocks.get("black", {})
        print(f"    reader.js parsed: White={w_c.get('seconds')}s (text='{w_c.get('text')}') | Black={b_c.get('seconds')}s (text='{b_c.get('text')}')")

    # Moves
    print("\n[+] MOVE LIST (لیست حرکات):")
    m_info = inspections.get("moves", {})
    if m_info.get("found"):
        print(f"    Container:      <{m_info.get('containerTag')}> (total plies: {m_info.get('totalPlies')})")
        first5 = [f"{m.get('san')} ({m.get('time') or '-'})" for m in m_info.get("first5", [])]
        print(f"    First moves:    {', '.join(first5) if first5 else 'None'}")
        if m_info.get("totalPlies", 0) > 5:
            last5 = [f"{m.get('san')} ({m.get('time') or '-'})" for m in m_info.get("last5", [])]
            print(f"    Last moves:     {', '.join(last5)}")
    else:
        print("    Container:      NOT FOUND (no move list on page)")

    # Game Over & Buttons
    print("\n[+] GAME OVER & BUTTONS (دکمه‌های پایان بازی):")
    go_info = inspections.get("gameOver", {})
    print(f"    Game Over Modal: {'FOUND' if go_info.get('modalFound') else 'NOT DETECTED'}")
    if go_info.get("title") or go_info.get("subtitle"):
        print(f"    Modal Text:      '{go_info.get('title')}' - '{go_info.get('subtitle')}'")
    buttons = go_info.get("buttons", [])
    print(f"    Candidate Buttons ({len(buttons)}):")
    for btn in buttons:
        vis = "VISIBLE" if btn.get("visible") else "HIDDEN"
        rect = btn.get("rect", {})
        print(f"      - [{vis}] '{btn.get('text')}' (data-cy='{btn.get('dataCy')}', rect={rect.get('width')}x{rect.get('height')})")

    # Selectors Evaluation Summary
    print("\n[+] SELECTORS EVALUATION BY CATEGORY:")
    for cat, sel_list in categories.items():
        found_in_cat = [s for s in sel_list if selector_results.get(s, {}).get("found")]
        missing_in_cat = [s for s in sel_list if not selector_results.get(s, {}).get("found")]
        print(f"\n  --- Category: {cat} ({len(found_in_cat)}/{len(sel_list)} found) ---")
        for s in found_in_cat:
            count = selector_results[s].get("count", 0)
            sample_text = ""
            samples = selector_results[s].get("samples", [])
            if samples and samples[0].get("text"):
                sample_text = f" -> text='{samples[0]['text'][:40]}'"
            print(f"    [✓ FOUND ({count})] {s}{sample_text}")
        for s in missing_in_cat:
            print(f"    [✗ MISSING]    {s}")

    print("\n" + "=" * 72)
    print("Files created:")
    prefix = f"debug/{label}/" if label else "debug/"
    print(f"  1. {prefix}page.html   (Full live HTML DOM snapshot)")
    print(f"  2. {prefix}report.json (Structured diagnostic results & real samples)")
    print("=" * 72 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Live DOM Inspector & Dumper for chess.com")
    parser.add_argument("--port", type=int, default=None, help="Chrome CDP debugging port (default: auto-detect 9333 or 9222)")
    parser.add_argument("--target-id", type=str, default=None, help="Target ID of specific tab to inspect")
    parser.add_argument("--url", type=str, default="chess.com", help="URL substring filter for target tab (default: chess.com)")
    parser.add_argument("--launch", action="store_true", help="Launch Chrome automatically if not running")
    parser.add_argument(
        "--label",
        type=str,
        choices=["lobby", "game", "gameover"],
        default=None,
        help="Subdirectory label for output in debug/<label>/ (lobby, game, gameover)",
    )
    args = parser.parse_args()

    asyncio.run(
        run_inspector(
            port=args.port,
            target_id=args.target_id,
            url_filter=args.url,
            auto_launch=args.launch,
            label=args.label,
        )
    )


if __name__ == "__main__":
    main()
