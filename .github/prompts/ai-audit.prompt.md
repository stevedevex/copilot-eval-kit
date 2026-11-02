---
name: ai-audit
description: 'Audit all Copilot customizations (instructions, agents, skills, prompts) for project-specific fit and token/AI-credit cost. Read-only; writes one report.'
agent: 'agent'
argument-hint: 'optional focus, e.g. "skills only" or ".github/agents"'
---
# Audit the Copilot AI setup in this repository

You are auditing this repo's AI customizations to answer two questions:

1. **Fit**: do they teach Copilot things that are *specific to this codebase*, *true*, and *relevant to the tasks this team actually does*?
2. **Cost**: how many tokens do they add to each request, and what in them pushes up AI-credit usage?

If the user typed text after the command, treat it as the focus and audit only that.

## Ground rules

- **Read-only.** The only files you may create are under `.github/ai-eval/reports/`. Never edit a customization file. Put proposed changes in the report as diffs.
- **Verify, don't assume.** Any statement in a customization that names a library, version, class, package, path, command, config key or convention must be checked against the repo (`pom.xml`/`build.gradle`, source, CI files such as `.gitlab-ci.yml`). Mark each one ✅ verified, ❌ wrong, or ⚠️ unverifiable.
- **Cite evidence** as `path:line`.
- **Be terse.** Use tables, not prose.
- **Skip the evaluation kit itself**: `.github/ai-eval/**` and `.github/prompts/ai-*.prompt.md`.

## Step 1: Inventory and token footprint

If you can run terminal commands, run this and use its numbers:

```
python3 .github/ai-eval/measure_context.py --repo . --json .github/ai-eval/reports/context.json
```

(On Windows use `python` or `py`.) If you can't run it, estimate tokens as characters ÷ 4.

Make sure every file in these locations is covered (skip any that don't exist):

| Type | Location | When it enters the model's context |
|---|---|---|
| Repo-wide instructions | `.github/copilot-instructions.md`, root `AGENTS.md` | every request |
| Nested agent instructions | `AGENTS.md` in subfolders | when working in that subtree (if enabled) |
| Path instructions | `.github/instructions/**/*.instructions.md` | when the `applyTo` glob matches a file in context (`**` means every request) |
| Skills | `.github/skills/*/SKILL.md` (also `.claude/skills`, `.agents/skills`) | name + description on every request; body when triggered; resource files when read |
| Custom agents | `.github/agents/*.agent.md`, legacy `.github/chatmodes/*.chatmode.md` | while that agent is selected |
| Prompt files | `.github/prompts/*.prompt.md` | when invoked with `/name` |
| Hooks / MCP | `.github/hooks/*.json`, `.vscode/mcp.json` | hooks run on events; MCP tools add tool definitions |

## Step 2: Fit score for each artifact

Score each one from 0 to 2 on every criterion:

| Criterion | 0 | 1 | 2 |
|---|---|---|---|
| Specificity | Generic advice the model already follows ("write clean code", "use meaningful names", "follow SOLID") | Mixed | Rules that only make sense here: our modules, starters, patterns, naming, commands |
| Accuracy | Contains wrong or outdated facts | Some unverifiable | Everything verified against the repo |
| Actionability | Vague | Partial | Concrete: exact commands, paths, short examples, do/don't pairs |
| Scope | Wrong trigger (`applyTo` too broad or matches nothing; skill description vague or overlapping) | OK | Precise |
| Efficiency | Over 50% filler, duplication, or prose that could be a one-line rule | Some | Dense |

The total is out of 10. Also list any **duplicated or contradicting rules across files**, for example two files that state different logging, testing or exception conventions.

Generic advice is the most common waste: it costs tokens on every call and changes nothing. Call it out explicitly.

## Step 3: Coverage of real work

Work out what this team actually does.

- If you can run git:
  - `git log --since="120 days ago" --no-merges --pretty=format:"%s" | head -400`
  - `git log --since="120 days ago" --no-merges --name-only --pretty=format: | sort | uniq -c | sort -rn | head -40`
- Otherwise infer it from module structure, READMEs and CI config.

Group the work into 6–10 recurring **task types**, for example: add a REST endpoint in service X, Mongo repository plus migration/changeset, fix a Sonar or security finding, write a Testcontainers integration test, bump a dependency, change the CI pipeline, update OpenAPI or schema-generated code.

For each task type, give: which customization covers it (file), how well (0–2), and what's missing. Then list every customization that maps to **no** recurring task. Those are dead-weight candidates.

## Step 4: Credit-cost risks

Under usage-based billing, each model call is charged for input, cached and output tokens at the selected model's per-token rate. Agent sessions make many model calls and resend the context on every call.

Flag each of these, with estimated tokens and a fix:

- Always-on context (repo-wide instructions + `applyTo: "**"` instructions + all skill descriptions) above roughly 2,000 tokens.
- Any single instruction or skill body above roughly 3,000 tokens, or skills that tell the agent to read large reference files up front instead of on demand.
- Agents or prompts pinned (`model:`) to a high-cost model for routine work such as tests, docs or small fixes.
- Instructions that cause long loops or big outputs: "run the full build/test suite after every change", "read the whole codebase first", "always explain in detail", verbose required output formats.
- Overlapping skills or agents, which can lead the model to load two.
- Many MCP tools enabled for every agent. Suggest a `tools:` restriction per agent.
- The same content duplicated across files, which you pay for twice.

## Step 5: Report

Write `.github/ai-eval/reports/audit-<YYYY-MM-DD>.md` containing:

1. **Summary** (5 lines max): overall fit score, always-on tokens per request, top 3 problems.
2. **Inventory table**: file | type | tokens | loads when | model pin | fit /10 | verdict (keep / fix / merge / delete).
3. **Verified-claims table**: only the ❌ and ⚠️ rows.
4. **Coverage matrix**: task type × customization.
5. **Cost risks**, with estimated token savings.
6. **Top 10 fixes**, ranked by quality gain and credit saving, each with a concrete diff or replacement text.
7. **Golden-task candidates**: the 5 task types from Step 3 that most need an eval (input for `/ai-eval-build-tasks`).

Then reply in chat with only the Summary and the report path.
