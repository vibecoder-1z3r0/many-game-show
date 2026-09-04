from playwright.sync_api import Page, expect


def test_lobby_loads(live_server: str, page: Page) -> None:
    page.goto(live_server)
    expect(page.locator("h1")).to_have_text("Many Game Show")


def test_lobby_delete_button_requires_confirmation_and_removes_game(
    live_server: str, page: Page
) -> None:
    resp = page.request.post(
        f"{live_server}/api/squad-squabble/games/",
        data={"team1_name": "Devs", "team2_name": "Ops"},
    )
    assert resp.ok
    game_id = resp.json()["id"]

    page.goto(live_server)
    card = page.locator(".game-card", has_text="Devs vs Ops")
    expect(card).to_be_visible()

    # Dismissing the confirm dialog leaves the game in place
    page.once("dialog", lambda dialog: dialog.dismiss())
    card.get_by_role("button", name="Delete", exact=True).click()
    expect(card).to_be_visible()

    # Accepting it removes the game from the lobby
    page.once("dialog", lambda dialog: dialog.accept())
    card.get_by_role("button", name="Delete", exact=True).click()
    expect(page.locator(".game-card", has_text="Devs vs Ops")).to_have_count(0)

    get_resp = page.request.get(f"{live_server}/api/squad-squabble/games/{game_id}")
    assert get_resp.status == 404
