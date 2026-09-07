from fastapi.testclient import TestClient


def _create_game(client: TestClient) -> str:
    resp = client.post(
        "/api/speed-points/games/",
        json={"player1_name": "Ada", "player2_name": "Grace"},
    )
    assert resp.status_code == 200
    return resp.json()["id"]  # type: ignore[no-any-return]


def _start_round(client: TestClient, game_id: str, player: str = "player1") -> None:
    resp = client.patch(
        f"/api/speed-points/games/{game_id}/start-round",
        json={"player": player},
    )
    assert resp.status_code == 200


def _award(client: TestClient, game_id: str, text: str, points: int) -> dict:
    resp = client.patch(
        f"/api/speed-points/games/{game_id}/award",
        json={"text": text, "points": points},
    )
    assert resp.status_code == 200
    return resp.json()  # type: ignore[no-any-return]


def _reveal_points(client: TestClient, game_id: str) -> dict:
    resp = client.patch(f"/api/speed-points/games/{game_id}/reveal-points")
    assert resp.status_code == 200
    return resp.json()  # type: ignore[no-any-return]


def _empty_slots() -> list[dict]:
    return [{"text": None, "points": None}] * 5


def test_create_sets_up_five_fixed_questions_get_list_delete(
    client: TestClient,
) -> None:
    game_id = _create_game(client)

    got = client.get(f"/api/speed-points/games/{game_id}")
    assert got.status_code == 200
    body = got.json()
    assert body["player1_name"] == "Ada"
    assert body["player2_name"] == "Grace"
    assert body["current_player"] is None
    assert body["current_question_index"] == 0
    assert body["current_question"] is None  # no round started yet
    assert body["player1_slots"] == _empty_slots()
    assert body["player2_slots"] == _empty_slots()
    assert body["player1_total"] == 0
    assert body["player2_total"] == 0
    assert body["combined_total"] == 0
    assert body["win_threshold"] == 200
    assert body["won"] is False
    assert body["scores_revealed"] is False
    assert body["remaining_seconds"] is None

    listed = client.get("/api/speed-points/games/")
    assert listed.status_code == 200
    assert any(g["id"] == game_id for g in listed.json())

    deleted = client.delete(f"/api/speed-points/games/{game_id}")
    assert deleted.status_code == 204
    assert client.get(f"/api/speed-points/games/{game_id}").status_code == 404


def test_start_round_sets_current_player_and_timer(client: TestClient) -> None:
    game_id = _create_game(client)

    resp = client.patch(
        f"/api/speed-points/games/{game_id}/start-round",
        json={"player": "player1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["current_player"] == "player1"
    assert body["current_question_index"] == 0
    assert body["current_question"] is not None
    assert body["timer_duration_seconds"] == 20
    assert body["remaining_seconds"] == 20


def test_start_round_player2_defaults_to_25_seconds(client: TestClient) -> None:
    game_id = _create_game(client)
    resp = client.patch(
        f"/api/speed-points/games/{game_id}/start-round",
        json={"player": "player2"},
    )
    assert resp.json()["timer_duration_seconds"] == 25


def test_start_round_accepts_duration_override(client: TestClient) -> None:
    game_id = _create_game(client)
    resp = client.patch(
        f"/api/speed-points/games/{game_id}/start-round",
        json={"player": "player1", "duration_seconds": 45},
    )
    assert resp.json()["timer_duration_seconds"] == 45


def test_award_locks_in_answer_text_but_hides_points(client: TestClient) -> None:
    """The two-step reveal: selecting a match shows what was said, not
    yet what it's worth."""
    game_id = _create_game(client)
    _start_round(client, game_id)

    body = _award(client, game_id, "Actually...", 34)
    assert body["player1_slots"][0] == {"text": "Actually...", "points": None}
    assert body["player1_total"] == 0  # not counted until revealed
    assert body["current_question_index"] == 0  # doesn't advance yet
    assert body["current_question"]["id"] == "code-review-word"  # still same Q


def test_reveal_points_shows_points_and_advances_question(client: TestClient) -> None:
    game_id = _create_game(client)
    _start_round(client, game_id)
    _award(client, game_id, "Actually...", 34)

    body = _reveal_points(client, game_id)
    assert body["player1_slots"][0] == {"text": "Actually...", "points": 34}
    assert body["player1_total"] == 34
    assert body["current_question_index"] == 1
    assert body["current_question"]["id"] == "standup-word"


def test_award_can_be_corrected_before_reveal(client: TestClient) -> None:
    """Host can change their match before the points step locks it in."""
    game_id = _create_game(client)
    _start_round(client, game_id)
    _award(client, game_id, "Actually...", 34)
    body = _award(client, game_id, "Nit:", 26)
    assert body["player1_slots"][0] == {"text": "Nit:", "points": None}


def test_award_with_zero_records_no_match(client: TestClient) -> None:
    game_id = _create_game(client)
    _start_round(client, game_id)
    _award(client, game_id, "No match", 0)
    body = _reveal_points(client, game_id)
    assert body["player1_slots"][0] == {"text": "No match", "points": 0}


def test_award_without_active_round_is_rejected(client: TestClient) -> None:
    game_id = _create_game(client)
    resp = client.patch(
        f"/api/speed-points/games/{game_id}/award",
        json={"text": "x", "points": 10},
    )
    assert resp.status_code == 400


def test_reveal_points_without_selected_answer_is_rejected(client: TestClient) -> None:
    game_id = _create_game(client)
    _start_round(client, game_id)
    resp = client.patch(f"/api/speed-points/games/{game_id}/reveal-points")
    assert resp.status_code == 400


def test_reveal_points_without_active_round_is_rejected(client: TestClient) -> None:
    game_id = _create_game(client)
    resp = client.patch(f"/api/speed-points/games/{game_id}/reveal-points")
    assert resp.status_code == 400


def test_award_past_fifth_question_is_rejected(client: TestClient) -> None:
    game_id = _create_game(client)
    _start_round(client, game_id)
    for _ in range(5):
        _award(client, game_id, "x", 5)
        body = _reveal_points(client, game_id)
    assert body["current_question_index"] == 5
    assert body["current_question"] is None

    sixth = client.patch(
        f"/api/speed-points/games/{game_id}/award",
        json={"text": "x", "points": 5},
    )
    assert sixth.status_code == 400


def test_full_relay_reveal_result_and_win_threshold(client: TestClient) -> None:
    game_id = _create_game(client)

    _start_round(client, game_id, "player1")
    for pts in [34, 26, 20, 12, 8]:  # 100
        _award(client, game_id, "x", pts)
        _reveal_points(client, game_id)

    _start_round(client, game_id, "player2")
    for pts in [38, 24, 18, 12, 8]:  # 100
        _award(client, game_id, "x", pts)
        _reveal_points(client, game_id)

    pre_reveal = client.get(f"/api/speed-points/games/{game_id}").json()
    assert pre_reveal["combined_total"] == 200
    assert pre_reveal["scores_revealed"] is False

    resp = client.patch(f"/api/speed-points/games/{game_id}/reveal-result")
    assert resp.status_code == 200
    body = resp.json()
    assert body["scores_revealed"] is True
    assert body["combined_total"] == 200
    assert body["won"] is True


def test_answer_options_returns_current_question_answers(client: TestClient) -> None:
    game_id = _create_game(client)
    _start_round(client, game_id)
    resp = client.get(f"/api/speed-points/games/{game_id}/answer-options")
    assert resp.status_code == 200
    options = resp.json()
    assert len(options) == 5
    assert options[0]["text"] == "Actually..."
    assert options[0]["points"] == 34


def test_answer_options_still_available_while_pending_reveal(
    client: TestClient,
) -> None:
    """Host can still see the option list (e.g. to change their mind)
    after selecting a match but before revealing points."""
    game_id = _create_game(client)
    _start_round(client, game_id)
    _award(client, game_id, "Actually...", 34)
    resp = client.get(f"/api/speed-points/games/{game_id}/answer-options")
    assert resp.status_code == 200
    assert len(resp.json()) == 5


def test_answer_options_404_when_no_round_active(client: TestClient) -> None:
    game_id = _create_game(client)
    resp = client.get(f"/api/speed-points/games/{game_id}/answer-options")
    assert resp.status_code == 400


def test_update_player_names(client: TestClient) -> None:
    game_id = _create_game(client)
    resp = client.patch(
        f"/api/speed-points/games/{game_id}/players",
        json={"player1_name": "Katherine"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["player1_name"] == "Katherine"
    assert body["player2_name"] == "Grace"  # unaffected


def test_reset_clears_round_state_but_keeps_names(client: TestClient) -> None:
    game_id = _create_game(client)
    _start_round(client, game_id)
    _award(client, game_id, "Actually...", 34)
    _reveal_points(client, game_id)
    client.patch(f"/api/speed-points/games/{game_id}/reveal-result")

    resp = client.patch(f"/api/speed-points/games/{game_id}/reset")
    assert resp.status_code == 200
    body = resp.json()
    assert body["player1_name"] == "Ada"
    assert body["current_player"] is None
    assert body["current_question_index"] == 0
    assert body["player1_slots"] == _empty_slots()
    assert body["player2_slots"] == _empty_slots()
    assert body["scores_revealed"] is False
    assert body["remaining_seconds"] is None
