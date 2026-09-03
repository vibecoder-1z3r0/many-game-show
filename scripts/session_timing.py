#!/usr/bin/env python3
"""Generate a turn-by-turn timing report from a Claude Code session JSONL.

Reads the session transcript the harness keeps under
~/.claude/projects/<project-slug>/<session-id>.jsonl and prints a markdown
table of each human turn with two separate timing metrics:

- "Time to next message": wall-clock from this human message to the *next*
  human message. Includes any gap while the human is reading/thinking/typing
  (and can be huge if the conversation was resumed after a long break).
- "Agent time spent": wall-clock from this human message to the *last*
  assistant/tool event before the next human message — i.e. how long the
  agent was actually working on this turn, excluding the trailing gap.

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
        "Time to next message |"
    )
    print("|---|---|---|---|---|")

    total_agent_seconds = 0.0
    flagged_agent_seconds = 0.0
    total_cycle_seconds = 0.0
    cycle_count = 0
    flagged_turns = []
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
            cycle_seconds = (next_start - start).total_seconds()
            total_cycle_seconds += cycle_seconds
            cycle_count += 1
            cycle_str = fmt_duration(cycle_seconds)
        else:
            cycle_str = "—"  # last turn has no "next message" yet

        prompt = t["prompt"][:70] + ("…" if len(t["prompt"]) > 70 else "")
        prompt = prompt.replace("|", "\\|")
        agent_str = fmt_duration(agent_seconds) + (" ⚠" if suspicious else "")
        print(
            f"| {i} | {prompt} | {start.strftime('%H:%M:%S')} "
            f"| {agent_str} | {cycle_str} |"
        )

    avg_cycle = total_cycle_seconds / cycle_count if cycle_count else 0.0
    print(
        f"\n**Total turns:** {len(turns)}  \n"
        f"**Total agent time spent (excl. flagged):** "
        f"{fmt_duration(total_agent_seconds)}  \n"
        f"**Total time to next message (excl. last turn):** "
        f"{fmt_duration(total_cycle_seconds)}  \n"
        f"**Average time to next message:** {fmt_duration(avg_cycle)}"
    )
    if flagged_turns:
        print(
            f"\n⚠ Turn(s) {', '.join(str(n) for n in flagged_turns)} had an "
            f"'agent time spent' over "
            f"{AGENT_TIME_SANITY_THRESHOLD_SECONDS // 60} min "
            f"(total {fmt_duration(flagged_agent_seconds)}), which is "
            f"implausible as real agent work — likely a transcript entry "
            f"logged near session-resume time rather than when it actually "
            f"ran. Excluded from the agent-time total above; 'time to next "
            f"message' is unaffected since that metric is expected to "
            f"include idle gaps."
        )


if __name__ == "__main__":
    main()
