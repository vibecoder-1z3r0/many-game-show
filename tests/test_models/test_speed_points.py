import json
from datetime import UTC, datetime, timedelta

from manygameshow.models.speed_points import (
    AnswerSlot,
    Player,
    SpeedPointsGame,
    combined_total,
    current_question,
    current_questions,
    player_slots,
    player_total,
    remaining_seconds,
)


def test_defaults() -> None:
    game = SpeedPointsGame()
    assert game.player1_name == "Player 1"
    assert game.player2_name == "Player 2"
    assert game.current_player is None
    assert game.current_question_index == 0
    assert game.win_threshold == 200
    assert game.scores_revealed is False
    assert game.pending_duplicate_flag is False
    assert game.status == "active"
    assert player_slots(game, Player.PLAYER1) == [None] * 5
    assert player_slots(game, Player.PLAYER2) == [None] * 5


def test_answer_slot_duplicate_defaults_false() -> None:
    assert AnswerSlot(text="x", points=5).duplicate is False


def test_id_is_unique_uuid() -> None:
    a, b = SpeedPointsGame(), SpeedPointsGame()
    assert a.id != b.id
    assert len(a.id) == 36


def test_player_enum_values() -> None:
    assert Player.PLAYER1 == "player1"
    assert Player.PLAYER2 == "player2"


def test_current_questions_resolves_from_sample_bank() -> None:
    game = SpeedPointsGame(
        question_ids_json=json.dumps(
            ["code-review-word", "standup-word", "laptop-sticker"]
        )
    )
    questions = current_questions(game)
    assert [q.id for q in questions] == [
        "code-review-word",
        "standup-word",
        "laptop-sticker",
    ]


def test_current_question_none_when_index_out_of_range() -> None:
    game = SpeedPointsGame(
        question_ids_json=json.dumps(["code-review-word"]),
        current_question_index=5,
    )
    assert current_question(game) is None


def test_current_question_resolves_at_index() -> None:
    game = SpeedPointsGame(
        question_ids_json=json.dumps(["code-review-word", "standup-word"]),
        current_question_index=1,
    )
    q = current_question(game)
    assert q is not None
    assert q.id == "standup-word"


def test_player_total_sums_only_revealed_slots() -> None:
    slots = [
        {"text": "Actually...", "points": 34, "revealed": True},
        {"text": "Nit:", "points": 26, "revealed": False},  # text chosen, not revealed
        None,
        None,
        None,
    ]
    game = SpeedPointsGame(player1_slots_json=json.dumps(slots))
    assert player_total(game, Player.PLAYER1) == 34
    assert player_total(game, Player.PLAYER2) == 0


def test_player_slots_parses_into_answer_slot_objects() -> None:
    slots = [
        {"text": "Actually...", "points": 34, "revealed": True},
        None,
        None,
        None,
        None,
    ]
    game = SpeedPointsGame(player1_slots_json=json.dumps(slots))
    parsed = player_slots(game, Player.PLAYER1)
    assert parsed[0] == AnswerSlot(text="Actually...", points=34, revealed=True)
    assert parsed[1:] == [None] * 4


def test_combined_total_sums_both_players_revealed_only() -> None:
    p1 = [
        {"text": "a", "points": 34, "revealed": True},
        {"text": "b", "points": 26, "revealed": True},
        None,
        None,
        None,
    ]
    p2 = [
        {"text": "c", "points": 38, "revealed": True},
        {"text": "d", "points": 24, "revealed": False},
        None,
        None,
        None,
    ]
    game = SpeedPointsGame(
        player1_slots_json=json.dumps(p1), player2_slots_json=json.dumps(p2)
    )
    assert combined_total(game) == (34 + 26) + 38


def test_remaining_seconds_none_when_no_timer_running() -> None:
    game = SpeedPointsGame()
    assert remaining_seconds(game) is None


def test_remaining_seconds_counts_down_from_duration() -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    game = SpeedPointsGame(
        current_player=Player.PLAYER1,
        timer_started_at=now - timedelta(seconds=5),
        timer_duration_seconds=20,
    )
    remaining = remaining_seconds(game, now=now)
    assert remaining == 15


def test_remaining_seconds_clamped_to_zero_when_expired() -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    game = SpeedPointsGame(
        current_player=Player.PLAYER1,
        timer_started_at=now - timedelta(seconds=99),
        timer_duration_seconds=20,
    )
    assert remaining_seconds(game, now=now) == 0
