from playwright.sync_api import Page, expect


def _create_game(live_server: str, page: Page) -> str:
    resp = page.request.post(
        f"{live_server}/api/speed-points/games/",
        data={"player1_name": "Ada", "player2_name": "Grace"},
    )
    assert resp.ok
    game_id: str = resp.json()["id"]
    return game_id


def _goto_control(live_server: str, page: Page, game_id: str) -> None:
    page.goto(f"{live_server}/speed-points.html?id={game_id}&view=control")


def test_lobby_create_speed_points_button_navigates_to_control(
    live_server: str, page: Page
) -> None:
    page.goto(live_server)
    page.get_by_role("button", name="New Speed Points Game").click()
    page.wait_for_url("**/speed-points.html?id=*&view=control")
    expect(page.locator("#tab-control")).to_have_class("active")


def test_start_round_shows_first_question_and_answer_options(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto_control(live_server, page, game_id)

    page.get_by_role("button", name="Start Player 1", exact=True).click()
    expect(page.locator("#current-prompt")).to_contain_text("code review comment")
    expect(page.locator("#answer-options button.award-btn")).to_have_count(
        6
    )  # 5 + no-match


def test_award_advances_to_next_question_and_updates_tally(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto_control(live_server, page, game_id)
    page.get_by_role("button", name="Start Player 1", exact=True).click()

    page.locator("#answer-options button.award-btn").first.click()
    expect(page.locator("#player1-tally .tally-slot").first).to_have_text("34")
    expect(page.locator("#current-prompt")).to_contain_text("standup")


def test_no_match_button_awards_zero(live_server: str, page: Page) -> None:
    game_id = _create_game(live_server, page)
    _goto_control(live_server, page, game_id)
    page.get_by_role("button", name="Start Player 1", exact=True).click()

    page.get_by_role("button", name="No match (0)", exact=True).click()
    expect(page.locator("#player1-tally .tally-slot").first).to_have_text("0")


def test_completing_five_questions_shows_start_player2(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto_control(live_server, page, game_id)
    page.get_by_role("button", name="Start Player 1", exact=True).click()

    for _ in range(5):
        page.get_by_role("button", name="No match (0)", exact=True).click()

    expect(page.locator("#current-prompt")).to_contain_text("No question in play")
    expect(
        page.get_by_role("button", name="Start Player 2", exact=True)
    ).to_be_enabled()


def test_reveal_result_shows_verdict(live_server: str, page: Page) -> None:
    game_id = _create_game(live_server, page)
    _goto_control(live_server, page, game_id)

    page.get_by_role("button", name="Start Player 1", exact=True).click()
    for _ in range(5):
        page.locator("#answer-options button.award-btn").first.click()
    page.get_by_role("button", name="Start Player 2", exact=True).click()
    for _ in range(5):
        page.locator("#answer-options button.award-btn").first.click()

    page.get_by_role("button", name="Reveal Result", exact=True).click()

    # The verdict banner is a Display-only affordance (the big screen the
    # audience watches) — Control just has the button that triggers it.
    # Always clicking the first (highest-value) answer option for every
    # question clears the 200-point threshold, whatever the exact total is.
    page.goto(f"{live_server}/speed-points.html?id={game_id}&view=display")
    expect(page.locator("#verdict")).to_be_visible()
    expect(page.locator("#verdict")).to_contain_text("WINNER!")


def test_display_view_hides_answer_key_and_shows_prompt(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto_control(live_server, page, game_id)
    page.get_by_role("button", name="Start Player 1", exact=True).click()

    page.goto(f"{live_server}/speed-points.html?id={game_id}&view=display")
    expect(page.locator("#display-prompt")).to_contain_text("code review comment")
    expect(page.locator("body")).not_to_contain_text("Actually...")


def test_reset_game_requires_confirmation_and_clears_state(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto_control(live_server, page, game_id)
    page.get_by_role("button", name="Start Player 1", exact=True).click()
    page.locator("#answer-options button.award-btn").first.click()

    page.once("dialog", lambda dialog: dialog.dismiss())
    page.get_by_role("button", name="Reset Game", exact=True).click()
    expect(page.locator("#player1-tally .tally-slot").first).to_have_text("34")

    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Reset Game", exact=True).click()
    expect(page.locator("#player1-tally .tally-slot").first).to_have_text("-")
