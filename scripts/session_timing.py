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

Also sums per-turn token usage (input/output/cache-write/cache-read),
summed across every assistant round-trip within that turn's boundary.

Usage:
    python3 scripts/session_timing.py [session_id]
    python3 scripts/session_timing.py [session_id] \\
        --skip-duplicate N --prior-summary path/to/prior.json

--skip-duplicate N: this transcript's first N turns are known duplicates
of turns already counted in a prior (frozen) log file — e.g. after a
container reset replayed a tail of the old transcript into a new JSONL.
Combined with --prior-summary, prints an extra "Combined Summary" section
that adds the frozen file's totals to *only* the turns after that
boundary, so the overlap isn't double-counted. The main per-turn table
still prints every row regardless, for a full transparent history.

--prior-summary PATH: a small JSON file with the frozen prior file's
totals: {"turns": int, "agent_seconds": number, "think_seconds": number,
"think_outliers": int}. These necessarily come from that file's
already-printed (rounded) footer, not raw data — the frozen file's own
source JSONL no longer has full precision available (that's the point of
freezing it), so the combined totals below are an approximation, not an
exact recomputation.
"""

import argparse
import json
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
    return bool(entry.get("origin", {}).get("kind") == "human")


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


def usage_of(entry: dict) -> dict[str, int]:
    """Token usage for one assistant event, zeroed out if absent (tool-result
    'user' events that count as agent activity carry no usage of their own)."""
    usage = entry.get("message", {}).get("usage") or {}
    return {
        "input": usage.get("input_tokens", 0),
        "output": usage.get("output_tokens", 0),
        "cache_write": usage.get("cache_creation_input_tokens", 0),
        "cache_read": usage.get("cache_read_input_tokens", 0),
    }


def first_text(entry: dict) -> str:
    content = entry.get("message", {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                return str(block.get("text", ""))
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


def load_turns(path: Path) -> list[dict]:
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
    turns: list[dict] = []
    current = None
    for entry in timestamped:
        if is_human_turn(entry):
            if current is not None:
                turns.append(current)
            current = {
                "prompt": first_text(entry).strip().replace("\n", " "),
                "start": entry["timestamp"],
                "last_activity": entry["timestamp"],
                "usage": {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0},
            }
        elif current is not None and is_agent_activity(entry):
            current["last_activity"] = entry["timestamp"]
            # A turn can involve many assistant round-trips (tool-call
            # loops) before the human sees a reply — sum all of them so
            # this turn's token cost reflects the whole exchange, not just
            # the final message.
            if entry.get("type") == "assistant":
                turn_usage = usage_of(entry)
                for key, value in turn_usage.items():
                    current["usage"][key] += value
    if current is not None:
        turns.append(current)
    return turns


def summarize(turns: list[dict], offset: int = 0) -> dict:
    """Compute the same totals the footer prints, over `turns` (a slice is
    fine — `offset` is only used to report correct 1-based turn numbers in
    the outlier/flagged lists)."""
    total_agent_seconds = 0.0
    flagged_agent_seconds = 0.0
    total_think_seconds = 0.0
    think_count = 0
    flagged_turns = []
    think_outlier_turns = []
    think_outlier_seconds = 0.0
    total_usage = {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0}

    for i, t in enumerate(turns, 1):
        start = parse_ts(t["start"])
        last_activity = parse_ts(t["last_activity"])
        agent_seconds = (last_activity - start).total_seconds()

        suspicious = agent_seconds > AGENT_TIME_SANITY_THRESHOLD_SECONDS
        if suspicious:
            flagged_turns.append(offset + i)
            flagged_agent_seconds += agent_seconds
        else:
            total_agent_seconds += agent_seconds

        if i < len(turns):
            next_start = parse_ts(turns[i]["start"])
            think_seconds = (next_start - last_activity).total_seconds()
            is_think_outlier = think_seconds > THINK_TIME_OUTLIER_THRESHOLD_SECONDS
            if is_think_outlier:
                think_outlier_turns.append(offset + i)
                think_outlier_seconds += think_seconds
            else:
                total_think_seconds += think_seconds
                think_count += 1

        for key in total_usage:
            total_usage[key] += t["usage"][key]

    return {
        "turns": len(turns),
        "agent_seconds": total_agent_seconds,
        "flagged_agent_seconds": flagged_agent_seconds,
        "flagged_turns": flagged_turns,
        "think_seconds": total_think_seconds,
        "think_count": think_count,
        "think_outlier_turns": think_outlier_turns,
        "think_outlier_seconds": think_outlier_seconds,
        "usage": total_usage,
    }


def print_report(turns: list[dict], path: Path) -> None:
    print(f"# Session Timing Report\n\nSource: `{path}`\n")
    print(
        "| # | Prompt (truncated) | Started (UTC) | Agent time spent | "
        "Human think time | Input | Output | Cache Write | Cache Read |"
    )
    print("|---|---|---|---|---|---|---|---|---|")

    for i, t in enumerate(turns, 1):
        start = parse_ts(t["start"])
        last_activity = parse_ts(t["last_activity"])
        agent_seconds = (last_activity - start).total_seconds()
        suspicious = agent_seconds > AGENT_TIME_SANITY_THRESHOLD_SECONDS

        if i < len(turns):
            next_start = parse_ts(turns[i]["start"])
            think_seconds = (next_start - last_activity).total_seconds()
            is_think_outlier = think_seconds > THINK_TIME_OUTLIER_THRESHOLD_SECONDS
            think_str = fmt_duration(think_seconds) + (
                " ⏳" if is_think_outlier else ""
            )
        else:
            think_str = "—"  # last turn has no "next message" yet

        prompt = t["prompt"][:70] + ("…" if len(t["prompt"]) > 70 else "")
        prompt = prompt.replace("|", "\\|")
        agent_str = fmt_duration(agent_seconds) + (" ⚠" if suspicious else "")
        u = t["usage"]
        print(
            f"| {i} | {prompt} | {start.strftime('%H:%M:%S')} "
            f"| {agent_str} | {think_str} "
            f"| {u['input']:,} | {u['output']:,} | {u['cache_write']:,} "
            f"| {u['cache_read']:,} |"
        )

    s = summarize(turns)
    avg_think = s["think_seconds"] / s["think_count"] if s["think_count"] else 0.0
    prompt_side = (
        s["usage"]["input"] + s["usage"]["cache_write"] + s["usage"]["cache_read"]
    )
    cache_hit_ratio = s["usage"]["cache_read"] / prompt_side if prompt_side else 0.0
    print(
        f"\n**Total turns:** {s['turns']}  \n"
        f"**Total agent time spent (excl. flagged):** "
        f"{fmt_duration(s['agent_seconds'])}  \n"
        f"**Total human think time (excl. outliers):** "
        f"{fmt_duration(s['think_seconds'])}  \n"
        f"**Average human think time (excl. outliers):** "
        f"{fmt_duration(avg_think)}  \n"
        f"**Think-time outliers (> "
        f"{THINK_TIME_OUTLIER_THRESHOLD_SECONDS // 60} min):** "
        f"{len(s['think_outlier_turns'])}  \n"
        f"**Total input tokens:** {s['usage']['input']:,}  \n"
        f"**Total output tokens:** {s['usage']['output']:,}  \n"
        f"**Total cache-write tokens:** {s['usage']['cache_write']:,}  \n"
        f"**Total cache-read tokens:** {s['usage']['cache_read']:,}  \n"
        f"**Cache hit ratio (cache-read ÷ all prompt-side tokens):** "
        f"{cache_hit_ratio:.0%}"
    )
    if s["flagged_turns"]:
        print(
            f"\n⚠ Turn(s) {', '.join(str(n) for n in s['flagged_turns'])} had an "
            f"'agent time spent' over "
            f"{AGENT_TIME_SANITY_THRESHOLD_SECONDS // 60} min "
            f"(total {fmt_duration(s['flagged_agent_seconds'])}), which is "
            f"implausible as real agent work — likely a transcript entry "
            f"logged near session-resume time rather than when it actually "
            f"ran. Excluded from the agent-time total above."
        )
    if s["think_outlier_turns"]:
        print(
            f"\n⏳ Turn(s) {', '.join(str(n) for n in s['think_outlier_turns'])} had "
            f"a 'human think time' over "
            f"{THINK_TIME_OUTLIER_THRESHOLD_SECONDS // 60} min "
            f"(total {fmt_duration(s['think_outlier_seconds'])}) — likely a "
            f"break, a resumed session, or time reading a long response "
            f"rather than active back-and-forth. Excluded from BOTH the "
            f"total and the average above (still shown per-row)."
        )


def print_combined_summary(
    turns: list[dict], skip_duplicate: int, prior_summary_path: Path
) -> None:
    prior = json.loads(prior_summary_path.read_text())
    new_turns = turns[skip_duplicate:]
    s = summarize(new_turns, offset=skip_duplicate)

    combined_turns = prior["turns"] + s["turns"]
    combined_agent_seconds = prior["agent_seconds"] + s["agent_seconds"]
    combined_think_seconds = prior["think_seconds"] + s["think_seconds"]
    combined_think_outliers = prior["think_outliers"] + len(s["think_outlier_turns"])

    print("\n---\n")
    print(
        f"## Combined Summary (whole session, both files)\n\n"
        f"Adds this file's turns after row {skip_duplicate} (the "
        f"known-duplicate boundary) to {prior_summary_path.name}'s frozen "
        f"totals. The frozen side is only as precise as that file's "
        f"already-rounded footer — its raw source data no longer exists —"
        f" so treat this as an approximation, not an exact recomputation.\n"
    )
    print(
        f"**Combined total turns:** {combined_turns}  \n"
        f"**Combined agent time spent (excl. flagged):** "
        f"{fmt_duration(combined_agent_seconds)}  \n"
        f"**Combined human think time (excl. outliers):** "
        f"{fmt_duration(combined_think_seconds)}  \n"
        f"**Combined think-time outliers:** {combined_think_outliers}  \n"
        f"**Total input tokens (since tracking began, this file only):** "
        f"{s['usage']['input']:,}  \n"
        f"**Total output tokens (since tracking began, this file only):** "
        f"{s['usage']['output']:,}  \n"
        f"**Total cache-write tokens (since tracking began, this file "
        f"only):** {s['usage']['cache_write']:,}  \n"
        f"**Total cache-read tokens (since tracking began, this file "
        f"only):** {s['usage']['cache_read']:,}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session_id", nargs="?", default=None)
    parser.add_argument(
        "--skip-duplicate",
        type=int,
        default=None,
        help="This transcript's first N turns duplicate a prior frozen log.",
    )
    parser.add_argument(
        "--prior-summary",
        type=Path,
        default=None,
        help="JSON file with the prior frozen log's totals (see module docstring).",
    )
    args = parser.parse_args()

    path = find_transcript(args.session_id)
    turns = load_turns(path)

    print_report(turns, path)

    if args.skip_duplicate is not None and args.prior_summary is not None:
        print_combined_summary(turns, args.skip_duplicate, args.prior_summary)
    elif args.skip_duplicate is not None or args.prior_summary is not None:
        raise SystemExit("--skip-duplicate and --prior-summary must be given together")


if __name__ == "__main__":
    main()
