from playwright.sync_api import Page, expect


def _create_game(live_server: str, page: Page) -> str:
    resp = page.request.post(
        f"{live_server}/api/squad-squabble/games/",
        data={"team1_name": "Devs", "team2_name": "Ops"},
    )
    assert resp.ok
    game_id: str = resp.json()["id"]
    return game_id


def test_lobby_create_game_button_navigates_to_control(
    live_server: str, page: Page
) -> None:
    page.goto(live_server)
    page.get_by_role("button", name="New Squad Squabble Game").click()
    page.wait_for_url("**/squad-squabble.html?id=*&view=control")
    expect(page.locator("#tab-control")).to_have_class("active")


def test_control_view_load_question_face_off_reveal(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    page.goto(f"{live_server}/squad-squabble.html?id={game_id}&view=control")

    # Question bank populated from the API
    expect(page.locator("#question-select option")).to_have_count(3)

    page.select_option("#multiplier-select", "2")
    page.get_by_role("button", name="Load", exact=True).click()

    # Reveal buttons should be disabled until a team has control
    first_reveal = page.locator("#answer-list button").first
    expect(first_reveal).to_be_disabled()

    page.get_by_role("button", name="Team 1 controls", exact=True).click()
    expect(first_reveal).to_be_enabled()

    first_reveal.click()

    # That answer row should now show "revealed" instead of a button
    expect(page.locator("#answer-list .answer-row").first).to_contain_text("revealed")
    expect(page.locator("#answer-list button")).to_have_count(4)  # 4 left, 1 revealed


def test_display_view_shows_revealed_answer_and_score(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)

    control = f"{live_server}/squad-squabble.html?id={game_id}&view=control"
    page.goto(control)
    page.select_option("#question-select", "desk-drawer")
    page.get_by_role("button", name="Load", exact=True).click()
    page.get_by_role("button", name="Team 1 controls", exact=True).click()
    page.locator("#answer-list button").first.click()

    # Now check the Display view reflects the reveal + score
    page.goto(f"{live_server}/squad-squabble.html?id={game_id}&view=display")
    expect(page.locator("#board .board-row").first).not_to_have_class("hidden-row")
    expect(page.locator("#board .board-row").first).to_contain_text("Tangled cables")
    expect(page.locator("#team1-score-display")).to_have_text("32")
    # Untouched answers still stay hidden on the big board
    expect(page.locator("#board .board-row").nth(1)).to_have_class(
        "board-row hidden-row"
    )


def test_strikes_and_steal_flow(live_server: str, page: Page) -> None:
    game_id = _create_game(live_server, page)
    page.goto(f"{live_server}/squad-squabble.html?id={game_id}&view=control")
    page.select_option("#question-select", "desk-drawer")
    page.get_by_role("button", name="Load", exact=True).click()
    page.get_by_role("button", name="Team 1 controls", exact=True).click()

    page.get_by_role("button", name="Add strike", exact=True).click()
    page.get_by_role("button", name="Add strike", exact=True).click()
    page.get_by_role("button", name="Add strike", exact=True).click()
    expect(page.locator("#strike-btn")).to_be_disabled()

    page.get_by_role("button", name="Team 2 steals remaining", exact=True).click()

    # All answers revealed after a steal, and team2 got the full board's points
    expect(page.locator("#answer-list .answer-row.revealed")).to_have_count(5)
