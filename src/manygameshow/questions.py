"""Question bank loading for survey-style games (e.g. Squad Squabble).

Question content is data, not code — it lives in a JSON file so it can be
authored/edited without touching game logic. The path defaults to the
bundled sample/test set; override with SQUAD_SQUABBLE_QUESTIONS_PATH to
point at real content (e.g. the presenter's own question set) without a
code change.
"""

import json
import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

_DEFAULT_QUESTIONS_PATH = (
    Path(__file__).parent / "data" / "squad_squabble_questions.sample.json"
)


class Answer(BaseModel):
    text: str
    points: int


class Question(BaseModel):
    id: str
    prompt: str
    answers: list[Answer]


def _questions_path() -> Path:
    override = os.environ.get("SQUAD_SQUABBLE_QUESTIONS_PATH")
    return Path(override) if override else _DEFAULT_QUESTIONS_PATH


@lru_cache
def load_questions() -> dict[str, Question]:
    path = _questions_path()
    data = json.loads(path.read_text())
    questions = [Question.model_validate(q) for q in data["questions"]]
    return {q.id: q for q in questions}


def get_question(question_id: str) -> Question | None:
    return load_questions().get(question_id)


def list_questions() -> list[Question]:
    return list(load_questions().values())
