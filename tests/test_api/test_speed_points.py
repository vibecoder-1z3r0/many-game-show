from fastapi.testclient import TestClient


def _create_game(client: TestClient) -> str:
    resp = client.post(
        "/api/speed-points/games/",
        json={"player1_name": "Ada", "player2_name": "Grace"},
    )
    assert resp.status_code == 200
    return resp.json()["id"]  # type: ignore[no-any-return]


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
    assert body["player1_points"] == [None] * 5
    assert body["player2_points"] == [None] * 5
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


def test_award_records_points_and_advances_question(client: TestClient) -> None:
    game_id = _create_game(client)
    client.patch(
        f"/api/speed-points/games/{game_id}/start-round",
        json={"player": "player1"},
    )

    resp = client.patch(f"/api/speed-points/games/{game_id}/award", json={"points": 34})
    assert resp.status_code == 200
    body = resp.json()
    assert body["player1_points"][0] == 34
    assert body["current_question_index"] == 1
    assert body["player1_total"] == 34


def test_award_with_zero_records_no_match(client: TestClient) -> None:
    game_id = _create_game(client)
    client.patch(
        f"/api/speed-points/games/{game_id}/start-round",
        json={"player": "player1"},
    )
    resp = client.patch(f"/api/speed-points/games/{game_id}/award", json={"points": 0})
    assert resp.json()["player1_points"][0] == 0


def test_award_without_active_round_is_rejected(client: TestClient) -> None:
    game_id = _create_game(client)
    resp = client.patch(f"/api/speed-points/games/{game_id}/award", json={"points": 10})
    assert resp.status_code == 400


def test_award_past_fifth_question_is_rejected(client: TestClient) -> None:
    game_id = _create_game(client)
    client.patch(
        f"/api/speed-points/games/{game_id}/start-round",
        json={"player": "player1"},
    )
    for _ in range(5):
        resp = client.patch(
            f"/api/speed-points/games/{game_id}/award", json={"points": 5}
        )
        assert resp.status_code == 200
    assert resp.json()["current_question_index"] == 5
    assert resp.json()["current_question"] is None

    sixth = client.patch(f"/api/speed-points/games/{game_id}/award", json={"points": 5})
    assert sixth.status_code == 400


def test_full_relay_reveal_result_and_win_threshold(client: TestClient) -> None:
    game_id = _create_game(client)

    client.patch(
        f"/api/speed-points/games/{game_id}/start-round",
        json={"player": "player1"},
    )
    for pts in [34, 26, 20, 12, 8]:  # 100
        client.patch(f"/api/speed-points/games/{game_id}/award", json={"points": pts})

    client.patch(
        f"/api/speed-points/games/{game_id}/start-round",
        json={"player": "player2"},
    )
    for pts in [38, 24, 18, 12, 8]:  # 100
        client.patch(f"/api/speed-points/games/{game_id}/award", json={"points": pts})

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
    client.patch(
        f"/api/speed-points/games/{game_id}/start-round",
        json={"player": "player1"},
    )
    resp = client.get(f"/api/speed-points/games/{game_id}/answer-options")
    assert resp.status_code == 200
    options = resp.json()
    assert len(options) == 5
    assert options[0]["text"] == "Actually..."
    assert options[0]["points"] == 34


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
    client.patch(
        f"/api/speed-points/games/{game_id}/start-round",
        json={"player": "player1"},
    )
    client.patch(f"/api/speed-points/games/{game_id}/award", json={"points": 34})
    client.patch(f"/api/speed-points/games/{game_id}/reveal-result")

    resp = client.patch(f"/api/speed-points/games/{game_id}/reset")
    assert resp.status_code == 200
    body = resp.json()
    assert body["player1_name"] == "Ada"
    assert body["current_player"] is None
    assert body["current_question_index"] == 0
    assert body["player1_points"] == [None] * 5
    assert body["player2_points"] == [None] * 5
    assert body["scores_revealed"] is False
    assert body["remaining_seconds"] is None
