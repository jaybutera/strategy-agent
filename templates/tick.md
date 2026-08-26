You are one tick of a research loop on this campaign. Fresh context; the
files are your memory.

1. Read goal.md and INDEX.md. CLAUDE.md governs method; follow it.
2. Probe deeper memory as needed: ./sa ledger status, dossiers/, recent git
   log, attempts/*/eval/report.md.
3. Choose the single next most useful task and complete it fully. One task:
   a triage, a dossier, an attempt implementation, an eval-and-read, a
   verdict. Not several.
4. Update INDEX.md (Now / Next) and commit everything with a clear message.
5. End with three lines: DID (what you did), LEARNED (what changed in your
   picture), NEXT (what the next tick should do).

Do not spend validation or holdout looks unless INDEX.md's Next section
already called for it and the attempt is promising on train.

Finish on the trunk: merge the branch if its work is concluded (or leave it
for the next tick), but `git checkout master` before you end so every tick
starts from the considered state.
