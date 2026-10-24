import time

from playwright.sync_api import Page, expect

# Slower than the 150ms game default (set per game via PATCH
# .../chase-speed in _create_game) so each square's window is wide enough
# to tolerate local HTTP/click overhead. Sleeping to the middle of a target
# index's window (index + 0.5 steps) gives tolerance in either direction.
TEST_CHASE_STEP_MS = 300
CHASE_STEP_S = TEST_CHASE_STEP_MS / 1000


def _create_game(live_server: str, page: Page, board_id: str = "classic") -> str:
    resp = page.request.post(
        f"{live_server}/api/big-tokens/games/", data={"board_id": board_id}
    )
    assert resp.ok
    game_id: str = resp.json()["id"]
    resp = page.request.patch(
        f"{live_server}/api/big-tokens/games/{game_id}/chase-speed",
        data={"step_ms": TEST_CHASE_STEP_MS},
    )
    assert resp.ok
    return game_id


def _goto(live_server: str, page: Page, game_id: str, view: str) -> None:
    page.goto(f"{live_server}/big-tokens.html?id={game_id}&view={view}")


def _adjust(
    live_server: str, page: Page, game_id: str, player: str, **fields: object
) -> None:
    resp = page.request.patch(
        f"{live_server}/api/big-tokens/games/{game_id}/adjust-player",
        data={"player": player, **fields},
    )
    assert resp.ok


def _set_active(live_server: str, page: Page, game_id: str, player: str) -> None:
    resp = page.request.patch(
        f"{live_server}/api/big-tokens/games/{game_id}/active-player",
        data={"player": player},
    )
    assert resp.ok


def _spin_and_land_via_api(
    live_server: str, page: Page, game_id: str, index: int
) -> None:
    resp = page.request.patch(
        f"{live_server}/api/big-tokens/games/{game_id}/start-spin"
    )
    assert resp.ok
    time.sleep((index + 0.5) * CHASE_STEP_S)
    resp = page.request.patch(f"{live_server}/api/big-tokens/games/{game_id}/stop-spin")
    assert resp.ok


def test_lobby_create_big_tokens_button_navigates_to_control(
    live_server: str, page: Page
) -> None:
    page.goto(live_server)
    page.get_by_role("button", name="New Big Tokens Game").click()
    page.wait_for_url("**/big-tokens.html?id=*&view=control")
    expect(page.locator("#tab-control")).to_have_class("active")


def test_lobby_board_select_lists_both_boards(live_server: str, page: Page) -> None:
    page.goto(live_server)
    options = page.locator("#big-tokens-board-select option")
    expect(options).to_have_count(2)


def test_control_shows_board_and_all_three_players(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto(live_server, page, game_id, "control")
    expect(page.locator("#control-board .square")).to_have_count(18)
    expect(page.locator("#control-players .control-player-row")).to_have_count(3)


def test_control_grant_spins_and_set_active_player(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto(live_server, page, game_id, "control")

    page.fill("#grant-spins-player1", "3")
    page.click("button[onclick=\"grantSpins('player1')\"]")
    expect(page.locator("#control-players")).to_contain_text("3 spins")

    page.click("button[onclick=\"setActivePlayer('player1')\"]")
    expect(page.locator("#control-turn-status")).to_contain_text("Player 1's turn")


def test_main_view_shows_board_and_turn_status(live_server: str, page: Page) -> None:
    game_id = _create_game(live_server, page)
    _set_active(live_server, page, game_id, "player2")
    _goto(live_server, page, game_id, "main")
    expect(page.locator("#main-board .square")).to_have_count(18)
    expect(page.locator("#main-turn-status")).to_contain_text("Player 2's turn")


def test_control_chase_speed_defaults_to_150_and_can_be_changed(
    live_server: str, page: Page
) -> None:
    resp = page.request.post(f"{live_server}/api/big-tokens/games/", data={})
    assert resp.ok
    game_id = resp.json()["id"]
    _goto(live_server, page, game_id, "control")

    step_input = page.locator("#chase-step-input")
    expect(step_input).to_have_value("150")

    step_input.fill("400")
    page.get_by_role("button", name="Apply", exact=True).click()
    page.reload()
    expect(page.locator("#chase-step-input")).to_have_value("400")


def test_player_view_has_no_spin_button_when_not_active(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _set_active(live_server, page, game_id, "player2")
    _goto(live_server, page, game_id, "player1")
    expect(page.locator(".spin-btn")).to_have_count(0)
    expect(page.locator("#player1-body")).to_contain_text("Waiting for Player 2")


def test_player_view_shows_spin_button_when_active_with_spins(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _adjust(live_server, page, game_id, "player1", spins_remaining=3)
    _set_active(live_server, page, game_id, "player1")
    _goto(live_server, page, game_id, "player1")
    expect(page.locator(".spin-btn")).to_contain_text("SPIN")
    expect(page.get_by_role("button", name="Pass Remaining Spins")).to_be_visible()


def test_spin_stop_resolves_tokens_square_from_the_players_own_device(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _adjust(live_server, page, game_id, "player1", spins_remaining=1)
    _set_active(live_server, page, game_id, "player1")
    _goto(live_server, page, game_id, "player1")

    page.click(".spin-btn")
    expect(page.locator(".spin-btn")).to_contain_text("STOP")
    page.click(".spin-btn.stop")

    # Which square the chase was over is timing-dependent, so don't predict
    # it — check the Stop locked in *a* square and the player's own view
    # shows whatever the server resolved (per-square effects are covered
    # by the backend tests).
    expect(page.locator("#player1-body .square.landed")).to_have_count(1)
    resp = page.request.get(f"{live_server}/api/big-tokens/games/{game_id}")
    assert resp.ok
    state = resp.json()
    assert state["last_landed_square_index"] is not None
    player = state["players"]["player1"]

    my_stats = page.locator("#player1-body .my-stats")
    expect(my_stats).to_contain_text(f"{player['token_total']} tokens")
    expect(my_stats).to_contain_text(f"{player['spins_remaining']} spin(s)")


def test_hallucination_hit_shows_strike_and_out_badge_at_max(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    # Classic board: max_hallucinations 3, square 2 is HALLUCINATION!.
    _adjust(
        live_server, page, game_id, "player1", spins_remaining=1, hallucination_count=2
    )
    _set_active(live_server, page, game_id, "player1")
    _spin_and_land_via_api(live_server, page, game_id, 2)

    _goto(live_server, page, game_id, "main")
    expect(page.locator("#main-scoreboard")).to_contain_text("Hallucinated")


def test_choice_square_shows_two_options_and_resolves(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    # Square 13: Take 400 Tokens or Remove a Hallucination.
    _adjust(live_server, page, game_id, "player1", spins_remaining=1)
    _set_active(live_server, page, game_id, "player1")
    _spin_and_land_via_api(live_server, page, game_id, 13)

    _goto(live_server, page, game_id, "player1")
    expect(page.get_by_role("button", name="Take 400 Tokens")).to_be_visible()
    page.get_by_role("button", name="Take 400 Tokens").click()
    expect(page.locator("#player1-body .my-stats")).to_contain_text("400 tokens")


def test_target_square_shows_other_players_and_resolves(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    # Square 8: Steal 300 Tokens.
    _adjust(live_server, page, game_id, "player1", spins_remaining=1)
    _adjust(live_server, page, game_id, "player2", token_total=1000)
    _set_active(live_server, page, game_id, "player1")
    _spin_and_land_via_api(live_server, page, game_id, 8)

    _goto(live_server, page, game_id, "player1")
    expect(page.get_by_role("button", name="Target Player 2")).to_be_visible()
    page.get_by_role("button", name="Target Player 2").click()
    expect(page.locator("#player1-body .my-stats")).to_contain_text("300 tokens")


def test_pass_remaining_spins_switches_active_player(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _adjust(live_server, page, game_id, "player1", spins_remaining=3)
    _set_active(live_server, page, game_id, "player1")
    _goto(live_server, page, game_id, "player1")

    page.get_by_role("button", name="Pass Remaining Spins").click()
    expect(page.locator("#player1-body")).to_contain_text("Waiting for Player 2")

    _goto(live_server, page, game_id, "player2")
    expect(page.locator(".spin-btn")).to_contain_text("SPIN")


def test_control_override_can_force_stop_and_resolve_pending_choice(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _adjust(live_server, page, game_id, "player1", spins_remaining=1)
    _set_active(live_server, page, game_id, "player1")
    _goto(live_server, page, game_id, "control")

    resp = page.request.patch(
        f"{live_server}/api/big-tokens/games/{game_id}/start-spin"
    )
    assert resp.ok
    # Poll the live chase position instead of a fixed sleep — a fixed
    # sleep followed by a page click has unpredictable extra latency
    # (button-visibility wait, etc.) that can drift onto the wrong square.
    for _ in range(1000):
        resp = page.request.get(f"{live_server}/api/big-tokens/games/{game_id}")
        if resp.json()["chase_position"] == 13:
            break
        time.sleep(0.01)
    else:
        raise AssertionError("chase never reached square 13")

    page.get_by_role("button", name="Force Stop (override)").click()
    expect(page.locator("#control-resolution")).to_contain_text("Take 400 Tokens")
    page.get_by_role("button", name="Take 400 Tokens").click()
    expect(page.locator("#control-players")).to_contain_text("400 tokens")


def test_reset_game_clears_scores(live_server: str, page: Page) -> None:
    game_id = _create_game(live_server, page)
    _adjust(live_server, page, game_id, "player1", token_total=999, spins_remaining=5)
    _goto(live_server, page, game_id, "control")

    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Reset Game", exact=True).click()
    expect(page.locator("#control-players")).to_contain_text("0 tokens")


def test_landed_square_stays_highlighted_until_new_spin_or_cleared(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _adjust(live_server, page, game_id, "player1", spins_remaining=2)
    _set_active(live_server, page, game_id, "player1")
    _goto(live_server, page, game_id, "player1")

    page.click(".spin-btn")
    expect(page.locator(".spin-btn")).to_contain_text("STOP")
    page.wait_for_timeout(int(0.5 * CHASE_STEP_S * 1000))  # land on square 0
    page.click(".spin-btn.stop")

    landed = page.locator("#player1-body .square.landed")
    expect(landed).to_have_count(1)
    # Stays highlighted across ordinary poll ticks after resolution.
    page.wait_for_timeout(600)
    expect(landed).to_have_count(1)

    # Clearing from Control removes it everywhere.
    _goto(live_server, page, game_id, "control")
    expect(page.locator("#control-board .square.landed")).to_have_count(1)
    page.get_by_role("button", name="Clear Selected Square Highlighting").click()
    expect(page.locator("#control-board .square.landed")).to_have_count(0)

    # Starting a new spin also clears it (re-grant a spin first).
    _adjust(live_server, page, game_id, "player1", spins_remaining=1)
    _goto(live_server, page, game_id, "player1")
    page.wait_for_timeout(300)
    page.click(".spin-btn")
    expect(page.locator("#player1-body .square.landed")).to_have_count(0)
