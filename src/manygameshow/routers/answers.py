"""Answers — /api/answers/games/* endpoints."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Field, Session, SQLModel, select

from manygameshow.answers_banks import (
    list_final_banks,
    list_round1_banks,
    list_round2_banks,
)
from manygameshow.database import get_session
from manygameshow.models.answers import (
    ALL_PLAYERS,
    AnswersGame,
    AnswersGameCreate,
    AnswersGameRead,
    CategoryRead,
    ClueRead,
    FinalEntry,
    FinalEntryRead,
    Player,
    PlayerScore,
    PlayerStatusRead,
    RoundName,
    TimingOverride,
    answer_time_for,
    buzz_elapsed_ms,
    can_ring_in,
    categories_revealed,
    clear_answer_time_overrides,
    clear_ring_in_overrides,
    clue_cells,
    clue_phase,
    current_bank,
    final_bank_content,
    final_entry,
    is_selected_context_clue,
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

router = APIRouter(prefix="/api/answers/games", tags=["answers"])

SessionDep = Annotated[Session, Depends(get_session)]


def _get_game(game_id: str, session: Session) -> AnswersGame:
    game = session.get(AnswersGame, game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="Game not found")
    return game


def _save(game: AnswersGame, session: Session) -> AnswersGame:
    game.updated_at = datetime.now(UTC).replace(tzinfo=None)
    session.add(game)
    session.commit()
    session.refresh(game)
    return game


def _final_entry_read(entry: FinalEntry) -> FinalEntryRead:
    return FinalEntryRead(
        eligible=entry.eligible,
        submitted=entry.submitted,
        revealed=entry.revealed,
        wager=entry.wager if entry.revealed else None,
        answer=entry.answer if entry.revealed else None,
        correct=entry.correct if entry.revealed else None,
    )


def _categories_read(game: AnswersGame, *, show_all: bool) -> list[CategoryRead]:
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
            is_context_clue = clue.context_clue != 0 if context_visible else False
            clue_reads.append(
                ClueRead(
                    category_index=cat_idx,
                    clue_index=clue_idx,
                    value=clue.value,
                    is_context_clue=is_context_clue,
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


def _to_read(game: AnswersGame, *, show_all: bool = False) -> AnswersGameRead:
    final_category: str | None = None
    final_text: str | None = None
    if game.current_round == RoundName.FINAL:
        final_category, final_text, _ = final_bank_content(game)

    def player_status(player: Player) -> PlayerStatusRead:
        score = player_score(game, player)
        start, window = ring_in_window_for(game, player)
        return PlayerStatusRead(
            name=score.name,
            score=score.score,
            can_ring_in=can_ring_in(game, player),
            ring_in_start_delay_ms=start,
            ring_in_window_ms=window,
            answer_time_ms=answer_time_for(game, player),
        )

    return AnswersGameRead(
        id=game.id,
        current_round=game.current_round,
        categories=_categories_read(game, show_all=show_all),
        players={p.value: player_status(p) for p in ALL_PLAYERS},
        board_control=game.board_control,
        selected_category_index=game.selected_category_index,
        selected_clue_index=game.selected_clue_index,
        clue_phase=clue_phase(game),
        buzzed_player=game.buzzed_player,
        context_clue_wager=game.context_clue_wager,
        ring_in_elapsed_ms=ring_in_elapsed_ms(game),
        buzz_elapsed_ms=buzz_elapsed_ms(game),
        answer_timer_stopped=game.buzz_timer_frozen_ms is not None,
        no_one_can_answer=ring_in_window_expired(game),
        ring_in_start_delay_ms=game.ring_in_start_delay_ms,
        ring_in_window_ms=game.ring_in_window_ms,
        answer_time_ms=game.answer_time_ms,
        final_category=final_category,
        final_text=final_text,
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


class BankOptionsRead(SQLModel):
    round1: list[BankOptionRead]
    round2: list[BankOptionRead]
    final: list[BankOptionRead]


@router.get("/banks", response_model=BankOptionsRead)
def get_bank_options() -> BankOptionsRead:
    return BankOptionsRead(
        round1=[BankOptionRead(id=b.id, name=b.name) for b in list_round1_banks()],
        round2=[BankOptionRead(id=b.id, name=b.name) for b in list_round2_banks()],
        final=[BankOptionRead(id=b.id, name=b.name) for b in list_final_banks()],
    )


@router.post("/", response_model=AnswersGameRead)
def create_game(body: AnswersGameCreate, session: SessionDep) -> AnswersGameRead:
    game = AnswersGame(
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


@router.get("/", response_model=list[AnswersGameRead])
def list_games(session: SessionDep) -> list[AnswersGameRead]:
    games = session.exec(select(AnswersGame)).all()
    return [_to_read(g) for g in games]


@router.get("/{game_id}", response_model=AnswersGameRead)
def get_game(game_id: str, session: SessionDep) -> AnswersGameRead:
    return _to_read(_get_game(game_id, session))


@router.get("/{game_id}/control", response_model=AnswersGameRead)
def get_control_game(game_id: str, session: SessionDep) -> AnswersGameRead:
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


@router.patch("/{game_id}/players", response_model=AnswersGameRead)
def update_players(
    game_id: str, body: PlayersBody, session: SessionDep
) -> AnswersGameRead:
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


@router.patch("/{game_id}/category-reveal", response_model=AnswersGameRead)
def set_category_reveal(
    game_id: str, body: CategoryRevealBody, session: SessionDep
) -> AnswersGameRead:
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


@router.patch("/{game_id}/select-clue", response_model=AnswersGameRead)
def select_clue(
    game_id: str, body: SelectClueBody, session: SessionDep
) -> AnswersGameRead:
    game = _get_game(game_id, session)
    if game.current_round == RoundName.FINAL:
        raise HTTPException(status_code=400, detail="No board in Final Exam")
    if game.selected_category_index is not None:
        raise HTTPException(status_code=400, detail="A clue is already in play")
    bank = current_bank(game)
    if not (0 <= body.category_index < len(bank.categories)):
        raise HTTPException(status_code=422, detail="category_index out of range")
    category = bank.categories[body.category_index]
    if not (0 <= body.clue_index < len(category.clues)):
        raise HTTPException(status_code=422, detail="clue_index out of range")
    cells = clue_cells(game)
    if cells[body.category_index][body.clue_index].played:
        raise HTTPException(status_code=400, detail="That clue is already played")
    game.selected_category_index = body.category_index
    game.selected_clue_index = body.clue_index
    game.clue_revealed_at = None
    game.buzzed_player = None
    game.buzz_answer_started_at = None
    game.buzz_timer_frozen_ms = None
    game.context_clue_wager = None
    return _to_read(_save(game, session), show_all=True)


class ContextWagerBody(SQLModel):
    wager: int = Field(ge=0)


@router.patch("/{game_id}/context-wager", response_model=AnswersGameRead)
def set_context_wager(
    game_id: str, body: ContextWagerBody, session: SessionDep
) -> AnswersGameRead:
    game = _get_game(game_id, session)
    if game.selected_category_index is None or not is_selected_context_clue(game):
        raise HTTPException(status_code=400, detail="No Context Clue is selected")
    if clue_phase(game) == "revealed":
        raise HTTPException(status_code=400, detail="Clue is already revealed")
    game.context_clue_wager = body.wager
    return _to_read(_save(game, session), show_all=True)


@router.patch("/{game_id}/reveal-clue", response_model=AnswersGameRead)
def reveal_clue(game_id: str, session: SessionDep) -> AnswersGameRead:
    game = _get_game(game_id, session)
    if game.selected_category_index is None:
        raise HTTPException(status_code=400, detail="No clue is selected")
    if clue_phase(game) == "revealed":
        raise HTTPException(status_code=400, detail="Clue is already revealed")
    if is_selected_context_clue(game) and game.context_clue_wager is None:
        raise HTTPException(status_code=400, detail="Set the wager before revealing")
    game.clue_revealed_at = datetime.now(UTC).replace(tzinfo=None)
    return _to_read(_save(game, session), show_all=True)


class BuzzBody(SQLModel):
    player: Player


@router.patch("/{game_id}/buzz", response_model=AnswersGameRead)
def buzz(game_id: str, body: BuzzBody, session: SessionDep) -> AnswersGameRead:
    """A buzz outside the valid window (too early, too late, already
    someone else's, locked out, or a Context Clue in play) is silently
    ignored — the state just comes back unchanged, no error."""
    game = _get_game(game_id, session)
    if can_ring_in(game, body.player):
        game.buzzed_player = body.player
        game.buzz_answer_started_at = datetime.now(UTC).replace(tzinfo=None)
        game.buzz_timer_frozen_ms = None
        return _to_read(_save(game, session))
    return _to_read(game)


@router.patch("/{game_id}/stop-answer-timer", response_model=AnswersGameRead)
def stop_answer_timer(game_id: str, session: SessionDep) -> AnswersGameRead:
    """Freezes the answering player's countdown bar in place — e.g. once
    they've visibly started talking, the host doesn't want the bar to
    keep ticking down (or running out) while they're still answering.
    Purely cosmetic: judging still works normally."""
    game = _get_game(game_id, session)
    if game.buzzed_player is None or game.buzz_answer_started_at is None:
        raise HTTPException(status_code=400, detail="No one is currently answering")
    game.buzz_timer_frozen_ms = buzz_elapsed_ms(game)
    return _to_read(_save(game, session), show_all=True)


@router.patch("/{game_id}/resume-answer-timer", response_model=AnswersGameRead)
def resume_answer_timer(game_id: str, session: SessionDep) -> AnswersGameRead:
    game = _get_game(game_id, session)
    if game.buzzed_player is None or game.buzz_answer_started_at is None:
        raise HTTPException(status_code=400, detail="No one is currently answering")
    if game.buzz_timer_frozen_ms is None:
        raise HTTPException(status_code=400, detail="Timer isn't stopped")
    game.buzz_answer_started_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(
        milliseconds=game.buzz_timer_frozen_ms
    )
    game.buzz_timer_frozen_ms = None
    return _to_read(_save(game, session), show_all=True)


class JudgeBody(SQLModel):
    correct: bool


@router.patch("/{game_id}/judge", response_model=AnswersGameRead)
def judge(game_id: str, body: JudgeBody, session: SessionDep) -> AnswersGameRead:
    """Rules on the currently in-play clue — a Context Clue is judged
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

    if is_selected_context_clue(game):
        if game.board_control is None:
            raise HTTPException(status_code=400, detail="No one holds board control")
        if game.context_clue_wager is None:
            raise HTTPException(status_code=400, detail="No wager has been set")
        player = game.board_control
        score = player_score(game, player)
        wager = game.context_clue_wager
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
            game.buzz_timer_frozen_ms = None
            if len(cell.locked_out) >= len(ALL_PLAYERS):
                cell.played = True
                _clear_selected(game)
            else:
                game.clue_revealed_at = datetime.now(UTC).replace(tzinfo=None)

    cells = clue_cells(game)
    cells[cat_idx][clue_idx] = cell
    set_clue_cells(game, cells)
    return _to_read(_save(game, session), show_all=True)


def _clear_selected(game: AnswersGame) -> None:
    game.selected_category_index = None
    game.selected_clue_index = None
    game.clue_revealed_at = None
    game.buzzed_player = None
    game.buzz_answer_started_at = None
    game.buzz_timer_frozen_ms = None
    game.context_clue_wager = None


@router.patch("/{game_id}/no-one-answered", response_model=AnswersGameRead)
def no_one_answered(game_id: str, session: SessionDep) -> AnswersGameRead:
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


@router.patch("/{game_id}/board-control", response_model=AnswersGameRead)
def set_board_control(
    game_id: str, body: BoardControlBody, session: SessionDep
) -> AnswersGameRead:
    game = _get_game(game_id, session)
    game.board_control = body.player
    return _to_read(_save(game, session), show_all=True)


@router.patch("/{game_id}/start-round2", response_model=AnswersGameRead)
def start_round2(game_id: str, session: SessionDep) -> AnswersGameRead:
    game = _get_game(game_id, session)
    reset_board_for_round(game, RoundName.ROUND2)
    return _to_read(_save(game, session), show_all=True)


@router.patch("/{game_id}/start-final", response_model=AnswersGameRead)
def start_final(game_id: str, session: SessionDep) -> AnswersGameRead:
    game = _get_game(game_id, session)
    game.current_round = RoundName.FINAL
    _clear_selected(game)
    game.board_control = None
    for player in ALL_PLAYERS:
        eligible = player_score(game, player).score > 0
        set_final_entry(game, player, FinalEntry(eligible=eligible))
    return _to_read(_save(game, session), show_all=True)


class FinalSubmitBody(SQLModel):
    player: Player
    wager: int = Field(ge=0)
    answer: str


@router.patch("/{game_id}/final-submit", response_model=AnswersGameRead)
def final_submit(
    game_id: str, body: FinalSubmitBody, session: SessionDep
) -> AnswersGameRead:
    """Self-serve: the player's own device submits their wager+answer
    once. Hidden from everyone — Main, Control, and the other players —
    until the host triggers final-reveal for this player."""
    game = _get_game(game_id, session)
    if game.current_round != RoundName.FINAL:
        raise HTTPException(status_code=400, detail="Not in Final Exam")
    entry = final_entry(game, body.player)
    if not entry.eligible:
        raise HTTPException(status_code=400, detail="Not eligible for Final Exam")
    if entry.submitted:
        raise HTTPException(status_code=400, detail="Already submitted")
    if body.wager > player_score(game, body.player).score:
        raise HTTPException(status_code=422, detail="Wager can't exceed current score")
    entry.wager = body.wager
    entry.answer = body.answer
    entry.submitted = True
    set_final_entry(game, body.player, entry)
    return _to_read(_save(game, session))


class FinalPlayerBody(SQLModel):
    player: Player


@router.patch("/{game_id}/final-reveal", response_model=AnswersGameRead)
def final_reveal(
    game_id: str, body: FinalPlayerBody, session: SessionDep
) -> AnswersGameRead:
    game = _get_game(game_id, session)
    entry = final_entry(game, body.player)
    if not entry.submitted:
        raise HTTPException(status_code=400, detail="That player hasn't submitted yet")
    entry.revealed = True
    set_final_entry(game, body.player, entry)
    return _to_read(_save(game, session), show_all=True)


class FinalJudgeBody(SQLModel):
    player: Player
    correct: bool


@router.patch("/{game_id}/final-judge", response_model=AnswersGameRead)
def final_judge(
    game_id: str, body: FinalJudgeBody, session: SessionDep
) -> AnswersGameRead:
    game = _get_game(game_id, session)
    entry = final_entry(game, body.player)
    if not entry.revealed:
        raise HTTPException(status_code=400, detail="Reveal before judging")
    if entry.correct is not None:
        raise HTTPException(status_code=400, detail="Already judged")
    entry.correct = body.correct
    assert entry.wager is not None
    score = player_score(game, body.player)
    score.score += entry.wager if body.correct else -entry.wager
    set_player_score(game, body.player, score)
    set_final_entry(game, body.player, entry)
    return _to_read(_save(game, session), show_all=True)


class RingInSettingsBody(SQLModel):
    start_delay_ms: int | None = Field(default=None, ge=0)
    window_ms: int | None = Field(default=None, ge=100)


@router.patch("/{game_id}/ring-in-settings", response_model=AnswersGameRead)
def set_ring_in_settings(
    game_id: str, body: RingInSettingsBody, session: SessionDep
) -> AnswersGameRead:
    game = _get_game(game_id, session)
    if body.start_delay_ms is not None:
        game.ring_in_start_delay_ms = body.start_delay_ms
    if body.window_ms is not None:
        game.ring_in_window_ms = body.window_ms
    return _to_read(_save(game, session), show_all=True)


class RingInOverrideBody(SQLModel):
    player: Player
    start_delay_ms: int | None = None
    window_ms: int | None = None


@router.patch("/{game_id}/ring-in-override", response_model=AnswersGameRead)
def set_ring_in_player_override(
    game_id: str, body: RingInOverrideBody, session: SessionDep
) -> AnswersGameRead:
    game = _get_game(game_id, session)
    set_ring_in_override(
        game,
        body.player,
        TimingOverride(start_delay_ms=body.start_delay_ms, window_ms=body.window_ms),
    )
    return _to_read(_save(game, session), show_all=True)


@router.patch("/{game_id}/ring-in-override-clear", response_model=AnswersGameRead)
def clear_ring_in_player_overrides(
    game_id: str, session: SessionDep
) -> AnswersGameRead:
    game = _get_game(game_id, session)
    clear_ring_in_overrides(game)
    return _to_read(_save(game, session), show_all=True)


class AnswerTimeSettingsBody(SQLModel):
    window_ms: int = Field(ge=100)


@router.patch("/{game_id}/answer-time-settings", response_model=AnswersGameRead)
def set_answer_time_settings(
    game_id: str, body: AnswerTimeSettingsBody, session: SessionDep
) -> AnswersGameRead:
    game = _get_game(game_id, session)
    game.answer_time_ms = body.window_ms
    return _to_read(_save(game, session), show_all=True)


class AnswerTimeOverrideBody(SQLModel):
    player: Player
    window_ms: int | None = None


@router.patch("/{game_id}/answer-time-override", response_model=AnswersGameRead)
def set_answer_time_player_override(
    game_id: str, body: AnswerTimeOverrideBody, session: SessionDep
) -> AnswersGameRead:
    game = _get_game(game_id, session)
    set_answer_time_override(game, body.player, body.window_ms)
    return _to_read(_save(game, session), show_all=True)


@router.patch("/{game_id}/answer-time-override-clear", response_model=AnswersGameRead)
def clear_answer_time_player_overrides(
    game_id: str, session: SessionDep
) -> AnswersGameRead:
    game = _get_game(game_id, session)
    clear_answer_time_overrides(game)
    return _to_read(_save(game, session), show_all=True)


class AdjustScoreBody(SQLModel):
    player: Player
    score: int


@router.patch("/{game_id}/adjust-score", response_model=AnswersGameRead)
def adjust_score(
    game_id: str, body: AdjustScoreBody, session: SessionDep
) -> AnswersGameRead:
    game = _get_game(game_id, session)
    score = player_score(game, body.player)
    score.score = body.score
    set_player_score(game, body.player, score)
    return _to_read(_save(game, session), show_all=True)


@router.patch("/{game_id}/reset", response_model=AnswersGameRead)
def reset_game(game_id: str, session: SessionDep) -> AnswersGameRead:
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
    return _to_read(_save(game, session), show_all=True)
