"""Squad Squabble — Family-Feud-style survey game state."""

import json
import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlmodel import Field, SQLModel

from manygameshow.questions import Question, get_question


def _utcnow() -> datetime:
    """Naive UTC timestamp for SQLite compatibility."""
    return datetime.now(UTC).replace(tzinfo=None)


class Team(StrEnum):
    TEAM1 = "team1"
    TEAM2 = "team2"


def _default_revealed_json() -> str:
    return json.dumps([])


class SquadSquabbleGame(SQLModel, table=True):
    __tablename__ = "squad_squabble_games"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    team1_name: str = Field(default="Team 1")
    team2_name: str = Field(default="Team 2")
    team1_score: int = Field(default=0, ge=0)
    team2_score: int = Field(default=0, ge=0)

    current_round: int = Field(default=1, ge=1)

    current_question_id: str | None = Field(default=None)
    question_visible: bool = Field(default=False)
    multiplier: int = Field(default=1, ge=1, le=3)
    controlling_team: Team | None = Field(default=None)
    strikes: int = Field(default=0, ge=0, le=3)

    # JSON string: list of revealed answer indices (into the current
    # question's answers array), e.g. "[0, 2]". Points for revealed answers
    # accumulate into a round pot (see round_points below) — they are NOT
    # credited to a team's score until the host explicitly awards the round.
    revealed_answer_indices_json: str = Field(default_factory=_default_revealed_json)

    status: str = Field(default="active")

    # Display-view strike callout timing — kept server-side (not a
    # localStorage-only setting) since Control and Display may run on
    # different devices (e.g. host's phone vs. a venue projector laptop),
    # and this app's design principle is server-authoritative state.
    strike_anim_hold_ms: int = Field(default=1000, ge=0, le=5000)
    strike_anim_duration_ms: int = Field(default=800, ge=100, le=5000)

    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class SquadSquabbleGameCreate(SQLModel):
    team1_name: str = "Team 1"
    team2_name: str = "Team 2"


class AnswerRead(SQLModel):
    text: str
    points: int
    revealed: bool


class QuestionRead(SQLModel):
    id: str
    prompt: str
    answers: list[AnswerRead]


class SquadSquabbleGameRead(SQLModel):
    """Response schema — replaces the raw question id/revealed-indices with
    the fully resolved question and per-answer revealed state."""

    id: str
    team1_name: str
    team2_name: str
    team1_score: int
    team2_score: int
    current_round: int
    current_question: QuestionRead | None
    question_visible: bool
    multiplier: int
    controlling_team: Team | None
    strikes: int
    round_points: int
    status: str
    strike_anim_hold_ms: int
    strike_anim_duration_ms: int
    created_at: datetime
    updated_at: datetime


def revealed_indices(game: SquadSquabbleGame) -> list[int]:
    result: list[int] = json.loads(game.revealed_answer_indices_json)
    return result


def current_question(game: SquadSquabbleGame) -> Question | None:
    if game.current_question_id is None:
        return None
    return get_question(game.current_question_id)


def round_points(game: SquadSquabbleGame) -> int:
    """Sum of revealed answers' points, times the round multiplier — the
    pot accumulated so far this round, not yet attributed to a team."""
    question = current_question(game)
    if question is None:
        return 0
    revealed = revealed_indices(game)
    total = sum(
        question.answers[i].points for i in revealed if 0 <= i < len(question.answers)
    )
    return total * game.multiplier
