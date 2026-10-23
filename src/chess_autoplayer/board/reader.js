(() => {
  const url = window.location.href;
  const boardEl = document.querySelector('wc-chess-board') ||
                  document.querySelector('#board-play-computer') ||
                  document.querySelector('.board');

  const winInfo = {
    screenX: window.screenX || 0,
    screenY: window.screenY || 0,
    outerWidth: window.outerWidth || 0,
    outerHeight: window.outerHeight || 0,
    innerWidth: window.innerWidth || 0,
    innerHeight: window.innerHeight || 0
  };

  const dpr = window.devicePixelRatio || 1;

  if (!boardEl) {
    return {
      url: url,
      found: false,
      boardRect: { x: 0, y: 0, width: 0, height: 0 },
      flippedClass: false,
      flippedGeometry: false,
      pieces: [],
      moves: [],
      structuredMoves: [],
      clocks: {
        top: { text: null, seconds: null, ticking: false, color: null },
        bottom: { text: null, seconds: null, ticking: false, color: null },
        white: { text: null, seconds: null, ticking: false, color: 'w' },
        black: { text: null, seconds: null, ticking: false, color: 'b' }
      },
      lastMoveHighlights: [],
      gameOver: false,
      gameOverText: null,
      gameOverButtons: [],
      promotionOpen: false,
      promotionOptions: [],
      devicePixelRatio: dpr,
      window: winInfo,
      dragging: false,
      ourColorHint: null,
      hasResignButton: false,
      hasDrawButton: false,
      hasMoveList: false,
      hasStartButton: false,
      startGameButton: null
    };
  }

  const rect = boardEl.getBoundingClientRect();
  const boardRect = {
    x: rect.left,
    y: rect.top,
    width: rect.width,
    height: rect.height
  };

  const flippedClass = boardEl.classList.contains('flipped');

  // Parse pieces
  const pieces = [];
  let isDragging = false;
  let rank1TopVotes = 0;
  let rank1BottomVotes = 0;

  const pieceEls = boardEl.querySelectorAll('.piece');
  pieceEls.forEach((el) => {
    if (el.classList.contains('dragging')) {
      isDragging = true;
    }

    let color = '';
    let ptype = '';
    let square = '';

    el.classList.forEach((cls) => {
      const pieceMatch = cls.match(/^([wb])([pnbrqk])$/);
      if (pieceMatch) {
        color = pieceMatch[1];
        ptype = pieceMatch[2];
      }

      const sqMatch = cls.match(/^square-([1-8])([1-8])$/);
      if (sqMatch) {
        const fileChar = String.fromCharCode('a'.charCodeAt(0) + parseInt(sqMatch[1], 10) - 1);
        const rankChar = sqMatch[2];
        square = fileChar + rankChar;

        const pRect = el.getBoundingClientRect();
        const pCenterY = pRect.top + pRect.height / 2;
        const bCenterY = rect.top + rect.height / 2;

        if (rankChar === '1') {
          if (pCenterY < bCenterY) {
            rank1TopVotes++;
          } else {
            rank1BottomVotes++;
          }
        } else if (rankChar === '8') {
          if (pCenterY > bCenterY) {
            rank1TopVotes++;
          } else {
            rank1BottomVotes++;
          }
        }
      }
    });

    if (color && ptype && square) {
      pieces.push({ color, type: ptype, square });
    }
  });

  // Check coordinate labels if present in DOM / SVG
  let flippedGeometry = false;
  const coordTexts = boardEl.querySelectorAll(
    'text.coordinate-dark, text.coordinate-light, .coordinates text, .coordinates span'
  );
  let coordFlippedFound = false;

  coordTexts.forEach((cEl) => {
    const text = cEl.textContent ? cEl.textContent.trim() : '';
    const cRect = cEl.getBoundingClientRect();
    const cCenterY = cRect.top + cRect.height / 2;
    const bCenterY = rect.top + rect.height / 2;

    if (text === '1') {
      coordFlippedFound = true;
      if (cCenterY < bCenterY) {
        flippedGeometry = true;
      } else {
        flippedGeometry = false;
      }
    } else if (text === '8' && !coordFlippedFound) {
      if (cCenterY > bCenterY) {
        flippedGeometry = true;
      } else {
        flippedGeometry = false;
      }
    }
  });

  if (!coordFlippedFound) {
    if (rank1TopVotes > rank1BottomVotes) {
      flippedGeometry = true;
    } else if (rank1BottomVotes > rank1TopVotes) {
      flippedGeometry = false;
    } else {
      flippedGeometry = flippedClass;
    }
  }

  // Determine ourColorHint independent of board orientation
  let ourColorHint = null;
  const topPlayerEl = document.querySelector('#board-layout-player-top, .board-layout-player-top');
  const botPlayerEl = document.querySelector('#board-layout-player-bottom, .board-layout-player-bottom');

  const topColor = flippedGeometry ? 'w' : 'b';
  const botColor = flippedGeometry ? 'b' : 'w';

  // 1. Try logged-in username from meta, window globals, data attributes, or profile links
  let loggedInUsername = '';
  const metaUser = document.querySelector('meta[name="user"]');
  if (metaUser && metaUser.getAttribute('content')) {
    loggedInUsername = metaUser.getAttribute('content').trim().toLowerCase();
  }
  if (!loggedInUsername && typeof window !== 'undefined' && window.context && window.context.user && window.context.user.username) {
    loggedInUsername = String(window.context.user.username).trim().toLowerCase();
  }
  if (!loggedInUsername) {
    const dataUserEl = document.querySelector('[data-user-username], [data-username]');
    if (dataUserEl) {
      loggedInUsername = (
        dataUserEl.getAttribute('data-user-username') ||
        dataUserEl.getAttribute('data-username') ||
        ''
      ).trim().toLowerCase();
    }
  }
  if (!loggedInUsername) {
    const profileLinks = Array.from(
      document.querySelectorAll(
        '#sb a[href*="/member/"], nav a[href*="/member/"], .nav-menu-area a[href*="/member/"], [data-tab="profile"] a[href*="/member/"], a.navigation-auth-profile[href*="/member/"], .sidebar a[href*="/member/"], a.user-nav-profile[href*="/member/"]'
      )
    ).filter(
      (el) =>
        !el.closest(
          '#board-layout-player-top, #board-layout-player-bottom, .board-layout-player-top, .board-layout-player-bottom, #board-layout-main, wc-chess-board, .board'
        )
    );
    for (const link of profileLinks) {
      const href = link.getAttribute('href') || '';
      const m = href.match(/\/member\/([a-zA-Z0-9_\-]+)/i);
      if (m && m[1]) {
        const uname = m[1].toLowerCase();
        if (uname !== 'settings' && uname !== 'membership' && uname !== 'home') {
          loggedInUsername = uname;
          break;
        }
      }
    }
  }

  function playerMatchesUsername(playerEl, uname) {
    if (!playerEl || !uname) return false;
    const uEl = playerEl.querySelector(
      '.user-username-component, .user-tagline-username, [data-test-element="user-tagline-username"], .user-username, a.user-username-link'
    );
    if (uEl) {
      const t = (uEl.textContent || '').trim().toLowerCase();
      if (t === uname || t.includes(uname)) return true;
    }
    const dataU = playerEl.getAttribute('data-user-username') || playerEl.getAttribute('data-username');
    if (dataU && dataU.trim().toLowerCase() === uname) return true;
    const text = (playerEl.innerText || playerEl.textContent || '').toLowerCase();
    return text.includes(uname);
  }

  let humanPosition = null; // 'top' or 'bot'

  if (loggedInUsername) {
    const isTopUser = playerMatchesUsername(topPlayerEl, loggedInUsername);
    const isBotUser = playerMatchesUsername(botPlayerEl, loggedInUsername);
    if (isTopUser && !isBotUser) {
      humanPosition = 'top';
    } else if (isBotUser && !isTopUser) {
      humanPosition = 'bot';
    }
  }

  // 2. Fallback to Guest detection
  if (!humanPosition) {
    const isTopGuest = topPlayerEl && (topPlayerEl.innerText || topPlayerEl.textContent || '').toLowerCase().includes('guest');
    const isBotGuest = botPlayerEl && (botPlayerEl.innerText || botPlayerEl.textContent || '').toLowerCase().includes('guest');
    if (isTopGuest && !isBotGuest) {
      humanPosition = 'top';
    } else if (isBotGuest && !isTopGuest) {
      humanPosition = 'bot';
    }
  }

  // 3. Fallback to botName if on play computer
  const botNameEl = document.querySelector(
    '.bot-selection-header-title, .cc-sidebar-header-title, .bot-speech-content-botMessage, h1.cc-sidebar-header-title'
  );
  const botName = botNameEl ? botNameEl.textContent.trim().toLowerCase() : '';

  if (!humanPosition && botName) {
    const isTopBot = topPlayerEl && (topPlayerEl.innerText || topPlayerEl.textContent || '').toLowerCase().includes(botName);
    const isBotBot = botPlayerEl && (botPlayerEl.innerText || botPlayerEl.textContent || '').toLowerCase().includes(botName);
    if (isTopBot && !isBotBot) humanPosition = 'bot';
    else if (isBotBot && !isTopBot) humanPosition = 'top';
  }

  if (humanPosition === 'top') {
    ourColorHint = topColor;
  } else if (humanPosition === 'bot') {
    ourColorHint = botColor;
  } else {
    const sideOptions = Array.from(document.querySelectorAll('.play-side-selector-option'));
    if (sideOptions.length >= 3) {
      if (sideOptions[0].classList.contains('cc-selected-border')) ourColorHint = 'w';
      else if (sideOptions[2].classList.contains('cc-selected-border')) ourColorHint = 'b';
    }
  }

  // 4. Fallback to board geometry if username / side not found:
  // In chess.com, local player is positioned at the bottom of the board.
  if (!ourColorHint) {
    ourColorHint = flippedGeometry ? 'b' : 'w';
  }

  // Read both clocks from DOM
  function parseClockText(text) {
    if (!text) return null;
    const cleaned = text.trim();
    if (!cleaned) return null;
    const parts = cleaned.split(':');
    if (parts.length === 3) {
      const h = parseFloat(parts[0]);
      const m = parseFloat(parts[1]);
      const s = parseFloat(parts[2]);
      if (!isNaN(h) && !isNaN(m) && !isNaN(s)) {
        return Math.round((h * 3600 + m * 60 + s) * 10) / 10;
      }
    } else if (parts.length === 2) {
      const m = parseFloat(parts[0]);
      const s = parseFloat(parts[1]);
      if (!isNaN(m) && !isNaN(s)) {
        return Math.round((m * 60 + s) * 10) / 10;
      }
    } else if (parts.length === 1) {
      const s = parseFloat(parts[0]);
      if (!isNaN(s)) {
        return Math.round(s * 10) / 10;
      }
    }
    return null;
  }

  function extractClock(playerEl, fallbackEl, color) {
    const clockEl = (playerEl && playerEl.querySelector(
      '.clock-component, .clock-time, [data-cy="clock-time"], .clock-player-turn, [class*="clock-"]'
    )) || fallbackEl;

    if (!clockEl) {
      return { text: null, seconds: null, ticking: false, color: color };
    }

    const timeEl = clockEl.querySelector('.clock-time, [data-cy="clock-time"]') || clockEl;
    const rawText = (timeEl.textContent || '').trim();
    const seconds = parseClockText(rawText);
    const ticking = clockEl.classList.contains('clock-player-turn') ||
                    clockEl.classList.contains('clock-ticking') ||
                    clockEl.classList.contains('running') ||
                    (playerEl && playerEl.classList.contains('clock-player-turn')) ||
                    Boolean(clockEl.closest && clockEl.closest('.clock-player-turn'));

    return {
      text: rawText || null,
      seconds: seconds,
      ticking: Boolean(ticking),
      color: color
    };
  }

  const topClockFallback = document.querySelector('.board-layout-clock-top, .clock-top');
  const botClockFallback = document.querySelector('.board-layout-clock-bottom, .clock-bottom');

  const topClock = extractClock(topPlayerEl, topClockFallback, topColor);
  const botClock = extractClock(botPlayerEl, botClockFallback, botColor);

  const whiteClock = topColor === 'w' ? topClock : botClock;
  const blackClock = topColor === 'b' ? topClock : botClock;

  const clocks = {
    top: topClock,
    bottom: botClock,
    white: whiteClock,
    black: blackClock
  };

  // Parse moves list and structured moves
  const moves = [];
  const structuredMoves = [];
  let moveListEl = null;
  const boardId = boardEl.id;
  if (boardId) {
    moveListEl = document.querySelector(
      `wc-simple-move-list[board-id="${boardId}"], wc-vertical-move-list[board-id="${boardId}"]`
    );
  }
  if (!moveListEl) {
    moveListEl = document.querySelector('wc-simple-move-list, wc-vertical-move-list, .move-list, .vertical-move-list');
  }

  if (moveListEl) {
    const hasMainLine = moveListEl.querySelector('.main-line-ply') !== null;
    const plySelector = hasMainLine
      ? '.node.main-line-ply'
      : '.node.white-move, .node.black-move, .node, .move-text';
    const moveNodes = moveListEl.querySelectorAll(plySelector);

    let plyIdx = 0;
    moveNodes.forEach((node) => {
      const figurineEl = node.querySelector('[data-figurine]');
      let prefix = '';
      if (figurineEl) {
        prefix = figurineEl.getAttribute('data-figurine') || '';
      }

      const contentEl = node.querySelector('.node-highlight-content') || node;
      let text = (contentEl.textContent || '').trim();

      if (prefix && !text.startsWith(prefix)) {
        text = prefix + text;
      }

      text = text.replace(/[!?]+/g, '').trim();

      const timeEl = node.querySelector('.time, [data-time], .node-time');
      const timeStr = timeEl ? (timeEl.textContent || '').trim() : null;

      if (text && !/^\d+\.?$/.test(text)) {
        plyIdx++;
        moves.push(text);
        structuredMoves.push({
          ply: plyIdx,
          moveNumber: Math.ceil(plyIdx / 2),
          color: (plyIdx % 2 === 1) ? 'w' : 'b',
          san: text,
          time: timeStr || null
        });
      }
    });
  }

  // Last move highlights
  const lastMoveHighlights = [];
  const highlightEls = boardEl.querySelectorAll('.highlight');
  highlightEls.forEach((el) => {
    el.classList.forEach((cls) => {
      const match = cls.match(/^square-([1-8])([1-8])$/);
      if (match) {
        const f = String.fromCharCode('a'.charCodeAt(0) + parseInt(match[1], 10) - 1);
        const r = match[2];
        const sq = f + r;
        if (!lastMoveHighlights.includes(sq)) {
          lastMoveHighlights.push(sq);
        }
      }
    });
  });

  // Game over detection (only selectors specific to game-over, with text verification)
  let gameOver = false;
  let gameOverText = null;
  const gameOverSelectors = [
    '.game-over-modal-header-component',
    '.game-over-modal-title-component',
    '.game-over-modal-shell-container',
    '.game-over-modal',
    '[data-cy="game-over-modal"]',
    '.modal-game-over-component',
    '.game-over-header',
    '.game-over-dialog'
  ];

  for (const sel of gameOverSelectors) {
    const el = document.querySelector(sel);
    if (el) {
      const style = window.getComputedStyle(el);
      if (style && style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0') {
        const titleEl = document.querySelector('.game-over-modal-title-component');
        const subEl = document.querySelector('.game-over-modal-subtitle-component');
        if (titleEl || subEl) {
          gameOver = true;
          const t = titleEl ? titleEl.textContent.trim() : '';
          const s = subEl ? subEl.textContent.trim() : '';
          gameOverText = (t + ' ' + s).trim();
          break;
        } else if (el.textContent && /won|winner|checkmate|resignation|draw|stalemate/i.test(el.textContent)) {
          gameOver = true;
          gameOverText = el.textContent.trim().replace(/\s+/g, ' ');
          break;
        }
      }
    }
  }

  // Game over buttons (New Game / Rematch)
  const gameOverButtons = [];
  const goBtnSelectors = [
    'button[data-cy="new-game-button"]',
    'button[data-cy="game-over-new-game-button"]',
    'button[data-cy="game-over-rematch-button"]',
    'button[data-cy="game-over-play-again-button"]',
    'button.game-over-button-component',
    'button.game-over-rematch-button',
    '.game-over-modal-buttons-component button',
    '.game-over-modal button',
    '.game-over-dialog button',
    '.modal-game-over-component button'
  ];

  function processGoButton(el) {
    if (!el) return;
    const style = window.getComputedStyle(el);
    if (!style || style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return;
    const text = (el.textContent || '').trim().replace(/\s+/g, ' ');
    const lower = text.toLowerCase();
    const isRematch = lower.includes('rematch');
    const isNewGame = lower.includes('new') || lower.includes('play again') || lower.includes('next');
    if (!isRematch && !isNewGame && !el.getAttribute('data-cy')) return;

    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.height > 0) {
      gameOverButtons.push({
        type: isRematch ? 'rematch' : 'new_game',
        text: text,
        rect: {
          x: r.x !== undefined ? r.x : r.left,
          y: r.y !== undefined ? r.y : r.top,
          width: r.width,
          height: r.height
        }
      });
    }
  }

  for (const sel of goBtnSelectors) {
    const els = document.querySelectorAll(sel);
    els.forEach(processGoButton);
  }

  if (gameOver && gameOverButtons.length === 0) {
    const candidateBtns = Array.from(document.querySelectorAll('button, a.ui_v5-button-component'));
    for (const btn of candidateBtns) {
      processGoButton(btn);
    }
  }

  // Promotion picker detection and options
  let promotionOpen = false;
  const promotionOptions = [];
  const promoWindow = document.querySelector(
    '.promotion-window, .promotion-menu, .promotion-window-component'
  );

  if (promoWindow) {
    const style = window.getComputedStyle(promoWindow);
    if (style && style.display !== 'none' && style.visibility !== 'hidden') {
      promotionOpen = true;
      const pieceEls = promoWindow.querySelectorAll('.promotion-piece, [data-piece]');
      pieceEls.forEach((el) => {
        const cls = el.className || '';
        let pieceType = null;
        const dataP = el.getAttribute('data-piece');
        if (dataP) {
          pieceType = dataP.toLowerCase();
        } else {
          const m = cls.match(/\b[wb]([qrbn])\b/i);
          if (m) {
            pieceType = m[1].toLowerCase();
          }
        }
        if (pieceType) {
          const r = el.getBoundingClientRect();
          promotionOptions.push({
            piece: pieceType,
            rect: {
              x: r.x !== undefined ? r.x : r.left,
              y: r.y !== undefined ? r.y : r.top,
              width: r.width,
              height: r.height
            }
          });
        }
      });
    }
  }

  if (!promotionOpen) {
    const directPieces = document.querySelectorAll('div.promotion-piece');
    if (directPieces.length > 0) {
      const firstStyle = window.getComputedStyle(directPieces[0]);
      if (firstStyle && firstStyle.display !== 'none' && firstStyle.visibility !== 'hidden') {
        promotionOpen = true;
        directPieces.forEach((el) => {
          const cls = el.className || '';
          const m = cls.match(/\b[wb]([qrbn])\b/i);
          const pieceType = m ? m[1].toLowerCase() : 'q';
          const r = el.getBoundingClientRect();
          promotionOptions.push({
            piece: pieceType,
            rect: {
              x: r.x !== undefined ? r.x : r.left,
              y: r.y !== undefined ? r.y : r.top,
              width: r.width,
              height: r.height
            }
          });
        });
      }
    }
  }

  // Live game indicators
  const resignBtn = document.querySelector('button[aria-label="Resign"], .resign-button-component');
  const hasResignButton = Boolean(
    resignBtn && (window.getComputedStyle ? window.getComputedStyle(resignBtn).display !== 'none' : true)
  );

  const drawBtn = document.querySelector('button[aria-label="Draw"], .draw-button-component');
  const hasDrawButton = Boolean(
    drawBtn && (window.getComputedStyle ? window.getComputedStyle(drawBtn).display !== 'none' : true)
  );

  const liveMoveList = document.querySelector('wc-simple-move-list, wc-vertical-move-list');
  const hasMoveList = Boolean(
    liveMoveList && (window.getComputedStyle ? window.getComputedStyle(liveMoveList).display !== 'none' : true)
  );

  // Start game / Play button in online lobby
  let startGameButton = null;
  const startBtnSelectors = [
    'a[href*="createLiveChallenge"]',
    'button[data-cy="new-game-index-play"]',
    'button.new-game-index-play',
    '.play-online-quick-links-quick-start a',
    '.play-online-quick-links-quick-start button',
    'button[data-cy="play-button"]'
  ];
  for (const sel of startBtnSelectors) {
    const el = document.querySelector(sel);
    if (el) {
      const style = window.getComputedStyle ? window.getComputedStyle(el) : null;
      if (!style || (style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0')) {
        const r = el.getBoundingClientRect ? el.getBoundingClientRect() : { x: 0, y: 0, width: 100, height: 40 };
        if (r.width > 0 && r.height > 0) {
          startGameButton = {
            rect: {
              x: r.x !== undefined ? r.x : r.left,
              y: r.y !== undefined ? r.y : r.top,
              width: r.width,
              height: r.height
            }
          };
          break;
        }
      }
    }
  }
  if (!startGameButton) {
    const primaryBtns = Array.from(
      document.querySelectorAll('button.cc-button-primary, a.cc-button-primary, button.ui_v5-button-primary')
    );
    for (const btn of primaryBtns) {
      const text = (btn.textContent || '').trim().toLowerCase();
      if (text === 'start game' || text === 'play' || text.startsWith('play (')) {
        const style = window.getComputedStyle ? window.getComputedStyle(btn) : null;
        if (!style || (style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0')) {
          const r = btn.getBoundingClientRect ? btn.getBoundingClientRect() : { x: 0, y: 0, width: 100, height: 40 };
          if (r.width > 0 && r.height > 0) {
            startGameButton = {
              rect: {
                x: r.x !== undefined ? r.x : r.left,
                y: r.y !== undefined ? r.y : r.top,
                width: r.width,
                height: r.height
              }
            };
            break;
          }
        }
      }
    }
  }
  const hasStartButton = Boolean(startGameButton);

  return {
    url: url,
    found: true,
    boardRect: boardRect,
    flippedClass: flippedClass,
    flippedGeometry: flippedGeometry,
    pieces: pieces,
    moves: moves,
    structuredMoves: structuredMoves,
    clocks: clocks,
    lastMoveHighlights: lastMoveHighlights,
    gameOver: gameOver,
    gameOverText: gameOverText,
    gameOverButtons: gameOverButtons,
    promotionOpen: promotionOpen,
    promotionOptions: promotionOptions,
    devicePixelRatio: dpr,
    window: winInfo,
    dragging: isDragging,
    ourColorHint: ourColorHint,
    hasResignButton: hasResignButton,
    hasDrawButton: hasDrawButton,
    hasMoveList: hasMoveList,
    hasStartButton: hasStartButton,
    startGameButton: startGameButton
  };
})()
