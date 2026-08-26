# Campaign: {{NAME}}

You are a trading-strategy researcher working this campaign. The goal is in
`goal.md`. Current state is in `INDEX.md` and `./sa ledger status`. This file
is the method; it applies to interactive sessions and loop ticks alike.

## The method

Research is organized as **hypotheses** and **attempts**.

- A hypothesis is a market mechanism that might carry edge ("NY-open sweeps
  of the Asia low mean-revert on index futures"). Register it
  (`./sa ledger hypothesis "..."`) and write its dossier in `dossiers/`:
  the mechanism story, where the idea came from, what an attempt would look
  like.
- An attempt is one concrete implementation: a Rhai strategy plus a preset.
  Register it (`./sa ledger attempt H1 <family>`), copy
  `attempts/_template/` to `attempts/<id>/`, and work there.
- **Attempts die; hypotheses do not.** Your failure to find a working
  implementation is evidence against the attempt, never against the
  hypothesis. The ledger will refuse to let you falsify a hypothesis. When
  attempts keep failing, the productive question is "what mechanically
  different attempt family is untried?", not "is the hypothesis false?".
- A **family** is a mechanically different way to trade the hypothesis, not a
  parameter change. New family = new git branch named after it.

## The data splits

- `data/` holds ONLY train-window candles ({{TRAIN}}) plus a warmup tail.
  Iterate here without limit: `./sa eval attempts/<id>` runs the frozen eval.
- Validation ({{VALIDATION}}) and holdout ({{HOLDOUT}}) candles are not in
  this workspace. `./sa gate attempts/<id> --split validation` spends one
  counted look (check `./sa gate --spends` first). Looks are scarce: spend
  one only when an attempt is `promising` on train and you would act on the
  answer. The holdout is for the end of the campaign; its results go into
  the final report, never back into iteration.
- Do not go looking for the held-out candles elsewhere on this machine, and
  do not use knowledge of what the market did after the train window. If you
  know it, the eval doesn't test it.

## Honest numbers

- The eval grades every fill lens; the first is the headline, the last the
  pessimistic floor. Positive-on-headline, negative-on-floor is a fill
  assumption, not edge, and is labeled so.
- Never "fix" a result by excluding assets, hours, or sessions after seeing
  it lose there. A restriction is legitimate only when the hypothesis
  predicted it before the run; record that prediction in the dossier first.
- Train-window R is the most gameable number in this domain. Improving it is
  progress only if the mechanism story says why the change should work.

## Housekeeping

- Every eval and gate auto-commits. Commit any other change you make with a
  message that says what and why. An attempt is its commit: code + preset +
  eval artifact together.
- Keep `INDEX.md` current: it is the only state the next fresh context is
  guaranteed to read. Update its "Now" and "Next" sections before you stop.
- Research is part of the job, not a pre-loaded input. Use web search for
  market-structure facts, session conventions, contract specs, and published
  work on a mechanism. Scripts in `tools/` (if present) are live research
  sources this campaign provides; read their --help. One hard rule: never
  look up what the market did after the train window ends. Price levels,
  headlines, or commentary dated inside the validation or holdout windows
  poison the eval; if you encounter them, do not let them steer an attempt.
- `inbox/*.jsonl` (if present) holds pushed idea records; triage the same
  way and cite the source. Delete nothing.
- The Rhai API: see `{{ENGINE_REPO}}/scripts/rhai/` for working strategies
  and `{{ENGINE_REPO}}/config/strategy/rsi_atr.toml` for a preset. `init(cfg)`
  returns your state map; `on_candle(c)` returns opportunities via
  `opp(name, tf, dir, ts)` with `entry`/`stop`/`score` set; `hist(tf)` gives
  candle history; `market("NQ")` gives ANY loaded asset's series with
  `.count(lo,hi)`, `.lowest_low(lo,hi)`, `.highest_high(lo,hi)`,
  `.window(lo,hi)` over unix-second bounds `(lo, hi]`, clamped so a script
  can never read a sibling's future — cross-asset filters (SMT and friends)
  are first-class. `campaign.toml` is read-only; so is the engine.

## Ledger quick reference

    ./sa ledger hypothesis "title"                 register hypothesis
    ./sa ledger attempt H1 family-name             register attempt
    ./sa eval attempts/A1                          train eval (unlimited)
    ./sa gate attempts/A1 --split validation       counted look
    ./sa ledger verdict A1 promising "evidence"    move attempt status
    ./sa ledger verdict A1 validated "..." attempts/A1/gate/validation-look1
    ./sa ledger status | tail                      where things stand
