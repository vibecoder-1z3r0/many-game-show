from playwright.sync_api import Page, expect


def test_lobby_loads(live_server: str, page: Page) -> None:
    page.goto(live_server)
    expect(page.locator("h1")).to_have_text("Many Game Show")
