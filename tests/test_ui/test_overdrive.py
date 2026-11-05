import re

from playwright.sync_api import Page, expect


def _create_game(live_server: str, page: Page, *, game_defaults: bool = False) -> str:
    """Create a game. The ring-in window opens 2.5s after a reveal by
    default, which would make every test that rings in wait that long, so
    tests get a short start delay unless they ask for the real defaults."""
    resp = page.request.post(f"{live_server}/api/overdrive/games/", data={})
    assert resp.ok
    game_id: str = resp.json()["id"]
    if not game_defaults:
        resp = page.request.patch(
            f"{live_server}/api/overdrive/games/{game_id}/ring-in-settings",
            data={"start_delay_ms": 300},
        )
        assert resp.ok
    return game_id


def _goto(live_server: str, page: Page, game_id: str, view: str) -> None:
    page.goto(f"{live_server}/overdrive.html?id={game_id}&view={view}")


def _open_setup(page: Page) -> None:
    """Content and Timing are collapsed on Control; expand them to edit."""
    page.evaluate(
        "document.querySelectorAll('details.setup-details')"
        ".forEach((d) => { d.open = true; })"
    )


def _select_clue(page: Page, category_index: int, clue_index: int) -> None:
    # Control and Host each have a board in the DOM; click the visible one.
    page.locator(
        f'.clue-cell[onclick="selectClue({category_index}, {clue_index})"]:visible'
    ).first.click()


def _reveal_clue(page: Page) -> None:
    page.get_by_role("button", name="Reveal Clue").click()


def _buzz(page: Page, player: str) -> None:
    # Every player section is rendered in the DOM at once (only one is
    # shown via CSS); scope to the active player's own section so we
    # don't grab another player's hidden button.
    page.click(f"#{player}-body .buzz-btn")


def _wait_for_ring_in_open(live_server: str, page: Page, game_id: str) -> None:
    for _ in range(100):
        resp = page.request.get(f"{live_server}/api/overdrive/games/{game_id}")
        players = resp.json()["players"]
        if any(p["can_ring_in"] for p in players.values()):
            return
        page.wait_for_timeout(20)
    raise AssertionError("ring-in window never opened")


def test_lobby_create_overdrive_button_navigates_to_control(
    live_server: str, page: Page
) -> None:
    page.goto(live_server)
    page.get_by_role("button", name="New Overdrive Game").click()
    page.get_by_role("button", name="Create game").click()
    page.wait_for_url("**/overdrive.html?id=*&view=control")
    expect(page.locator("#tab-control")).to_have_class("active")


def test_lobby_dialog_lists_all_sample_banks_and_creates_with_the_choices(
    live_server: str, page: Page
) -> None:
    page.goto(live_server)
    page.get_by_role("button", name="New Overdrive Game").click()
    expect(page.locator("#new-game-round1_bank_id option")).to_have_count(3)
    expect(page.locator("#new-game-round2_bank_id option")).to_have_count(3)
    expect(page.locator("#new-game-final_bank_id option")).to_have_count(5)

    page.select_option("#new-game-round1_bank_id", "movies")
    page.get_by_role("button", name="Create game").click()
    page.wait_for_url("**/overdrive.html?id=*&view=control")
    game_id = page.url.split("id=")[1].split("&")[0]
    control = page.request.get(
        f"{live_server}/api/overdrive/games/{game_id}/control"
    ).json()
    assert control["categories"][0]["name"] == "Blockbusters"


def test_control_shows_board_and_all_three_players(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto(live_server, page, game_id, "control")
    expect(page.locator("#control-board .clue-cell")).to_have_count(30)
    expect(page.locator("#control-players .control-player-row")).to_have_count(3)


def test_category_header_click_reveals_and_hides_directly(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto(live_server, page, game_id, "control")

    flip = page.locator("#control-board-headers .cat-header-flip").nth(1)
    front = flip.locator(".cat-header-front")
    back = flip.locator(".cat-header-back")
    # Control sees the real name on the greyed (unrevealed) face.
    expect(front).to_contain_text("HTTP Status Quo")
    expect(front).to_have_class(re.compile("hidden-cat"))
    expect(flip).not_to_have_class(re.compile("flipped"))

    flip.click()
    expect(back).to_contain_text("HTTP Status Quo")
    expect(flip).to_have_class(re.compile("flipped"))

    flip.click()
    expect(front).to_contain_text("HTTP Status Quo")
    expect(flip).not_to_have_class(re.compile("flipped"))


def test_board_values_show_as_plain_points_no_dollar_sign(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto(live_server, page, game_id, "control")

    cell = page.locator('#control-board .clue-cell[onclick="selectClue(1, 0)"]')
    expect(cell).to_have_text("200")
    expect(page.locator("#control-board")).not_to_contain_text("$")


def test_player_view_only_shows_their_own_controls(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto(live_server, page, game_id, "player1")

    body = page.locator("#player1-body")
    expect(body).to_contain_text("Player 1")
    expect(body.locator(".clue-cell")).to_have_count(0)
    expect(body.locator(".player-card")).to_have_count(0)


def test_main_overlay_shows_only_clue_text_when_revealed(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto(live_server, page, game_id, "control")

    _select_clue(page, 1, 0)
    _reveal_clue(page)

    _goto(live_server, page, game_id, "main")
    overlay = page.locator("#clue-overlay")
    expect(overlay.locator(".overlay-text-big")).to_contain_text(
        "This status code means the request succeeded."
    )
    expect(overlay.locator(".overlay-value")).to_have_count(0)
    expect(overlay.locator(".overlay-category")).to_have_count(0)


def test_main_status_bar_shows_buzzed_player_name_and_timer(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto(live_server, page, game_id, "control")

    _select_clue(page, 1, 0)
    _reveal_clue(page)

    _goto(live_server, page, game_id, "main")
    bar = page.locator("#clue-status-bar")
    expect(bar).to_be_visible()
    expect(bar).not_to_contain_text("Player 1")
    expect(bar.locator(".countdown-track")).to_have_count(1)

    _goto(live_server, page, game_id, "player1")
    _wait_for_ring_in_open(live_server, page, game_id)
    _buzz(page, "player1")

    _goto(live_server, page, game_id, "main")
    expect(bar).to_be_visible()
    expect(bar).to_contain_text("Player 1")
    expect(bar.locator(".countdown-track")).to_have_count(1)


def test_control_can_rename_a_player(live_server: str, page: Page) -> None:
    game_id = _create_game(live_server, page)
    _goto(live_server, page, game_id, "control")

    page.fill("#rename-input-player1", "Ada")
    page.get_by_role("button", name="Rename").first.click()
    expect(page.locator("#control-players")).to_contain_text("Ada")

    _goto(live_server, page, game_id, "main")
    expect(page.locator("#main-scoreboard")).to_contain_text("Ada")


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
    expect(page.locator("#control-clue-status .live-player.has-floor")).to_contain_text(
        "Player 1"
    )
    page.get_by_role("button", name="Correct", exact=True).click()

    expect(page.locator("#control-players")).to_contain_text("200")
    expect(page.locator("#control-round-status")).to_contain_text(
        "Board control: Player 1"
    )
    # The clue is consumed and the fieldset closes.
    expect(page.locator("#control-clue-fieldset")).to_be_hidden()


def _get_state(live_server: str, page: Page, game_id: str) -> dict:
    return page.request.get(f"{live_server}/api/overdrive/games/{game_id}").json()


def test_answer_timer_play_pause_stop_reset_clear(live_server: str, page: Page) -> None:
    game_id = _create_game(live_server, page)
    _goto(live_server, page, game_id, "control")

    _select_clue(page, 1, 0)
    _reveal_clue(page)

    _goto(live_server, page, game_id, "player1")
    _wait_for_ring_in_open(live_server, page, game_id)
    _buzz(page, "player1")

    _goto(live_server, page, game_id, "control")
    clue_status = page.locator("#control-clue-status")

    # Pause freezes the remaining time in place. Wait for the button
    # swap (Play appearing) to know the pause has actually landed
    # server-side before reading "frozen" — otherwise this races the
    # click's own in-flight request.
    clue_status.get_by_role("button", name="Pause", exact=True).click()
    expect(clue_status.get_by_role("button", name="Play", exact=True)).to_be_visible()
    frozen = _get_state(live_server, page, game_id)["buzz_remaining_ms"]
    page.wait_for_timeout(250)
    assert _get_state(live_server, page, game_id)["buzz_remaining_ms"] == frozen

    # Play resumes counting down from there.
    clue_status.get_by_role("button", name="Play", exact=True).click()
    expect(clue_status.get_by_role("button", name="Pause", exact=True)).to_be_visible()

    # Stop zeroes it out and pauses. Waiting for the Play button to
    # reappear confirms the stop has landed server-side before reading.
    clue_status.get_by_role("button", name="Stop", exact=True).click()
    expect(clue_status.get_by_role("button", name="Play", exact=True)).to_be_visible()
    stopped = _get_state(live_server, page, game_id)
    assert stopped["buzz_remaining_ms"] == 0
    assert stopped["answer_timer_running"] is False

    # Reset restores the full duration.
    clue_status.get_by_role("button", name="Reset", exact=True).click()
    page.wait_for_timeout(100)
    reset_state = _get_state(live_server, page, game_id)
    assert (
        reset_state["buzz_remaining_ms"]
        == reset_state["players"]["player1"]["answer_time_ms"]
    )

    # Clear cancels the attempt and reopens ring-in for everyone.
    clue_status.get_by_role("button", name="Clear", exact=True).click()
    expect(page.locator("#control-clue-status")).to_contain_text(
        "Waiting for a ring-in"
    )
    cleared = _get_state(live_server, page, game_id)
    assert cleared["buzzed_player"] is None


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
    page.get_by_role("button", name="Incorrect / No answer").click()

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


def test_crit_boost_announcement_phase_before_wager_and_reveal(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto(live_server, page, game_id, "control")
    page.get_by_role("button", name="P1 Control").click()

    # Git Happens / index 4 (1000 points) is the Crit Boost in the sample bank.
    _select_clue(page, 0, 4)

    # Main announces it, with no clue text and no point value yet.
    _goto(live_server, page, game_id, "main")
    overlay = page.locator("#clue-overlay")
    expect(overlay.locator(".overlay-crit-boost-announce")).to_contain_text(
        "Crit Boost!"
    )
    expect(overlay.locator(".overlay-value")).to_have_count(0)
    status_bar = page.locator("#clue-status-bar")
    # Main stays bare — just the name, no instructional text.
    expect(status_bar).to_contain_text("Player 1")
    expect(status_bar).not_to_contain_text("wager")

    # Player 1 (board control) sees the same pre-wager prompt.
    _goto(live_server, page, game_id, "player1")
    expect(page.locator("#player1-body")).to_contain_text(
        "Your Crit Boost — state your wager!"
    )

    # Player 2 (not board control) sees nothing about it.
    _goto(live_server, page, game_id, "player2")
    expect(page.locator("#player2-body")).not_to_contain_text("Crit Boost")

    # Once wagered and revealed, it flips over to the clue text.
    _goto(live_server, page, game_id, "control")
    page.fill("#crit-boost-wager-input", "500")
    page.get_by_role("button", name="Set Wager").click()
    _reveal_clue(page)

    _goto(live_server, page, game_id, "main")
    expect(overlay.locator(".overlay-crit-boost-announce")).to_have_count(0)
    expect(overlay.locator(".overlay-text-big")).to_be_visible()
    expect(status_bar).to_contain_text("Player 1")
    expect(status_bar).not_to_contain_text("Answering")


def test_crit_boost_wager_reveal_and_judge_correct(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto(live_server, page, game_id, "control")

    page.get_by_role("button", name="P1 Control").click()
    expect(page.locator("#control-round-status")).to_contain_text(
        "Board control: Player 1"
    )

    # Git Happens / index 4 (1000 points) is the Crit Boost in the sample bank.
    _select_clue(page, 0, 4)
    page.fill("#crit-boost-wager-input", "500")
    page.get_by_role("button", name="Set Wager").click()
    _reveal_clue(page)

    expect(page.locator("#control-clue-status")).to_contain_text("Wager: 500")
    page.get_by_role("button", name="Correct", exact=True).click()

    expect(page.locator("#control-players")).to_contain_text("500")
    # Board control is unchanged — they already held it.
    expect(page.locator("#control-round-status")).to_contain_text(
        "Board control: Player 1"
    )


def test_crit_boost_is_timed_but_starts_manually(live_server: str, page: Page) -> None:
    game_id = _create_game(live_server, page)
    _goto(live_server, page, game_id, "control")
    page.get_by_role("button", name="P1 Control").click()

    # Git Happens / index 4 (1000 points) is the Crit Boost in the sample bank.
    _select_clue(page, 0, 4)
    page.fill("#crit-boost-wager-input", "500")
    page.get_by_role("button", name="Set Wager").click()
    _reveal_clue(page)

    # Revealed, but not running yet — Control shows Play, not Pause.
    clue_status = page.locator("#control-clue-status")
    expect(clue_status.get_by_role("button", name="Play", exact=True)).to_be_visible()
    expect(clue_status.get_by_role("button", name="Pause", exact=True)).to_have_count(0)

    # Main already shows the bar (full, static) and Player 1's own
    # screen, even before the host starts the clock.
    _goto(live_server, page, game_id, "main")
    bar = page.locator("#clue-status-bar")
    expect(bar).to_contain_text("Player 1")
    expect(bar.locator(".countdown-track")).to_have_count(1)

    _goto(live_server, page, game_id, "player1")
    expect(page.locator("#player1-body")).to_contain_text(
        "Your Crit Boost — answer now!"
    )
    expect(page.locator("#player1-body .countdown-track")).to_have_count(1)

    # Host starts it manually once ready, and the full Play/Pause/
    # Stop/Reset/Clear row is there, same as a regular clue's timer.
    _goto(live_server, page, game_id, "control")
    clue_status.get_by_role("button", name="Play", exact=True).click()
    expect(clue_status.get_by_role("button", name="Pause", exact=True)).to_be_visible()

    # Judging still works regardless of timer state.
    clue_status.get_by_role("button", name="Correct", exact=True).click()
    expect(page.locator("#control-players")).to_contain_text("500")


def _final_game(live_server: str, page: Page, scores: dict[str, int]) -> str:
    game_id = _create_game(live_server, page)
    for player, score in scores.items():
        resp = page.request.patch(
            f"{live_server}/api/overdrive/games/{game_id}/adjust-score",
            data={"player": player, "score": score},
        )
        assert resp.ok
    return game_id


def _pad_wager(page: Page, player: str, digits: str) -> None:
    for d in digits:
        page.locator(f"#{player}-body .pad-key", has_text=re.compile(f"^{d}$")).click()
    page.get_by_role("button", name="Lock in wager").click()


def test_final_exam_full_flow_gate_any_order_and_per_player_scoring(
    live_server: str, page: Page
) -> None:
    game_id = _final_game(live_server, page, {"player1": 1000, "player2": 600})

    _goto(live_server, page, game_id, "control")
    page.get_by_role("button", name="Start Final Exam").click()
    final = page.locator("#control-final")
    expect(final).to_contain_text("Not playing")
    final.get_by_role("button", name="Reveal category").click()

    # The clue can't go out until everyone playing has wagered.
    expect(final).to_contain_text("waiting for wager")
    expect(final.get_by_role("button", name="Reveal clue")).to_have_count(0)
    expect(final.get_by_role("button", name="Reveal anyway")).to_be_visible()

    _goto(live_server, page, game_id, "player1")
    _pad_wager(page, "player1", "300")
    expect(page.locator("#player1-body")).to_contain_text("Wager locked in")
    _goto(live_server, page, game_id, "player2")
    _pad_wager(page, "player2", "9999")  # more than the score: capped at 600
    expect(page.locator("#player2-body")).to_contain_text("Wager locked in")

    _goto(live_server, page, game_id, "control")
    final.get_by_role("button", name="Reveal clue").click()
    expect(final).to_contain_text("Answer:")
    expect(final.locator(".hf-timer .countdown-track")).to_be_visible()

    for player, text in (("player1", "Who is Ada"), ("player2", "Who is Grace")):
        _goto(live_server, page, game_id, player)
        page.fill(f"#final-answer-{player}", text)
        page.get_by_role("button", name="Lock in answer").click()
        expect(page.locator(f"#{player}-body")).to_contain_text("Answer locked in")

    # Player 2 first, though Player 1 was first to answer.
    _goto(live_server, page, game_id, "control")
    final.get_by_role("button", name="Display Player 2").click()
    _goto(live_server, page, game_id, "main")
    card = page.locator("#main-final-top")
    expect(card).to_contain_text("Player 2")
    expect(card).to_contain_text("wagered 600")
    expect(card).not_to_contain_text("Who is Grace")  # wager first, answer later

    _goto(live_server, page, game_id, "control")
    final.get_by_role("button", name="Reveal answer").click()
    final.get_by_role("button", name="Correct", exact=True).click()
    expect(page.locator("#control-players")).to_contain_text("1200")
    _goto(live_server, page, game_id, "main")
    expect(page.locator("#main-final-top")).to_contain_text("Who is Grace")
    expect(page.locator("#main-final-scores")).to_contain_text("+600")

    _goto(live_server, page, game_id, "control")
    final.get_by_role("button", name="Display Player 1").click()
    final.get_by_role("button", name="Reveal answer").click()
    final.get_by_role("button", name="Incorrect / No answer").click()
    expect(page.locator("#control-players")).to_contain_text("700")

    final.get_by_role("button", name="Show final standings").click()
    _goto(live_server, page, game_id, "main")
    expect(page.locator("#main-final-top")).to_contain_text("Player 2")
    expect(page.locator("#main-final-scores .is-winner")).to_contain_text("1200")
    expect(page.locator("#main-final-scores .not-playing")).to_contain_text(
        "not playing"
    )


def test_final_exam_reveal_anyway_counts_missing_wager_as_zero(
    live_server: str, page: Page
) -> None:
    game_id = _final_game(live_server, page, {"player1": 1000, "player2": 600})
    _goto(live_server, page, game_id, "control")
    page.get_by_role("button", name="Start Final Exam").click()
    final = page.locator("#control-final")
    final.get_by_role("button", name="Reveal category").click()
    final.get_by_role("button", name="Reveal anyway").click()
    expect(final).to_contain_text("Answer:")
    _goto(live_server, page, game_id, "main")
    top = page.locator("#main-final-top")
    expect(top.locator(".final-clue")).to_be_visible()
    expect(top.locator(".final-category-small")).to_be_visible()


def test_final_exam_wager_pad_all_in_clear_and_backspace(
    live_server: str, page: Page
) -> None:
    game_id = _final_game(live_server, page, {"player1": 450, "player2": 600})
    _goto(live_server, page, game_id, "control")
    page.get_by_role("button", name="Start Final Exam").click()
    page.locator("#control-final").get_by_role("button", name="Reveal category").click()

    _goto(live_server, page, game_id, "player1")
    readout = page.locator("#wager-readout-player1")
    expect(readout).to_have_text("0")
    page.locator("#player1-body .pad-key", has_text=re.compile("^7$")).click()
    page.locator("#player1-body .pad-key", has_text=re.compile("^7$")).click()
    expect(readout).to_have_text("77")
    page.get_by_role("button", name="⌫").click()
    expect(readout).to_have_text("7")
    page.get_by_role("button", name="All in").click()
    expect(readout).to_have_text("450")
    page.get_by_role("button", name="Clear").click()
    expect(readout).to_have_text("0")


def test_final_exam_player_can_draw_the_answer_and_main_shows_it(
    live_server: str, page: Page
) -> None:
    game_id = _final_game(live_server, page, {"player1": 1000})
    _goto(live_server, page, game_id, "control")
    page.get_by_role("button", name="Start Final Exam").click()
    final = page.locator("#control-final")
    final.get_by_role("button", name="Reveal category").click()
    _goto(live_server, page, game_id, "player1")
    _pad_wager(page, "player1", "100")
    _goto(live_server, page, game_id, "control")
    final.get_by_role("button", name="Reveal clue").click()

    _goto(live_server, page, game_id, "player1")
    page.get_by_role("button", name="Draw", exact=True).click()
    pad = page.locator("#draw-pad-player1")
    expect(pad).to_be_visible()
    box = pad.bounding_box()
    assert box is not None
    page.mouse.move(box["x"] + 20, box["y"] + 20)
    page.mouse.down()
    page.mouse.move(box["x"] + 120, box["y"] + 80, steps=5)
    page.mouse.up()
    page.get_by_role("button", name="Lock in answer").click()
    expect(page.locator("#player1-body")).to_contain_text("Answer locked in")

    _goto(live_server, page, game_id, "control")
    final.get_by_role("button", name="Display Player 1").click()
    final.get_by_role("button", name="Reveal answer").click()
    _goto(live_server, page, game_id, "main")
    img = page.locator("#main-final-top .fc-answer img")
    expect(img).to_be_visible()
    assert img.evaluate("(el) => el.complete && el.naturalWidth") == 600


def test_final_exam_answer_timer_runs_on_player_and_main(
    live_server: str, page: Page
) -> None:
    game_id = _final_game(live_server, page, {"player1": 1000})
    resp = page.request.patch(
        f"{live_server}/api/overdrive/games/{game_id}/final-answer-time-settings",
        data={"window_ms": 60000},
    )
    assert resp.ok
    _goto(live_server, page, game_id, "control")
    page.get_by_role("button", name="Start Final Exam").click()
    final = page.locator("#control-final")
    final.get_by_role("button", name="Reveal category").click()
    _goto(live_server, page, game_id, "player1")
    _pad_wager(page, "player1", "50")
    _goto(live_server, page, game_id, "control")
    final.get_by_role("button", name="Reveal clue").click()

    _goto(live_server, page, game_id, "player1")
    expect(page.locator("#player1-body .pv-timer .countdown-track")).to_be_visible()
    _goto(live_server, page, game_id, "main")
    expect(
        page.locator("#main-final-top .final-timer .countdown-track")
    ).to_be_visible()


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
        f"{live_server}/api/overdrive/games/{game_id}/adjust-score",
        data={"player": "player1", "score": 777},
    )
    assert resp.ok
    _goto(live_server, page, game_id, "control")
    expect(page.locator("#control-players")).to_contain_text("777")

    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Reset Game", exact=True).click()
    expect(page.locator("#control-players")).not_to_contain_text("777")
    expect(page.locator("#control-round-status")).to_contain_text("Board control: none")


def test_control_can_swap_banks_until_the_round_starts(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto(live_server, page, game_id, "control")
    _open_setup(page)
    for select_id in ("#bank-round1", "#bank-round2", "#bank-final"):
        expect(page.locator(select_id)).to_be_enabled()

    page.select_option("#bank-round1", "movies")
    page.select_option("#bank-final", "moon-landing")
    page.get_by_role("button", name="Apply", exact=True).click()
    expect(
        page.locator("#control-board-headers .cat-header-front").first
    ).to_contain_text("Blockbusters")
    control = page.request.get(
        f"{live_server}/api/overdrive/games/{game_id}/control"
    ).json()
    assert control["categories"][0]["name"] == "Blockbusters"
    assert control["final_bank_id"] == "moon-landing"

    # Flipping a category starts round 1: its bank locks, later ones stay open.
    page.locator("#control-board-headers .cat-header-flip").first.click()
    expect(page.locator("#bank-round1")).to_be_disabled()
    expect(page.locator("#bank-round2")).to_be_enabled()
    expect(page.locator("#bank-final")).to_be_enabled()
    expect(page.locator("#bank-note")).to_contain_text("already started")


def test_main_still_hides_unrevealed_category_names(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto(live_server, page, game_id, "main")
    front = page.locator("#main-board-headers .cat-header-front").nth(1)
    expect(front).to_contain_text("???")
    expect(front).not_to_contain_text("HTTP Status Quo")


def test_bank_dropdowns_list_each_banks_categories(
    live_server: str, page: Page
) -> None:
    page.goto(live_server)
    page.get_by_role("button", name="New Overdrive Game").click()
    classic = page.locator("#new-game-round1_bank_id option[value=classic]")
    expect(classic).to_contain_text("Classic Dev Trivia (Git Happens, HTTP Status Quo")
    final = page.locator("#new-game-final_bank_id option[value=moon-landing]")
    expect(final).to_contain_text("(Space Exploration)")

    page.get_by_role("button", name="Create game").click()
    page.wait_for_url("**/overdrive.html?id=*&view=control")
    _open_setup(page)
    expect(page.locator("#bank-round1 option[value=classic]")).to_contain_text(
        "(Git Happens, HTTP Status Quo"
    )


def test_control_timing_fields_show_the_current_defaults(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page, game_defaults=True)
    _goto(live_server, page, game_id, "control")
    _open_setup(page)
    expect(page.locator("#ring-start-input")).to_have_value("2500")
    expect(page.locator("#ring-window-input")).to_have_value("10000")
    expect(page.locator("#answer-time-input")).to_have_value("10000")

    page.fill("#answer-time-input", "12000")
    page.get_by_role("button", name="Apply Global").nth(1).click()
    page.reload()
    _open_setup(page)
    expect(page.locator("#answer-time-input")).to_have_value("12000")


def test_clicking_the_selected_clue_again_deselects_it(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto(live_server, page, game_id, "control")
    _select_clue(page, 1, 0)
    expect(page.locator("#control-board .clue-cell.in-play")).to_have_count(1)

    page.locator("#control-board .clue-cell.in-play").click()
    expect(page.locator("#control-board .clue-cell.in-play")).to_have_count(0)
    expect(page.locator("#control-clue-fieldset")).to_be_hidden()


def test_clicking_another_clue_swaps_an_unrevealed_selection(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto(live_server, page, game_id, "control")
    _select_clue(page, 1, 0)
    _select_clue(page, 2, 1)
    expect(page.locator("#control-board .clue-cell.in-play")).to_have_count(1)
    expect(page.locator("#control-clue-status")).to_contain_text("Regex Pain")


def test_deselect_button_and_revealed_clues_are_not_swappable(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto(live_server, page, game_id, "control")
    _select_clue(page, 1, 0)
    page.get_by_role("button", name="Deselect Clue").click()
    expect(page.locator("#control-clue-fieldset")).to_be_hidden()

    _select_clue(page, 1, 0)
    _reveal_clue(page)
    expect(page.locator("#control-clue-status")).to_contain_text(
        "Waiting for a ring-in"
    )
    # Once revealed, board cells stop being clickable.
    expect(page.locator("#control-board .clue-cell.clickable")).to_have_count(0)


def test_control_flags_the_crit_boost_clue_but_main_does_not(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto(live_server, page, game_id, "control")
    tags = page.locator("#control-board .clue-cell.crit-boost .crit-tag")
    expect(tags).to_have_count(1)
    expect(tags.first).to_have_text("CRIT BOOST")

    _goto(live_server, page, game_id, "main")
    expect(page.locator("#main-board .crit-tag")).to_have_count(0)
    expect(page.locator("#main-board .crit-boost")).to_have_count(0)


def test_auto_reveal_setting_counts_down_and_reveals_the_clue(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto(live_server, page, game_id, "control")
    _open_setup(page)
    expect(page.locator("#auto-reveal-input")).to_have_value("0")

    page.fill("#auto-reveal-input", "1500")
    page.get_by_role("button", name="Set Auto-reveal").click()
    expect(page.locator("#auto-reveal-input")).not_to_be_focused()

    _select_clue(page, 1, 0)
    expect(page.locator("#control-clue-status .live-label")).to_contain_text(
        "Auto-revealing in"
    )
    expect(page.locator("#control-clue-status .live-seconds")).to_contain_text("s")
    expect(page.locator("#control-clue-status")).to_contain_text(
        "Waiting for a ring-in", timeout=5000
    )


def test_ring_in_buttons_live_in_the_player_boxes_of_the_clue_in_play_box(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto(live_server, page, game_id, "control")
    clue_box = page.locator("#control-clue-fieldset")
    # Not on the per-player rows, and nowhere until a clue is selected.
    expect(page.get_by_role("button", name="Ring In for Player 2")).to_have_count(0)

    _select_clue(page, 1, 0)
    # Selected but not revealed: the boxes are there, the buttons not yet usable.
    expect(clue_box.locator(".live-player")).to_have_count(3)
    expect(clue_box.get_by_role("button", name="Ring In for Player 2")).to_be_disabled()
    _reveal_clue(page)
    for n in (1, 2, 3):
        expect(
            clue_box.get_by_role("button", name=f"Ring In for Player {n}")
        ).to_be_enabled()
    clue_box.get_by_role("button", name="Ring In for Player 2").click()
    # The player who rang in is the one outlined, with their own timer in the box.
    answering = clue_box.locator(".live-player.has-floor")
    expect(answering).to_contain_text("Player 2")
    expect(answering.locator(".countdown-track")).to_have_count(1)
    expect(answering.locator(".lp-secs")).to_have_text(re.compile(r"\d+\.\ds"))
    expect(clue_box.locator(".live-player.has-floor")).to_have_count(1)
    expect(clue_box.get_by_role("button", name="Ring In for Player 1")).to_be_disabled()


def test_a_wrong_answer_disables_that_players_ring_in_but_not_the_others(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto(live_server, page, game_id, "control")
    _select_clue(page, 1, 0)
    _reveal_clue(page)
    clue_box = page.locator("#control-clue-fieldset")
    clue_box.get_by_role("button", name="Ring In for Player 1").click()
    page.get_by_role("button", name="Incorrect").click()

    expect(clue_box.get_by_role("button", name="Ring In for Player 1")).to_be_disabled()
    expect(clue_box.get_by_role("button", name="Ring In for Player 2")).to_be_enabled()
    expect(clue_box.get_by_role("button", name="Ring In for Player 3")).to_be_enabled()


def test_player_timing_buttons_are_named_for_what_they_do(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto(live_server, page, game_id, "control")
    expect(page.get_by_role("button", name="Set Ring-in Timing")).to_have_count(3)
    expect(
        page.get_by_role("button", name="Set Answer Time", exact=True)
    ).to_have_count(3)
    expect(page.get_by_role("button", name="Override Ring-in")).to_have_count(0)


def test_ring_in_bar_turns_red_when_the_window_closes_with_no_one_in(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    page.request.patch(
        f"{live_server}/api/overdrive/games/{game_id}/ring-in-settings",
        data={"start_delay_ms": 0, "window_ms": 800},
    )
    _goto(live_server, page, game_id, "control")
    _select_clue(page, 1, 0)
    _reveal_clue(page)

    _goto(live_server, page, game_id, "main")
    track = page.locator("#clue-status-bar .countdown-track")
    expect(track).not_to_have_class(re.compile("expired"))
    expect(track).to_have_class(re.compile("expired"), timeout=5000)
    expect(track).to_have_css("background-color", "rgb(255, 77, 77)")


def test_answer_bar_turns_red_when_the_answer_time_runs_out(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    api = f"{live_server}/api/overdrive/games/{game_id}"
    page.request.patch(f"{api}/answer-time-settings", data={"window_ms": 800})
    page.request.patch(
        f"{api}/select-clue", data={"category_index": 1, "clue_index": 0}
    )
    page.request.patch(f"{api}/reveal-clue")
    page.request.patch(f"{api}/host-ring-in", data={"player": "player1"})

    _goto(live_server, page, game_id, "main")
    track = page.locator("#clue-status-bar .countdown-track")
    expect(track).not_to_have_class(re.compile("expired"))
    expect(track).to_have_class(re.compile("expired"), timeout=5000)


def test_host_can_set_a_crit_boost_wager_of_zero(live_server: str, page: Page) -> None:
    game_id = _create_game(live_server, page)
    page.request.patch(
        f"{live_server}/api/overdrive/games/{game_id}/board-control",
        data={"player": "player1"},
    )
    _goto(live_server, page, game_id, "control")
    _select_clue(page, 0, 4)  # the Crit Boost clue

    reveal = page.get_by_role("button", name="Reveal Clue")
    expect(reveal).to_be_disabled()  # no wager yet
    # The valid range is shown: up to the round's top value (1000 in round 1).
    expect(page.locator("#crit-boost-wager-input")).to_have_attribute(
        "placeholder", "Wager (0–1000)"
    )
    page.fill("#crit-boost-wager-input", "0")
    page.get_by_role("button", name="Set Wager").click()
    expect(reveal).to_be_enabled()
    reveal.click()
    expect(page.locator("#control-clue-status")).to_contain_text("Wager: 0")


def test_a_press_held_across_several_polls_still_registers(
    live_server: str, page: Page
) -> None:
    # The page polls every 200ms and a live clue changes state on every
    # poll; a click needs mousedown and mouseup on the *same* element, so
    # redrawing the buttons under a held press used to swallow it.
    game_id = _create_game(live_server, page)
    _goto(live_server, page, game_id, "control")
    _select_clue(page, 1, 0)
    _reveal_clue(page)

    button = page.get_by_role("button", name="Ring In for Player 1")
    expect(button).to_be_enabled()
    button.hover()
    page.mouse.down()
    page.wait_for_timeout(700)  # several poll/redraw cycles
    page.mouse.up()
    expect(page.locator("#control-clue-status .live-player.has-floor")).to_contain_text(
        "Player 1"
    )


def test_control_and_player_buttons_survive_polling_untouched(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto(live_server, page, game_id, "control")
    _select_clue(page, 1, 0)
    _reveal_clue(page)
    # Let the ring-in window open first: that one state change legitimately
    # redraws the banner; after it, polling must leave the buttons alone.
    expect(page.locator("#control-clue-status .live-label")).to_contain_text(
        "Waiting for a ring-in"
    )
    no_one = page.get_by_role("button", name="No One Answered")
    no_one.evaluate("el => { el.dataset.keep = '1'; }")
    page.wait_for_timeout(900)  # ring-in elapsed ticks the whole time
    expect(no_one).to_have_attribute("data-keep", "1")

    _goto(live_server, page, game_id, "player1")
    buzz = page.locator("#player1-body .buzz-btn")
    expect(buzz).to_be_visible()
    buzz.evaluate("el => { el.dataset.keep = '1'; }")
    page.wait_for_timeout(900)  # the shrinking bar ticks the whole time
    expect(buzz).to_have_attribute("data-keep", "1")
    expect(page.locator("#player1-body .countdown-track")).to_have_count(1)


def test_control_shows_and_saves_the_retry_ring_in_timing(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page, game_defaults=True)
    _goto(live_server, page, game_id, "control")
    _open_setup(page)
    expect(page.locator("#retry-start-input")).to_have_value("0")
    expect(page.locator("#retry-window-input")).to_have_value("10000")

    page.fill("#retry-start-input", "400")
    page.fill("#retry-window-input", "7000")
    page.get_by_role("button", name="Set Retry Ring-in").click()
    page.reload()
    _open_setup(page)
    expect(page.locator("#retry-start-input")).to_have_value("400")
    expect(page.locator("#retry-window-input")).to_have_value("7000")
    # The first window's own settings are unchanged.
    expect(page.locator("#ring-start-input")).to_have_value("2500")


# ----- Host view and the live clue panel -----


def _reveal_via_api(
    live_server: str, page: Page, game_id: str, cat: int, clue: int
) -> None:
    api = f"{live_server}/api/overdrive/games/{game_id}"
    page.request.patch(
        f"{api}/select-clue", data={"category_index": cat, "clue_index": clue}
    )
    page.request.patch(f"{api}/reveal-clue")


def test_host_tab_shows_round_scores_and_a_clickable_board(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto(live_server, page, game_id, "host")
    expect(page.locator("#tab-host")).to_have_class(re.compile("active"))
    expect(page.locator("#host-round-status")).to_contain_text("Round 1")
    # With no clue in play the panel is just the player boxes (3 + clear).
    expect(page.locator("#host-clue-legend")).to_have_text("Scores and board control")
    expect(page.locator("#host-clue-status .live-player")).to_have_count(4)
    expect(page.locator("#host-board .clue-cell")).to_have_count(30)

    # Categories flip and clues select from the Host board too.
    flip = page.locator("#host-board-headers .cat-header-flip").nth(1)
    flip.click()
    expect(flip).to_have_class(re.compile("flipped"))
    _select_clue(page, 1, 0)
    expect(page.locator("#host-clue-fieldset")).to_be_visible()
    expect(page.locator("#host-clue-status")).to_contain_text("HTTP Status Quo")


def test_host_banner_counts_down_the_ring_in_window(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _reveal_via_api(live_server, page, game_id, 1, 0)
    _goto(live_server, page, game_id, "host")

    status = page.locator("#host-clue-status")
    expect(status.locator(".live-label")).to_contain_text("Waiting for a ring-in")
    seconds = status.locator(".live-seconds")
    expect(seconds).to_have_text(re.compile(r"^\d+\.\ds$"))
    first = float(seconds.inner_text().rstrip("s"))
    page.wait_for_timeout(1200)
    assert float(seconds.inner_text().rstrip("s")) < first  # it ticks down
    expect(status.locator(".live-bar-inline .countdown-track")).to_have_count(1)


def test_host_banner_turns_to_time_up_when_no_one_rings_in(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    page.request.patch(
        f"{live_server}/api/overdrive/games/{game_id}/ring-in-settings",
        data={"start_delay_ms": 0, "window_ms": 800},
    )
    _reveal_via_api(live_server, page, game_id, 1, 0)
    _goto(live_server, page, game_id, "host")
    banner = page.locator("#host-clue-status .live-banner")
    expect(banner).to_have_class(re.compile("tone-alert"), timeout=6000)
    expect(banner).to_contain_text("no one rang in")
    expect(page.locator("#host-clue-status .countdown-track")).to_have_class(
        re.compile("expired")
    )


def test_host_can_run_a_clue_start_to_finish(live_server: str, page: Page) -> None:
    game_id = _create_game(live_server, page)
    _goto(live_server, page, game_id, "host")
    _select_clue(page, 1, 0)
    panel = page.locator("#host-clue-fieldset")
    expect(page.locator("#host-clue-legend")).to_have_text("Clue in play")
    panel.get_by_role("button", name="Reveal Clue").click()
    panel.get_by_role("button", name="Ring In for Player 2").click()

    # The player who rang in is outlined green with the countdown in their box.
    answering = panel.locator(".live-player.has-floor")
    expect(answering).to_contain_text("Player 2")
    expect(answering.locator(".lp-secs")).to_have_text(re.compile(r"^\d+\.\ds$"))
    expect(panel.locator(".live-window")).to_be_empty()  # no separate banner

    panel.get_by_role("button", name="Correct", exact=True).click()
    # Back to just the boxes, with Player 2 holding control.
    expect(page.locator("#host-clue-legend")).to_have_text("Scores and board control")
    player2 = panel.locator(".live-player").nth(1)
    expect(player2).to_contain_text("200")
    expect(player2).to_have_class(re.compile("has-control"))
    expect(player2.locator(".lp-badge")).to_have_text("Control")
    expect(player2.get_by_role("button", name="Has control")).to_be_disabled()


def test_a_wrong_answer_shows_the_second_chance_window_on_the_host_banner(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _reveal_via_api(live_server, page, game_id, 1, 0)
    _goto(live_server, page, game_id, "host")
    panel = page.locator("#host-clue-fieldset")
    panel.get_by_role("button", name="Ring In for Player 1").click()
    panel.get_by_role("button", name="Incorrect").click()
    expect(panel.locator(".live-label")).to_contain_text("second chance")
    expect(panel.get_by_role("button", name="Ring In for Player 1")).to_be_disabled()
    expect(panel.get_by_role("button", name="Ring In for Player 3")).to_be_enabled()


def test_host_buttons_survive_a_press_held_across_polls(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _reveal_via_api(live_server, page, game_id, 1, 0)
    _goto(live_server, page, game_id, "host")
    button = page.locator("#host-clue-fieldset").get_by_role(
        "button", name="Ring In for Player 3"
    )
    expect(button).to_be_enabled()
    button.hover()
    page.mouse.down()
    page.wait_for_timeout(700)
    page.mouse.up()
    expect(page.locator("#host-clue-status .live-player.has-floor")).to_contain_text(
        "Player 3"
    )


def test_control_puts_the_clue_in_play_above_the_board_and_collapses_setup(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _goto(live_server, page, game_id, "control")
    details = page.locator("details.setup-details")
    expect(details).to_have_count(2)  # Content, Timing
    for i in range(2):
        assert details.nth(i).evaluate("el => el.open") is False

    _select_clue(page, 1, 0)
    expect(page.locator("#control-clue-status .live-banner")).to_be_visible()
    clue_y = page.locator("#control-clue-fieldset").bounding_box()["y"]
    board_y = page.locator("#control-board-fieldset").bounding_box()["y"]
    assert clue_y < board_y  # the live panel is above the board
    expect(page.locator("#control-clue-status .live-banner")).to_be_visible()


def test_lobby_overdrive_card_links_to_the_host_view(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    page.goto(live_server)
    expect(
        page.locator(f'a[href="/overdrive.html?id={game_id}&view=host"]')
    ).to_have_text("Host")


def test_board_control_is_a_tag_and_the_floor_is_an_outline(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    api = f"{live_server}/api/overdrive/games/{game_id}"
    page.request.patch(f"{api}/board-control", data={"player": "player1"})
    _reveal_via_api(live_server, page, game_id, 1, 0)
    page.request.patch(f"{api}/host-ring-in", data={"player": "player3"})
    _goto(live_server, page, game_id, "host")

    boxes = page.locator("#host-clue-status .live-player")
    # Player 1 holds control (gold tag, no outline); Player 3 has the floor.
    expect(boxes.nth(0)).to_have_class(re.compile("has-control"))
    expect(boxes.nth(0).locator(".lp-badge")).to_have_text("Control")
    expect(boxes.nth(0)).not_to_have_class(re.compile("has-floor"))
    expect(boxes.nth(2)).to_have_class(re.compile("has-floor"))
    expect(boxes.nth(2).locator(".lp-badge")).to_have_count(0)


def test_the_answering_players_box_turns_red_when_their_time_is_up(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    api = f"{live_server}/api/overdrive/games/{game_id}"
    page.request.patch(f"{api}/answer-time-settings", data={"window_ms": 800})
    _reveal_via_api(live_server, page, game_id, 1, 0)
    page.request.patch(f"{api}/host-ring-in", data={"player": "player2"})
    _goto(live_server, page, game_id, "host")
    box = page.locator("#host-clue-status .live-player").nth(1)
    expect(box).to_have_class(re.compile("time-up"), timeout=6000)
    expect(box.locator(".countdown-track")).to_have_class(re.compile("expired"))


def test_the_judge_button_covers_wrong_and_no_answer(
    live_server: str, page: Page
) -> None:
    game_id = _create_game(live_server, page)
    _reveal_via_api(live_server, page, game_id, 1, 0)
    _goto(live_server, page, game_id, "host")
    panel = page.locator("#host-clue-fieldset")
    panel.get_by_role("button", name="Ring In for Player 1").click()
    expect(panel.get_by_role("button", name="Incorrect / No answer")).to_be_visible()
    expect(panel.get_by_role("button", name="No answer", exact=True)).to_have_count(0)
