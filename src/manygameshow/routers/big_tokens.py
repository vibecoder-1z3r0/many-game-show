"""Big Tokens, No Hallucinations — /api/big-tokens/games/* endpoints."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Field, Session, SQLModel, select

from manygameshow.big_tokens_boards import list_boards
from manygameshow.database import get_session
from manygameshow.models.big_tokens import (
    ALL_PLAYERS,
    BigTokensGame,
    BigTokensGameCreate,
    BigTokensGameRead,
    OutReason,
    Player,
    PlayerState,
    PlayerStateRead,
    SquareRead,
    advance_square,
    all_square_items,
    awaiting,
    board_for,
    chase_position,
    next_active_player,
    player_state,
    player_states,
    set_player_state,
    square_item,
)

router = APIRouter(prefix="/api/big-tokens/games", tags=["big-tokens"])

SessionDep = Annotated[Session, Depends(get_session)]


def _get_game(game_id: str, session: Session) -> BigTokensGame:
    game = session.get(BigTokensGame, game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="Game not found")
    return game


def _save(game: BigTokensGame, session: Session) -> BigTokensGame:
    game.updated_at = datetime.now(UTC).replace(tzinfo=None)
    session.add(game)
    session.commit()
    session.refresh(game)
    return game


def _to_read(game: BigTokensGame) -> BigTokensGameRead:
    board = board_for(game)
    squares = [
        SquareRead(index=i, type=item.type, label=item.label, amount=item.amount)
        for i, item in enumerate(all_square_items(game))
    ]
    players = {
        player.value: PlayerStateRead(
            **state.model_dump(), max_hallucinations=board.max_hallucinations
        )
        for player, state in player_states(game).items()
    }
    return BigTokensGameRead(
        id=game.id,
        board_id=game.board_id,
        board_name=board.name,
        squares=squares,
        players=players,
        current_player=game.current_player,
        round_number=game.round_number,
        chase_position=chase_position(game),
        awaiting=awaiting(game),
        pending_square_index=game.pending_square_index,
        elimination_scope=board.elimination_scope,
        status=game.status,
        created_at=game.created_at,
        updated_at=game.updated_at,
    )


class BoardOptionRead(SQLModel):
    id: str
    name: str


@router.get("/boards", response_model=list[BoardOptionRead])
def get_board_options() -> list[BoardOptionRead]:
    return [BoardOptionRead(id=b.id, name=b.name) for b in list_boards()]


@router.post("/", response_model=BigTokensGameRead)
def create_game(body: BigTokensGameCreate, session: SessionDep) -> BigTokensGameRead:
    game = BigTokensGame(board_id=body.board_id)
    for player, name in zip(
        ALL_PLAYERS,
        [body.player1_name, body.player2_name, body.player3_name],
        strict=True,
    ):
        set_player_state(game, player, PlayerState(name=name))
    return _to_read(_save(game, session))


@router.get("/", response_model=list[BigTokensGameRead])
def list_games(session: SessionDep) -> list[BigTokensGameRead]:
    games = session.exec(select(BigTokensGame)).all()
    return [_to_read(g) for g in games]


@router.get("/{game_id}", response_model=BigTokensGameRead)
def get_game(game_id: str, session: SessionDep) -> BigTokensGameRead:
    return _to_read(_get_game(game_id, session))


@router.delete("/{game_id}", status_code=204)
def delete_game(game_id: str, session: SessionDep) -> None:
    game = _get_game(game_id, session)
    session.delete(game)
    session.commit()


class PlayersBody(SQLModel):
    player1_name: str | None = None
    player2_name: str | None = None
    player3_name: str | None = None


@router.patch("/{game_id}/players", response_model=BigTokensGameRead)
def update_players(
    game_id: str, body: PlayersBody, session: SessionDep
) -> BigTokensGameRead:
    game = _get_game(game_id, session)
    names = [body.player1_name, body.player2_name, body.player3_name]
    for player, name in zip(ALL_PLAYERS, names, strict=True):
        if name is not None:
            state = player_state(game, player)
            state.name = name
            set_player_state(game, player, state)
    return _to_read(_save(game, session))


@router.patch("/{game_id}/start-round", response_model=BigTokensGameRead)
def start_round(game_id: str, session: SessionDep) -> BigTokensGameRead:
    """Begin a new round: bumps round_number, clears in-flight chase/
    resolution state, and zeroes every player's spins for the host to
    re-grant. Hallucination strikes only reset for a "round"-scoped
    board — a "game"-scoped board's eliminated players stay eliminated
    across rounds."""
    game = _get_game(game_id, session)
    board = board_for(game)
    game.round_number += 1
    game.current_player = None
    game.chase_started_at = None
    game.pending_square_index = None
    game.pending_choice = None
    for player in ALL_PLAYERS:
        state = player_state(game, player)
        state.spins_remaining = 0
        state.mandatory_spins = 0
        if board.elimination_scope == "round":
            state.hallucination_count = 0
            state.is_out = False
            state.out_reason = None
        set_player_state(game, player, state)
    return _to_read(_save(game, session))


class SetActivePlayerBody(SQLModel):
    player: Player


@router.patch("/{game_id}/active-player", response_model=BigTokensGameRead)
def set_active_player(
    game_id: str, body: SetActivePlayerBody, session: SessionDep
) -> BigTokensGameRead:
    """Host override: set (or change) whose turn it is at any time. Also
    clears any in-flight chase/resolution state, since it can't sensibly
    carry over to a different player."""
    game = _get_game(game_id, session)
    game.current_player = body.player
    game.chase_started_at = None
    game.pending_square_index = None
    game.pending_choice = None
    return _to_read(_save(game, session))


class AdjustPlayerBody(SQLModel):
    player: Player
    token_total: int | None = None
    spins_remaining: int | None = Field(default=None, ge=0)
    mandatory_spins: int | None = Field(default=None, ge=0)
    hallucination_count: int | None = Field(default=None, ge=0)
    is_out: bool | None = None
    out_reason: OutReason | None = None


@router.patch("/{game_id}/adjust-player", response_model=BigTokensGameRead)
def adjust_player(
    game_id: str, body: AdjustPlayerBody, session: SessionDep
) -> BigTokensGameRead:
    """Host override: directly set any of a player's stats — granting
    spins for a new round, correcting a score, manually reviving an
    eliminated player, etc. Only the fields provided are changed."""
    game = _get_game(game_id, session)
    state = player_state(game, body.player)
    if body.token_total is not None:
        state.token_total = body.token_total
    if body.spins_remaining is not None:
        state.spins_remaining = body.spins_remaining
    if body.mandatory_spins is not None:
        state.mandatory_spins = body.mandatory_spins
    if body.hallucination_count is not None:
        state.hallucination_count = body.hallucination_count
    if body.is_out is not None:
        state.is_out = body.is_out
    if body.out_reason is not None:
        state.out_reason = body.out_reason
    set_player_state(game, body.player, state)
    return _to_read(_save(game, session))


def _require_active_player(game: BigTokensGame) -> Player:
    if game.current_player is None:
        raise HTTPException(status_code=400, detail="No active player")
    return game.current_player


@router.patch("/{game_id}/start-spin", response_model=BigTokensGameRead)
def start_spin(game_id: str, session: SessionDep) -> BigTokensGameRead:
    game = _get_game(game_id, session)
    player = _require_active_player(game)
    state = player_state(game, player)
    if state.is_out:
        raise HTTPException(status_code=400, detail="Active player is out")
    if state.spins_remaining <= 0:
        raise HTTPException(status_code=400, detail="Active player has no spins left")
    if game.chase_started_at is not None or game.pending_square_index is not None:
        raise HTTPException(status_code=400, detail="A spin is already in progress")
    game.chase_started_at = datetime.now(UTC).replace(tzinfo=None)
    return _to_read(_save(game, session))


def _pay_spin_cost(game: BigTokensGame, player: Player) -> None:
    state = player_state(game, player)
    state.spins_remaining -= 1
    if state.mandatory_spins > 0:
        state.mandatory_spins -= 1
    set_player_state(game, player, state)


def _check_out_and_advance(game: BigTokensGame, player: Player) -> None:
    state = player_state(game, player)
    if state.spins_remaining <= 0 and not state.is_out:
        state.is_out = True
        state.out_reason = OutReason.NO_SPINS
        set_player_state(game, player, state)
    if player_state(game, player).is_out and game.current_player == player:
        game.current_player = next_active_player(game)


def _resolve_hallucination(game: BigTokensGame, player: Player) -> None:
    board = board_for(game)
    state = player_state(game, player)
    state.hallucination_count += 1
    eliminating_hit = state.hallucination_count >= board.max_hallucinations
    if board.wipe_on_every_hallucination or eliminating_hit:
        state.token_total = 0
    if eliminating_hit:
        state.is_out = True
        state.out_reason = OutReason.HALLUCINATED
    set_player_state(game, player, state)
    if state.is_out and game.current_player == player:
        game.current_player = next_active_player(game)


def _resolve_tokens(game: BigTokensGame, player: Player, amount: int) -> None:
    state = player_state(game, player)
    state.token_total += amount
    set_player_state(game, player, state)


def _resolve_double(game: BigTokensGame, player: Player) -> None:
    state = player_state(game, player)
    state.token_total *= 2
    set_player_state(game, player, state)


def _resolve_free_spin(game: BigTokensGame, player: Player) -> None:
    state = player_state(game, player)
    state.spins_remaining += 1
    set_player_state(game, player, state)


def _resolve_cure(game: BigTokensGame, player: Player) -> None:
    state = player_state(game, player)
    state.hallucination_count = max(0, state.hallucination_count - 1)
    set_player_state(game, player, state)


def _resolve_steal(
    game: BigTokensGame, player: Player, target: Player, amount: int
) -> None:
    state = player_state(game, player)
    target_state = player_state(game, target)
    stolen = min(amount, target_state.token_total)
    state.token_total += stolen
    target_state.token_total -= stolen
    set_player_state(game, player, state)
    set_player_state(game, target, target_state)


def _resolve_swap_scores(game: BigTokensGame, player: Player, target: Player) -> None:
    state = player_state(game, player)
    target_state = player_state(game, target)
    state.token_total, target_state.token_total = (
        target_state.token_total,
        state.token_total,
    )
    set_player_state(game, player, state)
    set_player_state(game, target, target_state)


def _resolve_immediate(
    game: BigTokensGame, player: Player, effective_type: str, amount: int | None
) -> None:
    """Apply an effect that needs no further input (already known to not
    require a target)."""
    if effective_type == "tokens":
        _resolve_tokens(game, player, amount or 0)
    elif effective_type == "double":
        _resolve_double(game, player)
    elif effective_type == "free_spin":
        _resolve_free_spin(game, player)
    elif effective_type == "hallucination":
        _resolve_hallucination(game, player)
    elif effective_type == "cure":
        _resolve_cure(game, player)
    else:  # pragma: no cover - defensive
        raise HTTPException(
            status_code=500, detail=f"Unresolvable type: {effective_type}"
        )


@router.patch("/{game_id}/stop-spin", response_model=BigTokensGameRead)
def stop_spin(game_id: str, session: SessionDep) -> BigTokensGameRead:
    """Lock in whatever square the live chase is over at this instant —
    callable from the active player's own device, or the host's override.
    Pays the spin's cost immediately; if the landed item needs a choice
    and/or a target, resolution pauses there until PATCH .../choose
    and/or .../target supply it."""
    game = _get_game(game_id, session)
    player = _require_active_player(game)
    if game.chase_started_at is None:
        raise HTTPException(status_code=400, detail="No spin in progress")
    locked_index = chase_position(game)
    assert locked_index is not None
    game.chase_started_at = None
    game.pending_square_index = locked_index
    game.pending_choice = None
    _pay_spin_cost(game, player)

    # Landing cascades the square for FUTURE spins, but resolution below
    # must still read the item as it was at the moment of landing — so
    # the cascade advance is deferred until the item is fully resolved
    # (here, or in choose()/target() if it needs more input first).
    if awaiting(game) is None:
        item = square_item(game, locked_index)
        _resolve_immediate(game, player, item.type, item.amount)
        advance_square(game, locked_index)
        game.pending_square_index = None
        _check_out_and_advance(game, player)
    return _to_read(_save(game, session))


class ChooseBody(SQLModel):
    choice: str


@router.patch("/{game_id}/choose", response_model=BigTokensGameRead)
def choose(game_id: str, body: ChooseBody, session: SessionDep) -> BigTokensGameRead:
    """Pick between a choice square's two options. If the pick still
    needs a target (Swap Scores), resolution pauses again for
    PATCH .../target; otherwise it resolves immediately."""
    game = _get_game(game_id, session)
    player = _require_active_player(game)
    if game.pending_square_index is None or awaiting(game) != "choice":
        raise HTTPException(status_code=400, detail="No choice is pending")
    item = square_item(game, game.pending_square_index)
    valid_choices = (
        {"swap_scores", "free_spin"}
        if item.type == "choice_swap_or_free_spin"
        else {"tokens", "cure"}
    )
    if body.choice not in valid_choices:
        raise HTTPException(status_code=422, detail="Invalid choice for this square")
    if body.choice == "cure" and player_state(game, player).hallucination_count == 0:
        raise HTTPException(status_code=400, detail="No hallucinations to remove")
    game.pending_choice = body.choice

    if awaiting(game) is None:
        effective_type = "tokens" if body.choice == "tokens" else body.choice
        _resolve_immediate(game, player, effective_type, item.amount)
        advance_square(game, game.pending_square_index)
        game.pending_square_index = None
        game.pending_choice = None
        _check_out_and_advance(game, player)
    return _to_read(_save(game, session))


class TargetBody(SQLModel):
    target: Player


@router.patch("/{game_id}/target", response_model=BigTokensGameRead)
def target(game_id: str, body: TargetBody, session: SessionDep) -> BigTokensGameRead:
    """Supply the target player for Steal Tokens, Swap Scores, or a
    Swap-Scores choice — the last piece needed to resolve the pending
    square."""
    game = _get_game(game_id, session)
    player = _require_active_player(game)
    if game.pending_square_index is None or awaiting(game) != "target":
        raise HTTPException(status_code=400, detail="No target is pending")
    if body.target == player:
        raise HTTPException(status_code=422, detail="Can't target yourself")
    item = square_item(game, game.pending_square_index)
    effective_type = (
        "swap_scores" if game.pending_choice == "swap_scores" else item.type
    )

    if effective_type == "steal":
        _resolve_steal(game, player, body.target, item.amount or 0)
    elif effective_type == "swap_scores":
        _resolve_swap_scores(game, player, body.target)
    else:  # pragma: no cover - defensive
        raise HTTPException(
            status_code=500, detail=f"Unexpected type: {effective_type}"
        )

    advance_square(game, game.pending_square_index)
    game.pending_square_index = None
    game.pending_choice = None
    _check_out_and_advance(game, player)
    return _to_read(_save(game, session))


@router.patch("/{game_id}/pass-spins", response_model=BigTokensGameRead)
def pass_spins(game_id: str, session: SessionDep) -> BigTokensGameRead:
    """Voluntary pass: the active player hands their entire remaining
    spin count to the next player in turn order (skipping anyone already
    out). Blocked while they still owe mandatory (received-pass) spins —
    those must be spun down first."""
    game = _get_game(game_id, session)
    player = _require_active_player(game)
    state = player_state(game, player)
    if state.mandatory_spins > 0:
        raise HTTPException(
            status_code=400, detail="Mandatory spins must be used before passing"
        )
    if state.spins_remaining <= 0:
        raise HTTPException(status_code=400, detail="No spins left to pass")
    recipient = next_active_player(game)
    if recipient is None or recipient == player:
        raise HTTPException(status_code=400, detail="No other active player to pass to")
    recipient_state = player_state(game, recipient)
    recipient_state.spins_remaining += state.spins_remaining
    recipient_state.mandatory_spins += state.spins_remaining
    state.spins_remaining = 0
    set_player_state(game, player, state)
    set_player_state(game, recipient, recipient_state)
    game.current_player = recipient
    return _to_read(_save(game, session))


@router.patch("/{game_id}/reset", response_model=BigTokensGameRead)
def reset_game(game_id: str, session: SessionDep) -> BigTokensGameRead:
    """Full reset: fresh players (names kept), fresh board, round 1."""
    game = _get_game(game_id, session)
    names = {p: player_state(game, p).name for p in ALL_PLAYERS}
    fresh = BigTokensGame(id=game.id, board_id=game.board_id)
    for player in ALL_PLAYERS:
        set_player_state(fresh, player, PlayerState(name=names[player]))
    game.players_json = fresh.players_json
    game.board_state_json = fresh.board_state_json
    game.current_player = None
    game.round_number = 1
    game.chase_started_at = None
    game.pending_square_index = None
    game.pending_choice = None
    return _to_read(_save(game, session))
