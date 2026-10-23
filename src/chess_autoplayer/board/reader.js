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
      lastMoveHighlights: [],
      gameOver: false,
      gameOverText: null,
      promotionOpen: false,
      devicePixelRatio: dpr,
      window: winInfo,
      dragging: false,
      ourColorHint: null
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
  const topPlayerEl = document.querySelector('#board-layout-player-top');
  const botPlayerEl = document.querySelector('#board-layout-player-bottom');

  const topColor = flippedGeometry ? 'w' : 'b';
  const botColor = flippedGeometry ? 'b' : 'w';

  // 1. Try logged-in username from navigation/profile links and data attributes
  let loggedInUsername = '';
  const profileLinks = Array.from(
    document.querySelectorAll(
      '#sb a[href*="/member/"], nav a[href*="/member/"], .nav-menu-area a[href*="/member/"], a[href*="/member/"][data-tab="profile"], a.navigation-auth-profile[href*="/member/"], a[href*="/member/"]'
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
  if (!loggedInUsername) {
    const dataUserEl = document.querySelector('[data-user-username], [data-username]');
    if (dataUserEl) {
      loggedInUsername = (
        dataUserEl.getAttribute('data-user-username') ||
        dataUserEl.getAttribute('data-username') ||
        ''
      ).toLowerCase();
    }
  }

  let humanPosition = null; // 'top' or 'bot'

  if (loggedInUsername) {
    const isTopUser = topPlayerEl && topPlayerEl.innerText.toLowerCase().includes(loggedInUsername);
    const isBotUser = botPlayerEl && botPlayerEl.innerText.toLowerCase().includes(loggedInUsername);
    if (isTopUser && !isBotUser) {
      humanPosition = 'top';
    } else if (isBotUser && !isTopUser) {
      humanPosition = 'bot';
    }
  }

  // 2. Fallback to Guest detection
  if (!humanPosition) {
    const isTopGuest = topPlayerEl && topPlayerEl.innerText.toLowerCase().includes('guest');
    const isBotGuest = botPlayerEl && botPlayerEl.innerText.toLowerCase().includes('guest');
    if (isTopGuest && !isBotGuest) {
      humanPosition = 'top';
    } else if (isBotGuest && !isTopGuest) {
      humanPosition = 'bot';
    }
  }

  // 3. Fallback to botName
  const botNameEl = document.querySelector(
    '.bot-selection-header-title, .cc-sidebar-header-title, .bot-speech-content-botMessage, h1.cc-sidebar-header-title'
  );
  const botName = botNameEl ? botNameEl.textContent.trim().toLowerCase() : '';

  if (!humanPosition && botName) {
    const isTopBot = topPlayerEl && topPlayerEl.innerText.toLowerCase().includes(botName);
    const isBotBot = botPlayerEl && botPlayerEl.innerText.toLowerCase().includes(botName);
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

  // Parse moves list scoped to matching wc-simple-move-list
  const moves = [];
  let moveListEl = null;
  const boardId = boardEl.id;
  if (boardId) {
    moveListEl = document.querySelector(`wc-simple-move-list[board-id="${boardId}"]`);
  }
  if (!moveListEl) {
    moveListEl = document.querySelector('wc-simple-move-list');
  }

  if (moveListEl) {
    const hasMainLine = moveListEl.querySelector('.main-line-ply') !== null;
    const plySelector = hasMainLine ? '.node.main-line-ply' : '.node.white-move, .node.black-move';
    const moveNodes = moveListEl.querySelectorAll(plySelector);

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

      if (text && !/^\d+\.?$/.test(text)) {
        moves.push(text);
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

  // Promotion picker detection
  let promotionOpen = false;
  const promoSelectors = [
    '.promotion-window',
    '.promotion-menu',
    'div.promotion-piece',
    '.promotion-window-component'
  ];

  for (const sel of promoSelectors) {
    const el = document.querySelector(sel);
    if (el) {
      const style = window.getComputedStyle(el);
      if (style && style.display !== 'none' && style.visibility !== 'hidden') {
        promotionOpen = true;
        break;
      }
    }
  }

  // Board dragging state
  if (boardEl.classList.contains('dragging')) {
    isDragging = true;
  }

  return {
    url: url,
    found: true,
    boardRect: boardRect,
    flippedClass: flippedClass,
    flippedGeometry: flippedGeometry,
    pieces: pieces,
    moves: moves,
    lastMoveHighlights: lastMoveHighlights,
    gameOver: gameOver,
    gameOverText: gameOverText,
    promotionOpen: promotionOpen,
    devicePixelRatio: dpr,
    window: winInfo,
    dragging: isDragging,
    ourColorHint: ourColorHint
  };
})()
