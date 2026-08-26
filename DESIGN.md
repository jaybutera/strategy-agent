# strategy-agent (working name)

An agent harness for developing trading strategies on
[backtest-engine](https://github.com/jaybutera/backtest-engine). The agent
supplies creativity: reading sources, proposing mechanisms, writing strategy
code. The harness supplies epistemics: data splits, spend counters, and an
append-only record, enforced by workspace topology and small scripts rather
than by prompt instructions the agent can forget.

Status: design draft, living in ict-scanner's experiments/ tree until it
graduates to a sibling repo next to backtest-engine. Founding notes (Casper,
verbatim) are in `casper-design-thoughts.md`.

## Principles

1. **Attempts die, hypotheses don't.** A specific implementation can be
   falsified by its own eval. A hypothesis cannot be falsified by an agent's
   failure to find a working implementation; that is bad logic. The state
   machine has no "false" state on a hypothesis that the agent can reach.
2. **Rules the agent must not break are topology, not text.** Agents in long
   loops forget rules. Held-out data is absent from the workspace, not merely
   forbidden; ledger writes go through a validating script; eval definitions
   are read-only to the agent. Nothing depends on the agent remembering.
3. **Tight loop where it's safe, counted looks where it isn't.** Iteration on
   the train window is unlimited; that is the point of a local engine.
   Validation and holdout evaluations are scarce, logged, and counted.
4. **Minimal and agent-agnostic.** The product is a directory convention, git,
   and a handful of scripts. Any coding agent (Claude Code, or anything
   comparable) can operate a campaign, interactively or headless. Minimal
   means easy to understand and build on, not featureless.
5. **The lifecycle runs through deployment.** The harness ends at "validated
   candidate," but the ecosystem does not: a deployed strategy is monitored
   against its own backtest as a null model, and divergence feeds back into
   research. The deploy action itself is always human.
6. **Private integrations are adapters.** Idea sources and broker fills enter
   through file-format seams. The core repo names no community, no broker, no
   private infrastructure.

## Two frontends, one workspace

- **Interactive**: a normal agent session opened in the campaign directory.
  Discuss an idea, point it at a file, run a one-off eval, argue with a
  dossier. State changes go through the same gated scripts the loop uses.
- **Loop**: a runner that spawns fresh-context ticks against the same
  directory. Each tick reads `goal.md` and `INDEX.md`, probes the ledger and
  dossiers as needed, performs the next most useful task, writes results
  back, and commits. Ticks are deliberately small: one decision, one
  implementation, or one eval per tick.

A conversation that drifts into real research leaves artifacts in the
campaign format; the loop continues from them. Handoff in both directions is
free because there is nothing to hand off except files.

## Campaign workspace

A campaign is a git repository:

    campaign/
      goal.md            # human-written objective; steer by editing this
      campaign.toml      # frozen eval + split scheme + budgets (read-only to agent)
      INDEX.md           # compact current state; loaded into every tick
      ledger.jsonl       # append-only event log, written via script
      dossiers/          # one prose file per hypothesis
      attempts/<id>/     # strategy.rhai, preset.toml, eval/metrics.json, eval/report.md
      data/              # train-window candles only; nothing else exists here
      inbox/             # idea intake (adapter seam), JSONL records

Git conventions:

- **Attempt = commit.** The strategy file, preset, and eval artifact are
  committed together. A result that cannot be reproduced from its own commit
  does not exist. Eval artifacts record the engine commit hash and data
  checksums so any historical number is re-derivable and silent data changes
  are detectable.
- **Attempt family = branch.** A different mechanism is a branch, not an
  overwrite. Parallel ideas coexist; abandoned families keep their trail.
- **Trunk = considered state.** Merged winners, the ledger, the dossiers. The
  ledger indexes across branches by commit hash so "what have we tried"
  is answerable from one file.

The agent's mutable surface per attempt is the Rhai strategy file and its
preset TOML. The engine binary, `campaign.toml`, and past ledger entries are
not. Changing the eval definition is a human edit and invalidates
comparability, so it is logged as a campaign event.

## State machine

Hypothesis states: `active` -> `supported` (has a validated attempt) or
`shelved`. Shelving requires either human sign-off or a configured threshold
of distinct attempt families tried, and the dossier must record what evidence
would reopen it. There is no falsified state.

Attempt states: `draft` -> `evaluated` (train window) -> `failed` or
`promising` -> `validated` (survived a validation look) -> `candidate`
(survived holdout) -> `deployed` -> `monitored` -> `adjusted` or `retired`.
The transition into `deployed` is human-only. An adjustment to a live
strategy is a new attempt and walks the same ladder; there is no shortcut
where live tinkering skips validation.

## Eval

`campaign.toml` freezes the eval at campaign creation: dataset identity and
checksums, fill lenses, warmup policy, date windows per split, metric set,
and spend counters. The eval wrapper runs backtest-engine with those pins and
emits `metrics.json` plus a short human-readable report. Every attempt's
numbers are comparable across ticks and across weeks because nothing about
the eval moved.

Grading is multi-lens by default: the live-faithful lens is the headline, the
optimistic lens is diagnostic, and the pessimistic lens is the floor. A
candidate that only wins on the optimistic lens is labeled a fill-assumption
artifact by the wrapper itself.

## Split gate

Held-out data lives outside the workspace. A gate script owns the path, runs
the eval on request, appends the spend to the ledger, and refuses once the
counter is spent. The agent cannot fumble a rule about data it does not have.

The scheme is chosen per campaign in `campaign.toml`:

- **contiguous**: train | embargo | validation | embargo | holdout. The
  simplest scheme and the default.
- **n-chunk**: history cut into K time-contiguous blocks with embargo gaps;
  some blocks are train, the rest form the validation set. Guards against a
  single validation window happening to be one regime.
- **walk-forward**: rolling train windows each followed by an out-of-sample
  segment, advancing through history. One validation look = one full
  walk-forward pass over all segments.

Common to every scheme: blocks are time-contiguous with embargo gaps at the
seams (random row-level splits leak regime information across boundaries);
the holdout is a terminal contiguous tail, untouched by any scheme; a
validation look is a warmup-jitter ensemble over the window, not a single
run, so each spent look buys a distribution instead of a coin flip; and
validation looks are counted per campaign, with holdout counted tighter
still (one or two per campaign), holdout results flowing only into the final
report, never back into iteration.

## Ledger

`ledger.jsonl`, append-only, written through a validating script. Record
types: `hypothesis`, `attempt`, `eval`, `verdict`, `spend`, `note`,
`campaign-event`. Each record carries a timestamp, an id, a parent id where
applicable, and the git commit hash it describes. Verdicts are never edited,
only superseded. The script rejects writes that violate the state machine,
which is what makes "the agent can't declare a hypothesis false" structural
rather than aspirational.

## Live monitoring

A monitoring campaign watches deployed strategies. Its adapter seam is a
fills feed: a stream or file of realized fills tagged by strategy id, mapped
from whatever broker the operator uses. The backtest run that validated the
candidate becomes its standing expectation, and monitoring ticks grade live
fills against it: trade census (did the trades that should exist exist),
fill quality, R distribution, and divergence over time. Findings land as
evidence in the hypothesis dossier; proposed adjustments re-enter the
research loop as new attempts.

## Loop mechanics

- The runner spawns headless ticks (for Claude Code: a `-p` invocation in
  the campaign directory) with a standing prompt: goal, index, "probe memory,
  do the next most useful task, write back, commit."
- A scheduler multiplexes ticks across campaigns. Research campaigns run
  continuously under a budget; monitoring campaigns tick on a schedule.
  Campaigns are not "finished" by the agent; they decay in priority and
  humans retire goal files. A max-ticks knob exists for operators who want a
  hard stop.
- A digest tick closes each session: a morning report of what was tried,
  what moved, what is queued, written for a human who was asleep.

## Relation to karpathy/autoresearch

Borrowed: the human-edited program file as the steering surface, a
standardized cheap eval so iterations are comparable, a single mutable file
so diffs stay reviewable, and the overnight run-then-read-the-log workflow.

Rejected: the single-metric keep/discard hill-climb. Validation loss on
held-out text is a mostly honest objective; backtest return on the window
you are iterating against is the most gameable number in this domain. A
naive transplant of autoresearch onto a backtester is an overfitting machine
that produces beautiful equity curves by morning. Optimizing a trading model
and an ML model are structurally alike; the difference is sample size and
noise. An ML validation set is large enough that each evaluation leaks
little, while a trading validation window is a few hundred trades and each
look leaks fast. Hence counted looks where ML gets away with continuous
monitoring, and a hill-climb only inside the train window.

## The software inventory

The pieces that must be code, each small enough to read in one sitting:

1. campaign skeleton generator
2. eval wrapper (pins + artifact + lens grading)
3. split gate (out-of-workspace data, spend counting, scheme logic)
4. ledger append/validate script
5. loop runner + scheduler
6. digest generator

Everything else is markdown convention plus git.

## Open questions

- Name, and when to cut the sibling repo.
- Scheduler priority policy across concurrent campaigns.
- Attempt-family boundaries: agent-declared in the dossier, challenged by a
  skeptic pass at verdict time, rather than formalized. Revisit if gamed.
- Whether the founding-notes file travels to the public repo verbatim.
- Fills-feed adapter contract details (schema, delivery, id mapping).
