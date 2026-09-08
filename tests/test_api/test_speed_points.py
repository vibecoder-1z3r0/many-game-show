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


def _set_answer(client: TestClient, game_id: str, i: int, text: str) -> dict:
    resp = client.patch(
        f"/api/speed-points/games/{game_id}/answer",
        json={"question_index": i, "text": text},
    )
    assert resp.status_code == 200
    return resp.json()  # type: ignore[no-any-return]


def _lock_answer(client: TestClient, game_id: str, i: int, locked: bool = True) -> dict:
    resp = client.patch(
        f"/api/speed-points/games/{game_id}/answer-lock",
        json={"question_index": i, "locked": locked},
    )
    assert resp.status_code == 200
    return resp.json()  # type: ignore[no-any-return]


def _set_points(client: TestClient, game_id: str, i: int, points: int) -> dict:
    resp = client.patch(
        f"/api/speed-points/games/{game_id}/points",
        json={"question_index": i, "points": points},
    )
    assert resp.status_code == 200
    return resp.json()  # type: ignore[no-any-return]


def _lock_points(client: TestClient, game_id: str, i: int, locked: bool = True) -> dict:
    resp = client.patch(
        f"/api/speed-points/games/{game_id}/points-lock",
        json={"question_index": i, "locked": locked},
    )
    assert resp.status_code == 200
    return resp.json()  # type: ignore[no-any-return]


def _empty_slot() -> dict:
    """A fresh slot as the public (Main/Host) view sees it — nothing
    drafted, nothing revealed."""
    return {"text": None, "points": None, "duplicate": False}


def _empty_judge_slot() -> dict:
    """A fresh slot as the Judge view sees it — drafts always visible,
    just not yet locked."""
    return {
        "text": "",
        "points": 0,
        "text_revealed": False,
        "points_revealed": False,
        "duplicate": False,
    }


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
    assert body["player1_slots"] == [_empty_slot()] * 5
    assert body["player2_slots"] == [_empty_slot()] * 5
    assert body["player1_total"] == 0
    assert body["player2_total"] == 0
    assert body["combined_total"] == 0
    assert body["win_threshold"] == 200
    assert body["won"] is False
    assert body["scores_revealed"] is False
    assert body["remaining_seconds"] is None
    assert [q["id"] for q in body["all_questions"]] == [
        "code-review-word",
        "standup-word",
        "laptop-sticker",
        "deploy-fear",
        "ai-assistant-use",
    ]
    assert all("prompt" in q for q in body["all_questions"])

    listed = client.get("/api/speed-points/games/")
    assert listed.status_code == 200
    assert any(g["id"] == game_id for g in listed.json())

    deleted = client.delete(f"/api/speed-points/games/{game_id}")
    assert deleted.status_code == 204
    assert client.get(f"/api/speed-points/games/{game_id}").status_code == 404


def test_judge_endpoint_shows_full_draft_visibility(client: TestClient) -> None:
    game_id = _create_game(client)
    resp = client.get(f"/api/speed-points/games/{game_id}/judge")
    assert resp.status_code == 200
    body = resp.json()
    assert body["player1_slots"] == [_empty_judge_slot()] * 5
    assert body["player2_slots"] == [_empty_judge_slot()] * 5
    assert "all_questions" in body
    assert "created_at" not in body  # judge view is a leaner, live-state-only shape


def test_start_round_sets_current_player_and_timer(client: TestClient) -> None:
    game_id = _create_game(client)

    resp = client.patch(
        f"/api/speed-points/games/{game_id}/start-round",
        json={"player": "player1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["current_player"] == "player1"
    assert body["timer_duration_seconds"] == 20
    assert body["remaining_seconds"] == 20
    assert body["player1_slots"] == [_empty_slot()] * 5


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


def test_answer_draft_visible_to_judge_before_locking(client: TestClient) -> None:
    """The judge sees their own typed draft immediately — it's only
    Main/Host that can't see it until locked."""
    game_id = _create_game(client)
    _start_round(client, game_id)

    body = _set_answer(client, game_id, 2, "tangled cables")
    assert body["player1_slots"][2]["text"] == "tangled cables"
    assert body["player1_slots"][2]["text_revealed"] is False

    # Public view still hides it.
    public = client.get(f"/api/speed-points/games/{game_id}").json()
    assert public["player1_slots"][2] == _empty_slot()


def test_answer_and_points_are_independent(client: TestClient) -> None:
    """Text and points can be drafted, locked, and revealed independently
    of each other, in any order — locking one doesn't require the other."""
    game_id = _create_game(client)
    _start_round(client, game_id)

    _set_answer(client, game_id, 2, "tangled cables")
    body = _lock_answer(client, game_id, 2)
    assert body["player1_slots"][2]["text"] == "tangled cables"
    assert body["player1_slots"][2]["text_revealed"] is True
    assert body["player1_slots"][2]["points_revealed"] is False

    public = client.get(f"/api/speed-points/games/{game_id}").json()
    assert public["player1_slots"][2] == {
        "text": "tangled cables",
        "points": None,
        "duplicate": False,
    }
    assert public["player1_total"] == 0

    _set_points(client, game_id, 2, 34)
    body = _lock_points(client, game_id, 2)
    assert body["player1_slots"][2]["points"] == 34
    assert body["player1_slots"][2]["points_revealed"] is True
    assert body["player1_total"] == 34

    public = client.get(f"/api/speed-points/games/{game_id}").json()
    assert public["player1_slots"][2] == {
        "text": "tangled cables",
        "points": 34,
        "duplicate": False,
    }


def test_points_can_lock_before_answer(client: TestClient) -> None:
    game_id = _create_game(client)
    _start_round(client, game_id)
    _set_points(client, game_id, 0, 34)
    body = _lock_points(client, game_id, 0)
    assert body["player1_slots"][0]["points"] == 34
    assert body["player1_slots"][0]["points_revealed"] is True
    assert body["player1_slots"][0]["text_revealed"] is False
    assert body["player1_total"] == 34

    public = client.get(f"/api/speed-points/games/{game_id}").json()
    assert public["player1_slots"][0] == {
        "text": None,
        "points": 34,
        "duplicate": False,
    }


def test_any_question_index_workable_in_any_order(client: TestClient) -> None:
    game_id = _create_game(client)
    _start_round(client, game_id)
    _set_answer(client, game_id, 4, "last question first")
    _lock_answer(client, game_id, 4)
    body = _set_answer(client, game_id, 0, "first question")
    assert body["player1_slots"][4]["text"] == "last question first"
    assert body["player1_slots"][0]["text"] == "first question"
    assert body["player1_slots"][0]["text_revealed"] is False


def test_editing_requires_unlocking_first(client: TestClient) -> None:
    game_id = _create_game(client)
    _start_round(client, game_id)
    _set_answer(client, game_id, 0, "cables")
    _lock_answer(client, game_id, 0)

    resp = client.patch(
        f"/api/speed-points/games/{game_id}/answer",
        json={"question_index": 0, "text": "something else"},
    )
    assert resp.status_code == 400

    body = _lock_answer(client, game_id, 0, locked=False)
    assert body["player1_slots"][0]["text_revealed"] is False
    body = _set_answer(client, game_id, 0, "something else")
    assert body["player1_slots"][0]["text"] == "something else"


def test_unlock_hides_previously_revealed_value(client: TestClient) -> None:
    game_id = _create_game(client)
    _start_round(client, game_id)
    _set_points(client, game_id, 0, 34)
    _lock_points(client, game_id, 0)

    _lock_points(client, game_id, 0, locked=False)
    public = client.get(f"/api/speed-points/games/{game_id}").json()
    assert public["player1_slots"][0]["points"] is None


def test_answer_without_active_round_is_rejected(client: TestClient) -> None:
    game_id = _create_game(client)
    resp = client.patch(
        f"/api/speed-points/games/{game_id}/answer",
        json={"question_index": 0, "text": "x"},
    )
    assert resp.status_code == 400


def test_out_of_range_question_index_is_rejected(client: TestClient) -> None:
    game_id = _create_game(client)
    _start_round(client, game_id)
    resp = client.patch(
        f"/api/speed-points/games/{game_id}/answer",
        json={"question_index": 5, "text": "x"},
    )
    assert resp.status_code == 422


def test_duplicate_flag_settable_per_question_any_time(client: TestClient) -> None:
    game_id = _create_game(client)
    _start_round(client, game_id)

    resp = client.patch(
        f"/api/speed-points/games/{game_id}/duplicate-flag",
        json={"question_index": 3, "flagged": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["player1_slots"][3]["duplicate"] is True
    assert body["player1_slots"][0]["duplicate"] is False


def test_full_relay_reveal_result_and_win_threshold(client: TestClient) -> None:
    game_id = _create_game(client)

    _start_round(client, game_id, "player1")
    for i, pts in enumerate([34, 26, 20, 12, 8]):  # 100
        _set_points(client, game_id, i, pts)
        _lock_points(client, game_id, i)

    _start_round(client, game_id, "player2")
    for i, pts in enumerate([38, 24, 18, 12, 8]):  # 100
        _set_points(client, game_id, i, pts)
        _lock_points(client, game_id, i)

    pre_reveal = client.get(f"/api/speed-points/games/{game_id}").json()
    assert pre_reveal["combined_total"] == 200
    assert pre_reveal["scores_revealed"] is False

    resp = client.patch(f"/api/speed-points/games/{game_id}/reveal-result")
    assert resp.status_code == 200
    body = resp.json()
    assert body["scores_revealed"] is True
    assert body["combined_total"] == 200
    assert body["won"] is True


def test_answer_key_returns_all_five_questions_with_full_answers(
    client: TestClient,
) -> None:
    game_id = _create_game(client)
    resp = client.get(f"/api/speed-points/games/{game_id}/answer-key")
    assert resp.status_code == 200
    key = resp.json()
    assert len(key) == 5
    assert key[0]["id"] == "code-review-word"
    assert len(key[0]["answers"]) == 5
    assert key[0]["answers"][0]["text"] == "Actually..."
    assert key[0]["answers"][0]["points"] == 34


def test_answer_key_available_even_before_round_starts(client: TestClient) -> None:
    game_id = _create_game(client)
    resp = client.get(f"/api/speed-points/games/{game_id}/answer-key")
    assert resp.status_code == 200
    assert len(resp.json()) == 5


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
    _set_answer(client, game_id, 0, "cables")
    _lock_answer(client, game_id, 0)
    _set_points(client, game_id, 0, 34)
    _lock_points(client, game_id, 0)
    client.patch(f"/api/speed-points/games/{game_id}/reveal-result")

    resp = client.patch(f"/api/speed-points/games/{game_id}/reset")
    assert resp.status_code == 200
    body = resp.json()
    assert body["player1_name"] == "Ada"
    assert body["current_player"] is None
    assert body["player1_slots"] == [_empty_judge_slot()] * 5
    assert body["player2_slots"] == [_empty_judge_slot()] * 5
    assert body["scores_revealed"] is False
    assert body["remaining_seconds"] is None
