#!/usr/bin/env python3
"""Generate a turn-by-turn timing report from a Claude Code session JSONL.

Reads the session transcript the harness keeps under
~/.claude/projects/<project-slug>/<session-id>.jsonl and prints a markdown
table of each human turn: when it started, when the assistant's response to
it finished (last event before the next human turn), and the elapsed time.

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
    return f"{minutes:.0f}m {secs:.0f}s"


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

    turns = []
    current = None
    for entry in timestamped:
        if is_human_turn(entry):
            if current is not None:
                turns.append(current)
            current = {
                "prompt": first_text(entry).strip().replace("\n", " "),
                "start": entry["timestamp"],
                "end": entry["timestamp"],
            }
        elif current is not None:
            current["end"] = entry["timestamp"]
    if current is not None:
        turns.append(current)

    print(f"# Session Timing Report\n\nSource: `{path}`\n")
    print("| # | Prompt (truncated) | Started (UTC) | Last activity (UTC) | Duration |")
    print("|---|---|---|---|---|")

    total_seconds = 0.0
    for i, t in enumerate(turns, 1):
        start = parse_ts(t["start"])
        end = parse_ts(t["end"])
        dur = (end - start).total_seconds()
        total_seconds += dur
        prompt = t["prompt"][:70] + ("…" if len(t["prompt"]) > 70 else "")
        prompt = prompt.replace("|", "\\|")
        print(
            f"| {i} | {prompt} | {start.strftime('%H:%M:%S')} "
            f"| {end.strftime('%H:%M:%S')} | {fmt_duration(dur)} |"
        )

    print(f"\n**Total turns:** {len(turns)}  \n**Total active time:** {fmt_duration(total_seconds)}")


if __name__ == "__main__":
    main()
