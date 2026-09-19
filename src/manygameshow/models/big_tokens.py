"""Big Tokens, No Hallucinations — a Press-Your-Luck-style board game for
3 players. See ADDING_A_GAME.md for the shared conventions this follows.

Board content (square layout, hallucination severity, elimination rules)
is data, not code — see big_tokens_boards.py — so different boards can be
authored/swapped without touching this state machine.
"""

import json
import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlmodel import Field, SQLModel

from manygameshow.big_tokens_boards import (
    SQUARES_PER_BOARD,
    Board,
    BoardItem,
    get_board,
)

# How fast the chase light moves — server-authoritative, same pattern as
# Speed Points' countdown: store started_at, compute elapsed on every read.
CHASE_STEP_MS = 150


def _utcnow() -> datetime:
    """Naive UTC timestamp for SQLite compatibility."""
    return datetime.now(UTC).replace(tzinfo=None)


class Player(StrEnum):
    PLAYER1 = "player1"
    PLAYER2 = "player2"
    PLAYER3 = "player3"


ALL_PLAYERS: list[Player] = [Player.PLAYER1, Player.PLAYER2, Player.PLAYER3]


class OutReason(StrEnum):
    HALLUCINATED = "hallucinated"
    NO_SPINS = "no_spins"


class PlayerState(SQLModel):
    """One player's standing for the current round. token_total is the
    single running score — there's no separate "safe" pot; a Hallucination
    (depending on the board's wipe policy) can zero it outright regardless
    of when those tokens were won."""

    name: str = ""
    token_total: int = 0
    spins_remaining: int = 0
    # Spins passed to this player (voluntarily, or by host override) that
    # must be used before they may voluntarily pass onward themselves.
    mandatory_spins: int = 0
    hallucination_count: int = 0
    is_out: bool = False
    out_reason: OutReason | None = None


def _default_players_json() -> str:
    return json.dumps(
        [
            PlayerState(name="Player 1").model_dump(),
            PlayerState(name="Player 2").model_dump(),
            PlayerState(name="Player 3").model_dump(),
        ]
    )


def _default_board_state_json() -> str:
    return json.dumps([0] * SQUARES_PER_BOARD)


class BigTokensGame(SQLModel, table=True):
    __tablename__ = "big_tokens_games"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    board_id: str = Field(default="classic")

    # JSON list of exactly 3 PlayerState dicts, index-aligned with
    # ALL_PLAYERS. Parsed via player_state()/set_player_state() below,
    # never in the model itself.
    players_json: str = Field(default_factory=_default_players_json)

    # JSON list of SQUARES_PER_BOARD ints: each square's current cascade
    # index into its board-content item array (see big_tokens_boards.py).
    board_state_json: str = Field(default_factory=_default_board_state_json)

    current_player: Player | None = Field(default=None)
    round_number: int = Field(default=1, ge=1)

    # Live chase state, server-authoritative (per ARCHITECTURE.md: store
    # started_at, compute elapsed on every read — never a client timer).
    chase_started_at: datetime | None = Field(default=None)

    # Set the instant a spin is stopped (by the player or a host
    # override), until fully resolved (a choice and/or a target may still
    # be needed — see PendingResolution below). None means idle/spinning.
    pending_square_index: int | None = Field(default=None)
    pending_choice: str | None = Field(default=None)

    status: str = Field(default="active")

    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class BigTokensGameCreate(SQLModel):
    board_id: str = "classic"
    player1_name: str = "Player 1"
    player2_name: str = "Player 2"
    player3_name: str = "Player 3"


class SquareRead(SQLModel):
    index: int
    type: str
    label: str
    amount: int | None


class PlayerStateRead(SQLModel):
    name: str
    token_total: int
    spins_remaining: int
    mandatory_spins: int
    hallucination_count: int
    max_hallucinations: int
    is_out: bool
    out_reason: OutReason | None


class BigTokensGameRead(SQLModel):
    id: str
    board_id: str
    board_name: str
    squares: list[SquareRead]
    players: dict[str, PlayerStateRead]
    current_player: Player | None
    round_number: int
    chase_position: int | None
    awaiting: str | None
    pending_square_index: int | None
    elimination_scope: str
    status: str
    created_at: datetime
    updated_at: datetime


def board_for(game: BigTokensGame) -> Board:
    board = get_board(game.board_id)
    if board is None:
        raise ValueError(f"Unknown board id: {game.board_id}")
    return board


def all_square_items(game: BigTokensGame) -> list[BoardItem]:
    return [square_item(game, i) for i in range(SQUARES_PER_BOARD)]


def board_state(game: BigTokensGame) -> list[int]:
    result: list[int] = json.loads(game.board_state_json)
    return result


def set_board_state(game: BigTokensGame, indices: list[int]) -> None:
    game.board_state_json = json.dumps(indices)


def square_item(game: BigTokensGame, square_index: int) -> BoardItem:
    """The item currently active at one square, honoring how far its
    cascade has advanced (clamped at its last item)."""
    board = board_for(game)
    items = board.squares[square_index].items
    current_index = board_state(game)[square_index]
    return items[min(current_index, len(items) - 1)]


def advance_square(game: BigTokensGame, square_index: int) -> None:
    """Landing on a square cascades it one step, regardless of what the
    landing player does with the result — clamped at the last item, so an
    already-exhausted square just keeps returning its final face."""
    indices = board_state(game)
    board = board_for(game)
    max_index = len(board.squares[square_index].items) - 1
    indices[square_index] = min(indices[square_index] + 1, max_index)
    set_board_state(game, indices)


def player_states(game: BigTokensGame) -> dict[Player, PlayerState]:
    raw: list[dict[str, object]] = json.loads(game.players_json)
    return {p: PlayerState.model_validate(raw[i]) for i, p in enumerate(ALL_PLAYERS)}


def player_state(game: BigTokensGame, player: Player) -> PlayerState:
    return player_states(game)[player]


def set_player_state(game: BigTokensGame, player: Player, state: PlayerState) -> None:
    states = player_states(game)
    states[player] = state
    game.players_json = json.dumps([states[p].model_dump() for p in ALL_PLAYERS])


def chase_position(game: BigTokensGame, now: datetime | None = None) -> int | None:
    if game.chase_started_at is None:
        return None
    now = now if now is not None else _utcnow()
    elapsed_ms = (now - game.chase_started_at).total_seconds() * 1000
    return int(elapsed_ms // CHASE_STEP_MS) % SQUARES_PER_BOARD


def awaiting(game: BigTokensGame) -> str | None:
    """What input (if any) is still needed to resolve the square the
    active player just landed on. None once fully resolved (or if no
    spin has landed yet)."""
    if game.pending_square_index is None:
        return None
    item = square_item(game, game.pending_square_index)
    if item.type == "choice_swap_or_free_spin":
        if game.pending_choice is None:
            return "choice"
        return "target" if game.pending_choice == "swap_scores" else None
    if item.type == "choice_tokens_or_cure":
        return "choice" if game.pending_choice is None else None
    if item.type in ("steal", "swap_scores"):
        return "target"
    return None


def next_active_player(game: BigTokensGame) -> Player | None:
    """The next player after current_player, in turn order, skipping
    anyone already out. None if everyone is out (round over)."""
    if game.current_player is None:
        start = 0
    else:
        start = ALL_PLAYERS.index(game.current_player)
    states = player_states(game)
    for offset in range(1, len(ALL_PLAYERS) + 1):
        candidate = ALL_PLAYERS[(start + offset) % len(ALL_PLAYERS)]
        if not states[candidate].is_out:
            return candidate
    return None


def round_over(game: BigTokensGame) -> bool:
    return all(s.is_out for s in player_states(game).values())
