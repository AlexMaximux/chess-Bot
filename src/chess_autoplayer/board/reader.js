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
      dragging: false
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
      // Piece class: w[pnbrqk] or b[pnbrqk]
      const pieceMatch = cls.match(/^([wb])([pnbrqk])$/);
      if (pieceMatch) {
        color = pieceMatch[1];
        ptype = pieceMatch[2];
      }

      // Square class: square-XY where X=file (1-8), Y=rank (1-8)
      const sqMatch = cls.match(/^square-([1-8])([1-8])$/);
      if (sqMatch) {
        const fileChar = String.fromCharCode('a'.charCodeAt(0) + parseInt(sqMatch[1], 10) - 1);
        const rankChar = sqMatch[2];
        square = fileChar + rankChar;

        // Geometric verification for flipped board
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
            rank1TopVotes++; // rank 8 at bottom implies flipped
          } else {
            rank1BottomVotes++; // rank 8 at top implies normal
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
  const coordTexts = boardEl.querySelectorAll('text.coordinate-dark, text.coordinate-light, .coordinates text, .coordinates span');
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

  // Parse moves list
  const moves = [];
  const moveNodes = document.querySelectorAll(
    'wc-simple-move-list .node, .move-list-item, .move-list-wrapper .node, [class*="move-list"] .node'
  );

  moveNodes.forEach((node) => {
    // Only process individual move nodes (not parent turn containers if they exist)
    if (node.classList.contains('white-move') || node.classList.contains('black-move') || node.classList.contains('node')) {
      // Check for figurine icon
      const figurineEl = node.querySelector('[data-figurine]');
      let prefix = '';
      if (figurineEl) {
        prefix = figurineEl.getAttribute('data-figurine') || '';
      }

      // Clone node or extract content
      let text = '';
      const contentEl = node.querySelector('.node-highlight-content, [class*="node-content"]') || node;
      text = contentEl.textContent || '';
      text = text.trim();

      // If figurine was used and not present in text
      if (prefix && !text.startsWith(prefix)) {
        text = prefix + text;
      }

      // Clean annotations: strip ! and ? combinations (e.g., !?, ?!, ??, !!) but preserve check (+) and mate (#)
      text = text.replace(/[!?]+/g, '').trim();

      // Ensure valid SAN token (exclude turn numbers like "1.", "2.")
      if (text && !/^\d+\.?$/.test(text)) {
        moves.push(text);
      }
    }
  });

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

  // Game over detection
  let gameOver = false;
  let gameOverText = null;
  const gameOverSelectors = [
    '.game-over-modal-header-component',
    '.game-over-modal-title-component',
    '.game-over-modal-shell-container',
    '.game-over-modal',
    '.board-modal-component',
    '.game-result-component',
    '.board-dialog-component',
    '.game-over-dialog-content',
    '[data-cy="game-over-modal"]',
    '.modal-game-over-component',
    '.game-over-header',
    '.game-over-dialog'
  ];

  for (const sel of gameOverSelectors) {
    const el = document.querySelector(sel);
    if (el) {
      // Check visibility
      const style = window.getComputedStyle(el);
      if (style && style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0') {
        gameOver = true;
        const titleEl = document.querySelector('.game-over-modal-title-component');
        const subEl = document.querySelector('.game-over-modal-subtitle-component');
        if (titleEl && subEl) {
          gameOverText = (titleEl.textContent || '').trim() + ' ' + (subEl.textContent || '').trim();
        } else {
          gameOverText = (el.textContent || '').trim().replace(/\s+/g, ' ');
        }
        break;
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
    dragging: isDragging
  };
})()
