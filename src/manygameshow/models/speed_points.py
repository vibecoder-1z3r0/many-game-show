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


class AnswerSlot(SQLModel):
    """One question's judged answer for one player. All 5 questions are
    workable at once (not one-at-a-time), in whatever order the judge
    hears answers in. Text and points are independently drafted and
    independently locked/revealed — a judge can lock in (and reveal) the
    contestant's words before deciding the score, or vice versa; each
    lock is its own explicit action, reversible (unlock) before the
    other side locks if the judge needs to correct something."""

    text: str = ""
    points: int = 0
    text_revealed: bool = False
    points_revealed: bool = False
    # Buzzer: "this answer duplicates the other player's" — a plain
    # per-question toggle, freely settable any time. Main-view/scoring
    # behavior for a flagged duplicate is still TBD; this just carries
    # the marker.
    duplicate: bool = False


def _default_question_ids_json() -> str:
    return json.dumps([])


def _default_slots_json() -> str:
    return json.dumps([AnswerSlot().model_dump()] * QUESTIONS_PER_ROUND)


class SpeedPointsGame(SQLModel, table=True):
    __tablename__ = "speed_points_games"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    player1_name: str = Field(default="Player 1")
    player2_name: str = Field(default="Player 2")

    # The 5 questions both players face, chosen once at creation — JSON list
    # of question ids, in play order.
    question_ids_json: str = Field(default_factory=_default_question_ids_json)

    current_player: Player | None = Field(default=None)

    # JSON list of exactly QUESTIONS_PER_ROUND AnswerSlot dicts, index-
    # aligned with question_ids_json. Parsed in player_slots()/the router,
    # never in the model itself.
    player1_slots_json: str = Field(default_factory=_default_slots_json)
    player2_slots_json: str = Field(default_factory=_default_slots_json)

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
    so neither Main nor the Host view ever leaks the answer/points key
    the judge uses to score."""

    id: str
    prompt: str


class AnswerOptionRead(SQLModel):
    text: str
    points: int


class QuestionAnswerKeyRead(SQLModel):
    """Judge-only: one question's prompt plus its full answer key —
    never exposed on Main's or Host's response shape."""

    id: str
    prompt: str
    answers: list[AnswerOptionRead]


class SlotRead(SQLModel):
    """A player's judged-answer tile as Main/Host see it: text/points are
    each null until that specific side is locked/revealed — the two are
    independent, not a single combined reveal."""

    text: str | None
    points: int | None
    duplicate: bool


class JudgeSlotRead(SQLModel):
    """A player's judged-answer tile as the Judge sees it: the judge is
    the one who typed the draft, so unlike SlotRead this never hides
    anything — draft text/points are visible before locking too, plus the
    lock flags themselves so the UI knows whether a field is editable."""

    text: str
    points: int
    text_revealed: bool
    points_revealed: bool
    duplicate: bool


class SpeedPointsGameRead(SQLModel):
    id: str
    player1_name: str
    player2_name: str
    current_player: Player | None
    # Every question's prompt, spoiler-free, in play order — lets the Host
    # view show the full rundown, and Judge pair each row with its prompt.
    all_questions: list[QuestionPromptRead]
    player1_slots: list[SlotRead]
    player2_slots: list[SlotRead]
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


class JudgeGameRead(SQLModel):
    """Everything the Judge view needs, in one poll — same shape as
    SpeedPointsGameRead but with full-visibility slots (JudgeSlotRead)
    instead of the spoiler-gated ones Main/Host get."""

    id: str
    player1_name: str
    player2_name: str
    current_player: Player | None
    all_questions: list[QuestionPromptRead]
    player1_slots: list[JudgeSlotRead]
    player2_slots: list[JudgeSlotRead]
    player1_total: int
    player2_total: int
    combined_total: int
    win_threshold: int
    won: bool
    scores_revealed: bool
    remaining_seconds: int | None
    timer_duration_seconds: int
    status: str


def question_ids(game: SpeedPointsGame) -> list[str]:
    result: list[str] = json.loads(game.question_ids_json)
    return result


def current_questions(game: SpeedPointsGame) -> list[Question]:
    return [q for qid in question_ids(game) if (q := get_question(qid)) is not None]


def _slots_json_field(player: Player) -> str:
    return "player1_slots_json" if player == Player.PLAYER1 else "player2_slots_json"


def player_slots(game: SpeedPointsGame, player: Player) -> list[AnswerSlot]:
    raw: list[dict[str, object]] = json.loads(getattr(game, _slots_json_field(player)))
    return [AnswerSlot.model_validate(s) for s in raw]


def player_total(game: SpeedPointsGame, player: Player) -> int:
    return sum(s.points for s in player_slots(game, player) if s.points_revealed)


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
