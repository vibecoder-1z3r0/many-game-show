from datetime import UTC, datetime, timedelta

from manygameshow.models.big_tokens import (
    ALL_PLAYERS,
    BigTokensGame,
    OutReason,
    Player,
    PlayerState,
    advance_square,
    awaiting,
    board_state,
    chase_position,
    next_active_player,
    player_state,
    round_over,
    set_player_state,
    square_item,
)


def test_defaults() -> None:
    game = BigTokensGame()
    assert game.board_id == "classic"
    assert game.current_player is None
    assert game.round_number == 1
    assert game.chase_started_at is None
    assert game.pending_square_index is None
    assert game.pending_choice is None
    assert game.status == "active"
    assert board_state(game) == [0] * 18
    for i, player in enumerate(ALL_PLAYERS):
        state = player_state(game, player)
        assert state.name == f"Player {i + 1}"
        assert state.token_total == 0
        assert state.spins_remaining == 0
        assert state.mandatory_spins == 0
        assert state.hallucination_count == 0
        assert state.is_out is False
        assert state.out_reason is None


def test_square_item_returns_first_item_by_default() -> None:
    game = BigTokensGame()
    item = square_item(game, 0)
    assert item.type == "tokens"
    assert item.amount == 300


def test_advance_square_cascades_to_next_item() -> None:
    game = BigTokensGame()
    # Square 1 on the classic board: +500 Tokens -> +750 Tokens
    before = square_item(game, 1)
    assert before.amount == 500
    advance_square(game, 1)
    after = square_item(game, 1)
    assert after.amount == 750


def test_advance_square_clamps_at_last_item() -> None:
    game = BigTokensGame()
    advance_square(game, 1)
    advance_square(game, 1)
    advance_square(game, 1)
    item = square_item(game, 1)
    assert item.amount == 750


def test_advance_square_on_fixed_square_is_a_no_op() -> None:
    game = BigTokensGame()
    # Square 0 on the classic board is fixed (single item).
    advance_square(game, 0)
    item = square_item(game, 0)
    assert item.amount == 300


def test_player_state_set_and_read_roundtrip() -> None:
    game = BigTokensGame()
    set_player_state(
        game,
        Player.PLAYER2,
        PlayerState(name="Grace", token_total=500, spins_remaining=2),
    )
    state = player_state(game, Player.PLAYER2)
    assert state.name == "Grace"
    assert state.token_total == 500
    assert state.spins_remaining == 2
    # Other players untouched.
    assert player_state(game, Player.PLAYER1).name == "Player 1"


def test_chase_position_none_when_not_started() -> None:
    game = BigTokensGame()
    assert chase_position(game) is None


def test_chase_position_computes_from_elapsed() -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    game = BigTokensGame(chase_started_at=now - timedelta(milliseconds=475))
    # 475ms / 150ms per step = 3 steps, position 3.
    assert chase_position(game, now=now) == 3


def test_chase_position_wraps_around_18_squares() -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    # 20 steps * 150ms = 3000ms elapsed -> 20 % 18 == 2.
    game = BigTokensGame(chase_started_at=now - timedelta(milliseconds=3000))
    assert chase_position(game, now=now) == 2


def test_awaiting_none_when_no_pending_square() -> None:
    game = BigTokensGame()
    assert awaiting(game) is None


def test_awaiting_none_for_plain_tokens_square() -> None:
    game = BigTokensGame(pending_square_index=0)
    assert awaiting(game) is None


def test_awaiting_target_for_steal_square() -> None:
    # Square 8 on the classic board is "steal".
    game = BigTokensGame(pending_square_index=8)
    assert awaiting(game) == "target"


def test_awaiting_choice_for_choice_swap_or_free_spin_square() -> None:
    # Square 10 on the classic board.
    game = BigTokensGame(pending_square_index=10)
    assert awaiting(game) == "choice"


def test_awaiting_target_after_choosing_swap_scores() -> None:
    game = BigTokensGame(pending_square_index=10, pending_choice="swap_scores")
    assert awaiting(game) == "target"


def test_awaiting_none_after_choosing_free_spin() -> None:
    game = BigTokensGame(pending_square_index=10, pending_choice="free_spin")
    assert awaiting(game) is None


def test_awaiting_choice_for_choice_tokens_or_cure_square() -> None:
    # Square 13 on the classic board.
    game = BigTokensGame(pending_square_index=13)
    assert awaiting(game) == "choice"


def test_awaiting_none_after_choosing_tokens_or_cure() -> None:
    game = BigTokensGame(pending_square_index=13, pending_choice="tokens")
    assert awaiting(game) is None
    game2 = BigTokensGame(pending_square_index=13, pending_choice="cure")
    assert awaiting(game2) is None


def test_next_active_player_cycles_in_order() -> None:
    game = BigTokensGame(current_player=Player.PLAYER1)
    assert next_active_player(game) == Player.PLAYER2


def test_next_active_player_wraps_around() -> None:
    game = BigTokensGame(current_player=Player.PLAYER3)
    assert next_active_player(game) == Player.PLAYER1


def test_next_active_player_skips_out_players() -> None:
    game = BigTokensGame(current_player=Player.PLAYER1)
    set_player_state(
        game,
        Player.PLAYER2,
        PlayerState(name="Grace", is_out=True, out_reason=OutReason.NO_SPINS),
    )
    assert next_active_player(game) == Player.PLAYER3


def test_next_active_player_cycles_back_to_current_when_all_others_out() -> None:
    """Current player isn't out themselves, so if everyone else is, the
    only "next" active player is the current one again."""
    game = BigTokensGame(current_player=Player.PLAYER1)
    set_player_state(game, Player.PLAYER2, PlayerState(is_out=True))
    set_player_state(game, Player.PLAYER3, PlayerState(is_out=True))
    assert next_active_player(game) == Player.PLAYER1


def test_next_active_player_none_when_every_player_out() -> None:
    game = BigTokensGame(current_player=Player.PLAYER1)
    for player in ALL_PLAYERS:
        set_player_state(game, player, PlayerState(is_out=True))
    assert next_active_player(game) is None


def test_next_active_player_defaults_to_player1_when_no_current_player() -> None:
    game = BigTokensGame(current_player=None)
    assert next_active_player(game) == Player.PLAYER2


def test_round_over_false_when_any_player_active() -> None:
    game = BigTokensGame()
    assert round_over(game) is False


def test_round_over_true_when_all_players_out() -> None:
    game = BigTokensGame()
    for player in ALL_PLAYERS:
        set_player_state(game, player, PlayerState(is_out=True))
    assert round_over(game) is True
