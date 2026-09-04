# Architecture

Technical plan for Many Game Show, patterned after the `many-board`
scoreboard app's backend/frontend architecture. This doc is the reference
point before we start building — update it if we deviate.

---

## Stack

| Layer | Tech |
|---|---|
| Backend | Python 3.13+, FastAPI, SQLModel (SQLite), Pydantic v2 |
| Package mgr | uv |
| Lint / format | ruff (lint + format — no black; `ruff format` is a compatible superset) |
| Type check | mypy |
| Backend tests | pytest + pytest-cov |
| UI tests | pytest-playwright (Python bindings, not the Node/JS runner) |
| HTML lint/format | djlint |
| Frontend | Vanilla HTML + CSS + JS — no build step, no framework |
| Server | uvicorn |
| CI | GitHub Actions (`.github/workflows/ci.yml`) |

Same stack as the reference app. Chosen for: zero build tooling (nothing to
break mid-demo), fast to reason about, easy to extend live, runs anywhere
(including a laptop with no internet once dependencies are installed).

---

## CI & Testing

GitHub Actions (`.github/workflows/ci.yml`) runs three jobs on every push
and PR: `lint-and-typecheck`, `backend-tests`, `ui-tests`. Local equivalents
are in the `Makefile` (`make check` runs all of it).

### Why these tools

- **ruff only, no black.** `ruff format` is a fast, black-compatible
  formatter; running both would just mean two configs that can disagree
  with each other for no benefit.
- **djlint, not a Node toolchain.** The frontend is deliberately
  framework-free with no build step (see UI_LOOK_AND_FEEL.md). Pulling in
  ESLint/Prettier just to lint inline `<script>`/`<style>` blocks would
  add a second language toolchain purely for CI — against the spirit of
  the "nothing to break mid-demo" design goal. djlint is a pure-Python
  HTML formatter/linter with no Node dependency, so it's the one frontend
  lint tool we do use.
- **pytest-playwright, not the JS Playwright Test runner.** Keeps CI (and
  test authoring) to a single language — Python — end to end. Browser
  tests live in `tests/test_ui/` as ordinary pytest files, using the
  `page` fixture from `pytest-playwright`.
- **Real browser tests, not JS unit tests, are the frontend safety net.**
  Since there's no JS linter, correctness of the polling/render/theme
  logic in each game's `.html` file is verified by actually loading the
  page in Chromium and asserting on rendered state — this also matches
  how the app will really be used (a phone/tablet loading a page).

### Test layout

```
tests/
  test_api/      # pytest — FastAPI TestClient, one file per game's router
  test_models/   # pytest — model defaults, enums, ID generation (added as models are added)
  test_ui/       # pytest-playwright — loads real pages in Chromium, asserts on rendered DOM
```

### Coverage target

No hard threshold enforced yet — `pytest-cov` reports coverage in CI output
so gaps are visible, but a numeric gate can be added once there's enough
real game logic to make one meaningful.

---

## Project Structure

```
src/manygameshow/
  main.py                 # FastAPI app, router registration, static mount
  database.py              # SQLite engine + get_session() dependency
  models/
    {game}.py               # DB model, *Create schema, *Read schema per game
  routers/
    {game}.py               # /api/{game}/... endpoints per game
  static/
    index.html               # Lobby: list of active games/rounds, polls 1s
    {game}.html               # Full UI for one game (all its views/tabs)
    favicon.svg

tests/
  test_models/test_{game}.py
  test_api/test_{game}.py
```

Each game is a vertical slice: one model file, one router file, one HTML
file. Nothing shared between games except `main.py` wiring and common CSS
conventions (see UI_LOOK_AND_FEEL.md). This mirrors the reference app's
football/baseball split exactly.

---

## Core Architecture Decisions

### Server is the source of truth for all state
No independently-running client-side state — no `setInterval` counters, no
locally-decremented timers, no client-side score math the server doesn't
also know about. Every control action is a `PATCH` to the server; every
view is a render of the server's last response. This is non-negotiable —
it's what makes the app resilient to bad wifi, page reloads, and multiple
simultaneous viewers (host laptop + big screen + phones) staying in sync.

If something needs a countdown (e.g. a buzzer round timer), store
`remaining_seconds` + a `started_at` UTC timestamp server-side, and compute
elapsed time on every GET — same pattern as the reference app's game/play
clocks.

### REST polling, not WebSockets
Live views poll `GET /api/{game}/state` (or similar) every 200ms; the lobby
polls every 1s. No persistent connections, no reconnect logic, no server
push infrastructure. Simple to reason about, trivially resilient to a
dropped connection (worst case: the next poll just tries again), and
nothing to configure differently for a conference network vs. any other
network.

### Connection status is a first-class UI element
Every polling view tracks consecutive poll failures and surfaces a visible
"disconnected" state after 3 failures (~600ms at 200ms polling). See
UI_LOOK_AND_FEEL.md.

### Three schemas per game, same as the reference app

| Schema | Purpose |
|---|---|
| `{Game}` | DB table (`SQLModel, table=True`) — raw storage, may include JSON blob columns |
| `{Game}Create` | POST body — only fields settable at creation |
| `{Game}Read` | All API responses — replaces raw JSON blobs with parsed/typed fields, adds computed fields |

Router-local helpers per game (copy the shape, not the code, from game to
game):
- `_to_read(game)` — DB model → Read schema
- `_save(game, session)` — set `updated_at`, commit, refresh, return
- `_get_game(id, session)` — fetch by PK or raise 404

### Irregular/structured state as JSON columns
Anything shaped like a list or nested dict (e.g. per-round scores, a
question queue, a leaderboard snapshot) is stored as a JSON string column
on the model and parsed into a typed Pydantic object only in the Read
schema / router layer. The model layer never parses JSON itself.

### IDs and enums
- IDs are UUID4 strings, generated with `default_factory=lambda: str(uuid.uuid4())`.
- All string-valued enums use `StrEnum` (Python 3.11+).

### Database
- SQLite, single file, created automatically on startup via
  `SQLModel.metadata.create_all(engine)` in a FastAPI `lifespan` handler.
- No migrations tooling. **If a model's columns change, run `make clean`
  (or delete the `.db` file yourself) and restart** during development.
  Acceptable for a conference demo; would need real migrations (e.g.
  Alembic) if this became a long-lived multi-event app.

---

## Adding a New Game (extension pattern)

Same recipe as the reference app's `ADDING_A_SPORT.md`, renamed to games:

1. `models/{game}.py` — table model + `Create` + `Read` schemas.
2. `routers/{game}.py` — `APIRouter` with create/list/get/delete plus one
   `PATCH` endpoint per state-changing action (score, buzz, next question,
   reveal answer, etc. — whatever the game needs).
3. `static/{game}.html` — self-contained page with its own `<style>` and
   `<script>`; implements the poll/render loop and whatever views/tabs the
   game needs (Display, Control, Player, ...).
4. Wire it up:
   - `main.py`: import the router, `app.include_router(...)`.
   - `static/index.html`: add a card linking to the new game's views.
5. Tests: `test_models/test_{game}.py` (defaults, enums, ID generation),
   `test_api/test_{game}.py` (every endpoint, happy path + one edge case).

This is the pattern we'll actually exercise live at the conference — the
"idea to working app" arc is: pick a game → walk through steps 1–4 → it's
live in the lobby.

---

## What's Deliberately Out of Scope

- Auth / accounts — single shared control view, trust-based (same as the
  reference app; local-network conference demo, not a public product).
- Real-time push (WebSockets/SSE) — polling is simpler and was a deliberate
  choice in the reference app for the same class of problem.
- Client-side frameworks/bundlers — nothing to build, nothing to break.
- Database migrations — not needed at demo scale.

---

## Open Questions (fill in once the game-show concept is locked)

- What is the actual show format — single game, or a lobby of several
  mini-games? (Architecture above assumes "lobby of games," matching the
  reference app's multi-sport structure.)
- Does any game need a buzzer/player view, or is it host-vs-screen only?
- Any state that needs to survive a server restart mid-demo, or is
  fresh-DB-per-run acceptable for the conference run?
