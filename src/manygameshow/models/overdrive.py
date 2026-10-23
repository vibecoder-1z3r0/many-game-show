"""Overdrive (Jeopardy-style) — a 3-round, 3-player trivia board game. See
ADDING_A_GAME.md for the shared conventions this follows.

Content (categories, clues, wording) is data, not code — see
overdrive_banks.py — so a round's board can be authored/swapped without
touching this state machine.
"""

import json
import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlmodel import Field, SQLModel

from manygameshow.overdrive_banks import (
    ClueContent,
    RoundBank,
    get_final_bank,
    get_round1_bank,
    get_round2_bank,
)


def _utcnow() -> datetime:
    """Naive UTC timestamp for SQLite compatibility."""
    return datetime.now(UTC).replace(tzinfo=None)


class Player(StrEnum):
    PLAYER1 = "player1"
    PLAYER2 = "player2"
    PLAYER3 = "player3"


ALL_PLAYERS: list[Player] = [Player.PLAYER1, Player.PLAYER2, Player.PLAYER3]


class RoundName(StrEnum):
    ROUND1 = "round1"
    ROUND2 = "round2"
    FINAL = "final"


class ClueCell(SQLModel):
    """Per-clue mutable state — position in the grid is implicit (its
    index in the round's category/clue arrays)."""

    played: bool = False
    locked_out: list[Player] = Field(default_factory=list)


class TimingOverride(SQLModel):
    start_delay_ms: int | None = None
    window_ms: int | None = None


class FinalEntry(SQLModel):
    """One player's Final Exam participation. wager/answer are that
    player's own secret until revealed is True — callers building a
    public read must redact them until then."""

    eligible: bool = True
    wager: int | None = None
    answer: str | None = None
    submitted: bool = False
    revealed: bool = False
    correct: bool | None = None


class PlayerScore(SQLModel):
    name: str = ""
    score: int = 0


def _default_players_json() -> str:
    return json.dumps(
        [
            PlayerScore(name="Player 1").model_dump(),
            PlayerScore(name="Player 2").model_dump(),
            PlayerScore(name="Player 3").model_dump(),
        ]
    )


def _default_final_entries_json() -> str:
    return json.dumps({p.value: FinalEntry().model_dump() for p in ALL_PLAYERS})


class OverdriveGame(SQLModel, table=True):
    __tablename__ = "overdrive_games"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    round1_bank_id: str = Field(default="classic")
    round2_bank_id: str = Field(default="classic")
    final_bank_id: str = Field(default="classic")

    players_json: str = Field(default_factory=_default_players_json)
    current_round: RoundName = Field(default=RoundName.ROUND1)

    # Reset whenever current_round changes. JSON list[bool], one per
    # category in the current round's bank.
    categories_revealed_json: str = Field(default="[]")
    # JSON list[list[ClueCell dict]], category x clue, shaped to match
    # the current round's bank.
    clue_cells_json: str = Field(default="[]")

    board_control: Player | None = Field(default=None)

    # The clue currently in play, if any.
    selected_category_index: int | None = Field(default=None)
    selected_clue_index: int | None = Field(default=None)
    clue_revealed_at: datetime | None = Field(default=None)

    # Regular-clue ring-in state. The answer countdown is tracked as
    # time *remaining* (counts down), not elapsed: buzz_timer_remaining_ms
    # is the remaining-ms value as of buzz_answer_started_at while
    # running, or the frozen remaining value directly while paused —
    # see buzz_remaining_ms() below. Host transport controls (Play/
    # Pause/Stop/Reset/Clear) all just manipulate these three fields.
    buzzed_player: Player | None = Field(default=None)
    buzz_answer_started_at: datetime | None = Field(default=None)
    buzz_timer_remaining_ms: int | None = Field(default=None)
    buzz_timer_running: bool = Field(default=True)

    # Crit Boost (Daily Double) wager, entered by the host before reveal.
    crit_boost_wager: int | None = Field(default=None)

    # Ring-in window: a buzz only counts between start_delay and
    # start_delay+window after the clue's revealed. Global defaults, with
    # optional per-player overrides (JSON dict player -> TimingOverride).
    ring_in_start_delay_ms: int = Field(default=300, ge=0)
    ring_in_window_ms: int = Field(default=5000, ge=100)
    ring_in_overrides_json: str = Field(default="{}")

    # Personal answer countdown, once a player's won the buzz-in. Same
    # global-default-plus-override shape.
    answer_time_ms: int = Field(default=8000, ge=100)
    answer_time_overrides_json: str = Field(default="{}")

    final_entries_json: str = Field(default_factory=_default_final_entries_json)

    status: str = Field(default="active")

    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class OverdriveGameCreate(SQLModel):
    round1_bank_id: str = "classic"
    round2_bank_id: str = "classic"
    final_bank_id: str = "classic"
    player1_name: str = "Player 1"
    player2_name: str = "Player 2"
    player3_name: str = "Player 3"


class ClueRead(SQLModel):
    category_index: int
    clue_index: int
    value: int
    is_crit_boost: bool
    played: bool
    locked_out: list[Player]
    text: str | None
    answer: str | None


class CategoryRead(SQLModel):
    index: int
    name: str
    revealed: bool
    clues: list[ClueRead]


class FinalEntryRead(SQLModel):
    eligible: bool
    submitted: bool
    revealed: bool
    wager: int | None
    answer: str | None
    correct: bool | None


class PlayerStatusRead(SQLModel):
    name: str
    score: int
    can_ring_in: bool
    ring_in_start_delay_ms: int
    ring_in_window_ms: int
    answer_time_ms: int


class OverdriveGameRead(SQLModel):
    id: str
    current_round: RoundName
    categories: list[CategoryRead]
    players: dict[str, PlayerStatusRead]
    board_control: Player | None
    selected_category_index: int | None
    selected_clue_index: int | None
    clue_phase: str | None
    buzzed_player: Player | None
    crit_boost_wager: int | None
    ring_in_elapsed_ms: int | None
    buzz_remaining_ms: int | None
    answer_timer_running: bool
    no_one_can_answer: bool
    ring_in_start_delay_ms: int
    ring_in_window_ms: int
    answer_time_ms: int
    final_category: str | None
    final_text: str | None
    final_entries: dict[str, FinalEntryRead]
    status: str
    created_at: datetime
    updated_at: datetime


def bank_for_round(game: OverdriveGame, round_name: RoundName) -> RoundBank:
    if round_name == RoundName.ROUND1:
        bank = get_round1_bank(game.round1_bank_id)
    elif round_name == RoundName.ROUND2:
        bank = get_round2_bank(game.round2_bank_id)
    else:
        raise ValueError("Final round has no RoundBank — use the final bank helpers")
    if bank is None:
        raise ValueError(f"Unknown bank for {round_name}")
    return bank


def current_bank(game: OverdriveGame) -> RoundBank:
    return bank_for_round(game, game.current_round)


def player_scores(game: OverdriveGame) -> dict[Player, PlayerScore]:
    raw: list[dict[str, object]] = json.loads(game.players_json)
    return {p: PlayerScore.model_validate(raw[i]) for i, p in enumerate(ALL_PLAYERS)}


def player_score(game: OverdriveGame, player: Player) -> PlayerScore:
    return player_scores(game)[player]


def set_player_score(game: OverdriveGame, player: Player, score: PlayerScore) -> None:
    scores = player_scores(game)
    scores[player] = score
    game.players_json = json.dumps([scores[p].model_dump() for p in ALL_PLAYERS])


def categories_revealed(game: OverdriveGame) -> list[bool]:
    result: list[bool] = json.loads(game.categories_revealed_json)
    return result


def set_categories_revealed(game: OverdriveGame, revealed: list[bool]) -> None:
    game.categories_revealed_json = json.dumps(revealed)


def clue_cells(game: OverdriveGame) -> list[list[ClueCell]]:
    raw: list[list[dict[str, object]]] = json.loads(game.clue_cells_json)
    return [[ClueCell.model_validate(c) for c in row] for row in raw]


def set_clue_cells(game: OverdriveGame, cells: list[list[ClueCell]]) -> None:
    game.clue_cells_json = json.dumps([[c.model_dump() for c in row] for row in cells])


def reset_board_for_round(game: OverdriveGame, round_name: RoundName) -> None:
    """Start a round's board fresh: all categories hidden, all clues
    unplayed, no locked-out players. Does not touch scores or
    board_control."""
    bank = bank_for_round(game, round_name)
    game.current_round = round_name
    set_categories_revealed(game, [False] * len(bank.categories))
    set_clue_cells(game, [[ClueCell() for _ in cat.clues] for cat in bank.categories])
    game.selected_category_index = None
    game.selected_clue_index = None
    game.clue_revealed_at = None
    game.buzzed_player = None
    game.buzz_answer_started_at = None
    game.buzz_timer_remaining_ms = None
    game.buzz_timer_running = True
    game.crit_boost_wager = None


def selected_clue_content(game: OverdriveGame) -> ClueContent | None:
    if game.selected_category_index is None or game.selected_clue_index is None:
        return None
    bank = current_bank(game)
    return bank.categories[game.selected_category_index].clues[game.selected_clue_index]


def selected_clue_cell(game: OverdriveGame) -> ClueCell | None:
    if game.selected_category_index is None or game.selected_clue_index is None:
        return None
    cells = clue_cells(game)
    return cells[game.selected_category_index][game.selected_clue_index]


def is_selected_crit_boost(game: OverdriveGame) -> bool:
    content = selected_clue_content(game)
    return content is not None and content.crit_boost != 0


def clue_phase(game: OverdriveGame) -> str | None:
    """None (nothing selected), "selected" (fly-in, not yet revealed),
    or "revealed" (clue text visible, ring-in or Crit Boost answer in
    progress)."""
    if game.selected_category_index is None:
        return None
    return "revealed" if game.clue_revealed_at is not None else "selected"


def ring_in_window_for(game: OverdriveGame, player: Player) -> tuple[int, int]:
    """(start_delay_ms, window_ms) for one player, honoring any override."""
    overrides: dict[str, dict[str, int | None]] = json.loads(
        game.ring_in_overrides_json
    )
    override = overrides.get(player.value)
    start = game.ring_in_start_delay_ms
    window = game.ring_in_window_ms
    if override:
        if override.get("start_delay_ms") is not None:
            start = override["start_delay_ms"]  # type: ignore[assignment]
        if override.get("window_ms") is not None:
            window = override["window_ms"]  # type: ignore[assignment]
    return start, window


def set_ring_in_override(
    game: OverdriveGame, player: Player, override: TimingOverride
) -> None:
    overrides: dict[str, dict[str, int | None]] = json.loads(
        game.ring_in_overrides_json
    )
    overrides[player.value] = override.model_dump()
    game.ring_in_overrides_json = json.dumps(overrides)


def clear_ring_in_overrides(game: OverdriveGame) -> None:
    game.ring_in_overrides_json = "{}"


def answer_time_for(game: OverdriveGame, player: Player) -> int:
    overrides: dict[str, dict[str, int | None]] = json.loads(
        game.answer_time_overrides_json
    )
    override = overrides.get(player.value)
    if override and override.get("window_ms") is not None:
        return override["window_ms"]  # type: ignore[return-value]
    return game.answer_time_ms


def set_answer_time_override(
    game: OverdriveGame, player: Player, window_ms: int | None
) -> None:
    overrides: dict[str, dict[str, int | None]] = json.loads(
        game.answer_time_overrides_json
    )
    overrides[player.value] = {"start_delay_ms": None, "window_ms": window_ms}
    game.answer_time_overrides_json = json.dumps(overrides)


def clear_answer_time_overrides(game: OverdriveGame) -> None:
    game.answer_time_overrides_json = "{}"


def can_ring_in(
    game: OverdriveGame, player: Player, now: datetime | None = None
) -> bool:
    """Whether `player`'s buzz would currently be accepted — within
    their ring-in window, not already locked out of this clue, and no
    one's already won the buzz."""
    if game.clue_revealed_at is None or game.buzzed_player is not None:
        return False
    if is_selected_crit_boost(game):
        return False
    cell = selected_clue_cell(game)
    if cell is None or player in cell.locked_out:
        return False
    now = now if now is not None else _utcnow()
    elapsed_ms = (now - game.clue_revealed_at).total_seconds() * 1000
    start, window = ring_in_window_for(game, player)
    return start <= elapsed_ms <= start + window


def ring_in_window_expired(game: OverdriveGame, now: datetime | None = None) -> bool:
    """True once every still-eligible (not locked out) player's ring-in
    window has closed with no one having buzzed — the clue is dead."""
    if game.clue_revealed_at is None or game.buzzed_player is not None:
        return False
    cell = selected_clue_cell(game)
    if cell is None:
        return False
    now = now if now is not None else _utcnow()
    elapsed_ms = (now - game.clue_revealed_at).total_seconds() * 1000
    remaining = [p for p in ALL_PLAYERS if p not in cell.locked_out]
    if not remaining:
        return True

    def window_closed(p: Player) -> bool:
        start, window = ring_in_window_for(game, p)
        return elapsed_ms > start + window

    return all(window_closed(p) for p in remaining)


def ring_in_elapsed_ms(game: OverdriveGame, now: datetime | None = None) -> int | None:
    if game.clue_revealed_at is None:
        return None
    now = now if now is not None else _utcnow()
    return int((now - game.clue_revealed_at).total_seconds() * 1000)


def buzz_remaining_ms(game: OverdriveGame, now: datetime | None = None) -> int | None:
    """Time left on the answering player's countdown. None if no one's
    currently answering. Counts down from answer_time_for(player) to 0
    while running; frozen at buzz_timer_remaining_ms while paused."""
    if game.buzzed_player is None or game.buzz_timer_remaining_ms is None:
        return None
    if not game.buzz_timer_running or game.buzz_answer_started_at is None:
        return max(0, game.buzz_timer_remaining_ms)
    now = now if now is not None else _utcnow()
    elapsed_ms = int((now - game.buzz_answer_started_at).total_seconds() * 1000)
    return max(0, game.buzz_timer_remaining_ms - elapsed_ms)


def final_entries(game: OverdriveGame) -> dict[Player, FinalEntry]:
    raw: dict[str, dict[str, object]] = json.loads(game.final_entries_json)
    return {p: FinalEntry.model_validate(raw[p.value]) for p in ALL_PLAYERS}


def final_entry(game: OverdriveGame, player: Player) -> FinalEntry:
    return final_entries(game)[player]


def set_final_entry(game: OverdriveGame, player: Player, entry: FinalEntry) -> None:
    entries = final_entries(game)
    entries[player] = entry
    game.final_entries_json = json.dumps(
        {p.value: entries[p].model_dump() for p in ALL_PLAYERS}
    )


def final_bank_content(game: OverdriveGame) -> tuple[str, str, str]:
    """(category, text, answer) for the chosen final bank."""
    bank = get_final_bank(game.final_bank_id)
    if bank is None:
        raise ValueError(f"Unknown final bank: {game.final_bank_id}")
    return bank.category, bank.text, bank.answer
