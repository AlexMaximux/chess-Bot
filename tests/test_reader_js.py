"""Tests for reader.js color detection, clock reading, and structured moves."""

import json
import subprocess
from typing import Any

from chess_autoplayer.board.reader import get_reader_js
from chess_autoplayer.board.snapshot import parse_snapshot

RUNNER_TEMPLATE = """
const window = {
  location: { href: "https://www.chess.com/play/online" },
  devicePixelRatio: 2,
  screenX: 0,
  screenY: 0,
  outerWidth: 1400,
  outerHeight: 900,
  innerWidth: 1200,
  innerHeight: 800,
  getComputedStyle: () => ({ display: "block", visibility: "visible", opacity: "1" })
};

const document = {
  elements: [],
  body: null,
  querySelector(sel) {
    const all = this.querySelectorAll(sel);
    return all.length > 0 ? all[0] : null;
  },
  querySelectorAll(sel) {
    const res = [];
    const selectors = sel.split(',').map(s => s.trim());
    for (const el of this.elements) {
      for (const s of selectors) {
        if (s.startsWith('#') && el.id === s.slice(1)) { res.push(el); break; }
        if (s.startsWith('.') && el.classList.has(s.slice(1))) { res.push(el); break; }
        if (s === el.tagName.toLowerCase()) { res.push(el); break; }
        if (s.includes('[') && s.includes('=')) {
          const m = s.match(/([a-zA-Z0-9_-]+)?\\s*\\[([a-zA-Z0-9_-]+)\\s*=\\s*["']?([^"']+)["']?\\]/);
          if (m) {
            const tag = m[1];
            const attr = m[2];
            const val = m[3];
            if (!tag || el.tagName.toLowerCase() === tag.toLowerCase()) {
              if (el.attributes[attr] === val) { res.push(el); break; }
            }
          }
        } else if (s.includes('[') && s.includes(']')) {
          const m = s.match(/([a-zA-Z0-9_-]+)?\\s*\\[([a-zA-Z0-9_-]+)\\]/);
          if (m) {
            const tag = m[1];
            const attr = m[2];
            if (!tag || el.tagName.toLowerCase() === tag.toLowerCase()) {
              if (el.attributes[attr] !== undefined) { res.push(el); break; }
            }
          }
        }
      }
    }
    return res;
  }
};

class MockEl {
  constructor(tag, id = "", classes = []) {
    this.tagName = tag.toUpperCase();
    this.id = id;
    this.classList = new Set(classes);
    this.classList.contains = (c) => this.classList.has(c);
    this.attributes = {};
    this.textContent = "";
    this.innerText = "";
    this.children = [];
    document.elements.push(this);
  }
  setAttribute(k, v) { this.attributes[k] = v; }
  getAttribute(k) { return this.attributes[k] || null; }
  getBoundingClientRect() {
    return { left: 0, top: 0, x: 0, y: 0, width: 400, height: 400 };
  }
  closest(s) { return null; }
  querySelector(s) {
    const all = this.querySelectorAll(s);
    return all.length > 0 ? all[0] : null;
  }
  querySelectorAll(s) {
    const res = [];
    const selectors = s.split(',').map(item => item.trim());
    for (const child of this.children) {
      for (const sel of selectors) {
        if (sel.startsWith('.') && child.classList.has(sel.slice(1))) { res.push(child); break; }
        if (sel.startsWith('#') && child.id === sel.slice(1)) { res.push(child); break; }
        if (sel === child.tagName.toLowerCase()) { res.push(child); break; }
        if (sel.includes('[data-cy="clock-time"]') && child.attributes['data-cy'] === 'clock-time') { res.push(child); break; }
      }
    }
    return res;
  }
}

// Run test DOM setup
__DOM_SETUP__

// Run reader script
const result = __READER_CODE__;
console.log(JSON.stringify(result));
"""


def run_reader_in_mock_dom(dom_setup_js: str) -> dict[str, Any]:
    reader_code = get_reader_js()
    script = RUNNER_TEMPLATE.replace("__DOM_SETUP__", dom_setup_js).replace(
        "__READER_CODE__", reader_code
    )
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        check=True,
    )
    res = json.loads(proc.stdout)
    return res if isinstance(res, dict) else {}


def test_reader_detects_our_color_matching_username_at_bottom() -> None:
    dom_setup = """
    const board = new MockEl('wc-chess-board', 'board-single');

    // Logged in user: 'alex' in meta tag
    const meta = new MockEl('meta');
    meta.setAttribute('name', 'user');
    meta.setAttribute('content', 'alex');

    // Top player is 'bob'
    const topPlayer = new MockEl('div', 'board-layout-player-top', ['board-layout-player-top']);
    topPlayer.innerText = 'bob (1500)';

    // Bottom player is 'alex'
    const botPlayer = new MockEl('div', 'board-layout-player-bottom', ['board-layout-player-bottom']);
    botPlayer.innerText = 'alex (1600)';
    """
    raw = run_reader_in_mock_dom(dom_setup)
    snap = parse_snapshot(raw)
    assert snap.found is True
    assert snap.our_color_hint == "w"


def test_reader_detects_our_color_matching_username_at_top() -> None:
    dom_setup = """
    const board = new MockEl('wc-chess-board', 'board-single');

    // Logged in user: 'alex'
    const meta = new MockEl('meta');
    meta.setAttribute('name', 'user');
    meta.setAttribute('content', 'alex');

    // Top player is 'alex'
    const topPlayer = new MockEl('div', 'board-layout-player-top', ['board-layout-player-top']);
    topPlayer.innerText = 'alex (1600)';

    // Bottom player is 'bob'
    const botPlayer = new MockEl('div', 'board-layout-player-bottom', ['board-layout-player-bottom']);
    botPlayer.innerText = 'bob (1500)';
    """
    raw = run_reader_in_mock_dom(dom_setup)
    snap = parse_snapshot(raw)
    assert snap.found is True
    # Top player when unflipped is Black ('b')
    assert snap.our_color_hint == "b"


def test_reader_fallback_to_board_geometry_when_username_not_found() -> None:
    dom_setup = """
    const board = new MockEl('wc-chess-board', 'board-single');
    // No logged in username
    const topPlayer = new MockEl('div', 'board-layout-player-top', ['board-layout-player-top']);
    topPlayer.innerText = 'opponent (1500)';
    const botPlayer = new MockEl('div', 'board-layout-player-bottom', ['board-layout-player-bottom']);
    botPlayer.innerText = 'player2 (1600)';
    """
    raw = run_reader_in_mock_dom(dom_setup)
    snap = parse_snapshot(raw)
    assert snap.found is True
    # When unflipped, bottom player is White
    assert snap.our_color_hint == "w"


def test_reader_reads_clocks_from_dom() -> None:
    dom_setup = """
    const board = new MockEl('wc-chess-board', 'board-single');

    const topPlayer = new MockEl('div', 'board-layout-player-top', ['board-layout-player-top']);
    const topClock = new MockEl('div', '', ['clock-component']);
    topClock.textContent = '09:45';
    topPlayer.children.push(topClock);

    const botPlayer = new MockEl('div', 'board-layout-player-bottom', ['board-layout-player-bottom']);
    const botClock = new MockEl('div', '', ['clock-component', 'clock-player-turn']);
    botClock.textContent = '04:12.8';
    botPlayer.children.push(botClock);
    """
    raw = run_reader_in_mock_dom(dom_setup)
    snap = parse_snapshot(raw)
    assert snap.clocks.top is not None
    assert snap.clocks.top.text == "09:45"
    assert snap.clocks.top.seconds == 585.0
    assert snap.clocks.top.ticking is False

    assert snap.clocks.bottom is not None
    assert snap.clocks.bottom.text == "04:12.8"
    assert snap.clocks.bottom.seconds == 252.8
    assert snap.clocks.bottom.ticking is True

    # White is bottom (252.8s), Black is top (585.0s)
    assert snap.clocks.white is not None and snap.clocks.white.seconds == 252.8
    assert snap.clocks.black is not None and snap.clocks.black.seconds == 585.0


def test_reader_reads_move_list_and_structured_output() -> None:
    dom_setup = """
    const board = new MockEl('wc-chess-board', 'board-single');

    const moveList = new MockEl('wc-simple-move-list');

    const m1 = new MockEl('span', '', ['node', 'white-move']);
    m1.textContent = 'e4';

    const m2 = new MockEl('span', '', ['node', 'black-move']);
    m2.textContent = 'e5';

    const m3 = new MockEl('span', '', ['node', 'white-move']);
    m3.textContent = 'Nf3';

    moveList.children.push(m1, m2, m3);
    """
    raw = run_reader_in_mock_dom(dom_setup)
    snap = parse_snapshot(raw)
    assert snap.moves == ["e4", "e5", "Nf3"]
    assert len(snap.structured_moves) == 3
    assert snap.structured_moves[0].ply == 1
    assert snap.structured_moves[0].san == "e4"
    assert snap.structured_moves[0].color == "w"
    assert snap.structured_moves[1].ply == 2
    assert snap.structured_moves[1].san == "e5"
    assert snap.structured_moves[1].color == "b"
    assert snap.structured_moves[2].ply == 3
    assert snap.structured_moves[2].san == "Nf3"
    assert snap.structured_moves[2].color == "w"


def test_reader_detects_game_over_buttons() -> None:
    dom_setup = """
    const board = new MockEl('wc-chess-board', 'board-single');

    const modal = new MockEl('div', '', ['game-over-modal']);
    const title = new MockEl('div', '', ['game-over-modal-title-component']);
    title.textContent = 'Checkmate - White wins';

    const rematchBtn = new MockEl('button', '', ['game-over-button-component']);
    rematchBtn.textContent = 'Rematch';
    rematchBtn.setAttribute('data-cy', 'game-over-rematch-button');

    const newGameBtn = new MockEl('button', '', ['game-over-button-component']);
    newGameBtn.textContent = 'New 3 min';
    newGameBtn.setAttribute('data-cy', 'new-game-button');
    """
    raw = run_reader_in_mock_dom(dom_setup)
    snap = parse_snapshot(raw)
    assert snap.game_over is True
    assert len(snap.game_over_buttons) >= 2
    types = [b.type for b in snap.game_over_buttons]
    assert "rematch" in types
    assert "new_game" in types
