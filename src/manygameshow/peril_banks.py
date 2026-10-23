"""Board content loading for Peril (Jeopardy-style). Content is data,
not code — same content-as-data pattern as the other games' loaders —
so categories/clues/wording can be authored without touching game
logic. Each round type (round1, round2, final) has its own bank file
and env var override, mirroring how Big Tokens supports multiple
selectable boards: a "bank" is one full round's worth of content, and
the host picks one per round type at game creation.
"""

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

_DEFAULT_ROUND1_PATH = Path(__file__).parent / "data" / "peril_round1.sample.json"
_DEFAULT_ROUND2_PATH = Path(__file__).parent / "data" / "peril_round2.sample.json"
_DEFAULT_FINAL_PATH = Path(__file__).parent / "data" / "peril_final.sample.json"

# 0 = never a Stake Stacker. 1 = usable as round 1's single Stake Stacker or
# as one of round 2's two. 2 = usable only as one of round 2's two. This
# is purely a content-authoring convenience for building a shared clue
# pool across banks — whichever clues end up with a nonzero value in
# whichever bank is actually loaded for a round ARE that round's Stake
# Stacker(s); the engine doesn't treat 1 vs 2 differently at runtime.
StakeStackerFlag = Literal[0, 1, 2]


class ClueContent(BaseModel):
    text: str
    answer: str
    value: int
    stake_stacker: StakeStackerFlag = 0


class CategoryContent(BaseModel):
    name: str
    clues: list[ClueContent]


class RoundBank(BaseModel):
    id: str
    name: str
    categories: list[CategoryContent]


class FinalBank(BaseModel):
    id: str
    name: str
    category: str
    text: str
    answer: str


def _round1_path() -> Path:
    override = os.environ.get("PERIL_ROUND1_BANKS_PATH")
    return Path(override) if override else _DEFAULT_ROUND1_PATH


def _round2_path() -> Path:
    override = os.environ.get("PERIL_ROUND2_BANKS_PATH")
    return Path(override) if override else _DEFAULT_ROUND2_PATH


def _final_path() -> Path:
    override = os.environ.get("PERIL_FINAL_BANKS_PATH")
    return Path(override) if override else _DEFAULT_FINAL_PATH


@lru_cache
def load_round1_banks() -> dict[str, RoundBank]:
    data = json.loads(_round1_path().read_text())
    banks = [RoundBank.model_validate(b) for b in data["banks"]]
    return {b.id: b for b in banks}


@lru_cache
def load_round2_banks() -> dict[str, RoundBank]:
    data = json.loads(_round2_path().read_text())
    banks = [RoundBank.model_validate(b) for b in data["banks"]]
    return {b.id: b for b in banks}


@lru_cache
def load_final_banks() -> dict[str, FinalBank]:
    data = json.loads(_final_path().read_text())
    banks = [FinalBank.model_validate(b) for b in data["banks"]]
    return {b.id: b for b in banks}


def get_round1_bank(bank_id: str) -> RoundBank | None:
    return load_round1_banks().get(bank_id)


def get_round2_bank(bank_id: str) -> RoundBank | None:
    return load_round2_banks().get(bank_id)


def get_final_bank(bank_id: str) -> FinalBank | None:
    return load_final_banks().get(bank_id)


def list_round1_banks() -> list[RoundBank]:
    return list(load_round1_banks().values())


def list_round2_banks() -> list[RoundBank]:
    return list(load_round2_banks().values())


def list_final_banks() -> list[FinalBank]:
    return list(load_final_banks().values())
