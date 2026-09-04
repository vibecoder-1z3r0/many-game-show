"""Squad Squabble — /api/squad-squabble/games/* endpoints."""

import json
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, SQLModel, select

from manygameshow.database import get_session
from manygameshow.models.squad_squabble import (
    AnswerRead,
    QuestionRead,
    SquadSquabbleGame,
    SquadSquabbleGameCreate,
    SquadSquabbleGameRead,
    Team,
    current_question,
    revealed_indices,
)
from manygameshow.models.squad_squabble import round_points as compute_round_points
from manygameshow.questions import get_question, list_questions

router = APIRouter(prefix="/api/squad-squabble/games", tags=["squad-squabble"])

SessionDep = Annotated[Session, Depends(get_session)]


def _get_game(game_id: str, session: Session) -> SquadSquabbleGame:
    game = session.get(SquadSquabbleGame, game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="Game not found")
    return game


def _save(game: SquadSquabbleGame, session: Session) -> SquadSquabbleGame:
    game.updated_at = datetime.now(UTC).replace(tzinfo=None)
    session.add(game)
    session.commit()
    session.refresh(game)
    return game


def _to_read(game: SquadSquabbleGame) -> SquadSquabbleGameRead:
    question = current_question(game)
    revealed = set(revealed_indices(game))
    question_read = None
    if question is not None:
        question_read = QuestionRead(
            id=question.id,
            prompt=question.prompt,
            answers=[
                AnswerRead(text=a.text, points=a.points, revealed=i in revealed)
                for i, a in enumerate(question.answers)
            ],
        )
    return SquadSquabbleGameRead(
        id=game.id,
        team1_name=game.team1_name,
        team2_name=game.team2_name,
        team1_score=game.team1_score,
        team2_score=game.team2_score,
        current_round=game.current_round,
        current_question=question_read,
        question_visible=game.question_visible,
        multiplier=game.multiplier,
        controlling_team=game.controlling_team,
        strikes=game.strikes,
        round_points=compute_round_points(game),
        status=game.status,
        created_at=game.created_at,
        updated_at=game.updated_at,
    )


@router.post("/", response_model=SquadSquabbleGameRead)
def create_game(
    body: SquadSquabbleGameCreate, session: SessionDep
) -> SquadSquabbleGameRead:
    game = SquadSquabbleGame(team1_name=body.team1_name, team2_name=body.team2_name)
    session.add(game)
    session.commit()
    session.refresh(game)
    return _to_read(game)


@router.get("/", response_model=list[SquadSquabbleGameRead])
def list_games(session: SessionDep) -> list[SquadSquabbleGameRead]:
    games = session.exec(select(SquadSquabbleGame)).all()
    return [_to_read(g) for g in games]


@router.get("/{game_id}", response_model=SquadSquabbleGameRead)
def get_game(game_id: str, session: SessionDep) -> SquadSquabbleGameRead:
    return _to_read(_get_game(game_id, session))


@router.delete("/{game_id}", status_code=204)
def delete_game(game_id: str, session: SessionDep) -> None:
    game = _get_game(game_id, session)
    session.delete(game)
    session.commit()


@router.get("/{game_id}/questions", response_model=list[QuestionRead])
def get_question_bank(game_id: str, session: SessionDep) -> list[QuestionRead]:
    """List the full question bank (host-side picker; not exposed to Display)."""
    _get_game(game_id, session)  # 404 if game doesn't exist
    return [
        QuestionRead(
            id=q.id,
            prompt=q.prompt,
            answers=[
                AnswerRead(text=a.text, points=a.points, revealed=False)
                for a in q.answers
            ],
        )
        for q in list_questions()
    ]


class LoadQuestionBody(SQLModel):
    question_id: str
    multiplier: int = 1


def _reset_round_state(game: SquadSquabbleGame) -> None:
    game.controlling_team = None
    game.strikes = 0
    game.revealed_answer_indices_json = json.dumps([])


@router.patch("/{game_id}/load-question", response_model=SquadSquabbleGameRead)
def load_question(
    game_id: str, body: LoadQuestionBody, session: SessionDep
) -> SquadSquabbleGameRead:
    game = _get_game(game_id, session)
    if get_question(body.question_id) is None:
        raise HTTPException(status_code=404, detail="Question not found")
    if not (1 <= body.multiplier <= 3):
        raise HTTPException(status_code=422, detail="multiplier must be 1, 2, or 3")

    game.current_question_id = body.question_id
    game.question_visible = False  # hidden by default until the host reveals it
    game.multiplier = body.multiplier
    _reset_round_state(game)
    return _to_read(_save(game, session))


@router.patch("/{game_id}/unload-question", response_model=SquadSquabbleGameRead)
def unload_question(game_id: str, session: SessionDep) -> SquadSquabbleGameRead:
    game = _get_game(game_id, session)
    game.current_question_id = None
    game.question_visible = False
    _reset_round_state(game)
    return _to_read(_save(game, session))


class QuestionVisibilityBody(SQLModel):
    visible: bool


@router.patch("/{game_id}/question-visibility", response_model=SquadSquabbleGameRead)
def set_question_visibility(
    game_id: str, body: QuestionVisibilityBody, session: SessionDep
) -> SquadSquabbleGameRead:
    game = _get_game(game_id, session)
    game.question_visible = body.visible
    return _to_read(_save(game, session))


class FaceOffBody(SQLModel):
    team: Team | None = None


@router.patch("/{game_id}/face-off", response_model=SquadSquabbleGameRead)
def set_face_off(
    game_id: str, body: FaceOffBody, session: SessionDep
) -> SquadSquabbleGameRead:
    """Set which team controls the board, or clear control with team: null."""
    game = _get_game(game_id, session)
    game.controlling_team = body.team
    return _to_read(_save(game, session))


class RevealBody(SQLModel):
    answer_index: int


@router.patch("/{game_id}/reveal", response_model=SquadSquabbleGameRead)
def reveal_answer(
    game_id: str, body: RevealBody, session: SessionDep
) -> SquadSquabbleGameRead:
    """Mark an answer revealed. Its points join the round pot (round_points)
    — nothing is credited to a team's score until /award-round is called."""
    game = _get_game(game_id, session)
    question = current_question(game)
    if question is None:
        raise HTTPException(status_code=400, detail="No question loaded")
    if not (0 <= body.answer_index < len(question.answers)):
        raise HTTPException(status_code=422, detail="answer_index out of range")

    revealed = revealed_indices(game)
    if body.answer_index in revealed:
        raise HTTPException(status_code=400, detail="Answer already revealed")

    revealed.append(body.answer_index)
    game.revealed_answer_indices_json = json.dumps(revealed)

    return _to_read(_save(game, session))


@router.patch("/{game_id}/unreveal", response_model=SquadSquabbleGameRead)
def unreveal_answer(
    game_id: str, body: RevealBody, session: SessionDep
) -> SquadSquabbleGameRead:
    """Undo an accidental reveal — puts an answer back to hidden."""
    game = _get_game(game_id, session)
    question = current_question(game)
    if question is None:
        raise HTTPException(status_code=400, detail="No question loaded")

    revealed = revealed_indices(game)
    if body.answer_index not in revealed:
        raise HTTPException(status_code=400, detail="Answer is not revealed")

    revealed.remove(body.answer_index)
    game.revealed_answer_indices_json = json.dumps(revealed)

    return _to_read(_save(game, session))


@router.patch("/{game_id}/reveal-remaining", response_model=SquadSquabbleGameRead)
def reveal_remaining(game_id: str, session: SessionDep) -> SquadSquabbleGameRead:
    """Reveal every still-hidden answer — e.g. after a successful steal
    guess. Points join the round pot same as any other reveal."""
    game = _get_game(game_id, session)
    question = current_question(game)
    if question is None:
        raise HTTPException(status_code=400, detail="No question loaded")

    game.revealed_answer_indices_json = json.dumps(list(range(len(question.answers))))
    return _to_read(_save(game, session))


class AwardRoundBody(SQLModel):
    team: Team


@router.patch("/{game_id}/award-round", response_model=SquadSquabbleGameRead)
def award_round(
    game_id: str, body: AwardRoundBody, session: SessionDep
) -> SquadSquabbleGameRead:
    """Credit the accumulated round pot to a team's score, then reset
    strikes/control so the board is ready for the next question."""
    game = _get_game(game_id, session)
    points = compute_round_points(game)
    if body.team == Team.TEAM1:
        game.team1_score += points
    else:
        game.team2_score += points
    game.strikes = 0
    game.controlling_team = None
    return _to_read(_save(game, session))


@router.patch("/{game_id}/strike", response_model=SquadSquabbleGameRead)
def add_strike(game_id: str, session: SessionDep) -> SquadSquabbleGameRead:
    game = _get_game(game_id, session)
    if game.strikes >= 3:
        raise HTTPException(status_code=400, detail="Already at 3 strikes")
    game.strikes += 1
    return _to_read(_save(game, session))


@router.patch("/{game_id}/strike/max", response_model=SquadSquabbleGameRead)
def set_max_strikes(game_id: str, session: SessionDep) -> SquadSquabbleGameRead:
    """Jump straight to 3 strikes — the opposing team gets one steal
    attempt; if they miss it, the round ends in strikes with no steal."""
    game = _get_game(game_id, session)
    game.strikes = 3
    return _to_read(_save(game, session))


@router.patch("/{game_id}/strike/reset", response_model=SquadSquabbleGameRead)
def reset_strikes(game_id: str, session: SessionDep) -> SquadSquabbleGameRead:
    game = _get_game(game_id, session)
    game.strikes = 0
    return _to_read(_save(game, session))


class ScoreBody(SQLModel):
    team: Team
    value: int


@router.patch("/{game_id}/score", response_model=SquadSquabbleGameRead)
def set_score(
    game_id: str, body: ScoreBody, session: SessionDep
) -> SquadSquabbleGameRead:
    """Set a team's score to any arbitrary value (including 0, to reset it)."""
    game = _get_game(game_id, session)
    if body.value < 0:
        raise HTTPException(status_code=422, detail="value must be >= 0")
    if body.team == Team.TEAM1:
        game.team1_score = body.value
    else:
        game.team2_score = body.value
    return _to_read(_save(game, session))


class RoundBody(SQLModel):
    round_number: int


@router.patch("/{game_id}/round", response_model=SquadSquabbleGameRead)
def set_round(
    game_id: str, body: RoundBody, session: SessionDep
) -> SquadSquabbleGameRead:
    game = _get_game(game_id, session)
    if body.round_number < 1:
        raise HTTPException(status_code=422, detail="round_number must be >= 1")
    game.current_round = body.round_number
    return _to_read(_save(game, session))


@router.patch("/{game_id}/round/increment", response_model=SquadSquabbleGameRead)
def increment_round(game_id: str, session: SessionDep) -> SquadSquabbleGameRead:
    game = _get_game(game_id, session)
    game.current_round += 1
    return _to_read(_save(game, session))


@router.patch("/{game_id}/round/decrement", response_model=SquadSquabbleGameRead)
def decrement_round(game_id: str, session: SessionDep) -> SquadSquabbleGameRead:
    game = _get_game(game_id, session)
    game.current_round = max(1, game.current_round - 1)
    return _to_read(_save(game, session))


class TeamsBody(SQLModel):
    team1_name: str | None = None
    team2_name: str | None = None


@router.patch("/{game_id}/teams", response_model=SquadSquabbleGameRead)
def update_teams(
    game_id: str, body: TeamsBody, session: SessionDep
) -> SquadSquabbleGameRead:
    game = _get_game(game_id, session)
    if body.team1_name is not None:
        game.team1_name = body.team1_name
    if body.team2_name is not None:
        game.team2_name = body.team2_name
    return _to_read(_save(game, session))


class StatusBody(SQLModel):
    status: str


@router.patch("/{game_id}/status", response_model=SquadSquabbleGameRead)
def set_status(
    game_id: str, body: StatusBody, session: SessionDep
) -> SquadSquabbleGameRead:
    game = _get_game(game_id, session)
    game.status = body.status
    return _to_read(_save(game, session))


@router.patch("/{game_id}/reset", response_model=SquadSquabbleGameRead)
def reset_game(game_id: str, session: SessionDep) -> SquadSquabbleGameRead:
    """Reset scores, round, and board state for a fresh game — team names
    are kept since the same teams are presumably about to play again."""
    game = _get_game(game_id, session)
    game.team1_score = 0
    game.team2_score = 0
    game.current_round = 1
    game.current_question_id = None
    game.question_visible = False
    game.multiplier = 1
    _reset_round_state(game)
    return _to_read(_save(game, session))
