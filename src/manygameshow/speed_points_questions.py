"""Question bank loading for Speed Points (Fast Money).

Same content-as-data pattern as questions.py (Squad Squabble's loader) —
a separate module/file/env-override because Speed Points draws from its
own bank, even though the Question/Answer shape is identical. Exactly the
first 5 questions in the bank are used per game, in file order, so both
players face the same 5 questions.
"""

import json
import os
from functools import lru_cache
from pathlib import Path

from manygameshow.questions import Answer, Question

__all__ = ["Answer", "Question", "get_question", "list_questions"]

_DEFAULT_QUESTIONS_PATH = (
    Path(__file__).parent / "data" / "speed_points_questions.sample.json"
)


def _questions_path() -> Path:
    override = os.environ.get("SPEED_POINTS_QUESTIONS_PATH")
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
