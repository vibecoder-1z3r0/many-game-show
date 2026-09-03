from fastapi.testclient import TestClient


def _create_game(client: TestClient) -> str:
    resp = client.post(
        "/api/squad-squabble/games/",
        json={"team1_name": "Ravens", "team2_name": "Otters"},
    )
    assert resp.status_code == 200
    return resp.json()["id"]  # type: ignore[no-any-return]


def test_create_get_list_delete(client: TestClient) -> None:
    game_id = _create_game(client)

    got = client.get(f"/api/squad-squabble/games/{game_id}")
    assert got.status_code == 200
    body = got.json()
    assert body["team1_name"] == "Ravens"
    assert body["team2_name"] == "Otters"
    assert body["current_question"] is None

    listed = client.get("/api/squad-squabble/games/")
    assert listed.status_code == 200
    assert any(g["id"] == game_id for g in listed.json())

    deleted = client.delete(f"/api/squad-squabble/games/{game_id}")
    assert deleted.status_code == 204
    assert client.get(f"/api/squad-squabble/games/{game_id}").status_code == 404


def test_get_missing_game_404(client: TestClient) -> None:
    resp = client.get("/api/squad-squabble/games/does-not-exist")
    assert resp.status_code == 404


def test_question_bank_lists_sample_questions(client: TestClient) -> None:
    game_id = _create_game(client)
    resp = client.get(f"/api/squad-squabble/games/{game_id}/questions")
    assert resp.status_code == 200
    ids = [q["id"] for q in resp.json()]
    assert "desk-drawer" in ids


def test_load_question_resets_round_state(client: TestClient) -> None:
    game_id = _create_game(client)
    resp = client.patch(
        f"/api/squad-squabble/games/{game_id}/load-question",
        json={"question_id": "desk-drawer", "multiplier": 2},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["current_question"]["id"] == "desk-drawer"
    assert body["multiplier"] == 2
    assert body["controlling_team"] is None
    assert body["strikes"] == 0
    assert all(not a["revealed"] for a in body["current_question"]["answers"])


def test_load_unknown_question_404(client: TestClient) -> None:
    game_id = _create_game(client)
    resp = client.patch(
        f"/api/squad-squabble/games/{game_id}/load-question",
        json={"question_id": "not-a-real-question"},
    )
    assert resp.status_code == 404


def test_reveal_requires_control(client: TestClient) -> None:
    game_id = _create_game(client)
    client.patch(
        f"/api/squad-squabble/games/{game_id}/load-question",
        json={"question_id": "desk-drawer"},
    )
    resp = client.patch(
        f"/api/squad-squabble/games/{game_id}/reveal", json={"answer_index": 0}
    )
    assert resp.status_code == 400


def test_reveal_awards_points_with_multiplier(client: TestClient) -> None:
    game_id = _create_game(client)
    client.patch(
        f"/api/squad-squabble/games/{game_id}/load-question",
        json={"question_id": "desk-drawer", "multiplier": 3},
    )
    client.patch(
        f"/api/squad-squabble/games/{game_id}/face-off", json={"team": "team1"}
    )

    resp = client.patch(
        f"/api/squad-squabble/games/{game_id}/reveal", json={"answer_index": 0}
    )
    assert resp.status_code == 200
    body = resp.json()
    # "Tangled cables" is 32 points -> 32 * 3 multiplier
    assert body["team1_score"] == 96
    assert body["team2_score"] == 0
    assert body["current_question"]["answers"][0]["revealed"] is True


def test_reveal_same_answer_twice_rejected(client: TestClient) -> None:
    game_id = _create_game(client)
    client.patch(
        f"/api/squad-squabble/games/{game_id}/load-question",
        json={"question_id": "desk-drawer"},
    )
    client.patch(
        f"/api/squad-squabble/games/{game_id}/face-off", json={"team": "team1"}
    )
    client.patch(
        f"/api/squad-squabble/games/{game_id}/reveal", json={"answer_index": 0}
    )
    resp = client.patch(
        f"/api/squad-squabble/games/{game_id}/reveal", json={"answer_index": 0}
    )
    assert resp.status_code == 400


def test_strikes_accumulate_and_cap_at_three(client: TestClient) -> None:
    game_id = _create_game(client)
    for _ in range(3):
        resp = client.patch(f"/api/squad-squabble/games/{game_id}/strike")
        assert resp.status_code == 200
    assert resp.json()["strikes"] == 3

    over = client.patch(f"/api/squad-squabble/games/{game_id}/strike")
    assert over.status_code == 400


def test_steal_awards_remaining_points_to_stealing_team(client: TestClient) -> None:
    game_id = _create_game(client)
    client.patch(
        f"/api/squad-squabble/games/{game_id}/load-question",
        json={"question_id": "desk-drawer", "multiplier": 1},
    )
    client.patch(
        f"/api/squad-squabble/games/{game_id}/face-off", json={"team": "team1"}
    )
    # team1 reveals the top answer (32 pts), then whiffs — team2 steals the rest
    client.patch(
        f"/api/squad-squabble/games/{game_id}/reveal", json={"answer_index": 0}
    )
    resp = client.patch(
        f"/api/squad-squabble/games/{game_id}/steal", json={"team": "team2"}
    )
    assert resp.status_code == 200
    body = resp.json()
    # remaining answers: 27 + 18 + 13 + 10 = 68
    assert body["team2_score"] == 68
    assert body["team1_score"] == 32
    assert all(a["revealed"] for a in body["current_question"]["answers"])


def test_update_teams_partial(client: TestClient) -> None:
    game_id = _create_game(client)
    resp = client.patch(
        f"/api/squad-squabble/games/{game_id}/teams", json={"team1_name": "Sharks"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["team1_name"] == "Sharks"
    assert body["team2_name"] == "Otters"  # unchanged


def test_set_status(client: TestClient) -> None:
    game_id = _create_game(client)
    resp = client.patch(
        f"/api/squad-squabble/games/{game_id}/status", json={"status": "final"}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "final"
