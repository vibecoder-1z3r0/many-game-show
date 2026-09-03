#!/usr/bin/env python3
"""Generate a turn-by-turn timing report from a Claude Code session JSONL.

Reads the session transcript the harness keeps under
~/.claude/projects/<project-slug>/<session-id>.jsonl and prints a markdown
table of each human turn with two separate timing metrics:

- "Agent time spent": wall-clock from this human message to the *last*
  assistant/tool event before the next human message — i.e. how long the
  agent was actually working on this turn.
- "Human think time": wall-clock from the *end* of agent activity to the
  *next* human message — i.e. how long the human took to read/think/type
  before replying, with the agent's own working time subtracted out (a
  slow agent response no longer inflates this number).

Usage:
    python3 scripts/session_timing.py [session_id]

If session_id is omitted, uses the most recently modified .jsonl file for
this project.
"""

import json
import sys
from datetime import datetime
from pathlib import Path


def project_slug(cwd: Path) -> str:
    return str(cwd.resolve()).replace("/", "-")


def find_transcript(session_id: str | None) -> Path:
    project_dir = Path.home() / ".claude" / "projects" / project_slug(Path.cwd())
    if session_id:
        path = project_dir / f"{session_id}.jsonl"
        if not path.exists():
            raise SystemExit(f"No transcript found at {path}")
        return path

    candidates = sorted(
        project_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    if not candidates:
        raise SystemExit(f"No .jsonl transcripts found in {project_dir}")
    return candidates[0]


def is_human_turn(entry: dict) -> bool:
    if entry.get("type") != "user":
        return False
    return entry.get("origin", {}).get("kind") == "human"


def is_agent_activity(entry: dict) -> bool:
    """True for events that represent real agent work.

    Only `assistant` entries (actual model output) and non-human `user`
    entries (tool results feeding back into the agent's own loop) count.
    Everything else — `queue-operation`, `attachment`, `system`, etc. — is
    session/harness bookkeeping that can be logged on either side of a
    turn boundary (e.g. system-reminders bundled with the *next* human
    message), so none of it should be treated as "the agent was still
    working" if left in.
    """
    entry_type = entry.get("type")
    if entry_type == "assistant":
        return True
    if entry_type == "user" and not is_human_turn(entry):
        return True
    return False


def first_text(entry: dict) -> str:
    content = entry.get("message", {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                return block.get("text", "")
    return ""


def parse_ts(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def fmt_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes:.0f}m {secs:.0f}s"
    hours, mins = divmod(minutes, 60)
    return f"{hours:.0f}h {mins:.0f}m"


# Real single-turn agent work (model + tool calls) shouldn't plausibly
# exceed this. A larger value usually means the transcript logged an
# event's timestamp near session-resume time rather than when it actually
# ran (a known JSONL quirk for some entry types) — flag it rather than
# report it as if it were real agent compute time.
AGENT_TIME_SANITY_THRESHOLD_SECONDS = 30 * 60

# "Human think time" over this is treated as an outlier — the human
# stepped away (reading, a break, a resumed session days later) rather
# than genuinely "thinking" between turns. Excluded from BOTH the total
# and the average so a handful of long gaps don't dominate either; still
# shown per-row and counted.
THINK_TIME_OUTLIER_THRESHOLD_SECONDS = 15 * 60


def main() -> None:
    session_id = sys.argv[1] if len(sys.argv) > 1 else None
    path = find_transcript(session_id)

    entries = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    timestamped = [e for e in entries if e.get("timestamp")]
    timestamped.sort(key=lambda e: e["timestamp"])

    # Build turns: each starts at a human message, ends (agent-time-wise) at
    # the last *agent-activity* event timestamp before the next human
    # message (see is_agent_activity — bookkeeping types like
    # queue-operation/attachment/system are excluded since they can be
    # logged on either side of a turn boundary, e.g. reminders bundled with
    # the *next* human message, which would otherwise falsely stretch this
    # turn's end).
    turns = []
    current = None
    for entry in timestamped:
        if is_human_turn(entry):
            if current is not None:
                turns.append(current)
            current = {
                "prompt": first_text(entry).strip().replace("\n", " "),
                "start": entry["timestamp"],
                "last_activity": entry["timestamp"],
            }
        elif current is not None and is_agent_activity(entry):
            current["last_activity"] = entry["timestamp"]
    if current is not None:
        turns.append(current)

    print(f"# Session Timing Report\n\nSource: `{path}`\n")
    print(
        "| # | Prompt (truncated) | Started (UTC) | Agent time spent | "
        "Human think time |"
    )
    print("|---|---|---|---|---|")

    total_agent_seconds = 0.0
    flagged_agent_seconds = 0.0
    total_think_seconds = 0.0  # excludes think-time outliers
    think_count = 0
    flagged_turns = []
    think_outlier_turns = []
    think_outlier_seconds = 0.0
    for i, t in enumerate(turns, 1):
        start = parse_ts(t["start"])
        last_activity = parse_ts(t["last_activity"])
        agent_seconds = (last_activity - start).total_seconds()

        suspicious = agent_seconds > AGENT_TIME_SANITY_THRESHOLD_SECONDS
        if suspicious:
            flagged_turns.append(i)
            flagged_agent_seconds += agent_seconds
        else:
            total_agent_seconds += agent_seconds

        if i < len(turns):
            next_start = parse_ts(turns[i]["start"])
            # Human think time = gap between messages MINUS the agent's own
            # working time — a slow agent response should never count
            # against the human's pacing.
            think_seconds = (next_start - last_activity).total_seconds()

            is_think_outlier = think_seconds > THINK_TIME_OUTLIER_THRESHOLD_SECONDS
            if is_think_outlier:
                think_outlier_turns.append(i)
                think_outlier_seconds += think_seconds
            else:
                total_think_seconds += think_seconds
                think_count += 1

            think_str = fmt_duration(think_seconds) + (
                " ⏳" if is_think_outlier else ""
            )
        else:
            think_str = "—"  # last turn has no "next message" yet

        prompt = t["prompt"][:70] + ("…" if len(t["prompt"]) > 70 else "")
        prompt = prompt.replace("|", "\\|")
        agent_str = fmt_duration(agent_seconds) + (" ⚠" if suspicious else "")
        print(
            f"| {i} | {prompt} | {start.strftime('%H:%M:%S')} "
            f"| {agent_str} | {think_str} |"
        )

    avg_think = total_think_seconds / think_count if think_count else 0.0
    print(
        f"\n**Total turns:** {len(turns)}  \n"
        f"**Total agent time spent (excl. flagged):** "
        f"{fmt_duration(total_agent_seconds)}  \n"
        f"**Total human think time (excl. outliers):** "
        f"{fmt_duration(total_think_seconds)}  \n"
        f"**Average human think time (excl. outliers):** "
        f"{fmt_duration(avg_think)}  \n"
        f"**Think-time outliers (> "
        f"{THINK_TIME_OUTLIER_THRESHOLD_SECONDS // 60} min):** "
        f"{len(think_outlier_turns)}"
    )
    if flagged_turns:
        print(
            f"\n⚠ Turn(s) {', '.join(str(n) for n in flagged_turns)} had an "
            f"'agent time spent' over "
            f"{AGENT_TIME_SANITY_THRESHOLD_SECONDS // 60} min "
            f"(total {fmt_duration(flagged_agent_seconds)}), which is "
            f"implausible as real agent work — likely a transcript entry "
            f"logged near session-resume time rather than when it actually "
            f"ran. Excluded from the agent-time total above."
        )
    if think_outlier_turns:
        print(
            f"\n⏳ Turn(s) {', '.join(str(n) for n in think_outlier_turns)} had a "
            f"'human think time' over "
            f"{THINK_TIME_OUTLIER_THRESHOLD_SECONDS // 60} min "
            f"(total {fmt_duration(think_outlier_seconds)}) — likely a break, "
            f"a resumed session, or time reading a long response rather than "
            f"active back-and-forth. Excluded from BOTH the total and the "
            f"average above (still shown per-row)."
        )


if __name__ == "__main__":
    main()
