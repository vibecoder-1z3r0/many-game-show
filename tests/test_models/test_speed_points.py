import json
from datetime import UTC, datetime, timedelta

from manygameshow.models.speed_points import (
    QUESTIONS_PER_ROUND,
    AnswerSlot,
    Player,
    SpeedPointsGame,
    combined_total,
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
    assert game.win_threshold == 200
    assert game.scores_revealed is False
    assert game.status == "active"
    assert player_slots(game, Player.PLAYER1) == [AnswerSlot()] * QUESTIONS_PER_ROUND
    assert player_slots(game, Player.PLAYER2) == [AnswerSlot()] * QUESTIONS_PER_ROUND


def test_answer_slot_defaults() -> None:
    slot = AnswerSlot()
    assert slot.text == ""
    assert slot.points == 0
    assert slot.text_revealed is False
    assert slot.points_revealed is False
    assert slot.duplicate is False


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


def test_player_slots_parses_into_answer_slot_objects() -> None:
    slots = [
        {
            "text": "Actually...",
            "points": 34,
            "text_revealed": True,
            "points_revealed": True,
            "duplicate": False,
        }
    ] + [AnswerSlot().model_dump()] * 4
    game = SpeedPointsGame(player1_slots_json=json.dumps(slots))
    parsed = player_slots(game, Player.PLAYER1)
    assert parsed[0] == AnswerSlot(
        text="Actually...", points=34, text_revealed=True, points_revealed=True
    )
    assert parsed[1:] == [AnswerSlot()] * 4


def test_player_total_sums_only_points_revealed_slots() -> None:
    slots = [
        {"text": "Actually...", "points": 34, "points_revealed": True},
        {"text": "Nit:", "points": 26, "points_revealed": False},
    ] + [AnswerSlot().model_dump()] * 3
    game = SpeedPointsGame(player1_slots_json=json.dumps(slots))
    assert player_total(game, Player.PLAYER1) == 34
    assert player_total(game, Player.PLAYER2) == 0


def test_combined_total_sums_both_players_points_revealed_only() -> None:
    p1 = [
        {"text": "a", "points": 34, "points_revealed": True},
        {"text": "b", "points": 26, "points_revealed": True},
    ] + [AnswerSlot().model_dump()] * 3
    p2 = [
        {"text": "c", "points": 38, "points_revealed": True},
        {"text": "d", "points": 24, "points_revealed": False},
    ] + [AnswerSlot().model_dump()] * 3
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
