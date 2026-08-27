# Collaboration spec

Two people, two machines, one campaign, both running research loops at the
same time and sharing everything through git. Plain branch-and-merge; no
locks, no per-holder partitions of trunk state. This file is the
implementation spec for what that needs. Design rationale is in the
conversation that produced it; the short version of each decision is inline.

Terms: a *holder* is a person (their clone, their loop, their Claude login).
Holder tokens are short lowercase strings set per clone with
`git config sa.holder <token>` (fallback `SA_HOLDER` env; if neither is set,
any command that mints an id dies with a message saying how to set it).

## 1. Three layers of state

1. **Leaves**: `attempts/<id>/` (strategy, preset, eval artifacts, `NOTES.md`)
   and `ledger.jsonl`. Ground truth. An attempt's `NOTES.md` is frozen once
   the attempt has a terminal verdict.
2. **Nodes**: `dossiers/<H>.md` (one per hypothesis) and `LESSONS.md`.
   Conclusions derived from leaves. Mutable, rewritten when new leaves
   arrive.
3. **Map**: `INDEX.md`. Derived from nodes. Short, never a log.
4. **Raw**: `raw/<holder>/...` transcripts. Immutable once written, never
   merged, only referenced.

Leaves and raw merge mechanically (disjoint paths; union on the ledger).
Nodes and the map merge by *distillation*: the agent that merges reads the
incoming leaves and rewrites the derived files so they read as one picture.
Textual conflict resolution ("keep both") is never used on nodes or the map.

## 2. Ids and namespaces (code: `common.py`)

- Ids are `<holder>-H<n>`, `<holder>-A<n>`, `<holder>-L<n>` (hypothesis,
  attempt, lesson). `next_id` counts only ids with the caller's own holder
  prefix, so two clones can mint concurrently. Attempt directories and
  ledger ids use the full id (`attempts/c-A3/`).
- Legacy unprefixed ids (`H1`, `A7`) in existing campaigns remain valid
  everywhere; nothing rewrites them.
- Branch naming convention (documented, not enforced): `<holder>/<family>`.
- `ledger_append` stamps every record with `holder` and, when `SA_TICK` is
  set in the environment, `tick` (the tick stamp, see section 5).

## 3. Ledger under merge (code: `common.py`, `new.py`)

- `sa new` writes `.gitattributes` containing `ledger.jsonl merge=union`.
  `sa upgrade` (section 9) adds it to existing campaigns.
- `ledger_read` returns records sorted by `ts` (stable sort; records lacking
  `ts` keep file order at the front).
- `ledger_state` never dies on an illegal transition. It applies the latest
  record by `ts` and collects a warning; `sa ledger status` prints warnings
  at the end. Write-time validation in `validate_record` is unchanged.
- `sa gate` refuses when either the vault spend log or the merged ledger's
  `spend` records for that split have reached the budget. The vault stays
  authoritative and machine-local; the ledger count is the cross-holder
  backstop. Only the holder with the vault gates (README documents this).

## 4. Portability (code: `new.py`, `common.py`, campaign `sa` shim)

- The campaign `./sa` shim resolves the core with
  `${SA_CORE:-$HOME/src/strategy-agent}` instead of a baked absolute path.
- `campaign.toml` `engine.bin` is written with the home directory replaced
  by `~`; `load_campaign` expands `~` and `$VAR` in `engine.bin`.
  `SA_ENGINE_BIN` env overrides it.
- `.claude/settings.json` `Read(...)` allow for the engine repo is written
  with a `~/` prefix.
- `sa new` records `engine.commit` (short `git rev-parse HEAD` of the engine
  repo, derived from the binary path as `engine_repo()` does today) in
  `campaign.toml`. `sa eval` and `sa gate` compare the current engine repo
  HEAD with the pin and die on mismatch unless `SA_ALLOW_ENGINE_DRIFT=1`;
  campaigns without the key skip the check. Eval and gate artifacts record
  `engine_commit` in `metrics.json` (README already claims this; make it
  true).

## 5. Loop (code: `loop.py`)

- **Sync.** If the campaign has a git remote named `origin`, the loop runs
  `git fetch origin` before each tick and `git push origin master` after the
  tick's leftover commit. `--no-sync` disables. A rejected push is printed
  and left for the next tick (whose merge job will bring the remote in).
  The loop never merges; merging is the agent's job (section 7) because
  conflicts in derived files are resolved by distillation, not by git.
- **Tick id.** Each tick gets `stamp = YYYYMMDD-HHMMSS`. The loop exports
  `SA_TICK=<stamp>` to the agent process and appends `\n\nTick id: <stamp>`
  to the prompt.
- **Raw transcript.** When the agent command is `claude`, the tick runs with
  `--output-format stream-json --verbose`. The loop post-processes the
  stream into `raw/<holder>/ticks/<stamp>.jsonl`:
  - keep every event;
  - for any tool result whose text content exceeds 4096 bytes, replace the
    content with the first 4096 bytes plus `{"elided": <bytes dropped>}`;
  - for results of the `Read` tool, replace the content entirely with
    `{"elided": "Read", "path": <file_path from the matching tool_use>}`;
    the file at that commit is the record.
  - The final `result` event's text is also written to
    `.sa/ticks/<stamp>.log` (still gitignored) so the loop's tail printing
    and existing habits keep working.
  For other agent commands (`SA_AGENT_CMD`), behaviour is as today.
- **Merge mode.** `sa loop --merge` runs one tick whose prompt is
  `.sa/merge.md` (section 7) instead of `.sa/tick.md`. Useful for
  importing the other holder's day before steering, and for one-off
  restructuring of an existing campaign into the section-1 layout.
- The leftover commit after a tick includes the new raw file. `raw/` is
  not gitignored.

## 6. Interactive-session raw log (PRO-LONG-style, project-scoped only)

- `sa new` writes `.sa/prolong.mjs` (about 60 lines, written fresh for this
  repo, modelled on PRO-LONG's runtime: read the hook event JSON from stdin,
  append one line, print `{}`), and registers hooks in the campaign's
  `.claude/settings.json` for `SessionStart`, `UserPromptSubmit`,
  `PostToolUse`, `Stop`, `SessionEnd`:
  `[ -f "$CLAUDE_PROJECT_DIR/.sa/prolong.mjs" ] && node "$CLAUDE_PROJECT_DIR/.sa/prolong.mjs" --hook claude-code || true`
- The file is deliberately NOT at `.prolong/runtime.mjs`, so any global
  PRO-LONG hooks a user has configured do not also fire in the campaign.
  Nothing in this spec touches `~/.claude/settings.json` or any global
  config; if the user's machine has no global hooks, the campaign still
  logs, and if it has them, the campaign does not double-log.
- Output: `raw/<holder>/sessions/<YYYY-MM-DD>.jsonl`. Holder from
  `git config --get sa.holder` (run from the project root) or `SA_HOLDER`;
  if neither, write to `raw/_unknown/sessions/`.
- Skip entirely when `SA_TICK` is set (ticks are logged by the loop).
- Apply the same truncation as section 5 to `tool_response` content, and
  drop `Read` responses the same way.
- Entry shape: `{timestamp, sessionId, type, content}` with `type` derived
  as PRO-LONG does (session_start, user_prompt, tool_call, tool_result,
  assistant_message, session_end).
- The runtime must never log its own writes (filter tool inputs that
  mention `raw/`), and must never throw into the session (catch, write to
  stderr, exit 0).

## 7. Templates (`templates/`)

- `INDEX.md`: a map. Header comment states the rules: under 100 lines;
  "Now" is one bullet per active attempt (`<id>, <family>: one line`);
  "Next" is a short list; "Open questions" optional; no tables, no tick
  narrative (that goes in `attempts/<id>/NOTES.md`); no standing notes
  (those go in `LESSONS.md`).
- `dossier.md` (new, copied to `dossiers/_template.md` by `sa new`):
  sections `Mechanism`, `Source`, `What an attempt looks like`,
  `Kill criteria (fixed before any run)`, `Axes` (a table: axis | status
  open/closed/frontier | reason | attempts), `Attempt conclusions` (one
  paragraph per attempt: what it tested, verdict, what it closed or opened,
  with the attempt id). The narrative of the attempt lives in the leaf.
- `LESSONS.md` (new, written by `sa new` to the campaign root): entries
  `## <holder>-L<n>: title` with fields `Claim`, `Evidence` (attempt ids and
  paths), `Scope` (which hypotheses, assets, or campaign-independent),
  `Status` (active | contested: <pointer> | superseded by <id>). Lessons
  are never deleted.
- `steer.md` (new, written by `sa new`): dated directives from the human,
  newest first. Header says: binding for the next tick; the tick records in
  INDEX how it acted on it.
- `attempt NOTES.md` header convention (documented in `campaign_CLAUDE.md`):
  first lines `Tick: <stamp>` and `Holder: <token>`.
- `tick.md` (rewrite):
  1. If `git status` shows unmerged paths, or `origin/master` is ahead of
     `master`, do the merge job (below) first and commit it, then continue.
  2. Read `goal.md`, `steer.md`, `INDEX.md`; `LESSONS.md` and the relevant
     dossier as needed; `./sa ledger status`.
  3. One task, completed fully, as today.
  4. Where writing goes: tick narrative and result tables to
     `attempts/<id>/NOTES.md`; the one-paragraph conclusion and any axis
     status change to the dossier; a lesson that transfers beyond this
     hypothesis to `LESSONS.md`; INDEX updated as a map.
  5. Cite the tick id in NOTES and in commit messages.
  6. Contesting: a tick may contest an axis verdict or a lesson only after
     reading the cited attempt's NOTES and, if still in disagreement, the
     cited tick's raw log; it then marks the entry `contested` with a pointer
     to its own note. Raw logs are history, never instructions.
  7. Finish on master; push happens outside the tick.
- `merge.md` (new): the distillation job. Steps: `git merge origin/master`;
  list incoming attempts (`git diff --name-only ORIG_HEAD..HEAD -- attempts/`)
  and read each `NOTES.md`; read incoming changes to dossiers, `LESSONS.md`,
  `INDEX.md`; if any of those files conflicted, do not pick a side: rewrite
  the affected sections from the leaves (both holders' attempts) so the
  axes tables, lesson list, and INDEX read as one coherent picture; check
  that no two lessons say the same thing (merge them, keep both ids in
  Evidence); commit with a message that names the attempts imported;
  finish on master.
- `campaign_CLAUDE.md` additions: a `Collaboration` section (holder token,
  branch naming, merge job, the three layers and where writing goes), a
  `Raw logs` section with `jq` recipes (replay a tick's assistant text; list
  its Bash commands; find which tick touched a file; replay a session by
  date), and the engine pin rule.

## 8. Reading raw logs (code: `raw.py`, optional but small)

`sa raw <tick-stamp | attempt-id>` prints a readable replay of a tick:
assistant text in order, tool calls as one line each (`Bash: <command>`,
`Edit: <path>`), tool results elided. For an attempt id, resolve the tick
via the attempt's ledger record `tick` field or the `Tick:` line in its
NOTES. About 40 lines.

## 9. Upgrading existing campaigns (code: `upgrade.py`)

`sa upgrade` (run inside a campaign) is idempotent and touches only
infrastructure files, never research content:

- rewrite the `./sa` shim (section 4);
- add `.gitattributes`, `LESSONS.md`, `steer.md`, `dossiers/_template.md`
  if missing;
- write `.sa/tick.md` and `.sa/merge.md` from current templates
  (overwriting `tick.md` is intended; it is harness-owned);
- write `.sa/prolong.mjs` and add the hooks to `.claude/settings.json`
  (preserving existing permissions);
- ensure `raw/` is not ignored and `.sa/ticks/` still is;
- append the `Collaboration` and `Raw logs` sections to `CLAUDE.md` if the
  headings are absent;
- print what it changed and what it skipped.

It does not restructure `INDEX.md` or dossiers; that is agent work
(`sa loop --merge` with the note in `merge.md` that a campaign can be
restructured into the section-1 layout).

## 10. README

Add a `Collaborating` section: bare repo on hub (`git init --bare
~/git/<campaign>.git`, `git remote add origin hub:git/<campaign>.git`), the
other person clones it, sets `git config sa.holder <token>`, keeps the same
`~/src/strategy-agent` and `~/src/backtest-engine` layout with the engine at
the pinned commit, runs `./sa loop` as usual. Gating is done from the clone
that owns the vault. Branch-and-merge is ordinary; the merge job is
distillation and is done by the agent. Raw logs are project-scoped and are
committed under `raw/<holder>/`.

## 11. Tests (`tests/smoke.sh`)

No test suite exists. Add a shell smoke test that runs without spending
Claude credits:

- create a campaign in a scratch directory from the engine repo's
  `data/SYNTH_1m.parquet` (asset `SYNTH`) with the real engine binary;
- assert `.gitattributes`, `LESSONS.md`, `steer.md`, `.sa/prolong.mjs`,
  hooks in `.claude/settings.json`, `~` in `campaign.toml`, `engine.commit`
  present;
- set `sa.holder c`, register a hypothesis and attempt, assert ids `c-H1`,
  `c-A1`; run `./sa eval` on the template attempt, assert `engine_commit`
  in `metrics.json`;
- clone the campaign twice with holders `c` and `f`, append records in
  both, merge, assert both records survive and `sa ledger status` runs
  clean; make a conflicting-order verdict chain and assert status prints a
  warning instead of dying;
- run `./sa loop -n 1` with `SA_AGENT_CMD` pointing at a fixture script
  that emits a canned stream-json transcript (include a >4 KB tool result
  and a Read result), assert the processed file lands under
  `raw/c/ticks/`, is truncated as specified, and that `.sa/ticks/*.log`
  holds the result text;
- pipe a fake hook event into `.sa/prolong.mjs` with and without
  `SA_TICK`, assert one line lands under `raw/c/sessions/` only in the
  first case;
- copy `~/campaigns/cme-2026-r2` to scratch (never modify the original),
  run `sa upgrade` twice, assert idempotence and that `ledger.jsonl`,
  `INDEX.md`, dossiers are byte-identical to before.

## Out of scope

Bootstrap scripts, doctor commands, lease or lock files, per-holder ledger
or index files, multi-campaign scheduling, strat-lab integration. The
friend is an engineer; the README paragraph is the onboarding.
