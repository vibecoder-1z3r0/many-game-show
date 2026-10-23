from datetime import UTC, datetime, timedelta

from manygameshow.models.answers import (
    ALL_PLAYERS,
    AnswersGame,
    FinalEntry,
    Player,
    RoundName,
    TimingOverride,
    answer_time_for,
    buzz_elapsed_ms,
    can_ring_in,
    categories_revealed,
    clear_answer_time_overrides,
    clear_ring_in_overrides,
    clue_cells,
    clue_phase,
    current_bank,
    final_bank_content,
    final_entry,
    is_selected_context_clue,
    player_score,
    reset_board_for_round,
    ring_in_window_expired,
    ring_in_window_for,
    selected_clue_cell,
    selected_clue_content,
    set_answer_time_override,
    set_clue_cells,
    set_final_entry,
    set_player_score,
    set_ring_in_override,
)


def test_defaults() -> None:
    game = AnswersGame()
    assert game.current_round == RoundName.ROUND1
    assert game.board_control is None
    assert game.selected_category_index is None
    assert clue_phase(game) is None
    for i, player in enumerate(ALL_PLAYERS):
        score = player_score(game, player)
        assert score.name == f"Player {i + 1}"
        assert score.score == 0


def test_current_bank_resolves_round1_by_default() -> None:
    game = AnswersGame()
    bank = current_bank(game)
    assert bank.id == "classic"
    assert len(bank.categories) == 6


def test_reset_board_for_round_sets_up_fresh_grid() -> None:
    game = AnswersGame()
    reset_board_for_round(game, RoundName.ROUND1)
    assert categories_revealed(game) == [False] * 6
    cells = clue_cells(game)
    assert len(cells) == 6
    assert all(len(row) == 5 for row in cells)
    assert all(not c.played and c.locked_out == [] for row in cells for c in row)


def test_reset_board_clears_in_flight_clue_state() -> None:
    game = AnswersGame()
    reset_board_for_round(game, RoundName.ROUND1)
    game.selected_category_index = 0
    game.selected_clue_index = 0
    game.buzzed_player = Player.PLAYER1
    reset_board_for_round(game, RoundName.ROUND2)
    assert game.selected_category_index is None
    assert game.buzzed_player is None
    assert current_bank(game).id == "classic"
    assert len(clue_cells(game)) == 6


def test_selected_clue_content_and_cell() -> None:
    game = AnswersGame()
    reset_board_for_round(game, RoundName.ROUND1)
    assert selected_clue_content(game) is None
    assert selected_clue_cell(game) is None

    game.selected_category_index = 0
    game.selected_clue_index = 1
    content = selected_clue_content(game)
    assert content is not None
    assert content.value == 400
    cell = selected_clue_cell(game)
    assert cell is not None
    assert cell.played is False


def test_is_selected_context_clue() -> None:
    game = AnswersGame()
    reset_board_for_round(game, RoundName.ROUND1)
    # Round 1's only context_clue is category 0, clue 4 (the +1000 one).
    game.selected_category_index = 0
    game.selected_clue_index = 0
    assert is_selected_context_clue(game) is False
    game.selected_clue_index = 4
    assert is_selected_context_clue(game) is True


def test_clue_phase_transitions() -> None:
    game = AnswersGame()
    reset_board_for_round(game, RoundName.ROUND1)
    assert clue_phase(game) is None
    game.selected_category_index = 0
    game.selected_clue_index = 0
    assert clue_phase(game) == "selected"
    game.clue_revealed_at = datetime.now(UTC).replace(tzinfo=None)
    assert clue_phase(game) == "revealed"


def test_ring_in_window_for_uses_global_defaults() -> None:
    game = AnswersGame(ring_in_start_delay_ms=300, ring_in_window_ms=5000)
    assert ring_in_window_for(game, Player.PLAYER1) == (300, 5000)


def test_ring_in_override_applies_only_to_that_player() -> None:
    game = AnswersGame(ring_in_start_delay_ms=300, ring_in_window_ms=5000)
    set_ring_in_override(
        game, Player.PLAYER2, TimingOverride(start_delay_ms=1000, window_ms=3000)
    )
    assert ring_in_window_for(game, Player.PLAYER1) == (300, 5000)
    assert ring_in_window_for(game, Player.PLAYER2) == (1000, 3000)


def test_ring_in_override_partial_fields_fall_back_to_global() -> None:
    game = AnswersGame(ring_in_start_delay_ms=300, ring_in_window_ms=5000)
    set_ring_in_override(game, Player.PLAYER1, TimingOverride(window_ms=9000))
    assert ring_in_window_for(game, Player.PLAYER1) == (300, 9000)


def test_clear_ring_in_overrides_reverts_everyone_to_global() -> None:
    game = AnswersGame(ring_in_start_delay_ms=300, ring_in_window_ms=5000)
    set_ring_in_override(game, Player.PLAYER2, TimingOverride(window_ms=1))
    clear_ring_in_overrides(game)
    assert ring_in_window_for(game, Player.PLAYER2) == (300, 5000)


def test_answer_time_override_and_clear() -> None:
    game = AnswersGame(answer_time_ms=8000)
    assert answer_time_for(game, Player.PLAYER1) == 8000
    set_answer_time_override(game, Player.PLAYER1, 15000)
    assert answer_time_for(game, Player.PLAYER1) == 15000
    assert answer_time_for(game, Player.PLAYER2) == 8000
    clear_answer_time_overrides(game)
    assert answer_time_for(game, Player.PLAYER1) == 8000


def test_can_ring_in_false_before_reveal() -> None:
    game = AnswersGame()
    reset_board_for_round(game, RoundName.ROUND1)
    game.selected_category_index = 0
    game.selected_clue_index = 0
    assert can_ring_in(game, Player.PLAYER1) is False


def test_can_ring_in_false_before_start_delay_elapses() -> None:
    game = AnswersGame(ring_in_start_delay_ms=300, ring_in_window_ms=5000)
    reset_board_for_round(game, RoundName.ROUND1)
    game.selected_category_index = 0
    game.selected_clue_index = 0
    now = datetime.now(UTC).replace(tzinfo=None)
    game.clue_revealed_at = now - timedelta(milliseconds=100)
    assert can_ring_in(game, Player.PLAYER1, now=now) is False


def test_can_ring_in_true_within_window() -> None:
    game = AnswersGame(ring_in_start_delay_ms=300, ring_in_window_ms=5000)
    reset_board_for_round(game, RoundName.ROUND1)
    game.selected_category_index = 0
    game.selected_clue_index = 0
    now = datetime.now(UTC).replace(tzinfo=None)
    game.clue_revealed_at = now - timedelta(milliseconds=1000)
    assert can_ring_in(game, Player.PLAYER1, now=now) is True


def test_can_ring_in_false_after_window_closes() -> None:
    game = AnswersGame(ring_in_start_delay_ms=300, ring_in_window_ms=5000)
    reset_board_for_round(game, RoundName.ROUND1)
    game.selected_category_index = 0
    game.selected_clue_index = 0
    now = datetime.now(UTC).replace(tzinfo=None)
    game.clue_revealed_at = now - timedelta(milliseconds=6000)
    assert can_ring_in(game, Player.PLAYER1, now=now) is False


def test_can_ring_in_false_once_someone_already_buzzed() -> None:
    game = AnswersGame(ring_in_start_delay_ms=300, ring_in_window_ms=5000)
    reset_board_for_round(game, RoundName.ROUND1)
    game.selected_category_index = 0
    game.selected_clue_index = 0
    now = datetime.now(UTC).replace(tzinfo=None)
    game.clue_revealed_at = now - timedelta(milliseconds=1000)
    game.buzzed_player = Player.PLAYER2
    assert can_ring_in(game, Player.PLAYER1, now=now) is False


def test_can_ring_in_false_for_locked_out_player() -> None:
    game = AnswersGame(ring_in_start_delay_ms=300, ring_in_window_ms=5000)
    reset_board_for_round(game, RoundName.ROUND1)
    game.selected_category_index = 0
    game.selected_clue_index = 0
    cells = clue_cells(game)
    cells[0][0].locked_out = [Player.PLAYER1]
    set_clue_cells(game, cells)
    now = datetime.now(UTC).replace(tzinfo=None)
    game.clue_revealed_at = now - timedelta(milliseconds=1000)
    assert can_ring_in(game, Player.PLAYER1, now=now) is False
    assert can_ring_in(game, Player.PLAYER2, now=now) is True


def test_can_ring_in_false_for_context_clue() -> None:
    game = AnswersGame(ring_in_start_delay_ms=300, ring_in_window_ms=5000)
    reset_board_for_round(game, RoundName.ROUND1)
    game.selected_category_index = 0
    game.selected_clue_index = 4  # the context clue
    now = datetime.now(UTC).replace(tzinfo=None)
    game.clue_revealed_at = now - timedelta(milliseconds=1000)
    assert can_ring_in(game, Player.PLAYER1, now=now) is False


def test_ring_in_window_expired_false_before_anyone_times_out() -> None:
    game = AnswersGame(ring_in_start_delay_ms=300, ring_in_window_ms=5000)
    reset_board_for_round(game, RoundName.ROUND1)
    game.selected_category_index = 0
    game.selected_clue_index = 0
    now = datetime.now(UTC).replace(tzinfo=None)
    game.clue_revealed_at = now - timedelta(milliseconds=1000)
    assert ring_in_window_expired(game, now=now) is False


def test_ring_in_window_expired_true_once_all_windows_pass() -> None:
    game = AnswersGame(ring_in_start_delay_ms=300, ring_in_window_ms=5000)
    reset_board_for_round(game, RoundName.ROUND1)
    game.selected_category_index = 0
    game.selected_clue_index = 0
    now = datetime.now(UTC).replace(tzinfo=None)
    game.clue_revealed_at = now - timedelta(milliseconds=6000)
    assert ring_in_window_expired(game, now=now) is True


def test_ring_in_window_expired_true_when_everyone_locked_out() -> None:
    game = AnswersGame(ring_in_start_delay_ms=300, ring_in_window_ms=5000)
    reset_board_for_round(game, RoundName.ROUND1)
    game.selected_category_index = 0
    game.selected_clue_index = 0
    cells = clue_cells(game)
    cells[0][0].locked_out = list(ALL_PLAYERS)
    set_clue_cells(game, cells)
    now = datetime.now(UTC).replace(tzinfo=None)
    game.clue_revealed_at = now - timedelta(milliseconds=500)
    assert ring_in_window_expired(game, now=now) is True


def test_player_score_set_and_read_roundtrip() -> None:
    game = AnswersGame()
    set_player_score(game, Player.PLAYER2, player_score(game, Player.PLAYER2))
    score = player_score(game, Player.PLAYER2)
    score.name = "Grace"
    score.score = 600
    set_player_score(game, Player.PLAYER2, score)
    assert player_score(game, Player.PLAYER2).name == "Grace"
    assert player_score(game, Player.PLAYER2).score == 600
    assert player_score(game, Player.PLAYER1).name == "Player 1"


def test_final_entry_default_and_roundtrip() -> None:
    game = AnswersGame()
    entry = final_entry(game, Player.PLAYER1)
    assert entry.submitted is False
    assert entry.wager is None

    entry.wager = 500
    entry.answer = "What is Python"
    entry.submitted = True
    set_final_entry(game, Player.PLAYER1, entry)

    stored = final_entry(game, Player.PLAYER1)
    assert stored.wager == 500
    assert stored.answer == "What is Python"
    assert stored.submitted is True
    # Other players untouched.
    assert final_entry(game, Player.PLAYER2) == FinalEntry()


def test_final_bank_content() -> None:
    game = AnswersGame()
    category, text, answer = final_bank_content(game)
    assert category == "Famous Firsts in Computing"
    assert "Ada Lovelace" in answer


def test_buzz_elapsed_ms_none_when_no_one_buzzed() -> None:
    game = AnswersGame()
    assert buzz_elapsed_ms(game) is None


def test_buzz_elapsed_ms_frozen_stays_fixed_regardless_of_now() -> None:
    game = AnswersGame(
        buzz_answer_started_at=datetime(2024, 1, 1, 0, 0, 0),
        buzz_timer_frozen_ms=1234,
    )
    now = datetime(2024, 1, 1, 0, 5, 0)
    assert buzz_elapsed_ms(game, now=now) == 1234
