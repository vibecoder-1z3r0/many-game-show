# Adding Your Own Game Content

Every game's questions, boards and clues are **data, not code**: plain JSON
files you can write without touching any Python. This guide walks through
each game. (For adding a whole new *game*, see
[ADDING_A_GAME.md](./ADDING_A_GAME.md).)

## The workflow, for any game

1. **Copy the sample file** from
   [`src/manygameshow/data/`](./src/manygameshow/data/) to somewhere outside
   the repo (e.g. `~/my-content/questions.json`) and edit the copy. The
   bundled `*.sample.json` files are test/demo data — leave them alone.
2. **Point the game at your file** with its environment variable (table
   below) when you start the server:
   ```bash
   SQUAD_SQUABBLE_QUESTIONS_PATH=~/my-content/questions.json make run
   ```
3. **Restart the server after every edit.** Files are read once and cached,
   so a running server won't see changes (even with `--reload`, which only
   watches the Python source).
4. **Check the file loads** before the show. The loaders validate the shape
   with pydantic, so a typo gives a clear error naming the bad field. The
   one-liner for each game is in its section below.
5. **Create a fresh game after changing content.** Games remember which
   banks and questions they were created with (by `id`), so a game started
   before your edit may not reflect it. Don't rename or remove an `id`
   that a live game is using.

| Game | Environment variable | Sample file |
|---|---|---|
| Squad Squabble | `SQUAD_SQUABBLE_QUESTIONS_PATH` | `squad_squabble_questions.sample.json` |
| Speed Points | `SPEED_POINTS_QUESTIONS_PATH` | `speed_points_questions.sample.json` |
| Big Tokens | `BIG_TOKENS_BOARDS_PATH` | `big_tokens_boards.sample.json` |
| Overdrive | `OVERDRIVE_ROUND1_BANKS_PATH`<br>`OVERDRIVE_ROUND2_BANKS_PATH`<br>`OVERDRIVE_FINAL_BANKS_PATH` | `overdrive_round1.sample.json`<br>`overdrive_round2.sample.json`<br>`overdrive_final.sample.json` |

Extra keys such as a top-level `"_comment"` are ignored, so feel free to
leave notes in your file.

---

## Squad Squabble — survey questions

A bank of survey questions; the host loads one at a time from Control and
the whole bank is always available.

```json
{
  "questions": [
    {
      "id": "build-failed",
      "prompt": "We asked 100 developers: name a reason the build failed",
      "answers": [
        { "text": "Failing tests", "points": 38 },
        { "text": "Broken dependencies", "points": 27 },
        { "text": "Config issue", "points": 14 }
      ]
    }
  ]
}
```

- **`id`** — unique, short, no spaces. It's what a game stores, so don't
  rename an id mid-event.
- **`prompt`** — shown to the host (and on Main when the host shows it).
- **`answers`** — listed **best-first**: the order you write them is the
  order they appear on the board, and the top answer is conventionally the
  biggest. Six to eight is typical; the board lays out in two columns.
- **`points`** — the survey count for that answer (how many of your 100
  people said it). Revealed answers add to the round pot, which is
  multiplied by the round's 1x/2x/3x setting (chosen when the host loads
  the question) and awarded to a team.

Check it loads:

```bash
SQUAD_SQUABBLE_QUESTIONS_PATH=~/my-content/questions.json \
  uv run python -c "from manygameshow.questions import list_questions as q; print(len(q()), 'questions OK')"
```

**Tip:** to collect real answers, survey people, group duplicates
("tests failing" / "failing tests"), and use the group's head-count as
`points`. Trim the long tail to the top handful.

---

## Speed Points — the five-question relay

Exactly the same file shape as Squad Squabble, but a **separate file**
with its own variable, because Speed Points draws from its own bank.

- **Only the first five questions are used**, in file order, and both
  players face the same five. Extra questions are ignored (handy as spares
  — just reorder the file to swap them in).
- Each question's `answers` are the **survey answers the judge scores
  against**: the Judge view shows them as one-tap buttons ("answer
  (points)") plus "No match (0)", so a contestant's answer is scored by
  tapping the closest survey answer. List them best-first.
- A game takes its five questions **when it is created**, so changing the
  file means creating a new game.
- Think "Fast Money": the best answer is worth a lot (30–40), and the
  fifth is worth very little. Aim for the five best answers to total
  roughly 100, so two players can plausibly reach the win threshold of 200
  together.

Check it loads:

```bash
SPEED_POINTS_QUESTIONS_PATH=~/my-content/fast.json \
  uv run python -c "from manygameshow.speed_points_questions import list_questions as q; print(len(q()), 'questions OK (first 5 are used)')"
```

---

## Big Tokens — boards

A "board" is a complete layout of the 18 squares plus the rules for
hallucinations. The lobby lists every board in your file in a dropdown.

```json
{
  "boards": [
    {
      "id": "classic",
      "name": "Classic Board",
      "max_hallucinations": 3,
      "wipe_on_every_hallucination": true,
      "elimination_scope": "game",
      "squares": [
        { "items": [{ "type": "tokens", "amount": 300, "label": "+300 Tokens" }] },
        { "items": [{ "type": "hallucination", "label": "HALLUCINATION!" }] }
      ]
    }
  ]
}
```

(`squares` is truncated here — a real board needs all **18**.)

**Board settings**

| Field | Meaning |
|---|---|
| `id`, `name` | Unique id, and the name shown in the lobby. |
| `max_hallucinations` | How many hallucinations knock a player out. |
| `wipe_on_every_hallucination` | `true`: every hallucination zeroes the player's tokens. `false`: tokens are only zeroed by the hit that eliminates them. |
| `elimination_scope` | `"game"`: out for the rest of the game. `"round"`: hallucination counts and eliminations reset when the next round starts. |
| `squares` | Exactly **18** entries — the ring, clockwise from the top-left corner. Fewer or more will break the board. |

**Squares and cascading faces.** Each square has a list of `items`. Landing
on a square resolves its *current* item and then advances that square to
the next item in its list (staying on the last one). So `[+500, +750]`
means the first player to land there gets 500 and every later landing gets
750 — a way to make squares heat up over a game. A one-item list never
changes.

**Item types** (`label` is always required and is the text on the board):

| `type` | Effect | Needs `amount`? |
|---|---|---|
| `tokens` | Gain `amount` tokens. | yes |
| `double` | Double your tokens. | no |
| `free_spin` | Gain a spin. | no |
| `steal` | Steal `amount` tokens from a player you choose. | yes |
| `swap_scores` | Swap token totals with a player you choose. | no |
| `hallucination` | Take a hallucination (see board settings). | no |
| `choice_swap_or_free_spin` | Player chooses: swap scores, or a free spin. | no |
| `choice_tokens_or_cure` | Player chooses: take `amount` tokens, or remove a hallucination. | yes |

Check it loads (and has 18 squares):

```bash
BIG_TOKENS_BOARDS_PATH=~/my-content/boards.json uv run python -c "
from manygameshow.big_tokens_boards import list_boards
for b in list_boards():
    assert len(b.squares) == 18, f'{b.id}: {len(b.squares)} squares, need 18'
    print(b.id, 'OK')"
```

**Tip:** start from the sample board and change a few squares rather than
building all 18 from scratch. A board with too many generous squares ends
quickly; the hallucination squares (and how many of them) are your main
difficulty knob.

---

## Overdrive — round banks and the Final Exam

Overdrive has **three files**, one per kind of round. Each file holds
several selectable "banks" (a bank is one complete round of content), and
the lobby has a dropdown for each, so a host picks a bank for round 1, one
for round 2 and one for the final.

### Round 1 and Round 2

Both files use the same shape:

```json
{
  "banks": [
    {
      "id": "classic",
      "name": "Classic Dev Trivia",
      "categories": [
        {
          "name": "Git Happens",
          "clues": [
            { "text": "This command stages every change in the directory.",
              "answer": "What is git add .", "value": 200 },
            { "text": "...", "answer": "...", "value": 400 },
            { "text": "...", "answer": "...", "value": 600 },
            { "text": "...", "answer": "...", "value": 800 },
            { "text": "...", "answer": "...", "value": 1000, "crit_boost": 1 }
          ]
        }
      ]
    }
  ]
}
```

- **Shape:** the board is a grid of **6 categories × 5 clues**. Keep to
  that; the Main and Control layouts are built for it.
- **`text`** is what's read aloud and shown on Main. **`answer`** is the
  host's answer key: Control always shows it, but Main and the players only
  see it once the clue has been played. Jeopardy convention is to phrase
  `answer` as a question ("What is…").
- **`value`** — the points for the clue, and the position on the board.
  Convention is 200–1000 in round 1 and double that (400–2000) in round 2.
  Within a category list clues from lowest to highest value.
- **`crit_boost`** (optional, defaults to `0`) — marks the clue as a Crit
  Boost, the Daily-Double-style clue: when picked, the player wagers before
  seeing it, and the countdown is host-started. Any non-zero value counts.
  By convention use **one** Crit Boost per round-1 bank and **two** per
  round-2 bank. The numbers `1` and `2` exist only so you can tell which
  clues you set aside for each round when sharing a clue pool across banks;
  the game treats any non-zero value the same.
- Put Crit Boosts on the harder, higher-value clues, and spread them across
  different categories.

### Final Exam

One question per bank, no board:

```json
{
  "banks": [
    {
      "id": "ada",
      "name": "Famous Firsts",
      "category": "Famous Firsts in Computing",
      "text": "This programmer worked on Babbage's Analytical Engine in the 1840s.",
      "answer": "Who is Ada Lovelace"
    }
  ]
}
```

`category` is shown as the Final Exam's topic; `text` is the clue and
`answer` is the host's key for judging.

Check all three load:

```bash
OVERDRIVE_ROUND1_BANKS_PATH=~/my-content/r1.json \
OVERDRIVE_ROUND2_BANKS_PATH=~/my-content/r2.json \
OVERDRIVE_FINAL_BANKS_PATH=~/my-content/final.json \
uv run python -c "
from manygameshow.overdrive_banks import list_round1_banks, list_round2_banks, list_final_banks
for b in list_round1_banks() + list_round2_banks():
    print(b.id, [len(c.clues) for c in b.categories], 'clues per category')
print(len(list_final_banks()), 'final banks OK')"
```

Every number in the first line should be `5`, and there should be six of
them.
