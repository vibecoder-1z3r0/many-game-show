import pytest
from fastapi.testclient import TestClient


def _create_game(client: TestClient, board_id: str = "classic") -> str:
    resp = client.post(
        "/api/big-tokens/games/",
        json={
            "board_id": board_id,
            "player1_name": "Ada",
            "player2_name": "Grace",
            "player3_name": "Hedy",
        },
    )
    assert resp.status_code == 200
    return resp.json()["id"]  # type: ignore[no-any-return]


def _get(client: TestClient, game_id: str) -> dict:
    resp = client.get(f"/api/big-tokens/games/{game_id}")
    assert resp.status_code == 200
    return resp.json()  # type: ignore[no-any-return]


def _set_active(client: TestClient, game_id: str, player: str) -> dict:
    resp = client.patch(
        f"/api/big-tokens/games/{game_id}/active-player", json={"player": player}
    )
    assert resp.status_code == 200
    return resp.json()  # type: ignore[no-any-return]


def _adjust(client: TestClient, game_id: str, player: str, **fields: object) -> dict:
    resp = client.patch(
        f"/api/big-tokens/games/{game_id}/adjust-player",
        json={"player": player, **fields},
    )
    assert resp.status_code == 200
    return resp.json()  # type: ignore[no-any-return]


def _start_spin(client: TestClient, game_id: str) -> dict:
    resp = client.patch(f"/api/big-tokens/games/{game_id}/start-spin")
    assert resp.status_code == 200
    return resp.json()  # type: ignore[no-any-return]


def _lock_square(monkeypatch: pytest.MonkeyPatch, index: int) -> None:
    monkeypatch.setattr(
        "manygameshow.routers.big_tokens.chase_position", lambda game, now=None: index
    )


def _spin_and_land(
    client: TestClient, game_id: str, monkeypatch: pytest.MonkeyPatch, index: int
) -> dict:
    _start_spin(client, game_id)
    _lock_square(monkeypatch, index)
    resp = client.patch(f"/api/big-tokens/games/{game_id}/stop-spin")
    assert resp.status_code == 200
    return resp.json()  # type: ignore[no-any-return]


def _choose(client: TestClient, game_id: str, choice: str) -> dict:
    resp = client.patch(
        f"/api/big-tokens/games/{game_id}/choose", json={"choice": choice}
    )
    assert resp.status_code == 200
    return resp.json()  # type: ignore[no-any-return]


def _target(client: TestClient, game_id: str, target: str) -> dict:
    resp = client.patch(
        f"/api/big-tokens/games/{game_id}/target", json={"target": target}
    )
    assert resp.status_code == 200
    return resp.json()  # type: ignore[no-any-return]


def test_create_sets_up_three_players_and_default_board(client: TestClient) -> None:
    game_id = _create_game(client)
    body = _get(client, game_id)
    assert body["board_id"] == "classic"
    assert body["board_name"] == "Classic Board"
    assert len(body["squares"]) == 18
    assert body["players"]["player1"]["name"] == "Ada"
    assert body["players"]["player2"]["name"] == "Grace"
    assert body["players"]["player3"]["name"] == "Hedy"
    for p in body["players"].values():
        assert p["token_total"] == 0
        assert p["spins_remaining"] == 0
        assert p["is_out"] is False
    assert body["current_player"] is None
    assert body["round_number"] == 1
    assert body["chase_position"] is None
    assert body["awaiting"] is None


def test_board_options_lists_both_sample_boards(client: TestClient) -> None:
    resp = client.get("/api/big-tokens/games/boards")
    assert resp.status_code == 200
    ids = {b["id"] for b in resp.json()}
    assert ids == {"classic", "chaos"}


def test_active_player_endpoint_sets_current_player(client: TestClient) -> None:
    game_id = _create_game(client)
    body = _set_active(client, game_id, "player2")
    assert body["current_player"] == "player2"


def test_adjust_player_sets_requested_fields_only(client: TestClient) -> None:
    game_id = _create_game(client)
    body = _adjust(client, game_id, "player1", token_total=500, spins_remaining=3)
    p1 = body["players"]["player1"]
    assert p1["token_total"] == 500
    assert p1["spins_remaining"] == 3
    assert p1["hallucination_count"] == 0


def test_start_spin_requires_active_player(client: TestClient) -> None:
    game_id = _create_game(client)
    resp = client.patch(f"/api/big-tokens/games/{game_id}/start-spin")
    assert resp.status_code == 400


def test_start_spin_requires_spins_remaining(client: TestClient) -> None:
    game_id = _create_game(client)
    _set_active(client, game_id, "player1")
    resp = client.patch(f"/api/big-tokens/games/{game_id}/start-spin")
    assert resp.status_code == 400


def test_start_spin_sets_a_live_chase_position(client: TestClient) -> None:
    game_id = _create_game(client)
    _set_active(client, game_id, "player1")
    _adjust(client, game_id, "player1", spins_remaining=3)
    body = _start_spin(client, game_id)
    assert body["chase_position"] is not None


def test_stop_spin_without_active_spin_errors(client: TestClient) -> None:
    game_id = _create_game(client)
    _set_active(client, game_id, "player1")
    _adjust(client, game_id, "player1", spins_remaining=3)
    resp = client.patch(f"/api/big-tokens/games/{game_id}/stop-spin")
    assert resp.status_code == 400


def test_tokens_square_resolves_immediately(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    game_id = _create_game(client)
    _set_active(client, game_id, "player1")
    _adjust(client, game_id, "player1", spins_remaining=3)
    body = _spin_and_land(client, game_id, monkeypatch, 0)  # +300 Tokens
    p1 = body["players"]["player1"]
    assert p1["token_total"] == 300
    assert p1["spins_remaining"] == 2
    assert body["pending_square_index"] is None
    assert body["awaiting"] is None
    assert body["current_player"] == "player1"
    assert body["last_landed_square_index"] == 0


def test_double_square_doubles_token_total(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    game_id = _create_game(client)
    _set_active(client, game_id, "player1")
    _adjust(client, game_id, "player1", spins_remaining=1, token_total=400)
    body = _spin_and_land(client, game_id, monkeypatch, 7)  # Double Your Tokens
    assert body["players"]["player1"]["token_total"] == 800


def test_free_spin_square_nets_zero_spin_cost(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    game_id = _create_game(client)
    _set_active(client, game_id, "player1")
    _adjust(client, game_id, "player1", spins_remaining=2)
    body = _spin_and_land(client, game_id, monkeypatch, 16)  # Free Spin (fixed)
    assert body["players"]["player1"]["spins_remaining"] == 2


def test_square_cascades_after_being_landed_on(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    game_id = _create_game(client)
    _set_active(client, game_id, "player1")
    _adjust(client, game_id, "player1", spins_remaining=2)
    # Square 1: +500 Tokens -> +750 Tokens.
    body = _spin_and_land(client, game_id, monkeypatch, 1)
    assert body["players"]["player1"]["token_total"] == 500
    assert body["squares"][1]["amount"] == 750

    _adjust(client, game_id, "player1", spins_remaining=1)
    body = _spin_and_land(client, game_id, monkeypatch, 1)
    assert body["players"]["player1"]["token_total"] == 500 + 750


def test_hallucination_wipes_every_hit_on_classic_board(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    game_id = _create_game(client, board_id="classic")
    _set_active(client, game_id, "player1")
    _adjust(client, game_id, "player1", spins_remaining=2, token_total=1000)
    body = _spin_and_land(client, game_id, monkeypatch, 2)  # HALLUCINATION!
    p1 = body["players"]["player1"]
    assert p1["token_total"] == 0
    assert p1["hallucination_count"] == 1
    assert p1["is_out"] is False


def test_hallucination_elimination_at_max_ends_participation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    game_id = _create_game(client, board_id="classic")
    _set_active(client, game_id, "player1")
    _adjust(
        client,
        game_id,
        "player1",
        spins_remaining=5,
        hallucination_count=2,
        token_total=100,
    )
    body = _spin_and_land(client, game_id, monkeypatch, 6)  # 2nd HALLUCINATION! index
    p1 = body["players"]["player1"]
    assert p1["hallucination_count"] == 3
    assert p1["is_out"] is True
    assert p1["out_reason"] == "hallucinated"
    # Turn auto-advances since the active player is now out.
    assert body["current_player"] == "player2"


def test_chaos_board_only_wipes_on_the_eliminating_hallucination(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    game_id = _create_game(client, board_id="chaos")
    _set_active(client, game_id, "player1")
    _adjust(client, game_id, "player1", spins_remaining=5, token_total=1000)
    # Chaos max_hallucinations is 2; square 1 is the first HALLUCINATION!.
    body = _spin_and_land(client, game_id, monkeypatch, 1)
    p1 = body["players"]["player1"]
    assert p1["hallucination_count"] == 1
    assert p1["token_total"] == 1000  # not wiped yet - not the eliminating hit
    assert p1["is_out"] is False

    body = _spin_and_land(client, game_id, monkeypatch, 4)  # 2nd HALLUCINATION!
    p1 = body["players"]["player1"]
    assert p1["hallucination_count"] == 2
    assert p1["token_total"] == 0  # eliminating hit wipes
    assert p1["is_out"] is True


def test_steal_square_requires_a_target_then_resolves(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    game_id = _create_game(client)
    _set_active(client, game_id, "player1")
    _adjust(client, game_id, "player1", spins_remaining=1)
    _adjust(client, game_id, "player2", token_total=1000)
    body = _spin_and_land(client, game_id, monkeypatch, 8)  # Steal 300 Tokens
    assert body["awaiting"] == "target"
    assert body["pending_square_index"] == 8

    body = _target(client, game_id, "player2")
    assert body["players"]["player1"]["token_total"] == 300
    assert body["players"]["player2"]["token_total"] == 700
    assert body["awaiting"] is None
    assert body["pending_square_index"] is None


def test_steal_clamps_to_targets_available_tokens(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    game_id = _create_game(client)
    _set_active(client, game_id, "player1")
    _adjust(client, game_id, "player1", spins_remaining=1)
    _adjust(client, game_id, "player2", token_total=100)
    _spin_and_land(client, game_id, monkeypatch, 8)  # Steal 300 Tokens
    body = _target(client, game_id, "player2")
    assert body["players"]["player1"]["token_total"] == 100
    assert body["players"]["player2"]["token_total"] == 0


def test_target_rejects_targeting_self(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    game_id = _create_game(client)
    _set_active(client, game_id, "player1")
    _adjust(client, game_id, "player1", spins_remaining=1)
    _spin_and_land(client, game_id, monkeypatch, 8)
    resp = client.patch(
        f"/api/big-tokens/games/{game_id}/target", json={"target": "player1"}
    )
    assert resp.status_code == 422


def test_choice_swap_or_free_spin_choosing_free_spin_resolves_immediately(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    game_id = _create_game(client)
    _set_active(client, game_id, "player1")
    _adjust(client, game_id, "player1", spins_remaining=2)
    body = _spin_and_land(client, game_id, monkeypatch, 10)  # choice square
    assert body["awaiting"] == "choice"

    body = _choose(client, game_id, "free_spin")
    assert body["awaiting"] is None
    assert body["players"]["player1"]["spins_remaining"] == 2  # net zero cost


def test_choice_swap_or_free_spin_choosing_swap_then_needs_target(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    game_id = _create_game(client)
    _set_active(client, game_id, "player1")
    _adjust(client, game_id, "player1", spins_remaining=1, token_total=200)
    _adjust(client, game_id, "player3", token_total=900)
    _spin_and_land(client, game_id, monkeypatch, 10)
    body = _choose(client, game_id, "swap_scores")
    assert body["awaiting"] == "target"

    body = _target(client, game_id, "player3")
    assert body["players"]["player1"]["token_total"] == 900
    assert body["players"]["player3"]["token_total"] == 200
    assert body["awaiting"] is None


def test_choice_tokens_or_cure_choosing_tokens(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    game_id = _create_game(client)
    _set_active(client, game_id, "player1")
    _adjust(client, game_id, "player1", spins_remaining=1)
    _spin_and_land(
        client, game_id, monkeypatch, 13
    )  # Take 400 Tokens or Remove a Hallucination
    body = _choose(client, game_id, "tokens")
    assert body["players"]["player1"]["token_total"] == 400
    assert body["awaiting"] is None


def test_choice_tokens_or_cure_choosing_cure_reduces_hallucination_count(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    game_id = _create_game(client)
    _set_active(client, game_id, "player1")
    _adjust(client, game_id, "player1", spins_remaining=1, hallucination_count=2)
    _spin_and_land(client, game_id, monkeypatch, 13)
    body = _choose(client, game_id, "cure")
    assert body["players"]["player1"]["hallucination_count"] == 1
    assert body["players"]["player1"]["token_total"] == 0


def test_choice_tokens_or_cure_rejects_cure_when_no_hallucinations(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    game_id = _create_game(client)
    _set_active(client, game_id, "player1")
    _adjust(client, game_id, "player1", spins_remaining=1)
    _spin_and_land(client, game_id, monkeypatch, 13)
    resp = client.patch(
        f"/api/big-tokens/games/{game_id}/choose", json={"choice": "cure"}
    )
    assert resp.status_code == 400


def test_choose_rejects_invalid_choice_for_square(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    game_id = _create_game(client)
    _set_active(client, game_id, "player1")
    _adjust(client, game_id, "player1", spins_remaining=1)
    _spin_and_land(client, game_id, monkeypatch, 10)  # swap-or-free-spin square
    resp = client.patch(
        f"/api/big-tokens/games/{game_id}/choose", json={"choice": "tokens"}
    )
    assert resp.status_code == 422


def test_choose_without_pending_choice_rejected(client: TestClient) -> None:
    game_id = _create_game(client)
    _set_active(client, game_id, "player1")
    resp = client.patch(
        f"/api/big-tokens/games/{game_id}/choose", json={"choice": "tokens"}
    )
    assert resp.status_code == 400


def test_target_without_pending_target_rejected(client: TestClient) -> None:
    game_id = _create_game(client)
    _set_active(client, game_id, "player1")
    resp = client.patch(
        f"/api/big-tokens/games/{game_id}/target", json={"target": "player2"}
    )
    assert resp.status_code == 400


def test_no_spins_left_marks_out_and_advances_turn(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    game_id = _create_game(client)
    _set_active(client, game_id, "player1")
    _adjust(client, game_id, "player1", spins_remaining=1)
    body = _spin_and_land(client, game_id, monkeypatch, 0)
    p1 = body["players"]["player1"]
    assert p1["spins_remaining"] == 0
    assert p1["is_out"] is True
    assert p1["out_reason"] == "no_spins"
    assert body["current_player"] == "player2"


def test_pass_spins_requires_no_mandatory_spins(client: TestClient) -> None:
    game_id = _create_game(client)
    _set_active(client, game_id, "player1")
    _adjust(client, game_id, "player1", spins_remaining=3, mandatory_spins=1)
    resp = client.patch(f"/api/big-tokens/games/{game_id}/pass-spins")
    assert resp.status_code == 400


def test_pass_spins_transfers_to_next_player_in_turn_order(client: TestClient) -> None:
    game_id = _create_game(client)
    _set_active(client, game_id, "player1")
    _adjust(client, game_id, "player1", spins_remaining=3)
    resp = client.patch(f"/api/big-tokens/games/{game_id}/pass-spins")
    assert resp.status_code == 200
    body = resp.json()
    assert body["players"]["player1"]["spins_remaining"] == 0
    p2 = body["players"]["player2"]
    assert p2["spins_remaining"] == 3
    assert p2["mandatory_spins"] == 3
    assert body["current_player"] == "player2"


def test_pass_spins_skips_out_players(client: TestClient) -> None:
    game_id = _create_game(client)
    _set_active(client, game_id, "player1")
    _adjust(client, game_id, "player1", spins_remaining=3)
    _adjust(client, game_id, "player2", is_out=True, out_reason="no_spins")
    resp = client.patch(f"/api/big-tokens/games/{game_id}/pass-spins")
    assert resp.status_code == 200
    body = resp.json()
    assert body["current_player"] == "player3"
    assert body["players"]["player3"]["spins_remaining"] == 3


def test_start_round_resets_round_scoped_hallucinations(client: TestClient) -> None:
    game_id = _create_game(client, board_id="chaos")  # elimination_scope: round
    _adjust(
        client,
        game_id,
        "player1",
        hallucination_count=2,
        is_out=True,
        out_reason="hallucinated",
    )
    resp = client.patch(f"/api/big-tokens/games/{game_id}/start-round")
    assert resp.status_code == 200
    body = resp.json()
    assert body["round_number"] == 2
    p1 = body["players"]["player1"]
    assert p1["hallucination_count"] == 0
    assert p1["is_out"] is False
    assert p1["spins_remaining"] == 0


def test_start_round_preserves_game_scoped_eliminations(client: TestClient) -> None:
    game_id = _create_game(client, board_id="classic")  # elimination_scope: game
    _adjust(
        client,
        game_id,
        "player1",
        hallucination_count=3,
        is_out=True,
        out_reason="hallucinated",
    )
    resp = client.patch(f"/api/big-tokens/games/{game_id}/start-round")
    assert resp.status_code == 200
    p1 = resp.json()["players"]["player1"]
    assert p1["is_out"] is True
    assert p1["hallucination_count"] == 3


def test_last_landed_square_persists_after_immediate_resolution(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    game_id = _create_game(client)
    _set_active(client, game_id, "player1")
    _adjust(client, game_id, "player1", spins_remaining=2)
    body = _spin_and_land(client, game_id, monkeypatch, 5)  # +1000 Tokens
    assert body["last_landed_square_index"] == 5
    # A second, unrelated mutation shouldn't clear it.
    body = _adjust(client, game_id, "player2", token_total=10)
    assert body["last_landed_square_index"] == 5


def test_last_landed_square_persists_through_pending_resolution(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    game_id = _create_game(client)
    _set_active(client, game_id, "player1")
    _adjust(client, game_id, "player1", spins_remaining=1)
    body = _spin_and_land(client, game_id, monkeypatch, 8)  # Steal 300 Tokens
    assert body["last_landed_square_index"] == 8
    body = _target(client, game_id, "player2")
    assert body["last_landed_square_index"] == 8


def test_starting_a_new_spin_clears_the_previous_highlight(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    game_id = _create_game(client)
    _set_active(client, game_id, "player1")
    _adjust(client, game_id, "player1", spins_remaining=2)
    _spin_and_land(client, game_id, monkeypatch, 0)
    body = _start_spin(client, game_id)
    assert body["last_landed_square_index"] is None


def test_clear_highlight_endpoint(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    game_id = _create_game(client)
    _set_active(client, game_id, "player1")
    _adjust(client, game_id, "player1", spins_remaining=1)
    body = _spin_and_land(client, game_id, monkeypatch, 0)
    assert body["last_landed_square_index"] == 0

    resp = client.patch(f"/api/big-tokens/games/{game_id}/clear-highlight")
    assert resp.status_code == 200
    assert resp.json()["last_landed_square_index"] is None


def test_reset_game_clears_state_but_keeps_names(client: TestClient) -> None:
    game_id = _create_game(client)
    _set_active(client, game_id, "player1")
    _adjust(client, game_id, "player1", token_total=999, spins_remaining=5)
    resp = client.patch(f"/api/big-tokens/games/{game_id}/reset")
    assert resp.status_code == 200
    body = resp.json()
    assert body["current_player"] is None
    assert body["round_number"] == 1
    assert body["players"]["player1"]["token_total"] == 0
    assert body["players"]["player1"]["name"] == "Ada"


def test_delete_game(client: TestClient) -> None:
    game_id = _create_game(client)
    resp = client.delete(f"/api/big-tokens/games/{game_id}")
    assert resp.status_code == 204
    resp = client.get(f"/api/big-tokens/games/{game_id}")
    assert resp.status_code == 404


def test_list_games(client: TestClient) -> None:
    _create_game(client)
    _create_game(client)
    resp = client.get("/api/big-tokens/games/")
    assert resp.status_code == 200
    assert len(resp.json()) == 2
