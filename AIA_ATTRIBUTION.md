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

This is the **abbreviated** statement, as issued by the project owner's AIA
badge:

```
AIA PAI SeCeNc Hin R Claude Code Web Sonnet 5 Medium v1.0
```

| Segment | Meaning |
|---|---|
| `AIA` | AI Attribution tag prefix |
| `PAI` | Collaboration type for this project (as issued by the project owner's AIA badge) |
| `SeCeNc` | Contribution flags: **S**tylistic **e**dits, **C**ontent **e**dits, **N**ew **c**ontent — all present, since AI both drafts and edits |
| `Hin` | **H**uman-**in**itiated — work starts from a human request/prompt |
| `R` | **R**eviewed — a human reviews the AI's output before it's committed |
| `Claude Code Web` | Interface used |
| `Sonnet 5` | Model used |
| `Medium` | Effort/capability tier used for the session |
| `v1.0` | AIA spec version |

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
