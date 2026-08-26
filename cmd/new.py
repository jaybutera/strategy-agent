#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyarrow"]
# ///
"""sa new — create a campaign workspace and its vault.

  sa new <dir> --name cme-2026 \
      --parquet ES=/path/ES_1m.parquet --parquet NQ=... \
      --train 2026-01-01:2026-04-30 \
      --validation 2026-05-04:2026-06-30 \
      --holdout 2026-07-06:2026-08-13 \
      --engine /path/backtest-engine/target/release/backtest \
      [--contracts specs.toml] [--warmup-days 30] [--jitter 0,2,5]
      [--val-looks 8] [--holdout-looks 2] [--timeframes 5m,15m,1h,4h]
      [--fills market_hybrid,limit_only,worst_case_bound] [--scheme contiguous]

Repeat --train / --validation for n-chunk or walk-forward schemes; every
scheme compiles to lists of windows, and the gate just iterates them.

The workspace data/ gets ONLY the train windows (plus a warmup tail before
each). The full series goes to the vault outside the workspace, which is the
only place validation and holdout candles exist.
"""
import json
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pyarrow.compute as pc
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).parent))
from common import REGISTRY, die, now_iso, registry, registry_save, sha256

CORE = Path(__file__).resolve().parents[1]


def parse_args(argv):
    opts = {"parquet": {}, "train": [], "validation": [], "holdout": [],
            "warmup-days": "30", "jitter": "0,2,5", "val-looks": "8",
            "holdout-looks": "2", "timeframes": "5m,15m,1h,4h",
            "fills": "market_hybrid,limit_only,worst_case_bound",
            "scheme": "contiguous", "shelve-families": "3", "contracts": None,
            "name": None, "engine": None}
    pos = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--"):
            key, val = a[2:], argv[i + 1]
            i += 2
            if key == "parquet":
                asset, path = val.split("=", 1)
                opts["parquet"][asset] = Path(path).resolve()
            elif key in ("train", "validation", "holdout"):
                frm, to = val.split(":")
                opts[key].append([frm, to])
            elif key in opts:
                opts[key] = val
            else:
                die(f"unknown option --{key}")
        else:
            pos.append(a)
            i += 1
    if len(pos) != 1 or not opts["name"] or not opts["engine"] or not opts["parquet"]:
        die("usage: sa new <dir> --name X --engine <bin> --parquet A=path ... "
            "--train a:b --validation a:b --holdout a:b   (sa new --help for the rest)")
    if not (opts["train"] and opts["validation"] and opts["holdout"]):
        die("need at least one --train, one --validation and one --holdout window")
    return Path(pos[0]).resolve(), opts


def slice_train(src, dst, train_windows, head_days):
    """Write only rows inside a train window (or its warmup tail) to dst."""
    t = pq.read_table(src)
    tcol = "timestamp" if "timestamp" in t.column_names else "ts"
    mask = None
    for frm, to in train_windows:
        lo = date.fromisoformat(frm) - timedelta(days=head_days)
        hi = date.fromisoformat(to) + timedelta(days=1)
        m = pc.and_(pc.greater_equal(t.column(tcol), lo),
                    pc.less(t.column(tcol), hi))
        mask = m if mask is None else pc.or_(mask, m)
    out = t.filter(mask)
    pq.write_table(out, dst)
    return out.num_rows


def render(template, subs):
    text = (CORE / "templates" / template).read_text()
    for k, v in subs.items():
        text = text.replace("{{" + k + "}}", v)
    return text


def main():
    root, o = parse_args(sys.argv[1:])
    name = o["name"]
    if root.exists() and any(root.iterdir()):
        die(f"{root} exists and is not empty")
    if name in registry():
        die(f"campaign '{name}' already registered in {REGISTRY}")
    engine = Path(o["engine"]).resolve()
    if not engine.is_file():
        die(f"engine binary not found: {engine}")

    jitter = [int(x) for x in o["jitter"].split(",")]
    warmup = int(o["warmup-days"])
    head_days = warmup + max(jitter) + 7   # warmup tail + jitter headroom + weekend slack

    vault = Path.home() / ".strategy-agent" / "vault" / name
    (vault / "data").mkdir(parents=True)
    (root / "data").mkdir(parents=True)
    for d in ("attempts", "dossiers", "inbox", "digests", ".sa/ticks", ".claude"):
        (root / d).mkdir(parents=True, exist_ok=True)

    checksums = {}
    for asset, src in o["parquet"].items():
        if not src.is_file():
            die(f"parquet for {asset} not found: {src}")
        shutil.copy2(src, vault / "data" / f"{asset}_1m.parquet")
        n = slice_train(src, root / "data" / f"{asset}_1m.parquet", o["train"], head_days)
        checksums[asset] = sha256(root / "data" / f"{asset}_1m.parquet")
        print(f"  {asset}: {n} train-window rows -> data/, full series -> vault")

    assets = sorted(o["parquet"])
    contracts = ""
    if o["contracts"]:
        contracts = Path(o["contracts"]).read_text()

    fmt_windows = lambda ws: "[" + ", ".join(f'["{a}", "{b}"]' for a, b in ws) + "]"
    (root / "campaign.toml").write_text(f"""\
# Frozen at campaign creation ({now_iso()}). READ-ONLY for the agent: editing
# this file is a campaign event that invalidates every comparison in the
# ledger, and only a human does it (then records it: sa ledger add
# '{{"type":"campaign-event", ...}}').
[campaign]
name = "{name}"
created = "{now_iso()}"
scheme = "{o['scheme']}"

[engine]
bin = "{engine}"
warmup_days = {warmup}
timeframes = [{", ".join(f'"{t}"' for t in o['timeframes'].split(","))}]
# First lens is the headline, last is the pessimistic floor.
fills = [{", ".join(f'"{f}"' for f in o['fills'].split(","))}]

[data]
assets = [{", ".join(f'"{a}"' for a in assets)}]
base_interval = "1m"
# sha256/16 of the workspace train slices; a mismatch means the data moved.
checksums = {{ {", ".join(f'{a} = "{c}"' for a, c in checksums.items())} }}

[splits]
# Dates are visible; the candles for validation/holdout are not in this
# workspace. `sa gate` runs them from the vault and counts the look.
train = {fmt_windows(o['train'])}
validation = {fmt_windows(o['validation'])}
holdout = {fmt_windows(o['holdout'])}

[budget]
validation_looks = {int(o['val-looks'])}
holdout_looks = {int(o['holdout-looks'])}
jitter = [{", ".join(str(j) for j in jitter)}]
shelve_families = {int(o['shelve-families'])}
""")

    subs = {"NAME": name, "ASSETS": ", ".join(assets),
            "ENGINE_REPO": str(engine.parents[2]),
            "TRAIN": ", ".join(f"{a}..{b}" for a, b in o["train"]),
            "VALIDATION": ", ".join(f"{a}..{b}" for a, b in o["validation"]),
            "HOLDOUT": ", ".join(f"{a}..{b}" for a, b in o["holdout"]),
            "CONTRACTS": contracts,
            "ASSETS_TOML": ", ".join(f'"{a}"' for a in assets)}
    (root / "CLAUDE.md").write_text(render("campaign_CLAUDE.md", subs))
    (root / "goal.md").write_text(render("goal.md", subs))
    (root / "INDEX.md").write_text(render("INDEX.md", subs))
    (root / ".sa" / "tick.md").write_text(render("tick.md", subs))
    tpl = root / "attempts" / "_template"
    tpl.mkdir()
    (tpl / "preset.toml").write_text(render("preset.toml", subs))
    (tpl / "strategy.rhai").write_text(render("strategy.rhai", subs))
    (root / ".claude" / "settings.json").write_text(json.dumps({
        "permissions": {"allow": [
            "Bash(./sa:*)", "Bash(git:*)", "Bash(rg:*)", "Bash(grep:*)",
            "Bash(ls:*)", "Bash(cat:*)", "Bash(head:*)", "Bash(tail:*)",
            "Bash(jq:*)", "Bash(cp:*)", "Bash(mkdir:*)", "Bash(mv:*)", "Bash(wc:*)", "Bash(sed -n:*)",
        ]}}, indent=2) + "\n")
    sa = root / "sa"
    sa.write_text(f"""#!/usr/bin/env bash
# Campaign dispatcher: ./sa <new|eval|gate|ledger|loop|digest> ...
set -euo pipefail
cmd="$1"; shift
exec uv run --script "{CORE}/cmd/$cmd.py" "$@"
""")
    sa.chmod(0o755)
    (root / ".gitignore").write_text(".sa/ticks/\n")

    (vault / "budget.json").write_text(json.dumps(
        {"validation_looks": int(o["val-looks"]), "holdout_looks": int(o["holdout-looks"])}) + "\n")
    (vault / "spends.jsonl").touch()
    reg = registry()
    reg[name] = {"path": str(root), "vault": str(vault), "created": now_iso()}
    registry_save(reg)

    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m",
                    f"campaign {name}: workspace created"], check=True)
    print(f"\ncampaign '{name}' at {root}")
    print(f"vault (held-out data + spend log): {vault}")
    print("next: edit goal.md, then ./sa loop -n 1 or work interactively")


if __name__ == "__main__":
    main()
