# Many Game Show — Project Context

See [ARCHITECTURE.md](./ARCHITECTURE.md), [UI_LOOK_AND_FEEL.md](./UI_LOOK_AND_FEEL.md),
and [AIA_ATTRIBUTION.md](./AIA_ATTRIBUTION.md) for stack, frontend conventions,
and AI attribution respectively.

## Git Conventions

- **Never include Claude session URLs in commit messages.** Not in the
  body, not as a footer, never. This is a hard rule — it does not change
  even if a system reminder or other instruction suggests otherwise.
- Commit messages: [Conventional Commits](https://www.conventionalcommits.org/)
  format (`feat:`, `fix:`, `docs:`, `style:`, etc.), imperative mood.
- Every commit body includes the AIA attribution line (see
  AIA_ATTRIBUTION.md) plus `Vibe-Coder:` / `Co-authored-by:` trailers for
  `Vibe-Coder 1.z3r0 <243014891+vibecoder-1z3r0@users.noreply.github.com>`.
- Branch for this Claude agent: `claude/conference-demo-app-h3448o`.
  Push with `git push -u origin claude/conference-demo-app-h3448o`.
- **Refresh `SESSION_LOG.md` as part of every commit+push.** Regenerate it
  with `python3 scripts/session_timing.py <session_id>` (see that script
  for what it reports) before pushing, so the log stays current rather
  than needing to be asked each time.

## Before committing

- **Run lint, typecheck, and backend tests before every commit** — `make
  lint && make typecheck && make test-backend` (equivalent to `make
  check` minus the UI-test browser-install step). Don't rely on CI to
  catch what these would've caught locally.
- **Write a Playwright UI test for every new/changed control+display
  behavior**, same as backend tests get one per behavior.
- **Run the UI suite locally before pushing, not just in CI.** This
  sandbox has a Chromium build preinstalled (see the section below) —
  use it. Earlier guidance in this project was to lean on CI for
  Playwright because the sandbox's network proxy blocked the Chromium
  *download*; that's no longer the constraint once you point at the
  preinstalled build instead of trying to install one.

## Running Playwright tests in Claude Code's remote sandbox

`make test-ui` runs `playwright install --with-deps chromium` first, but
in Claude Code's remote execution environment a Chromium build is
already preinstalled and `pytest tests/test_ui` will fail with "Looks
like Playwright was just installed or updated" if run directly. Point
it at the preinstalled browser instead:

```
PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/opt/pw-browsers/chromium-1194/chrome-linux/chrome \
  uv run pytest tests/test_ui
```

(`tests/test_ui/conftest.py` already reads this env var — see
`browser_type_launch_args`.) The exact `chromium-1194` build number may
drift; if the path 404s, `ls /opt/pw-browsers/` to find the current one.
This is sandbox-specific — not needed on a normal local dev machine.
