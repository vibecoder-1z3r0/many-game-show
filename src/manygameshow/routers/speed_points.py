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
    Player,
    QuestionPromptRead,
    SpeedPointsGame,
    SpeedPointsGameCreate,
    SpeedPointsGameRead,
    combined_total,
    current_question,
    player_points,
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
        player1_points=player_points(game, Player.PLAYER1),
        player2_points=player_points(game, Player.PLAYER2),
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


def _reset_round_state(game: SpeedPointsGame) -> None:
    game.current_player = None
    game.current_question_index = 0
    game.player1_points_json = json.dumps([None] * QUESTIONS_PER_ROUND)
    game.player2_points_json = json.dumps([None] * QUESTIONS_PER_ROUND)
    game.timer_started_at = None
    game.scores_revealed = False


class StartRoundBody(SQLModel):
    player: Player
    duration_seconds: int | None = Field(default=None, ge=1, le=300)


@router.patch("/{game_id}/start-round", response_model=SpeedPointsGameRead)
def start_round(
    game_id: str, body: StartRoundBody, session: SessionDep
) -> SpeedPointsGameRead:
    """Start (or restart) one player's 5-question relay leg: resets their
    points, rewinds to question 1, and starts their countdown."""
    game = _get_game(game_id, session)
    game.current_player = body.player
    game.current_question_index = 0
    points_field = (
        "player1_points_json"
        if body.player == Player.PLAYER1
        else "player2_points_json"
    )
    setattr(game, points_field, json.dumps([None] * QUESTIONS_PER_ROUND))
    game.timer_duration_seconds = (
        body.duration_seconds
        if body.duration_seconds is not None
        else DEFAULT_TIMER_SECONDS[body.player.value]
    )
    game.timer_started_at = datetime.now(UTC).replace(tzinfo=None)
    return _to_read(_save(game, session))


class AwardBody(SQLModel):
    points: int = Field(ge=0)


@router.patch("/{game_id}/award", response_model=SpeedPointsGameRead)
def award(game_id: str, body: AwardBody, session: SessionDep) -> SpeedPointsGameRead:
    """Record the host's judged points for the current question (0 = no
    match), then advance to the next question in this player's leg."""
    game = _get_game(game_id, session)
    if game.current_player is None:
        raise HTTPException(status_code=400, detail="No active round")
    if game.current_question_index >= QUESTIONS_PER_ROUND:
        raise HTTPException(status_code=400, detail="Round already complete")

    points_field = (
        "player1_points_json"
        if game.current_player == Player.PLAYER1
        else "player2_points_json"
    )
    points = json.loads(getattr(game, points_field))
    points[game.current_question_index] = body.points
    setattr(game, points_field, json.dumps(points))
    game.current_question_index += 1
    return _to_read(_save(game, session))


@router.patch("/{game_id}/reveal-result", response_model=SpeedPointsGameRead)
def reveal_result(game_id: str, session: SessionDep) -> SpeedPointsGameRead:
    game = _get_game(game_id, session)
    game.scores_revealed = True
    return _to_read(_save(game, session))


@router.get("/{game_id}/answer-options", response_model=list[AnswerOptionRead])
def answer_options(game_id: str, session: SessionDep) -> list[AnswerOptionRead]:
    """Host-only reference: the current question's possible answers and
    their point values, for judging which one the player's spoken answer
    matches. Never exposed on the Display view's response shape."""
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
