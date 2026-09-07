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


def _award_and_reveal(page: Page, *, no_match: bool = False) -> None:
    if no_match:
        page.get_by_role("button", name="No match (0)", exact=True).click()
    else:
        page.locator("#answer-options button.award-btn").first.click()
    page.get_by_role("button", name="Reveal Points", exact=True).click()


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


def test_award_locks_in_text_but_does_not_advance(live_server: str, page: Page) -> None:
    """First reveal beat: picking a match shows immediately (as pending),
    but doesn't move on until points are separately revealed."""
    game_id = _create_game(live_server, page)
    _goto_control(live_server, page, game_id)
    page.get_by_role("button", name="Start Player 1", exact=True).click()

    page.locator("#answer-options button.award-btn").first.click()
    expect(page.get_by_role("button", name="Reveal Points", exact=True)).to_be_visible()
    expect(page.locator("#current-prompt")).to_contain_text("code review comment")
    expect(page.locator("#player1-tally .tally-slot").first).to_have_class(
        "tally-slot pending"
    )


def test_reveal_points_shows_points_and_advances_question(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto_control(live_server, page, game_id)
    page.get_by_role("button", name="Start Player 1", exact=True).click()

    _award_and_reveal(page)
    expect(page.locator("#player1-tally .tally-slot").first).to_have_text("34")
    expect(page.locator("#current-prompt")).to_contain_text("standup")


def test_no_match_button_awards_zero(live_server: str, page: Page) -> None:
    game_id = _create_game(live_server, page)
    _goto_control(live_server, page, game_id)
    page.get_by_role("button", name="Start Player 1", exact=True).click()

    _award_and_reveal(page, no_match=True)
    expect(page.locator("#player1-tally .tally-slot").first).to_have_text("0")


def test_completing_five_questions_shows_start_player2(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto_control(live_server, page, game_id)
    page.get_by_role("button", name="Start Player 1", exact=True).click()

    for _ in range(5):
        _award_and_reveal(page, no_match=True)

    expect(page.locator("#current-prompt")).to_contain_text("No question in play")
    expect(
        page.get_by_role("button", name="Start Player 2", exact=True)
    ).to_be_enabled()


def test_reveal_result_shows_verdict(live_server: str, page: Page) -> None:
    game_id = _create_game(live_server, page)
    _goto_control(live_server, page, game_id)

    page.get_by_role("button", name="Start Player 1", exact=True).click()
    for _ in range(5):
        _award_and_reveal(page)
    page.get_by_role("button", name="Start Player 2", exact=True).click()
    for _ in range(5):
        _award_and_reveal(page)

    page.get_by_role("button", name="Reveal Result", exact=True).click()

    # The verdict banner is a Main/Display-only affordance (the big screen
    # the audience watches) — Control just has the button that triggers it.
    # Always clicking the first (highest-value) answer option for every
    # question clears the 200-point threshold, whatever the exact total is.
    page.goto(f"{live_server}/speed-points.html?id={game_id}&view=display")
    expect(page.locator("#verdict")).to_be_visible()
    expect(page.locator("#verdict")).to_contain_text("WINNER!")


def test_display_view_shows_prompt_and_no_answer_yet(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto_control(live_server, page, game_id)
    page.get_by_role("button", name="Start Player 1", exact=True).click()

    page.goto(f"{live_server}/speed-points.html?id={game_id}&view=display")
    expect(page.locator("#display-prompt")).to_contain_text("code review comment")
    # Nothing chosen yet -> none of the answer-key text should be visible.
    expect(page.locator("body")).not_to_contain_text("Actually...")
    expect(page.locator("body")).not_to_contain_text("Nit:")


def test_display_view_reveals_answer_text_before_points(
    live_server: str, page: Page
) -> None:
    """The two-step reveal, as seen from the audience's screen: the chosen
    answer's text appears as soon as the host picks it, but the point
    value only appears after the separate Reveal Points action — and the
    other (non-chosen) answer-key options never appear at all."""
    game_id = _create_game(live_server, page)
    _goto_control(live_server, page, game_id)
    page.get_by_role("button", name="Start Player 1", exact=True).click()
    page.locator("#answer-options button.award-btn").first.click()

    page.goto(f"{live_server}/speed-points.html?id={game_id}&view=display")
    expect(page.locator("#display-tallies")).to_contain_text("Actually...")
    expect(page.locator("#display-tallies")).not_to_contain_text("34")
    expect(page.locator("body")).not_to_contain_text("Nit:")

    _goto_control(live_server, page, game_id)
    page.get_by_role("button", name="Reveal Points", exact=True).click()

    page.goto(f"{live_server}/speed-points.html?id={game_id}&view=display")
    expect(page.locator("#display-tallies")).to_contain_text("Actually...")
    expect(page.locator("#display-tallies")).to_contain_text("34")


def test_display_view_player_tallies_are_vertical(live_server: str, page: Page) -> None:
    game_id = _create_game(live_server, page)
    page.goto(f"{live_server}/speed-points.html?id={game_id}&view=display")
    expect(page.locator("#display-tallies .tally-slots").first).to_have_css(
        "flex-direction", "column"
    )


def test_reset_game_requires_confirmation_and_clears_state(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto_control(live_server, page, game_id)
    page.get_by_role("button", name="Start Player 1", exact=True).click()
    _award_and_reveal(page)

    page.once("dialog", lambda dialog: dialog.dismiss())
    page.get_by_role("button", name="Reset Game", exact=True).click()
    expect(page.locator("#player1-tally .tally-slot").first).to_have_text("34")

    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Reset Game", exact=True).click()
    expect(page.locator("#player1-tally .tally-slot").first).to_have_text("-")
