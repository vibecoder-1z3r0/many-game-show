"""Speed Points — Fast-Money-style relay game state."""

import json
import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlmodel import Field, SQLModel

from manygameshow.speed_points_questions import Question, get_question

QUESTIONS_PER_ROUND = 5

# Classic Fast Money split: the second player gets more time since they're
# also avoiding duplicate answers against the first player's (already
# locked-in, but not yet revealed) picks.
DEFAULT_TIMER_SECONDS = {"player1": 20, "player2": 25}


def _utcnow() -> datetime:
    """Naive UTC timestamp for SQLite compatibility."""
    return datetime.now(UTC).replace(tzinfo=None)


class Player(StrEnum):
    PLAYER1 = "player1"
    PLAYER2 = "player2"


def _default_question_ids_json() -> str:
    return json.dumps([])


def _default_points_json() -> str:
    return json.dumps([None] * QUESTIONS_PER_ROUND)


class SpeedPointsGame(SQLModel, table=True):
    __tablename__ = "speed_points_games"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    player1_name: str = Field(default="Player 1")
    player2_name: str = Field(default="Player 2")

    # The 5 questions both players face, chosen once at creation — JSON list
    # of question ids, in play order.
    question_ids_json: str = Field(default_factory=_default_question_ids_json)

    current_player: Player | None = Field(default=None)
    current_question_index: int = Field(default=0, ge=0, le=QUESTIONS_PER_ROUND)

    # JSON list of QUESTIONS_PER_ROUND ints-or-null: points awarded per
    # question, in the same order as question_ids_json. null = not yet
    # answered. Parsed in the router/Read layer, never in the model itself.
    player1_points_json: str = Field(default_factory=_default_points_json)
    player2_points_json: str = Field(default_factory=_default_points_json)

    # Countdown for the current player's round, server-authoritative (per
    # ARCHITECTURE.md: store started_at + duration, compute elapsed on every
    # read — never a client-side timer).
    timer_started_at: datetime | None = Field(default=None)
    timer_duration_seconds: int = Field(default=20, ge=1, le=300)

    win_threshold: int = Field(default=200, ge=1)
    scores_revealed: bool = Field(default=False)

    status: str = Field(default="active")

    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class SpeedPointsGameCreate(SQLModel):
    player1_name: str = "Player 1"
    player2_name: str = "Player 2"


class QuestionPromptRead(SQLModel):
    """Spoiler-free question view for the main Read schema — no answers,
    so Display never leaks the answer/points key the host uses to judge."""

    id: str
    prompt: str


class AnswerOptionRead(SQLModel):
    text: str
    points: int


class SpeedPointsGameRead(SQLModel):
    id: str
    player1_name: str
    player2_name: str
    current_player: Player | None
    current_question_index: int
    current_question: QuestionPromptRead | None
    player1_points: list[int | None]
    player2_points: list[int | None]
    player1_total: int
    player2_total: int
    combined_total: int
    win_threshold: int
    won: bool
    scores_revealed: bool
    remaining_seconds: int | None
    timer_duration_seconds: int
    status: str
    created_at: datetime
    updated_at: datetime


def question_ids(game: SpeedPointsGame) -> list[str]:
    result: list[str] = json.loads(game.question_ids_json)
    return result


def current_questions(game: SpeedPointsGame) -> list[Question]:
    return [q for qid in question_ids(game) if (q := get_question(qid)) is not None]


def current_question(game: SpeedPointsGame) -> Question | None:
    questions = current_questions(game)
    if 0 <= game.current_question_index < len(questions):
        return questions[game.current_question_index]
    return None


def _points_json_field(player: Player) -> str:
    return "player1_points_json" if player == Player.PLAYER1 else "player2_points_json"


def player_points(game: SpeedPointsGame, player: Player) -> list[int | None]:
    result: list[int | None] = json.loads(getattr(game, _points_json_field(player)))
    return result


def player_total(game: SpeedPointsGame, player: Player) -> int:
    return sum(p for p in player_points(game, player) if p is not None)


def combined_total(game: SpeedPointsGame) -> int:
    return player_total(game, Player.PLAYER1) + player_total(game, Player.PLAYER2)


def remaining_seconds(game: SpeedPointsGame, now: datetime | None = None) -> int | None:
    if game.timer_started_at is None:
        return None
    now = now if now is not None else _utcnow()
    elapsed = (now - game.timer_started_at).total_seconds()
    # round rather than floor: a fresh timer (elapsed ~0ms) should still
    # read as the full duration, not duration-1 from truncation noise.
    return max(0, round(game.timer_duration_seconds - elapsed))
