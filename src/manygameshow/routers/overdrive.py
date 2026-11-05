"""Overdrive — /api/overdrive/games/* endpoints."""

import base64
import binascii
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import Field, Session, SQLModel, select

from manygameshow.database import get_session
from manygameshow.models.overdrive import (
    ALL_PLAYERS,
    CategoryRead,
    ClueRead,
    FinalEntry,
    FinalEntryRead,
    OverdriveGame,
    OverdriveGameCreate,
    OverdriveGameRead,
    Player,
    PlayerScore,
    PlayerStatusRead,
    RoundName,
    TimingOverride,
    answer_time_for,
    apply_auto_reveal,
    auto_reveal_remaining_ms,
    buzz_remaining_ms,
    can_ring_in,
    categories_revealed,
    changeable_banks,
    clear_answer_time_overrides,
    clear_ring_in_overrides,
    clue_cells,
    clue_phase,
    crit_boost_max_wager,
    current_bank,
    final_answer_remaining_ms,
    final_answers_open,
    final_bank_content,
    final_entries,
    final_entry,
    is_selected_crit_boost,
    player_score,
    reset_board_for_round,
    ring_in_elapsed_ms,
    ring_in_window_expired,
    ring_in_window_for,
    selected_clue_cell,
    selected_clue_content,
    set_answer_time_override,
    set_categories_revealed,
    set_clue_cells,
    set_final_entry,
    set_player_score,
    set_ring_in_override,
)
from manygameshow.overdrive_banks import (
    RoundBank,
    get_final_bank,
    get_round1_bank,
    get_round2_bank,
    list_final_banks,
    list_round1_banks,
    list_round2_banks,
)

router = APIRouter(prefix="/api/overdrive/games", tags=["overdrive"])

SessionDep = Annotated[Session, Depends(get_session)]


def _get_game(game_id: str, session: Session) -> OverdriveGame:
    game = session.get(OverdriveGame, game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="Game not found")
    if apply_auto_reveal(game):
        _save(game, session)
    return game


def _save(game: OverdriveGame, session: Session) -> OverdriveGame:
    game.updated_at = datetime.now(UTC).replace(tzinfo=None)
    session.add(game)
    session.commit()
    session.refresh(game)
    return game


def _final_entry_read(entry: FinalEntry) -> FinalEntryRead:
    """What anyone may see: the wager once it's been displayed, the answer
    once it's been revealed — never earlier, even to the host."""
    return FinalEntryRead(
        eligible=entry.eligible,
        wager_submitted=entry.wager_submitted,
        answer_submitted=entry.answer_submitted,
        wager_revealed=entry.wager_revealed,
        revealed=entry.revealed,
        wager=entry.wager if entry.wager_revealed else None,
        answer=entry.answer if entry.revealed else None,
        has_drawing=bool(entry.drawing) and entry.revealed,
        correct=entry.correct if entry.revealed else None,
        delta=entry.delta,
    )


def _categories_read(game: OverdriveGame, *, show_all: bool) -> list[CategoryRead]:
    if game.current_round == RoundName.FINAL:
        return []
    bank = current_bank(game)
    revealed = categories_revealed(game)
    cells = clue_cells(game)
    out: list[CategoryRead] = []
    for cat_idx, category in enumerate(bank.categories):
        clue_reads = []
        for clue_idx, clue in enumerate(category.clues):
            cell = cells[cat_idx][clue_idx]
            is_current = (
                game.selected_category_index == cat_idx
                and game.selected_clue_index == clue_idx
            )
            text_visible = (
                show_all
                or cell.played
                or (is_current and clue_phase(game) == "revealed")
            )
            answer_visible = show_all or cell.played
            context_visible = show_all or cell.played or is_current
            is_crit_boost = clue.crit_boost != 0 if context_visible else False
            clue_reads.append(
                ClueRead(
                    category_index=cat_idx,
                    clue_index=clue_idx,
                    value=clue.value,
                    is_crit_boost=is_crit_boost,
                    played=cell.played,
                    locked_out=cell.locked_out,
                    text=clue.text if text_visible else None,
                    answer=clue.answer if answer_visible else None,
                )
            )
        out.append(
            CategoryRead(
                index=cat_idx,
                name=category.name,
                revealed=revealed[cat_idx],
                clues=clue_reads,
            )
        )
    return out


def _to_read(game: OverdriveGame, *, show_all: bool = False) -> OverdriveGameRead:
    final_phase: str | None = None
    final_category: str | None = None
    final_text: str | None = None
    final_answer: str | None = None
    if game.current_round == RoundName.FINAL:
        final_phase = game.final_phase
        category, text, answer = final_bank_content(game)
        if final_phase != "intro":
            final_category = category
        if final_phase in ("clue", "reveal", "standings"):
            final_text = text
            if show_all:
                final_answer = answer

    def player_status(player: Player) -> PlayerStatusRead:
        score = player_score(game, player)
        start, window = ring_in_window_for(game, player)
        return PlayerStatusRead(
            name=score.name,
            score=score.score,
            can_ring_in=can_ring_in(game, player),
            locked_out=(
                (cell := selected_clue_cell(game)) is not None
                and player in cell.locked_out
            ),
            ring_in_start_delay_ms=start,
            ring_in_window_ms=window,
            answer_time_ms=answer_time_for(game, player),
        )

    return OverdriveGameRead(
        id=game.id,
        current_round=game.current_round,
        round1_bank_id=game.round1_bank_id,
        round2_bank_id=game.round2_bank_id,
        final_bank_id=game.final_bank_id,
        changeable_banks=changeable_banks(game),
        categories=_categories_read(game, show_all=show_all),
        players={p.value: player_status(p) for p in ALL_PLAYERS},
        board_control=game.board_control,
        selected_category_index=game.selected_category_index,
        selected_clue_index=game.selected_clue_index,
        clue_phase=clue_phase(game),
        buzzed_player=game.buzzed_player,
        crit_boost_wager=game.crit_boost_wager,
        crit_boost_max_wager=crit_boost_max_wager(game),
        auto_reveal_delay_ms=game.auto_reveal_delay_ms,
        auto_reveal_remaining_ms=auto_reveal_remaining_ms(game),
        ring_in_elapsed_ms=ring_in_elapsed_ms(game),
        buzz_remaining_ms=buzz_remaining_ms(game),
        answer_timer_running=game.buzz_timer_running,
        no_one_can_answer=ring_in_window_expired(game),
        ring_in_start_delay_ms=game.ring_in_start_delay_ms,
        ring_in_window_ms=game.ring_in_window_ms,
        ring_in_is_retry=game.ring_in_is_retry,
        ring_in_retry_start_delay_ms=game.ring_in_retry_start_delay_ms,
        ring_in_retry_window_ms=game.ring_in_retry_window_ms,
        answer_time_ms=game.answer_time_ms,
        final_phase=final_phase,
        final_category=final_category,
        final_text=final_text,
        final_answer=final_answer,
        final_answer_time_ms=game.final_answer_time_ms,
        final_answer_remaining_ms=final_answer_remaining_ms(game),
        final_display_player=game.final_display_player,
        final_entries={
            p.value: _final_entry_read(final_entry(game, p)) for p in ALL_PLAYERS
        },
        status=game.status,
        created_at=game.created_at,
        updated_at=game.updated_at,
    )


class BankOptionRead(SQLModel):
    id: str
    name: str
    # Host-facing hint of what's in the bank: a round bank's category
    # names, or a Final Exam bank's single category.
    categories: list[str]


class BankOptionsRead(SQLModel):
    round1: list[BankOptionRead]
    round2: list[BankOptionRead]
    final: list[BankOptionRead]


def _round_bank_option(bank: RoundBank) -> BankOptionRead:
    return BankOptionRead(
        id=bank.id, name=bank.name, categories=[c.name for c in bank.categories]
    )


@router.get("/banks", response_model=BankOptionsRead)
def get_bank_options() -> BankOptionsRead:
    return BankOptionsRead(
        round1=[_round_bank_option(b) for b in list_round1_banks()],
        round2=[_round_bank_option(b) for b in list_round2_banks()],
        final=[
            BankOptionRead(id=b.id, name=b.name, categories=[b.category])
            for b in list_final_banks()
        ],
    )


@router.post("/", response_model=OverdriveGameRead)
def create_game(body: OverdriveGameCreate, session: SessionDep) -> OverdriveGameRead:
    game = OverdriveGame(
        round1_bank_id=body.round1_bank_id,
        round2_bank_id=body.round2_bank_id,
        final_bank_id=body.final_bank_id,
    )
    for player, name in zip(
        ALL_PLAYERS,
        [body.player1_name, body.player2_name, body.player3_name],
        strict=True,
    ):
        set_player_score(game, player, PlayerScore(name=name))
    reset_board_for_round(game, RoundName.ROUND1)
    return _to_read(_save(game, session))


@router.get("/", response_model=list[OverdriveGameRead])
def list_games(session: SessionDep) -> list[OverdriveGameRead]:
    games = session.exec(select(OverdriveGame)).all()
    return [_to_read(g) for g in games]


@router.get("/{game_id}", response_model=OverdriveGameRead)
def get_game(game_id: str, session: SessionDep) -> OverdriveGameRead:
    return _to_read(_get_game(game_id, session))


@router.get("/{game_id}/control", response_model=OverdriveGameRead)
def get_control_game(game_id: str, session: SessionDep) -> OverdriveGameRead:
    """Host-only view: every clue's text and answer are always visible
    (the host needs the answer key to judge), regardless of whether
    that clue's been selected/revealed/played yet. Final Exam entries
    are still redacted until revealed, same as everyone else — the host
    doesn't get to peek at the cards early either."""
    return _to_read(_get_game(game_id, session), show_all=True)


@router.delete("/{game_id}", status_code=204)
def delete_game(game_id: str, session: SessionDep) -> None:
    game = _get_game(game_id, session)
    session.delete(game)
    session.commit()


class PlayersBody(SQLModel):
    player1_name: str | None = None
    player2_name: str | None = None
    player3_name: str | None = None


@router.patch("/{game_id}/players", response_model=OverdriveGameRead)
def update_players(
    game_id: str, body: PlayersBody, session: SessionDep
) -> OverdriveGameRead:
    game = _get_game(game_id, session)
    names = [body.player1_name, body.player2_name, body.player3_name]
    for player, name in zip(ALL_PLAYERS, names, strict=True):
        if name is not None:
            score = player_score(game, player)
            score.name = name
            set_player_score(game, player, score)
    return _to_read(_save(game, session), show_all=True)


class CategoryRevealBody(SQLModel):
    category_index: int
    revealed: bool


@router.patch("/{game_id}/category-reveal", response_model=OverdriveGameRead)
def set_category_reveal(
    game_id: str, body: CategoryRevealBody, session: SessionDep
) -> OverdriveGameRead:
    game = _get_game(game_id, session)
    revealed = categories_revealed(game)
    if not (0 <= body.category_index < len(revealed)):
        raise HTTPException(status_code=422, detail="category_index out of range")
    revealed[body.category_index] = body.revealed
    set_categories_revealed(game, revealed)
    return _to_read(_save(game, session), show_all=True)


class SelectClueBody(SQLModel):
    category_index: int
    clue_index: int


@router.patch("/{game_id}/select-clue", response_model=OverdriveGameRead)
def select_clue(
    game_id: str, body: SelectClueBody, session: SessionDep
) -> OverdriveGameRead:
    game = _get_game(game_id, session)
    if game.current_round == RoundName.FINAL:
        raise HTTPException(status_code=400, detail="No board in Final Exam")
    if clue_phase(game) == "revealed":
        raise HTTPException(status_code=400, detail="A clue is already in play")
    # A selection that hasn't been revealed yet can simply be swapped for
    # another clue; re-selecting the same one leaves it (and its
    # auto-reveal countdown) alone.
    bank = current_bank(game)
    if not (0 <= body.category_index < len(bank.categories)):
        raise HTTPException(status_code=422, detail="category_index out of range")
    category = bank.categories[body.category_index]
    if not (0 <= body.clue_index < len(category.clues)):
        raise HTTPException(status_code=422, detail="clue_index out of range")
    cells = clue_cells(game)
    if cells[body.category_index][body.clue_index].played:
        raise HTTPException(status_code=400, detail="That clue is already played")
    if (
        game.selected_category_index == body.category_index
        and game.selected_clue_index == body.clue_index
    ):
        return _to_read(game, show_all=True)
    game.selected_category_index = body.category_index
    game.selected_clue_index = body.clue_index
    game.clue_selected_at = datetime.now(UTC).replace(tzinfo=None)
    game.clue_revealed_at = None
    game.ring_in_is_retry = False
    game.buzzed_player = None
    game.buzz_answer_started_at = None
    game.buzz_timer_remaining_ms = None
    game.buzz_timer_running = True
    game.crit_boost_wager = None
    return _to_read(_save(game, session), show_all=True)


@router.patch("/{game_id}/deselect-clue", response_model=OverdriveGameRead)
def deselect_clue(game_id: str, session: SessionDep) -> OverdriveGameRead:
    """Back out of a selected clue before it has been revealed (which also
    cancels any pending auto-reveal). Once revealed, use no-one-answered or
    judge instead."""
    game = _get_game(game_id, session)
    if game.selected_category_index is None:
        raise HTTPException(status_code=400, detail="No clue is selected")
    if clue_phase(game) == "revealed":
        raise HTTPException(status_code=400, detail="That clue is already revealed")
    _clear_selected(game)
    return _to_read(_save(game, session), show_all=True)


class CritBoostWagerBody(SQLModel):
    wager: int = Field(ge=0)


@router.patch("/{game_id}/crit-boost-wager", response_model=OverdriveGameRead)
def set_crit_boost_wager(
    game_id: str, body: CritBoostWagerBody, session: SessionDep
) -> OverdriveGameRead:
    game = _get_game(game_id, session)
    if game.selected_category_index is None or not is_selected_crit_boost(game):
        raise HTTPException(status_code=400, detail="No Crit Boost is selected")
    if clue_phase(game) == "revealed":
        raise HTTPException(status_code=400, detail="Clue is already revealed")
    max_wager = crit_boost_max_wager(game)
    if max_wager is not None and body.wager > max_wager:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Wager can be at most {max_wager} (the holder's score or the "
                "round's top clue value, whichever is higher)"
            ),
        )
    game.crit_boost_wager = body.wager
    return _to_read(_save(game, session), show_all=True)


@router.patch("/{game_id}/reveal-clue", response_model=OverdriveGameRead)
def reveal_clue(game_id: str, session: SessionDep) -> OverdriveGameRead:
    game = _get_game(game_id, session)
    if game.selected_category_index is None:
        raise HTTPException(status_code=400, detail="No clue is selected")
    if clue_phase(game) == "revealed":
        raise HTTPException(status_code=400, detail="Clue is already revealed")
    board_control = game.board_control
    if is_selected_crit_boost(game):
        if game.crit_boost_wager is None:
            raise HTTPException(
                status_code=400, detail="Set the wager before revealing"
            )
        if board_control is None:
            raise HTTPException(
                status_code=400, detail="No one holds board control to answer it"
            )
    game.clue_revealed_at = datetime.now(UTC).replace(tzinfo=None)
    if is_selected_crit_boost(game) and board_control is not None:
        # Crit Boost is still timed — it just skips the ring-in race
        # since only the board-control holder can answer it. Reuses the
        # same buzzed_player/answer-timer machinery as a regular buzz,
        # but the clock doesn't start on its own: the host reads the
        # clue first and starts it manually with Play when ready.
        game.buzzed_player = board_control
        game.buzz_answer_started_at = None
        game.buzz_timer_remaining_ms = answer_time_for(game, board_control)
        game.buzz_timer_running = False
    return _to_read(_save(game, session), show_all=True)


class BuzzBody(SQLModel):
    player: Player


@router.patch("/{game_id}/buzz", response_model=OverdriveGameRead)
def buzz(game_id: str, body: BuzzBody, session: SessionDep) -> OverdriveGameRead:
    """A buzz outside the valid window (too early, too late, already
    someone else's, locked out, or a Crit Boost in play) is silently
    ignored — the state just comes back unchanged, no error."""
    game = _get_game(game_id, session)
    if can_ring_in(game, body.player):
        game.buzzed_player = body.player
        game.buzz_answer_started_at = datetime.now(UTC).replace(tzinfo=None)
        game.buzz_timer_remaining_ms = answer_time_for(game, body.player)
        game.buzz_timer_running = True
        return _to_read(_save(game, session))
    return _to_read(game)


@router.patch("/{game_id}/host-ring-in", response_model=OverdriveGameRead)
def host_ring_in(
    game_id: str, body: BuzzBody, session: SessionDep
) -> OverdriveGameRead:
    """Host rings in on a player's behalf (a dead phone, a missed window).
    Unlike a player's buzz this ignores the ring-in window, but a clue
    must be revealed, nobody else may be answering, and the player can't
    be locked out of it — and unlike a buzz, a refusal is an error."""
    game = _get_game(game_id, session)
    name = player_score(game, body.player).name
    if clue_phase(game) != "revealed":
        raise HTTPException(status_code=400, detail="No revealed clue to ring in on")
    if is_selected_crit_boost(game):
        raise HTTPException(
            status_code=400,
            detail="Crit Boost clues go to whoever holds board control",
        )
    if game.buzzed_player is not None:
        answering = player_score(game, game.buzzed_player).name
        raise HTTPException(status_code=400, detail=f"{answering} is already answering")
    cell = selected_clue_cell(game)
    if cell is not None and body.player in cell.locked_out:
        raise HTTPException(
            status_code=400, detail=f"{name} is locked out of this clue"
        )
    game.buzzed_player = body.player
    game.buzz_answer_started_at = datetime.now(UTC).replace(tzinfo=None)
    game.buzz_timer_remaining_ms = answer_time_for(game, body.player)
    game.buzz_timer_running = True
    return _to_read(_save(game, session), show_all=True)


def _require_answering(game: OverdriveGame) -> Player:
    if game.buzzed_player is None:
        raise HTTPException(status_code=400, detail="No one is currently answering")
    return game.buzzed_player


@router.patch("/{game_id}/play-answer-timer", response_model=OverdriveGameRead)
def play_answer_timer(game_id: str, session: SessionDep) -> OverdriveGameRead:
    """Resumes a paused (or stopped-at-zero) countdown from wherever it
    was left off."""
    game = _get_game(game_id, session)
    _require_answering(game)
    if game.buzz_timer_running:
        raise HTTPException(status_code=400, detail="Timer is already running")
    game.buzz_answer_started_at = datetime.now(UTC).replace(tzinfo=None)
    game.buzz_timer_running = True
    return _to_read(_save(game, session), show_all=True)


@router.patch("/{game_id}/pause-answer-timer", response_model=OverdriveGameRead)
def pause_answer_timer(game_id: str, session: SessionDep) -> OverdriveGameRead:
    """Freezes the countdown in place — e.g. once the contestant's
    visibly started talking, the host doesn't want the bar to keep
    ticking down while they're still answering. Resumable with Play.
    Purely cosmetic: judging still works normally."""
    game = _get_game(game_id, session)
    _require_answering(game)
    if not game.buzz_timer_running:
        raise HTTPException(status_code=400, detail="Timer is already paused")
    game.buzz_timer_remaining_ms = buzz_remaining_ms(game)
    game.buzz_timer_running = False
    return _to_read(_save(game, session), show_all=True)


@router.patch("/{game_id}/stop-answer-timer", response_model=OverdriveGameRead)
def stop_answer_timer(game_id: str, session: SessionDep) -> OverdriveGameRead:
    """Zeroes the countdown out immediately — "time's up" — and pauses
    it there. Resumable with Play (resumes from 0, i.e. stays expired
    until Reset)."""
    game = _get_game(game_id, session)
    _require_answering(game)
    game.buzz_timer_remaining_ms = 0
    game.buzz_timer_running = False
    return _to_read(_save(game, session), show_all=True)


@router.patch("/{game_id}/reset-answer-timer", response_model=OverdriveGameRead)
def reset_answer_timer(game_id: str, session: SessionDep) -> OverdriveGameRead:
    """Restarts the countdown at the player's full answer duration,
    keeping whatever running/paused state it was already in."""
    game = _get_game(game_id, session)
    player = _require_answering(game)
    game.buzz_timer_remaining_ms = answer_time_for(game, player)
    if game.buzz_timer_running:
        game.buzz_answer_started_at = datetime.now(UTC).replace(tzinfo=None)
    return _to_read(_save(game, session), show_all=True)


@router.patch("/{game_id}/clear-answer-timer", response_model=OverdriveGameRead)
def clear_answer_timer(game_id: str, session: SessionDep) -> OverdriveGameRead:
    """Cancels this player's answer attempt entirely — un-buzzes them
    and reopens a fresh ring-in window for everyone else, with no
    scoring change. For when a buzz was a mistake (wrong button,
    technical glitch) rather than a wrong answer."""
    game = _get_game(game_id, session)
    _require_answering(game)
    game.buzzed_player = None
    game.buzz_answer_started_at = None
    game.buzz_timer_remaining_ms = None
    game.buzz_timer_running = True
    game.clue_revealed_at = datetime.now(UTC).replace(tzinfo=None)
    game.ring_in_is_retry = True
    return _to_read(_save(game, session), show_all=True)


class JudgeBody(SQLModel):
    correct: bool


@router.patch("/{game_id}/judge", response_model=OverdriveGameRead)
def judge(game_id: str, body: JudgeBody, session: SessionDep) -> OverdriveGameRead:
    """Rules on the currently in-play clue — a Crit Boost is judged
    against whoever holds board control (no buzz race); a regular clue
    is judged against whoever's currently buzzed in. Wrong on a regular
    clue just locks that player out of this clue and reopens ring-ins
    for whoever's left, unless that was the last eligible player."""
    game = _get_game(game_id, session)
    if game.selected_category_index is None:
        raise HTTPException(status_code=400, detail="No clue is selected")
    content = selected_clue_content(game)
    cell = selected_clue_cell(game)
    assert content is not None and cell is not None
    cat_idx, clue_idx = game.selected_category_index, game.selected_clue_index
    assert cat_idx is not None and clue_idx is not None

    if is_selected_crit_boost(game):
        if game.board_control is None:
            raise HTTPException(status_code=400, detail="No one holds board control")
        if game.crit_boost_wager is None:
            raise HTTPException(status_code=400, detail="No wager has been set")
        player = game.board_control
        score = player_score(game, player)
        wager = game.crit_boost_wager
        score.score += wager if body.correct else -wager
        set_player_score(game, player, score)
        cell.played = True
        _clear_selected(game)
    else:
        if game.buzzed_player is None:
            raise HTTPException(status_code=400, detail="No one has buzzed in")
        player = game.buzzed_player
        score = player_score(game, player)
        if body.correct:
            score.score += content.value
            set_player_score(game, player, score)
            cell.played = True
            game.board_control = player
            _clear_selected(game)
        else:
            score.score -= content.value
            set_player_score(game, player, score)
            cell.locked_out = [*cell.locked_out, player]
            game.buzzed_player = None
            game.buzz_answer_started_at = None
            game.buzz_timer_remaining_ms = None
            game.buzz_timer_running = True
            if len(cell.locked_out) >= len(ALL_PLAYERS):
                cell.played = True
                _clear_selected(game)
            else:
                game.clue_revealed_at = datetime.now(UTC).replace(tzinfo=None)
                game.ring_in_is_retry = True

    cells = clue_cells(game)
    cells[cat_idx][clue_idx] = cell
    set_clue_cells(game, cells)
    return _to_read(_save(game, session), show_all=True)


def _clear_selected(game: OverdriveGame) -> None:
    game.selected_category_index = None
    game.selected_clue_index = None
    game.clue_selected_at = None
    game.clue_revealed_at = None
    game.ring_in_is_retry = False
    game.buzzed_player = None
    game.buzz_answer_started_at = None
    game.buzz_timer_remaining_ms = None
    game.buzz_timer_running = True
    game.crit_boost_wager = None


@router.patch("/{game_id}/no-one-answered", response_model=OverdriveGameRead)
def no_one_answered(game_id: str, session: SessionDep) -> OverdriveGameRead:
    """Host bails on the current clue — the ring-in window closed (or
    the host just wants to move on) with no one holding the floor.
    Reveals the answer, no scoring, board control unchanged."""
    game = _get_game(game_id, session)
    if game.selected_category_index is None:
        raise HTTPException(status_code=400, detail="No clue is selected")
    if game.buzzed_player is not None:
        raise HTTPException(status_code=400, detail="Someone is still answering")
    cat_idx, clue_idx = game.selected_category_index, game.selected_clue_index
    assert clue_idx is not None
    cells = clue_cells(game)
    cells[cat_idx][clue_idx].played = True
    set_clue_cells(game, cells)
    _clear_selected(game)
    return _to_read(_save(game, session), show_all=True)


class BoardControlBody(SQLModel):
    player: Player | None = None


@router.patch("/{game_id}/board-control", response_model=OverdriveGameRead)
def set_board_control(
    game_id: str, body: BoardControlBody, session: SessionDep
) -> OverdriveGameRead:
    game = _get_game(game_id, session)
    game.board_control = body.player
    return _to_read(_save(game, session), show_all=True)


@router.patch("/{game_id}/start-round2", response_model=OverdriveGameRead)
def start_round2(game_id: str, session: SessionDep) -> OverdriveGameRead:
    game = _get_game(game_id, session)
    reset_board_for_round(game, RoundName.ROUND2)
    return _to_read(_save(game, session), show_all=True)


@router.patch("/{game_id}/start-final", response_model=OverdriveGameRead)
def start_final(game_id: str, session: SessionDep) -> OverdriveGameRead:
    game = _get_game(game_id, session)
    game.current_round = RoundName.FINAL
    _clear_selected(game)
    game.board_control = None
    game.final_phase = "intro"
    game.final_clue_revealed_at = None
    game.final_display_player = None
    for player in ALL_PLAYERS:
        eligible = player_score(game, player).score > 0
        set_final_entry(game, player, FinalEntry(eligible=eligible))
    return _to_read(_save(game, session), show_all=True)


def _require_final(game: OverdriveGame, *phases: str) -> None:
    if game.current_round != RoundName.FINAL:
        raise HTTPException(status_code=400, detail="Not in Final Exam")
    if phases and game.final_phase not in phases:
        raise HTTPException(
            status_code=400,
            detail=f"Not available right now (Final Exam is at: {game.final_phase})",
        )


@router.patch("/{game_id}/final-reveal-category", response_model=OverdriveGameRead)
def final_reveal_category(game_id: str, session: SessionDep) -> OverdriveGameRead:
    """Show the category; this is what opens the players' wagers."""
    game = _get_game(game_id, session)
    _require_final(game, "intro")
    game.final_phase = "category"
    return _to_read(_save(game, session), show_all=True)


class FinalWagerBody(SQLModel):
    player: Player
    wager: int = Field(ge=0)


@router.patch("/{game_id}/final-wager", response_model=OverdriveGameRead)
def final_wager(
    game_id: str, body: FinalWagerBody, session: SessionDep
) -> OverdriveGameRead:
    """Self-serve: a player's device locks in their wager once, after the
    category is shown. Hidden from everyone until the host displays it."""
    game = _get_game(game_id, session)
    _require_final(game, "category")
    entry = final_entry(game, body.player)
    if not entry.eligible:
        raise HTTPException(status_code=400, detail="Not eligible for Final Exam")
    if entry.wager_submitted:
        raise HTTPException(status_code=400, detail="Wager already submitted")
    if body.wager > player_score(game, body.player).score:
        raise HTTPException(status_code=422, detail="Wager can't exceed current score")
    entry.wager = body.wager
    entry.wager_submitted = True
    set_final_entry(game, body.player, entry)
    return _to_read(_save(game, session))


class FinalRevealClueBody(SQLModel):
    force: bool = False


@router.patch("/{game_id}/final-reveal-clue", response_model=OverdriveGameRead)
def final_reveal_clue(
    game_id: str, session: SessionDep, body: FinalRevealClueBody | None = None
) -> OverdriveGameRead:
    """Show the clue and start the answer timer — once every eligible
    player has wagered. With force, anyone still missing wagers 0."""
    game = _get_game(game_id, session)
    _require_final(game, "category")
    waiting = [
        p
        for p, e in final_entries(game).items()
        if e.eligible and not e.wager_submitted
    ]
    force = body is not None and body.force
    if waiting and not force:
        names = ", ".join(player_score(game, p).name for p in waiting)
        raise HTTPException(status_code=400, detail=f"Waiting for wagers from: {names}")
    for p in waiting:
        entry = final_entry(game, p)
        entry.wager = 0
        entry.wager_submitted = True
        set_final_entry(game, p, entry)
    game.final_phase = "clue"
    game.final_clue_revealed_at = datetime.now(UTC).replace(tzinfo=None)
    return _to_read(_save(game, session), show_all=True)


_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_MAX_DRAWING_CHARS = 250_000  # base64 text: roughly 180 KB of PNG


def _clean_drawing(raw: str) -> str:
    """Accept a PNG as a data URL or bare base64; return bare base64 or
    raise 422. Only a real, size-capped PNG is ever stored."""
    data = raw.removeprefix("data:image/png;base64,").strip()
    if len(data) > _MAX_DRAWING_CHARS:
        raise HTTPException(status_code=422, detail="Drawing is too large")
    try:
        decoded = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=422, detail="Drawing isn't valid") from None
    if not decoded.startswith(_PNG_SIGNATURE):
        raise HTTPException(status_code=422, detail="Drawing must be a PNG")
    return data


class FinalAnswerBody(SQLModel):
    player: Player
    text: str | None = None
    drawing: str | None = None


@router.patch("/{game_id}/final-answer", response_model=OverdriveGameRead)
def final_answer(
    game_id: str, body: FinalAnswerBody, session: SessionDep
) -> OverdriveGameRead:
    """Self-serve: a player's device submits their answer — typed, drawn,
    or both — once the clue is up and until the timer runs out."""
    game = _get_game(game_id, session)
    _require_final(game, "clue")
    entry = final_entry(game, body.player)
    if not entry.eligible:
        raise HTTPException(status_code=400, detail="Not eligible for Final Exam")
    if entry.answer_submitted:
        raise HTTPException(status_code=400, detail="Answer already submitted")
    if not final_answers_open(game):
        raise HTTPException(status_code=400, detail="Time's up — answers are locked")
    text = (body.text or "").strip()
    drawing = _clean_drawing(body.drawing) if body.drawing else None
    if not text and not drawing:
        raise HTTPException(status_code=422, detail="Type or draw an answer")
    entry.answer = text or None
    entry.drawing = drawing
    entry.answer_submitted = True
    set_final_entry(game, body.player, entry)
    return _to_read(_save(game, session))


class FinalPlayerBody(SQLModel):
    player: Player


@router.patch("/{game_id}/final-display", response_model=OverdriveGameRead)
def final_display(
    game_id: str, body: FinalPlayerBody, session: SessionDep
) -> OverdriveGameRead:
    """Put one player's Final Exam on Main — their wager first. Players can
    be shown in any order; this also closes answering."""
    game = _get_game(game_id, session)
    _require_final(game, "clue", "reveal")
    entry = final_entry(game, body.player)
    if not entry.eligible:
        raise HTTPException(status_code=400, detail="Not eligible for Final Exam")
    entry.wager_revealed = True
    set_final_entry(game, body.player, entry)
    game.final_display_player = body.player
    game.final_phase = "reveal"
    return _to_read(_save(game, session), show_all=True)


@router.patch("/{game_id}/final-reveal-answer", response_model=OverdriveGameRead)
def final_reveal_answer(
    game_id: str, body: FinalPlayerBody, session: SessionDep
) -> OverdriveGameRead:
    """Reveal the displayed player's answer, after their wager. A player who
    never answered reveals as a blank answer (judged incorrect)."""
    game = _get_game(game_id, session)
    _require_final(game, "reveal")
    entry = final_entry(game, body.player)
    if not entry.eligible or not entry.wager_revealed:
        raise HTTPException(status_code=400, detail="Display that player first")
    entry.answer_submitted = True
    entry.revealed = True
    set_final_entry(game, body.player, entry)
    game.final_display_player = body.player
    return _to_read(_save(game, session), show_all=True)


class FinalJudgeBody(SQLModel):
    player: Player
    correct: bool


@router.patch("/{game_id}/final-judge", response_model=OverdriveGameRead)
def final_judge(
    game_id: str, body: FinalJudgeBody, session: SessionDep
) -> OverdriveGameRead:
    """Correct adds the wager to that player's score, incorrect (or no
    answer) subtracts it. Each player is judged on their own, in any order."""
    game = _get_game(game_id, session)
    entry = final_entry(game, body.player)
    if not entry.revealed:
        raise HTTPException(status_code=400, detail="Reveal before judging")
    if entry.correct is not None:
        raise HTTPException(status_code=400, detail="Already judged")
    assert entry.wager is not None
    entry.correct = body.correct
    entry.delta = entry.wager if body.correct else -entry.wager
    score = player_score(game, body.player)
    score.score += entry.delta
    set_player_score(game, body.player, score)
    set_final_entry(game, body.player, entry)
    return _to_read(_save(game, session), show_all=True)


@router.patch("/{game_id}/final-standings", response_model=OverdriveGameRead)
def final_standings(game_id: str, session: SessionDep) -> OverdriveGameRead:
    """Finish up: Main shows the winner and final standings. Needs every
    eligible player judged."""
    game = _get_game(game_id, session)
    _require_final(game, "reveal")
    if any(e.eligible and e.correct is None for e in final_entries(game).values()):
        raise HTTPException(status_code=400, detail="Judge every player first")
    game.final_phase = "standings"
    game.final_display_player = None
    return _to_read(_save(game, session), show_all=True)


class FinalAnswerTimeBody(SQLModel):
    window_ms: int = Field(ge=0, le=300000)


@router.patch("/{game_id}/final-answer-time-settings", response_model=OverdriveGameRead)
def set_final_answer_time(
    game_id: str, body: FinalAnswerTimeBody, session: SessionDep
) -> OverdriveGameRead:
    """How long players get to answer once the clue is shown; 0 = no timer."""
    game = _get_game(game_id, session)
    game.final_answer_time_ms = body.window_ms
    return _to_read(_save(game, session), show_all=True)


@router.get("/{game_id}/final-drawing/{player}")
def final_drawing(game_id: str, player: Player, session: SessionDep) -> Response:
    """A revealed answer's drawing, as a PNG (kept out of the polled state
    so it isn't re-sent every 200ms). 404 until the host reveals it."""
    game = _get_game(game_id, session)
    entry = final_entry(game, player)
    if not entry.revealed or not entry.drawing:
        raise HTTPException(status_code=404, detail="No drawing to show")
    return Response(content=base64.b64decode(entry.drawing), media_type="image/png")


class RingInSettingsBody(SQLModel):
    start_delay_ms: int | None = Field(default=None, ge=0)
    window_ms: int | None = Field(default=None, ge=100)


@router.patch("/{game_id}/ring-in-settings", response_model=OverdriveGameRead)
def set_ring_in_settings(
    game_id: str, body: RingInSettingsBody, session: SessionDep
) -> OverdriveGameRead:
    game = _get_game(game_id, session)
    if body.start_delay_ms is not None:
        game.ring_in_start_delay_ms = body.start_delay_ms
    if body.window_ms is not None:
        game.ring_in_window_ms = body.window_ms
    return _to_read(_save(game, session), show_all=True)


@router.patch("/{game_id}/ring-in-retry-settings", response_model=OverdriveGameRead)
def set_ring_in_retry_settings(
    game_id: str, body: RingInSettingsBody, session: SessionDep
) -> OverdriveGameRead:
    """Timing of the second-chance ring-in window that opens for the
    remaining players after a wrong answer (separate from the first one)."""
    game = _get_game(game_id, session)
    if body.start_delay_ms is not None:
        game.ring_in_retry_start_delay_ms = body.start_delay_ms
    if body.window_ms is not None:
        game.ring_in_retry_window_ms = body.window_ms
    return _to_read(_save(game, session), show_all=True)


class RingInOverrideBody(SQLModel):
    player: Player
    start_delay_ms: int | None = None
    window_ms: int | None = None


@router.patch("/{game_id}/ring-in-override", response_model=OverdriveGameRead)
def set_ring_in_player_override(
    game_id: str, body: RingInOverrideBody, session: SessionDep
) -> OverdriveGameRead:
    game = _get_game(game_id, session)
    set_ring_in_override(
        game,
        body.player,
        TimingOverride(start_delay_ms=body.start_delay_ms, window_ms=body.window_ms),
    )
    return _to_read(_save(game, session), show_all=True)


@router.patch("/{game_id}/ring-in-override-clear", response_model=OverdriveGameRead)
def clear_ring_in_player_overrides(
    game_id: str, session: SessionDep
) -> OverdriveGameRead:
    game = _get_game(game_id, session)
    clear_ring_in_overrides(game)
    return _to_read(_save(game, session), show_all=True)


class AnswerTimeSettingsBody(SQLModel):
    window_ms: int = Field(ge=100)


class AutoRevealBody(SQLModel):
    delay_ms: int = Field(ge=0, le=60000)


@router.patch("/{game_id}/auto-reveal-settings", response_model=OverdriveGameRead)
def set_auto_reveal(
    game_id: str, body: AutoRevealBody, session: SessionDep
) -> OverdriveGameRead:
    """How long after a clue is selected it reveals itself; 0 turns
    auto-reveal off. Applies to selections made from now on."""
    game = _get_game(game_id, session)
    game.auto_reveal_delay_ms = body.delay_ms
    return _to_read(_save(game, session), show_all=True)


@router.patch("/{game_id}/answer-time-settings", response_model=OverdriveGameRead)
def set_answer_time_settings(
    game_id: str, body: AnswerTimeSettingsBody, session: SessionDep
) -> OverdriveGameRead:
    game = _get_game(game_id, session)
    game.answer_time_ms = body.window_ms
    return _to_read(_save(game, session), show_all=True)


class AnswerTimeOverrideBody(SQLModel):
    player: Player
    window_ms: int | None = None


@router.patch("/{game_id}/answer-time-override", response_model=OverdriveGameRead)
def set_answer_time_player_override(
    game_id: str, body: AnswerTimeOverrideBody, session: SessionDep
) -> OverdriveGameRead:
    game = _get_game(game_id, session)
    set_answer_time_override(game, body.player, body.window_ms)
    return _to_read(_save(game, session), show_all=True)


@router.patch("/{game_id}/answer-time-override-clear", response_model=OverdriveGameRead)
def clear_answer_time_player_overrides(
    game_id: str, session: SessionDep
) -> OverdriveGameRead:
    game = _get_game(game_id, session)
    clear_answer_time_overrides(game)
    return _to_read(_save(game, session), show_all=True)


class AdjustScoreBody(SQLModel):
    player: Player
    score: int


@router.patch("/{game_id}/adjust-score", response_model=OverdriveGameRead)
def adjust_score(
    game_id: str, body: AdjustScoreBody, session: SessionDep
) -> OverdriveGameRead:
    game = _get_game(game_id, session)
    score = player_score(game, body.player)
    score.score = body.score
    set_player_score(game, body.player, score)
    return _to_read(_save(game, session), show_all=True)


class BanksBody(SQLModel):
    round1_bank_id: str | None = None
    round2_bank_id: str | None = None
    final_bank_id: str | None = None


@router.patch("/{game_id}/banks", response_model=OverdriveGameRead)
def set_banks(game_id: str, body: BanksBody, session: SessionDep) -> OverdriveGameRead:
    """Swap a round's content bank — only for a round that hasn't started
    (see changeable_banks), so a swap never discards progress. All
    requested changes are checked before any is applied."""
    game = _get_game(game_id, session)
    allowed = changeable_banks(game)
    requested = (
        ("round1", "Round 1", body.round1_bank_id, get_round1_bank),
        ("round2", "Round 2", body.round2_bank_id, get_round2_bank),
        ("final", "Final Exam", body.final_bank_id, get_final_bank),
    )
    changes: list[tuple[str, str]] = []
    for kind, label, bank_id, getter in requested:
        if bank_id is None or bank_id == getattr(game, f"{kind}_bank_id"):
            continue
        if getter(bank_id) is None:
            raise HTTPException(status_code=422, detail=f"Unknown bank: {bank_id}")
        if kind not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"The {label} bank can't change once that round has started",
            )
        changes.append((kind, bank_id))
    for kind, bank_id in changes:
        setattr(game, f"{kind}_bank_id", bank_id)
    current_kind = {RoundName.ROUND1: "round1", RoundName.ROUND2: "round2"}.get(
        game.current_round
    )
    if any(kind == current_kind for kind, _ in changes):
        # The current round's board was untouched (that's what allowed the
        # swap), so rebuilding it for the new bank loses nothing.
        reset_board_for_round(game, game.current_round)
    return _to_read(_save(game, session), show_all=True)


@router.patch("/{game_id}/reset", response_model=OverdriveGameRead)
def reset_game(game_id: str, session: SessionDep) -> OverdriveGameRead:
    """Full reset: fresh players (names kept), round 1 board, board
    control cleared."""
    game = _get_game(game_id, session)
    names = {p: player_score(game, p).name for p in ALL_PLAYERS}
    for player in ALL_PLAYERS:
        set_player_score(game, player, PlayerScore(name=names[player]))
    game.board_control = None
    reset_board_for_round(game, RoundName.ROUND1)
    for player in ALL_PLAYERS:
        set_final_entry(game, player, FinalEntry())
    game.final_phase = "intro"
    game.final_clue_revealed_at = None
    game.final_display_player = None
    return _to_read(_save(game, session), show_all=True)
