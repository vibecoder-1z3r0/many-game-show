"""UI test fixtures.

Some sandboxed dev environments ship a pre-installed Chromium whose
directory-versioned path doesn't match what this pinned Playwright version
expects, so the default browser lookup fails even though a usable browser
exists. Set PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH to point at it explicitly
for local dev in that case. Unset (the default, and the case on CI, where
`playwright install` successfully fetches the matching version) leaves
Playwright's normal lookup untouched.
"""

import os
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

_PORT = 8811
_BASE_URL = f"http://127.0.0.1:{_PORT}"
_DB_PATH = Path(__file__).parent.parent.parent / "manygameshow.db"


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args: dict) -> dict:
    executable_path = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH")
    if executable_path:
        return {**browser_type_launch_args, "executable_path": executable_path}
    return browser_type_launch_args


@pytest.fixture(scope="session")
def live_server() -> Iterator[str]:
    _DB_PATH.unlink(missing_ok=True)  # start every UI test run from a clean DB
    proc = subprocess.Popen(["uvicorn", "manygameshow.main:app", "--port", str(_PORT)])
    try:
        for _ in range(50):  # ~5s
            try:
                urllib.request.urlopen(f"{_BASE_URL}/health", timeout=0.5)
                break
            except (urllib.error.URLError, ConnectionError):
                time.sleep(0.1)
        else:
            raise RuntimeError("uvicorn did not become healthy in time")
        yield _BASE_URL
    finally:
        proc.terminate()
        proc.wait(timeout=5)
        _DB_PATH.unlink(missing_ok=True)
