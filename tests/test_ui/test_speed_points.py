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


def _row(page: Page, i: int) -> None:
    """Wait for row i's quick-fill buttons (sourced from the async answer
    key fetch) to be present before interacting with them."""
    expect(page.locator(f"#quick-points-{i} button").first).to_be_visible()


def _lock_answer(page: Page, i: int, text: str) -> None:
    page.fill(f"#answer-input-{i}", text)
    page.locator(f"#answer-input-{i}").blur()
    page.locator(f"#answer-lock-btn-{i}").click()


def _lock_points(page: Page, i: int, points: int) -> None:
    page.fill(f"#points-input-{i}", str(points))
    page.locator(f"#points-input-{i}").blur()
    page.locator(f"#points-lock-btn-{i}").click()


def _award_and_lock(
    page: Page, i: int, *, text: str = "Actually...", points: int = 34
) -> None:
    _row(page, i)
    _lock_answer(page, i, text)
    page.locator(f"#points-input-{i}").fill(str(points))
    page.locator(f"#points-input-{i}").blur()
    _lock_points(page, i, points)


def _pass_and_lock(page: Page, i: int) -> None:
    _row(page, i)
    page.get_by_role("button", name="Pass", exact=True).nth(i).click()
    page.locator(f"#answer-lock-btn-{i}").click()
    page.locator(f"#points-lock-btn-{i}").click()


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
    expect(page.locator("#host-turn-status")).to_contain_text("0/5 scored")
    expect(page.locator("#host-timer")).to_contain_text("s")


def test_judge_view_shows_waiting_message_before_round_starts(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto_judge(live_server, page, game_id)
    expect(page.locator("#judge-no-round")).to_be_visible()
    expect(page.locator("#judge-rows")).to_be_hidden()


def test_judge_shows_all_five_questions_at_once(live_server: str, page: Page) -> None:
    game_id = _create_game(live_server, page)
    _goto_host(live_server, page, game_id)
    page.get_by_role("button", name="Start Player 1", exact=True).click()

    _goto_judge(live_server, page, game_id)
    rows = page.locator(".judge-row")
    expect(rows).to_have_count(5)
    expect(rows.nth(0)).to_contain_text("code review comment")
    expect(rows.nth(1)).to_contain_text("standup")


def test_quick_fill_prefills_points_editable_before_lock(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto_host(live_server, page, game_id)
    page.get_by_role("button", name="Start Player 1", exact=True).click()

    _goto_judge(live_server, page, game_id)
    _row(page, 0)
    page.get_by_role("button", name="Actually... (34)", exact=True).click()
    expect(page.locator("#points-input-0")).to_have_value("34")
    # Override before locking.
    page.fill("#points-input-0", "20")
    page.locator("#points-input-0").blur()
    expect(page.locator("#points-input-0")).to_have_value("20")


def test_answer_and_points_lock_independently_in_any_order(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto_host(live_server, page, game_id)
    page.get_by_role("button", name="Start Player 1", exact=True).click()

    _goto_judge(live_server, page, game_id)
    _row(page, 0)
    # Lock points on question 0 first, without locking the answer.
    page.fill("#points-input-0", "34")
    page.locator("#points-input-0").blur()
    page.locator("#points-lock-btn-0").click()
    expect(page.locator("#points-lock-btn-0")).to_have_text("Unlock Points")
    expect(page.locator("#answer-lock-btn-0")).to_have_text("Lock Answer")
    expect(page.locator("#points-input-0")).to_be_disabled()
    expect(page.locator("#answer-input-0")).to_be_enabled()

    # Now lock the answer for question 1 without touching its points.
    page.fill("#answer-input-1", "I was in meetings all day")
    page.locator("#answer-input-1").blur()
    page.locator("#answer-lock-btn-1").click()
    expect(page.locator("#answer-lock-btn-1")).to_have_text("Unlock Answer")
    expect(page.locator("#points-lock-btn-1")).to_have_text("Lock Points")


def test_editing_requires_unlocking_first(live_server: str, page: Page) -> None:
    game_id = _create_game(live_server, page)
    _goto_host(live_server, page, game_id)
    page.get_by_role("button", name="Start Player 1", exact=True).click()

    _goto_judge(live_server, page, game_id)
    _lock_answer(page, 0, "Actually...")
    expect(page.locator("#answer-input-0")).to_be_disabled()

    page.locator("#answer-lock-btn-0").click()  # unlock
    expect(page.locator("#answer-input-0")).to_be_enabled()
    expect(page.locator("#answer-input-0")).to_have_value("Actually...")


def test_any_question_index_workable_in_any_order(live_server: str, page: Page) -> None:
    game_id = _create_game(live_server, page)
    _goto_host(live_server, page, game_id)
    page.get_by_role("button", name="Start Player 1", exact=True).click()

    _goto_judge(live_server, page, game_id)
    # Award question 3 before question 0.
    _award_and_lock(page, 3, text="Blocked on review", points=18)
    expect(page.locator("#answer-lock-btn-3")).to_have_text("Unlock Answer")
    expect(page.locator("#answer-lock-btn-0")).to_have_text("Lock Answer")


def test_pass_prefills_and_locks_zero_points(live_server: str, page: Page) -> None:
    game_id = _create_game(live_server, page)
    _goto_host(live_server, page, game_id)
    page.get_by_role("button", name="Start Player 1", exact=True).click()

    _goto_judge(live_server, page, game_id)
    _pass_and_lock(page, 0)
    page.goto(f"{live_server}/speed-points.html?id={game_id}&view=main")
    expect(page.locator("#main-tallies")).to_contain_text("Pass")
    expect(page.locator("#main-tallies")).to_contain_text("0")


def test_buzzer_flags_duplicate_independently_of_answer_state(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto_host(live_server, page, game_id)
    page.get_by_role("button", name="Start Player 1", exact=True).click()

    _goto_judge(live_server, page, game_id)
    buzzer = page.locator("#buzzer-btn-0")
    expect(buzzer).to_have_text("Flag Duplicate")
    buzzer.click()
    expect(buzzer).to_have_class("buzzer-btn active")
    expect(buzzer).to_have_text("Duplicate flagged")


def test_completing_five_questions_shows_scored_progress(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto_host(live_server, page, game_id)
    page.get_by_role("button", name="Start Player 1", exact=True).click()

    _goto_judge(live_server, page, game_id)
    for i in range(5):
        _pass_and_lock(page, i)

    _goto_host(live_server, page, game_id)
    expect(page.locator("#host-turn-status")).to_contain_text("5/5 scored")
    expect(
        page.get_by_role("button", name="Start Player 2", exact=True)
    ).to_be_enabled()


def test_reveal_result_shows_verdict(live_server: str, page: Page) -> None:
    game_id = _create_game(live_server, page)
    _goto_host(live_server, page, game_id)
    page.get_by_role("button", name="Start Player 1", exact=True).click()

    _goto_judge(live_server, page, game_id)
    for i in range(5):
        _award_and_lock(page, i, points=50)

    _goto_host(live_server, page, game_id)
    page.get_by_role("button", name="Start Player 2", exact=True).click()

    _goto_judge(live_server, page, game_id)
    for i in range(5):
        _award_and_lock(page, i, points=50)

    _goto_host(live_server, page, game_id)
    page.get_by_role("button", name="Reveal Result", exact=True).click()

    page.goto(f"{live_server}/speed-points.html?id={game_id}&view=main")
    expect(page.locator("#verdict")).to_be_visible()
    expect(page.locator("#verdict")).to_contain_text("WINNER!")


def test_main_view_shows_no_answers_before_any_locked(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto_host(live_server, page, game_id)
    page.get_by_role("button", name="Start Player 1", exact=True).click()

    page.goto(f"{live_server}/speed-points.html?id={game_id}&view=main")
    expect(page.locator("#turn-main")).to_contain_text("Ada")
    expect(page.locator("body")).not_to_contain_text("Actually...")
    expect(page.locator("body")).not_to_contain_text("Nit:")


def test_main_view_reveals_answer_text_and_points_independently(
    live_server: str, page: Page
) -> None:
    """The two independent locks, as seen from the audience's screen: the
    judge's typed answer appears once the answer lock fires, the point
    value only appears once the (separate) points lock fires — and the
    canned answer-key options never appear at all."""
    game_id = _create_game(live_server, page)
    _goto_host(live_server, page, game_id)
    page.get_by_role("button", name="Start Player 1", exact=True).click()

    _goto_judge(live_server, page, game_id)
    _lock_answer(page, 0, "tangled cables from under the desk")

    page.goto(f"{live_server}/speed-points.html?id={game_id}&view=main")
    expect(page.locator("#main-tallies")).to_contain_text(
        "tangled cables from under the desk"
    )
    expect(page.locator("#main-tallies")).not_to_contain_text("34")
    expect(page.locator("body")).not_to_contain_text("Nit:")

    _goto_judge(live_server, page, game_id)
    _lock_points(page, 0, 34)

    page.goto(f"{live_server}/speed-points.html?id={game_id}&view=main")
    expect(page.locator("#main-tallies")).to_contain_text("34")


def test_main_view_player_columns_are_side_by_side(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    page.goto(f"{live_server}/speed-points.html?id={game_id}&view=main")
    expect(page.locator("#main-tallies")).to_have_css("flex-direction", "row")
    columns = page.locator(".player-column")
    expect(columns).to_have_count(2)


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
    _award_and_lock(page, 0, points=34)

    page.once("dialog", lambda dialog: dialog.dismiss())
    page.get_by_role("button", name="Reset Game", exact=True).click()
    expect(page.locator("#player1-tally .tally-slot").first).to_have_text("34")

    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Reset Game", exact=True).click()
    expect(page.locator("#judge-no-round")).to_be_visible()
