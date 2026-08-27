"""Shared pieces for the sa-* commands.

Everything here is deliberately small: campaign loading, ledger append with
state-machine validation, and running the backtest engine. The ledger schema
and the transition tables ARE the product; read DESIGN.md before changing them.
"""

import hashlib
import json
import os
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

REGISTRY = Path.home() / ".strategy-agent" / "registry.json"

# ---------------------------------------------------------------- state machine

ATTEMPT_TRANSITIONS = {
    None: {"draft"},
    "draft": {"evaluated", "failed"},
    "evaluated": {"evaluated", "failed", "promising"},
    "promising": {"evaluated", "failed", "validated"},
    "validated": {"failed", "candidate"},
    "candidate": {"deployed", "retired"},
    "deployed": {"monitored", "retired"},
    "monitored": {"adjusted", "retired"},
    "adjusted": {"retired"},
}

HYPOTHESIS_TRANSITIONS = {
    None: {"active"},
    "active": {"supported", "shelved"},
    "supported": {"active", "shelved"},
    "shelved": {"active"},
}

# Statuses only the split gate may confer: they mean "survived a counted look".
GATE_ONLY = {"validated", "candidate"}
# The deploy transition is human-only by design.
HUMAN_ONLY = {"deployed"}

RECORD_TYPES = {
    "hypothesis", "hypothesis-status", "attempt", "verdict",
    "eval", "spend", "note", "campaign-event", "inbox",
}


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def die(msg, code=1):
    print(f"sa: {msg}", file=sys.stderr)
    sys.exit(code)


# ---------------------------------------------------------------- holder

def holder(root=None, required=True):
    """The holder token for this clone: `git config sa.holder`, else $SA_HOLDER.

    Two people sharing a campaign each set their own token; ids are namespaced
    with it so both can mint concurrently without collisions."""
    if root is not None:
        r = subprocess.run(["git", "-C", str(root), "config", "--get", "sa.holder"],
                           capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    env = os.environ.get("SA_HOLDER", "").strip()
    if env:
        return env
    if required:
        die("no holder token: run `git config sa.holder <token>` in this clone "
            "(a short lowercase string, one per person) or set SA_HOLDER")
    return None


# ---------------------------------------------------------------- campaign

def find_campaign_root(start=None):
    p = Path(start or Path.cwd()).resolve()
    for d in [p, *p.parents]:
        if (d / "campaign.toml").exists():
            return d
    die("not inside a campaign (no campaign.toml found upward)")


def load_campaign(root):
    with open(root / "campaign.toml", "rb") as f:
        return tomllib.load(f)


def registry():
    if REGISTRY.exists():
        return json.loads(REGISTRY.read_text())
    return {}


def registry_save(reg):
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps(reg, indent=2) + "\n")


def vault_for(name):
    """The vault holds held-out data and the authoritative spend log.
    It lives outside every campaign workspace on purpose."""
    entry = registry().get(name)
    if not entry:
        die(f"campaign '{name}' not in {REGISTRY}; was it created with sa new?")
    return Path(entry["vault"])


# ---------------------------------------------------------------- ledger

def ledger_path(root):
    return root / "ledger.jsonl"


def ledger_read(root):
    path = ledger_path(root)
    if not path.exists():
        return []
    out = []
    for i, line in enumerate(path.read_text().splitlines()):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            die(f"ledger line {i + 1} is not valid JSON; the ledger is append-only, do not hand-edit it")
    # Union-merged ledgers interleave two holders' appends in arbitrary file
    # order; time order is the real order. Stable sort, records without a ts
    # keep file order at the front.
    out.sort(key=lambda r: (r.get("ts") is not None, r.get("ts") or ""))
    return out


def ledger_state(records, warnings=None):
    """Fold the ledger into current state: hypotheses and attempts with
    their latest status, plus spend counts per split.

    Reading never dies. Two holders can each append a legal verdict and the
    merged sequence can be illegal; the latest record by ts wins and the
    transition is reported through `warnings` (a list the caller passes in).
    Write-time validation is where illegal transitions are actually refused."""
    hyps, atts, spends = {}, {}, {"validation": 0, "holdout": 0}
    warn = warnings if warnings is not None else []
    for r in records:
        t = r.get("type")
        if t == "hypothesis":
            hyps[r["id"]] = {"title": r.get("title", ""), "status": "active", "families": set()}
        elif t == "hypothesis-status":
            h = hyps.get(r.get("id"))
            if h is None:
                warn.append(f"hypothesis-status for unknown hypothesis {r.get('id')}")
                continue
            if r.get("status") not in HYPOTHESIS_TRANSITIONS.get(h["status"], set()):
                warn.append(f"hypothesis {r['id']}: {h['status']} -> {r.get('status')} "
                            f"is not a legal transition (applied anyway, from ts {r.get('ts')})")
            h["status"] = r["status"]
        elif t == "attempt":
            atts[r["id"]] = {"hypothesis": r.get("hypothesis"), "family": r.get("family"),
                             "status": "draft", "branch": r.get("branch")}
            if r.get("hypothesis") in hyps and r.get("family"):
                hyps[r["hypothesis"]]["families"].add(r["family"])
        elif t == "eval":
            a = atts.get(r.get("attempt"))
            if a is not None and a["status"] == "draft":
                a["status"] = "evaluated"
        elif t == "verdict":
            a = atts.get(r.get("attempt"))
            if a is None:
                warn.append(f"verdict for unknown attempt {r.get('attempt')}")
                continue
            if r.get("status") not in ATTEMPT_TRANSITIONS.get(a["status"], set()):
                warn.append(f"attempt {r['attempt']}: {a['status']} -> {r.get('status')} "
                            f"is not a legal transition (applied anyway, from ts {r.get('ts')})")
            a["status"] = r["status"]
        elif t == "spend":
            spends[r["split"]] = spends.get(r["split"], 0) + 1
    return hyps, atts, spends


def next_id(records, kind, root=None):
    """Mint the next id of `kind` ("H", "A", "L") for the caller's holder.

    Counts only ids carrying this holder's prefix, so two clones minting at the
    same time never collide. Legacy unprefixed ids (H1, A7) are left alone."""
    prefix = f"{holder(root)}-{kind}"
    n = 0
    for r in records:
        rid = r.get("id", "")
        if rid.startswith(prefix) and rid[len(prefix):].isdigit():
            n = max(n, int(rid[len(prefix):]))
    return f"{prefix}{n + 1}"


def validate_record(root, rec, records):
    t = rec.get("type")
    if t not in RECORD_TYPES:
        die(f"unknown record type '{t}' (one of {sorted(RECORD_TYPES)})")
    hyps, atts, _ = ledger_state(records)
    from_gate = os.environ.get("SA_FROM_GATE") == "1"
    human = os.environ.get("SA_HUMAN") == "1"

    if t == "hypothesis":
        rec.setdefault("id", next_id(records, "H", root))
        if not rec.get("title"):
            die("hypothesis needs a title")

    elif t == "hypothesis-status":
        status = rec.get("status")
        if status is None or "fals" in str(status).lower():
            die("a hypothesis has no falsified state: attempts die, hypotheses "
                "are supported, shelved, or active. See DESIGN.md.")
        cur = hyps.get(rec.get("id"), {}).get("status")
        if rec.get("id") not in hyps:
            die(f"unknown hypothesis {rec.get('id')}")
        if status not in HYPOTHESIS_TRANSITIONS.get(cur, set()):
            die(f"hypothesis {rec['id']}: {cur} -> {status} is not a legal transition")
        if status == "shelved":
            cfg = load_campaign(root)
            need = cfg.get("budget", {}).get("shelve_families", 3)
            failed_fams = {a["family"] for a in atts.values()
                           if a["hypothesis"] == rec["id"] and a["status"] == "failed" and a["family"]}
            if not human and len(failed_fams) < need:
                die(f"shelving needs SA_HUMAN=1 or >= {need} distinct failed attempt "
                    f"families (this hypothesis has {len(failed_fams)}). An agent's "
                    "failure to find an implementation is not evidence against the hypothesis.")
            if not rec.get("reopen_when"):
                die("shelving requires reopen_when: what evidence would reopen this hypothesis")

    elif t == "attempt":
        rec.setdefault("id", next_id(records, "A", root))
        if rec.get("hypothesis") not in hyps:
            die(f"attempt must name an existing hypothesis (got {rec.get('hypothesis')})")
        if not rec.get("family"):
            die("attempt needs a family (mechanism label; a new mechanism is a new family + branch)")

    elif t == "verdict":
        att = atts.get(rec.get("attempt"))
        if att is None:
            die(f"unknown attempt {rec.get('attempt')}")
        status = rec.get("status")
        cur = att["status"]
        if status not in ATTEMPT_TRANSITIONS.get(cur, set()):
            die(f"attempt {rec['attempt']}: {cur} -> {status} is not a legal transition")
        if status in GATE_ONLY:
            ref = rec.get("gate_ref")
            want_split = "validation" if status == "validated" else "holdout"
            ok = (ref and (root / ref).is_dir()
                  and f"attempts/{rec['attempt']}/gate/{want_split}-" in str(Path(ref).as_posix()))
            if not ok:
                die(f"'{status}' requires gate_ref pointing at an existing "
                    f"attempts/{rec['attempt']}/gate/{want_split}-look* directory: "
                    "the status means 'survived a counted look', so the look must exist")
        if status in HUMAN_ONLY and not human:
            die("deploying is a human decision: rerun with SA_HUMAN=1")
        if not rec.get("evidence"):
            die("verdict needs evidence (a sentence and a path)")

    elif t == "eval":
        if rec.get("split", "train") != "train" and not from_gate:
            die("only the split gate records non-train evals")

    elif t == "spend":
        if not from_gate:
            die("spend records come from the split gate only")

    return rec


def ledger_append(root, rec, skip_validation=False):
    records = ledger_read(root)
    if not skip_validation:
        rec = validate_record(root, rec, records)
    rec.setdefault("ts", now_iso())
    h = holder(root, required=False)
    if h:
        rec.setdefault("holder", h)
    tick = os.environ.get("SA_TICK")
    if tick:
        rec.setdefault("tick", tick)
    with open(ledger_path(root), "a") as f:
        f.write(json.dumps(rec, separators=(",", ":")) + "\n")
    return rec


# ---------------------------------------------------------------- engine

def engine_bin(cfg):
    """The engine binary path. `campaign.toml` stores it with `~` and may use
    $VARS so the file is portable between machines; SA_ENGINE_BIN overrides."""
    raw = os.environ.get("SA_ENGINE_BIN") or cfg["engine"]["bin"]
    return Path(os.path.expanduser(os.path.expandvars(raw)))


def engine_repo(cfg):
    return engine_bin(cfg).resolve().parents[2]


def engine_head(cfg):
    """Short HEAD of the engine repo, or None when it is not a git checkout."""
    r = subprocess.run(["git", "-C", str(engine_repo(cfg)), "rev-parse", "--short", "HEAD"],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def check_engine_pin(cfg):
    """Refuse to produce numbers against an engine other than the pinned one.

    A campaign compares evals across months; a rebuilt engine with different
    fill semantics makes those comparisons lies. Campaigns created before the
    pin existed have no key and skip the check. Returns the current HEAD."""
    pin = cfg.get("engine", {}).get("commit")
    head = engine_head(cfg)
    if pin and head and head != pin and os.environ.get("SA_ALLOW_ENGINE_DRIFT") != "1":
        die(f"engine drift: campaign.toml pins engine.commit = {pin}, the engine repo "
            f"at {engine_repo(cfg)} is at {head}. Check out the pinned commit and "
            "rebuild, or set SA_ALLOW_ENGINE_DRIFT=1 to accept incomparable numbers.")
    return head


def resolve_fill(cfg, name):
    p = Path(name)
    if p.is_absolute():
        return p
    return engine_repo(cfg) / "config" / "fill" / f"{name}.toml"


def run_engine(cfg, data_dirs, strategy, fill, frm, to, warmup_days, extra=None):
    cmd = [str(engine_bin(cfg)), "replay", "--output", "json",
           "--strategy", str(strategy), "--fill", str(resolve_fill(cfg, fill)),
           "--from", frm, "--to", to, "--warmup-days", str(warmup_days)]
    for d in data_dirs:
        cmd += ["--data-dir", str(d)]
    for tf in cfg["engine"].get("timeframes", []):
        cmd += ["--timeframe", tf]
    cmd += extra or []
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        die(f"engine failed ({' '.join(cmd)}):\n{r.stderr[-2000:]}")
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        die(f"engine did not emit JSON:\n{r.stdout[:500]}")


def summarize_report(rep):
    """Reduce an engine JSON report (single object or a list of per-asset
    objects) to the metrics the ledger and reports care about."""
    reps = rep if isinstance(rep, list) else [rep]
    out = {"trades": 0, "wins": 0, "losses": 0, "r": 0.0, "fees_r": 0.0, "by_asset": {}}
    for x in reps:
        out["trades"] += x.get("opportunities_taken", 0)
        out["wins"] += x.get("wins", 0) if "wins" in x else sum(v.get("win", 0) for v in x.get("by_asset", {}).values())
        out["losses"] += x.get("losses", 0)
        out["r"] += x.get("total_r_pnl", 0.0)
        out["fees_r"] += x.get("total_fees", 0.0)
        for a, v in x.get("by_asset", {}).items():
            cur = out["by_asset"].setdefault(a, {"win": 0, "loss": 0})
            cur["win"] += v.get("win", 0)
            cur["loss"] += v.get("loss", 0)
    out["r"] = round(out["r"], 3)
    out["fees_r"] = round(out["fees_r"], 3)
    return out


# ---------------------------------------------------------------- git

def git(root, *args, check=True):
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        die(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip()


def git_commit_all(root, msg):
    git(root, "add", "-A")
    if git(root, "status", "--porcelain"):
        git(root, "commit", "-q", "-m", msg)
    return git(root, "rev-parse", "--short", "HEAD")


def sha256(path, limit=None):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()[:16]
