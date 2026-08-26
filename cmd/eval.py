#!/usr/bin/env -S uv run --script
"""sa eval — run the frozen train-window eval on an attempt.

  sa eval attempts/A1 [--no-commit]

Runs the engine over every train window, once per fill lens, using only the
workspace data/ directory (which holds train candles and warmup tail; nothing
else exists there). Writes attempts/<id>/eval/metrics.json and report.md,
commits the attempt + artifact, and appends an eval record to the ledger.

Unlimited use: iterating here is the point. Validation and holdout runs go
through `sa gate` and are counted.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (die, find_campaign_root, git_commit_all, ledger_append,
                    load_campaign, run_engine, summarize_report)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    no_commit = "--no-commit" in sys.argv
    if len(args) != 1:
        die("usage: sa eval attempts/<id> [--no-commit]")
    root = find_campaign_root()
    cfg = load_campaign(root)
    attempt_dir = (root / args[0]).resolve()
    preset = attempt_dir / "preset.toml"
    if not preset.exists():
        die(f"{preset} not found (an attempt is a directory with preset.toml + strategy.rhai)")
    attempt_id = attempt_dir.name

    fills = cfg["engine"]["fills"]
    warmup = cfg["engine"]["warmup_days"]
    windows = cfg["splits"]["train"]
    data_dirs = [root / "data"]

    per_lens = {}
    for fill in fills:
        agg = None
        for frm, to in windows:
            rep = summarize_report(run_engine(cfg, data_dirs, preset, fill, frm, to, warmup))
            if agg is None:
                agg = rep
            else:
                for k in ("trades", "wins", "losses"):
                    agg[k] += rep[k]
                agg["r"] = round(agg["r"] + rep["r"], 3)
                agg["fees_r"] = round(agg["fees_r"] + rep["fees_r"], 3)
                for a, v in rep["by_asset"].items():
                    cur = agg["by_asset"].setdefault(a, {"win": 0, "loss": 0})
                    cur["win"] += v["win"]
                    cur["loss"] += v["loss"]
        per_lens[fill] = agg

    headline, floor = fills[0], fills[-1]
    fill_sensitive = per_lens[headline]["r"] > 0 > per_lens[floor]["r"]

    evdir = attempt_dir / "eval"
    evdir.mkdir(exist_ok=True)
    metrics = {"split": "train", "windows": windows, "warmup_days": warmup,
               "lenses": per_lens, "headline": headline, "floor": floor,
               "fill_sensitive": fill_sensitive}
    (evdir / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")

    lines = [f"# {attempt_id} train eval", "",
             f"windows: {', '.join(f'{a}..{b}' for a, b in windows)}  warmup {warmup}d", "",
             "| lens | trades | W-L | R | fees(R) |", "|---|---|---|---|---|"]
    for fill, m in per_lens.items():
        tag = " (headline)" if fill == headline else (" (floor)" if fill == floor else "")
        lines.append(f"| {fill}{tag} | {m['trades']} | {m['wins']}-{m['losses']} | {m['r']} | {m['fees_r']} |")
    if fill_sensitive:
        lines += ["", "**fill-sensitive**: positive on the headline lens, negative on the floor. "
                      "Treat the edge as a fill assumption until shown otherwise."]
    (evdir / "report.md").write_text("\n".join(lines) + "\n")

    commit = None
    if not no_commit:
        commit = git_commit_all(root, f"eval {attempt_id}: {headline} R={per_lens[headline]['r']} "
                                      f"({per_lens[headline]['trades']} trades)")
    ledger_append(root, {"type": "eval", "attempt": attempt_id, "split": "train",
                         "commit": commit, "metrics": {f: {"r": m["r"], "trades": m["trades"]}
                                                       for f, m in per_lens.items()},
                         "fill_sensitive": fill_sensitive})
    print((evdir / "report.md").read_text())


if __name__ == "__main__":
    main()
