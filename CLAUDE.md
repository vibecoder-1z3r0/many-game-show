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
