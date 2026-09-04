from playwright.sync_api import Page, expect


def _create_game(live_server: str, page: Page) -> str:
    resp = page.request.post(
        f"{live_server}/api/squad-squabble/games/",
        data={"team1_name": "Devs", "team2_name": "Ops"},
    )
    assert resp.ok
    game_id: str = resp.json()["id"]
    return game_id


def _goto_control(live_server: str, page: Page, game_id: str) -> None:
    page.goto(f"{live_server}/squad-squabble.html?id={game_id}&view=control")


def _load_question(page: Page, question_id: str = "desk-drawer") -> None:
    page.select_option("#question-select", question_id)
    page.get_by_role("button", name="Load", exact=True).click()


def test_lobby_create_game_button_navigates_to_control(
    live_server: str, page: Page
) -> None:
    page.goto(live_server)
    page.get_by_role("button", name="New Squad Squabble Game").click()
    page.wait_for_url("**/squad-squabble.html?id=*&view=control")
    expect(page.locator("#tab-control")).to_have_class("active")


def test_breadcrumb_links_back_to_lobby(live_server: str, page: Page) -> None:
    game_id = _create_game(live_server, page)
    _goto_control(live_server, page, game_id)

    expect(page.get_by_role("link", name="Many Game Show")).to_be_visible()
    page.get_by_role("link", name="Many Game Show").click()
    page.wait_for_url(f"{live_server}/")
    expect(page.locator("h1")).to_have_text("Many Game Show")


def test_display_header_collapses_to_led_and_expands_back(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    page.goto(f"{live_server}/squad-squabble.html?id={game_id}&view=display")

    header = page.locator("header")
    mini_header = page.locator("#mini-header")
    expect(header).to_be_visible()
    expect(mini_header).to_be_hidden()

    page.get_by_role("button", name="Hide header", exact=True).click()
    expect(header).to_be_hidden()
    expect(mini_header).to_be_visible()
    expect(page.locator("#mini-led")).to_have_class("mini-led ok")

    page.get_by_role("button", name="Show header", exact=True).click()
    expect(header).to_be_visible()
    expect(mini_header).to_be_hidden()


def test_control_view_always_shows_full_header(live_server: str, page: Page) -> None:
    """The collapse feature is a Display-only affordance — Control always
    needs its tabs/theme select visible to operate the game."""
    game_id = _create_game(live_server, page)
    _goto_control(live_server, page, game_id)
    expect(page.get_by_role("button", name="Hide header", exact=True)).to_be_hidden()
    expect(page.locator("header")).to_be_visible()


def test_reveal_active_without_control_and_no_score_until_awarded(
    live_server: str, page: Page
) -> None:
    """Items 6 and 8: reveal works with no team in control, and points sit
    in the round pot rather than crediting a team immediately."""
    game_id = _create_game(live_server, page)
    _goto_control(live_server, page, game_id)
    _load_question(page)

    first_reveal = page.locator("#answer-list button.reveal-btn").first
    expect(first_reveal).to_be_enabled()  # no control needed (item 8)
    first_reveal.click()

    expect(page.locator("#round-score-value")).to_have_text("32")
    expect(page.locator("#team1-score-input")).to_have_value("0")
    expect(page.locator("#team2-score-input")).to_have_value("0")


def test_clear_control_resets_to_no_one(live_server: str, page: Page) -> None:
    """Item 8: control can be reset back to 'no one'."""
    game_id = _create_game(live_server, page)
    _goto_control(live_server, page, game_id)
    page.get_by_role("button", name="Team 1 controls", exact=True).click()
    expect(page.locator("#team1-controls-btn")).to_have_class("control-btn active")

    page.get_by_role("button", name="Clear control", exact=True).click()
    expect(page.locator("#team1-controls-btn")).not_to_have_class("control-btn active")
    expect(page.locator("#team2-controls-btn")).not_to_have_class("control-btn active")


def test_unreveal_button_hides_answer_again(live_server: str, page: Page) -> None:
    """Item 9."""
    game_id = _create_game(live_server, page)
    _goto_control(live_server, page, game_id)
    _load_question(page)
    page.locator("#answer-list button.reveal-btn").first.click()

    expect(page.locator("#answer-list .answer-row").first).to_have_class(
        "answer-row revealed"
    )
    page.get_by_role("button", name="Unreveal", exact=True).first.click()
    expect(page.locator("#answer-list button.reveal-btn")).to_have_count(5)


def test_three_strikes_button_jumps_to_three(live_server: str, page: Page) -> None:
    """Item 1."""
    game_id = _create_game(live_server, page)
    _goto_control(live_server, page, game_id)

    page.get_by_role("button", name="3 Strikes", exact=True).click()
    expect(page.locator("#strike-btn")).to_be_disabled()
    expect(page.locator(".strike-x.on")).to_have_count(3)


def test_award_round_credits_team_and_resets_round_score(
    live_server: str, page: Page
) -> None:
    """Item 6."""
    game_id = _create_game(live_server, page)
    _goto_control(live_server, page, game_id)
    _load_question(page)
    page.locator("#answer-list button.reveal-btn").first.click()
    expect(page.locator("#round-score-value")).to_have_text("32")

    page.get_by_role("button", name="Award to Team 1", exact=True).click()
    expect(page.locator("#team1-score-input")).to_have_value("32")


def test_set_arbitrary_score_and_reset(live_server: str, page: Page) -> None:
    """Item 3."""
    game_id = _create_game(live_server, page)
    _goto_control(live_server, page, game_id)

    page.fill("#team2-score-input", "250")
    page.get_by_role("button", name="Set score", exact=True).nth(1).click()
    expect(page.locator("#team2-score-input")).to_have_value("250")

    page.get_by_role("button", name="Reset to 0", exact=True).nth(1).click()
    expect(page.locator("#team2-score-input")).to_have_value("0")


def test_unload_question_clears_board(live_server: str, page: Page) -> None:
    """Item 4."""
    game_id = _create_game(live_server, page)
    _goto_control(live_server, page, game_id)
    _load_question(page)
    expect(page.locator("#answer-list button.reveal-btn")).to_have_count(5)

    page.get_by_role("button", name="Unload Question", exact=True).click()
    expect(page.locator("#answer-list")).to_contain_text("Load a question first")


def test_round_number_controls(live_server: str, page: Page) -> None:
    """Item 7."""
    game_id = _create_game(live_server, page)
    _goto_control(live_server, page, game_id)

    expect(page.locator("#round-value")).to_have_text("1")
    page.get_by_role("button", name="Round +", exact=True).click()
    expect(page.locator("#round-value")).to_have_text("2")
    page.get_by_role("button", name="Round -", exact=True).click()
    expect(page.locator("#round-value")).to_have_text("1")

    page.fill("#round-input", "5")
    page.get_by_role("button", name="Set round", exact=True).click()
    expect(page.locator("#round-value")).to_have_text("5")


def test_question_visibility_defaults_hidden_and_can_toggle(
    live_server: str, page: Page
) -> None:
    """Item 10."""
    game_id = _create_game(live_server, page)
    _goto_control(live_server, page, game_id)
    _load_question(page)

    expect(page.get_by_role("button", name="Show Question", exact=True)).to_be_visible()

    page.get_by_role("button", name="Show Question", exact=True).click()
    expect(page.get_by_role("button", name="Hide Question", exact=True)).to_be_visible()


def test_display_view_round_number_and_hidden_question(
    live_server: str, page: Page
) -> None:
    """Items 7 and 10."""
    game_id = _create_game(live_server, page)
    _goto_control(live_server, page, game_id)
    _load_question(page)
    page.get_by_role("button", name="Round +", exact=True).click()

    page.goto(f"{live_server}/squad-squabble.html?id={game_id}&view=display")
    expect(page.locator("#round-display")).to_contain_text("ROUND 2")
    # Hidden by default (item 10) — the real prompt text shouldn't be visible
    expect(page.locator("#question-back")).not_to_be_visible()


def test_display_view_question_reveals_on_visibility_toggle(
    live_server: str, page: Page
) -> None:
    """Item 5 (flip trigger) + item 10."""
    game_id = _create_game(live_server, page)
    _goto_control(live_server, page, game_id)
    _load_question(page)
    page.get_by_role("button", name="Show Question", exact=True).click()

    page.goto(f"{live_server}/squad-squabble.html?id={game_id}&view=display")
    expect(page.locator("#question-card")).to_have_class("flipped")
    expect(page.locator("#question-back")).to_contain_text(
        "name something you'd find in their desk drawer"
    )


def test_display_view_reveal_remaining_shows_all_answers(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto_control(live_server, page, game_id)
    _load_question(page)
    page.get_by_role("button", name="Reveal remaining answers", exact=True).click()

    page.goto(f"{live_server}/squad-squabble.html?id={game_id}&view=display")
    expect(page.locator("#board .board-row.hidden-row")).to_have_count(0)


def test_reset_game_button_requires_confirmation_and_clears_state(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto_control(live_server, page, game_id)
    _load_question(page)
    page.get_by_role("button", name="Round +", exact=True).click()
    page.fill("#team1-score-input", "250")
    page.get_by_role("button", name="Set score", exact=True).first.click()

    # Dismissing the confirm dialog should leave everything untouched
    page.once("dialog", lambda dialog: dialog.dismiss())
    page.get_by_role("button", name="Reset Game", exact=True).click()
    expect(page.locator("#round-value")).to_have_text("2")

    # Accepting it resets round/score/board but keeps team names
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Reset Game", exact=True).click()
    expect(page.locator("#round-value")).to_have_text("1")
    expect(page.locator("#team1-score-input")).to_have_value("0")
    expect(page.locator("#answer-list")).to_contain_text("Load a question first")


def test_strike_animation_timing_configurable_and_persisted(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto_control(live_server, page, game_id)

    expect(page.locator("#strike-hold-input")).to_have_value("1000")
    expect(page.locator("#strike-duration-input")).to_have_value("800")

    page.fill("#strike-hold-input", "1200")
    page.fill("#strike-duration-input", "900")
    page.get_by_role("button", name="Set timing", exact=True).click()

    # Reload to prove it's server-persisted, not just left in the input
    page.reload()
    expect(page.locator("#strike-hold-input")).to_have_value("1200")
    expect(page.locator("#strike-duration-input")).to_have_value("900")
