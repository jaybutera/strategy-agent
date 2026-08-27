You are the merge job on this campaign. Another holder has been working the
same research; your task is to fold their day into one coherent picture. This
is distillation, not conflict resolution. Do it fully, then stop.

1. `git fetch origin && git merge origin/master`. Note the merge base:
   `git rev-parse ORIG_HEAD`.
2. List the incoming leaves:
   `git diff --name-only ORIG_HEAD..HEAD -- attempts/ ledger.jsonl`.
   Read every incoming `attempts/<id>/NOTES.md` and its `eval/report.md`.
   Run `./sa ledger status` and read its warnings if it prints any.
3. Read the incoming changes to `dossiers/`, `LESSONS.md`, and `INDEX.md`:
   `git diff ORIG_HEAD..HEAD -- dossiers/ LESSONS.md INDEX.md`.
4. If any of those files conflicted, do not pick a side and do not keep both
   copies. Rewrite the affected sections from the leaves, using both holders'
   attempts as evidence, so that:
   - each dossier's Axes table has one row per axis with one status, and the
     `attempts` column names every attempt from both holders that bears on
     it. An axis one holder called closed and the other calls frontier is a
     real disagreement: mark it `contested` with a pointer to both attempts,
     never split it into two rows.
   - each dossier's Attempt conclusions section has one paragraph per
     attempt, from both holders, in chronological order.
   - `LESSONS.md` has no two entries making the same claim. Merge duplicates
     into one entry and keep both ids in its Evidence line. Lessons are never
     deleted; a lesson the incoming evidence contradicts is marked
     `contested: <pointer>` or `superseded by <id>`.
   - `INDEX.md` is one map of the whole campaign: Now lists the active
     attempts of both holders, Next is one list, and it is still short.
5. Leaves and the ledger merge mechanically. `ledger.jsonl` is union-merged,
   so both holders' records survive; never hand-edit it. An attempt directory
   from the other holder is theirs: read it, cite it, do not rewrite it.
6. Commit with a message naming the attempts you imported, for example
   `merge: import f-A3, f-A4 from f; distill H2 axes`.
7. Finish on master with a clean tree.

Restructuring: a campaign that predates this layout may have its conclusions
buried in INDEX.md or in attempt notes. When you see that, one merge job may
also lift them into place: dossiers get the axes tables and attempt
conclusions, LESSONS.md gets the standing notes, INDEX.md shrinks to a map.
Move text, do not invent it, and do not touch the ledger or existing eval
artifacts.
