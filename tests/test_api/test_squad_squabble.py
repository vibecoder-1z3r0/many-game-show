from fastapi.testclient import TestClient


def _create_game(client: TestClient) -> str:
    resp = client.post(
        "/api/squad-squabble/games/",
        json={"team1_name": "Ravens", "team2_name": "Otters"},
    )
    assert resp.status_code == 200
    return resp.json()["id"]  # type: ignore[no-any-return]


def _load(client: TestClient, game_id: str, multiplier: int = 1) -> dict:
    resp = client.patch(
        f"/api/squad-squabble/games/{game_id}/load-question",
        json={"question_id": "desk-drawer", "multiplier": multiplier},
    )
    assert resp.status_code == 200
    return resp.json()  # type: ignore[no-any-return]


def test_create_get_list_delete(client: TestClient) -> None:
    game_id = _create_game(client)

    got = client.get(f"/api/squad-squabble/games/{game_id}")
    assert got.status_code == 200
    body = got.json()
    assert body["team1_name"] == "Ravens"
    assert body["team2_name"] == "Otters"
    assert body["current_question"] is None
    assert body["current_round"] == 1
    assert body["question_visible"] is False
    assert body["round_points"] == 0

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


def test_load_question_resets_round_state_and_hides_question(
    client: TestClient,
) -> None:
    game_id = _create_game(client)
    body = _load(client, game_id, multiplier=2)
    assert body["current_question"]["id"] == "desk-drawer"
    assert body["multiplier"] == 2
    assert body["controlling_team"] is None
    assert body["strikes"] == 0
    assert body["question_visible"] is False  # hidden by default (item 10)
    assert all(not a["revealed"] for a in body["current_question"]["answers"])


def test_load_unknown_question_404(client: TestClient) -> None:
    game_id = _create_game(client)
    resp = client.patch(
        f"/api/squad-squabble/games/{game_id}/load-question",
        json={"question_id": "not-a-real-question"},
    )
    assert resp.status_code == 404


def test_unload_question_clears_round_state(client: TestClient) -> None:
    game_id = _create_game(client)
    _load(client, game_id)
    client.patch(
        f"/api/squad-squabble/games/{game_id}/face-off", json={"team": "team1"}
    )
    client.patch(
        f"/api/squad-squabble/games/{game_id}/reveal", json={"answer_index": 0}
    )

    resp = client.patch(f"/api/squad-squabble/games/{game_id}/unload-question")
    assert resp.status_code == 200
    body = resp.json()
    assert body["current_question"] is None
    assert body["controlling_team"] is None
    assert body["strikes"] == 0
    assert body["round_points"] == 0


def test_question_visibility_toggle(client: TestClient) -> None:
    game_id = _create_game(client)
    _load(client, game_id)

    shown = client.patch(
        f"/api/squad-squabble/games/{game_id}/question-visibility",
        json={"visible": True},
    )
    assert shown.status_code == 200
    assert shown.json()["question_visible"] is True

    hidden = client.patch(
        f"/api/squad-squabble/games/{game_id}/question-visibility",
        json={"visible": False},
    )
    assert hidden.json()["question_visible"] is False


def test_reveal_active_without_control(client: TestClient) -> None:
    """Item 8: reveal should work even if no team currently controls the board."""
    game_id = _create_game(client)
    _load(client, game_id)

    resp = client.patch(
        f"/api/squad-squabble/games/{game_id}/reveal", json={"answer_index": 0}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["current_question"]["answers"][0]["revealed"] is True
    # No auto-crediting (item 6) — points sit in the round pot, not a team score
    assert body["team1_score"] == 0
    assert body["team2_score"] == 0
    assert body["round_points"] == 32


def test_face_off_can_be_cleared(client: TestClient) -> None:
    """Item 8: control can be reset back to 'no one'."""
    game_id = _create_game(client)
    client.patch(
        f"/api/squad-squabble/games/{game_id}/face-off", json={"team": "team1"}
    )

    resp = client.patch(
        f"/api/squad-squabble/games/{game_id}/face-off", json={"team": None}
    )
    assert resp.status_code == 200
    assert resp.json()["controlling_team"] is None


def test_reveal_same_answer_twice_rejected(client: TestClient) -> None:
    game_id = _create_game(client)
    _load(client, game_id)
    client.patch(
        f"/api/squad-squabble/games/{game_id}/reveal", json={"answer_index": 0}
    )
    resp = client.patch(
        f"/api/squad-squabble/games/{game_id}/reveal", json={"answer_index": 0}
    )
    assert resp.status_code == 400


def test_unreveal_puts_answer_back_to_hidden(client: TestClient) -> None:
    """Item 9."""
    game_id = _create_game(client)
    _load(client, game_id)
    client.patch(
        f"/api/squad-squabble/games/{game_id}/reveal", json={"answer_index": 0}
    )

    resp = client.patch(
        f"/api/squad-squabble/games/{game_id}/unreveal", json={"answer_index": 0}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["current_question"]["answers"][0]["revealed"] is False
    assert body["round_points"] == 0


def test_unreveal_not_revealed_rejected(client: TestClient) -> None:
    game_id = _create_game(client)
    _load(client, game_id)
    resp = client.patch(
        f"/api/squad-squabble/games/{game_id}/unreveal", json={"answer_index": 0}
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


def test_strike_max_jumps_to_three(client: TestClient) -> None:
    """Item 1."""
    game_id = _create_game(client)
    resp = client.patch(f"/api/squad-squabble/games/{game_id}/strike/max")
    assert resp.status_code == 200
    assert resp.json()["strikes"] == 3


def test_reveal_remaining_reveals_all_hidden_answers(client: TestClient) -> None:
    """Item 6 restructure: reveal-remaining just reveals — no team credit."""
    game_id = _create_game(client)
    _load(client, game_id, multiplier=1)
    client.patch(
        f"/api/squad-squabble/games/{game_id}/reveal", json={"answer_index": 0}
    )

    resp = client.patch(f"/api/squad-squabble/games/{game_id}/reveal-remaining")
    assert resp.status_code == 200
    body = resp.json()
    assert all(a["revealed"] for a in body["current_question"]["answers"])
    assert body["team1_score"] == 0
    assert body["team2_score"] == 0
    # 32 + 27 + 18 + 13 + 10 = 100
    assert body["round_points"] == 100


def test_award_round_credits_team_and_resets_round(client: TestClient) -> None:
    """Item 6: points accumulate in the round, then get attributed to a team."""
    game_id = _create_game(client)
    _load(client, game_id, multiplier=2)
    client.patch(
        f"/api/squad-squabble/games/{game_id}/face-off", json={"team": "team1"}
    )
    client.patch(
        f"/api/squad-squabble/games/{game_id}/reveal", json={"answer_index": 0}
    )
    client.patch(f"/api/squad-squabble/games/{game_id}/strike")

    resp = client.patch(
        f"/api/squad-squabble/games/{game_id}/award-round", json={"team": "team1"}
    )
    assert resp.status_code == 200
    body = resp.json()
    # 32 pts * 2 multiplier
    assert body["team1_score"] == 64
    assert body["team2_score"] == 0
    assert body["strikes"] == 0
    assert body["controlling_team"] is None
    # revealed answers stay revealed on the board after awarding
    assert body["current_question"]["answers"][0]["revealed"] is True


def test_set_score_arbitrary_and_reset(client: TestClient) -> None:
    """Item 3."""
    game_id = _create_game(client)

    resp = client.patch(
        f"/api/squad-squabble/games/{game_id}/score",
        json={"team": "team2", "value": 250},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["team2_score"] == 250
    assert body["team1_score"] == 0  # unaffected

    reset = client.patch(
        f"/api/squad-squabble/games/{game_id}/score",
        json={"team": "team2", "value": 0},
    )
    assert reset.json()["team2_score"] == 0


def test_set_score_negative_rejected(client: TestClient) -> None:
    game_id = _create_game(client)
    resp = client.patch(
        f"/api/squad-squabble/games/{game_id}/score",
        json={"team": "team1", "value": -5},
    )
    assert resp.status_code == 422


def test_round_number_set_increment_decrement(client: TestClient) -> None:
    """Item 7."""
    game_id = _create_game(client)

    inc = client.patch(f"/api/squad-squabble/games/{game_id}/round/increment")
    assert inc.json()["current_round"] == 2

    inc2 = client.patch(f"/api/squad-squabble/games/{game_id}/round/increment")
    assert inc2.json()["current_round"] == 3

    dec = client.patch(f"/api/squad-squabble/games/{game_id}/round/decrement")
    assert dec.json()["current_round"] == 2

    set_abs = client.patch(
        f"/api/squad-squabble/games/{game_id}/round", json={"round_number": 7}
    )
    assert set_abs.json()["current_round"] == 7


def test_round_number_cannot_go_below_one(client: TestClient) -> None:
    game_id = _create_game(client)
    resp = client.patch(f"/api/squad-squabble/games/{game_id}/round/decrement")
    assert resp.json()["current_round"] == 1  # floors at 1, doesn't go to 0


def test_round_number_set_below_one_rejected(client: TestClient) -> None:
    game_id = _create_game(client)
    resp = client.patch(
        f"/api/squad-squabble/games/{game_id}/round", json={"round_number": 0}
    )
    assert resp.status_code == 422


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


def test_reset_game_clears_state_but_keeps_team_names(client: TestClient) -> None:
    game_id = _create_game(client)
    _load(client, game_id, multiplier=3)
    client.patch(
        f"/api/squad-squabble/games/{game_id}/face-off", json={"team": "team1"}
    )
    client.patch(
        f"/api/squad-squabble/games/{game_id}/reveal", json={"answer_index": 0}
    )
    client.patch(
        f"/api/squad-squabble/games/{game_id}/award-round", json={"team": "team1"}
    )
    client.patch(f"/api/squad-squabble/games/{game_id}/round/increment")
    client.patch(
        f"/api/squad-squabble/games/{game_id}/score",
        json={"team": "team2", "value": 500},
    )

    resp = client.patch(f"/api/squad-squabble/games/{game_id}/reset")
    assert resp.status_code == 200
    body = resp.json()

    assert body["team1_name"] == "Ravens"  # unchanged
    assert body["team2_name"] == "Otters"  # unchanged
    assert body["team1_score"] == 0
    assert body["team2_score"] == 0
    assert body["current_round"] == 1
    assert body["current_question"] is None
    assert body["question_visible"] is False
    assert body["multiplier"] == 1
    assert body["controlling_team"] is None
    assert body["strikes"] == 0
    assert body["round_points"] == 0


def test_strike_animation_defaults(client: TestClient) -> None:
    game_id = _create_game(client)
    resp = client.get(f"/api/squad-squabble/games/{game_id}")
    body = resp.json()
    assert body["strike_anim_hold_ms"] == 1000
    assert body["strike_anim_duration_ms"] == 800


def test_set_strike_animation_timing(client: TestClient) -> None:
    game_id = _create_game(client)
    resp = client.patch(
        f"/api/squad-squabble/games/{game_id}/strike-animation",
        json={"hold_ms": 1200, "duration_ms": 900},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["strike_anim_hold_ms"] == 1200
    assert body["strike_anim_duration_ms"] == 900


def test_set_strike_animation_timing_rejects_out_of_range(client: TestClient) -> None:
    game_id = _create_game(client)
    resp = client.patch(
        f"/api/squad-squabble/games/{game_id}/strike-animation",
        json={"hold_ms": -1, "duration_ms": 600},
    )
    assert resp.status_code == 422
