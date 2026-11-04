import time

from fastapi.testclient import TestClient


def _create_game(client: TestClient) -> str:
    resp = client.post(
        "/api/overdrive/games/",
        json={
            "player1_name": "Ada",
            "player2_name": "Grace",
            "player3_name": "Hedy",
        },
    )
    assert resp.status_code == 200
    return resp.json()["id"]  # type: ignore[no-any-return]


def _get(client: TestClient, game_id: str) -> dict:
    resp = client.get(f"/api/overdrive/games/{game_id}")
    assert resp.status_code == 200
    return resp.json()  # type: ignore[no-any-return]


def _control(client: TestClient, game_id: str) -> dict:
    resp = client.get(f"/api/overdrive/games/{game_id}/control")
    assert resp.status_code == 200
    return resp.json()  # type: ignore[no-any-return]


def _select_clue(client: TestClient, game_id: str, cat: int, clue: int) -> dict:
    resp = client.patch(
        f"/api/overdrive/games/{game_id}/select-clue",
        json={"category_index": cat, "clue_index": clue},
    )
    assert resp.status_code == 200
    return resp.json()  # type: ignore[no-any-return]


def _reveal_clue(client: TestClient, game_id: str) -> dict:
    resp = client.patch(f"/api/overdrive/games/{game_id}/reveal-clue")
    assert resp.status_code == 200
    return resp.json()  # type: ignore[no-any-return]


def _set_fast_ring_in(client: TestClient, game_id: str) -> None:
    resp = client.patch(
        f"/api/overdrive/games/{game_id}/ring-in-settings",
        json={"start_delay_ms": 0, "window_ms": 60000},
    )
    assert resp.status_code == 200


def _buzz(client: TestClient, game_id: str, player: str) -> dict:
    resp = client.patch(f"/api/overdrive/games/{game_id}/buzz", json={"player": player})
    assert resp.status_code == 200
    return resp.json()  # type: ignore[no-any-return]


def _judge(client: TestClient, game_id: str, correct: bool) -> dict:
    resp = client.patch(
        f"/api/overdrive/games/{game_id}/judge", json={"correct": correct}
    )
    assert resp.status_code == 200
    return resp.json()  # type: ignore[no-any-return]


def test_create_sets_up_round1_board_hidden(client: TestClient) -> None:
    game_id = _create_game(client)
    body = _get(client, game_id)
    assert body["current_round"] == "round1"
    assert len(body["categories"]) == 6
    assert all(len(c["clues"]) == 5 for c in body["categories"])
    assert all(not c["revealed"] for c in body["categories"])
    assert body["players"]["player1"]["name"] == "Ada"
    assert body["players"]["player1"]["score"] == 0
    assert body["board_control"] is None


def test_bank_options_lists_all_three_round_types(client: TestClient) -> None:
    resp = client.get("/api/overdrive/games/banks")
    assert resp.status_code == 200
    body = resp.json()
    assert {b["id"] for b in body["round1"]} == {"classic", "movies", "world"}
    assert {b["id"] for b in body["round2"]} == {"classic", "movies", "world"}
    assert {b["id"] for b in body["final"]} == {
        "classic",
        "moon-landing",
        "shakespeare",
        "seven-samurai",
        "andes",
    }


def test_bank_options_include_category_names_for_hosts(client: TestClient) -> None:
    body = client.get("/api/overdrive/games/banks").json()
    classic = next(b for b in body["round1"] if b["id"] == "classic")
    assert classic["categories"][:2] == ["Git Happens", "HTTP Status Quo"]
    assert len(classic["categories"]) == 6
    moon = next(b for b in body["final"] if b["id"] == "moon-landing")
    assert moon["categories"] == ["Space Exploration"]


def test_clue_text_and_answer_hidden_before_selection(client: TestClient) -> None:
    game_id = _create_game(client)
    body = _get(client, game_id)
    clue = body["categories"][0]["clues"][0]
    assert clue["text"] is None
    assert clue["answer"] is None
    assert clue["is_crit_boost"] is False


def test_control_sees_full_answer_key_always(client: TestClient) -> None:
    game_id = _create_game(client)
    body = _control(client, game_id)
    clue = body["categories"][0]["clues"][0]
    assert clue["text"] is not None
    assert clue["answer"] is not None
    # The known Crit Boost clue on the classic round1 bank.
    crit_boost = body["categories"][0]["clues"][4]
    assert crit_boost["is_crit_boost"] is True


def test_category_reveal_toggle(client: TestClient) -> None:
    game_id = _create_game(client)
    resp = client.patch(
        f"/api/overdrive/games/{game_id}/category-reveal",
        json={"category_index": 0, "revealed": True},
    )
    assert resp.status_code == 200
    assert resp.json()["categories"][0]["revealed"] is True

    resp = client.patch(
        f"/api/overdrive/games/{game_id}/category-reveal",
        json={"category_index": 0, "revealed": False},
    )
    assert resp.json()["categories"][0]["revealed"] is False


def test_select_clue_rejects_once_the_clue_in_play_is_revealed(
    client: TestClient,
) -> None:
    game_id = _create_game(client)
    _select_clue(client, game_id, 0, 0)
    _reveal_clue(client, game_id)
    resp = client.patch(
        f"/api/overdrive/games/{game_id}/select-clue",
        json={"category_index": 1, "clue_index": 0},
    )
    assert resp.status_code == 400


def test_select_clue_rejects_already_played(client: TestClient) -> None:
    game_id = _create_game(client)
    _set_fast_ring_in(client, game_id)
    _select_clue(client, game_id, 0, 1)
    _reveal_clue(client, game_id)
    _buzz(client, game_id, "player1")
    _judge(client, game_id, True)
    resp = client.patch(
        f"/api/overdrive/games/{game_id}/select-clue",
        json={"category_index": 0, "clue_index": 1},
    )
    assert resp.status_code == 400


def test_selecting_clue_shows_fly_in_phase_not_yet_text(client: TestClient) -> None:
    game_id = _create_game(client)
    body = _select_clue(client, game_id, 0, 0)
    assert body["clue_phase"] == "selected"
    # select-clue is a Control-only action and returns the full answer key,
    # but the public view other screens poll must still hide the text.
    public = _get(client, game_id)
    assert public["categories"][0]["clues"][0]["text"] is None


def test_reveal_clue_shows_text_to_everyone(client: TestClient) -> None:
    game_id = _create_game(client)
    _select_clue(client, game_id, 0, 0)
    body = _reveal_clue(client, game_id)
    assert body["clue_phase"] == "revealed"
    public = _get(client, game_id)
    assert public["categories"][0]["clues"][0]["text"] is not None
    assert public["categories"][0]["clues"][0]["answer"] is None  # not played yet


def test_reveal_requires_wager_for_crit_boost(client: TestClient) -> None:
    game_id = _create_game(client)
    _select_clue(client, game_id, 0, 4)  # the Crit Boost clue
    resp = client.patch(f"/api/overdrive/games/{game_id}/reveal-clue")
    assert resp.status_code == 400


def test_reveal_requires_board_control_for_crit_boost(client: TestClient) -> None:
    game_id = _create_game(client)
    _select_clue(client, game_id, 0, 4)  # the Crit Boost clue
    client.patch(
        f"/api/overdrive/games/{game_id}/crit-boost-wager", json={"wager": 500}
    )
    resp = client.patch(f"/api/overdrive/games/{game_id}/reveal-clue")
    assert resp.status_code == 400


def test_crit_boost_is_timed_but_does_not_auto_start(client: TestClient) -> None:
    game_id = _create_game(client)
    client.patch(
        f"/api/overdrive/games/{game_id}/board-control", json={"player": "player1"}
    )
    _select_clue(client, game_id, 0, 4)
    client.patch(
        f"/api/overdrive/games/{game_id}/crit-boost-wager", json={"wager": 500}
    )
    body = _reveal_clue(client, game_id)
    assert body["buzzed_player"] == "player1"
    # Ready to time, but not running yet — the host starts it manually
    # (with Play) once they're done reading the clue aloud.
    assert body["answer_timer_running"] is False
    assert body["buzz_remaining_ms"] == body["players"]["player1"]["answer_time_ms"]

    # Host starts it when ready.
    resp = client.patch(f"/api/overdrive/games/{game_id}/play-answer-timer")
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer_timer_running"] is True

    # And can still pause/stop/reset it like any other answer timer.
    resp = client.patch(f"/api/overdrive/games/{game_id}/pause-answer-timer")
    assert resp.status_code == 200
    assert resp.json()["answer_timer_running"] is False


def test_context_wager_rejected_for_regular_clue(client: TestClient) -> None:
    game_id = _create_game(client)
    _select_clue(client, game_id, 0, 0)
    resp = client.patch(
        f"/api/overdrive/games/{game_id}/crit-boost-wager", json={"wager": 500}
    )
    assert resp.status_code == 400


def test_buzz_silently_ignored_before_window_opens(client: TestClient) -> None:
    game_id = _create_game(client)
    client.patch(
        f"/api/overdrive/games/{game_id}/ring-in-settings",
        json={"start_delay_ms": 1000000, "window_ms": 5000},
    )
    _select_clue(client, game_id, 0, 0)
    _reveal_clue(client, game_id)
    body = _buzz(client, game_id, "player1")
    assert body["buzzed_player"] is None


def test_buzz_registers_within_window(client: TestClient) -> None:
    game_id = _create_game(client)
    _set_fast_ring_in(client, game_id)
    _select_clue(client, game_id, 0, 0)
    _reveal_clue(client, game_id)
    body = _buzz(client, game_id, "player2")
    assert body["buzzed_player"] == "player2"


def test_second_buzz_ignored_once_someone_already_in(client: TestClient) -> None:
    game_id = _create_game(client)
    _set_fast_ring_in(client, game_id)
    _select_clue(client, game_id, 0, 0)
    _reveal_clue(client, game_id)
    _buzz(client, game_id, "player1")
    body = _buzz(client, game_id, "player2")
    assert body["buzzed_player"] == "player1"


def _buzz_and_select(client: TestClient, game_id: str, player: str = "player1") -> None:
    _set_fast_ring_in(client, game_id)
    _select_clue(client, game_id, 0, 0)
    _reveal_clue(client, game_id)
    _buzz(client, game_id, player)


def test_pause_answer_timer_freezes_remaining_ms(client: TestClient) -> None:
    game_id = _create_game(client)
    _buzz_and_select(client, game_id)
    time.sleep(0.05)

    resp = client.patch(f"/api/overdrive/games/{game_id}/pause-answer-timer")
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer_timer_running"] is False
    frozen = body["buzz_remaining_ms"]
    assert frozen is not None

    time.sleep(0.05)
    body = _get(client, game_id)
    assert body["buzz_remaining_ms"] == frozen


def test_pause_answer_timer_requires_someone_answering(client: TestClient) -> None:
    game_id = _create_game(client)
    _select_clue(client, game_id, 0, 0)
    _reveal_clue(client, game_id)
    resp = client.patch(f"/api/overdrive/games/{game_id}/pause-answer-timer")
    assert resp.status_code == 400


def test_pause_answer_timer_rejected_when_already_paused(client: TestClient) -> None:
    game_id = _create_game(client)
    _buzz_and_select(client, game_id)
    client.patch(f"/api/overdrive/games/{game_id}/pause-answer-timer")
    resp = client.patch(f"/api/overdrive/games/{game_id}/pause-answer-timer")
    assert resp.status_code == 400


def test_play_answer_timer_resumes_from_paused_remaining(client: TestClient) -> None:
    game_id = _create_game(client)
    _buzz_and_select(client, game_id)
    client.patch(f"/api/overdrive/games/{game_id}/pause-answer-timer")
    paused_remaining = _get(client, game_id)["buzz_remaining_ms"]

    resp = client.patch(f"/api/overdrive/games/{game_id}/play-answer-timer")
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer_timer_running"] is True
    # Resumes from (approximately) where it was paused — a few ms of
    # real wall-clock time pass between the two requests.
    assert abs(body["buzz_remaining_ms"] - paused_remaining) < 100


def test_play_answer_timer_rejected_when_already_running(client: TestClient) -> None:
    game_id = _create_game(client)
    _buzz_and_select(client, game_id)
    resp = client.patch(f"/api/overdrive/games/{game_id}/play-answer-timer")
    assert resp.status_code == 400


def test_stop_answer_timer_zeroes_and_pauses(client: TestClient) -> None:
    game_id = _create_game(client)
    _buzz_and_select(client, game_id)

    resp = client.patch(f"/api/overdrive/games/{game_id}/stop-answer-timer")
    assert resp.status_code == 200
    body = resp.json()
    assert body["buzz_remaining_ms"] == 0
    assert body["answer_timer_running"] is False


def test_reset_answer_timer_restores_full_duration_and_keeps_running(
    client: TestClient,
) -> None:
    game_id = _create_game(client)
    _buzz_and_select(client, game_id)
    client.patch(f"/api/overdrive/games/{game_id}/stop-answer-timer")

    resp = client.patch(f"/api/overdrive/games/{game_id}/reset-answer-timer")
    assert resp.status_code == 200
    body = resp.json()
    assert body["buzz_remaining_ms"] == body["players"]["player1"]["answer_time_ms"]
    # Reset doesn't change the running/paused state — it was paused (by Stop).
    assert body["answer_timer_running"] is False


def test_clear_answer_timer_unbuzzes_and_reopens_ring_in(client: TestClient) -> None:
    game_id = _create_game(client)
    _buzz_and_select(client, game_id)

    resp = client.patch(f"/api/overdrive/games/{game_id}/clear-answer-timer")
    assert resp.status_code == 200
    body = resp.json()
    assert body["buzzed_player"] is None
    assert body["buzz_remaining_ms"] is None
    assert body["players"]["player2"]["can_ring_in"] is True


def test_clear_answer_timer_requires_someone_answering(client: TestClient) -> None:
    game_id = _create_game(client)
    _select_clue(client, game_id, 0, 0)
    _reveal_clue(client, game_id)
    resp = client.patch(f"/api/overdrive/games/{game_id}/clear-answer-timer")
    assert resp.status_code == 400


def test_judge_correct_awards_value_and_sets_control(client: TestClient) -> None:
    game_id = _create_game(client)
    _set_fast_ring_in(client, game_id)
    _select_clue(client, game_id, 0, 1)  # $400
    _reveal_clue(client, game_id)
    _buzz(client, game_id, "player2")
    body = _judge(client, game_id, True)
    assert body["players"]["player2"]["score"] == 400
    assert body["board_control"] == "player2"
    assert body["selected_category_index"] is None
    assert body["categories"][0]["clues"][1]["played"] is True
    assert body["categories"][0]["clues"][1]["answer"] is not None


def test_judge_incorrect_deducts_and_reopens_for_others(client: TestClient) -> None:
    game_id = _create_game(client)
    _set_fast_ring_in(client, game_id)
    _select_clue(client, game_id, 0, 1)  # $400
    _reveal_clue(client, game_id)
    _buzz(client, game_id, "player1")
    body = _judge(client, game_id, False)
    assert body["players"]["player1"]["score"] == -400
    assert body["selected_category_index"] == 0  # clue still in play
    assert body["categories"][0]["clues"][1]["played"] is False
    assert body["buzzed_player"] is None

    # player1 is locked out, but player2 can still ring in.
    resp = client.patch(
        f"/api/overdrive/games/{game_id}/buzz", json={"player": "player1"}
    )
    assert resp.json()["buzzed_player"] is None
    resp = client.patch(
        f"/api/overdrive/games/{game_id}/buzz", json={"player": "player2"}
    )
    assert resp.json()["buzzed_player"] == "player2"


def test_judge_incorrect_from_all_three_closes_clue(client: TestClient) -> None:
    game_id = _create_game(client)
    _set_fast_ring_in(client, game_id)
    _select_clue(client, game_id, 0, 1)
    _reveal_clue(client, game_id)
    for player in ("player1", "player2", "player3"):
        client.patch(f"/api/overdrive/games/{game_id}/buzz", json={"player": player})
        _judge(client, game_id, False)
    body = _get(client, game_id)
    assert body["selected_category_index"] is None
    assert body["categories"][0]["clues"][1]["played"] is True


def test_no_one_answered_closes_clue_without_scoring(client: TestClient) -> None:
    game_id = _create_game(client)
    _select_clue(client, game_id, 0, 0)
    _reveal_clue(client, game_id)
    resp = client.patch(f"/api/overdrive/games/{game_id}/no-one-answered")
    assert resp.status_code == 200
    body = resp.json()
    assert body["selected_category_index"] is None
    assert body["categories"][0]["clues"][0]["played"] is True
    assert body["players"]["player1"]["score"] == 0


def test_crit_boost_full_flow_correct(client: TestClient) -> None:
    game_id = _create_game(client)
    client.patch(
        f"/api/overdrive/games/{game_id}/board-control", json={"player": "player3"}
    )
    _select_clue(client, game_id, 0, 4)
    resp = client.patch(
        f"/api/overdrive/games/{game_id}/crit-boost-wager", json={"wager": 1000}
    )
    assert resp.status_code == 200
    body = _reveal_clue(client, game_id)
    assert body["clue_phase"] == "revealed"
    body = _judge(client, game_id, True)
    assert body["players"]["player3"]["score"] == 1000
    assert body["board_control"] == "player3"  # unchanged


def test_crit_boost_full_flow_incorrect(client: TestClient) -> None:
    game_id = _create_game(client)
    client.patch(
        f"/api/overdrive/games/{game_id}/board-control", json={"player": "player3"}
    )
    _select_clue(client, game_id, 0, 4)
    client.patch(
        f"/api/overdrive/games/{game_id}/crit-boost-wager", json={"wager": 1000}
    )
    _reveal_clue(client, game_id)
    body = _judge(client, game_id, False)
    assert body["players"]["player3"]["score"] == -1000


def test_crit_boost_no_buzzing(client: TestClient) -> None:
    game_id = _create_game(client)
    _set_fast_ring_in(client, game_id)
    client.patch(
        f"/api/overdrive/games/{game_id}/board-control", json={"player": "player1"}
    )
    _select_clue(client, game_id, 0, 4)
    client.patch(
        f"/api/overdrive/games/{game_id}/crit-boost-wager", json={"wager": 500}
    )
    _reveal_clue(client, game_id)
    body = _buzz(client, game_id, "player2")
    # player2's buzz is a no-op — player1 (board control) is already
    # the one "answering" (timed, just without a ring-in race).
    assert body["buzzed_player"] == "player1"


def test_board_control_manual_override(client: TestClient) -> None:
    game_id = _create_game(client)
    resp = client.patch(
        f"/api/overdrive/games/{game_id}/board-control", json={"player": "player2"}
    )
    assert resp.json()["board_control"] == "player2"
    resp = client.patch(
        f"/api/overdrive/games/{game_id}/board-control", json={"player": None}
    )
    assert resp.json()["board_control"] is None


def test_start_round2_resets_board_keeps_scores(client: TestClient) -> None:
    game_id = _create_game(client)
    client.patch(
        f"/api/overdrive/games/{game_id}/adjust-score",
        json={"player": "player1", "score": 1200},
    )
    resp = client.patch(f"/api/overdrive/games/{game_id}/start-round2")
    assert resp.status_code == 200
    body = resp.json()
    assert body["current_round"] == "round2"
    assert body["players"]["player1"]["score"] == 1200
    assert all(not c["revealed"] for c in body["categories"])
    assert body["categories"][0]["clues"][0]["value"] == 400  # round2 values


def test_start_final_marks_eligibility_by_score(client: TestClient) -> None:
    game_id = _create_game(client)
    client.patch(
        f"/api/overdrive/games/{game_id}/adjust-score",
        json={"player": "player1", "score": 500},
    )
    client.patch(
        f"/api/overdrive/games/{game_id}/adjust-score",
        json={"player": "player2", "score": -200},
    )
    resp = client.patch(f"/api/overdrive/games/{game_id}/start-final")
    assert resp.status_code == 200
    body = resp.json()
    assert body["current_round"] == "final"
    assert body["categories"] == []
    assert body["final_category"] == "Famous Firsts in Computing"
    assert body["final_entries"]["player1"]["eligible"] is True
    assert body["final_entries"]["player2"]["eligible"] is False


def test_final_submit_hidden_until_reveal(client: TestClient) -> None:
    game_id = _create_game(client)
    client.patch(
        f"/api/overdrive/games/{game_id}/adjust-score",
        json={"player": "player1", "score": 1000},
    )
    client.patch(f"/api/overdrive/games/{game_id}/start-final")
    resp = client.patch(
        f"/api/overdrive/games/{game_id}/final-submit",
        json={"player": "player1", "wager": 500, "answer": "Who is Ada Lovelace"},
    )
    assert resp.status_code == 200
    body = resp.json()
    entry = body["final_entries"]["player1"]
    assert entry["submitted"] is True
    assert entry["wager"] is None  # hidden until revealed
    assert entry["answer"] is None


def test_final_submit_rejects_wager_over_score(client: TestClient) -> None:
    game_id = _create_game(client)
    client.patch(
        f"/api/overdrive/games/{game_id}/adjust-score",
        json={"player": "player1", "score": 300},
    )
    client.patch(f"/api/overdrive/games/{game_id}/start-final")
    resp = client.patch(
        f"/api/overdrive/games/{game_id}/final-submit",
        json={"player": "player1", "wager": 500, "answer": "x"},
    )
    assert resp.status_code == 422


def test_final_submit_rejects_ineligible_player(client: TestClient) -> None:
    game_id = _create_game(client)
    client.patch(
        f"/api/overdrive/games/{game_id}/adjust-score",
        json={"player": "player1", "score": -100},
    )
    client.patch(f"/api/overdrive/games/{game_id}/start-final")
    resp = client.patch(
        f"/api/overdrive/games/{game_id}/final-submit",
        json={"player": "player1", "wager": 0, "answer": "x"},
    )
    assert resp.status_code == 400


def test_final_submit_rejects_double_submit(client: TestClient) -> None:
    game_id = _create_game(client)
    client.patch(
        f"/api/overdrive/games/{game_id}/adjust-score",
        json={"player": "player1", "score": 1000},
    )
    client.patch(f"/api/overdrive/games/{game_id}/start-final")
    client.patch(
        f"/api/overdrive/games/{game_id}/final-submit",
        json={"player": "player1", "wager": 100, "answer": "x"},
    )
    resp = client.patch(
        f"/api/overdrive/games/{game_id}/final-submit",
        json={"player": "player1", "wager": 100, "answer": "y"},
    )
    assert resp.status_code == 400


def test_final_reveal_and_judge_correct(client: TestClient) -> None:
    game_id = _create_game(client)
    client.patch(
        f"/api/overdrive/games/{game_id}/adjust-score",
        json={"player": "player1", "score": 1000},
    )
    client.patch(f"/api/overdrive/games/{game_id}/start-final")
    client.patch(
        f"/api/overdrive/games/{game_id}/final-submit",
        json={"player": "player1", "wager": 400, "answer": "Who is Ada Lovelace"},
    )
    resp = client.patch(
        f"/api/overdrive/games/{game_id}/final-reveal", json={"player": "player1"}
    )
    assert resp.status_code == 200
    entry = resp.json()["final_entries"]["player1"]
    assert entry["revealed"] is True
    assert entry["wager"] == 400
    assert entry["answer"] == "Who is Ada Lovelace"

    resp = client.patch(
        f"/api/overdrive/games/{game_id}/final-judge",
        json={"player": "player1", "correct": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["players"]["player1"]["score"] == 1400
    assert body["final_entries"]["player1"]["correct"] is True


def test_final_judge_incorrect_deducts_wager(client: TestClient) -> None:
    game_id = _create_game(client)
    client.patch(
        f"/api/overdrive/games/{game_id}/adjust-score",
        json={"player": "player1", "score": 1000},
    )
    client.patch(f"/api/overdrive/games/{game_id}/start-final")
    client.patch(
        f"/api/overdrive/games/{game_id}/final-submit",
        json={"player": "player1", "wager": 400, "answer": "x"},
    )
    client.patch(
        f"/api/overdrive/games/{game_id}/final-reveal", json={"player": "player1"}
    )
    resp = client.patch(
        f"/api/overdrive/games/{game_id}/final-judge",
        json={"player": "player1", "correct": False},
    )
    assert resp.json()["players"]["player1"]["score"] == 600


def test_final_reveal_before_submit_rejected(client: TestClient) -> None:
    game_id = _create_game(client)
    client.patch(
        f"/api/overdrive/games/{game_id}/adjust-score",
        json={"player": "player1", "score": 1000},
    )
    client.patch(f"/api/overdrive/games/{game_id}/start-final")
    resp = client.patch(
        f"/api/overdrive/games/{game_id}/final-reveal", json={"player": "player1"}
    )
    assert resp.status_code == 400


def test_ring_in_player_override_and_clear(client: TestClient) -> None:
    game_id = _create_game(client)
    resp = client.patch(
        f"/api/overdrive/games/{game_id}/ring-in-override",
        json={"player": "player2", "start_delay_ms": 10, "window_ms": 99999},
    )
    assert resp.status_code == 200
    assert resp.json()["players"]["player2"]["ring_in_window_ms"] == 99999
    assert resp.json()["players"]["player1"]["ring_in_window_ms"] != 99999

    resp = client.patch(f"/api/overdrive/games/{game_id}/ring-in-override-clear")
    assert resp.json()["players"]["player2"]["ring_in_window_ms"] != 99999


def test_answer_time_player_override_and_clear(client: TestClient) -> None:
    game_id = _create_game(client)
    resp = client.patch(
        f"/api/overdrive/games/{game_id}/answer-time-override",
        json={"player": "player2", "window_ms": 20000},
    )
    assert resp.json()["players"]["player2"]["answer_time_ms"] == 20000
    resp = client.patch(f"/api/overdrive/games/{game_id}/answer-time-override-clear")
    assert resp.json()["players"]["player2"]["answer_time_ms"] != 20000


def test_adjust_score_allows_negative(client: TestClient) -> None:
    game_id = _create_game(client)
    resp = client.patch(
        f"/api/overdrive/games/{game_id}/adjust-score",
        json={"player": "player1", "score": -500},
    )
    assert resp.json()["players"]["player1"]["score"] == -500


def test_reset_clears_state_keeps_names(client: TestClient) -> None:
    game_id = _create_game(client)
    client.patch(
        f"/api/overdrive/games/{game_id}/adjust-score",
        json={"player": "player1", "score": 999},
    )
    client.patch(
        f"/api/overdrive/games/{game_id}/board-control", json={"player": "player1"}
    )
    resp = client.patch(f"/api/overdrive/games/{game_id}/reset")
    assert resp.status_code == 200
    body = resp.json()
    assert body["players"]["player1"]["score"] == 0
    assert body["players"]["player1"]["name"] == "Ada"
    assert body["board_control"] is None
    assert body["current_round"] == "round1"


def test_delete_game(client: TestClient) -> None:
    game_id = _create_game(client)
    resp = client.delete(f"/api/overdrive/games/{game_id}")
    assert resp.status_code == 204
    resp = client.get(f"/api/overdrive/games/{game_id}")
    assert resp.status_code == 404


def test_list_games(client: TestClient) -> None:
    _create_game(client)
    _create_game(client)
    resp = client.get("/api/overdrive/games/")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_timing_fields_present_for_frontend_countdown_math(client: TestClient) -> None:
    game_id = _create_game(client)
    _set_fast_ring_in(client, game_id)
    _select_clue(client, game_id, 0, 0)
    body = _reveal_clue(client, game_id)
    assert body["ring_in_elapsed_ms"] is not None
    time.sleep(0.05)
    body = _buzz(client, game_id, "player1")
    assert body["buzz_remaining_ms"] is not None


def _set_banks(client: TestClient, game_id: str, **banks: str) -> object:
    return client.patch(f"/api/overdrive/games/{game_id}/banks", json=banks)


def test_banks_default_and_everything_changeable_at_start(client: TestClient) -> None:
    body = _get(client, _create_game(client))
    assert body["round1_bank_id"] == "classic"
    assert body["changeable_banks"] == ["round1", "round2", "final"]


def test_swap_all_banks_before_anything_has_happened(client: TestClient) -> None:
    game_id = _create_game(client)
    resp = _set_banks(
        client,
        game_id,
        round1_bank_id="movies",
        round2_bank_id="world",
        final_bank_id="moon-landing",
    )
    assert resp.status_code == 200  # type: ignore[attr-defined]
    body = resp.json()  # type: ignore[attr-defined]
    assert (body["round1_bank_id"], body["round2_bank_id"]) == ("movies", "world")
    assert body["final_bank_id"] == "moon-landing"
    # Round 1's board was rebuilt from the new bank.
    assert _control(client, game_id)["categories"][0]["name"] == "Blockbusters"


def test_round1_bank_locked_once_a_category_is_revealed(client: TestClient) -> None:
    game_id = _create_game(client)
    client.patch(
        f"/api/overdrive/games/{game_id}/category-reveal",
        json={"category_index": 0, "revealed": True},
    )
    body = _get(client, game_id)
    assert body["changeable_banks"] == ["round2", "final"]
    resp = _set_banks(client, game_id, round1_bank_id="movies")
    assert resp.status_code == 400  # type: ignore[attr-defined]
    assert _get(client, game_id)["round1_bank_id"] == "classic"
    # Later rounds are still free to change mid round 1, and nothing on
    # the live board is disturbed.
    resp = _set_banks(client, game_id, round2_bank_id="world")
    assert resp.status_code == 200  # type: ignore[attr-defined]
    assert _get(client, game_id)["categories"][0]["revealed"] is True


def test_round1_bank_locked_once_a_clue_is_selected(client: TestClient) -> None:
    game_id = _create_game(client)
    _select_clue(client, game_id, 0, 0)
    assert "round1" not in _get(client, game_id)["changeable_banks"]


def test_failed_swap_applies_nothing(client: TestClient) -> None:
    game_id = _create_game(client)
    _select_clue(client, game_id, 0, 0)
    resp = _set_banks(client, game_id, round1_bank_id="movies", round2_bank_id="world")
    assert resp.status_code == 400  # type: ignore[attr-defined]
    body = _get(client, game_id)
    assert (body["round1_bank_id"], body["round2_bank_id"]) == ("classic", "classic")


def test_round2_bank_swappable_until_round2_board_is_touched(
    client: TestClient,
) -> None:
    game_id = _create_game(client)
    client.patch(f"/api/overdrive/games/{game_id}/start-round2")
    assert _get(client, game_id)["changeable_banks"] == ["round2", "final"]
    resp = _set_banks(client, game_id, round2_bank_id="world")
    assert resp.status_code == 200  # type: ignore[attr-defined]
    client.patch(
        f"/api/overdrive/games/{game_id}/category-reveal",
        json={"category_index": 0, "revealed": True},
    )
    assert _get(client, game_id)["changeable_banks"] == ["final"]
    assert _set_banks(client, game_id, round1_bank_id="movies").status_code == 400  # type: ignore[attr-defined]


def test_nothing_changeable_once_final_has_started(client: TestClient) -> None:
    game_id = _create_game(client)
    client.patch(f"/api/overdrive/games/{game_id}/start-final")
    assert _get(client, game_id)["changeable_banks"] == []
    assert _set_banks(client, game_id, final_bank_id="shakespeare").status_code == 400  # type: ignore[attr-defined]


def test_swap_rejects_unknown_bank(client: TestClient) -> None:
    game_id = _create_game(client)
    assert _set_banks(client, game_id, round1_bank_id="nope").status_code == 422  # type: ignore[attr-defined]


def _patch(client: TestClient, game_id: str, action: str, body: dict | None = None):  # type: ignore[no-untyped-def]
    return client.patch(f"/api/overdrive/games/{game_id}/{action}", json=body)


def test_selecting_another_clue_swaps_an_unrevealed_selection(
    client: TestClient,
) -> None:
    game_id = _create_game(client)
    _select_clue(client, game_id, 0, 0)
    body = _select_clue(client, game_id, 1, 2)
    assert (body["selected_category_index"], body["selected_clue_index"]) == (1, 2)
    assert body["clue_phase"] == "selected"


def test_selecting_the_same_clue_again_changes_nothing(client: TestClient) -> None:
    game_id = _create_game(client)
    _patch(client, game_id, "auto-reveal-settings", {"delay_ms": 60000})
    first = _select_clue(client, game_id, 0, 0)["auto_reveal_remaining_ms"]
    again = _select_clue(client, game_id, 0, 0)["auto_reveal_remaining_ms"]
    assert again <= first  # the countdown wasn't restarted


def test_deselect_clears_an_unrevealed_selection(client: TestClient) -> None:
    game_id = _create_game(client)
    _select_clue(client, game_id, 0, 0)
    resp = _patch(client, game_id, "deselect-clue")
    assert resp.status_code == 200
    body = resp.json()
    assert body["selected_category_index"] is None
    assert body["clue_phase"] is None


def test_deselect_errors_without_selection_or_after_reveal(
    client: TestClient,
) -> None:
    game_id = _create_game(client)
    assert _patch(client, game_id, "deselect-clue").status_code == 400
    _select_clue(client, game_id, 0, 0)
    _reveal_clue(client, game_id)
    assert _patch(client, game_id, "deselect-clue").status_code == 400


def test_auto_reveal_is_off_by_default(client: TestClient) -> None:
    game_id = _create_game(client)
    body = _select_clue(client, game_id, 0, 0)
    assert body["auto_reveal_delay_ms"] == 0
    assert body["auto_reveal_remaining_ms"] is None


def test_auto_reveal_reveals_the_clue_after_the_delay(client: TestClient) -> None:
    game_id = _create_game(client)
    _patch(client, game_id, "auto-reveal-settings", {"delay_ms": 150})
    body = _select_clue(client, game_id, 0, 0)
    assert body["clue_phase"] == "selected"
    assert 0 < body["auto_reveal_remaining_ms"] <= 150
    time.sleep(0.3)
    body = _get(client, game_id)
    assert body["clue_phase"] == "revealed"
    assert body["categories"][0]["clues"][0]["text"] is not None
    assert body["auto_reveal_remaining_ms"] is None


def test_deselecting_cancels_a_pending_auto_reveal(client: TestClient) -> None:
    game_id = _create_game(client)
    _patch(client, game_id, "auto-reveal-settings", {"delay_ms": 150})
    _select_clue(client, game_id, 0, 0)
    _patch(client, game_id, "deselect-clue")
    time.sleep(0.3)
    assert _get(client, game_id)["clue_phase"] is None


def test_auto_reveal_never_fires_for_a_crit_boost(client: TestClient) -> None:
    game_id = _create_game(client)
    _patch(client, game_id, "auto-reveal-settings", {"delay_ms": 100})
    body = _select_clue(client, game_id, 0, 4)  # the Crit Boost clue
    assert body["auto_reveal_remaining_ms"] is None
    time.sleep(0.25)
    assert _get(client, game_id)["clue_phase"] == "selected"


def test_auto_reveal_setting_is_validated(client: TestClient) -> None:
    game_id = _create_game(client)
    for delay in (-1, 60001):
        resp = _patch(client, game_id, "auto-reveal-settings", {"delay_ms": delay})
        assert resp.status_code == 422


def test_host_can_ring_in_for_a_player_outside_their_window(
    client: TestClient,
) -> None:
    game_id = _create_game(client)
    # A window that opens far in the future: a real buzz would be ignored.
    _patch(
        client,
        game_id,
        "ring-in-settings",
        {"start_delay_ms": 50000, "window_ms": 1000},
    )
    _select_clue(client, game_id, 0, 0)
    _reveal_clue(client, game_id)
    assert _buzz(client, game_id, "player2")["buzzed_player"] is None

    resp = _patch(client, game_id, "host-ring-in", {"player": "player2"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["buzzed_player"] == "player2"
    assert body["answer_timer_running"] is True
    assert body["buzz_remaining_ms"] > 0


def test_host_ring_in_refusals(client: TestClient) -> None:
    game_id = _create_game(client)
    _set_fast_ring_in(client, game_id)
    # No clue yet / not revealed yet.
    assert (
        _patch(client, game_id, "host-ring-in", {"player": "player1"}).status_code
        == 400
    )
    _select_clue(client, game_id, 0, 0)
    assert (
        _patch(client, game_id, "host-ring-in", {"player": "player1"}).status_code
        == 400
    )
    _reveal_clue(client, game_id)

    # Someone else already answering.
    _patch(client, game_id, "host-ring-in", {"player": "player1"})
    resp = _patch(client, game_id, "host-ring-in", {"player": "player2"})
    assert resp.status_code == 400
    assert "already answering" in resp.json()["detail"]

    # A player who answered wrong is locked out of that clue.
    _judge(client, game_id, False)
    resp = _patch(client, game_id, "host-ring-in", {"player": "player1"})
    assert resp.status_code == 400
    assert "locked out" in resp.json()["detail"]
    assert (
        _patch(client, game_id, "host-ring-in", {"player": "player3"}).status_code
        == 200
    )


def test_host_ring_in_refused_on_a_crit_boost(client: TestClient) -> None:
    game_id = _create_game(client)
    _patch(client, game_id, "board-control", {"player": "player1"})
    _select_clue(client, game_id, 0, 4)
    _patch(client, game_id, "crit-boost-wager", {"wager": 100})
    _reveal_clue(client, game_id)
    resp = _patch(client, game_id, "host-ring-in", {"player": "player2"})
    assert resp.status_code == 400
