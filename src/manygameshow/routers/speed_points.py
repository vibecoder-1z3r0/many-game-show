"""Speed Points — /api/speed-points/games/* endpoints."""

import json
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Field, Session, SQLModel, select

from manygameshow.database import get_session
from manygameshow.models.speed_points import (
    DEFAULT_TIMER_SECONDS,
    QUESTIONS_PER_ROUND,
    AnswerOptionRead,
    AnswerSlot,
    Player,
    QuestionPromptRead,
    SlotRead,
    SpeedPointsGame,
    SpeedPointsGameCreate,
    SpeedPointsGameRead,
    combined_total,
    current_question,
    current_questions,
    player_slots,
    player_total,
    remaining_seconds,
)
from manygameshow.speed_points_questions import list_questions

router = APIRouter(prefix="/api/speed-points/games", tags=["speed-points"])

SessionDep = Annotated[Session, Depends(get_session)]


def _get_game(game_id: str, session: Session) -> SpeedPointsGame:
    game = session.get(SpeedPointsGame, game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="Game not found")
    return game


def _save(game: SpeedPointsGame, session: Session) -> SpeedPointsGame:
    game.updated_at = datetime.now(UTC).replace(tzinfo=None)
    session.add(game)
    session.commit()
    session.refresh(game)
    return game


def _slot_read(slot: AnswerSlot | None) -> SlotRead:
    if slot is None:
        return SlotRead(text=None, points=None, duplicate=False)
    # Text is visible as soon as it's chosen; points stay hidden in the API
    # response itself (not just CSS-hidden client-side) until revealed.
    return SlotRead(
        text=slot.text,
        points=slot.points if slot.revealed else None,
        duplicate=slot.duplicate,
    )


def _to_read(game: SpeedPointsGame) -> SpeedPointsGameRead:
    # No round active yet (or a leg just finished) -> nothing "current" to
    # show, even if the index still points at a resolvable question.
    question = current_question(game) if game.current_player is not None else None
    question_read = (
        QuestionPromptRead(id=question.id, prompt=question.prompt)
        if question is not None
        else None
    )
    total = combined_total(game)
    return SpeedPointsGameRead(
        id=game.id,
        player1_name=game.player1_name,
        player2_name=game.player2_name,
        current_player=game.current_player,
        current_question_index=game.current_question_index,
        current_question=question_read,
        all_questions=[
            QuestionPromptRead(id=q.id, prompt=q.prompt)
            for q in current_questions(game)
        ],
        pending_duplicate_flag=game.pending_duplicate_flag,
        player1_slots=[_slot_read(s) for s in player_slots(game, Player.PLAYER1)],
        player2_slots=[_slot_read(s) for s in player_slots(game, Player.PLAYER2)],
        player1_total=player_total(game, Player.PLAYER1),
        player2_total=player_total(game, Player.PLAYER2),
        combined_total=total,
        win_threshold=game.win_threshold,
        won=total >= game.win_threshold,
        scores_revealed=game.scores_revealed,
        remaining_seconds=remaining_seconds(game),
        timer_duration_seconds=game.timer_duration_seconds,
        status=game.status,
        created_at=game.created_at,
        updated_at=game.updated_at,
    )


@router.post("/", response_model=SpeedPointsGameRead)
def create_game(
    body: SpeedPointsGameCreate, session: SessionDep
) -> SpeedPointsGameRead:
    question_ids = [q.id for q in list_questions()[:QUESTIONS_PER_ROUND]]
    game = SpeedPointsGame(
        player1_name=body.player1_name,
        player2_name=body.player2_name,
        question_ids_json=json.dumps(question_ids),
    )
    session.add(game)
    session.commit()
    session.refresh(game)
    return _to_read(game)


@router.get("/", response_model=list[SpeedPointsGameRead])
def list_games(session: SessionDep) -> list[SpeedPointsGameRead]:
    games = session.exec(select(SpeedPointsGame)).all()
    return [_to_read(g) for g in games]


@router.get("/{game_id}", response_model=SpeedPointsGameRead)
def get_game(game_id: str, session: SessionDep) -> SpeedPointsGameRead:
    return _to_read(_get_game(game_id, session))


@router.delete("/{game_id}", status_code=204)
def delete_game(game_id: str, session: SessionDep) -> None:
    game = _get_game(game_id, session)
    session.delete(game)
    session.commit()


def _empty_slots_json() -> str:
    return json.dumps([None] * QUESTIONS_PER_ROUND)


def _reset_round_state(game: SpeedPointsGame) -> None:
    game.current_player = None
    game.current_question_index = 0
    game.player1_slots_json = _empty_slots_json()
    game.player2_slots_json = _empty_slots_json()
    game.timer_started_at = None
    game.scores_revealed = False
    game.pending_duplicate_flag = False


class StartRoundBody(SQLModel):
    player: Player
    duration_seconds: int | None = Field(default=None, ge=1, le=300)


@router.patch("/{game_id}/start-round", response_model=SpeedPointsGameRead)
def start_round(
    game_id: str, body: StartRoundBody, session: SessionDep
) -> SpeedPointsGameRead:
    """Start (or restart) one player's 5-question relay leg: resets their
    slots, rewinds to question 1, and starts their countdown."""
    game = _get_game(game_id, session)
    game.current_player = body.player
    game.current_question_index = 0
    game.pending_duplicate_flag = False
    slots_field = (
        "player1_slots_json" if body.player == Player.PLAYER1 else "player2_slots_json"
    )
    setattr(game, slots_field, _empty_slots_json())
    game.timer_duration_seconds = (
        body.duration_seconds
        if body.duration_seconds is not None
        else DEFAULT_TIMER_SECONDS[body.player.value]
    )
    game.timer_started_at = datetime.now(UTC).replace(tzinfo=None)
    return _to_read(_save(game, session))


def _slots_field_for(game: SpeedPointsGame) -> str:
    assert game.current_player is not None
    return (
        "player1_slots_json"
        if game.current_player == Player.PLAYER1
        else "player2_slots_json"
    )


class AwardBody(SQLModel):
    text: str = Field(min_length=1)
    points: int = Field(ge=0)


@router.patch("/{game_id}/award", response_model=SpeedPointsGameRead)
def award(game_id: str, body: AwardBody, session: SessionDep) -> SpeedPointsGameRead:
    """Lock in the judge's typed transcription of the player's answer plus
    the points they matched it to for the current question — the text
    becomes visible immediately, but the points stay hidden until
    /reveal-points. Calling this again for the same (still-unrevealed)
    question overwrites the choice, so the judge can correct it before
    committing. Snapshots the current buzzer state (pending_duplicate_flag)
    onto the slot each time, so toggling the buzzer before a (re-)award
    updates what gets baked in."""
    game = _get_game(game_id, session)
    if game.current_player is None:
        raise HTTPException(status_code=400, detail="No active round")
    if game.current_question_index >= QUESTIONS_PER_ROUND:
        raise HTTPException(status_code=400, detail="Round already complete")

    slots_field = _slots_field_for(game)
    slots = json.loads(getattr(game, slots_field))
    slots[game.current_question_index] = AnswerSlot(
        text=body.text,
        points=body.points,
        revealed=False,
        duplicate=game.pending_duplicate_flag,
    ).model_dump()
    setattr(game, slots_field, json.dumps(slots))
    return _to_read(_save(game, session))


@router.patch("/{game_id}/reveal-points", response_model=SpeedPointsGameRead)
def reveal_points(game_id: str, session: SessionDep) -> SpeedPointsGameRead:
    """Reveal the current question's points (the second reveal beat),
    then advance to the next question in this player's leg."""
    game = _get_game(game_id, session)
    if game.current_player is None:
        raise HTTPException(status_code=400, detail="No active round")
    if game.current_question_index >= QUESTIONS_PER_ROUND:
        raise HTTPException(status_code=400, detail="Round already complete")

    slots_field = _slots_field_for(game)
    slots = json.loads(getattr(game, slots_field))
    slot = slots[game.current_question_index]
    if slot is None:
        raise HTTPException(status_code=400, detail="No answer selected yet")

    slot["revealed"] = True
    setattr(game, slots_field, json.dumps(slots))
    game.current_question_index += 1
    # The buzzer applies to the question just resolved (already baked into
    # its slot above) — clear it so it doesn't leak into the next question.
    game.pending_duplicate_flag = False
    return _to_read(_save(game, session))


class DuplicateFlagBody(SQLModel):
    flagged: bool


@router.patch("/{game_id}/duplicate-flag", response_model=SpeedPointsGameRead)
def set_duplicate_flag(
    game_id: str, body: DuplicateFlagBody, session: SessionDep
) -> SpeedPointsGameRead:
    """The judge's buzzer: flag (or clear) that the current question's
    answer duplicates the other player's — a standalone action, settable
    any time before /reveal-points regardless of whether an answer has
    been typed in yet. Scoring/display behavior for a flagged duplicate
    is still TBD; this just records the marker."""
    game = _get_game(game_id, session)
    game.pending_duplicate_flag = body.flagged
    return _to_read(_save(game, session))


@router.patch("/{game_id}/reveal-result", response_model=SpeedPointsGameRead)
def reveal_result(game_id: str, session: SessionDep) -> SpeedPointsGameRead:
    game = _get_game(game_id, session)
    game.scores_revealed = True
    return _to_read(_save(game, session))


@router.get("/{game_id}/answer-options", response_model=list[AnswerOptionRead])
def answer_options(game_id: str, session: SessionDep) -> list[AnswerOptionRead]:
    """Judge-only reference: the current question's possible answers and
    their point values, for picking which one the player's spoken answer
    matches. Never exposed on the Main view's response shape."""
    game = _get_game(game_id, session)
    question = current_question(game) if game.current_player is not None else None
    if question is None:
        raise HTTPException(status_code=400, detail="No active question")
    return [AnswerOptionRead(text=a.text, points=a.points) for a in question.answers]


class PlayersBody(SQLModel):
    player1_name: str | None = None
    player2_name: str | None = None


@router.patch("/{game_id}/players", response_model=SpeedPointsGameRead)
def update_players(
    game_id: str, body: PlayersBody, session: SessionDep
) -> SpeedPointsGameRead:
    game = _get_game(game_id, session)
    if body.player1_name is not None:
        game.player1_name = body.player1_name
    if body.player2_name is not None:
        game.player2_name = body.player2_name
    return _to_read(_save(game, session))


@router.patch("/{game_id}/reset", response_model=SpeedPointsGameRead)
def reset_game(game_id: str, session: SessionDep) -> SpeedPointsGameRead:
    """Reset round state for a fresh relay — player names and the chosen
    question set are kept."""
    game = _get_game(game_id, session)
    _reset_round_state(game)
    return _to_read(_save(game, session))
