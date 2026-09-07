# Many Game Show

A multi-game-show web app, built for a "50 minutes, idea to working app"
conference session. FastAPI + SQLite backend, vanilla HTML/CSS/JS frontend,
no build step. See [ARCHITECTURE.md](./ARCHITECTURE.md) and
[UI_LOOK_AND_FEEL.md](./UI_LOOK_AND_FEEL.md) for the design behind it.

Currently implements:
- **Squad Squabble** — a Family-Feud-style survey game.
- **Speed Points** — a Fast-Money-style relay: two players take turns
  answering the same 5 questions against a countdown, the host judges each
  answer against the survey data, and a big reveal checks the combined
  score against a win threshold.

---

## Screenshots

| Lobby | Control (host) |
|---|---|
| ![Lobby](./docs/screenshots/lobby.png) | ![Control view](./docs/screenshots/control-view.png) |

| Display (default theme) | Display (stage theme) |
|---|---|
| ![Display view](./docs/screenshots/display-view.png) | ![Display view, stage theme](./docs/screenshots/display-view-stage-theme.png) |

---

## Running it

Requires [uv](https://docs.astral.sh/uv/) — everything else (Python 3.13,
all Python dependencies) lives inside uv's auto-created `.venv` and needs
nothing pre-installed. On a new machine, check first:

```bash
make preflight
```

This checks for `uv`, `git`, network reachability (PyPI is required;
astral.sh is optional — see script comments for why), a free port 8000,
and whether Playwright's browser is installed (only needed for
`make test-ui`, not for just running the app). It exits non-zero with fix
instructions if anything required is missing.

```bash
# Install dependencies
make sync
# (equivalent to: uv sync --extra dev)

# Run the dev server (hot-reload)
make run
# (equivalent to: uv run uvicorn manygameshow.main:app --reload)
```

Then open **http://localhost:8000** — click **New Squad Squabble Game** or
**New Speed Points Game** from the lobby to create a game. That takes you
to the Control view; open `/squad-squabble.html?id=<the game id>&view=display`
(or `/speed-points.html?...`) on a second screen/tab for the big-screen
Display view.

The SQLite database file (`manygameshow.db`) is created automatically on
first run. **If you change a model's fields, run `make clean` (or delete
the db file yourself) before restarting** — there's no migration tooling
(see ARCHITECTURE.md).

### Question content

Both games' questions live as data, not code, so real content can be
swapped in without touching any code — point the env var at a different
JSON file (same `{"questions": [{"id", "prompt", "answers": [{"text",
"points"}]}]}` shape):

```bash
SQUAD_SQUABBLE_QUESTIONS_PATH=/path/to/real_questions.json make run
SPEED_POINTS_QUESTIONS_PATH=/path/to/other_questions.json make run
```

Squad Squabble uses its whole bank; Speed Points always uses exactly the
first 5 questions in the file (both players face the same 5, in order).

---

## Checks

```bash
make lint        # ruff + djlint
make typecheck    # mypy
make test-backend # pytest (models + API)
make test-ui       # Playwright, real browser
make check        # all of the above
```

See [`.github/workflows/ci.yml`](./.github/workflows/ci.yml) for what runs
in CI on every push/PR.

---

## Project docs

- [ARCHITECTURE.md](./ARCHITECTURE.md) — stack, conventions, extension pattern
- [ADDING_A_GAME.md](./ADDING_A_GAME.md) — step-by-step recipe for adding a new game
- [UI_LOOK_AND_FEEL.md](./UI_LOOK_AND_FEEL.md) — theming, typography, view conventions
- [AIA_ATTRIBUTION.md](./AIA_ATTRIBUTION.md) — AI attribution statement used in commits
- [SESSION_LOG.md](./SESSION_LOG.md) — turn-by-turn build timing, turns 1–69
  (frozen: a container reset truncated the transcript this is generated
  from — see the file's own header)
- [SESSION_LOG_2.md](./SESSION_LOG_2.md) — continuation of the above from
  the reset onward (turn numbering restarts at 1, since it's a separate
  transcript file)
