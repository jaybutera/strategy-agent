#!/usr/bin/env bash
# tests/smoke.sh — end-to-end check of the harness, without spending Claude
# credits. The loop is driven by tests/fixture-agent.sh, which emits a canned
# stream-json transcript.
#
#   tests/smoke.sh
#
# Needs the backtest engine built (SA_TEST_ENGINE, default
# ~/src/backtest-engine/target/release/backtest) and its data/SYNTH_1m.parquet.
# Everything is created under a scratch directory (SA_TEST_SCRATCH, default a
# mktemp dir) and removed at the end, along with the scratch campaign's
# registry entry and vault. The existing campaigns under ~/campaigns are copied,
# never touched.
set -uo pipefail

CORE="$(cd "$(dirname "$0")/.." && pwd)"
ENGINE="${SA_TEST_ENGINE:-$HOME/src/backtest-engine/target/release/backtest}"
ENGINE_REPO="$(cd "$(dirname "$ENGINE")/../.." && pwd)"
PARQUET="$ENGINE_REPO/data/SYNTH_1m.parquet"
UPGRADE_FROM="${SA_TEST_UPGRADE_FROM:-$HOME/campaigns/cme-2026-r2}"
SCRATCH="${SA_TEST_SCRATCH:-$(mktemp -d)}"
mkdir -p "$SCRATCH"
NAME="sa-smoke-$$"
VAULT="$HOME/.strategy-agent/vault/$NAME"
REGISTRY="$HOME/.strategy-agent/registry.json"

PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); printf '  ok    %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  FAIL  %s\n' "$1"; }
check(){ if [ "$1" = 0 ]; then ok "$2"; else bad "$2"; fi; }
have() { if [ -e "$1" ]; then ok "$2"; else bad "$2 (missing $1)"; fi; }
grep_ok(){ if grep -q "$1" "$2" 2>/dev/null; then ok "$3"; else bad "$3"; fi; }
eq()   { if [ "$1" = "$2" ]; then ok "$3"; else bad "$3 (got '$1', want '$2')"; fi; }
section(){ printf '\n%s\n' "$1"; }

cleanup() {
  # The scratch campaign is the only thing this test registers; take it back out.
  if [ -f "$REGISTRY" ]; then
    python3 - "$REGISTRY" "$NAME" <<'PY'
import json, sys
path, name = sys.argv[1], sys.argv[2]
reg = json.load(open(path))
if reg.pop(name, None) is not None:
    open(path, "w").write(json.dumps(reg, indent=2) + "\n")
PY
  fi
  rm -rf "$VAULT"
  [ -n "${SA_TEST_KEEP:-}" ] || rm -rf "$SCRATCH"
}
trap cleanup EXIT

[ -x "$ENGINE" ]  || { echo "no engine binary at $ENGINE"; exit 2; }
[ -f "$PARQUET" ] || { echo "no $PARQUET"; exit 2; }

CAMP="$SCRATCH/campaign"
SA="$CORE/bin/sa"
export SA_CORE="$CORE"

section "1. sa new (SYNTH, real engine)"
SA_HOLDER=c "$SA" new "$CAMP" --name "$NAME" --engine "$ENGINE" \
  --parquet "SYNTH=$PARQUET" \
  --train 2024-02-01:2024-04-30 \
  --validation 2024-05-06:2024-05-31 \
  --holdout 2024-06-03:2024-06-28 \
  --warmup-days 10 --jitter 0,2 --val-looks 2 --holdout-looks 1 \
  > "$SCRATCH/new.log" 2>&1
NEW_RC=$?
check $NEW_RC "sa new exited 0"
if [ $NEW_RC -ne 0 ]; then
  echo "sa new failed; nothing else can run:"; sed 's/^/    /' "$SCRATCH/new.log"
  echo; echo "smoke: $PASS passed, $FAIL failed"; exit 1
fi
have "$CAMP/.gitattributes" ".gitattributes written"
grep_ok "ledger.jsonl merge=union" "$CAMP/.gitattributes" "ledger is union-merged"
have "$CAMP/LESSONS.md" "LESSONS.md written"
have "$CAMP/steer.md" "steer.md written"
have "$CAMP/dossiers/_template.md" "dossiers/_template.md written"
have "$CAMP/.sa/merge.md" ".sa/merge.md written"
have "$CAMP/.sa/prolong.mjs" ".sa/prolong.mjs written"
node --check "$CAMP/.sa/prolong.mjs" 2>/dev/null
check $? "prolong.mjs parses as an ES module"
grep_ok 'bin = "~/' "$CAMP/campaign.toml" "engine.bin written with ~"
grep_ok '^commit = ' "$CAMP/campaign.toml" "engine.commit pinned"
grep_ok 'Read(~/' "$CAMP/.claude/settings.json" "engine Read allow written with ~"
grep_ok 'SA_CORE' "$CAMP/sa" "campaign shim resolves the core through SA_CORE"
# The runtime must not write to or be invoked from .prolong/: a global PRO-LONG
# install would otherwise double-log this campaign. (Its header comment says why
# it lives at .sa/, so only quoted paths and the hook command are checked.)
if grep -qE '"[^"]*\.prolong|\.prolong/(runtime|log)' \
     "$CAMP/.sa/prolong.mjs" "$CAMP/.claude/settings.json"; then
  bad "no .prolong/ path in the runtime or the hooks"
else
  ok "no .prolong/ path in the runtime or the hooks"
fi
grep_ok '\.sa/prolong\.mjs' "$CAMP/.claude/settings.json" "hooks invoke .sa/prolong.mjs"
HOOKS=$(python3 -c "
import json; d=json.load(open('$CAMP/.claude/settings.json'))
print(','.join(sorted(d.get('hooks', {}))))")
eq "$HOOKS" "PostToolUse,SessionEnd,SessionStart,Stop,UserPromptSubmit" "all five hooks registered"

section "2. holder-namespaced ids and a real eval"
cd "$CAMP" || exit 2
git config sa.holder c
./sa ledger hypothesis "SYNTH reverts after an outsized 5m bar" > "$SCRATCH/hyp.log" 2>&1
check $? "sa ledger hypothesis exited 0"
HID=$(python3 -c "
import json
print([json.loads(l)['id'] for l in open('ledger.jsonl') if json.loads(l)['type']=='hypothesis'][-1])")
eq "$HID" "c-H1" "hypothesis id is c-H1"
./sa ledger attempt c-H1 baseline > "$SCRATCH/att.log" 2>&1
check $? "sa ledger attempt exited 0"
AID=$(python3 -c "
import json
print([json.loads(l)['id'] for l in open('ledger.jsonl') if json.loads(l)['type']=='attempt'][-1])")
eq "$AID" "c-A1" "attempt id is c-A1"
HOLDER_STAMPED=$(python3 -c "
import json
print(all(json.loads(l).get('holder')=='c' for l in open('ledger.jsonl')))")
eq "$HOLDER_STAMPED" "True" "every ledger record carries its holder"

# The template attempt runs as-is: sa new wrote its asset list from --parquet,
# so a SYNTH-only campaign gets a SYNTH-only preset.
cp -r attempts/_template attempts/c-A1
./sa eval attempts/c-A1 > "$SCRATCH/eval.log" 2>&1
check $? "sa eval ran the engine on SYNTH"
have "attempts/c-A1/eval/metrics.json" "eval wrote metrics.json"
EC=$(python3 -c "
import json; print(json.load(open('attempts/c-A1/eval/metrics.json')).get('engine_commit'))")
if [ -n "$EC" ] && [ "$EC" != None ]; then ok "metrics.json records engine_commit ($EC)"
else bad "metrics.json records engine_commit"; fi
PIN=$(sed -n 's/^commit = "\([^"]*\)".*/\1/p' campaign.toml)
eq "$EC" "$PIN" "engine_commit matches the campaign pin"

section "3. engine pin refuses a different build"
sed -i 's/^commit = ".*"/commit = "deadbee"/' campaign.toml
./sa eval attempts/c-A1 > "$SCRATCH/drift.log" 2>&1
if [ $? -ne 0 ] && grep -q "engine drift" "$SCRATCH/drift.log"; then
  ok "eval dies on engine drift"
else bad "eval dies on engine drift"; fi
SA_ALLOW_ENGINE_DRIFT=1 ./sa eval attempts/c-A1 > "$SCRATCH/drift2.log" 2>&1
check $? "SA_ALLOW_ENGINE_DRIFT=1 overrides the pin"
sed -i "s/^commit = \".*\"/commit = \"$PIN\"/" campaign.toml
git commit -qam "restore engine pin"

section "4. two clones, union merge, out-of-order verdicts"
git checkout -q -b master 2>/dev/null || git branch -M master
CC="$SCRATCH/clone-c"; CF="$SCRATCH/clone-f"
git clone -q "$CAMP" "$CC" && git clone -q "$CAMP" "$CF"
check $? "campaign clones twice"
(cd "$CC" && git config sa.holder c)
(cd "$CF" && git config sa.holder f)
(cd "$CC" && ./sa ledger hypothesis "c-side idea" >/dev/null 2>&1 && git commit -qam "c: hypothesis")
check $? "clone c appends a record"
(cd "$CF" && ./sa ledger hypothesis "f-side idea" >/dev/null 2>&1 && git commit -qam "f: hypothesis")
check $? "clone f appends a record"
FID=$(cd "$CF" && python3 -c "
import json
print([json.loads(l)['id'] for l in open('ledger.jsonl') if json.loads(l)['type']=='hypothesis'][-1])")
eq "$FID" "f-H1" "clone f mints f-H1 while c holds c-H1 and c-H2"
cd "$CC" || exit 2
git remote add other "$CF" && git fetch -q other && git merge -q other/master -m "merge f" 2>/dev/null
check $? "the two ledgers merge without conflict"
BOTH=$(python3 -c "
import json
ids={json.loads(l).get('id') for l in open('ledger.jsonl')}
print('c-H2' in ids and 'f-H1' in ids)")
eq "$BOTH" "True" "both holders' records survive the merge"
./sa ledger status > "$SCRATCH/status-clean.log" 2>&1
check $? "sa ledger status runs on the merged ledger"
if grep -q "^warnings" "$SCRATCH/status-clean.log"; then
  bad "a clean merged ledger prints no warnings"
else ok "a clean merged ledger prints no warnings"; fi

# Two legal verdicts whose merged order is illegal: status must warn, not die.
python3 - <<'PY'
import json
for rec in [{"type": "verdict", "attempt": "c-A1", "status": "failed",
             "evidence": "floor lens negative", "ts": "2099-02-01T00:00:00Z", "holder": "c"},
            {"type": "verdict", "attempt": "c-A1", "status": "candidate",
             "evidence": "holdout look", "ts": "2099-03-01T00:00:00Z", "holder": "f"}]:
    open("ledger.jsonl", "a").write(json.dumps(rec) + "\n")
PY
./sa ledger status > "$SCRATCH/status-warn.log" 2>&1
check $? "sa ledger status survives an illegal merged transition"
grep_ok "not a legal transition" "$SCRATCH/status-warn.log" "status warns about it"
grep_ok "c-A1 \[candidate\]" "$SCRATCH/status-warn.log" "the latest record by ts is applied"

section "5. loop tick against the fixture agent"
cd "$CAMP" || exit 2
SA_AGENT_CMD="$CORE/tests/fixture-agent.sh" SA_AGENT_STREAM=1 \
  ./sa loop -n 1 --no-sync > "$SCRATCH/loop.log" 2>&1
check $? "sa loop -n 1 exited 0"
STAMP=$(ls raw/c/ticks 2>/dev/null | head -1 | sed 's/\.jsonl$//')
if [ -n "$STAMP" ]; then ok "transcript landed at raw/c/ticks/$STAMP.jsonl"
else bad "transcript landed under raw/c/ticks/"; fi
have ".sa/ticks/$STAMP.log" ".sa/ticks/$STAMP.log written"
grep_ok "DID read the index" ".sa/ticks/$STAMP.log" "the log holds the result event's text"
python3 - "raw/c/ticks/$STAMP.jsonl" <<'PY' > "$SCRATCH/raw-check.txt"
import json, sys
events = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
types = [e.get("type") for e in events]
read_result = big_result = None
for e in events:
    for b in (e.get("message") or {}).get("content") or []:
        if isinstance(b, dict) and b.get("type") == "tool_result":
            if b.get("tool_use_id") == "tu_read":
                read_result = b["content"]
            if b.get("tool_use_id") == "tu_bash":
                big_result = b["content"]
print("events", len(events))
print("kept_unknown", "an_event_type_from_a_future_cli" in types)
print("has_result", "result" in types)
print("read_elided", read_result == {"elided": "Read", "path": "INDEX.md"})
kept = big_result[0]["text"] if isinstance(big_result, list) else ""
print("big_head_bytes", len(kept.encode()))
print("big_elided", big_result[1].get("elided") if isinstance(big_result, list) else None)
PY
grep_ok "kept_unknown True" "$SCRATCH/raw-check.txt" "an unknown event type is kept"
grep_ok "has_result True" "$SCRATCH/raw-check.txt" "the result event is kept"
grep_ok "read_elided True" "$SCRATCH/raw-check.txt" "the Read result is replaced by its path"
grep_ok "big_head_bytes 4096" "$SCRATCH/raw-check.txt" "an oversized result keeps 4096 bytes"
grep_ok "big_elided 4904" "$SCRATCH/raw-check.txt" "and records the 4904 bytes dropped"
git log --oneline -1 --name-only | grep -q "raw/c/ticks/$STAMP.jsonl"
check $? "the leftover commit includes the raw transcript"
./sa raw "$STAMP" > "$SCRATCH/raw-replay.txt" 2>&1
check $? "sa raw replays the tick"
grep_ok "Bash: ./sa ledger status" "$SCRATCH/raw-replay.txt" "the replay lists tool calls one per line"

section "6. prolong hook on interactive sessions"
EVENT='{"hook_event_name":"UserPromptSubmit","session_id":"sess1","prompt":"what next"}'
echo "$EVENT" | SA_TICK=20240101-000000 node .sa/prolong.mjs --hook claude-code > /dev/null
if [ -d raw/c/sessions ]; then bad "SA_TICK set: the hook writes nothing"
else ok "SA_TICK set: the hook writes nothing"; fi
echo "$EVENT" | node .sa/prolong.mjs --hook claude-code > "$SCRATCH/hook.out"
eq "$(cat "$SCRATCH/hook.out")" "{}" "the hook prints {} to Claude"
LINES=$(cat raw/c/sessions/*.jsonl 2>/dev/null | wc -l)
eq "$LINES" "1" "SA_TICK unset: exactly one line lands under raw/c/sessions/"
grep_ok '"type":"user_prompt"' raw/c/sessions/*.jsonl "the entry's type is derived"
python3 -c "
import json
d = json.dumps({'hook_event_name':'PostToolUse','session_id':'sess1','tool_name':'Read',
                'tool_input':{'file_path':'INDEX.md'},'tool_response':'the whole file'})
print(d)" | node .sa/prolong.mjs --hook claude-code > /dev/null
python3 -c "
import json
d = json.dumps({'hook_event_name':'PostToolUse','session_id':'sess1','tool_name':'Bash',
                'tool_input':{'command':'yes'},'tool_response':'B'*9000})
print(d)" | node .sa/prolong.mjs --hook claude-code > /dev/null
python3 - raw/c/sessions <<'PY' > "$SCRATCH/session-check.txt"
import glob, json, sys
rows = [json.loads(l) for f in glob.glob(sys.argv[1] + "/*.jsonl") for l in open(f)]
resp = [r["content"].get("tool_response") for r in rows if r["type"] == "tool_result"]
print("read_dropped", {"elided": "Read", "path": "INDEX.md"} in resp)
big = [r for r in resp if isinstance(r, dict) and "head" in r]
print("big_head_bytes", len(big[0]["head"].encode()) if big else 0)
print("big_elided", big[0]["elided"] if big else None)
PY
grep_ok "read_dropped True" "$SCRATCH/session-check.txt" "a Read response is dropped for its path"
grep_ok "big_head_bytes 4096" "$SCRATCH/session-check.txt" "an oversized response keeps 4096 bytes"
grep_ok "big_elided 4904" "$SCRATCH/session-check.txt" "and records the 4904 bytes dropped"

section "7. sa upgrade on an existing campaign"
if [ ! -d "$UPGRADE_FROM" ]; then
  echo "  skip  no campaign at $UPGRADE_FROM to upgrade"
else
  OLD="$SCRATCH/upgrade-me"
  cp -r "$UPGRADE_FROM" "$OLD"
  check $? "copied $UPGRADE_FROM to scratch (the original is never touched)"
  cd "$OLD" || exit 2
  find ledger.jsonl INDEX.md dossiers attempts -type f | sort \
    | xargs md5sum > "$SCRATCH/content-before.md5"
  ./sa upgrade > "$SCRATCH/upgrade1.log" 2>&1
  check $? "first sa upgrade exited 0"
  grep_ok "SA_CORE" sa "the shim was rewritten"
  have ".gitattributes" ".gitattributes added"
  have "LESSONS.md" "LESSONS.md added"
  have "steer.md" "steer.md added"
  have "dossiers/_template.md" "dossiers/_template.md added"
  have ".sa/merge.md" ".sa/merge.md added"
  have ".sa/prolong.mjs" ".sa/prolong.mjs added"
  grep_ok "## Collaboration" CLAUDE.md "CLAUDE.md gained a Collaboration section"
  grep_ok "## Raw logs" CLAUDE.md "CLAUDE.md gained a Raw logs section"
  grep_ok "\.sa/ticks/" .gitignore ".sa/ticks/ still ignored"
  if grep -qE '^/?raw/?$' .gitignore; then bad "raw/ is not ignored"
  else ok "raw/ is not ignored"; fi
  md5sum -c "$SCRATCH/content-before.md5" > /dev/null 2>&1
  check $? "ledger, INDEX and dossiers are byte-identical after the upgrade"
  find . -path ./.git -prune -o -type f -print | sort | xargs md5sum > "$SCRATCH/all-after1.md5"
  ./sa upgrade > "$SCRATCH/upgrade2.log" 2>&1
  check $? "second sa upgrade exited 0"
  grep_ok "^changed (0):" "$SCRATCH/upgrade2.log" "the second upgrade changes nothing"
  md5sum -c "$SCRATCH/all-after1.md5" > /dev/null 2>&1
  check $? "every file is byte-identical after the second upgrade"
  ./sa ledger status > "$SCRATCH/legacy-status.log" 2>&1
  check $? "sa ledger status still works on legacy unprefixed ids"
  grep_ok "^  H1 " "$SCRATCH/legacy-status.log" "legacy id H1 is unchanged"
fi

printf '\n%s\n' "-----"
printf '%s\n' "smoke: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
