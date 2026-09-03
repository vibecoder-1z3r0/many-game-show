import subprocess
import time
from collections.abc import Iterator

import pytest
from playwright.sync_api import Page, expect


@pytest.fixture(scope="module")
def live_server() -> Iterator[str]:
    proc = subprocess.Popen(
        ["uvicorn", "manygameshow.main:app", "--port", "8811"],
    )
    try:
        time.sleep(1.5)  # give uvicorn a moment to bind
        yield "http://127.0.0.1:8811"
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_lobby_loads(live_server: str, page: Page) -> None:
    page.goto(live_server)
    expect(page.locator("h1")).to_have_text("Many Game Show")
