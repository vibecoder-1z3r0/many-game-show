from manygameshow.models.squad_squabble import (
    SquadSquabbleGame,
    Team,
    current_question,
    revealed_indices,
    round_points,
)


def test_defaults() -> None:
    game = SquadSquabbleGame()
    assert game.team1_name == "Team 1"
    assert game.team2_name == "Team 2"
    assert game.team1_score == 0
    assert game.team2_score == 0
    assert game.current_round == 1
    assert game.question_visible is False
    assert game.multiplier == 1
    assert game.controlling_team is None
    assert game.strikes == 0
    assert game.status == "active"
    assert revealed_indices(game) == []


def test_id_is_unique_uuid() -> None:
    a, b = SquadSquabbleGame(), SquadSquabbleGame()
    assert a.id != b.id
    assert len(a.id) == 36  # UUID4 string form


def test_team_enum_values() -> None:
    assert Team.TEAM1 == "team1"
    assert Team.TEAM2 == "team2"


def test_current_question_none_when_unset() -> None:
    game = SquadSquabbleGame()
    assert current_question(game) is None


def test_current_question_resolves_from_sample_bank() -> None:
    game = SquadSquabbleGame(current_question_id="desk-drawer")
    question = current_question(game)
    assert question is not None
    assert question.id == "desk-drawer"
    assert len(question.answers) == 5


def test_round_points_zero_with_no_question() -> None:
    game = SquadSquabbleGame()
    assert round_points(game) == 0


def test_round_points_sums_revealed_with_multiplier() -> None:
    game = SquadSquabbleGame(
        current_question_id="desk-drawer",
        multiplier=2,
        revealed_answer_indices_json="[0, 1]",
    )
    # "Tangled cables" (32) + "Snacks" (27) = 59, times 2x multiplier
    assert round_points(game) == 118
