# Adding a New Game

This is the concrete recipe extracted from building **Squad Squabble**, the
first game in this app. Follow it step by step for the next game; if a step
doesn't fit, that's a signal this doc needs updating, not that the new game
should quietly diverge.

See also: [ARCHITECTURE.md](./ARCHITECTURE.md) for the overall stack/repo
layout, and [UI_LOOK_AND_FEEL.md](./UI_LOOK_AND_FEEL.md) for the shared
visual/UX conventions (theming, typography, connection-status badge, etc.)
every game's frontend follows regardless of its own rules.

---

## 1. Backend: model

`src/manygameshow/models/{game}.py`

- One `SQLModel` table class (`{Game}Game`) holding all server-authoritative
  state for a single game instance: team/player names, scores, whatever
  "current position in the game" looks like for this format, and a
  `status: str` field (mirrors Squad Squabble's `status = "active"`).
- List/set-shaped state (e.g. "which answers are revealed") is stored as a
  JSON string column (`..._json: str`) with a small accessor function next
  to the model (`revealed_indices(game)` is the Squad Squabble example) —
  SQLModel/SQLite doesn't give you a native list column, and a JSON string
  column plus a plain function is simpler than reaching for a related table.
- A derived-value function for anything computed from state rather than
  stored directly (Squad Squabble's `round_points(game)`, which sums
  revealed answers × the round multiplier). Keep these as free functions
  taking the model, not model methods — matches the existing style and
  keeps the SQLModel class itself just data.
- `{Game}GameCreate` — the POST body schema (usually just the
  human-choosable setup fields: team/player names).
- `{Game}GameRead` — the response schema. This is where you resolve
  anything that shouldn't leak raw internal shape to the client: Squad
  Squabble's `SquadSquabbleGameRead` swaps `current_question_id` +
  `revealed_answer_indices_json` for a fully-resolved `current_question`
  with per-answer `revealed: bool`, and includes the derived
  `round_points` instead of making the client recompute it.
- Any enums (`StrEnum`, e.g. `Team`) live here too.

If the game needs question/prompt content (survey-style, trivia, etc.),
follow the **content-as-data** pattern: a small `Question`/`Answer`
`pydantic.BaseModel` pair, loaded from a JSON file via an
`lru_cache`d loader function, with an env var override for pointing at real
content (see `src/manygameshow/questions.py` — currently scoped to Squad
Squabble's shape; generalize it or add a sibling loader if the new game's
content shape differs).

## 2. Backend: router

`src/manygameshow/routers/{game}.py`

- `APIRouter(prefix="/api/{game-slug}/games", tags=["{game-slug}"])`.
- Local helpers at the top: `_get_game` (fetch-or-404), `_save` (bump
  `updated_at`, commit, refresh), `_to_read` (build the `*Read` schema —
  this is where the model's raw fields become the resolved response shape).
- Standard CRUD: `POST /`, `GET /`, `GET /{id}`, `DELETE /{id}` (204).
  The lobby needs `GET /` (list) and `DELETE /{id}` — don't skip the
  delete endpoint even if the first cut of the UI doesn't call it yet
  (this bit us once: Squad Squabble's delete endpoint existed and was
  tested for two weeks before anything in the UI actually called it).
- One `PATCH /{id}/{action}` endpoint per state-changing action, each with
  its own small `SQLModel` request body class defined right above it
  (`RevealBody`, `AwardRoundBody`, etc.) — not a single generic "update
  game" endpoint. Validate host-only invariants here (e.g. "can't award
  more than 3 strikes") with `HTTPException`, not in the frontend.
- If an action needs to *reset* a slice of state shared by several other
  actions (new question loaded, round awarded, game reset), factor that
  into one shared private function (`_reset_round_state`) and call it from
  every place that needs it — don't duplicate the reset logic per caller.
  This is exactly the kind of thing that silently drifts otherwise (it's
  where Squad Squabble's round-score freeze bug lived: one reset path
  forgot to clear the new flag).
- Wire it into `main.py`: `app.include_router({game}.router)`.

## 3. Frontend: one self-contained HTML page

`src/manygameshow/static/{game}.html`

One file, own inline `<style>` + `<script>`, no build step, no shared JS
file between games (keeps games fully independent — nothing to break
across games by touching a shared file). Copy the `<head>`
boilerplate (font `@font-face` blocks, `:root` theme variables,
`[data-theme="..."]` overrides) from `squad-squabble.html` verbatim, then
diverge.

Required structure, in order of how central it is:

1. **View tabs** (`?view=display|control[|player]`), written to the URL so
   a refresh or a shared link restores the same tab. `switchView(v)` sets
   `currentView`, toggles `hidden` on each `#view-*` section, updates the
   URL via `history.replaceState`, and shows/hides the tab buttons
   themselves (Control should be the only place the game can be operated
   from — Display and any player view are read-only).
2. **Collapsible header on Display only** (`Hide header` → shows a small
   `#mini-header` with just a connection-status LED and a `Show header`
   button; state persisted to `localStorage`). Control always keeps the
   full header — it needs its tabs/theme-select to operate the game.
3. **Poll loop**: `async function poll()` hits `GET /api/{game}/games/{id}`
   every ~200ms via `setInterval`, tracks `failCount`, flips the
   connection badge to "Signal Lost" after 3 consecutive failures (both
   the full badge and the mini-LED), flips back on the next success.
   `state` is *only* ever replaced wholesale by a poll response — no
   independent client-side timers or counters (server is the clock).
4. **`render()`**: one function, called after every successful poll,
   that writes the current `state` into the DOM. Reuse existing DOM nodes
   where an in-place CSS transition matters (Squad Squabble's flip-card
   board rows are only rebuilt when the question itself changes; revealing
   an answer just toggles a class on the same node) — rebuilding from
   scratch every poll tick kills CSS transitions.
5. **`patch(path, body)` / `api(path, opts)` helper** wrapping `fetch` for
   control actions — one line per button (`onclick="patch('/strike')"` /
   a named wrapper function per action), not inline fetch calls scattered
   through the markup.
6. **Destructive actions require `confirm()`** (reset game, delete) —
   browser-native `confirm()`/`window.confirm`, not a custom modal. Keep
   it that simple; it's what the existing reset-game and lobby-delete
   buttons do.
7. Any one-off visual flourish (Squad Squabble's FLIP-technique strike-X
   overlay: spawn large elements at a fixed screen position, then animate
   `transform`/`opacity` to the real target element's `getBoundingClientRect()`)
   is fine to keep fully local to this file — it doesn't need to be a
   reusable pattern unless a second game actually needs the same trick.

## 4. Wire it into the lobby

`src/manygameshow/static/index.html`

- A "New {Game} Game" button that `POST`s to `/api/{game}/games/` and
  redirects straight into that game's Control view.
- Extend `loadGames()`'s per-card rendering: right now it's hardcoded to
  one game type's fields (team names/scores/round/strikes). When adding a
  second game, this needs to branch on a game-type tag per card (fetch
  each game type's list separately, or add a `game_type` discriminator) —
  **do this refactor as part of adding the second game**, don't do it
  speculatively before there's a second real shape to design it against.
- The lobby's Delete button pattern (`confirm()` → `DELETE
  /api/{game}/games/{id}` → `loadGames()`) applies to every game type the
  same way; keep it generic rather than duplicating per game type.

## 5. Tests — written first (TDD)

Write the test before the code it exercises; confirm it fails for the
right reason, then implement until it passes. This is the standing
convention for this project (see CLAUDE.md), not just a Squad Squabble
habit.

- `tests/test_models/test_{game}.py` — defaults (every field's default
  value), ID uniqueness/shape, enum values, any derived-value function
  (happy path + the zero/empty-state edge case).
- `tests/test_api/test_{game}.py` — every endpoint, happy path, plus the
  edge cases that actually matter (e.g. "already revealed" → 400,
  "index out of range" → 422). One test per behavior, not one giant
  end-to-end test.
- `tests/test_ui/test_{game}.py` — Playwright, one test per user-facing
  behavior (button click → visible DOM change), following the existing
  file's `_create_game` / `_goto_control` helper pattern. Run these
  locally before pushing (see CLAUDE.md's Playwright-in-sandbox note) —
  don't just leave it to CI to find out whether they pass.

## 6. Docs

- Add a row/section to `README.md` for the new game (what it is, any
  game-specific env var like `SQUAD_SQUABBLE_QUESTIONS_PATH`).
- If the new game's frontend needs a genuinely new UI convention (not
  covered by an existing section of UI_LOOK_AND_FEEL.md), add it there —
  that file is meant to accumulate conventions across games, not just
  describe the first one.

---

## Sequencing note

Steps 1–2 (model + router) and step 5's backend tests interleave — write
a model test, add the field it needs, write an API test, add the endpoint
it needs, repeat. Steps 3–4 (frontend) come once the API is stable enough
to build against. This mirrors how Squad Squabble was actually built and
is what makes the "idea → working game" arc demoable live.
