#!/usr/bin/env python3
"""
measure_context.py: token footprint and AI-credit estimate for GitHub Copilot customizations.

Mode 1, footprint (default)
    Inventories the repo's Copilot customization files, counts tokens, separates what
    loads on EVERY request from what loads on demand, flags cost/quality risks, and
    estimates the monthly AI credits caused by the always-on context alone.

        python3 .github/ai-eval/measure_context.py --repo . --model "Claude Sonnet 4.6"

Mode 2, scorecard (--scorecard)
    Fills the empty `credits` column of scorecard.csv from the recorded token counts
    and prints quality versus cost per configuration (baseline vs current vs candidates).

        python3 .github/ai-eval/measure_context.py --scorecard .github/ai-eval/scorecard.csv

Standard library only. If `tiktoken` is installed it is used (o200k_base); otherwise
tokens are estimated as characters / 4 (typically within ~15% for English and code).
Prices come from pricing.csv next to this script; update it from GitHub's
"Models and pricing for GitHub Copilot" page when rates change.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKIP_DIRS = {
    ".git", "node_modules", "target", "build", "dist", "out", ".idea", ".gradle",
    "__pycache__", ".venv", "venv", ".mvn", ".terraform", "coverage", ".next",
}
MAX_FILES = 300_000
NON_SOURCE_EXT = {"", ".md", ".txt", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
                  ".lock", ".jar", ".class", ".pdf", ".zip", ".gz", ".log"}

# Phrases that usually signal generic advice the model already follows (heuristic only).
GENERIC_PATTERNS = [
    r"clean code", r"best practices?", r"meaningful (variable |method |class )?names?",
    r"\bSOLID\b", r"\bDRY\b", r"\bKISS\b", r"readab(le|ility)", r"maintainab(le|ility)",
    r"you are an? (expert|senior|world[- ]class)", r"be concise", r"well[- ]documented",
    r"follow (the )?(coding )?(standards|conventions)", r"write (good|high[- ]quality) code",
    r"handle errors (properly|gracefully)", r"keep (functions|methods) small",
]
LOOP_PATTERNS = [
    r"run (the )?(full|entire|whole) (build|test suite|suite)",
    r"after (every|each) (change|edit|file)", r"read (the )?(entire|whole) (code ?base|repo)",
    r"always explain", r"in (great|full) detail", r"step[- ]by[- ]step explanation",
]


# --------------------------------------------------------------------------- tokens
def make_counter():
    try:
        import tiktoken  # type: ignore
        enc = tiktoken.get_encoding("o200k_base")
        return (lambda s: len(enc.encode(s, disallowed_special=()))), "tiktoken o200k_base"
    except Exception:
        return (lambda s: (len(s) + 3) // 4), "chars/4 estimate"


# --------------------------------------------------------------------- frontmatter
def split_frontmatter(text: str):
    if text.startswith("\ufeff"):
        text = text[1:]
    m = re.match(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(\r?\n|$)", text, re.S)
    if not m:
        return {}, "", text
    return parse_yaml_lite(m.group(1)), m.group(1), text[m.end():]


def parse_yaml_lite(raw: str) -> dict:
    """Enough YAML for Copilot frontmatter: scalars, quoted strings, block scalars, lists."""
    out: dict[str, str] = {}
    cur = None
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$", line)
        if m and not line.startswith((" ", "\t")):
            cur, v = m.group(1), m.group(2).strip()
            out[cur] = "" if v in (">", "|", ">-", "|-", ">+", "|+") else v.strip("'\"")
        elif cur and line.startswith((" ", "\t")):
            s = line.strip()
            if s.startswith("- "):
                s = s[2:].strip().strip("'\"")
                out[cur] = f"{out[cur]}, {s}" if out[cur] else s
            else:
                out[cur] = f"{out[cur]} {s}" if out[cur] else s
    return out


def list_value(v: str) -> list[str]:
    v = (v or "").strip()
    if v.startswith("[") and v.endswith("]"):
        v = v[1:-1]
    return [x.strip().strip("'\"") for x in split_outside_braces(v) if x.strip()]


# ---------------------------------------------------------------------------- globs
def split_outside_braces(s: str) -> list[str]:
    parts, depth, buf = [], 0, ""
    for ch in s:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            parts.append(buf)
            buf = ""
        else:
            buf += ch
    parts.append(buf)
    return parts


def _glob_fragment(pat: str) -> str:
    i, n, out = 0, len(pat), []
    while i < n:
        c = pat[i]
        if c == "*":
            if i + 1 < n and pat[i + 1] == "*":
                if i + 2 < n and pat[i + 2] == "/":
                    out.append("(?:.*/)?")
                    i += 3
                    continue
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "{":
            j = pat.find("}", i)
            if j == -1:
                out.append(re.escape(c))
            else:
                alts = split_outside_braces(pat[i + 1:j])
                out.append("(?:" + "|".join(_glob_fragment(a) for a in alts) + ")")
                i = j + 1
                continue
        elif c == "[":
            j = pat.find("]", i)
            if j == -1:
                out.append(re.escape(c))
            else:
                out.append(pat[i:j + 1])
                i = j + 1
                continue
        else:
            out.append(re.escape(c))
        i += 1
    return "".join(out)


def compile_apply_to(value: str):
    pats = [p.strip().strip("'\"").lstrip("./") for p in split_outside_braces(value or "")]
    pats = [p for p in pats if p]
    return pats, [re.compile("^" + _glob_fragment(p) + "$") for p in pats]


# ------------------------------------------------------------------------ discovery
def walk_repo(repo: Path) -> list[str]:
    files: list[str] = []
    for root, dirs, names in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for n in names:
            rel = Path(root, n).relative_to(repo).as_posix()
            files.append(rel)
            if len(files) >= MAX_FILES:
                return files
    return files


SKILL_RE = re.compile(r"^(?:\.github|\.claude|\.agents)/skills/([^/]+)/(.+)$", re.I)


def classify(rel: str) -> str | None:
    p = rel.lower()
    name = p.rsplit("/", 1)[-1]
    if p.startswith(".github/ai-eval/") or (p.startswith(".github/prompts/") and name.startswith("ai-")):
        return None  # the evaluation kit itself
    if p == ".github/copilot-instructions.md":
        return "repo-instructions"
    if name == "agents.md":
        return "repo-instructions" if "/" not in p else "nested-agents-md"
    if p == "claude.md":
        return "claude-md"
    if p.startswith(".github/instructions/") and name.endswith(".instructions.md"):
        return "path-instructions"
    m = SKILL_RE.match(rel)
    if m:
        return "skill" if m.group(2).lower() == "skill.md" else "skill-resource"
    if p.startswith(".github/agents/") and name.endswith(".agent.md"):
        return "agent"
    if p.startswith(".github/chatmodes/") and name.endswith(".chatmode.md"):
        return "agent"
    if p.startswith(".github/prompts/") and name.endswith(".prompt.md"):
        return "prompt"
    if p.startswith(".github/hooks/") and name.endswith(".json"):
        return "hook"
    if p == ".vscode/mcp.json":
        return "mcp"
    return None


# -------------------------------------------------------------------------- pricing
def norm(s: str) -> str:
    s = re.sub(r"\(.*?\)", "", s or "")
    return re.sub(r"[^a-z0-9.]", "", s.lower())


def load_pricing(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as f:
        lines = [ln for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    table = {}
    for r in csv.DictReader(lines):
        def num(k):
            v = (r.get(k) or "").strip()
            return float(v) if v else None
        table[norm(r["model"])] = {
            "model": r["model"].strip(), "category": (r.get("category") or "").strip(),
            "input": num("input") or 0.0, "cached_input": num("cached_input") or 0.0,
            "cache_write": num("cache_write"), "output": num("output") or 0.0,
        }
    return table


def lookup(pricing: dict, model: str):
    if not model:
        return None
    first = list_value(model)[0] if model.strip().startswith("[") else model
    k = norm(first)
    if k in pricing:
        return pricing[k]
    best = None
    for key, row in pricing.items():  # longest key contained in the given name
        if key and key in k and (best is None or len(key) > len(norm(best["model"]))):
            best = row
    return best


def credits_for(price: dict, inp=0.0, cached=0.0, write=0.0, out=0.0) -> float:
    cw = price["cache_write"] if price["cache_write"] is not None else price["input"]
    usd = (inp * price["input"] + cached * price["cached_input"] + write * cw + out * price["output"]) / 1e6
    return usd * 100.0  # 1 AI credit = $0.01


# ------------------------------------------------------------------------ footprint
def footprint(args) -> int:
    repo = Path(args.repo).resolve()
    count, method = make_counter()
    pricing = load_pricing(Path(args.pricing))
    all_files = walk_repo(repo)

    items, skills = [], defaultdict(lambda: {"discovery": 0, "body": 0, "resources": 0, "files": 0})
    line_index: dict[str, set] = defaultdict(set)
    line_tokens: dict[str, int] = {}

    for rel in all_files:
        kind = classify(rel)
        if not kind:
            continue
        try:
            text = (repo / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fm, fm_raw, body = split_frontmatter(text)
        it = {"path": rel, "kind": kind, "tokens": count(text), "fm": fm, "flags": []}

        if kind in ("skill", "skill-resource"):
            sk = SKILL_RE.match(rel).group(1)
            it["skill"] = sk
            if kind == "skill":
                desc = fm.get("description", "")
                it["discovery"] = count(f"name: {fm.get('name', sk)}\ndescription: {desc}")
                it["body_tokens"] = count(body)
                skills[sk]["discovery"] += it["discovery"]
                skills[sk]["body"] += it["body_tokens"]
                if not desc:
                    it["flags"].append("no description: the skill can't be discovered")
                elif len(desc) < 60:
                    it["flags"].append(f"description only {len(desc)} chars: likely too vague to trigger reliably")
                elif len(desc) > 1024:
                    it["flags"].append("description over 1024 chars (Agent Skills limit)")
                if fm.get("name") and fm["name"] != sk:
                    it["flags"].append(f"name '{fm['name']}' doesn't match folder '{sk}'")
                if it["body_tokens"] > args.big:
                    it["flags"].append(f"body {it['body_tokens']} tokens: move detail into on-demand reference files")
            else:
                skills[sk]["resources"] += it["tokens"]
                if it["tokens"] > 2 * args.big:
                    it["flags"].append("large reference file: make sure SKILL.md says when to read it (and which section)")
            skills[sk]["files"] += 1

        if kind == "path-instructions":
            pats, regs = compile_apply_to(fm.get("applyTo", ""))
            it["applyTo"] = ", ".join(pats) or "(none)"
            if not pats:
                it["flags"].append("no applyTo: only applies when attached manually")
                it["match_files"] = 0
                it["coverage"] = 0.0
            else:
                matches = [f for f in all_files if any(r.match(f) for r in regs)]
                it["match_files"] = len(matches)
                it["coverage"] = len(matches) / max(1, len(all_files))
                it["always"] = any(p in ("**", "**/*") for p in pats) or it["coverage"] >= 0.95
                it["exts"] = sorted({Path(f).suffix.lower() for f in matches})
                if not matches:
                    it["flags"].append("applyTo matches 0 files: never applies (dead)")
                elif it["always"]:
                    it["flags"].append("applies to (almost) every request")

        if kind in ("agent", "prompt"):
            it["model"] = fm.get("model", "")
            it["tools"] = len(list_value(fm.get("tools", ""))) if fm.get("tools") else None
            p = lookup(pricing, it["model"]) if it["model"] else None
            if it["model"] and p and p["category"].lower() == "powerful":
                it["flags"].append(f"pinned to high-cost model '{it['model']}': justify or use a Versatile model")
            if it["model"] and not p:
                it["flags"].append(f"model '{it['model']}' not in pricing.csv")

        if kind in ("repo-instructions", "path-instructions", "skill", "agent") and it["tokens"] > args.big:
            if not any("body" in f for f in it["flags"]):
                it["flags"].append(f"{it['tokens']} tokens: large; split or trim")

        if kind in ("repo-instructions", "path-instructions", "skill", "agent", "prompt", "nested-agents-md"):
            low = body.lower()
            g = sum(len(re.findall(p, low, re.I)) for p in GENERIC_PATTERNS)
            lp = [p for p in LOOP_PATTERNS if re.search(p, low, re.I)]
            if g >= 3:
                it["flags"].append(f"{g} generic-advice phrases (e.g. 'best practices', 'clean code'): likely wasted tokens")
            if lp:
                it["flags"].append("may drive long loops/large output: " + "; ".join(lp))
            for ln in body.splitlines():
                s = re.sub(r"\s+", " ", ln.strip().lower())
                s = re.sub(r"^([-*+]|\d+[.)])\s+", "", s)
                if len(s) >= 40 and not s.startswith(("```", "|---", "---")):
                    h = hashlib.md5(s.encode()).hexdigest()
                    line_index[h].add(rel)
                    line_tokens[h] = count(s)

        if kind == "mcp":
            try:
                cleaned = re.sub(r"(?m)(^|[\s,{\[])//.*$", r"\1", text)  # JSONC comments
                cleaned = re.sub(r",(\s*[}\]])", r"\1", cleaned)            # trailing commas
                cfg = json.loads(cleaned)
                it["servers"] = len((cfg.get("servers") or cfg.get("mcpServers") or {}))
            except Exception:
                it["servers"] = None
        items.append(it)

    dup = [(h, files) for h, files in line_index.items() if len(files) > 1]
    dup_tokens = sum(line_tokens[h] * (len(f) - 1) for h, f in dup)

    # ---- context accounting
    always = [i for i in items if i["kind"] == "repo-instructions" or (i["kind"] == "path-instructions" and i.get("always"))]
    skill_disc = sum(s["discovery"] for s in skills.values())
    always_tokens = sum(i["tokens"] for i in always) + skill_disc

    ext_counts = defaultdict(int)
    for f in all_files:
        e = Path(f).suffix.lower()
        if e not in NON_SOURCE_EXT and not f.startswith(".github/"):
            ext_counts[e] += 1
    top_exts = [e for e, _ in sorted(ext_counts.items(), key=lambda x: -x[1])[:3]]
    per_ext = {}
    for e in top_exts:
        extra = [i for i in items if i["kind"] == "path-instructions" and not i.get("always") and e in i.get("exts", [])]
        per_ext[e] = (sum(i["tokens"] for i in extra), [Path(i["path"]).name for i in extra])

    # ---- print
    W = 78
    print("=" * W)
    print(f"Copilot customization footprint: {repo.name}   (tokens: {method})")
    print("=" * W)
    order = ["repo-instructions", "path-instructions", "skill", "skill-resource", "agent",
             "prompt", "nested-agents-md", "claude-md", "hook", "mcp"]
    loads = {
        "repo-instructions": "every request", "path-instructions": "when applyTo matches",
        "skill": "desc: every request; body: on trigger", "skill-resource": "when the skill reads it",
        "agent": "while agent selected", "prompt": "when /invoked", "nested-agents-md": "in that subtree (if enabled)",
        "claude-md": "only if CLAUDE.md support is on", "hook": "on hook events", "mcp": "tool definitions (agent mode)",
    }
    for kind in order:
        group = sorted((i for i in items if i["kind"] == kind), key=lambda x: -x["tokens"])
        if not group:
            continue
        total = sum(i["tokens"] for i in group)
        print(f"\n[{kind}]  {len(group)} file(s), {total:,} tokens. Loads: {loads[kind]}")
        for i in group:
            extra = ""
            if kind == "path-instructions":
                extra = f"  applyTo={i['applyTo']}  matches {i.get('match_files', 0)} files ({i.get('coverage', 0):.0%})"
            elif kind == "skill":
                extra = f"  discovery={i['discovery']}  body={i['body_tokens']}"
            elif kind in ("agent", "prompt"):
                extra = f"  model={i['model'] or '(picker)'}  tools={'all' if i['tools'] is None else i['tools']}"
            elif kind == "mcp":
                extra = f"  servers={i.get('servers', '?')}"
            print(f"  {i['tokens']:>7,}  {i['path']}{extra}")
            for fl in i["flags"]:
                print(f"           ! {fl}")

    if skills:
        print("\n[skills summary]  discovery tokens are paid on every request; body/resources only when used")
        for sk, s in sorted(skills.items(), key=lambda x: -(x[1]["body"] + x[1]["resources"])):
            print(f"  {sk:<32} discovery={s['discovery']:>4}  body={s['body']:>6,}  resources={s['resources']:>7,}  files={s['files']}")

    print("\n" + "-" * W)
    print(f"ALWAYS-ON context per model call : {always_tokens:,} tokens")
    print(f"   repo-wide + applyTo-'**' files : {always_tokens - skill_disc:,}")
    print(f"   skill descriptions             : {skill_disc:,}")
    for e, (t, names) in per_ext.items():
        print(f"   + when working on {e:<6} files : " + (f"up to +{t:,}  ({', '.join(names)})" if names else "no extra instructions"))
    if dup:
        print(f"Duplicated lines across files     : {len(dup)} lines, ~{dup_tokens:,} tokens paid twice")
    print("-" * W)

    # ---- cost estimate
    price = lookup(pricing, args.model)
    est = {}
    if not price:
        print(f"\n(model '{args.model}' not found in {args.pricing}: skipping credit estimate)")
    else:
        T, C = always_tokens, args.calls
        cw = price["cache_write"] if price["cache_write"] is not None else price["input"]
        per_session = (T * cw + (C - 1) * T * price["cached_input"]) / 1e6 * 100
        per_session_nocache = (C * T * price["input"]) / 1e6 * 100
        per_dev_month = per_session * args.sessions * args.days
        team_month = per_dev_month * args.devs
        est = {"model": price["model"], "per_session": per_session, "per_session_nocache": per_session_nocache,
               "per_dev_month": per_dev_month, "team_month": team_month}
        print(f"\nCost of the ALWAYS-ON context alone on {price['model']} "
              f"(${price['input']}/M in, ${price['cached_input']}/M cached, ${price['output']}/M out)")
        print(f"  assumptions: {C} model calls/session, {args.sessions} sessions/dev/day, {args.days} days, {args.devs} dev(s)")
        print(f"  per agent session : {per_session:.2f} credits with prompt caching   "
              f"({per_session_nocache:.2f} if nothing is cached)")
        print(f"  per dev per month : {per_dev_month:,.0f} credits  = {per_dev_month / args.allowance:.1%} of a "
              f"{args.allowance:,}-credit monthly allowance")
        if args.devs > 1:
            print(f"  team per month    : {team_month:,.0f} credits (~${team_month / 100:,.0f})")
        print("  Note: this is only the customization overhead. Real session cost is dominated by code/tool output")
        print("  read into context and by model choice. Measure that with the golden tasks + Agent Debug panel.")

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps({
            "repo": str(repo), "token_method": method, "always_on_tokens": always_tokens,
            "skill_discovery_tokens": skill_disc, "per_extension": per_ext, "duplicate_lines": len(dup),
            "duplicate_tokens": dup_tokens, "estimate": est,
            "items": [{k: v for k, v in i.items() if k != "fm"} for i in items],
            "skills": skills,
        }, indent=2, default=list), encoding="utf-8")
        print(f"\nJSON written to {args.json}")
    return 0


# ------------------------------------------------------------------------ scorecard
def f2(x) -> float:
    try:
        return float(str(x).strip() or 0)
    except ValueError:
        return 0.0


def scorecard(args) -> int:
    path = Path(args.scorecard)
    pricing = load_pricing(Path(args.pricing))
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        rows = list(reader)
    if not rows:
        print("scorecard is empty: run some golden tasks and /ai-eval-judge first.")
        return 0

    filled, missing = 0, set()
    for r in rows:
        if (r.get("credits") or "").strip():
            continue
        p = lookup(pricing, r.get("model", ""))
        if not p:
            missing.add(r.get("model", "?"))
            continue
        r["credits"] = f"{credits_for(p, f2(r.get('input_tokens')), f2(r.get('cached_tokens')), f2(r.get('cache_write_tokens')), f2(r.get('output_tokens'))):.2f}"
        filled += 1
    if filled and not args.dry_run:
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
    if missing:
        print(f"! models not in pricing.csv (credits left empty): {', '.join(sorted(missing))}")
    print(f"credits computed for {filled} row(s){' (dry run, not saved)' if args.dry_run else ''}\n")

    by = defaultdict(list)
    for r in rows:
        by[r.get("config", "?")].append(r)

    def stats(rs):
        n = len(rs)
        passes = sum(1 for r in rs if str(r.get("pass", "")).strip().upper() in ("Y", "YES", "TRUE", "1"))
        priced = [f2(r.get("credits")) for r in rs if (r.get("credits") or "").strip()]
        avg_cred = sum(priced) / len(priced) if priced else 0.0
        return {
            "runs": n, "passes": passes, "pass_rate": passes / n if n else 0,
            "score": sum(f2(r.get("score_total")) for r in rs) / n if n else 0,
            "credits": avg_cred, "cpp": (avg_cred * n / passes) if passes else float("inf"),
            "followups": sum(f2(r.get("followups")) for r in rs) / n if n else 0,
            "fix_min": sum(f2(r.get("fix_minutes")) for r in rs) / n if n else 0,
            "calls": sum(f2(r.get("model_calls")) for r in rs) / n if n else 0,
        }

    S = {c: stats(rs) for c, rs in by.items()}
    hdr = f"{'config':<16}{'runs':>5}{'pass%':>7}{'score/10':>9}{'credits/run':>12}{'credits/pass':>13}{'follow-ups':>11}{'fix min':>8}{'calls':>7}"
    print(hdr)
    print("-" * len(hdr))
    for c, s in sorted(S.items()):
        cpp = "n/a" if s["cpp"] == float("inf") else f"{s['cpp']:.1f}"
        print(f"{c:<16}{s['runs']:>5}{s['pass_rate']:>7.0%}{s['score']:>9.1f}{s['credits']:>12.1f}{cpp:>13}"
              f"{s['followups']:>11.1f}{s['fix_min']:>8.1f}{s['calls']:>7.1f}")

    # per-task matrix
    tasks = sorted({r.get("task_id", "?") for r in rows})
    cfgs = sorted(S)
    print("\nPass matrix (passes/runs)")
    print(f"{'task':<8}" + "".join(f"{c:>14}" for c in cfgs))
    for t in tasks:
        cells = []
        for c in cfgs:
            rs = [r for r in by[c] if r.get("task_id") == t]
            p = sum(1 for r in rs if str(r.get("pass", "")).strip().upper() in ("Y", "YES", "TRUE", "1"))
            cells.append(f"{p}/{len(rs)}" if rs else "-")
        print(f"{t:<8}" + "".join(f"{x:>14}" for x in cells))

    base = S.get(args.baseline)
    if base:
        print(f"\nUplift vs '{args.baseline}'")
        base_tasks = {r.get("task_id") for r in by[args.baseline]}
        for c in sorted(S):
            if c == args.baseline:
                continue
            common = base_tasks & {r.get("task_id") for r in by[c]}
            if not common:
                print(f"  {c:<16} no tasks in common with baseline: run the same tasks to compare")
                continue
            s = stats([r for r in by[c] if r.get("task_id") in common])
            b = stats([r for r in by[args.baseline] if r.get("task_id") in common])
            base = b
            dp = (s["pass_rate"] - base["pass_rate"]) * 100
            ds = s["score"] - base["score"]
            dc = s["credits"] - base["credits"]
            bc = base["credits"] or 1e-9
            if dp >= 15 and dc <= bc * 0.3:
                verdict = "clearly better, and worth the credits"
            elif dp >= 5:
                verdict = "better; check credits/pass before rolling out"
            elif dp > -5:
                if dc < -0.2 * bc:
                    verdict = "same quality, cheaper: prefer this"
                elif dc > 0.2 * bc:
                    verdict = "no quality gain but costs more: trim or rework"
                else:
                    verdict = "no real quality gain: the customizations aren't earning their tokens"
            else:
                verdict = "WORSE than baseline: find the misleading rule or model"
            print(f"  {c:<16} pass {dp:+.0f} pts | score {ds:+.1f} | credits/run {dc:+.1f}  "
                  f"(on {len(common)} common task(s))  ->  {verdict}")
        if min(s["runs"] for s in S.values()) < 3 * len(tasks):
            print("  (fewer than 3 runs per task per config: treat differences under ~15 pts as noise)")
    return 0


# ----------------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".", help="repository root (default: .)")
    ap.add_argument("--pricing", default=str(HERE / "pricing.csv"), help="pricing table CSV")
    ap.add_argument("--model", default="Claude Sonnet 4.6", help="model for the credit estimate")
    ap.add_argument("--calls", type=int, default=12, help="model calls per agent session (default 12)")
    ap.add_argument("--sessions", type=int, default=8, help="agent sessions per dev per day (default 8)")
    ap.add_argument("--days", type=int, default=21, help="working days per month (default 21)")
    ap.add_argument("--devs", type=int, default=1, help="developers using this repo (default 1)")
    ap.add_argument("--allowance", type=int, default=3900, help="monthly credits per user (Enterprise 3900, Business 1900)")
    ap.add_argument("--big", type=int, default=3000, help="token size that counts as 'large' (default 3000)")
    ap.add_argument("--json", help="also write results as JSON to this path")
    ap.add_argument("--scorecard", help="scorecard CSV: compute credits and summarise")
    ap.add_argument("--baseline", default="baseline", help="config label to compare against (default: baseline)")
    ap.add_argument("--dry-run", action="store_true", help="scorecard mode: don't write credits back")
    args = ap.parse_args()
    return scorecard(args) if args.scorecard else footprint(args)


if __name__ == "__main__":
    sys.exit(main())
