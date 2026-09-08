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
    JudgeGameRead,
    JudgeSlotRead,
    Player,
    QuestionAnswerKeyRead,
    QuestionPromptRead,
    SlotRead,
    SpeedPointsGame,
    SpeedPointsGameCreate,
    SpeedPointsGameRead,
    combined_total,
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


def _slot_read(slot: AnswerSlot) -> SlotRead:
    return SlotRead(
        text=slot.text if slot.text_revealed else None,
        points=slot.points if slot.points_revealed else None,
        duplicate=slot.duplicate,
    )


def _judge_slot_read(slot: AnswerSlot) -> JudgeSlotRead:
    return JudgeSlotRead(
        text=slot.text,
        points=slot.points,
        text_revealed=slot.text_revealed,
        points_revealed=slot.points_revealed,
        duplicate=slot.duplicate,
    )


def _to_judge_read(game: SpeedPointsGame) -> JudgeGameRead:
    total = combined_total(game)
    return JudgeGameRead(
        id=game.id,
        player1_name=game.player1_name,
        player2_name=game.player2_name,
        current_player=game.current_player,
        all_questions=[
            QuestionPromptRead(id=q.id, prompt=q.prompt)
            for q in current_questions(game)
        ],
        player1_slots=[_judge_slot_read(s) for s in player_slots(game, Player.PLAYER1)],
        player2_slots=[_judge_slot_read(s) for s in player_slots(game, Player.PLAYER2)],
        player1_total=player_total(game, Player.PLAYER1),
        player2_total=player_total(game, Player.PLAYER2),
        combined_total=total,
        win_threshold=game.win_threshold,
        won=total >= game.win_threshold,
        scores_revealed=game.scores_revealed,
        remaining_seconds=remaining_seconds(game),
        timer_duration_seconds=game.timer_duration_seconds,
        status=game.status,
    )


def _to_read(game: SpeedPointsGame) -> SpeedPointsGameRead:
    total = combined_total(game)
    return SpeedPointsGameRead(
        id=game.id,
        player1_name=game.player1_name,
        player2_name=game.player2_name,
        current_player=game.current_player,
        all_questions=[
            QuestionPromptRead(id=q.id, prompt=q.prompt)
            for q in current_questions(game)
        ],
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


@router.get("/{game_id}/judge", response_model=JudgeGameRead)
def get_judge_game(game_id: str, session: SessionDep) -> JudgeGameRead:
    """Judge-only poll target: full visibility into every slot's draft
    text/points and lock state, regardless of whether they're revealed to
    Main/Host yet — the judge is the one who typed them in the first
    place, so hiding a draft from its own author would just break the
    type-then-lock workflow. Never used by Main or Host."""
    return _to_judge_read(_get_game(game_id, session))


@router.delete("/{game_id}", status_code=204)
def delete_game(game_id: str, session: SessionDep) -> None:
    game = _get_game(game_id, session)
    session.delete(game)
    session.commit()


def _fresh_slots_json() -> str:
    return json.dumps([AnswerSlot().model_dump()] * QUESTIONS_PER_ROUND)


def _reset_round_state(game: SpeedPointsGame) -> None:
    game.current_player = None
    game.player1_slots_json = _fresh_slots_json()
    game.player2_slots_json = _fresh_slots_json()
    game.timer_started_at = None
    game.scores_revealed = False


class StartRoundBody(SQLModel):
    player: Player
    duration_seconds: int | None = Field(default=None, ge=1, le=300)


@router.patch("/{game_id}/start-round", response_model=SpeedPointsGameRead)
def start_round(
    game_id: str, body: StartRoundBody, session: SessionDep
) -> SpeedPointsGameRead:
    """Start (or restart) one player's leg: resets their 5 slots to blank
    and starts their countdown."""
    game = _get_game(game_id, session)
    game.current_player = body.player
    slots_field = (
        "player1_slots_json" if body.player == Player.PLAYER1 else "player2_slots_json"
    )
    setattr(game, slots_field, _fresh_slots_json())
    game.timer_duration_seconds = (
        body.duration_seconds
        if body.duration_seconds is not None
        else DEFAULT_TIMER_SECONDS[body.player.value]
    )
    game.timer_started_at = datetime.now(UTC).replace(tzinfo=None)
    return _to_read(_save(game, session))


def _slots_field_for(game: SpeedPointsGame) -> str:
    if game.current_player is None:
        raise HTTPException(status_code=400, detail="No active round")
    return (
        "player1_slots_json"
        if game.current_player == Player.PLAYER1
        else "player2_slots_json"
    )


def _load_slots(game: SpeedPointsGame) -> list[dict]:
    slots_field = _slots_field_for(game)
    slots: list[dict] = json.loads(getattr(game, slots_field))
    return slots


def _save_slots(game: SpeedPointsGame, slots: list[dict]) -> None:
    setattr(game, _slots_field_for(game), json.dumps(slots))


def _slot_at(slots: list[dict], question_index: int) -> dict:
    if not (0 <= question_index < QUESTIONS_PER_ROUND):
        raise HTTPException(status_code=422, detail="question_index out of range")
    return slots[question_index]


class AnswerBody(SQLModel):
    question_index: int
    text: str


@router.patch("/{game_id}/answer", response_model=JudgeGameRead)
def set_answer(game_id: str, body: AnswerBody, session: SessionDep) -> JudgeGameRead:
    """Draft (or redraft) the judge's typed transcription of what the
    contestant said for one question. Only while that side is unlocked —
    unlock it first (PATCH .../answer-lock) to correct an already-revealed
    answer."""
    game = _get_game(game_id, session)
    slots = _load_slots(game)
    slot = _slot_at(slots, body.question_index)
    if slot["text_revealed"]:
        raise HTTPException(
            status_code=400, detail="Answer is locked — unlock it to edit"
        )
    slot["text"] = body.text
    _save_slots(game, slots)
    return _to_judge_read(_save(game, session))


class LockBody(SQLModel):
    question_index: int
    locked: bool


@router.patch("/{game_id}/answer-lock", response_model=JudgeGameRead)
def set_answer_lock(game_id: str, body: LockBody, session: SessionDep) -> JudgeGameRead:
    """Lock (reveal on Main) or unlock (hide again, re-open for editing)
    one question's answer text — independent of its points."""
    game = _get_game(game_id, session)
    slots = _load_slots(game)
    slot = _slot_at(slots, body.question_index)
    slot["text_revealed"] = body.locked
    _save_slots(game, slots)
    return _to_judge_read(_save(game, session))


class PointsBody(SQLModel):
    question_index: int
    points: int = Field(ge=0)


@router.patch("/{game_id}/points", response_model=JudgeGameRead)
def set_points(game_id: str, body: PointsBody, session: SessionDep) -> JudgeGameRead:
    """Draft (or redraft) one question's awarded points — from clicking an
    answer-key option (pre-fill) or typed directly by the judge (override).
    Only while unlocked."""
    game = _get_game(game_id, session)
    slots = _load_slots(game)
    slot = _slot_at(slots, body.question_index)
    if slot["points_revealed"]:
        raise HTTPException(
            status_code=400, detail="Points are locked — unlock them to edit"
        )
    slot["points"] = body.points
    _save_slots(game, slots)
    return _to_judge_read(_save(game, session))


@router.patch("/{game_id}/points-lock", response_model=JudgeGameRead)
def set_points_lock(game_id: str, body: LockBody, session: SessionDep) -> JudgeGameRead:
    """Lock (reveal on Main) or unlock one question's points — independent
    of its answer text."""
    game = _get_game(game_id, session)
    slots = _load_slots(game)
    slot = _slot_at(slots, body.question_index)
    slot["points_revealed"] = body.locked
    _save_slots(game, slots)
    return _to_judge_read(_save(game, session))


class DuplicateFlagBody(SQLModel):
    question_index: int
    flagged: bool


@router.patch("/{game_id}/duplicate-flag", response_model=JudgeGameRead)
def set_duplicate_flag(
    game_id: str, body: DuplicateFlagBody, session: SessionDep
) -> JudgeGameRead:
    """The judge's buzzer for one question: player 2 repeated an answer
    player 1 already gave, so the contestant gets to answer again.
    Only meaningful during player 2's turn (there's nothing to duplicate
    against during player 1's) — hit it as soon as the repeat happens,
    before typing the contestant's actual (new) answer into the same
    slot, same as normal from there."""
    game = _get_game(game_id, session)
    if game.current_player != Player.PLAYER2:
        raise HTTPException(
            status_code=400,
            detail="Duplicate flag only applies during Player 2's turn",
        )
    slots = _load_slots(game)
    slot = _slot_at(slots, body.question_index)
    slot["duplicate"] = body.flagged
    _save_slots(game, slots)
    return _to_judge_read(_save(game, session))


@router.patch("/{game_id}/reveal-result", response_model=SpeedPointsGameRead)
def reveal_result(game_id: str, session: SessionDep) -> SpeedPointsGameRead:
    game = _get_game(game_id, session)
    game.scores_revealed = True
    return _to_read(_save(game, session))


@router.get("/{game_id}/answer-key", response_model=list[QuestionAnswerKeyRead])
def answer_key(game_id: str, session: SessionDep) -> list[QuestionAnswerKeyRead]:
    """Judge-only reference: all 5 questions' prompts and their full
    answer keys together, for judging any question in any order. Never
    exposed on the Main or Host response shape."""
    game = _get_game(game_id, session)
    return [
        QuestionAnswerKeyRead(
            id=q.id,
            prompt=q.prompt,
            answers=[AnswerOptionRead(text=a.text, points=a.points) for a in q.answers],
        )
        for q in current_questions(game)
    ]


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


@router.patch("/{game_id}/reset", response_model=JudgeGameRead)
def reset_game(game_id: str, session: SessionDep) -> JudgeGameRead:
    """Reset round state for a fresh relay — player names and the chosen
    question set are kept."""
    game = _get_game(game_id, session)
    _reset_round_state(game)
    return _to_judge_read(_save(game, session))
