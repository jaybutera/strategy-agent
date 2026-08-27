#!/usr/bin/env -S uv run --script
"""sa loop — run fresh-context research ticks against this campaign.

  sa loop -n 5              five ticks, sequential
  sa loop -n 5 --yolo       ticks run with --dangerously-skip-permissions
  sa loop -n 5 --model X    pass a model override to the agent CLI
  sa loop --merge           one tick prompted from .sa/merge.md instead
  sa loop -n 5 --no-sync    do not fetch or push around ticks
  sa loop -n 5 --max-minutes 90
  sa loop --forever         run until Ctrl-C; a failed tick backs off and retries

Each tick is a headless `claude -p` invocation in the campaign directory,
prompted from .sa/tick.md: read goal + index, probe memory, do the next most
useful task, write back, commit. After each tick anything left uncommitted is
committed so no tick can strand work. Ctrl-C stops the loop the same way:
leftovers are committed, the clone returns to master, and everything is pushed.

`--forever` is the unattended mode: it ignores -n and --max-minutes, and a
tick that fails (agent error, rate limit, git trouble, a crash inside the
loop) is followed by a wait that doubles from one minute up to fifteen before
the next tick; a good tick resets the wait. Only Ctrl-C ends it.

When the campaign has an `origin` remote the loop fetches before each tick and
pushes after it. It never merges: merging derived files is distillation, which
is the agent's job (.sa/merge.md), not git's. A rejected push is reported and
left for the next tick, whose merge job brings the remote in.

Every tick gets a stamp (YYYYMMDD-HHMMSS) exported as SA_TICK and appended to
the prompt, so ledger records, NOTES headers and the raw transcript all name
the same tick. Under `claude` the tick runs as stream-json and the whole
transcript is kept at raw/<holder>/ticks/<stamp>.jsonl. Another agent command
is treated the same way when SA_AGENT_STREAM=1 says it also emits stream-json.

The agent CLI is configurable (SA_AGENT_CMD, default "claude"); any agent
that takes a -p prompt and works a directory can drive a tick.
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import die, find_campaign_root, git, git_commit_all, holder

LIMIT = 4096   # bytes of tool-result text kept in the raw transcript


def has_origin(root):
    return "origin" in git(root, "remote").split()


def elide_events(lines):
    """Turn a stream-json transcript into the committed raw record.

    Every event is kept. Tool results are what make a transcript enormous, so
    a Read result is replaced by the path it read (the file at that commit is
    the record) and any other oversized result keeps its first 4 KB plus a
    count of the bytes dropped."""
    reads = {}          # tool_use id -> file_path, from the assistant events
    out = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue                      # not our format; drop the line
        if not isinstance(ev, dict):
            continue
        msg = ev.get("message")
        msg = msg if isinstance(msg, dict) else {}
        content = msg.get("content")
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "Read":
                reads[block.get("id")] = (block.get("input") or {}).get("file_path")
        if isinstance(content, list):
            for i, block in enumerate(content):
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    content[i] = elide_result(block, reads)
        out.append(ev)
    return out


def elide_result(block, reads):
    tid = block.get("tool_use_id")
    if tid in reads:
        return {**block, "content": {"elided": "Read", "path": reads[tid]}}
    body = block.get("content")
    text = body if isinstance(body, str) else json.dumps(body, separators=(",", ":"))
    raw = text.encode("utf8", "replace")
    if len(raw) <= LIMIT:
        return block
    return {**block, "content": [{"type": "text", "text": raw[:LIMIT].decode("utf8", "ignore")},
                                 {"elided": len(raw) - LIMIT}]}


def result_text(events):
    """The final result event's text: what the loop tails and what .sa/ticks
    logs have always held."""
    for ev in reversed(events):
        if ev.get("type") == "result":
            r = ev.get("result")
            return r if isinstance(r, str) else json.dumps(r, indent=2)
    return ""


def main():
    argv = sys.argv[1:]
    n = int(argv[argv.index("-n") + 1]) if "-n" in argv else 1
    model = argv[argv.index("--model") + 1] if "--model" in argv else None
    max_minutes = (float(argv[argv.index("--max-minutes") + 1])
                   if "--max-minutes" in argv else None)
    yolo = "--yolo" in argv
    forever = "--forever" in argv
    merge_mode = "--merge" in argv
    sync = "--no-sync" not in argv
    started = time.monotonic()
    root = find_campaign_root()

    if merge_mode:
        n = 1
        prompt_file = root / ".sa" / "merge.md"
        if not prompt_file.exists():
            die("no .sa/merge.md in this campaign; run `sa upgrade` to install it")
    else:
        prompt_file = root / ".sa" / "tick.md"
    prompt = prompt_file.read_text()
    agent_cmd = os.environ.get("SA_AGENT_CMD", "claude")
    sync = sync and has_origin(root)
    tag = holder(root, required=False) or "_unknown"

    if agent_cmd == "claude" and not yolo:
        cfgp = Path.home() / ".claude.json"
        try:
            trusted = json.loads(cfgp.read_text()).get("projects", {}) \
                .get(str(root), {}).get("hasTrustDialogAccepted")
        except (OSError, json.JSONDecodeError):
            trusted = None
        if not trusted:
            print(f"warning: {root} is not a trusted Claude workspace, so the campaign's "
                  "Bash allowlist will be ignored and ticks cannot run ./sa or git.\n"
                  "Fix: open an interactive claude session here once and accept the trust "
                  f"dialog, or set projects[\"{root}\"].hasTrustDialogAccepted in ~/.claude.json.")

    def tick(i):
        """One tick. Returns "ok", "failed", or "stop"."""
        if max_minutes is not None and not forever:
            elapsed = (time.monotonic() - started) / 60
            if elapsed >= max_minutes:
                print(f"time budget reached ({elapsed:.0f} of {max_minutes:.0f} minutes) "
                      f"after {i - 1} ticks; stopping.")
                return "stop"
        if sync:
            r = subprocess.run(["git", "-C", str(root), "fetch", "origin"],
                               capture_output=True, text=True)
            if r.returncode != 0:
                print(f"  fetch failed: {r.stderr.strip().splitlines()[-1:] or ['?']}")
            else:
                behind = git(root, "rev-list", "--count", "master..origin/master", check=False)
                if behind.isdigit() and int(behind) > 0:
                    print(f"  origin/master is {behind} commits ahead; the tick merges it")

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        log = root / ".sa" / "ticks" / f"{stamp}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "SA_TICK": stamp}
        text = prompt + f"\n\nTick id: {stamp}"
        # `claude` emits stream-json; another agent command does not, unless it
        # says so (SA_AGENT_STREAM=1), which is how the smoke test drives this
        # path without spending credits.
        stream = agent_cmd == "claude" or os.environ.get("SA_AGENT_STREAM") == "1"

        cmd = [agent_cmd, "-p", text]
        if model:
            cmd += ["--model", model]
        cmd += (["--dangerously-skip-permissions"] if yolo
                else ["--permission-mode", "acceptEdits"])
        if agent_cmd == "claude":
            cmd += ["--output-format", "stream-json", "--verbose"]
        print(f"tick {i}/{'forever' if forever else n}{' (merge)' if merge_mode else ''} -> {stamp}")

        try:
            if stream:
                r = subprocess.run(cmd, cwd=root, capture_output=True, text=True, env=env)
                rawdir = root / "raw" / tag / "ticks"
                rawdir.mkdir(parents=True, exist_ok=True)
                rawfile = rawdir / f"{stamp}.jsonl"
                try:
                    events = elide_events(r.stdout.splitlines())
                    with open(rawfile, "w") as f:
                        for ev in events:
                            f.write(json.dumps(ev, separators=(",", ":")) + "\n")
                    log.write_text(result_text(events) or r.stderr)
                except Exception as e:                  # noqa: BLE001
                    # A transcript is never dropped: keep it verbatim if the
                    # elision failed, and say so in the tick log.
                    rawfile.write_text(r.stdout)
                    log.write_text(f"raw transcript kept unprocessed ({type(e).__name__}: {e})\n"
                                   + (r.stderr or ""))
            else:
                with open(log, "w") as f:
                    r = subprocess.run(cmd, cwd=root, stdout=f, stderr=subprocess.STDOUT,
                                       text=True, env=env)
        except KeyboardInterrupt:
            # Ctrl-C is how a person stops the loop for the night. The agent
            # process is already dead; keep whatever it left, return to trunk,
            # and push so the other holder sees the state.
            print(f"\ninterrupted during tick {stamp}; committing leftovers and stopping.")
            if git(root, "status", "--porcelain"):
                git_commit_all(root, f"tick {stamp}: interrupted, leftovers committed")
            git(root, "checkout", "-q", "master", check=False)
            if sync:
                subprocess.run(["git", "-C", str(root), "push", "origin", "--all"],
                               capture_output=True, text=True)
            sys.exit(130)

        for line in log.read_text().strip().splitlines()[-6:]:
            print(f"  {line}")
        ok = r.returncode == 0
        if not ok:
            print(f"  tick exited {r.returncode}; see {log}")
        if git(root, "status", "--porcelain"):
            git_commit_all(root, f"tick {stamp}: uncommitted leftovers")
            print("  (leftover changes committed)")

        if sync:
            p = subprocess.run(["git", "-C", str(root), "push", "origin", "master"],
                               capture_output=True, text=True)
            if p.returncode != 0:
                print("  push rejected; the next tick's merge job will bring origin in:")
                for line in p.stderr.strip().splitlines()[-3:]:
                    print(f"    {line}")
        return "ok" if ok else "failed"


    wait = 0
    i = 0
    while True:
        i += 1
        if not forever and i > n:
            break
        try:
            outcome = tick(i)
        except KeyboardInterrupt:
            raise
        except SystemExit as e:
            if not forever:
                raise
            outcome = "failed"
            print(f"  tick {i} aborted (exit {e.code}); the loop continues")
        except Exception as e:                      # noqa: BLE001
            if not forever:
                raise
            outcome = "failed"
            print(f"  tick {i} crashed: {type(e).__name__}: {e}; the loop continues")
        if outcome == "stop" and not forever:
            break
        if outcome == "ok":
            wait = 0
            continue
        if forever:
            wait = min(max(60, wait * 2), 900)
            print(f"  waiting {wait // 60} min before the next tick")
            try:
                time.sleep(wait)
            except KeyboardInterrupt:
                print("\ninterrupted while waiting; stopping.")
                sys.exit(130)


if __name__ == "__main__":
    main()
