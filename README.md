# strategy-agent

An agent harness for developing trading strategies on
[backtest-engine](https://github.com/jaybutera/backtest-engine). The agent
supplies creativity: triaging ideas, proposing mechanisms, writing Rhai
strategies. The harness supplies epistemics: data splits the agent cannot
reach around, counted looks at held-out data, and an append-only ledger with
a state machine that refuses bad logic (an agent's failure to implement a
hypothesis is not evidence the hypothesis is false).

Read `DESIGN.md` for the full design. If you arrived from
karpathy/autoresearch: the ergonomics are borrowed (a goal file, a cheap
frozen eval, one mutable file per attempt, run-overnight-read-the-log), the
hill-climb is not. Validation loss on held-out text is a mostly honest
objective; backtest return on the window you iterate against is the most
gameable number in this domain. A naive autoresearch-on-a-backtester is an
overfitting machine. Here the hill-climb is confined to the train window and
everything else is a counted look.

## Quick start

Build the engine, fetch some 1m candles (the engine repo has a Databento
fetcher), then:

    ./bin/sa new ~/campaigns/my-campaign --name my-campaign \
        --engine ~/src/backtest-engine/target/release/backtest \
        --parquet ES=/path/ES_1m.parquet --parquet NQ=/path/NQ_1m.parquet \
        --train 2026-01-01:2026-04-30 \
        --validation 2026-05-04:2026-06-30 \
        --holdout 2026-07-06:2026-08-13 \
        --contracts my-contract-specs.toml

    cd ~/campaigns/my-campaign
    $EDITOR goal.md          # say what you are hunting
    ./sa loop -n 5           # or open an interactive agent session here
    ./sa digest              # the morning report

The campaign directory is a git repository and the whole contract: a
conversation and a headless loop tick read and write the same files, so you
can switch between driving it interactively and letting it run.

## What the pieces are

    cmd/new.py      campaign skeleton: slices train candles into the
                    workspace, puts the full series in a vault outside it
    cmd/eval.py     frozen train-window eval, multi-lens, auto-committed
    cmd/gate.py     the only path to validation/holdout candles; counts looks
    cmd/ledger.py   append-only ledger with the state machine
    cmd/loop.py     fresh-context ticks (headless claude -p, agent-configurable)
    cmd/digest.py   morning report from ledger + git log

Everything else is markdown convention plus git. Attempts are commits,
attempt families are branches, `INDEX.md` is what a fresh context reads
first, and `CLAUDE.md` in the campaign carries the method.

## Split schemes

`--train`/`--validation` are repeatable; every scheme compiles to window
lists. Contiguous (default): train | validation | holdout with embargo gaps
you choose in the dates. N-chunk: several train and validation blocks.
Walk-forward: alternating train/validation segments; one counted look runs
every validation segment. The holdout is always a terminal tail. A
validation look runs as a warmup-jitter ensemble, so it buys a distribution,
not a coin flip.

## Honesty about enforcement

The hard guarantee is topological: validation and holdout candles are not in
the workspace, so no amount of forgotten rules leaks them into iteration.
The ledger state machine and spend counters are guardrails an adversarial
agent could route around with enough filesystem access; if you need that
boundary hard too, run ticks in a container that mounts only the campaign
directory. The vault lives at `~/.strategy-agent/vault/<name>` and no
campaign file records that path.

## Scope

The lifecycle runs hypothesis -> attempts -> validated -> candidate ->
deployed -> monitored, but the deploy transition requires a human
(`SA_HUMAN=1`) and this repo ships no execution adapter. Live monitoring
compares realized fills (adapter-supplied, broker-agnostic) against the
validating backtest as a null model; adjustment proposals re-enter research
as new attempts. Idea intake is a directory of JSONL records (`inbox/`);
point anything you like at it.
