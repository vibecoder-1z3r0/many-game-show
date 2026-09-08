from playwright.sync_api import Page, expect


def _create_game(live_server: str, page: Page) -> str:
    resp = page.request.post(
        f"{live_server}/api/speed-points/games/",
        data={"player1_name": "Ada", "player2_name": "Grace"},
    )
    assert resp.ok
    game_id: str = resp.json()["id"]
    return game_id


def _goto_host(live_server: str, page: Page, game_id: str) -> None:
    page.goto(f"{live_server}/speed-points.html?id={game_id}&view=host")


def _goto_judge(live_server: str, page: Page, game_id: str) -> None:
    page.goto(f"{live_server}/speed-points.html?id={game_id}&view=judge")


def _wait_for_options_ready(page: Page) -> None:
    # After a question transition, #answer-options gets rebuilt once the
    # new question's options finish loading — a real judge reads the new
    # question before answering it, so wait for that same settle point
    # rather than clicking mid-rebuild (which a bare .click() can lose).
    # Button *count* alone can't distinguish "options" from "still showing
    # the previous question's options" — every question has exactly 5 +
    # no-match — so wait for the app's own freshness marker instead:
    # #answer-options[data-ready] only equals the current question's id
    # once its options have actually finished (re)loading.
    qid = page.locator("#current-prompt").get_attribute("data-question-id")
    expect(page.locator("#answer-options")).to_have_attribute("data-ready", qid or "")


def _type_and_award(page: Page, text: str = "Actually cables") -> None:
    _wait_for_options_ready(page)
    page.fill("#judge-answer-input", text)
    page.locator("#answer-options button.award-btn").first.click()


def _award_and_reveal(page: Page, *, no_match: bool = False, text: str = "x") -> None:
    _wait_for_options_ready(page)
    prev_qid = page.locator("#current-prompt").get_attribute("data-question-id")
    if no_match:
        page.fill("#judge-answer-input", "")
        page.get_by_role("button", name="No match (0)", exact=True).click()
    else:
        page.fill("#judge-answer-input", text)
        page.locator("#answer-options button.award-btn").first.click()
    page.get_by_role("button", name="Reveal Points", exact=True).click()
    # Wait for the transition to the next question (or round end) to
    # actually land, and its options (if any) to be fresh, before
    # returning — otherwise the *next* call's readiness wait could pass
    # instantly against stale leftover data instead of genuinely waiting.
    expect(page.locator("#current-prompt")).not_to_have_attribute(
        "data-question-id", prev_qid or ""
    )
    _wait_for_options_ready(page)


def test_lobby_create_speed_points_button_navigates_to_host(
    live_server: str, page: Page
) -> None:
    page.goto(live_server)
    page.get_by_role("button", name="New Speed Points Game").click()
    page.wait_for_url("**/speed-points.html?id=*&view=host")
    expect(page.locator("#tab-host")).to_have_class("active")


def test_host_view_shows_full_question_rundown_and_no_answers(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto_host(live_server, page, game_id)

    items = page.locator("#host-question-list li")
    expect(items).to_have_count(5)
    expect(items.nth(0)).to_contain_text("code review comment")
    expect(items.nth(1)).to_contain_text("standup")
    # No answer/points content anywhere on Host.
    expect(page.locator("body")).not_to_contain_text("Actually...")
    expect(page.locator("body")).not_to_contain_text("34 pts")


def test_host_can_start_the_clock(live_server: str, page: Page) -> None:
    game_id = _create_game(live_server, page)
    _goto_host(live_server, page, game_id)

    page.get_by_role("button", name="Start Player 1", exact=True).click()
    expect(page.locator("#host-turn-status")).to_contain_text("Ada")
    expect(page.locator("#host-timer")).to_contain_text("s")
    expect(page.locator("#host-question-list li").first).to_have_class(
        "current-question"
    )


def test_judge_view_has_no_start_round_or_rundown_controls(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto_judge(live_server, page, game_id)
    expect(page.get_by_role("button", name="Start Player 1")).to_be_hidden()
    expect(page.locator("#host-question-list")).to_be_hidden()


def test_judge_types_answer_and_awards_from_options(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto_host(live_server, page, game_id)
    page.get_by_role("button", name="Start Player 1", exact=True).click()

    _goto_judge(live_server, page, game_id)
    page.fill("#judge-answer-input", "tangled cables")
    page.locator("#answer-options button.award-btn").first.click()

    expect(page.get_by_role("button", name="Reveal Points", exact=True)).to_be_visible()
    page.get_by_role("button", name="Reveal Points", exact=True).click()
    expect(page.locator("#player1-tally .tally-slot").first).to_have_text("34")


def test_award_requires_typed_answer_first(live_server: str, page: Page) -> None:
    game_id = _create_game(live_server, page)
    _goto_host(live_server, page, game_id)
    page.get_by_role("button", name="Start Player 1", exact=True).click()

    _goto_judge(live_server, page, game_id)
    page.locator("#answer-options button.award-btn").first.click()
    expect(page.locator("#judge-status-line")).to_contain_text(
        "Type the contestant's answer"
    )
    expect(page.get_by_role("button", name="Reveal Points")).to_have_count(0)


def test_no_match_works_without_typed_text(live_server: str, page: Page) -> None:
    game_id = _create_game(live_server, page)
    _goto_host(live_server, page, game_id)
    page.get_by_role("button", name="Start Player 1", exact=True).click()

    _goto_judge(live_server, page, game_id)
    page.get_by_role("button", name="No match (0)", exact=True).click()
    page.get_by_role("button", name="Reveal Points", exact=True).click()
    expect(page.locator("#player1-tally .tally-slot").first).to_have_text("0")


def test_buzzer_toggles_independently_of_typing(live_server: str, page: Page) -> None:
    game_id = _create_game(live_server, page)
    _goto_host(live_server, page, game_id)
    page.get_by_role("button", name="Start Player 1", exact=True).click()

    _goto_judge(live_server, page, game_id)
    buzzer = page.locator("#buzzer-btn")
    expect(buzzer).to_have_text("Flag Duplicate")
    buzzer.click()
    expect(buzzer).to_have_class("buzzer-btn active")
    expect(buzzer).to_contain_text("flagged")


def test_completing_five_questions_shows_start_player2(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto_host(live_server, page, game_id)
    page.get_by_role("button", name="Start Player 1", exact=True).click()

    _goto_judge(live_server, page, game_id)
    for _ in range(5):
        _award_and_reveal(page, no_match=True)
    expect(page.locator("#current-prompt")).to_contain_text("No question in play")

    _goto_host(live_server, page, game_id)
    expect(
        page.get_by_role("button", name="Start Player 2", exact=True)
    ).to_be_enabled()


def test_reveal_result_shows_verdict(live_server: str, page: Page) -> None:
    game_id = _create_game(live_server, page)
    _goto_host(live_server, page, game_id)
    page.get_by_role("button", name="Start Player 1", exact=True).click()

    _goto_judge(live_server, page, game_id)
    for _ in range(5):
        _award_and_reveal(page)

    _goto_host(live_server, page, game_id)
    page.get_by_role("button", name="Start Player 2", exact=True).click()

    _goto_judge(live_server, page, game_id)
    for _ in range(5):
        _award_and_reveal(page)

    _goto_host(live_server, page, game_id)
    page.get_by_role("button", name="Reveal Result", exact=True).click()

    # The verdict banner is a Main/Display-only affordance (the big screen
    # the audience watches) — Host just has the button that triggers it.
    # Always clicking the first (highest-value) answer option for every
    # question clears the 200-point threshold, whatever the exact total is.
    page.goto(f"{live_server}/speed-points.html?id={game_id}&view=display")
    expect(page.locator("#verdict")).to_be_visible()
    expect(page.locator("#verdict")).to_contain_text("WINNER!")


def test_display_view_shows_prompt_and_no_answer_yet(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto_host(live_server, page, game_id)
    page.get_by_role("button", name="Start Player 1", exact=True).click()

    page.goto(f"{live_server}/speed-points.html?id={game_id}&view=display")
    expect(page.locator("#display-prompt")).to_contain_text("code review comment")
    # Nothing chosen yet -> none of the answer-key text should be visible.
    expect(page.locator("body")).not_to_contain_text("Actually...")
    expect(page.locator("body")).not_to_contain_text("Nit:")


def test_display_view_reveals_typed_answer_before_points(
    live_server: str, page: Page
) -> None:
    """The two-step reveal, as seen from the audience's screen: what the
    judge typed appears as soon as they lock in a match, but the point
    value only appears after the separate Reveal Points action — and the
    canned answer-key options never appear at all."""
    game_id = _create_game(live_server, page)
    _goto_host(live_server, page, game_id)
    page.get_by_role("button", name="Start Player 1", exact=True).click()

    _goto_judge(live_server, page, game_id)
    _type_and_award(page, "tangled cables from under the desk")

    page.goto(f"{live_server}/speed-points.html?id={game_id}&view=display")
    expect(page.locator("#display-tallies")).to_contain_text(
        "tangled cables from under the desk"
    )
    expect(page.locator("#display-tallies")).not_to_contain_text("34")
    expect(page.locator("body")).not_to_contain_text("Nit:")

    _goto_judge(live_server, page, game_id)
    page.get_by_role("button", name="Reveal Points", exact=True).click()

    page.goto(f"{live_server}/speed-points.html?id={game_id}&view=display")
    expect(page.locator("#display-tallies")).to_contain_text("34")


def test_display_view_player_tallies_are_vertical(live_server: str, page: Page) -> None:
    game_id = _create_game(live_server, page)
    page.goto(f"{live_server}/speed-points.html?id={game_id}&view=display")
    expect(page.locator("#display-tallies .tally-slots").first).to_have_css(
        "flex-direction", "column"
    )


def test_reset_game_is_on_judge_not_host(live_server: str, page: Page) -> None:
    game_id = _create_game(live_server, page)
    _goto_host(live_server, page, game_id)
    expect(page.get_by_role("button", name="Reset Game")).to_be_hidden()

    _goto_judge(live_server, page, game_id)
    expect(page.get_by_role("button", name="Reset Game", exact=True)).to_be_visible()


def test_reset_game_requires_confirmation_and_clears_state(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto_host(live_server, page, game_id)
    page.get_by_role("button", name="Start Player 1", exact=True).click()

    _goto_judge(live_server, page, game_id)
    _award_and_reveal(page)

    page.once("dialog", lambda dialog: dialog.dismiss())
    page.get_by_role("button", name="Reset Game", exact=True).click()
    expect(page.locator("#player1-tally .tally-slot").first).to_have_text("34")

    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Reset Game", exact=True).click()
    expect(page.locator("#player1-tally .tally-slot").first).to_have_text("-")


def test_pass_records_distinct_from_no_match(live_server: str, page: Page) -> None:
    """A contestant who says nothing (Pass) should read differently from
    one who guessed something not on the board (No match) — both score 0,
    but the reveal text should tell the two apart."""
    game_id = _create_game(live_server, page)
    _goto_host(live_server, page, game_id)
    page.get_by_role("button", name="Start Player 1", exact=True).click()

    _goto_judge(live_server, page, game_id)
    page.get_by_role("button", name="Pass", exact=True).click()
    page.get_by_role("button", name="Reveal Points", exact=True).click()
    expect(page.locator("#player1-tally .tally-slot").first).to_have_text("0")

    page.goto(f"{live_server}/speed-points.html?id={game_id}&view=display")
    expect(page.locator("#display-tallies")).to_contain_text("Pass")


def test_pass_works_even_with_typed_text(live_server: str, page: Page) -> None:
    """Pass always records as a pass, ignoring anything left in the input
    (e.g. a partial note the judge was jotting down)."""
    game_id = _create_game(live_server, page)
    _goto_host(live_server, page, game_id)
    page.get_by_role("button", name="Start Player 1", exact=True).click()

    _goto_judge(live_server, page, game_id)
    page.fill("#judge-answer-input", "something they mumbled")
    page.get_by_role("button", name="Pass", exact=True).click()
    page.get_by_role("button", name="Reveal Points", exact=True).click()

    page.goto(f"{live_server}/speed-points.html?id={game_id}&view=display")
    expect(page.locator("#display-tallies")).to_contain_text("Pass")
    expect(page.locator("#display-tallies")).not_to_contain_text(
        "something they mumbled"
    )
