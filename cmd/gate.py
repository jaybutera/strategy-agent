#!/usr/bin/env -S uv run --script
"""sa gate — spend one counted look at held-out data.

  sa gate attempts/A1 --split validation
  sa gate attempts/A1 --split holdout
  sa gate --spends            show looks spent / remaining

The held-out candles live in the vault, outside the workspace; this command
is the only path to them. One look = the full window set for that split, run
as a warmup-jitter ensemble on the headline and floor lenses, so a spent look
buys a distribution, not a coin flip. The spend log in the vault is
authoritative; once the budget is gone the gate refuses.

Holdout results are for the final report. Feeding them back into iteration
defeats the split; the counter is small so the temptation is bounded.
"""
import json
import os
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (die, find_campaign_root, git_commit_all, ledger_append,
                    load_campaign, now_iso, run_engine, summarize_report,
                    vault_for)


def spends_of(vault, split):
    log = vault / "spends.jsonl"
    if not log.exists():
        return 0
    return sum(1 for ln in log.read_text().splitlines()
               if ln.strip() and json.loads(ln)["split"] == split)


def main():
    root = find_campaign_root()
    cfg = load_campaign(root)
    vault = vault_for(cfg["campaign"]["name"])
    budget = json.loads((vault / "budget.json").read_text())

    if "--spends" in sys.argv:
        for split in ("validation", "holdout"):
            print(f"{split}: {spends_of(vault, split)}/{budget[split + '_looks']} looks spent")
        return

    argv = sys.argv[1:]
    split = None
    if "--split" in argv:
        i = argv.index("--split")
        split = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 1 or split not in ("validation", "holdout"):
        die("usage: sa gate attempts/<id> --split validation|holdout   (or sa gate --spends)")
    attempt_dir = (root / args[0]).resolve()
    preset = attempt_dir / "preset.toml"
    if not preset.exists():
        die(f"{preset} not found")
    attempt_id = attempt_dir.name

    spent, total = spends_of(vault, split), budget[split + "_looks"]
    if spent >= total:
        die(f"{split} budget exhausted ({spent}/{total} looks). The counter does not reset; "
            "a new campaign is a human decision.")

    fills = cfg["engine"]["fills"]
    lenses = [fills[0]] + ([fills[-1]] if len(fills) > 1 else [])
    warmup = cfg["engine"]["warmup_days"]
    jitters = cfg["budget"].get("jitter", [0])
    windows = cfg["splits"][split]
    data_dirs = [vault / "data"]

    results = {f: [] for f in lenses}          # per lens: one summed-R entry per jitter
    detail = []
    for j in jitters:
        for fill in lenses:
            total_r, trades = 0.0, 0
            for frm, to in windows:
                rep = summarize_report(run_engine(cfg, data_dirs, preset, fill, frm, to, warmup + j))
                total_r += rep["r"]
                trades += rep["trades"]
                detail.append({"lens": fill, "jitter": j, "window": [frm, to],
                               "r": rep["r"], "trades": rep["trades"]})
            results[fill].append(round(total_r, 3))

    look_n = spent + 1
    summary = {}
    for fill, rs in results.items():
        summary[fill] = {"runs": rs, "mean_r": round(statistics.mean(rs), 3),
                         "min_r": min(rs), "max_r": max(rs)}

    outdir = attempt_dir / "gate" / f"{split}-look{look_n}"
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "results.json").write_text(json.dumps(
        {"split": split, "look": look_n, "windows": windows, "jitters": jitters,
         "summary": summary, "detail": detail}, indent=2) + "\n")
    lines = [f"# {attempt_id} {split} look {look_n}/{total}", "",
             f"windows: {', '.join(f'{a}..{b}' for a, b in windows)}  "
             f"jitter ensemble: warmup {warmup}d + {jitters}", "",
             "| lens | R per jitter | mean | min | max |", "|---|---|---|---|---|"]
    for fill, s in summary.items():
        lines.append(f"| {fill} | {s['runs']} | {s['mean_r']} | {s['min_r']} | {s['max_r']} |")
    (outdir / "report.md").write_text("\n".join(lines) + "\n")

    with open(vault / "spends.jsonl", "a") as f:
        f.write(json.dumps({"ts": now_iso(), "split": split, "attempt": attempt_id,
                            "look": look_n}) + "\n")

    os.environ["SA_FROM_GATE"] = "1"
    ledger_append(root, {"type": "spend", "split": split, "attempt": attempt_id,
                         "look": look_n, "of": total})
    commit = git_commit_all(root, f"gate {attempt_id}: {split} look {look_n}/{total}")
    ledger_append(root, {"type": "eval", "attempt": attempt_id, "split": split,
                         "commit": commit,
                         "metrics": {f: {"mean_r": s["mean_r"], "min_r": s["min_r"]}
                                     for f, s in summary.items()}})
    git_commit_all(root, f"gate {attempt_id}: ledger records for {split} look {look_n}")
    print((outdir / "report.md").read_text())
    print(f"\n{split} looks: {look_n}/{total} spent.")
    status = "validated" if split == "validation" else "candidate"
    print(f"If the numbers support it: sa ledger verdict {attempt_id} {status} "
          f"\"<one sentence of evidence>\" {outdir.relative_to(root)}")


if __name__ == "__main__":
    main()
