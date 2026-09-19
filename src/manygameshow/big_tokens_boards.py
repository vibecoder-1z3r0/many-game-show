"""Board content loading for Big Tokens, No Hallucinations (Press Your
Luck-style). Board content is data, not code — same content-as-data
pattern as questions.py/speed_points_questions.py — so a board's square
layout, hallucination severity, and difficulty knobs can be authored
without touching game logic. Override with BIG_TOKENS_BOARDS_PATH to
point at a different board set.
"""

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

SQUARES_PER_BOARD = 18

_DEFAULT_BOARDS_PATH = Path(__file__).parent / "data" / "big_tokens_boards.sample.json"

ItemType = Literal[
    "tokens",
    "double",
    "free_spin",
    "steal",
    "swap_scores",
    "hallucination",
    "choice_swap_or_free_spin",
    "choice_tokens_or_cure",
]


class BoardItem(BaseModel):
    type: ItemType
    label: str
    # Only meaningful for "tokens", "steal", and "choice_tokens_or_cure".
    amount: int | None = None


class BoardSquare(BaseModel):
    """A board position's cascading face sequence — landing on it advances
    to the next item (clamped at the last one) rather than replaying the
    same item forever."""

    items: list[BoardItem]


class Board(BaseModel):
    id: str
    name: str
    max_hallucinations: int
    wipe_on_every_hallucination: bool
    elimination_scope: Literal["game", "round"]
    squares: list[BoardSquare]


def _boards_path() -> Path:
    override = os.environ.get("BIG_TOKENS_BOARDS_PATH")
    return Path(override) if override else _DEFAULT_BOARDS_PATH


@lru_cache
def load_boards() -> dict[str, Board]:
    path = _boards_path()
    data = json.loads(path.read_text())
    boards = [Board.model_validate(b) for b in data["boards"]]
    return {b.id: b for b in boards}


def get_board(board_id: str) -> Board | None:
    return load_boards().get(board_id)


def list_boards() -> list[Board]:
    return list(load_boards().values())
