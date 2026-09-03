# UI Look & Feel

Visual and UX conventions for Many Game Show, adapted from the `many-board`
scoreboard app's frontend patterns. No frontend framework, no build step —
vanilla HTML/CSS/JS served as static files, same as the reference app.

---

## Design Goals

- Readable at a glance from across a room (big text, high contrast) —
  this is a "screen at the front, phone in the host's hand" app.
- Works unmodified on a phone, tablet, or a projector/TV.
- No layout breakage if the network hiccups — always show *something*,
  plus a clear signal when data is stale.

---

## View Types

Every game/round gets (at least) two kinds of view, same split as the
reference app:

| View type | Audience | Behavior |
|---|---|---|
| **Display view** | Projected / big screen, read-only | Polls for state, renders big, no controls |
| **Control view** | Host/operator, on a phone or laptop | Interactive buttons that PATCH state |

Optional third type if a game needs it: a **player/buzzer view** (read-only
status + a single action, e.g. "buzz in").

A tab/segment switcher lets one HTML page hold multiple views for the same
game (mirrors `football.html` / `baseball.html` having Display / Box Score /
Control / Ref tabs). The active tab is written to the URL as `?view=...` so
a refresh (or someone else opening the link) restores the same tab.

---

## Theming

- Theme choice is stored in `localStorage`, applied via a `data-theme`
  attribute on `<html>`, and controlled by a `<select>` present in every
  header.
- Colors are CSS custom properties defined on `:root` (`--bg`, `--panel`,
  `--text`, `--accent`, etc.), with per-theme overrides scoped under
  `[data-theme="..."]`.
- Default component styling should use the CSS vars so it inherits
  whichever theme is active.
- A view with a strong genre-specific look (e.g. a "game show set" aesthetic
  for one particular game) can add a `[data-theme="X"]`-scoped override block
  so it looks purpose-built in the matching theme, while still degrading
  gracefully to plain themed styling in the others. Never hardcode a look
  that only works in one theme.
- Semantic colors that mean the same thing everywhere (correct/green,
  wrong/red, buzzer/blue, connection lost/red) are hardcoded, not themed —
  consistent signal color matters more than theme purity here.

Suggested starting theme set (rename to fit the actual show once the format
is picked): `default`, `stage` (dark, spotlight-style), `bright` (high
color, daytime/outdoor).

---

## Typography

- A distinct display font (Orbitron) for scores/numbers/big countdown
  text — anything meant to be read from a distance. **Self-host the font
  file** (serve it from `/fonts/`, `@font-face` with a local `src`)
  rather than loading it live from Google Fonts or any other CDN — this
  app is explicitly designed to survive flaky conference wifi, and a
  live font fetch is exactly the kind of dependency that undermines
  that. Squad Squabble ships `orbitron-600.ttf` / `orbitron-800.ttf`
  under `static/fonts/`; follow the same pattern for any new game.
- Body/UI text uses a plain system font stack for legibility in dense
  control views.

---

## Responsive Sizing

- Display views use `clamp(min, preferred, max)` for font sizes and
  spacing instead of media query breakpoints, so the same markup scales
  from phone to tablet to TV without a distinct mobile layout.
- Control views can be denser/fixed-size since they're operated on a known
  device (host's phone/laptop), but should still not require horizontal
  scrolling on a phone.

---

## Connection Status

Every polling view shows a small connected/disconnected indicator:

- Track `failCount` across poll attempts.
- After 3 consecutive failures, flip to a red "Signal Lost" (or similar)
  badge in the header.
- On the next successful poll, flip back to a green "Connected" badge.

This is cheap to implement and matters a lot for a conference-wifi
environment — the audience should see "we know we're disconnected," never
a silently frozen screen.

---

## Rendering Model

- `state` = the raw parsed JSON from the last successful poll. No other
  client-side mutable game state.
- `render()` runs after every successful poll and after every control
  action (optimistic re-render is optional; source of truth is always the
  next poll response).
- No client-side timers/counters that run independently of the server
  (see ARCHITECTURE.md — server is the clock/state source of truth).

---

## Layout Conventions

- Single self-contained `.html` file per game, each with its own inline
  `<style>` and `<script>` — matches the reference app's per-sport pages.
  Keeps each game's view fully independent; nothing to accidentally break
  across games.
- A lobby/index page lists active games/rounds, links into each one's
  views, and polls slowly (~1s) since it's just a list, not a live view.
