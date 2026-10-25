#!/usr/bin/env python3
"""Regenerate the README screenshots in docs/screenshots/.

Starts a throwaway server (its own temp SQLite db and port, so your dev
database is untouched), drives one game of each kind into a photogenic
state through the real API, and screenshots the lobby plus each game's
Main and Control views with Playwright.

Usage:
    uv run python scripts/screenshots.py

In Claude Code's remote sandbox, where a Chromium build is preinstalled
(see CLAUDE.md), point at it first:
    PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=<path to chrome> \\
        uv run python scripts/screenshots.py
(the chromium-1194 directory under /opt/pw-browsers/ at time of writing)
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import httpx
from playwright.sync_api import Page, ViewportSize, sync_playwright

ROOT = Path(__file__).parent.parent
OUT = ROOT / "docs" / "screenshots"
PORT = 8899
BASE = f"http://127.0.0.1:{PORT}"
VIEWPORT: ViewportSize = {"width": 1280, "height": 800}


def api(method: str, path: str, **kwargs: object) -> dict:
    resp = httpx.request(method, f"{BASE}/api{path}", **kwargs)  # type: ignore[arg-type]
    resp.raise_for_status()
    return resp.json() if resp.content else {}


def create(game: str, body: dict | None = None) -> str:
    return api("POST", f"/{game}/games/", json=body or {})["id"]  # type: ignore[no-any-return]


def patch(game: str, game_id: str, action: str, body: dict | None = None) -> None:
    api("PATCH", f"/{game}/games/{game_id}/{action}", json=body)


def shot(page: Page, name: str, url: str, wait_ms: int = 900) -> None:
    page.goto(f"{BASE}{url}")
    page.wait_for_timeout(wait_ms)
    page.screenshot(path=str(OUT / f"{name}.png"))
    print(f"  {name}.png")


def setup_squad_squabble() -> str:
    gid = create("squad-squabble")
    bank = json.loads(
        (
            ROOT / "src/manygameshow/data/squad_squabble_questions.sample.json"
        ).read_text()
    )
    patch(
        "squad-squabble",
        gid,
        "load-question",
        {"question_id": bank["questions"][0]["id"]},
    )
    patch("squad-squabble", gid, "face-off", {"team": "team1"})
    for i in (0, 1, 2):
        patch("squad-squabble", gid, "reveal", {"answer_index": i})
    patch("squad-squabble", gid, "strike")
    patch("squad-squabble", gid, "strike")
    return gid


def setup_speed_points() -> str:
    """Player 1 has answered all five questions and the host has revealed
    every answer on Main; points (the second reveal beat) are still hidden."""
    gid = create("speed-points")
    patch(
        "speed-points",
        gid,
        "start-round",
        {"player": "player1", "duration_seconds": 1},
    )
    answers = ["Nit:", "Blocked on review", "Rubber duck", "Friday", "Write tests"]
    for i, text in enumerate(answers):
        patch("speed-points", gid, "answer", {"question_index": i, "text": text})
        patch("speed-points", gid, "answer-lock", {"question_index": i, "locked": True})
    time.sleep(1.5)  # let the 1s countdown expire: the round is over
    return gid


def setup_big_tokens() -> str:
    gid = create("big-tokens")
    patch("big-tokens", gid, "chase-speed", {"step_ms": 400})
    for player, tokens in (("player1", 1200), ("player2", 650), ("player3", 300)):
        patch(
            "big-tokens",
            gid,
            "adjust-player",
            {"player": player, "token_total": tokens, "spins_remaining": 2},
        )
    patch(
        "big-tokens",
        gid,
        "adjust-player",
        {"player": "player3", "hallucination_count": 1},
    )
    patch("big-tokens", gid, "active-player", {"player": "player1"})
    patch("big-tokens", gid, "start-spin")
    return gid


def setup_overdrive() -> str:
    gid = create("overdrive")
    for i in range(6):
        patch(
            "overdrive", gid, "category-reveal", {"category_index": i, "revealed": True}
        )
    return gid


def wait_for_server() -> None:
    for _ in range(100):
        try:
            urllib.request.urlopen(f"{BASE}/health", timeout=0.5)
            return
        except (urllib.error.URLError, ConnectionError):
            time.sleep(0.1)
    raise RuntimeError("server did not become healthy")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    executable = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH")
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "MANYGAMESHOW_DB_PATH": str(Path(tmp) / "shots.db")}
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "manygameshow.main:app",
                "--port",
                str(PORT),
            ],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            wait_for_server()
            # Set up each game right before shooting it, so live state (the
            # Speed Points countdown, the Big Tokens chase) is fresh.
            setups = {
                "squad-squabble": setup_squad_squabble,
                "speed-points": setup_speed_points,
                "big-tokens": setup_big_tokens,
                "overdrive": setup_overdrive,
            }
            ids: dict[str, str] = {}
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=executable)
                page = browser.new_page(viewport=VIEWPORT)
                print("Writing screenshots to", OUT)
                for game, setup in setups.items():
                    ids[game] = setup()
                    # Squad Squabble's Main is tall enough to push the
                    # strikes below an 800px fold.
                    height = 1000 if game == "squad-squabble" else VIEWPORT["height"]
                    page.set_viewport_size(
                        {"width": VIEWPORT["width"], "height": height}
                    )
                    shot(page, f"{game}-main", f"/{game}.html?id={ids[game]}&view=main")
                    shot(
                        page,
                        f"{game}-control",
                        f"/{game}.html?id={ids[game]}&view=control",
                    )
                shot(page, "lobby", "/")
                # Overdrive's clue overlay and the stage theme.
                patch(
                    "overdrive",
                    ids["overdrive"],
                    "select-clue",
                    {"category_index": 1, "clue_index": 1},
                )
                patch("overdrive", ids["overdrive"], "reveal-clue")
                shot(
                    page,
                    "overdrive-clue",
                    f"/overdrive.html?id={ids['overdrive']}&view=main",
                )
                page.goto(
                    f"{BASE}/squad-squabble.html?id={ids['squad-squabble']}&view=main"
                )
                page.select_option("#theme-select", "stage")
                page.wait_for_timeout(500)
                page.screenshot(path=str(OUT / "squad-squabble-main-stage-theme.png"))
                print("  squad-squabble-main-stage-theme.png")
                browser.close()
        finally:
            server.terminate()
            server.wait(timeout=5)


if __name__ == "__main__":
    main()
