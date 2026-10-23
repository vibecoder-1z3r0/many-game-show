from playwright.sync_api import Page, expect


def _create_game(live_server: str, page: Page) -> str:
    resp = page.request.post(f"{live_server}/api/answers/games/", data={})
    assert resp.ok
    game_id: str = resp.json()["id"]
    return game_id


def _goto(live_server: str, page: Page, game_id: str, view: str) -> None:
    page.goto(f"{live_server}/answers.html?id={game_id}&view={view}")


def _select_clue(page: Page, category_index: int, clue_index: int) -> None:
    page.click(f'.clue-cell[onclick="selectClue({category_index}, {clue_index})"]')


def _reveal_clue(page: Page) -> None:
    page.get_by_role("button", name="Reveal Clue").click()


def _buzz(page: Page, player: str) -> None:
    # Every player section is rendered in the DOM at once (only one is
    # shown via CSS); scope to the active player's own section so we
    # don't grab another player's hidden button.
    page.click(f"#{player}-body .buzz-btn")


def _wait_for_ring_in_open(live_server: str, page: Page, game_id: str) -> None:
    for _ in range(100):
        resp = page.request.get(f"{live_server}/api/answers/games/{game_id}")
        players = resp.json()["players"]
        if any(p["can_ring_in"] for p in players.values()):
            return
        page.wait_for_timeout(20)
    raise AssertionError("ring-in window never opened")


def test_lobby_create_answers_button_navigates_to_control(
    live_server: str, page: Page
) -> None:
    page.goto(live_server)
    page.get_by_role("button", name="New Answers Game").click()
    page.wait_for_url("**/answers.html?id=*&view=control")
    expect(page.locator("#tab-control")).to_have_class("active")


def test_lobby_bank_selects_list_all_sample_banks(live_server: str, page: Page) -> None:
    page.goto(live_server)
    expect(page.locator("#answers-round1-select option")).to_have_count(3)
    expect(page.locator("#answers-round2-select option")).to_have_count(3)
    expect(page.locator("#answers-final-select option")).to_have_count(5)


def test_control_shows_board_and_all_three_players(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto(live_server, page, game_id, "control")
    expect(page.locator("#control-board .clue-cell")).to_have_count(30)
    expect(page.locator("#control-players .control-player-row")).to_have_count(3)


def test_category_reveal_toggle_shows_and_hides_category_name(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto(live_server, page, game_id, "control")

    toggle = page.locator('button[onclick="toggleCategory(1, true)"]')
    expect(toggle).to_contain_text("Reveal: HTTP Status Quo")
    toggle.click()

    hide_toggle = page.locator('button[onclick="toggleCategory(1, false)"]')
    expect(hide_toggle).to_contain_text("HTTP Status Quo")
    expect(page.locator("#control-board .cat-header").nth(1)).to_contain_text(
        "HTTP Status Quo"
    )

    hide_toggle.click()
    expect(page.locator('button[onclick="toggleCategory(1, true)"]')).to_contain_text(
        "Reveal: HTTP Status Quo"
    )


def test_select_reveal_buzz_judge_correct_awards_points_and_board_control(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto(live_server, page, game_id, "control")

    _select_clue(page, 1, 0)
    expect(page.locator("#control-clue-status")).to_contain_text("HTTP Status Quo")
    _reveal_clue(page)
    expect(page.locator("#control-clue-status")).to_contain_text(
        "Waiting for a ring-in"
    )

    _goto(live_server, page, game_id, "player1")
    _wait_for_ring_in_open(live_server, page, game_id)
    _buzz(page, "player1")
    expect(page.locator("#player1-body")).to_contain_text("You're up")

    _goto(live_server, page, game_id, "control")
    expect(page.locator("#control-clue-status")).to_contain_text("is answering")
    page.get_by_role("button", name="Correct", exact=True).click()

    expect(page.locator("#control-players")).to_contain_text("200")
    expect(page.locator("#control-round-status")).to_contain_text(
        "Board control: Player 1"
    )
    # The clue is consumed and the fieldset closes.
    expect(page.locator("#control-clue-fieldset")).to_be_hidden()


def test_judge_incorrect_locks_out_player_and_reopens_ring_in(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto(live_server, page, game_id, "control")

    _select_clue(page, 1, 0)
    _reveal_clue(page)

    _goto(live_server, page, game_id, "player1")
    _wait_for_ring_in_open(live_server, page, game_id)
    _buzz(page, "player1")

    _goto(live_server, page, game_id, "control")
    page.get_by_role("button", name="Incorrect", exact=True).click()

    expect(page.locator("#control-players")).to_contain_text("-200")
    # Still in play — a second player can still ring in.
    expect(page.locator("#control-clue-fieldset")).to_be_visible()
    expect(page.locator("#control-clue-status")).to_contain_text(
        "Waiting for a ring-in"
    )

    _goto(live_server, page, game_id, "player2")
    _wait_for_ring_in_open(live_server, page, game_id)
    _buzz(page, "player2")

    _goto(live_server, page, game_id, "control")
    page.get_by_role("button", name="Correct", exact=True).click()
    expect(page.locator("#control-round-status")).to_contain_text(
        "Board control: Player 2"
    )


def test_no_one_answered_reveals_clue_with_no_scoring(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto(live_server, page, game_id, "control")

    _select_clue(page, 1, 0)
    _reveal_clue(page)
    page.get_by_role("button", name="No One Answered").click()

    expect(page.locator("#control-clue-fieldset")).to_be_hidden()
    expect(page.locator("#control-players")).to_contain_text("0")


def test_context_clue_wager_reveal_and_judge_correct(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto(live_server, page, game_id, "control")

    page.get_by_role("button", name="P1 Control").click()
    expect(page.locator("#control-round-status")).to_contain_text(
        "Board control: Player 1"
    )

    # Git Happens / index 4 ($1000) is the Context Clue in the sample bank.
    _select_clue(page, 0, 4)
    page.fill("#context-wager-input", "500")
    page.get_by_role("button", name="Set Wager").click()
    _reveal_clue(page)

    expect(page.locator("#control-clue-status")).to_contain_text("Wager: $500")
    page.get_by_role("button", name="Correct", exact=True).click()

    expect(page.locator("#control-players")).to_contain_text("500")
    # Board control is unchanged — they already held it.
    expect(page.locator("#control-round-status")).to_contain_text(
        "Board control: Player 1"
    )


def test_final_exam_self_serve_submit_reveal_and_judge(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    resp = page.request.patch(
        f"{live_server}/api/answers/games/{game_id}/adjust-score",
        data={"player": "player1", "score": 1000},
    )
    assert resp.ok

    _goto(live_server, page, game_id, "control")
    page.get_by_role("button", name="Start Final Exam").click()
    expect(page.locator("#control-final")).to_contain_text("not eligible")

    _goto(live_server, page, game_id, "player1")
    page.fill("#final-wager-player1", "300")
    page.fill("#final-answer-player1", "Who is Ada Lovelace")
    page.get_by_role("button", name="Submit").click()
    expect(page.locator("#player1-body")).to_contain_text("Submitted! Waiting")

    _goto(live_server, page, game_id, "control")
    expect(page.locator("#control-final")).to_contain_text("Player 1: submitted")
    page.get_by_role("button", name="Reveal").click()
    expect(page.locator("#control-final")).to_contain_text("Ada Lovelace")

    page.get_by_role("button", name="Correct", exact=True).click()
    expect(page.locator("#control-players")).to_contain_text("1300")

    _goto(live_server, page, game_id, "player1")
    expect(page.locator("#player1-body")).to_contain_text("Correct!")


def test_board_control_manual_override_visible_on_main(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto(live_server, page, game_id, "control")
    page.get_by_role("button", name="P3 Control").click()

    _goto(live_server, page, game_id, "main")
    expect(page.locator("#main-round-status")).to_contain_text("Round 1")
    highlighted = page.locator("#main-scoreboard .player-card.in-control")
    expect(highlighted).to_have_count(1)
    expect(highlighted).to_contain_text("Player 3")


def test_reset_game_clears_scores_and_board(live_server: str, page: Page) -> None:
    game_id = _create_game(live_server, page)
    resp = page.request.patch(
        f"{live_server}/api/answers/games/{game_id}/adjust-score",
        data={"player": "player1", "score": 777},
    )
    assert resp.ok
    _goto(live_server, page, game_id, "control")
    expect(page.locator("#control-players")).to_contain_text("777")

    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Reset Game", exact=True).click()
    expect(page.locator("#control-players")).not_to_contain_text("777")
    expect(page.locator("#control-round-status")).to_contain_text("Board control: none")
