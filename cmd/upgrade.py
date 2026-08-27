#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyarrow"]
# ///
"""sa upgrade — bring an existing campaign's infrastructure up to date.

  sa upgrade [--dry-run]

Run inside a campaign. Idempotent, and it touches only harness-owned files:
the ./sa shim, .gitattributes, .gitignore, .sa/tick.md, .sa/merge.md,
.sa/prolong.mjs, .claude/settings.json, and the templates for LESSONS.md,
steer.md and dossiers/_template.md when those are missing.

It never touches research content. INDEX.md, existing dossiers, attempts and
ledger.jsonl come out byte-identical. Restructuring a campaign into the
leaves/nodes/map layout is agent work: `sa loop --merge` reads .sa/merge.md,
which says how.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import find_campaign_root, load_campaign
from new import HOOK_CMD, HOOK_EVENTS, SHIM

CORE = Path(__file__).resolve().parents[1]
TPL = CORE / "templates"


def render(name, subs):
    text = (TPL / name).read_text()
    for k, v in subs.items():
        text = text.replace("{{" + k + "}}", v)
    return text


def write_if(path, text, changed, skipped, label, force=False):
    """Write `text` when the file is missing, or when it is harness-owned and
    its content moved on."""
    if path.exists() and not force:
        skipped.append(f"{label} already present")
        return
    if path.exists() and path.read_text() == text:
        skipped.append(f"{label} already current")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    changed.append(f"{'rewrote' if force else 'added'} {label}")


def upgrade_settings(root, changed, skipped):
    """Add the prolong hooks without disturbing the permissions already set."""
    path = root / ".claude" / "settings.json"
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            skipped.append(".claude/settings.json is not valid JSON; left alone")
            return
    hooks = data.setdefault("hooks", {})
    added = []
    for ev in HOOK_EVENTS:
        entries = hooks.setdefault(ev, [])
        # Compare the command values themselves; json.dumps escapes the quotes
        # inside HOOK_CMD, so a substring test against dumped text never matches
        # and every run would append another copy.
        present = any(h.get("command") == HOOK_CMD
                      for e in entries if isinstance(e, dict)
                      for h in (e.get("hooks") or []) if isinstance(h, dict))
        if not present:
            entries.append({"hooks": [{"type": "command", "command": HOOK_CMD}]})
            added.append(ev)
    text = json.dumps(data, indent=2) + "\n"
    if added:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        changed.append(f"registered prolong hooks in .claude/settings.json ({', '.join(added)})")
    elif path.exists() and path.read_text() != text:
        path.write_text(text)
        changed.append("normalized .claude/settings.json")
    else:
        skipped.append("prolong hooks already registered")


def upgrade_gitignore(root, changed, skipped):
    """raw/ is committed; .sa/ticks/ stays local."""
    path = root / ".gitignore"
    lines = path.read_text().splitlines() if path.exists() else []
    before = list(lines)
    lines = [ln for ln in lines if ln.strip().rstrip("/") not in ("raw", "/raw")]
    if not any(ln.strip().rstrip("/") == ".sa/ticks" for ln in lines):
        lines.append(".sa/ticks/")
    if lines != before:
        path.write_text("\n".join(lines) + "\n")
        changed.append(".gitignore: raw/ tracked, .sa/ticks/ ignored")
    else:
        skipped.append(".gitignore already correct")


def upgrade_claude_md(root, changed, skipped):
    """Append the collaboration sections, taking them from the current
    template so the two files do not drift apart."""
    path = root / "CLAUDE.md"
    if not path.exists():
        skipped.append("no CLAUDE.md in this campaign")
        return
    text = path.read_text()
    template = (TPL / "campaign_CLAUDE.md").read_text()
    added = []
    for heading in ("## Collaboration", "## Raw logs"):
        if heading in text:
            continue
        start = template.index(heading)
        rest = template[start + len(heading):]
        nxt = rest.find("\n## ")
        section = (heading + rest[:nxt]) if nxt >= 0 else (heading + rest)
        section = section.replace("{{NAME}}", load_campaign(root)["campaign"]["name"])
        text = text.rstrip("\n") + "\n\n" + section.strip() + "\n"
        added.append(heading)
    if added:
        path.write_text(text)
        changed.append(f"appended to CLAUDE.md: {', '.join(added)}")
    else:
        skipped.append("CLAUDE.md already has Collaboration and Raw logs")


def main():
    dry = "--dry-run" in sys.argv
    root = find_campaign_root()
    cfg = load_campaign(root)
    subs = {"NAME": cfg["campaign"]["name"], "ID": "H1"}
    changed, skipped = [], []

    if dry:
        print(f"dry run in {root}; nothing is written")

    def w(path, text, label, force=False):
        if dry:
            cur = path.read_text() if path.exists() else None
            if cur is None:
                changed.append(f"would add {label}")
            elif force and cur != text:
                changed.append(f"would rewrite {label}")
            else:
                skipped.append(f"{label} unchanged")
            return
        write_if(path, text, changed, skipped, label, force)

    w(root / "sa", SHIM, "./sa shim (SA_CORE-resolved)", force=True)
    if not dry:
        (root / "sa").chmod(0o755)
    w(root / ".gitattributes", "ledger.jsonl merge=union\n", ".gitattributes (ledger merge=union)")
    w(root / "LESSONS.md", render("LESSONS.md", subs), "LESSONS.md")
    w(root / "steer.md", render("steer.md", subs), "steer.md")
    w(root / "dossiers" / "_template.md", render("dossier.md", subs), "dossiers/_template.md")
    w(root / ".sa" / "tick.md", render("tick.md", subs), ".sa/tick.md", force=True)
    w(root / ".sa" / "merge.md", render("merge.md", subs), ".sa/merge.md", force=True)
    w(root / ".sa" / "prolong.mjs", (TPL / "prolong.mjs").read_text(), ".sa/prolong.mjs", force=True)

    if not dry:
        (root / ".sa" / "prolong.mjs").chmod(0o755)
        (root / "raw").mkdir(exist_ok=True)
        keep = root / "raw" / ".gitkeep"
        if not any(p for p in (root / "raw").iterdir() if p.name != ".gitkeep"):
            keep.touch()
        upgrade_settings(root, changed, skipped)
        upgrade_gitignore(root, changed, skipped)
        upgrade_claude_md(root, changed, skipped)

    print(f"\nchanged ({len(changed)}):")
    for c in changed:
        print(f"  {c}")
    print(f"skipped ({len(skipped)}):")
    for s in skipped:
        print(f"  {s}")
    if not dry:
        print("\nResearch content untouched: INDEX.md, dossiers/, attempts/ and "
              "ledger.jsonl are as they were.")
        if "commit" not in cfg.get("engine", {}):
            print("Note: campaign.toml has no engine.commit, so eval and gate skip the "
                  "engine pin check. Add one by hand if you want it enforced.")


if __name__ == "__main__":
    main()
