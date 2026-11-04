"""Question bank loading for Speed Points (Fast Money).

Same content-as-data pattern as questions.py (Squad Squabble's loader),
but organised as named banks — like Overdrive's — because the host picks
one bank per game. A bank is a list of questions in the same Question /
Answer shape Squad Squabble uses; the first 5 questions of the chosen bank
are played, in file order, so both players face the same 5 questions.
"""

import json
import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from manygameshow.questions import Answer, Question

__all__ = ["Answer", "Question", "QuestionBank", "get_bank", "list_banks"]

_DEFAULT_QUESTIONS_PATH = (
    Path(__file__).parent / "data" / "speed_points_questions.sample.json"
)


class QuestionBank(BaseModel):
    id: str
    name: str
    questions: list[Question]


def _questions_path() -> Path:
    override = os.environ.get("SPEED_POINTS_QUESTIONS_PATH")
    return Path(override) if override else _DEFAULT_QUESTIONS_PATH


@lru_cache
def load_banks() -> dict[str, QuestionBank]:
    data = json.loads(_questions_path().read_text())
    banks = [QuestionBank.model_validate(b) for b in data["banks"]]
    return {b.id: b for b in banks}


def get_bank(bank_id: str) -> QuestionBank | None:
    return load_banks().get(bank_id)


def list_banks() -> list[QuestionBank]:
    return list(load_banks().values())
