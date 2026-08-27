#!/usr/bin/env bash
# Fixture agent for tests/smoke.sh: emits a canned `claude -p --output-format
# stream-json --verbose` transcript on stdout and exits. It spends no Claude
# credits, so the loop's transcript handling can be tested for real.
#
# The transcript deliberately contains a Read result (which the loop replaces
# with the path it read), a tool result over 4 KB (truncated, with the dropped
# byte count recorded), an event type the loop has never seen (kept as-is), and
# a final result event (whose text becomes .sa/ticks/<stamp>.log).
python3 - <<'PY'
import json

BIG = "B" * 9000

events = [
    {"type": "system", "subtype": "init", "session_id": "fixture",
     "tools": ["Bash", "Read", "Edit"], "model": "fixture"},
    {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "text", "text": "Reading INDEX.md to see where the campaign stands."},
        {"type": "tool_use", "id": "tu_read", "name": "Read",
         "input": {"file_path": "INDEX.md"}}]}},
    {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "tu_read",
         "content": "# INDEX\n\n## Now\n\nthe entire file, which the loop should not keep"}]}},
    {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": "tu_bash", "name": "Bash",
         "input": {"command": "./sa ledger status"}}]}},
    {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "tu_bash", "content": BIG}]}},
    {"type": "an_event_type_from_a_future_cli", "payload": {"n": 1}},
    {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "text", "text": "Nothing to change this tick."}]}},
    {"type": "result", "subtype": "success", "num_turns": 3,
     "result": "DID read the index\nLEARNED nothing new\nNEXT design an attempt"},
]
for e in events:
    print(json.dumps(e))
PY
