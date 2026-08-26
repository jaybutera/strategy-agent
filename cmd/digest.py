#!/usr/bin/env -S uv run --script
"""sa digest — the morning report: what happened since the last digest.

  sa digest

Assembled from the ledger and git log, deterministic, written to
digests/<date>.md for a human who was asleep while the loop ran.
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import find_campaign_root, git, ledger_read, ledger_state


def main():
    root = find_campaign_root()
    marker = root / ".sa" / "last-digest"
    since = marker.read_text().strip() if marker.exists() else ""
    records = ledger_read(root)
    fresh = [r for r in records if r.get("ts", "") > since]
    hyps, atts, spends = ledger_state(records)

    lines = [f"# Digest {datetime.now().strftime('%Y-%m-%d %H:%M')}", ""]
    if since:
        lines.append(f"Since {since}: {len(fresh)} ledger records.")
    news = {"hypothesis": [], "attempt": [], "eval": [], "verdict": [], "spend": [], "note": []}
    for r in fresh:
        news.setdefault(r["type"], []).append(r)
    if news["hypothesis"]:
        lines += ["", "## New hypotheses"]
        lines += [f"- {r['id']}: {r['title']}" for r in news["hypothesis"]]
    if news["attempt"]:
        lines += ["", "## New attempts"]
        lines += [f"- {r['id']} ({r['hypothesis']}, family {r['family']})" for r in news["attempt"]]
    if news["eval"]:
        lines += ["", "## Evals"]
        for r in news["eval"]:
            m = ", ".join(f"{k} R={v.get('r', v.get('mean_r'))}" for k, v in r.get("metrics", {}).items())
            lines.append(f"- {r['attempt']} [{r.get('split', 'train')}] {m}")
    if news["verdict"]:
        lines += ["", "## Verdicts"]
        lines += [f"- {r['attempt']} -> {r['status']}: {r['evidence']}" for r in news["verdict"]]
    lines += ["", "## Standing state",
              f"- hypotheses: " + (", ".join(f"{h_id}[{h['status']}]" for h_id, h in hyps.items()) or "none"),
              f"- attempts: " + (", ".join(f"{a_id}[{a['status']}]" for a_id, a in atts.items()) or "none"),
              f"- looks spent: validation {spends.get('validation', 0)}, holdout {spends.get('holdout', 0)}"]
    log = git(root, "log", "--oneline", "-15")
    lines += ["", "## Recent commits", "```", log, "```", ""]
    idx = (root / "INDEX.md").read_text()
    lines += ["## INDEX.md as the loop left it", "", idx]

    out = root / "digests" / f"{datetime.now().strftime('%Y-%m-%d-%H%M')}.md"
    out.write_text("\n".join(lines))
    marker.parent.mkdir(exist_ok=True)
    marker.write_text(records[-1]["ts"] if records else "")
    print("\n".join(lines))
    print(f"\n(written to {out.relative_to(root)})")


if __name__ == "__main__":
    main()
