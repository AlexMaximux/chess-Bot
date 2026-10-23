# Log

## 2026-10-23

- Model: gemini-4-argon-high quota exhausted (429, resets ~2026-10-28). Using gemini-3.8-flash-high, effort high.
- Brief 01 dispatched (Foundation).
- Brief 01 done in 1122 s (conversation fc940f3c-46c6-402e-8116-9a73bffdb708). Gates verified by Claude: 58 tests pass, mypy, ruff clean.
- Review 01-r1: 2 high (tab hijack, color after Flip Board), 2 medium (move-list scope, game-over false positives), 2 low.
- Dispatched 01-r1 fixes + brief 02 in same conversation.
- 01-r1 + brief 02 done in 2599 s. Gates verified: 94 tests, mypy, ruff clean. Live analyse commands correct.
- Review 02-r1: selector mate guard fallback, speed vs clock caps, recapture w/o stack, logged-in color hint.
- NOT dispatched: 02-r1 fixes + brief 03. Claude Code auto-mode classifier denied the `agy ... --dangerously-skip-permissions` run ("Create Unsafe Agents"). Waiting for user decision.
- User added allow rule `Bash(/Users/nersibayat/.local/bin/agy:*)`. Dispatched 02-r1 fixes + brief 03 (same conversation, background).
- 02-r1 + brief 03 done in 12113 s (commits 92b5e53, 79ecb50). Gates verified: 110 tests, mypy (26 files), ruff clean. Live: won as white and black vs Martin, BLOCKED_URL ok.
- Review 03-r1: 3 high (game-over/new-game dead code, URL guard before move, tab hijack via --start-url), 4 medium (fake reconnect, mouse button left pressed, username link order, runtime settings), 3 low, 1 check (promotion live).
- Dispatched 03-r1 fixes + brief 04 together (saves one long cycle).
- 03-r1 + brief 04 done in 14577 s (commits ae3dabb, e9c844c). Gates verified: 123 tests, mypy (29 files), ruff, gui --smoke 3 exit 0. Live: two games in one session won, GUI game won, drag 0.7-0.9 s.
- Review 04-r1: 2 high (false claim of promotion_open.json fixture, Tk thread calls controller/engine directly), 4 medium (cannot resume from ERROR, move style not applied, README paths wrong, verify accepts wrong move), 3 low. Dispatched.
- 04-r1 done in 16263 s (commit c622bf4). Gates verified: 128 tests, mypy, ruff, smoke exit 0. All UI→controller calls via call_soon_threadsafe; strength applied between searches; README paths fixed. Live GUI game with strength/style/pause changes won. ACCEPTED. Project complete. Open limit: promotion never verified live (chess.com ignores ?fen=).
