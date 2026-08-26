#!/usr/bin/env -S uv run --script
"""sa loop — run fresh-context research ticks against this campaign.

  sa loop -n 5              five ticks, sequential
  sa loop -n 5 --yolo       ticks run with --dangerously-skip-permissions
  sa loop -n 5 --model X    pass a model override to the agent CLI

Each tick is a headless `claude -p` invocation in the campaign directory,
prompted from .sa/tick.md: read goal + index, probe memory, do the next most
useful task, write back, commit. Transcripts land in .sa/ticks/. After each
tick anything left uncommitted is committed so no tick can strand work.

The agent CLI is configurable (SA_AGENT_CMD, default "claude"); any agent
that takes a -p prompt and works a directory can drive a tick.
"""
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import die, find_campaign_root, git, git_commit_all


def main():
    argv = sys.argv[1:]
    n = int(argv[argv.index("-n") + 1]) if "-n" in argv else 1
    model = argv[argv.index("--model") + 1] if "--model" in argv else None
    yolo = "--yolo" in argv
    root = find_campaign_root()
    prompt = (root / ".sa" / "tick.md").read_text()
    agent_cmd = os.environ.get("SA_AGENT_CMD", "claude")

    for i in range(1, n + 1):
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        log = root / ".sa" / "ticks" / f"{stamp}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        cmd = [agent_cmd, "-p", prompt]
        if model:
            cmd += ["--model", model]
        cmd += (["--dangerously-skip-permissions"] if yolo
                else ["--permission-mode", "acceptEdits"])
        print(f"tick {i}/{n} -> {log.name}")
        with open(log, "w") as f:
            r = subprocess.run(cmd, cwd=root, stdout=f, stderr=subprocess.STDOUT, text=True)
        tail = log.read_text().strip().splitlines()[-6:]
        for line in tail:
            print(f"  {line}")
        if r.returncode != 0:
            print(f"  tick exited {r.returncode}; see {log}")
        if git(root, "status", "--porcelain"):
            git_commit_all(root, f"tick {stamp}: uncommitted leftovers")
            print("  (leftover changes committed)")


if __name__ == "__main__":
    main()
