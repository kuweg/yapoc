"""Self-contained Tic-Tac-Toe game engine (no imports from the bot).

Pure logic only: a single player (human) vs an unbeatable minimax AI.
Board indexing is row-major: index 0 = top-left, index 8 = bottom-right.

    0 | 1 | 2
    --+---+--
    3 | 4 | 5
    --+---+--
    6 | 7 | 8
"""

from __future__ import annotations

# The 8 winning lines: 3 rows + 3 columns + 2 diagonals.
_WIN_LINES: tuple[tuple[int, int, int], ...] = (
    (0, 1, 2), (3, 4, 5), (6, 7, 8),   # rows
    (0, 3, 6), (1, 4, 7), (2, 5, 8),   # columns
    (0, 4, 8), (2, 4, 6),              # diagonals
)


class TicTacToe:
    """A single Tic-Tac-Toe match of human (X, first) vs AI (O).

    The AI is unbeatable: it uses minimax with alpha-beta pruning so it
    never loses and wins whenever the human blunders.
    """

    def __init__(self, human: str = "X", ai: str = "O") -> None:
        self.human: str = human
        self.ai: str = ai
        self.board: list[str] = [""] * 9
        self.winner: str | None = None
        self.draw: bool = False
        self.current_turn: str = self.human  # human moves first
        self.game_over: bool = False
        self.move_count: int = 0

    # ── queries ────────────────────────────────────────────────────────────

    def available_moves(self) -> list[int]:
        """Return the list of empty cell indices."""
        return [i for i, cell in enumerate(self.board) if cell == ""]

    def is_game_over(self) -> bool:
        return self.game_over

    # ── moves ──────────────────────────────────────────────────────────────

    def make_move(self, idx: int) -> bool:
        """Place the current player's symbol at ``idx`` and update state.

        Returns False if the move is invalid (out of range, cell occupied,
        or the game is already over). Otherwise places the symbol, checks
        for a win/draw, toggles whose turn it is, and returns True.
        """
        if self.game_over:
            return False
        if not 0 <= idx < 9 or self.board[idx] != "":
            return False

        self.board[idx] = self.current_turn
        self.move_count += 1

        if self._check_win():
            self.winner = self.current_turn
            self.game_over = True
        elif self.move_count == 9:
            self.draw = True
            self.game_over = True
        else:
            # Toggle turn
            self.current_turn = self.ai if self.current_turn == self.human else self.human

        return True

    def _check_win(self) -> bool:
        """Return True if the last-placed symbol completes a winning line."""
        player = self.current_turn
        for a, b, c in _WIN_LINES:
            if self.board[a] == player and self.board[b] == player and self.board[c] == player:
                return True
        return False

    def reset(self) -> None:
        """Reset to a fresh match (human still plays X and moves first)."""
        self.board[:] = [""] * 9
        self.winner = None
        self.draw = False
        self.current_turn = self.human
        self.game_over = False
        self.move_count = 0

    # ── AI ─────────────────────────────────────────────────────────────────

    def ai_move(self) -> int:
        """Pick and return the AI's best move index (or -1 if none exist).

        The AI plays as ``self.ai``. If a winning/empty situation changes we
        simply negamax. If a move wins on the next turn and would otherwise be
        left, picks it. Returns -1 when the board is full.
        """
        moves = self.available_moves()
        if not moves:
            return -1

        ai_sym = self.ai
        human_sym = self.human

        # Quick wins / block opponent wins:
        # 1. If AI can win now, do it.
        win_move = self._find_winning_move(ai_sym)
        if win_move is not None:
            return win_move
        # 2. If the human could win next, block them.
        block_move = self._find_winning_move(human_sym)
        if block_move is not None:
            return block_move

        # Minimax over remaining cells with alpha-beta pruning.
        best_score: float | None = None
        best_move = moves[0]
        for idx in moves:
            # Try AI move.
            self.board[idx] = ai_sym
            score = self._minimax(False, ai_sym, human_sym, -10**9, 10**9)
            self.board[idx] = ""
            if best_score is None or score > best_score:
                best_score = score
                best_move = idx
        return best_move

    def _find_winning_move(self, symbol: str) -> int | None:
        """Return an index that completes a line of ``symbol``, else None."""
        for i in self.available_moves():
            self.board[i] = symbol
            won = self._board_wins(symbol)
            self.board[i] = ""
            if won:
                return i
        return None

    def _board_wins(self, symbol: str) -> bool:
        for a, b, c in _WIN_LINES:
            if self.board[a] == symbol and self.board[b] == symbol and self.board[c] == symbol:
                return True
        return False

    def _minimax(self, ai_turn: bool, ai_sym: str, human_sym: str, alpha: float, beta: float) -> float:
        """Negamax-style minimax with alpha-beta pruning.

        Evaluates from the perspective of the AI player in ``ai_turn``.
        """
        # Terminal evaluation.
        if self._board_wins(ai_sym):
            return 1.0
        if self._board_wins(human_sym):
            return -1.0
        if not self.available_moves():
            return 0.0

        moves = self.available_moves()
        if ai_turn:
            value: float = -10**9
            for idx in moves:
                self.board[idx] = ai_sym
                value = max(value, self._minimax(False, ai_sym, human_sym, alpha, beta))
                self.board[idx] = ""
                alpha = max(alpha, value)
                if beta <= alpha:
                    break  # beta cutoff
            return value
        else:
            value = 10**9
            for idx in moves:
                self.board[idx] = human_sym
                value = min(value, self._minimax(True, ai_sym, human_sym, alpha, beta))
                self.board[idx] = ""
                beta = min(beta, value)
                if beta <= alpha:
                    break  # alpha cutoff
            return value


def render_board(board: list[str]) -> str:
    """Render a board as a compact 5-line monospace string.

    Empty cells are shown as ``.``; X and O use their symbols.
    """
    def cell(i: int) -> str:
        return board[i] if board[i] else "."

    return (
        f"{cell(0)} | {cell(1)} | {cell(2)}\n"
        f"--+---+--\n"
        f"{cell(3)} | {cell(4)} | {cell(5)}\n"
        f"--+---+--\n"
        f"{cell(6)} | {cell(7)} | {cell(8)}"
    )
