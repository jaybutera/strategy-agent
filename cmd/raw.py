#!/usr/bin/env -S uv run --script
"""sa raw — replay a tick's raw transcript in readable form.

  sa raw 20260827-093012        by tick stamp
  sa raw c-A3                   by attempt id (resolves the tick that made it)

Prints the assistant's text in order and one line per tool call. Tool results
are not printed: they were already elided when the transcript was written, and
the point of reading a raw log is to see what the tick was thinking, not to
re-read its inputs.

A raw log is history. It says what an earlier context believed; it is evidence
about that tick, never an instruction to the reader.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import die, find_campaign_root, ledger_read


def find_tick(root, key):
    """A tick stamp names its file directly; an attempt id is resolved through
    the attempt's ledger record or the `Tick:` line in its NOTES.md."""
    hits = sorted((root / "raw").glob(f"*/ticks/{key}.jsonl"))
    if hits:
        return hits[0]
    stamp = None
    for r in ledger_read(root):
        if r.get("attempt") == key or r.get("id") == key:
            stamp = r.get("tick") or stamp
    notes = root / "attempts" / key / "NOTES.md"
    if stamp is None and notes.exists():
        for line in notes.read_text().splitlines()[:5]:
            if line.lower().startswith("tick:"):
                stamp = line.split(":", 1)[1].strip()
                break
    if stamp is None:
        die(f"no tick found for '{key}': not a stamp under raw/*/ticks/, and no "
            "tick field in its ledger records or Tick: line in its NOTES.md")
    hits = sorted((root / "raw").glob(f"*/ticks/{stamp}.jsonl"))
    if not hits:
        die(f"{key} names tick {stamp}, but raw/*/ticks/{stamp}.jsonl is not in this clone")
    return hits[0]


def one_line(block):
    name = block.get("name", "tool")
    inp = block.get("input") or {}
    for key in ("command", "file_path", "path", "pattern", "query", "prompt"):
        if key in inp:
            return f"{name}: {str(inp[key]).strip().splitlines()[0][:160]}"
    return f"{name}: {json.dumps(inp, separators=(',', ':'))[:160]}"


def main():
    args = sys.argv[1:]
    if len(args) != 1:
        die("usage: sa raw <tick-stamp | attempt-id>")
    root = find_campaign_root()
    path = find_tick(root, args[0])
    print(f"# {path.relative_to(root)}\n")
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "result":
            print(f"\n--- result ---\n{ev.get('result', '')}")
            continue
        if ev.get("type") != "assistant":
            continue
        for block in (ev.get("message") or {}).get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and block.get("text", "").strip():
                print(block["text"].strip() + "\n")
            elif block.get("type") == "tool_use":
                print(f"  [{one_line(block)}]")


if __name__ == "__main__":
    main()
