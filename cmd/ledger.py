#!/usr/bin/env -S uv run --script
"""sa ledger — append to and query the campaign ledger.

  sa ledger add '<json>'            append one record (validated)
  sa ledger hypothesis "title"      shorthand: register a hypothesis
  sa ledger attempt H1 family       shorthand: register an attempt
  sa ledger verdict A1 status "evidence"
  sa ledger status                  fold the ledger into current state
  sa ledger tail [N]                last N records, pretty-printed

The ledger is append-only. Verdicts are superseded, never edited. The state
machine lives in common.py; 'validated'/'candidate' come only from sa gate,
'deployed' only from a human (SA_HUMAN=1), and hypotheses cannot be falsified.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (die, find_campaign_root, ledger_append, ledger_read,
                    ledger_state)


def main():
    args = sys.argv[1:]
    if not args:
        die(__doc__.strip(), 2)
    root = find_campaign_root()
    cmd, rest = args[0], args[1:]

    if cmd == "add":
        if len(rest) != 1:
            die("usage: sa ledger add '<json>'")
        rec = ledger_append(root, json.loads(rest[0]))
        print(json.dumps(rec))

    elif cmd == "hypothesis":
        if not rest:
            die("usage: sa ledger hypothesis \"title\" [notes]")
        rec = ledger_append(root, {"type": "hypothesis", "title": rest[0],
                                   **({"notes": rest[1]} if len(rest) > 1 else {})})
        print(f"{rec['id']} registered: {rec['title']}")
        print(f"now write dossiers/{rec['id']}.md (mechanism story, source, what an attempt looks like)")

    elif cmd == "attempt":
        if len(rest) < 2:
            die("usage: sa ledger attempt <hypothesis-id> <family> [notes]")
        rec = ledger_append(root, {"type": "attempt", "hypothesis": rest[0], "family": rest[1],
                                   **({"notes": rest[2]} if len(rest) > 2 else {})})
        print(f"{rec['id']} registered under {rest[0]} (family {rest[1]})")
        print(f"work in attempts/{rec['id']}/ on branch {rest[1]}")

    elif cmd == "verdict":
        if len(rest) < 3:
            die("usage: sa ledger verdict <attempt-id> <status> \"evidence\" [gate_ref]")
        rec = {"type": "verdict", "attempt": rest[0], "status": rest[1], "evidence": rest[2]}
        if len(rest) > 3:
            rec["gate_ref"] = rest[3]
        print(json.dumps(ledger_append(root, rec)))

    elif cmd == "status":
        warnings = []
        hyps, atts, spends = ledger_state(ledger_read(root), warnings)
        print("hypotheses:")
        for hid, h in hyps.items():
            fams = ",".join(sorted(h["families"])) or "-"
            print(f"  {hid} [{h['status']}] {h['title']}  (families: {fams})")
        print("attempts:")
        for aid, a in atts.items():
            print(f"  {aid} [{a['status']}] hyp={a['hypothesis']} family={a['family']}")
        print(f"spends: validation={spends.get('validation', 0)} holdout={spends.get('holdout', 0)}")
        if warnings:
            print(f"\nwarnings ({len(warnings)}): the merged ledger is out of order somewhere.")
            print("the latest record by ts won. Reconcile in the attempt's NOTES.md:")
            for w in warnings:
                print(f"  {w}")

    elif cmd == "tail":
        n = int(rest[0]) if rest else 10
        for r in ledger_read(root)[-n:]:
            print(json.dumps(r))

    else:
        die(f"unknown ledger command '{cmd}'\n\n{__doc__.strip()}", 2)


if __name__ == "__main__":
    main()
