# AI Attribution (AIA)

This project uses the [AI Attribution](https://aiattribution.github.io/)
standard to disclose how AI was involved in each commit.

Note: the AIA site itself (`aiattribution.github.io`) is not reachable from
this session's network (egress blocked), so the statement below is taken
verbatim from the badge/SVG the project owner supplied, not re-derived from
the spec page. If the exact field meanings ever need double-checking,
verify against the live site directly.

---

## Statement used for this project

Full statement, as issued by the project owner's AIA badge:

```
AIA Primarily AI, Stylistic edits, Content edits, New content, Human-initiated, Reviewed, Claude Code Web Sonnet 5 Medium v1.0
```

Abbreviated form (used in commit messages, where space is tighter):

```
AIA PAI SeCeNc Hin R Claude Code Web Sonnet 5 Medium v1.0
```

| Segment | Abbrev. | Meaning |
|---|---|---|
| `AIA` | `AIA` | AI Attribution tag prefix |
| Primarily AI | `PAI` | Collaboration type — AI produced most of the content |
| Stylistic edits | `Se` | AI made wording/formatting-level edits |
| Content edits | `Ce` | AI made substantive edits to existing content |
| New content | `Nc` | AI generated new content from scratch |
| Human-initiated | `Hin` | Work started from a human request/prompt |
| Reviewed | `R` | A human reviewed the AI's output before it was committed |
| `Claude Code Web` | — | Interface used |
| `Sonnet 5` | — | Model used |
| `Medium` | — | Effort/capability tier used for the session |
| `v1.0` | — | AIA spec version |

Swap `Sonnet 5` / `Medium` / `Claude Code Web` if a future commit is made
with a different model, effort tier, or interface — keep the rest of the
string as issued.

---

## How it's applied

Every commit where Claude authored or materially edited the content
includes the full statement as a line in the commit body, e.g.:

```
docs: add architecture and UI look-and-feel specs

<body explaining the change>

AIA PAI SeCeNc Hin R Claude Code Web Sonnet 5 Medium v1.0

Vibe-Coder: <human name> <<human email>>
Co-authored-by: <human name> <<human email>>
```

Combined with the project's existing git convention (see CLAUDE.md-style
rules, once we add one): **never** include a `claude.ai/code/session_...`
URL in any commit. AIA attribution and session-link avoidance are separate
rules — the former discloses AI involvement, the latter avoids leaking a
private session URL into public git history.
