# {{ID}}: <one-line hypothesis>

<!-- One dossier per hypothesis. This file holds conclusions, not narrative.
The story of what a tick did lives in attempts/<id>/NOTES.md; here you write
what the campaign now believes and why. Rewrite sections when new attempts
land; do not append a running log. -->

## Mechanism

Why this edge would exist: who is on the other side, what they are doing,
and why they keep doing it. A mechanism a trader would recognize, in prose.

## Source

Where the idea came from: a paper, a desk convention, an observation in the
data, a post. Link it and date it. An idea with no source is a guess, which
is fine, but say so.

## What an attempt looks like

The concrete shape of an implementation: entry trigger, stop placement,
target or exit rule, session and timeframe, which assets. Enough that two
people would build roughly the same thing.

## Kill criteria (fixed before any run)

What result would make this hypothesis not worth further attempts. Write
these before the first eval; a criterion invented after seeing a number is
not a criterion. Note that attempts die and hypotheses do not: these say when
to stop spending attempts here, not that the mechanism is false.

## Axes

An axis is one dimension an attempt can vary (session, timeframe, stop rule,
asset, filter). `open` means untried, `closed` means attempts settled it,
`frontier` means the next attempt should go here.

| axis | status | reason | attempts |
|---|---|---|---|
| (example) entry session | open | untried | |

## Attempt conclusions

One paragraph per attempt, newest last. Each names the attempt id, what it
tested, its verdict, and what it closed or opened on the axes table above.
